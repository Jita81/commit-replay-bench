"""``crb doctor``: every line of the report. The ``claude_code`` probe (the login source —
env | secrets file (…xxxx) | keychain | none — the CLI's presence/version, and the Haiku
turn ONLY with ``--live``); the ``settings``, ``home``, ``github_app``, ``migrations``,
``worker`` and ``ui`` lines (F38); the ``ok / warn / fail / skip`` text labels and the
``--json`` shape. Hermetic: a fake ``claude`` on PATH, a throwaway ``CRB_HOME``, an
``httpx.MockTransport`` for GitHub, never the operator's login and never the network.

Navigation
----------
What it is:   ``crb doctor``'s test suite — the ``claude_code`` probe and the F38 lines.
What it does: Pins that a keychain login is ok, that no login and no key is degraded WITH the
              fix named, that a secrets file shows only its fingerprint, that an environment
              token wins, that an insecure secrets file is down, that a missing CLI is degraded,
              that ``--live`` (and its old name ``--verify``) runs the probe (ok and invalid)
              and nothing else does; that ``home`` fails on a temporary ``CRB_HOME`` in prod,
              warns in dev, fails on a group-readable secrets directory and passes a
              persistent path, fails on a secrets directory another uid owns; that
              ``settings`` names the server's refusal; that
              ``github_app`` skips when unconfigured, fails on a half configuration, an
              unreadable key file, a key that does not parse and a refusing GitHub, warns
              with no installation and is ok with installations (naming how many can
              deliver); that ``ui`` warns without a build and with an incomplete help bundle
              (an empty chunk counts as missing) and is ok with the eight chunks; and that
              ``crb doctor`` on a migrated store renders every line with ``ok / warn / fail /
              skip`` in text and the ``/health`` vocabulary in JSON, failing on a store
              stamped behind head and on one whose append-only triggers are missing.
How:          A fake ``claude`` on PATH and a throwaway ``CRB_HOME`` (the persistent case is a
              unique, never-created path under ``/srv`` — host state cannot reach it); an RSA key pair from
              ``cryptography`` and an ``httpx.MockTransport`` standing in for GitHub; a
              ``ui/dist`` made of one-line chunk files.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/cli/commands/service.py (under test), src/crb/builders/claude_code.py
              (the token sources it reports), src/crb/core/secrets_file.py (the store),
              src/crb/server/settings.py (``temp_dir_reason`` behind the ``home`` line),
              src/crb/server/routes/system.py (``migrations_result`` / ``probe_worker`` shared
              with ``/health``), tests/test_builders_claude_code.py (the same sources at the
              builder), docs/OPERATOR.md#11-check-the-installation-crb-doctor
Tested by:    tests/test_cli_doctor.py
Touch when:   a token source or auth mode is added (a status case naming it); a doctor line is
              added (its ok, warn and fail cases with the fix named).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from crb.builders import claude_code as cc
from crb.cli.commands.service import (
    HELP_GUIDES,
    load_settings,
    probe_claude_code,
    probe_github_app,
    probe_home,
    probe_settings,
    probe_ui,
)
from crb.cli.main import main
from crb.core.secrets_file import SecretsStore
from crb.server.settings import GitHubAppSettings, Settings
from crb.store import migrate

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
    code = main(["doctor", "--live"])
    out = capsys.readouterr().out
    assert code == 1  # the database is not initialised in a bare home — fail
    line = next(ln for ln in out.splitlines() if ln.split()[1:2] == ["claude_code"])
    assert line.split()[0] == "ok"
    assert "auth: secrets file (…GOOD)" in line and "claude 9.9.9 (fake)" in line
    assert "verify: ok" in line
    assert STORED not in out and STORED[:-4] not in out
    main(["doctor", "--verify"])  # the old name still runs the live turn
    assert "verify: ok" in capsys.readouterr().out
    code = main(["doctor", "--json"])
    body = json.loads(capsys.readouterr().out)
    probe = next(p for p in body["probes"] if p["name"] == "claude_code")
    assert probe["status"] == "ok" and probe["data"]["auth"] == "secrets_file"
    assert probe["data"]["fingerprint"] == "GOOD" and "verify" not in probe["data"]
    assert STORED not in json.dumps(body)


# --- F38: the settings / home / github_app / migrations / worker / ui lines ----------------

DOCTOR_LINES = (
    "toolchains",
    "sandbox",
    "builders",
    "claude_code",
    "settings",
    "home",
    "github_app",
    "database",
    "migrations",
    "intake",
    "worker",
    "ui",
)


@pytest.fixture
def persistent_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A test-owned, unique path under ``/srv`` (the image's ``CRB_HOME`` root) that is
    outside every ``TEMP_DIR_ROOTS`` entry and ``$TMPDIR`` — pinned to ``tmp_path`` so the
    host's own ``TMPDIR`` cannot classify it. Never created, so the ``home`` line's
    ``(not created yet)`` branch is what is exercised whatever exists on the host (the
    fixed ``/srv/crb`` once depended on host state: a host that had run the image made
    the probe report an existing directory)."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    path = Path("/srv") / f"crb-doctor-test-{uuid.uuid4().hex}"
    assert not path.exists()
    return path


def _lines(out: str) -> dict[str, tuple[str, str]]:
    """``name → (label, detail)`` from the text report."""
    rows: dict[str, tuple[str, str]] = {}
    for ln in out.splitlines():
        parts = ln.split(maxsplit=2)
        if len(parts) == 3 and parts[1] in DOCTOR_LINES:
            rows[parts[1]] = (parts[0], parts[2])
    return rows


class TestSettingsAndHomeLines:
    def test_settings_line_names_the_refusal_and_home_fails_on_a_temporary_home_in_prod(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # a bare prod shell: no CRB_SECRET_KEY, CRB_HOME under tmp_path (an OS temp dir)
        settings, refusal = load_settings()
        assert settings is not None and settings.env == "dev"  # the relaxed copy
        r = probe_settings(settings, refusal)
        assert r.status == "down"
        assert r.detail.startswith("the server would refuse to start: CRB_SECRET_KEY is required")
        h = probe_home()
        assert h.status == "down"
        assert "CRB_HOME" in h.detail and "OS-managed temporary directory" in h.detail
        assert "periodic clean-up" in h.detail and "~/crb-stack" in h.detail
        assert "secrets dir" in h.detail and "(not created yet)" in h.detail
        assert h.data["temporary"] and h.data["env"] == "prod"

    def test_home_warns_in_dev_and_with_the_opt_out(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_ENV", "dev")
        assert probe_home().status == "degraded"
        monkeypatch.setenv("CRB_ENV", "prod")
        monkeypatch.setenv("CRB_ALLOW_TEMP_HOME", "true")
        assert probe_home().status == "degraded"

    def test_home_is_ok_on_a_persistent_path_and_settings_ok_when_they_construct(
        self, home: Path, persistent_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_HOME", str(persistent_home))
        monkeypatch.setenv("CRB_SECRET_KEY", "k" * 40)
        settings, refusal = load_settings()
        assert settings is not None and refusal == "" and settings.env == "prod"
        r = probe_settings(settings, refusal)
        assert r.status == "ok"
        assert r.detail == f"CRB_ENV=prod · home {persistent_home} · database sqlite"
        h = probe_home()
        assert h.status == "ok"
        assert h.detail == (
            f"CRB_HOME {persistent_home} (not created yet) · "
            f"secrets dir {persistent_home / 'secrets'} (not created yet)"
        )
        assert "temporary" not in h.data and h.data["exists"] is False

    def test_home_fails_on_a_group_readable_secrets_dir(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_ENV", "dev")
        (home / "secrets").mkdir(parents=True)
        os.chmod(home / "secrets", 0o750)
        h = probe_home()
        assert h.status == "down" and f"`chmod 0700 {home / 'secrets'}`" in h.detail
        assert h.data["secrets_dir_mode"] == "0750"
        os.chmod(home / "secrets", 0o700)
        h = probe_home()
        assert h.status == "degraded" and "mode 0700" in h.detail  # degraded: still under tmp

    def test_home_fails_on_a_secrets_dir_owned_by_another_user(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mode 0700 is not enough: ``SecretsStore._check_dir_for_write`` refuses a directory
        another uid owns (a root-created mount), so the doctor must too — with the fix."""
        monkeypatch.setenv("CRB_ENV", "dev")
        (home / "secrets").mkdir(parents=True)
        os.chmod(home / "secrets", 0o700)
        me = os.geteuid()
        monkeypatch.setattr(os, "geteuid", lambda: me + 1)
        h = probe_home()
        assert h.status == "down"
        assert (
            f"secrets dir {home / 'secrets'} is owned by uid {me}, not the current user" in h.detail
        )
        assert f"(uid {me + 1})" in h.detail and f"`chown {me + 1} {home / 'secrets'}`" in h.detail
        assert h.data["secrets_dir_uid"] == me


@pytest.fixture(scope="module")
def pem() -> tuple[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    text = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return text, key.public_key()


def _github(installations: list[dict[str, Any]] | int) -> httpx.Client:
    """A stand-in GitHub: answers ``/app/installations`` with the list, or with the given
    HTTP status and a message."""

    def handle(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/app/installations", req.url.path
        assert req.headers.get("Authorization", "").startswith("Bearer ")
        if isinstance(installations, int):
            return httpx.Response(installations, json={"message": "Bad credentials"})
        return httpx.Response(200, json=installations)

    return httpx.Client(transport=httpx.MockTransport(handle))


INSTALL_RO = {
    "id": 77,
    "account": {"login": "acme", "type": "Organization"},
    "repository_selection": "selected",
    "html_url": "https://github.com/organizations/acme/settings/installations/77",
    "permissions": {"contents": "read", "metadata": "read"},
}
INSTALL_RW = {
    **INSTALL_RO,
    "id": 78,
    "account": {"login": "beta", "type": "Organization"},
    "permissions": {"contents": "write", "pull_requests": "write"},
}


class TestGitHubAppLine:
    def test_unconfigured_is_skipped_with_the_two_settings_named(self) -> None:
        r = probe_github_app(GitHubAppSettings())
        assert r.status == "skipped"
        assert "CRB_GITHUB__APP_ID" in r.detail and "CRB_GITHUB__PRIVATE_KEY_FILE" in r.detail
        assert r.data["configured"] is False and r.data["key_source"] == "none"
        assert probe_github_app(None).status == "degraded"

    def test_half_configured_and_unreadable_key_file_fail(self, tmp_path: Path) -> None:
        r = probe_github_app(GitHubAppSettings(app_id="4242"))
        assert r.status == "down" and "half configured" in r.detail
        assert "a private key (CRB_GITHUB__PRIVATE_KEY_FILE) is missing" in r.detail
        missing = tmp_path / "nope.pem"
        r = probe_github_app(GitHubAppSettings(app_id="4242", private_key_file=str(missing)))
        assert r.status == "down" and f"CRB_GITHUB__PRIVATE_KEY_FILE={missing}" in r.detail
        assert "cannot be read" in r.detail and "mount the app's PEM" in r.detail
        assert r.data["key_source"] == "file" and r.data["key_file_error"]
        empty = tmp_path / "empty.pem"
        empty.write_text("")
        r = probe_github_app(GitHubAppSettings(app_id="4242", private_key_file=str(empty)))
        assert r.status == "down" and "(empty)" in r.detail

    def test_a_key_that_does_not_parse_fails_before_any_request(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.pem"
        bad.write_text("-----BEGIN PRIVATE KEY-----\nnot a key\n-----END PRIVATE KEY-----\n")
        calls: list[str] = []

        def handle(req: httpx.Request) -> httpx.Response:
            calls.append(req.url.path)
            return httpx.Response(500)

        r = probe_github_app(
            GitHubAppSettings(app_id="4242", private_key_file=str(bad)),
            httpx.Client(transport=httpx.MockTransport(handle)),
        )
        assert r.status == "down" and "does not parse as the app's RSA PEM" in r.detail
        assert "download a fresh key" in r.detail and calls == []

    def test_github_refusing_fails_with_its_message(self, pem: tuple[str, Any]) -> None:
        r = probe_github_app(GitHubAppSettings(app_id="4242", private_key=pem[0]), _github(401))
        assert r.status == "down"
        assert "GitHub 401: Bad credentials" in r.detail and "check the app id" in r.detail
        assert r.data["github_status"] == 401

    def test_no_installation_warns_and_installations_are_ok(
        self, pem: tuple[str, Any], tmp_path: Path
    ) -> None:
        key_file = tmp_path / "app.pem"
        key_file.write_text(pem[0])
        settings = GitHubAppSettings(
            app_id="4242", app_slug="crb-bench", private_key_file=str(key_file)
        )
        r = probe_github_app(settings, _github([]))
        assert r.status == "degraded"
        assert "no installation yet" in r.detail
        assert "https://github.com/apps/crb-bench/installations/new" in r.detail
        r = probe_github_app(settings, _github([INSTALL_RO, INSTALL_RW]))
        assert r.status == "ok"
        assert r.detail == "app 4242: 2 installations (acme, beta) · 1 can deliver"
        assert [i["id"] for i in r.data["installations"]] == [77, 78]
        assert r.data["key_source"] == "file" and r.data["key_file"] == str(key_file)
        assert pem[0] not in json.dumps(r.to_dict())


def _dev_settings(home: Path, **over: Any) -> Settings:
    return Settings(env="dev", home=home, **over)


#: What a built help chunk contains — never empty (an empty chunk is a missing guide).
CHUNK = "export default 'guide'\n"


class TestUiLine:
    def test_no_build_warns_with_the_fix(self, home: Path, tmp_path: Path) -> None:
        r = probe_ui(_dev_settings(home, ui_dist=str(tmp_path / "nowhere")))
        assert r.status == "degraded" and "no built UI" in r.detail
        assert "npm --prefix ui run build" in r.detail and r.data["dist"] is None
        assert probe_ui(None).status == "degraded"

    def test_incomplete_help_bundle_names_the_missing_guides(
        self, home: Path, tmp_path: Path
    ) -> None:
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>")
        for name in HELP_GUIDES[:-2]:
            (dist / "assets" / f"{name}-Ab12cD3.js").write_text(CHUNK)
        r = probe_ui(_dev_settings(home, ui_dist=str(dist)))
        assert r.status == "degraded"
        assert "6/8 guides, missing LEARNING-LOOP, DEPLOYMENT" in r.detail
        assert r.data["missing_guides"] == ["LEARNING-LOOP", "DEPLOYMENT"]
        # a hash may start with "-" (vite emitted OPERATOR--HQku2aS.js): still the guide's chunk
        (dist / "assets" / "LEARNING-LOOP--x1.js").write_text(CHUNK)
        (dist / "assets" / "DEPLOYMENT-DMf1bMdE.js").write_text(CHUNK)
        r = probe_ui(_dev_settings(home, ui_dist=str(dist)))
        assert r.status == "ok" and r.detail == f"UI at {dist} · 8/8 help guides bundled"

    def test_an_empty_or_non_file_chunk_is_a_missing_guide(
        self, home: Path, tmp_path: Path
    ) -> None:
        """A zero-byte asset (a truncated copy, an interrupted build) or a directory that
        happens to match the glob would serve an empty ``/help/docs/<guide>`` — not ``ok``."""
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>")
        for name in HELP_GUIDES:
            (dist / "assets" / f"{name}-Ab12cD3.js").write_text(CHUNK)
        (dist / "assets" / "SECURITY-Ab12cD3.js").write_text("")
        (dist / "assets" / "DEPLOYMENT-Ab12cD3.js").unlink()
        (dist / "assets" / "DEPLOYMENT-Ab12cD3.js").mkdir()
        r = probe_ui(_dev_settings(home, ui_dist=str(dist)))
        assert r.status == "degraded"
        assert r.data["missing_guides"] == ["SECURITY", "DEPLOYMENT"]
        assert "6/8 guides, missing SECURITY, DEPLOYMENT" in r.detail


class TestDoctorReport:
    def test_every_line_on_a_migrated_store_then_a_store_behind_head(
        self,
        home: Path,
        fake_cli: Callable[[bool], None],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_cli(True)
        monkeypatch.setenv("CRB_ENV", "dev")
        # the `ui` line below asserts the NO-built-UI case, so this test must not read the
        # developer's own `ui/dist`: running the walkthrough in the same worktree built one and
        # the line flipped to `ok` — a test that depends on the machine it runs on
        monkeypatch.setenv("CRB_UI_DIST", str(home / "no-built-ui"))
        url = f"sqlite:///{home / 'crb.db'}"
        home.mkdir()
        migrate.upgrade(url)
        code = main(["doctor"])
        out = capsys.readouterr().out
        rows = _lines(out)
        assert list(rows) == list(DOCTOR_LINES)
        assert rows["settings"][0] == "ok" and rows["home"][0] == "warn"  # dev, under tmp
        assert rows["github_app"][0] == "skip"
        assert rows["database"] == ("ok", "answers · triggers present; UPDATE on grades refused")
        assert rows["migrations"] == ("ok", f"database at {migrate.head_revision()} = code head")
        # no worker has ever checked in on this fresh store: /health's worker probe says so
        # (degraded, never down); doctor renders it as warn
        assert rows["worker"] == (
            "warn",
            "no worker has checked in yet — queued runs will not start",
        )
        assert rows["ui"][0] == "warn" and "no built UI" in rows["ui"][1]
        assert "claude_code" in rows and "verify" not in rows["claude_code"][1]
        assert out.rstrip().endswith("overall: warn") and code == 0

        from alembic import command

        command.stamp(migrate.alembic_config(url), migrate.INITIAL_REVISION)
        code = main(["doctor", "--json"])
        body = json.loads(capsys.readouterr().out)
        assert code == 1 and body["status"] == "down"
        assert [p["name"] for p in body["probes"]] == list(DOCTOR_LINES)
        m = next(p for p in body["probes"] if p["name"] == "migrations")
        assert m["status"] == "down"  # the /health vocabulary, not the text labels
        assert m["detail"].startswith(
            f"database at 0001, code head {migrate.head_revision()} — run `crb migrate`"
        )
        assert next(p for p in body["probes"] if p["name"] == "worker")["status"] == "degraded"

    def test_uninitialised_store_fails_and_the_worker_is_not_guessed(
        self, home: Path, fake_cli: Callable[[bool], None], capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_cli(True)
        assert main(["doctor"]) == 1
        rows = _lines(capsys.readouterr().out)
        assert rows["database"] == ("fail", "database not initialised — run `crb migrate`")
        assert (
            rows["migrations"][0] == "fail"
            and "database not migrated (empty)" in rows["migrations"][1]
        )
        assert rows["worker"] == ("warn", "not checked: the database line failed")

    def test_a_store_with_tables_but_no_triggers_fails_the_database_line(
        self,
        home: Path,
        fake_cli: Callable[[bool], None],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``assert_append_only`` returns on an empty ``grades`` table, so a store whose
        triggers were dropped (or never installed) looked ``ok``; the line now counts the
        triggers the way ``/health`` does and names how many are missing."""
        from sqlalchemy import text

        from crb.store.db import make_engine
        from crb.store.models import APPEND_ONLY_TABLES

        fake_cli(True)
        monkeypatch.setenv("CRB_ENV", "dev")
        url = f"sqlite:///{home / 'crb.db'}"
        home.mkdir()
        migrate.upgrade(url)
        engine = make_engine(url)
        with engine.begin() as c:
            c.execute(text("DROP TRIGGER grades_no_update"))
            c.execute(text("DROP TRIGGER grades_no_delete"))
        engine.dispose()
        code = main(["doctor", "--json"])
        body = json.loads(capsys.readouterr().out)
        expected = 2 * len(APPEND_ONLY_TABLES)
        db = next(p for p in body["probes"] if p["name"] == "database")
        assert code == 1 and db["status"] == "down"
        assert db["detail"] == (
            f"{expected - 2}/{expected} append-only triggers present — run `crb migrate`"
        )
        assert db["data"]["triggers"] == expected - 2 and db["data"]["url"].startswith("sqlite")
        # the worker line is not guessed from a store that failed
        assert next(p for p in body["probes"] if p["name"] == "worker")["status"] == "degraded"
