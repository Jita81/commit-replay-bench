"""Secrets at rest: ``crb.core.secrets_file`` (the owner-only store) and
``crb.server.secrets`` (the admin wrapper, shape validation, verify rate limit).

Every test here is hermetic (tmp_path, no network, no real ``claude``).

Navigation
----------
What it is:   The secrets-at-rest test suite — ``crb.core.secrets_file`` (the owner-only store)
              and ``crb.server.secrets`` (the admin wrapper, shape validation, verify rate limit).
What it does: Pins directory resolution precedence, that a fingerprint is at most four trailing
              characters (empty for short values), the closed name alphabet, that ``set`` creates
              a 0700 directory and 0600 files atomically (no partial file on failure; concurrent
              writers never tear), that a group- or world-readable directory or value is refused,
              that an operator-mounted raw file without metadata is readable (CSI / Key Vault),
              that ``repr`` and status never carry the value; token shape validation without
              echoing; and the wrapper's dir resolution, set-validates-then-stores logging only
              the fingerprint, unknown names refused, insecure files reported absent with the
              reason, verify running the builder's probe, and the deployment-wide one-per-interval
              rate limiter with a single winner under threads.
How:          Everything under ``tmp_path`` with real ``chmod``; no network, no real ``claude``.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/core/secrets_file.py and src/crb/server/secrets.py (under test),
              src/crb/builders/claude_code.py (the probe verify runs),
              tests/test_server_routes_admin_secrets.py (the same store behind the API),
              docs/SECURITY.md (credentials, §3.3), docs/DEPLOYMENT.md (Key Vault → environment)
Tested by:    tests/test_server_secrets.py
Touch when:   a secret name is added to the alphabet (a shape case); the file-mode rules change
              (never looser than owner-only).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
from pathlib import Path
from typing import Any

import pytest

from crb.core import secrets_file as sf
from crb.core.secrets_file import (
    FINGERPRINT_CHARS,
    SecretsInsecure,
    SecretsNameError,
    SecretsStore,
    fingerprint,
    resolve_secrets_dir,
)
from crb.server import secrets as srv
from crb.server.secrets import (
    SecretsFile,
    VerifyRateLimiter,
    secrets_dir_for,
    validate_claude_code_token,
)
from crb.server.settings import Settings

TOKEN = "sk-ant-oat01-" + "Q" * 60 + "-" + "z" * 20 + "WXYZ"
NAME = "claude_code_oauth_token"


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


# ---------------------------------------------------------------------------
# resolution + fingerprint + names
# ---------------------------------------------------------------------------


def test_resolve_secrets_dir_precedence() -> None:
    assert resolve_secrets_dir({}) == Path(".crb") / "secrets"
    assert resolve_secrets_dir({"CRB_HOME": "/srv/crb"}) == Path("/srv/crb/secrets")
    assert resolve_secrets_dir({"CRB_HOME": "/srv/crb", "CRB_SECRETS_DIR": "/mnt/kv"}) == Path(
        "/mnt/kv"
    )
    assert resolve_secrets_dir({"CRB_SECRETS_DIR": "  "}) == Path(".crb") / "secrets"


def test_fingerprint_is_at_most_four_trailing_chars_and_empty_for_short_values() -> None:
    assert fingerprint(TOKEN) == "WXYZ"
    assert len(fingerprint(TOKEN)) == FINGERPRINT_CHARS == 4
    assert fingerprint("short") == ""  # a fingerprint of a short value is the value
    assert fingerprint("x" * 11) == ""
    assert fingerprint("x" * 12) == "xxxx"


@pytest.mark.parametrize("bad", ["", "../etc", "Claude", "a b", "a/b", "x" * 65, ".hidden"])
def test_names_are_a_closed_alphabet(tmp_path: Path, bad: str) -> None:
    store = SecretsStore(tmp_path / "s")
    with pytest.raises(SecretsNameError):
        store.value_path(bad)
    with pytest.raises(SecretsNameError):
        store.set(bad, TOKEN)


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------


class TestSecretsStore:
    def test_set_creates_0700_dir_and_0600_files_atomically(self, tmp_path: Path) -> None:
        d = tmp_path / "home" / "secrets"
        store = SecretsStore(d)
        assert store.get(NAME) is None and not store.status(NAME).present
        status = store.set(NAME, TOKEN, set_by="root")
        assert _mode(d) == 0o700
        assert _mode(d / NAME) == 0o600
        assert _mode(d / f"{NAME}.meta.json") == 0o600
        assert (d / NAME).read_text() == TOKEN  # the raw value, nothing else
        meta = json.loads((d / f"{NAME}.meta.json").read_text())
        assert meta["set_by"] == "root" and meta["name"] == NAME and "value" not in meta
        assert TOKEN not in json.dumps(meta)
        assert status.present and status.fingerprint == "WXYZ" and status.set_by == "root"
        assert status.set_at.endswith("+00:00")
        # no temp files left behind
        assert sorted(p.name for p in d.iterdir()) == [NAME, f"{NAME}.meta.json"]
        assert store.get(NAME) == TOKEN

    def test_set_replaces_and_delete_removes_both_files(self, tmp_path: Path) -> None:
        store = SecretsStore(tmp_path / "s")
        store.set(NAME, TOKEN)
        store.set(NAME, TOKEN[:-4] + "ABCD", set_by="ops")
        assert store.get(NAME) == TOKEN[:-4] + "ABCD"
        assert store.status(NAME).fingerprint == "ABCD"
        assert store.delete(NAME) is True
        assert not list((tmp_path / "s").iterdir())
        assert store.delete(NAME) is False
        assert not store.status(NAME).present

    def test_value_is_stripped_and_empty_or_multiline_refused(self, tmp_path: Path) -> None:
        store = SecretsStore(tmp_path / "s")
        store.set(NAME, f"  {TOKEN}\n")
        assert store.get(NAME) == TOKEN
        with pytest.raises(ValueError, match="empty"):
            store.set(NAME, "   ")
        with pytest.raises(ValueError, match="line breaks"):
            store.set(NAME, "abc\ndef" + "x" * 20)

    def test_refuses_to_store_into_group_or_world_readable_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "s"
        d.mkdir(mode=0o750)
        os.chmod(d, 0o750)
        store = SecretsStore(d)
        with pytest.raises(SecretsInsecure, match="group/world accessible"):
            store.set(NAME, TOKEN)
        assert not (d / NAME).exists()
        os.chmod(d, 0o701)
        with pytest.raises(SecretsInsecure):
            store.set(NAME, TOKEN)
        os.chmod(d, 0o700)
        store.set(NAME, TOKEN)  # fixed by the operator → accepted; never chmod'd by us
        os.chmod(d, 0o755)
        with pytest.raises(SecretsInsecure):
            store.delete(NAME)

    def test_refuses_to_read_a_group_or_world_readable_value(self, tmp_path: Path) -> None:
        store = SecretsStore(tmp_path / "s")
        store.set(NAME, TOKEN)
        os.chmod(tmp_path / "s" / NAME, 0o640)
        with pytest.raises(SecretsInsecure, match="group/world readable"):
            store.get(NAME)
        with pytest.raises(SecretsInsecure):
            store.status(NAME)
        os.chmod(tmp_path / "s" / NAME, 0o600)
        assert store.get(NAME) == TOKEN

    def test_refuses_a_non_regular_value(self, tmp_path: Path) -> None:
        d = tmp_path / "s"
        d.mkdir(mode=0o700)
        (d / NAME).mkdir(mode=0o700)
        with pytest.raises(SecretsInsecure, match="not a regular file"):
            SecretsStore(d).get(NAME)

    def test_operator_mounted_raw_file_without_meta_is_readable(self, tmp_path: Path) -> None:
        """A CSI / Key Vault mount: a raw value file, no ``.meta.json``."""
        d = tmp_path / "mount"
        d.mkdir(mode=0o700)
        (d / NAME).write_text(TOKEN + "\n")
        os.chmod(d / NAME, 0o400)
        store = SecretsStore(d)
        assert store.get(NAME) == TOKEN
        st = store.status(NAME)
        assert st.present and st.fingerprint == "WXYZ" and st.set_by == ""
        assert st.set_at.endswith("+00:00")  # the file's mtime

    def test_empty_file_is_absent(self, tmp_path: Path) -> None:
        d = tmp_path / "s"
        d.mkdir(mode=0o700)
        (d / NAME).write_text("\n")
        os.chmod(d / NAME, 0o600)
        assert SecretsStore(d).get(NAME) is None
        assert not SecretsStore(d).status(NAME).present

    def test_atomic_write_leaves_no_partial_file_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = SecretsStore(tmp_path / "s")
        store.set(NAME, TOKEN)

        def boom(*_a: Any, **_k: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(sf.os, "fsync", boom)
        with pytest.raises(OSError, match="disk full"):
            store.set(NAME, TOKEN[:-4] + "NEW1")
        assert store.get(NAME) == TOKEN  # the old value survived intact
        assert sorted(p.name for p in (tmp_path / "s").iterdir()) == [NAME, f"{NAME}.meta.json"]

    def test_repr_and_status_never_carry_the_value(self, tmp_path: Path) -> None:
        store = SecretsStore(tmp_path / "s")
        st = store.set(NAME, TOKEN)
        for text in (repr(store), str(store), repr(st), str(st), json.dumps(st.to_dict())):
            assert TOKEN not in text
            assert TOKEN[:-4] not in text
        assert st.to_dict() == {
            "name": NAME,
            "present": True,
            "fingerprint": "WXYZ",
            "set_at": st.set_at,
            "set_by": "",
        }

    def test_concurrent_writers_never_tear(self, tmp_path: Path) -> None:
        store = SecretsStore(tmp_path / "s")
        values = [TOKEN[:-4] + f"{i:04d}" for i in range(8)]
        errors: list[BaseException] = []

        def w(v: str) -> None:
            try:
                for _ in range(5):
                    store.set(NAME, v)
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=w, args=(v,)) for v in values]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert store.get(NAME) in values  # one whole value, never a mix


# ---------------------------------------------------------------------------
# the server wrapper
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
    return Settings(env="dev", home=tmp_path / "home", secret_key="s" * 40)


class TestValidateToken:
    def test_accepts_a_setup_token_shape(self) -> None:
        assert validate_claude_code_token(f"  {TOKEN}\n") == TOKEN

    @pytest.mark.parametrize(
        ("bad", "why"),
        [
            ("", "starts with"),
            ("sk-ant-api03-" + "x" * 60, "starts with"),
            ("sk-ant-oat01-short", "too short"),
            ("sk-ant-oat01-" + "x" * 600, "too long"),
            ("sk-ant-oat01-" + "x" * 30 + " " + "y" * 20, "characters outside"),
            ("sk-ant-oat01-" + "x" * 30 + "\n" + "y" * 20, "characters outside"),
        ],
    )
    def test_rejects_wrong_shapes_without_echoing_the_value(self, bad: str, why: str) -> None:
        with pytest.raises(ValueError, match=why) as ei:
            validate_claude_code_token(bad)
        if len(bad) > 20:
            assert bad[13:40] not in str(ei.value)


class TestSecretsFile:
    def test_dir_resolution_prefers_env_then_settings_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CRB_SECRETS_DIR", raising=False)
        s = _settings(tmp_path)
        assert secrets_dir_for(s) == tmp_path / "home" / "secrets"
        monkeypatch.setenv("CRB_SECRETS_DIR", str(tmp_path / "kv"))
        assert secrets_dir_for(s) == tmp_path / "kv"
        assert SecretsFile.for_settings(s).path == tmp_path / "kv"

    def test_set_validates_then_stores_and_logs_only_the_fingerprint(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        f = SecretsFile(tmp_path / "secrets")
        with pytest.raises(ValueError):
            f.set(NAME, "not-a-token")
        assert not (tmp_path / "secrets" / NAME).exists()
        with caplog.at_level(logging.INFO, logger="crb.server.secrets"):
            st = f.set(NAME, TOKEN, set_by="root")
            f.delete(NAME)
        assert st.present and st.fingerprint == "WXYZ"
        assert caplog.records, "set/delete are logged (without the value)"
        for rec in caplog.records:
            dumped = rec.getMessage() + json.dumps(rec.__dict__, default=str)
            assert TOKEN not in dumped and TOKEN[:-4] not in dumped
            assert rec.__dict__.get("fingerprint", "") in ("", "WXYZ")
        assert repr(f) == f"SecretsFile({str(tmp_path / 'secrets')!r})"

    def test_unknown_names_are_refused(self, tmp_path: Path) -> None:
        f = SecretsFile(tmp_path / "secrets")
        with pytest.raises(KeyError, match="unknown secret"):
            f.set("openai_api_key", "sk-" + "x" * 40)
        with pytest.raises(KeyError):
            f.get("openai_api_key")

    def test_statuses_report_an_insecure_file_as_absent_and_log_why(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        f = SecretsFile(tmp_path / "secrets")
        f.set(NAME, TOKEN)
        os.chmod(tmp_path / "secrets" / NAME, 0o644)
        with caplog.at_level(logging.WARNING, logger="crb.server.secrets"):
            [st] = f.statuses()
        assert st.name == NAME and not st.present and st.fingerprint == ""
        assert any("unreadable" in r.getMessage() for r in caplog.records)
        with pytest.raises(SecretsInsecure):
            f.verify(NAME)

    def test_verify_absent_is_none_and_present_runs_the_builder_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = SecretsFile(tmp_path / "secrets")
        assert f.verify(NAME) is None
        f.set(NAME, TOKEN)
        seen: dict[str, Any] = {}

        def fake_verify(**kw: Any) -> Any:
            seen.update(kw)
            from crb.builders.claude_code import LoginCheck

            return LoginCheck("ok", "pong", "explicit", "WXYZ")

        monkeypatch.setattr(srv, "verify_login", fake_verify)
        check = f.verify(NAME, timeout_s=7, binary="/opt/claude")
        assert check is not None and check.status == "ok"
        # the configured CLI binary (CRB_BUILDER__CLAUDE_BINARY) reaches the probe
        assert seen == {"token": TOKEN, "timeout_s": 7, "binary": "/opt/claude"}


class TestVerifyRateLimiter:
    def test_one_per_interval_deployment_wide(self) -> None:
        now = [100.0]
        lim = VerifyRateLimiter(min_interval_s=10.0, clock=lambda: now[0])
        assert lim.acquire() is None
        assert lim.acquire() == pytest.approx(10.0)
        now[0] = 104.0
        assert lim.acquire() == pytest.approx(6.0)
        now[0] = 110.0
        assert lim.acquire() is None
        assert lim.acquire() == pytest.approx(10.0)

    def test_thread_safe_single_winner(self) -> None:
        lim = VerifyRateLimiter(min_interval_s=60.0)
        wins: list[bool] = []

        def go() -> None:
            wins.append(lim.acquire() is None)

        ts = [threading.Thread(target=go) for _ in range(16)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert wins.count(True) == 1
