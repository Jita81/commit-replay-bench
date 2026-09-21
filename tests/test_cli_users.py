"""``crb users list | create | set-password | activate | deactivate`` — the break-glass CLI,
end to end against a temp database the server then reads.

Navigation
----------
What it is:   The test suite for the ``crb users`` verbs.
What it does: Pins that the verbs resolve the same database as ``crb serve`` (an account the
              CLI created logs in through the API; a password the CLI set ends the API session
              issued under the old one), that a password is never taken from argv (prompt or
              ``CRB_USERS_PASSWORD_FILE``; no terminal and no file is a clean exit 2), the
              last-admin guard on ``deactivate``, the ≥ 12 character rule, unknown accounts,
              an uninitialised database, and that every change is one ``user.*`` event with
              actor ``cli:<os user>`` and never a password.
How:          ``crb migrate`` on a temp SQLite URL, ``main(argv)`` in-process with
              ``CRB_DATABASE_URL`` set and the password in a temp file; the API side is
              ``create_app`` over the same URL (no bootstrap admin) behind a ``TestClient``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/cli/commands/users.py (under test), src/crb/server/auth.py (the shared
              primitives), src/crb/server/routes/admin.py (``record_user_event`` and
              ``user_trace_id``), src/crb/store/db.py (``database_url`` resolution),
              docs/OPERATOR.md#9-users
Tested by:    tests/test_cli_users.py
Touch when:   a verb is added; the password source rule changes; the event shape changes.
"""

from __future__ import annotations

import getpass
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from crb.cli.commands.users import PASSWORD_FILE_ENV, actor, read_password
from crb.cli.main import main
from crb.server.app import API_PREFIX, create_app
from crb.server.auth import CSRF_COOKIE
from crb.server.routes.admin import user_trace_id
from crb.server.settings import Settings
from crb.store import make_engine, make_session_factory
from crb.store.models import Event, User

Run = Callable[[Sequence[str]], tuple[int, str, str]]
PW = "correct-horse-battery-staple"
PW2 = "a-brand-new-long-password"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A migrated temp database, exported as ``CRB_DATABASE_URL`` — what ``crb serve`` reads."""
    url = f"sqlite:///{tmp_path / 'crb.db'}"
    assert main(["migrate", "--database-url", url]) == 0
    monkeypatch.setenv("CRB_DATABASE_URL", url)
    return url


@pytest.fixture
def run(db_url: str, capsys: pytest.CaptureFixture[str]) -> Run:
    """``run(argv) -> (exit_code, stdout, stderr)``."""

    def _run(argv: Sequence[str]) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(list(argv))
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


@pytest.fixture
def password_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """``set(pw)`` writes ``pw`` to a temp file and points ``CRB_USERS_PASSWORD_FILE`` at it."""
    path = tmp_path / "pw.txt"

    def _set(pw: str) -> None:
        path.write_text(pw + "\n", encoding="utf-8")
        monkeypatch.setenv(PASSWORD_FILE_ENV, str(path))

    return _set


def events_for(db_url: str, user_id: str) -> list[Event]:
    factory = make_session_factory(make_engine(db_url))
    with factory() as s:
        rows = list(
            s.execute(
                select(Event).where(Event.trace_id == user_trace_id(user_id)).order_by(Event.seq)
            ).scalars()
        )
        s.expunge_all()
        return rows


def user_id(db_url: str, username: str) -> str:
    factory = make_session_factory(make_engine(db_url))
    with factory() as s:
        row = s.execute(select(User).where(User.subject == f"local:{username}")).scalar_one()
        return row.id


def api(tmp_path: Path, db_url: str) -> TestClient:
    """The server over the same database — no bootstrap admin, so every account is the CLI's."""
    settings = Settings(
        env="dev",
        home=tmp_path,
        database_url=db_url,
        secret_key=SecretStr("s" * 40),
        sandbox={"executor": "local"},
        log_format="text",
    )
    return TestClient(create_app(settings))


def login(c: TestClient, username: str, password: str) -> Any:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    if r.status_code == 200:
        c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]
    return r


# --- password source ------------------------------------------------------------------------


class TestPasswordSource:
    def test_no_terminal_and_no_file_is_a_clean_error(self, run: Run) -> None:
        code, _, errtxt = run(["users", "create", "root", "--role", "admin"])
        assert code == 2 and PASSWORD_FILE_ENV in errtxt

    def test_file_is_read_first_line_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "pw"
        path.write_text("first-line-password\r\nsecond line\n", encoding="utf-8")
        monkeypatch.setenv(PASSWORD_FILE_ENV, str(path))
        assert read_password(confirm=True) == "first-line-password"
        path.write_text("\n", encoding="utf-8")
        with pytest.raises(Exception, match="is empty"):
            read_password(confirm=True)
        monkeypatch.setenv(PASSWORD_FILE_ENV, str(tmp_path / "missing"))
        with pytest.raises(Exception, match="cannot read"):
            read_password(confirm=True)

    def test_prompt_confirms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter([PW, PW, PW, "different"])
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        assert read_password(confirm=True) == PW
        with pytest.raises(Exception, match="do not match"):
            read_password(confirm=True)

    def test_password_is_never_an_argument(self) -> None:
        # No verb accepts a password flag: argparse refuses it as an unknown option.
        assert main(["users", "create", "root", "--password", PW]) == 2
        assert main(["users", "set-password", "root", "--password", PW]) == 2

    def test_actor_names_the_os_user(self) -> None:
        assert actor() == f"cli:{getpass.getuser()}"


# --- the verbs, end to end ------------------------------------------------------------------


def test_lifecycle_end_to_end(
    run: Run, db_url: str, tmp_path: Path, password_file: Callable[[str], None]
) -> None:
    # An empty database lists nothing and says what to do.
    code, out, _ = run(["users", "list"])
    assert code == 0 and "no accounts" in out

    # create → the account logs in through the API over the same database.
    password_file(PW)
    code, out, _ = run(["users", "create", "root", "--role", "admin"])
    assert code == 0 and "created root (admin)" in out and PW not in out
    code, _, errtxt = run(["users", "create", "root", "--role", "admin"])
    assert code == 2 and "user_exists" in errtxt
    code, _, errtxt = run(["users", "create", "x y", "--role", "admin"])
    assert code == 2 and "username" in errtxt
    code, _, errtxt = run(["users", "create", "ok", "--role", "god"])
    assert code == 2 and "role" in errtxt
    password_file("short")
    code, _, errtxt = run(["users", "create", "ok"])
    assert code == 2 and "at least 12" in errtxt

    with api(tmp_path, db_url) as c:
        assert login(c, "root", PW).status_code == 200
        assert c.get(f"{API_PREFIX}/users").json()["total"] == 1

        # set-password → the API session issued under the old password ends.
        password_file(PW2)
        code, out, _ = run(["users", "set-password", "root"])
        assert code == 0 and "sessions have ended" in out and PW2 not in out
        r = c.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"
        assert login(c, "root", PW).status_code == 401
        assert login(c, "root", PW2).status_code == 200

        # deactivate the last active admin: refused, nothing written, still signed in.
        code, _, errtxt = run(["users", "deactivate", "root"])
        assert code == 2 and "last_admin" in errtxt
        assert c.get(f"{API_PREFIX}/auth/me").status_code == 200

        # A second admin makes it possible; deactivation ends root's session at once.
        password_file(PW)
        assert run(["users", "create", "admin2", "--role", "admin"])[0] == 0
        code, out, _ = run(["users", "deactivate", "root"])
        assert code == 0 and "deactivated root" in out
        assert c.get(f"{API_PREFIX}/auth/me").status_code == 401
        assert login(c, "root", PW2).status_code == 401
        code, out, _ = run(["users", "deactivate", "root"])
        assert code == 0 and "already deactivated" in out
        code, out, _ = run(["users", "activate", "root"])
        assert code == 0 and "activated root" in out
        assert login(c, "root", PW2).status_code == 200

    code, _, errtxt = run(["users", "set-password", "nobody"])
    assert code == 2 and "no local account 'nobody'" in errtxt
    code, _, errtxt = run(["users", "activate", "nobody"])
    assert code == 2 and "no local account" in errtxt

    # list: text and JSON, never a hash.
    code, out, _ = run(["users", "list"])
    assert code == 0
    lines = [ln for ln in out.splitlines() if ln and not ln.startswith("-")]
    assert lines[0].split()[:4] == ["username", "role", "active", "issuer"]
    assert {ln.split()[0] for ln in lines[1:]} == {"root", "admin2"}
    assert "argon2" not in out
    code, out, _ = run(["users", "list", "--json"])
    rows = {r["username"]: r for r in json.loads(out)}
    assert rows["root"]["role"] == "admin" and rows["root"]["active"] is True
    assert rows["root"]["last_login"] != "" and rows["admin2"]["last_login"] == ""
    assert not any("password_hash" in r for r in rows.values())

    # Every change is one event with the CLI actor and the target; never a password.
    root = user_id(db_url, "root")
    evs = events_for(db_url, root)
    assert [e.action for e in evs] == [
        "user.created",
        "user.password_set",
        "user.deactivated",
        "user.activated",
    ]
    assert [e.seq for e in evs] == [1, 2, 3, 4]
    assert {e.actor for e in evs} == {f"cli:{getpass.getuser()}"}
    assert all(e.stage == "system" for e in evs)
    assert all(e.payload_json["target"] == root for e in evs)
    assert all(e.payload_json["username"] == "root" for e in evs)
    assert evs[1].payload_json["by"] == "cli"
    for e in evs:
        blob = repr(e.payload_json)
        assert PW not in blob and PW2 not in blob and "argon2" not in blob


def test_uninitialised_database_says_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CRB_DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    assert main(["users", "list"]) == 2
    assert "crb migrate" in capsys.readouterr().err


def test_users_without_a_verb_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["users"]) == 2
    assert "set-password" in capsys.readouterr().out
