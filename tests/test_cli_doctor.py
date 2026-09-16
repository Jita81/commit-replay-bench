"""``crb doctor``'s ``claude_code`` probe: the login source (env | secrets file (…xxxx)
| keychain | none), the CLI's presence/version, and ``--verify``. Hermetic: a fake
``claude`` on PATH, a throwaway ``CRB_HOME``, never the operator's login.

Navigation
----------
What it is:   ``crb doctor``'s ``claude_code`` probe test suite — the login source, the CLI's
              presence and ``--verify``.
What it does: Pins that a keychain login is ok, that no login and no key is degraded WITH the
              fix named, that a secrets file shows only its fingerprint, that an environment
              token wins, that an insecure secrets file is down, that a missing CLI is degraded,
              that ``--verify`` runs the probe (ok and invalid), and that ``crb doctor`` reports
              the probe in text and JSON.
How:          A fake ``claude`` on PATH and a throwaway ``CRB_HOME`` — never the operator's login.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/cli/commands/service.py (``probe_claude_code`` under test),
              src/crb/builders/claude_code.py (the token sources it reports),
              src/crb/core/secrets_file.py (the store), tests/test_builders_claude_code.py (the
              same sources at the builder), docs/OPERATOR.md
Tested by:    tests/test_cli_doctor.py
Touch when:   a token source or auth mode is added (a status case naming it); a probe for
              another builder is added (a module beside this one).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from crb.builders import claude_code as cc
from crb.cli.commands.service import probe_claude_code
from crb.cli.main import main
from crb.core.secrets_file import SecretsStore

STORED = "sk-ant-oat01-" + "S" * 70 + "-GOOD"

FAKE = """#!/bin/sh
case "$1" in
  --version) echo "9.9.9 (fake)"; exit 0;;
  auth) echo '{{"loggedIn": {logged_in}, "authMethod": "claude.ai", "email": "op@example.org"}}'; exit 0;;
esac
case "$CLAUDE_CODE_OAUTH_TOKEN" in
  *GOOD)
    echo '{{"type":"system","subtype":"init","model":"claude-haiku-4-5","tools":[]}}'
    echo '{{"type":"result","subtype":"success","is_error":false,"result":"pong","num_turns":1,"total_cost_usd":0}}'
    exit 0;;
  *)
    echo '{{"type":"system","subtype":"api_retry","attempt":1,"error_status":401,"error":"authentication_failed"}}'
    sleep 20; exit 1;;
esac
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway ``CRB_HOME`` with every ``CRB_*`` and credential variable cleared, so the probe
    never sees the operator's login.
    """
    for key in list(os.environ):
        if key.startswith("CRB_") or key in {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"}:
            monkeypatch.delenv(key, raising=False)
    h = tmp_path / "crb-home"
    monkeypatch.setenv("CRB_HOME", str(h))
    return h


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Install a fake ``claude`` first on PATH whose ``auth status`` answers ``logged_in``."""

    def make(logged_in: bool) -> None:
        bindir = tmp_path / "fakebin"
        bindir.mkdir(exist_ok=True)
        script = bindir / "claude"
        script.write_text(FAKE.format(logged_in="true" if logged_in else "false"))
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")

    return make


def test_keychain_login_is_ok(home: Path, fake_cli: Callable[[bool], None]) -> None:
    fake_cli(True)
    r = probe_claude_code()
    assert r.status == "ok"
    assert r.detail == f"auth: keychain · claude 9.9.9 (fake) · secrets dir {home / 'secrets'}"
    assert r.data == {
        "auth": "keychain",
        "fingerprint": "",
        "cli": True,
        "cli_version": "9.9.9 (fake)",
        "secrets_dir": str(home / "secrets"),
        "api_key": False,
    }


def test_no_login_and_no_key_is_degraded_with_the_fix(
    home: Path, fake_cli: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_cli(False)
    r = probe_claude_code()
    assert r.status == "degraded" and r.detail.startswith("auth: none")
    assert "claude setup-token" in r.detail
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-" + "k" * 40)
    r = probe_claude_code()  # api_key mode is a valid production posture
    assert r.status == "ok" and r.data["api_key"] is True and r.data["auth"] == "none"


def test_secrets_file_shows_fingerprint_only(home: Path, fake_cli: Callable[[bool], None]) -> None:
    fake_cli(False)
    SecretsStore(home / "secrets").set(cc.CLI_TOKEN_SECRET, STORED, set_by="root")
    r = probe_claude_code()
    assert r.status == "ok"
    assert r.detail.startswith("auth: secrets file (…GOOD) · claude 9.9.9 (fake)")
    assert r.data["auth"] == "secrets_file" and r.data["fingerprint"] == "GOOD"
    assert STORED not in r.detail and STORED not in json.dumps(r.to_dict())


def test_env_token_wins(
    home: Path, fake_cli: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_cli(False)
    SecretsStore(home / "secrets").set(cc.CLI_TOKEN_SECRET, STORED)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", STORED[:-4] + "ENVV")
    r = probe_claude_code()
    assert r.status == "ok" and r.detail.startswith("auth: env ·")
    assert r.data["fingerprint"] == ""


def test_insecure_secrets_file_is_down(home: Path, fake_cli: Callable[[bool], None]) -> None:
    fake_cli(True)
    SecretsStore(home / "secrets").set(cc.CLI_TOKEN_SECRET, STORED)
    os.chmod(home / "secrets" / cc.CLI_TOKEN_SECRET, 0o644)
    r = probe_claude_code(verify=True)
    assert r.status == "down"
    assert r.detail.startswith("auth: REFUSED · ") and "chmod 0600" in r.detail
    assert "verify" not in r.data  # never probes with a refused token
    assert STORED not in r.detail


def test_cli_missing_is_degraded(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    r = probe_claude_code()
    assert r.status == "degraded"
    assert "claude: not on PATH" in r.detail and r.data["cli"] is False


def test_verify_runs_the_probe_ok_and_invalid(home: Path, fake_cli: Callable[[bool], None]) -> None:
    fake_cli(False)
    store = SecretsStore(home / "secrets")
    store.set(cc.CLI_TOKEN_SECRET, STORED)
    r = probe_claude_code(verify=True)
    assert r.status == "ok" and "· verify: ok (" in r.detail
    assert r.data["verify"]["status"] == "ok" and r.data["verify"]["source"] == "secrets_file"
    assert r.data["verify"]["fingerprint"] == "GOOD"
    store.set(cc.CLI_TOKEN_SECRET, STORED[:-4] + "XBAD")
    r = probe_claude_code(verify=True)
    assert r.status == "degraded" and "verify: invalid" in r.detail
    assert "authentication failed (HTTP 401)" in r.detail
    assert r.data["verify"]["duration_s"] < 15  # killed at the first 401, not after the sleep


def test_crb_doctor_reports_the_probe_in_text_and_json(
    home: Path,
    fake_cli: Callable[[bool], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_cli(True)
    SecretsStore(home / "secrets").set(cc.CLI_TOKEN_SECRET, STORED, set_by="root")
    code = main(["doctor", "--verify"])
    out = capsys.readouterr().out
    assert code == 1  # the database probe is down in a bare home — unchanged behaviour
    line = next(ln for ln in out.splitlines() if ln.split()[1:2] == ["claude_code"])
    assert line.split()[0] == "ok"
    assert "auth: secrets file (…GOOD)" in line and "claude 9.9.9 (fake)" in line
    assert "verify: ok" in line
    assert STORED not in out and STORED[:-4] not in out
    code = main(["doctor", "--json"])
    body = json.loads(capsys.readouterr().out)
    probe = next(p for p in body["probes"] if p["name"] == "claude_code")
    assert probe["status"] == "ok" and probe["data"]["auth"] == "secrets_file"
    assert probe["data"]["fingerprint"] == "GOOD" and "verify" not in probe["data"]
    assert STORED not in json.dumps(body)
