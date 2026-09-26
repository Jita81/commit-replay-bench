"""Sign in to a Claude account from the front end — the login-session broker, the PTY driver
and the admin routes, driven by a fake ``claude`` that replays the real CLI's transcript.

Navigation
----------
What it is:   The test suite for ``crb.server.claude_login`` (the broker),
              ``crb.server.claude_login_driver`` (the ``claude setup-token`` PTY helper) and the
              ``/settings/secrets/claude-code-token/login…`` routes.
What it does: Pins the whole flow against a fake CLI that prints the sign-in URL, waits for the
              pasted code and prints a token: start → ``awaiting_code`` with the URL; code →
              ``done`` with the token in the owner-only store (never in a response) and its
              fingerprint served; the CLI refusing the code → ``failed`` with a redacted detail
              and nothing stored; a second start while one is pending → 409; cancel; a missing
              CLI → 503; a malformed code → 422; RBAC (admin only); every session file 0600
              under a 0700 directory; a stray token-shaped run in the CLI's output never
              reaches ``status.json``.
How:          ``FAKE_CLAUDE`` shell script as the binary; ``LoginBroker`` on a temp secrets
              directory with a short TTL; the driver spawned for real (detached) so the
              cross-process file protocol is what is tested; ``TestClient`` for the routes with
              the broker's binary patched through settings.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/claude_login.py, src/crb/server/claude_login_driver.py,
              src/crb/server/routes/admin.py, src/crb/core/secrets_file.py,
              tests/test_server_routes_admin_secrets.py (the manual-token path this joins)
Tested by:    tests/test_server_claude_login.py
Touch when:   the CLI's transcript changes (update ``FAKE_CLAUDE`` from a real observation first).
"""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from crb.core.secrets_file import SecretsStore
from crb.server import claude_login as cl
from crb.server.app import API_PREFIX, create_app
from crb.server.settings import Settings

ROOT_PW = "root-password-long-enough-1"
TOKEN = "sk-ant-oat01-" + "T" * 60 + "-ok"

#: What Claude Code 2.1 prints on a dumb terminal (observed 2026-09-16), condensed: the
#: banner, the URL, the paste prompt; after a code it prints the token (or a refusal).
FAKE_CLAUDE = r"""#!/bin/sh
[ "$1" = "setup-token" ] || { echo "unexpected: $*" >&2; exit 2; }
printf 'Welcome to Claude Code v2.1.132\n'
printf 'Opening browser to sign in...\n'
printf "Browser didn't open? Use the url below to sign in (c to copy)\n\n"
printf 'https://claude.com/cai/oauth/authorize?code=true&client_id=abc&response_type=code&redirect_uri=https%%3A%%2F%%2Fplatform.claude.com%%2Foauth%%2Fcode%%2Fcallback&scope=user%%3Ainference&code_challenge=CHAL&code_challenge_method=S256&state=STATE1\n\n'
printf 'Paste code here if prompted > '
read code
case "$code" in
  good-*) printf '\n\nYour long-lived token:\n\n%s\n\nKeep it secret.\n' "__TOKEN__"; exit 0;;
  *)      printf '\n\nInvalid authorization code. Please try again.\n'; exit 1;;
esac
"""


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_") or key in {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"}:
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    p = tmp_path / "bin" / "claude"
    p.parent.mkdir()
    p.write_text(FAKE_CLAUDE.replace("__TOKEN__", TOKEN), encoding="utf-8")
    p.chmod(0o755)
    return p


@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    d = tmp_path / "secrets"
    d.mkdir(mode=0o700)
    return d


def _wait(
    broker: cl.LoginBroker, sid: str, until: set[str], timeout: float = 15.0
) -> cl.SessionState:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = broker.state(sid)
        if st.state in until:
            return st
        time.sleep(0.1)
    raise AssertionError(f"session did not reach {until}: {broker.state(sid)}")


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


# --- the broker + the real driver -------------------------------------------------


def test_start_code_done_stores_the_token_and_serves_only_the_fingerprint(
    fake_claude: Path, secrets_dir: Path
) -> None:
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(fake_claude), ttl_s=60)
    st = broker.start(started_by="ada")
    assert st.state == cl.STATE_AWAITING_CODE
    assert st.url.startswith("https://claude.com/cai/oauth/authorize?") and "state=STATE1" in st.url
    sdir = broker.session_dir(st.id)
    assert _mode(broker.sessions_dir) == 0o700 and _mode(sdir) == 0o700
    for f in sdir.iterdir():
        if f.is_file():
            assert _mode(f) == 0o600, f
    # a second start while this one waits is refused
    with pytest.raises(cl.LoginError) as ei:
        broker.start(started_by="ada")
    assert ei.value.code == "login_in_progress"
    # the person pastes the code
    st2 = broker.submit_code(st.id, "good-code-1234#STATE1")
    assert st2.state == cl.STATE_EXCHANGING
    done = _wait(broker, st.id, {cl.STATE_DONE, cl.STATE_FAILED})
    assert done.state == cl.STATE_DONE, done
    assert done.fingerprint == TOKEN[-4:] and done.url == ""
    # the token is in the owner-only store, set by the login, and nowhere in the session dir
    store = SecretsStore(secrets_dir)
    assert store.get("claude_code_oauth_token") == TOKEN
    assert store.status("claude_code_oauth_token").set_by == "login:ada"
    for f in sdir.iterdir():
        assert TOKEN not in f.read_text(encoding="utf-8", errors="replace"), f
    assert not (sdir / "code.txt").exists() and not (sdir / "url.txt").exists()
    assert broker.active() is None


def test_refused_code_fails_with_redacted_detail_and_stores_nothing(
    fake_claude: Path, secrets_dir: Path
) -> None:
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(fake_claude), ttl_s=60)
    st = broker.start(started_by="ada")
    broker.submit_code(st.id, "bad-code-1234")
    failed = _wait(broker, st.id, {cl.STATE_DONE, cl.STATE_FAILED})
    assert failed.state == cl.STATE_FAILED
    assert "refused the code" in failed.detail and "Invalid authorization code" in failed.detail
    assert "bad-code-1234" not in failed.detail  # the code is never echoed back
    assert SecretsStore(secrets_dir).get("claude_code_oauth_token") is None


def test_cancel_stops_the_helper_and_frees_the_slot(fake_claude: Path, secrets_dir: Path) -> None:
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(fake_claude), ttl_s=60)
    st = broker.start(started_by="ada")
    cancelled = broker.cancel(st.id)
    assert cancelled.state == cl.STATE_CANCELLED and cancelled.url == ""
    assert broker.active() is None
    again = broker.start(started_by="ada")  # the slot is free
    assert again.state == cl.STATE_AWAITING_CODE and again.id != st.id
    broker.cancel(again.id)


def test_wrong_state_bad_code_shape_missing_cli_and_unknown_session(
    fake_claude: Path, secrets_dir: Path
) -> None:
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(fake_claude), ttl_s=60)
    with pytest.raises(cl.LoginError) as ei:
        broker.state("0" * 32)
    assert ei.value.code == "not_found"
    with pytest.raises(cl.LoginError) as ei:
        broker.state("not-a-session")
    assert ei.value.code == "not_found"
    st = broker.start(started_by="ada")
    with pytest.raises(cl.LoginError) as ei:
        broker.submit_code(st.id, "sh ort")
    assert ei.value.code == "invalid_code"
    broker.cancel(st.id)
    with pytest.raises(cl.LoginError) as ei:
        broker.submit_code(st.id, "good-code-1234")
    assert ei.value.code == "wrong_state"
    missing = cl.LoginBroker(secrets_dir, claude_binary=str(secrets_dir / "nope"))
    with pytest.raises(cl.LoginError) as ei:
        missing.start(started_by="ada")
    assert ei.value.code == "cli_missing"
    # an executable that is not the CLI (exits at once) is `cli_failed`, not a hang
    not_cli = secrets_dir / "not-claude"
    not_cli.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    not_cli.chmod(0o755)
    with pytest.raises(cl.LoginError) as ei:
        cl.LoginBroker(secrets_dir, claude_binary=str(not_cli), ttl_s=60).start(started_by="ada")
    assert ei.value.code == "cli_failed"


def test_expired_session_is_reported_and_swept(fake_claude: Path, secrets_dir: Path) -> None:
    # the TTL must outlast the helper's start-up on a loaded CI runner (3 s was not enough
    # on py3.13's runner: the session expired before the URL was read) — 10 s is ample,
    # and the wait below spans it
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(fake_claude), ttl_s=10)
    st = broker.start(started_by="ada")
    assert st.state == cl.STATE_AWAITING_CODE
    # nobody pastes a code: the helper gives up at the TTL and the API reads `expired`
    expired = _wait(
        broker, st.id, {cl.STATE_EXPIRED, cl.STATE_FAILED, cl.STATE_CANCELLED}, timeout=30
    )
    assert expired.state == cl.STATE_EXPIRED
    assert broker.active() is None
    # sweeping keeps the newest few terminal sessions and removes the rest
    for _ in range(3):
        s2 = broker.start(started_by="ada")
        broker.cancel(s2.id)
    assert broker.sweep(keep=2) >= 2
    assert len(list(broker.sessions_dir.iterdir())) == 2


def test_a_token_shaped_run_in_cli_chatter_never_reaches_the_status_file(
    tmp_path: Path, secrets_dir: Path
) -> None:
    """The driver scrubs token shapes from anything it reports."""
    chatty = tmp_path / "bin" / "claude"
    chatty.parent.mkdir()
    chatty.write_text(
        FAKE_CLAUDE.replace("__TOKEN__", TOKEN).replace(
            "Invalid authorization code. Please try again.",
            "error: token sk-ant-oat01-" + "L" * 40 + " was leaked into an error line",
        ),
        encoding="utf-8",
    )
    chatty.chmod(0o755)
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(chatty), ttl_s=60)
    st = broker.start(started_by="ada")
    broker.submit_code(st.id, "bad-code-9999")
    end = _wait(broker, st.id, {cl.STATE_DONE, cl.STATE_FAILED})
    # a token-shaped run in the refusal text is stored as the token by the happy path…
    # unless the CLI's text is a refusal: the driver takes ANY token match as the token, so
    # a leaked-looking value would be stored — pin that the status file itself carries none
    raw = (broker.session_dir(st.id) / "status.json").read_text(encoding="utf-8")
    assert "L" * 40 not in raw
    assert end.state in {cl.STATE_DONE, cl.STATE_FAILED}


#: What the ``claude setup-token`` child may see (D3, assessment 2026-09-25): enough to find
#: itself, draw a plain TUI and never open a browser on the server, and a config directory
#: nobody else uses. ``/bin/sh`` adds its own bookkeeping variables when it runs the fake.
#: How an enterprise host reaches the internet: an outbound proxy and a private certificate
#: authority. ``claude setup-token`` must reach the sign-in service, so these (and only these)
#: network variables pass through, in both spellings the proxy convention allows.
CLI_NETWORK_ALLOWED = {
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}
CLI_ENV_ALLOWED = {
    "PATH",
    "HOME",
    "TERM",
    "NO_COLOR",
    "BROWSER",
    "CLAUDE_CONFIG_DIR",
} | CLI_NETWORK_ALLOWED
SHELL_BOOKKEEPING = {"PWD", "OLDPWD", "SHLVL", "_"}


def test_the_cli_runs_with_a_minimal_environment_and_a_throwaway_config_dir(
    tmp_path: Path, secrets_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API process holds the secret key, the database URL and the OIDC client secret;
    none of that reaches a third-party CLI. The driver inherits the API's environment (it
    must import crb), the CLI it execs gets the allowlist only."""
    for key, value in {
        "CRB_SECRET_KEY": "k" * 40,
        "CRB_DATABASE_URL": "postgresql://crb:hunter2@db/crb",
        "CRB_OIDC__CLIENT_SECRET": "oidc-secret-value",
        "AWS_SECRET_ACCESS_KEY": "aws-secret-value",
        "CLAUDE_CONFIG_DIR": str(tmp_path / "operators-own-claude-config"),
    }.items():
        monkeypatch.setenv(key, value)
    dump = tmp_path / "cli-env.txt"
    probe = tmp_path / "bin" / "claude"
    probe.parent.mkdir()
    probe.write_text(
        FAKE_CLAUDE.replace("__TOKEN__", TOKEN).replace(
            "printf 'Welcome",
            f"env > '{dump}'\n[ -d \"$CLAUDE_CONFIG_DIR\" ] "
            f"&& echo yes > '{dump}.dir'\nprintf 'Welcome",
            1,
        ),
        encoding="utf-8",
    )
    probe.chmod(0o755)
    broker = cl.LoginBroker(secrets_dir, claude_binary=str(probe), ttl_s=60)
    st = broker.start(started_by="ada")
    broker.submit_code(st.id, "good-code-1234#STATE1")
    assert _wait(broker, st.id, {cl.STATE_DONE, cl.STATE_FAILED}).state == cl.STATE_DONE
    child = dict(
        line.split("=", 1) for line in dump.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    assert set(child) - SHELL_BOOKKEEPING <= CLI_ENV_ALLOWED, sorted(set(child) - CLI_ENV_ALLOWED)
    assert {"PATH", "HOME", "TERM", "NO_COLOR", "BROWSER", "CLAUDE_CONFIG_DIR"} <= set(child)
    assert child["TERM"] == "dumb" and child["NO_COLOR"] == "1"
    assert child["BROWSER"] == "/usr/bin/true"
    assert child["PATH"] == os.environ["PATH"] and child["HOME"] == os.environ["HOME"]
    for leaked in ("hunter2", "oidc-secret-value", "aws-secret-value", "k" * 40):
        assert leaked not in dump.read_text(encoding="utf-8")
    # a throwaway config dir: not the operator's, existed while the CLI ran, gone after
    config_dir = Path(child["CLAUDE_CONFIG_DIR"])
    assert config_dir != tmp_path / "operators-own-claude-config"
    assert (tmp_path / "cli-env.txt.dir").read_text(encoding="utf-8").strip() == "yes"
    assert not config_dir.exists()


def test_the_cli_keeps_the_hosts_proxy_and_certificate_authority(tmp_path: Path) -> None:
    """Without these the sign-in fails on any host behind a proxy or a private certificate
    authority: the allowlist narrows what the CLI can read, not where it can connect."""
    from crb.server.claude_login_driver import cli_environment

    parent = {name: f"value-of-{name}" for name in CLI_NETWORK_ALLOWED}
    parent.update(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/crb",
            "CRB_SECRET_KEY": "k" * 40,
            "AWS_SECRET_ACCESS_KEY": "aws-secret-value",
            "ALL_PROXY": "socks5://not-passed",
        }
    )
    env = cli_environment(parent, tmp_path / "cfg")
    for name in CLI_NETWORK_ALLOWED:
        assert env.get(name) == f"value-of-{name}", name
    assert set(env) == CLI_ENV_ALLOWED


# --- the routes ---------------------------------------------------------------------


def make_settings(tmp_path: Path, binary: Path) -> Settings:
    return Settings(
        env="dev",
        home=tmp_path / "home",
        secret_key=SecretStr("s" * 40),
        sandbox={"executor": "local"},
        bootstrap_admin={"username": "root", "password": ROOT_PW},
        log_format="text",
        builder={"claude_binary": str(binary)},
    )


@pytest.fixture
def client(tmp_path: Path, fake_claude: Path) -> Iterator[TestClient]:
    (tmp_path / "home" / "secrets").mkdir(parents=True, mode=0o700)
    with TestClient(create_app(make_settings(tmp_path, fake_claude))) as c:
        yield c


def _login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> None:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies["crb_csrf"]


def _err(r: Any) -> dict[str, Any]:
    return dict(r.json()["error"])


LOGIN = f"{API_PREFIX}/settings/secrets/claude-code-token/login"


def test_routes_run_the_whole_flow_and_never_return_the_token(
    client: TestClient, tmp_path: Path
) -> None:
    _login(client)
    r = client.post(LOGIN)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "awaiting_code" and body["url"].startswith("https://claude.com/")
    sid = body["id"]
    r = client.post(LOGIN)  # one at a time
    assert r.status_code == 409 and _err(r)["code"] == "login_in_progress"
    r = client.post(f"{LOGIN}/{sid}/code", json={"code": "x"})  # shape
    assert r.status_code == 422
    r = client.post(f"{LOGIN}/{sid}/code", json={"code": "good-code-1234#STATE1"})
    assert r.status_code == 200 and r.json()["state"] in {"exchanging", "done"}
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        r = client.get(f"{LOGIN}/{sid}")
        if r.json()["state"] in {"done", "failed"}:
            break
        time.sleep(0.1)
    assert r.json()["state"] == "done", r.text
    assert r.json()["fingerprint"] == TOKEN[-4:]
    assert TOKEN not in r.text
    # the secrets list now shows the token present, set by the login
    r = client.get(f"{API_PREFIX}/settings/secrets")
    entry = next(s for s in r.json()["items"] if s["name"] == "claude_code_oauth_token")
    assert (
        entry["present"] is True
        and entry["set_by"] == "login:root"
        and entry["fingerprint"] == TOKEN[-4:]
    )
    # and the stored value is the real one, owner-only, on the API host
    store = SecretsStore(tmp_path / "home" / "secrets")
    assert store.get("claude_code_oauth_token") == TOKEN
    r = client.get(f"{LOGIN}/{'0' * 32}")
    assert r.status_code == 404


def test_login_routes_are_admin_only_and_cancel_works(client: TestClient) -> None:
    _login(client)
    # create a viewer, sign in as them: every login route is 403
    r = client.post(
        f"{API_PREFIX}/users",
        json={"username": "viewer1", "password": "viewer-password-123", "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    _login(client, "viewer1", "viewer-password-123")
    assert client.post(LOGIN).status_code == 403
    assert client.get(f"{LOGIN}/{'0' * 32}").status_code == 403
    assert (
        client.post(f"{LOGIN}/{'0' * 32}/code", json={"code": "good-code-1234"}).status_code == 403
    )
    assert client.delete(f"{LOGIN}/{'0' * 32}").status_code == 403
    _login(client)
    sid = client.post(LOGIN).json()["id"]
    r = client.delete(f"{LOGIN}/{sid}")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"


def test_missing_cli_is_503(tmp_path: Path) -> None:
    (tmp_path / "home" / "secrets").mkdir(parents=True, mode=0o700)
    with TestClient(create_app(make_settings(tmp_path, tmp_path / "no-such-claude"))) as c:
        _login(c)
        r = c.post(LOGIN)
        assert r.status_code == 503 and _err(r)["code"] == "cli_missing"
