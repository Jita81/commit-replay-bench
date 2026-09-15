"""``/settings/secrets`` — the Claude Code login token through the admin API.

RBAC matrix, CSRF, shape validation, the secrets-file contract (owner-only, never
a value in a response or log), the verify probe against a fake ``claude`` on PATH,
and the verify rate limit. Hermetic: no network, no real CLI.

Navigation
----------
What it is:   ``/settings/secrets``'s test suite — the Claude Code login token through the admin
              API.
What it does: Pins that every route is 401 anonymous and admin-only, that CSRF is required on
              every mutating route, that PUT stores owner-only and answers with a status never
              the value (shape validated, never echoed), that DELETE is idempotent, that an
              insecure directory refuses the store with 409, that ``CRB_SECRETS_DIR`` relocates
              the store; and that verify is 404 without a token, runs the fake CLI with the
              stored token in the builder's environment, reports an invalid token fast (not
              after the CLI's retries), handles a missing CLI, is rate-limited to one per ten
              seconds, and refuses an insecure file.
How:          A fake ``claude`` first on PATH that records what it was run with; a temp
              ``CRB_HOME``; ambient ``CRB_*`` cleared.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/routes/admin.py (under test), src/crb/server/secrets.py (the
              wrapper and rate limiter), src/crb/core/secrets_file.py (the owner-only store),
              tests/test_server_secrets.py (the store's own suite), docs/API.md (admin, the
              ``/settings/secrets`` contract), docs/SECURITY.md (credentials, §3.3)
Tested by:    tests/test_server_routes_admin_secrets.py
Touch when:   a secret name is added (a shape-validation case and a never-echoed case); the
              verify probe changes what it runs.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from crb.server.app import API_PREFIX, create_app
from crb.server.secrets import VerifyRateLimiter
from crb.server.settings import Settings

ROOT_PW = "correct-horse-battery-staple"
USER_PW = "long-enough-password"
GOOD = "sk-ant-oat01-" + "G" * 70 + "-GOOD"
BAD = "sk-ant-oat01-" + "B" * 70 + "-XBAD"
NAME = "claude_code_oauth_token"
PATH_ = f"{API_PREFIX}/settings/secrets/claude-code-token"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_") or key in {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"}:
            monkeypatch.delenv(key, raising=False)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Dev ``Settings`` on ``tmp_path`` (the secrets directory resolves under its home)."""
    base: dict[str, Any] = {
        "env": "dev",
        "home": tmp_path / "home",
        "secret_key": SecretStr("s" * 40),
        "sandbox": {"executor": "local"},
        "bootstrap_admin": {"username": "root", "password": ROOT_PW},
        "log_format": "text",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Default dev settings for one test."""
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A started app behind a ``TestClient``."""
    with TestClient(create_app(settings)) as c:
        yield c


def login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> str:
    """Log ``c`` in as ``username`` and set the CSRF header."""
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    token = c.cookies["crb_csrf"]
    c.headers["X-CSRF-Token"] = token
    return token


def _envelope(r: Any) -> dict[str, Any]:
    body = r.json()
    assert set(body) == {"error"}
    return dict(body["error"])


FAKE_CLAUDE = """#!/bin/sh
# A stand-in for the claude CLI: records what it was given, then answers by the token.
REC="{record}"
printf '%s\\n' "$@" > "$REC.argv"
env > "$REC.env"
case "$1" in
  --version) echo "9.9.9 (fake)"; exit 0;;
  auth) echo '{{"loggedIn": true, "authMethod": "claude.ai", "email": "op@example.org"}}'; exit 0;;
esac
case "$CLAUDE_CODE_OAUTH_TOKEN" in
  *GOOD)
    echo '{{"type":"system","subtype":"init","model":"claude-haiku-4-5","tools":[]}}'
    echo '{{"type":"assistant","message":{{"content":[{{"type":"text","text":"pong"}}],"usage":{{"input_tokens":5,"output_tokens":1}}}}}}'
    echo '{{"type":"result","subtype":"success","is_error":false,"result":"pong","num_turns":1,"total_cost_usd":0}}'
    exit 0;;
  *HANG) sleep 30; exit 0;;
  *)
    echo '{{"type":"system","subtype":"init","model":"claude-haiku-4-5","tools":[]}}'
    echo '{{"type":"system","subtype":"api_retry","attempt":1,"max_retries":10,"error_status":401,"error":"authentication_failed"}}'
    sleep 30; exit 1;;
esac
"""


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ``claude`` first on PATH; returns the record prefix it writes to."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    record = tmp_path / "record"
    script = bindir / "claude"
    script.write_text(FAKE_CLAUDE.format(record=record))
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    return record


# ---------------------------------------------------------------------------
# RBAC + CSRF
# ---------------------------------------------------------------------------


class TestAccess:
    def test_unauthenticated_is_401_everywhere(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/settings/secrets").status_code == 401
        assert client.put(PATH_, json={"token": GOOD}).status_code == 401
        assert client.delete(PATH_).status_code == 401
        assert client.post(PATH_ + "/verify").status_code == 401

    def test_rbac_matrix_admin_only(self, client: TestClient, fake_claude: Path) -> None:
        login(client)
        for name, role in (("viewer1", "viewer"), ("op1", "operator"), ("appr1", "approver")):
            r = client.post(
                f"{API_PREFIX}/users", json={"username": name, "password": USER_PW, "role": role}
            )
            assert r.status_code == 201, r.text
        for username in ("viewer1", "op1", "appr1"):
            login(client, username, USER_PW)
            # status is readable by every role (non-secret by construction) …
            r = client.get(f"{API_PREFIX}/settings/secrets")
            assert r.status_code == 200, (username, r.text)
            assert r.json()["items"][0]["present"] is False
            assert r.json()["secrets_dir"] == ""  # … but the host path is admin-only
            for method, path, kw in (
                ("PUT", PATH_, {"json": {"token": GOOD}}),
                ("DELETE", PATH_, {}),
                ("POST", PATH_ + "/verify", {}),
            ):
                r = client.request(method, path, **kw)
                assert r.status_code == 403, (username, method, r.text)
                assert _envelope(r)["code"] == "forbidden"
        login(client)
        r = client.get(f"{API_PREFIX}/settings/secrets")
        assert r.status_code == 200 and r.json()["secrets_dir"].endswith("/secrets")
        assert client.put(PATH_, json={"token": GOOD}).status_code == 200
        assert client.post(PATH_ + "/verify").status_code == 200
        assert client.delete(PATH_).status_code == 200
        # the non-admin roles never got a file written
        assert (client.app.state.settings.home / "secrets" / NAME).exists() is False

    def test_csrf_required_on_every_mutating_route(self, client: TestClient) -> None:
        login(client)
        del client.headers["X-CSRF-Token"]
        for method, path, kw in (
            ("PUT", PATH_, {"json": {"token": GOOD}}),
            ("DELETE", PATH_, {}),
            ("POST", PATH_ + "/verify", {}),
        ):
            r = client.request(method, path, **kw)
            assert r.status_code == 403, (method, r.text)
            assert _envelope(r)["code"] == "csrf_failed"
        assert client.get(f"{API_PREFIX}/settings/secrets").status_code == 200


# ---------------------------------------------------------------------------
# store / status / delete
# ---------------------------------------------------------------------------


class TestStore:
    def test_put_stores_owner_only_and_answers_with_status_never_value(
        self, client: TestClient, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        login(client)
        r = client.get(f"{API_PREFIX}/settings/secrets")
        assert r.json() == {
            "items": [
                {"name": NAME, "present": False, "fingerprint": "", "set_at": "", "set_by": ""}
            ],
            "secrets_dir": str(settings.home / "secrets"),
        }
        with caplog.at_level(logging.INFO):
            r = client.put(PATH_, json={"token": f" {GOOD}\n"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["present"] is True and body["fingerprint"] == "GOOD"
        assert body["set_by"] == "root" and body["set_at"].endswith("+00:00")
        assert GOOD not in r.text and GOOD[:-4] not in r.text
        d = settings.home / "secrets"
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
        assert stat.S_IMODE((d / NAME).stat().st_mode) == 0o600
        assert (d / NAME).read_text() == GOOD
        # nothing logged carries the value
        for rec in caplog.records:
            assert GOOD not in rec.getMessage() and GOOD not in json.dumps(
                rec.__dict__, default=str
            )
        r = client.get(f"{API_PREFIX}/settings/secrets")
        item = r.json()["items"][0]
        assert item["present"] and item["fingerprint"] == "GOOD" and item["set_by"] == "root"
        assert GOOD not in r.text
        # the value is never in /settings either
        assert GOOD not in client.get(f"{API_PREFIX}/settings").text

    def test_put_validates_shape_and_never_echoes(self, client: TestClient) -> None:
        login(client)
        for bad, code in (
            ("", 422),
            ("sk-ant-api03-" + "x" * 60, 422),
            ("sk-ant-oat01-tiny", 422),
            ("sk-ant-oat01-" + "x" * 30 + " " + "y" * 30, 422),
            ("sk-ant-oat01-" + "x" * 600, 422),
        ):
            r = client.put(PATH_, json={"token": bad})
            assert r.status_code == code, (bad[:20], r.text)
            if len(bad) > 30:
                assert bad[13:40] not in r.text
        assert client.put(PATH_, json={}).status_code == 422
        assert not (client.app.state.settings.home / "secrets" / NAME).exists()

    def test_delete_removes_and_is_idempotent(self, client: TestClient, settings: Settings) -> None:
        login(client)
        assert client.put(PATH_, json={"token": GOOD}).status_code == 200
        r = client.delete(PATH_)
        assert r.status_code == 200 and r.json()["present"] is False
        assert not (settings.home / "secrets" / NAME).exists()
        assert not (settings.home / "secrets" / f"{NAME}.meta.json").exists()
        assert client.delete(PATH_).status_code == 200

    def test_insecure_dir_refuses_store_with_409(
        self, client: TestClient, settings: Settings
    ) -> None:
        login(client)
        d = settings.home / "secrets"
        d.mkdir(parents=True)
        os.chmod(d, 0o755)
        r = client.put(PATH_, json={"token": GOOD})
        assert r.status_code == 409, r.text
        e = _envelope(r)
        assert e["code"] == "secrets_insecure" and "chmod 0700" in e["message"]
        assert GOOD not in r.text
        assert not (d / NAME).exists()

    def test_crb_secrets_dir_env_relocates_the_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kv = tmp_path / "kv"
        monkeypatch.setenv("CRB_SECRETS_DIR", str(kv))
        with TestClient(create_app(make_settings(tmp_path))) as c:
            login(c)
            assert c.put(PATH_, json={"token": GOOD}).status_code == 200
            assert (kv / NAME).read_text() == GOOD
            assert c.get(f"{API_PREFIX}/settings/secrets").json()["secrets_dir"] == str(kv)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


class TestVerify:
    def test_no_token_is_404(self, client: TestClient, fake_claude: Path) -> None:
        login(client)
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 404 and _envelope(r)["code"] == "not_found"

    def test_verify_runs_the_fake_cli_with_the_stored_token_in_the_builder_env(
        self, client: TestClient, fake_claude: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOME_OTHER_SECRET", "must-not-leak")
        login(client)
        assert client.put(PATH_, json={"token": GOOD}).status_code == 200
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok" and body["detail"] == "pong"
        assert body["source"] == "explicit" and body["fingerprint"] == "GOOD"
        assert body["model"] == "claude-haiku-4-5" and body["cli_version"] == "9.9.9 (fake)"
        assert body["cost_usd"] == 0 and body["duration_s"] >= 0
        assert GOOD not in r.text
        # exactly the builder's cli-mode environment: the token, nothing else from the shell
        env = dict(
            line.split("=", 1)
            for line in Path(f"{fake_claude}.env").read_text().splitlines()
            if "=" in line
        )
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == GOOD
        assert "SOME_OTHER_SECRET" not in env and "ANTHROPIC_API_KEY" not in env
        assert env["CI"] == "1" and env["NO_COLOR"] == "1" and "PATH" in env and "HOME" in env
        argv = Path(f"{fake_claude}.argv").read_text().splitlines()
        assert argv[:2] == ["-p", "Reply with the single word: pong"]
        assert "--output-format" in argv and "stream-json" in argv
        assert argv[argv.index("--tools") + 1] == ""  # no tools
        assert argv[argv.index("--max-turns") + 1] == "1"
        assert argv[argv.index("--setting-sources") + 1] == "user"
        assert "--bare" not in argv and "--no-session-persistence" in argv

    def test_invalid_token_is_reported_fast_not_after_the_cli_retries(
        self, client: TestClient, fake_claude: Path
    ) -> None:
        login(client)
        assert client.put(PATH_, json={"token": BAD}).status_code == 200
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "invalid"
        assert body["detail"] == "authentication failed (HTTP 401)"
        assert body["duration_s"] < 20  # the fake sleeps 30 s after the retry event: we killed it
        assert BAD not in r.text

    def test_cli_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        empty = tmp_path / "emptybin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        login(client)
        assert client.put(PATH_, json={"token": GOOD}).status_code == 200
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 200
        assert r.json()["status"] == "cli_missing"

    def test_rate_limited_one_per_ten_seconds(self, client: TestClient, fake_claude: Path) -> None:
        now = [1000.0]
        client.app.state.verify_limiter = VerifyRateLimiter(clock=lambda: now[0])
        login(client)
        assert client.put(PATH_, json={"token": GOOD}).status_code == 200
        assert client.post(PATH_ + "/verify").status_code == 200
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 429, r.text
        e = _envelope(r)
        assert e["code"] == "rate_limited" and e["detail"] == {"retry_after_s": 10}
        assert r.headers["Retry-After"] == "10"
        now[0] = 1004.0
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 429 and r.headers["Retry-After"] == "6"
        now[0] = 1010.0
        assert client.post(PATH_ + "/verify").status_code == 200
        assert client.post(PATH_ + "/verify").status_code == 429

    def test_insecure_file_refuses_verify(
        self, client: TestClient, settings: Settings, fake_claude: Path
    ) -> None:
        login(client)
        assert client.put(PATH_, json={"token": GOOD}).status_code == 200
        os.chmod(settings.home / "secrets" / NAME, 0o644)
        r = client.post(PATH_ + "/verify")
        assert r.status_code == 409 and _envelope(r)["code"] == "secrets_insecure"
        # and the status list reports it as absent rather than leak anything
        items = client.get(f"{API_PREFIX}/settings/secrets").json()["items"]
        assert items[0]["present"] is False
