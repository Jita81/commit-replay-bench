"""Automatic sign-in for a development stack (``CRB_AUTH__DEV_AUTOLOGIN``, ADR-0027).

The setting names one local account. When it is set, a browser on the same machine is signed
in as that account without a password — and nothing else is. These tests pin every half of
that sentence: the settings refuse it outside ``CRB_ENV=dev`` and on a non-loopback bind
(``crb serve --host`` included); the route signs in a loopback peer that names a loopback
host and refuses a remote peer, a request that came through a proxy (any forwarding header),
a page served under another host name (DNS rebinding) and a cross-site request, answering
all of them exactly as if the setting were off; the session it issues is an ordinary one
(the CSRF check, the role ladder, sign-out); every sign-in is an audit event and a log line;
a missing or disabled account signs nobody in and the log says why; ``/health``,
``/version`` and ``crb doctor`` report it; and it is off by default.

Navigation
----------
What it is:   The test suite for the development-only automatic sign-in — the settings
              refusals, the loopback-only route, the session it issues and how it is reported.
What it does: Pins that the setting is empty by default and the route then answers 404
              ``dev_autologin_off``; that ``prod`` and a non-loopback ``bind_host`` refuse to
              construct and ``serve`` refuses a non-loopback ``--host``; that a loopback peer
              (IPv4 and IPv6) on a loopback host name is signed in with the session and CSRF
              cookies; that a remote peer, each forwarding header, a foreign ``Host``, a
              foreign ``Origin`` and ``Sec-Fetch-Site: cross-site`` are refused like "off"
              with the reason logged; that the session is refused an unsafe method without
              the CSRF header, admitted with it, held to the account's role, and ended by
              sign-out (the next call signs in again); that each sign-in writes one
              ``auth.dev_autologin`` event and one warning line; that start-up warns; that a
              missing or disabled account is 403 with the reason in the log; and that
              ``/health``, ``/version`` and the ``dev_autologin`` doctor line report it.
How:          ``create_app`` on a throwaway SQLite home behind Starlette's ``TestClient``,
              whose ``client=`` sets the TCP peer and ``base_url`` the ``Host`` header.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0027-dev-autologin-on-loopback.md
Works with:   src/crb/server/auth.py (``dev_autologin_refusal``, the session primitives),
              src/crb/server/routes/auth.py (``POST /auth/dev-autologin``),
              src/crb/server/settings.py (``AuthSettings``, ``dev_autologin_refusal_for``),
              src/crb/server/main.py (``serve``), src/crb/server/routes/system.py
              (``probe_dev_autologin``, ``/health``, ``/version``), src/crb/server/app.py
              (the start-up warning), docs/SECURITY.md#38-automatic-sign-in-on-a-development-stack
Tested by:    tests/test_server_dev_autologin.py
Touch when:   the conditions for an automatic sign-in change (a case here for each one, and
              the threat-model row in docs/SECURITY.md); never to relax a refusal.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from crb.server.app import API_PREFIX, create_app
from crb.server.auth import CSRF_COOKIE, SESSION_COOKIE
from crb.server.settings import Settings
from crb.store.models import Event

ROOT_PW = "correct-horse-battery-staple"
VIEWER_PW = "another-long-password"
AUTOLOGIN = f"{API_PREFIX}/auth/dev-autologin"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Dev settings with the bootstrap admin ``root``; automatic sign-in as ``root`` unless
    ``auth`` is overridden."""
    base: dict[str, Any] = {
        "env": "dev",
        "home": tmp_path,
        "secret_key": SecretStr("s" * 40),
        "sandbox": {"executor": "local"},
        "bootstrap_admin": {"username": "root", "password": ROOT_PW},
        "log_format": "text",
        "auth": {"dev_autologin": "root"},
    }
    base.update(overrides)
    return Settings(**base)


def local_client(app: Any, peer: str = "127.0.0.1", host: str = "localhost:8000") -> TestClient:
    """A client whose TCP peer is ``peer`` and whose ``Host`` header is ``host``."""
    return TestClient(app, base_url=f"http://{host}", client=(peer, 50123))


def err(r: Any) -> dict[str, Any]:
    body = r.json()
    assert set(body) == {"error"}
    return dict(body["error"])


@pytest.fixture
def app(tmp_path: Path) -> Any:
    return create_app(make_settings(tmp_path))


@pytest.fixture
def local(app: Any) -> Iterator[TestClient]:
    with local_client(app) as c:
        yield c


def _autologin_events(app: Any) -> list[Event]:
    with app.state.session_factory() as s:
        return list(s.execute(select(Event).where(Event.action == "auth.dev_autologin")).scalars())


# --- settings ------------------------------------------------------------------------------


class TestSettings:
    def test_off_by_default(self, tmp_path: Path) -> None:
        s = Settings(env="dev", home=tmp_path, secret_key=SecretStr("s" * 40))
        assert s.auth.dev_autologin == ""
        with TestClient(create_app(make_settings(tmp_path, auth={}))) as c:
            c2 = local_client(c.app)
            r = c2.post(AUTOLOGIN)
            assert r.status_code == 404 and err(r)["code"] == "dev_autologin_off"
            assert SESSION_COOKIE not in c2.cookies
            assert c.get(f"{API_PREFIX}/health").json()["dev_autologin"] == "off"
            assert c.get(f"{API_PREFIX}/version").json()["dev_autologin"] is False

    def test_prod_refuses_it(self, tmp_path: Path) -> None:
        # allow_temp_home: tmp_path is an OS temporary directory, which prod refuses first
        with pytest.raises(ValidationError, match="only when CRB_ENV=dev"):
            make_settings(tmp_path, env="prod", allow_temp_home=True)

    def test_prod_from_the_environment_refuses_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_AUTH__DEV_AUTOLOGIN", "root")
        monkeypatch.setenv("CRB_SECRET_KEY", "k" * 40)
        monkeypatch.setenv("CRB_HOME", "/srv/crb-never-created")
        with pytest.raises(ValidationError, match="only when CRB_ENV=dev"):
            Settings()
        monkeypatch.setenv("CRB_ENV", "dev")
        assert Settings().auth.dev_autologin == "root"

    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "crb.example.com"])
    def test_a_non_loopback_bind_refuses_it(self, tmp_path: Path, host: str) -> None:
        with pytest.raises(ValidationError, match="loopback"):
            make_settings(tmp_path, bind_host=host)

    @pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "localhost"])
    def test_a_loopback_bind_admits_it(self, tmp_path: Path, host: str) -> None:
        assert make_settings(tmp_path, bind_host=host).auth.dev_autologin == "root"

    def test_a_malformed_username_is_refused_at_start_up(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="CRB_AUTH__DEV_AUTOLOGIN"):
            make_settings(tmp_path, auth={"dev_autologin": "root admin"})

    def test_serve_refuses_a_non_loopback_host_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``crb serve --host 0.0.0.0`` bypasses ``CRB_BIND_HOST``; ``serve`` checks the
        address it will actually bind, before uvicorn starts."""
        import crb.server.main as main_mod

        ran: list[str] = []
        monkeypatch.setattr(main_mod.uvicorn, "run", lambda *a, **k: ran.append(k["host"]))
        with pytest.raises(SystemExit, match="loopback"):
            main_mod.serve(host="0.0.0.0", settings=make_settings(tmp_path))
        assert ran == []
        main_mod.serve(host="127.0.0.1", settings=make_settings(tmp_path))
        assert ran == ["127.0.0.1"]

    def test_the_admin_settings_view_names_it(self, tmp_path: Path) -> None:
        assert make_settings(tmp_path).redacted_dict()["auth"] == {"dev_autologin": "root"}


# --- who is signed in ----------------------------------------------------------------------


class TestWhoIsSignedIn:
    @pytest.mark.parametrize("peer", ["127.0.0.1", "127.0.0.9", "::1"])
    def test_a_loopback_request_is_signed_in(self, app: Any, peer: str) -> None:
        with local_client(app, peer=peer) as c:
            assert c.get(f"{API_PREFIX}/auth/me").status_code == 401
            r = c.post(AUTOLOGIN)
            assert r.status_code == 200, r.text
            assert r.json()["role"] == "admin" and r.json()["issuer"] == "local"
            assert SESSION_COOKIE in c.cookies and CSRF_COOKIE in c.cookies
            me = c.get(f"{API_PREFIX}/auth/me")
            assert me.status_code == 200 and me.json()["display_name"] == "root"

    @pytest.mark.parametrize(
        "host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "localhost", "LOCALHOST:5173"]
    )
    def test_every_loopback_host_name_is_admitted(self, local: TestClient, host: str) -> None:
        assert local.post(AUTOLOGIN, headers={"Host": host}).status_code == 200

    @pytest.mark.parametrize("peer", ["192.168.1.20", "10.0.0.5", "172.17.0.1", "testclient"])
    def test_a_remote_peer_is_refused_as_if_it_were_off(
        self, app: Any, peer: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with local_client(app, peer=peer) as c, caplog.at_level(logging.WARNING):
            r = c.post(AUTOLOGIN)
            assert r.status_code == 404 and err(r)["code"] == "dev_autologin_off"
            assert SESSION_COOKIE not in c.cookies
            assert c.get(f"{API_PREFIX}/auth/me").status_code == 401
        assert "not loopback" in caplog.text
        assert _autologin_events(app) == []

    @pytest.mark.parametrize(
        ("header", "value"),
        [
            ("X-Forwarded-For", "203.0.113.7"),
            ("X-Forwarded-For", "127.0.0.1"),
            ("Forwarded", "for=203.0.113.7"),
            ("X-Real-IP", "203.0.113.7"),
            ("X-Forwarded-Host", "crb.example.com"),
            ("X-Forwarded-Proto", "https"),
            ("Via", "1.1 proxy"),
        ],
    )
    def test_a_forwarded_request_from_loopback_is_refused(
        self, local: TestClient, app: Any, header: str, value: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A reverse proxy on the same host connects from loopback; the header it adds is what
        tells the request apart from a browser on this machine."""
        with caplog.at_level(logging.WARNING):
            r = local.post(AUTOLOGIN, headers={header: value})
        assert r.status_code == 404 and err(r)["code"] == "dev_autologin_off"
        assert SESSION_COOKIE not in local.cookies
        assert header.lower() in caplog.text
        assert _autologin_events(app) == []

    @pytest.mark.parametrize(
        "host", ["evil.example:8000", "localhost.evil.example", "10.0.0.5:8000"]
    )
    def test_a_foreign_host_name_is_refused(
        self, app: Any, host: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """DNS rebinding: a page on ``evil.example`` whose name now resolves to 127.0.0.1
        reaches this server from a loopback peer, but its ``Host`` header names the page."""
        with local_client(app, host=host) as c, caplog.at_level(logging.WARNING):
            r = c.post(AUTOLOGIN)
            assert r.status_code == 404 and SESSION_COOKIE not in c.cookies
        assert "Host" in caplog.text

    @pytest.mark.parametrize(
        "headers",
        [
            {"Origin": "https://evil.example"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
        ],
    )
    def test_a_cross_site_request_is_refused(
        self, local: TestClient, headers: dict[str, str]
    ) -> None:
        r = local.post(AUTOLOGIN, headers=headers)
        assert r.status_code == 404 and SESSION_COOKIE not in local.cookies

    def test_a_same_origin_request_from_the_page_is_admitted(self, local: TestClient) -> None:
        r = local.post(
            AUTOLOGIN,
            headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"},
        )
        assert r.status_code == 200, r.text

    def test_a_missing_account_signs_nobody_in_and_says_why(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = create_app(make_settings(tmp_path, auth={"dev_autologin": "ghost"}))
        with local_client(app) as c, caplog.at_level(logging.WARNING):
            r = c.post(AUTOLOGIN)
            assert r.status_code == 403 and err(r)["code"] == "dev_autologin_unavailable"
            assert SESSION_COOKIE not in c.cookies
        assert "'ghost'" in caplog.text and "no local account" in caplog.text
        assert _autologin_events(app) == []

    def test_a_disabled_account_signs_nobody_in_and_says_why(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = create_app(make_settings(tmp_path, auth={"dev_autologin": "vera"}))
        with TestClient(app) as admin:
            _login_root(admin)
            uid = _create(admin, "vera", "viewer")
            r = admin.put(f"{API_PREFIX}/users/{uid}/active", json={"active": False})
            assert r.status_code == 200, r.text
            with local_client(app) as c, caplog.at_level(logging.WARNING):
                r = c.post(AUTOLOGIN)
                assert r.status_code == 403 and err(r)["code"] == "dev_autologin_unavailable"
                assert SESSION_COOKIE not in c.cookies
        assert "'vera'" in caplog.text and "disabled" in caplog.text


def _login_root(c: TestClient) -> None:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]


def _create(c: TestClient, username: str, role: str) -> str:
    r = c.post(
        f"{API_PREFIX}/users", json={"username": username, "password": VIEWER_PW, "role": role}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


# --- the session is an ordinary one --------------------------------------------------------


class TestTheSession:
    def test_an_unsafe_method_needs_the_csrf_header_like_any_session(
        self, local: TestClient
    ) -> None:
        assert local.post(AUTOLOGIN).status_code == 200
        body = {"username": "ada", "password": VIEWER_PW, "role": "viewer"}
        r = local.post(f"{API_PREFIX}/users", json=body)
        assert r.status_code == 403 and err(r)["code"] == "csrf_failed"
        r = local.post(
            f"{API_PREFIX}/users", json=body, headers={"X-CSRF-Token": local.cookies[CSRF_COOKIE]}
        )
        assert r.status_code == 201, r.text

    def test_the_account_role_holds(self, tmp_path: Path) -> None:
        app = create_app(make_settings(tmp_path, auth={"dev_autologin": "vera"}))
        with TestClient(app) as admin:
            _login_root(admin)
            _create(admin, "vera", "viewer")
            with local_client(app) as c:
                r = c.post(AUTOLOGIN)
                assert r.status_code == 200 and r.json()["role"] == "viewer"
                r = c.get(f"{API_PREFIX}/users")
                assert r.status_code == 403 and err(r)["code"] == "forbidden"

    def test_sign_out_ends_it_and_the_next_call_signs_in_again(self, local: TestClient) -> None:
        assert local.post(AUTOLOGIN).status_code == 200
        local.headers["X-CSRF-Token"] = local.cookies[CSRF_COOKIE]
        assert local.post(f"{API_PREFIX}/auth/logout").status_code == 204
        assert local.get(f"{API_PREFIX}/auth/me").status_code == 401
        del local.headers["X-CSRF-Token"]
        assert local.post(AUTOLOGIN).status_code == 200
        assert local.get(f"{API_PREFIX}/auth/me").status_code == 200

    def test_a_password_change_ends_the_session_like_any_other(self, local: TestClient) -> None:
        assert local.post(AUTOLOGIN).status_code == 200
        with TestClient(local.app) as other:
            _login_root(other)
            r = other.put(
                f"{API_PREFIX}/users/me/password",
                json={"current_password": ROOT_PW, "new_password": ROOT_PW + "-2"},
            )
            assert r.status_code == 200, r.text
        r = local.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"


# --- audit and reporting -------------------------------------------------------------------


class TestAuditAndReporting:
    def test_each_sign_in_is_an_event_and_a_warning(
        self, local: TestClient, app: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.auth"):
            assert local.post(AUTOLOGIN).status_code == 200
            # the second call rides the first session, so it is CSRF-checked like any other
            csrf = {"X-CSRF-Token": local.cookies[CSRF_COOKIE]}
            assert local.post(AUTOLOGIN).status_code == 403  # no header: refused, no event
            assert local.post(AUTOLOGIN, headers=csrf).status_code == 200
        events = _autologin_events(app)
        assert len(events) == 2
        me = local.get(f"{API_PREFIX}/auth/me").json()
        for ev in events:
            assert ev.actor == me["id"] and ev.stage == "system"
            assert ev.payload_json["client"] == "127.0.0.1"
            assert ev.payload_json["username"] == "root"
        lines = [r for r in caplog.records if "automatic sign-in" in r.getMessage()]
        assert len(lines) == 2 and all(r.levelno == logging.WARNING for r in lines)
        assert "'root'" in lines[0].getMessage() and "127.0.0.1" in lines[0].getMessage()

    def test_start_up_warns(self, app: Any, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING), TestClient(app):
            pass
        assert "AUTOMATIC SIGN-IN IS ON" in caplog.text and "'root'" in caplog.text

    def test_health_and_version_report_it(self, local: TestClient) -> None:
        assert local.get(f"{API_PREFIX}/health").json()["dev_autologin"] == "on"
        assert local.get(f"{API_PREFIX}/version").json()["dev_autologin"] is True

    def test_the_doctor_line_warns_when_on_and_is_ok_when_off(self, tmp_path: Path) -> None:
        from crb.server.routes.system import probe_dev_autologin

        on = probe_dev_autologin(make_settings(tmp_path))
        assert on.name == "dev_autologin" and on.status == "degraded"
        assert "'root'" in on.detail and "never use in production" in on.detail
        assert on.data == {"enabled": True, "username": "root"}
        off = probe_dev_autologin(make_settings(tmp_path, auth={}))
        assert off.status == "ok" and off.detail == "off" and off.data == {"enabled": False}
        assert probe_dev_autologin(None).status == "skipped"
