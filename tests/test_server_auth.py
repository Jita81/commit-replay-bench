"""Authentication: local login, sessions, CSRF, rate limit, OIDC (faked provider), users.

No network: the OIDC provider is a fake injected through ``create_app(oidc_client=...)``.

Navigation
----------
What it is:   The authentication test suite — local login, sessions, CSRF, the login rate
              limit, OIDC against a faked provider, and user management.
What it does: Pins password hashing (short passwords refused), session round trip / tamper /
              expiry, the rate limiter window, ``safe_next_path`` (open redirects neutralised),
              role mapping; that login sets the cookies, a wrong password is a 401 envelope, five
              failures rate-limit, local auth can be disabled, a deactivated user's session
              stops working, logout clears; that a POST without the CSRF header is refused while
              GET is never checked and an anonymous POST is 401 not CSRF; that a viewer cannot
              manage users, the last-admin guard, and user lists never include hashes; and the
              OIDC flow — state + PKCE cookie on start, a mapped user on callback, state mismatch
              and provider errors rejected, exchange failure as 502.
How:          ``create_app(oidc_client=FakeOidc(...))`` — no network; a ``TestClient`` per
              settings variant.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/auth.py (under test), src/crb/server/routes/auth.py (the login /
              logout / users routes), src/crb/server/settings.py (``OidcSettings``),
              src/crb/store/models.py (the ``users`` table), docs/SECURITY.md (authentication
              and authorisation, §3.4), docs/DEPLOYMENT.md (Entra ID → ``CRB_OIDC__*``, §4.1)
Tested by:    tests/test_server_auth.py
Touch when:   a role is added to the ladder (the map and the RBAC matrices in every route
              suite); the OIDC claims mapping changes; never so that a mutating route skips CSRF.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from crb.server.app import API_PREFIX, create_app
from crb.server.auth import (
    CSRF_COOKIE,
    OIDC_COOKIE,
    SESSION_COOKIE,
    LoginRateLimiter,
    hash_password,
    issue_session,
    map_role,
    read_oidc_cookie,
    read_session,
    safe_next_path,
    verify_password,
)
from crb.server.deps import ApiError
from crb.server.settings import OidcSettings, Settings

ROOT_PW = "correct-horse-battery-staple"
USER_PW = "another-long-password"
ISSUER = "https://login.example/tenant-1"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Dev ``Settings`` on ``tmp_path`` with the bootstrap admin; ``overrides`` win (``oidc``,
    cookie security, ``local_auth``).
    """
    base: dict[str, Any] = {
        "env": "dev",
        "home": tmp_path,
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


def login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> Any:
    """Log ``c`` in as ``username`` and set the CSRF header."""
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]
    return r


def err(r: Any) -> dict[str, Any]:
    """The error envelope of a response, shape asserted."""
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "detail"}
    return dict(body["error"])


# --- primitives ---------------------------------------------------------------------------


class TestPrimitives:
    """The building blocks below the routes: hashing, sessions, the limiter, redirects, role
    mapping.
    """

    def test_password_hash_roundtrip(self) -> None:
        h = hash_password(USER_PW)
        assert h.startswith("$argon2id$")
        assert verify_password(h, USER_PW)
        assert not verify_password(h, USER_PW + "x")
        assert not verify_password("", USER_PW)  # unknown-user path: still a real verify
        assert not verify_password("not-a-hash", USER_PW)

    def test_hash_rejects_short_password(self) -> None:
        with pytest.raises(ValueError, match="at least 12"):
            hash_password("short")

    def test_session_roundtrip_and_tamper(self, settings: Settings) -> None:
        token = issue_session(settings, "user-1")
        assert read_session(settings, token) == "user-1"
        with pytest.raises(ApiError) as ei:
            read_session(settings, token[:-3] + "xyz")
        assert ei.value.status_code == 401 and ei.value.code == "unauthenticated"
        other = make_settings(settings.home, secret_key=SecretStr("t" * 40))
        with pytest.raises(ApiError):
            read_session(other, token)

    def test_session_expires(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        token = issue_session(settings, "user-1")
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + settings.session_ttl + 5)
        with pytest.raises(ApiError) as ei:
            read_session(settings, token)
        assert ei.value.code == "session_expired"

    def test_rate_limiter_window(self) -> None:
        clock = {"t": 1000.0}
        rl = LoginRateLimiter(limit=5, window_s=60, clock=lambda: clock["t"])
        assert rl.retry_after("u", "ip") is None
        for _ in range(5):
            rl.record_failure("u", "ip")
        assert rl.retry_after("u", "ip") == pytest.approx(60.0)
        assert rl.retry_after("u", "other-ip") is None  # keyed by (user, ip)
        assert rl.retry_after("v", "ip") is None
        clock["t"] += 61
        assert rl.retry_after("u", "ip") is None
        for _ in range(5):
            rl.record_failure("u", "ip")
        rl.reset("u", "ip")
        assert rl.retry_after("u", "ip") is None

    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            (None, "/"),
            ("", "/"),
            ("/runs?repo=x", "/runs?repo=x"),
            ("//evil.example", "/"),
            ("https://evil.example", "/"),
            ("/ok\\evil", "/"),
            ("/ok\r\nSet-Cookie: x", "/"),
        ],
    )
    def test_safe_next_path(self, candidate: str | None, expected: str) -> None:
        assert safe_next_path(candidate) == expected

    def test_map_role(self) -> None:
        oidc = OidcSettings(
            role_claim="roles",
            role_map={"crb-ops": "operator", "crb-approvers": "approver", "crb-view": "viewer"},
            admin_groups=["grp-admins"],
        )
        assert map_role({}, oidc) == "viewer"
        assert map_role({"roles": "crb-ops"}, oidc) == "operator"
        assert map_role({"roles": ["crb-view", "crb-approvers", "unknown"]}, oidc) == "approver"
        assert map_role({"groups": ["grp-admins"]}, oidc) == "admin"
        assert map_role({"roles": ["crb-ops"], "groups": ["grp-admins"]}, oidc) == "admin"
        assert map_role({"roles": ["nothing-mapped"]}, oidc) == "viewer"


# --- local login ------------------------------------------------------------------------


class TestLocalLogin:
    def test_login_sets_cookies_and_me(self, client: TestClient) -> None:
        r = login(client)
        body = r.json()
        assert body["role"] == "admin" and body["issuer"] == "local"
        assert body["display_name"] == "root"
        set_cookie = " ".join(v.lower() for v in r.headers.get_list("set-cookie"))
        assert f"{SESSION_COOKIE}=" in set_cookie
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "secure" not in set_cookie  # dev
        assert client.cookies.get(CSRF_COOKIE)
        me = client.get(f"{API_PREFIX}/auth/me")
        assert me.status_code == 200
        assert me.json() == body

    def test_secure_flag_follows_settings(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path, cookie_secure=True))) as c:
            r = c.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
            assert r.status_code == 200
            assert all("secure" in v.lower() for v in r.headers.get_list("set-cookie"))

    def test_wrong_password_401_envelope(self, client: TestClient) -> None:
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": "nope-x"})
        assert r.status_code == 401
        assert err(r)["code"] == "invalid_credentials"
        assert SESSION_COOKIE not in client.cookies
        # Unknown user: same status, same code — no enumeration.
        r = client.post(
            f"{API_PREFIX}/auth/login", json={"username": "ghost", "password": "nope-x"}
        )
        assert r.status_code == 401
        assert err(r)["code"] == "invalid_credentials"

    def test_rate_limit_after_five_failures(self, client: TestClient) -> None:
        for _ in range(5):
            r = client.post(
                f"{API_PREFIX}/auth/login", json={"username": "root", "password": "bad"}
            )
            assert r.status_code == 401
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
        assert r.status_code == 429
        e = err(r)
        assert e["code"] == "rate_limited"
        assert e["detail"]["retry_after_s"] >= 1
        assert r.headers["Retry-After"].isdigit()
        # A different username from the same client is not blocked.
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "other", "password": "bad"})
        assert r.status_code == 401

    def test_local_auth_can_be_disabled(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path, local_auth_enabled=False))) as c:
            r = c.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
            assert r.status_code == 403
            assert err(r)["code"] == "local_auth_disabled"

    def test_unauthenticated_and_bad_session(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "unauthenticated"
        client.cookies.set(SESSION_COOKIE, "garbage.token.value")
        r = client.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "unauthenticated"

    def test_logout_clears_session(self, client: TestClient) -> None:
        login(client)
        r = client.post(f"{API_PREFIX}/auth/logout")
        assert r.status_code == 204
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 401

    def test_deactivated_user_cannot_use_session(self, client: TestClient) -> None:
        login(client)
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "bob", "password": USER_PW, "role": "viewer"}
        )
        bob = r.json()["id"]
        with TestClient(client.app) as bob_client:
            login(bob_client, "bob", USER_PW)
            assert bob_client.get(f"{API_PREFIX}/auth/me").status_code == 200
            r = client.put(
                f"{API_PREFIX}/users/{bob}/role", json={"role": "viewer", "active": False}
            )
            assert r.status_code == 200 and r.json()["active"] is False
            r = bob_client.get(f"{API_PREFIX}/auth/me")
            assert r.status_code == 401
            r = bob_client.post(
                f"{API_PREFIX}/auth/login", json={"username": "bob", "password": USER_PW}
            )
            assert r.status_code == 401


# --- CSRF -------------------------------------------------------------------------------


class TestCsrf:
    def test_post_without_header_is_refused(self, client: TestClient) -> None:
        login(client)
        del client.headers["X-CSRF-Token"]
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "x1", "password": USER_PW, "role": "viewer"}
        )
        assert r.status_code == 403
        assert err(r)["code"] == "csrf_failed"
        r = client.post(
            f"{API_PREFIX}/users",
            json={"username": "x1", "password": USER_PW, "role": "viewer"},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert r.status_code == 403 and err(r)["code"] == "csrf_failed"

    def test_post_with_header_passes(self, client: TestClient) -> None:
        login(client)
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "x2", "password": USER_PW, "role": "viewer"}
        )
        assert r.status_code == 201, r.text

    def test_csrf_endpoint_returns_cookie_token(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/auth/csrf").status_code == 401
        login(client)
        r = client.get(f"{API_PREFIX}/auth/csrf")
        assert r.status_code == 200
        assert r.json()["token"] == client.cookies[CSRF_COOKIE]

    def test_get_is_never_csrf_checked(self, client: TestClient) -> None:
        login(client)
        del client.headers["X-CSRF-Token"]
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 200

    def test_anonymous_post_is_401_not_csrf(self, client: TestClient) -> None:
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "x3", "password": USER_PW, "role": "viewer"}
        )
        assert r.status_code == 401
        assert err(r)["code"] == "unauthenticated"


# --- admin: users -------------------------------------------------------------------------


class TestUsers:
    def test_viewer_cannot_manage_users(self, client: TestClient) -> None:
        login(client)
        client.post(
            f"{API_PREFIX}/users", json={"username": "vw", "password": USER_PW, "role": "viewer"}
        )
        login(client, "vw", USER_PW)
        assert client.get(f"{API_PREFIX}/users").status_code == 403
        assert client.get(f"{API_PREFIX}/settings").status_code == 403
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "z", "password": USER_PW, "role": "admin"}
        )
        assert r.status_code == 403 and err(r)["code"] == "forbidden"

    def test_create_validation(self, client: TestClient) -> None:
        login(client)
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "ok", "password": "short", "role": "viewer"}
        )
        assert r.status_code == 422 and err(r)["code"] == "validation_error"
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "ok", "password": USER_PW, "role": "god"}
        )
        assert r.status_code == 422 and err(r)["detail"]["field"] == "role"
        r = client.post(f"{API_PREFIX}/users", json={"username": "bad name!", "password": USER_PW})
        assert r.status_code == 422 and err(r)["detail"]["field"] == "username"
        r = client.post(f"{API_PREFIX}/users", json={"username": "ok", "password": USER_PW})
        assert r.status_code == 201 and r.json()["role"] == "viewer"
        r = client.post(f"{API_PREFIX}/users", json={"username": "ok", "password": USER_PW})
        assert r.status_code == 409 and err(r)["code"] == "user_exists"
        assert "password" not in r.text

    def test_role_change_and_last_admin_guard(self, client: TestClient) -> None:
        login(client)
        root_id = client.get(f"{API_PREFIX}/auth/me").json()["id"]
        r = client.put(f"{API_PREFIX}/users/{root_id}/role", json={"role": "viewer"})
        assert r.status_code == 409 and err(r)["code"] == "last_admin"
        r = client.put(
            f"{API_PREFIX}/users/{root_id}/role", json={"role": "admin", "active": False}
        )
        assert r.status_code == 409 and err(r)["code"] == "last_admin"
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "a2", "password": USER_PW, "role": "operator"}
        )
        a2 = r.json()["id"]
        r = client.put(f"{API_PREFIX}/users/nope/role", json={"role": "viewer"})
        assert r.status_code == 404 and err(r)["code"] == "not_found"
        r = client.put(f"{API_PREFIX}/users/{a2}/role", json={"role": "chief"})
        assert r.status_code == 422
        r = client.put(f"{API_PREFIX}/users/{a2}/role", json={"role": "admin"})
        assert r.status_code == 200 and r.json()["role"] == "admin"
        # With a second admin in place, root may step down — and immediately loses admin.
        r = client.put(f"{API_PREFIX}/users/{root_id}/role", json={"role": "viewer"})
        assert r.status_code == 200 and r.json()["role"] == "viewer"
        assert client.get(f"{API_PREFIX}/users").status_code == 403

    def test_list_users_never_includes_hashes(self, client: TestClient) -> None:
        login(client)
        r = client.get(f"{API_PREFIX}/users")
        assert r.status_code == 200
        assert r.json()["total"] == 1
        assert "password_hash" not in r.text and "argon2" not in r.text


# --- OIDC ---------------------------------------------------------------------------------


class FakeOidc:
    """Records the PKCE material handed to it and returns canned claims on exchange."""

    def __init__(self, claims: Mapping[str, Any]) -> None:
        self.claims = dict(claims)
        self.starts: list[dict[str, str]] = []
        self.exchanges: list[dict[str, str]] = []

    def authorization_url(
        self, *, state: str, nonce: str, code_verifier: str, redirect_uri: str
    ) -> str:
        """Record the PKCE material and answer a canned provider URL."""
        self.starts.append(
            {
                "state": state,
                "nonce": nonce,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            }
        )
        return (
            f"{ISSUER}/oauth2/authorize?response_type=code&client_id=cid&state={state}"
            f"&nonce={nonce}&code_challenge_method=S256&redirect_uri={redirect_uri}"
        )

    def exchange(
        self, *, code: str, code_verifier: str, nonce: str, redirect_uri: str
    ) -> Mapping[str, Any]:
        """Answer the canned claims for any code (the provider is trusted by construction here)."""
        self.exchanges.append(
            {
                "code": code,
                "code_verifier": code_verifier,
                "nonce": nonce,
                "redirect_uri": redirect_uri,
            }
        )
        if code != "good-code":
            raise RuntimeError("invalid_grant")
        return {**self.claims, "iss": ISSUER, "nonce": nonce}


OIDC_SETTINGS: dict[str, Any] = {
    "issuer": ISSUER,
    "client_id": "cid",
    "client_secret": "csecret-value-1234567890",
    "role_claim": "roles",
    "role_map": {"crb-operators": "operator", "crb-approvers": "approver"},
    "admin_groups": ["grp-crb-admins"],
    "redirect_url": "https://crb.example/api/v1/auth/oidc/callback",
}


@pytest.fixture
def oidc_app(tmp_path: Path) -> tuple[Any, FakeOidc]:
    """An app with OIDC configured against ``FakeOidc``; returns both so a test can read what the
    provider was handed.
    """
    fake = FakeOidc(
        {
            "sub": "entra-oid-123",
            "email": "ann@nhs.example",
            "name": "Ann Example",
            "roles": ["crb-operators"],
        }
    )
    app = create_app(make_settings(tmp_path, oidc=OIDC_SETTINGS), oidc_client=fake)
    return app, fake


class TestOidc:
    def test_not_configured(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
        assert r.status_code == 404 and err(r)["code"] == "oidc_not_configured"

    def test_start_redirects_with_state_and_pkce_cookie(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, fake = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        with TestClient(app) as c:
            r = c.get(f"{API_PREFIX}/auth/oidc/start?next=/runs", follow_redirects=False)
            assert r.status_code == 302
            loc = urlparse(r.headers["location"])
            assert f"{loc.scheme}://{loc.netloc}{loc.path}" == f"{ISSUER}/oauth2/authorize"
            q = parse_qs(loc.query)
            assert q["code_challenge_method"] == ["S256"]
            assert q["redirect_uri"] == [OIDC_SETTINGS["redirect_url"]]
            cookie_hdr = " ".join(v.lower() for v in r.headers.get_list("set-cookie"))
            assert f"{OIDC_COOKIE}=" in cookie_hdr and "httponly" in cookie_hdr
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            assert pending.state == q["state"][0]
            assert pending.nonce == q["nonce"][0]
            assert pending.next_path == "/runs"
            assert len(pending.code_verifier) >= 43  # RFC 7636 minimum
            assert fake.starts[-1]["code_verifier"] == pending.code_verifier
            assert SESSION_COOKIE not in c.cookies

    def test_callback_happy_path_creates_mapped_user(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, fake = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start?next=/runs", follow_redirects=False)
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": pending.state},
                follow_redirects=False,
            )
            assert r.status_code == 302, r.text
            assert r.headers["location"] == "/runs"
            assert fake.exchanges[-1]["code_verifier"] == pending.code_verifier
            assert fake.exchanges[-1]["nonce"] == pending.nonce
            assert fake.exchanges[-1]["redirect_uri"] == OIDC_SETTINGS["redirect_url"]
            assert c.cookies.get(SESSION_COOKIE) and c.cookies.get(CSRF_COOKIE)
            me = c.get(f"{API_PREFIX}/auth/me").json()
            assert me["role"] == "operator"
            assert me["issuer"] == ISSUER
            assert me["email"] == "ann@nhs.example"
            assert me["display_name"] == "Ann Example"
            # The pending-login cookie is single use.
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": pending.state},
                follow_redirects=False,
            )
            assert r.status_code == 400 and err(r)["code"] == "oidc_state_missing"
        # Upsert by (issuer, subject): a second login with new groups updates the role.
        fake.claims["roles"] = ["crb-approvers"]
        fake.claims["groups"] = ["grp-crb-admins"]
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": pending.state},
                follow_redirects=False,
            )
            assert r.status_code == 302 and r.headers["location"] == "/"
            assert c.get(f"{API_PREFIX}/auth/me").json()["role"] == "admin"
            c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]
            users = c.get(f"{API_PREFIX}/users").json()
            oidc_users = [u for u in users["items"] if u["issuer"] == ISSUER]
            assert len(oidc_users) == 1 and oidc_users[0]["subject"] == "entra-oid-123"

    def test_callback_rejects_state_mismatch_and_provider_errors(
        self, oidc_app: tuple[Any, FakeOidc]
    ) -> None:
        app, _ = oidc_app
        with TestClient(app) as c:
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": "x"},
                follow_redirects=False,
            )
            assert r.status_code == 400 and err(r)["code"] == "oidc_state_missing"
            c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": "forged"},
                follow_redirects=False,
            )
            assert r.status_code == 400 and err(r)["code"] == "oidc_state_mismatch"
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"error": "access_denied", "error_description": "user cancelled"},
                follow_redirects=False,
            )
            assert r.status_code == 400 and err(r)["code"] == "oidc_provider_error"
            assert SESSION_COOKIE not in c.cookies

    def test_callback_exchange_failure_is_502(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, _ = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "bad-code", "state": pending.state},
                follow_redirects=False,
            )
            assert r.status_code == 502 and err(r)["code"] == "oidc_exchange_failed"
            assert "invalid_grant" not in r.text
            assert SESSION_COOKIE not in c.cookies

    def test_open_redirect_is_neutralised(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, _ = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start?next=//evil.example/x", follow_redirects=False)
            assert read_oidc_cookie(settings, c.cookies[OIDC_COOKIE]).next_path == "/"

    def test_real_client_is_built_when_configured(self, tmp_path: Path) -> None:
        from crb.server.auth import AuthlibOidcClient

        app = create_app(make_settings(tmp_path, oidc=OIDC_SETTINGS))
        assert isinstance(app.state.oidc_client, AuthlibOidcClient)
        assert app.state.oidc_client.oidc.client_secret is not None
        assert "csecret" not in repr(app.state.oidc_client)


# --- D4 (assessment 2026-09-25): revocable sessions, bound CSRF, per-IP limit, OIDC role ---


def _oidc_login(app: Any, settings: Settings) -> TestClient:
    """One OIDC sign-in through the fake provider; returns the signed-in client (open — the
    caller closes it)."""
    c = TestClient(app)
    c.__enter__()
    c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
    pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
    r = c.get(
        f"{API_PREFIX}/auth/oidc/callback",
        params={"code": "good-code", "state": pending.state},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]
    return c


def _user_events(app: Any, action: str) -> list[Any]:
    from sqlalchemy import select

    from crb.store.models import Event

    with app.state.session_factory() as s:
        return list(
            s.execute(select(Event).where(Event.action == action).order_by(Event.seq)).scalars()
        )


class TestSessionRevocation:
    """A signed cookie is not a session the server can end — unless it carries a per-account
    nonce the server can rotate. Logout and "sign out everywhere" rotate it."""

    def test_logout_revokes_the_token_not_just_the_cookie(self, client: TestClient) -> None:
        login(client)
        stolen = client.cookies[SESSION_COOKIE]
        assert client.post(f"{API_PREFIX}/auth/logout").status_code == 204
        with TestClient(client.app) as thief:
            thief.cookies.set(SESSION_COOKIE, stolen)
            r = thief.get(f"{API_PREFIX}/auth/me")
            assert r.status_code == 401 and err(r)["code"] == "session_revoked"

    def test_logout_ends_every_session_of_the_account(self, client: TestClient) -> None:
        login(client)
        with TestClient(client.app) as laptop:
            login(laptop)
            assert laptop.get(f"{API_PREFIX}/auth/me").status_code == 200
            assert client.post(f"{API_PREFIX}/auth/logout").status_code == 204
            r = laptop.get(f"{API_PREFIX}/auth/me")
            assert r.status_code == 401 and err(r)["code"] == "session_revoked"
            login(laptop)  # signing in again is always possible
            assert laptop.get(f"{API_PREFIX}/auth/me").status_code == 200

    def test_admin_signs_a_user_out_everywhere(self, client: TestClient) -> None:
        login(client)
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "bob", "password": USER_PW, "role": "viewer"}
        )
        bob = r.json()["id"]
        with TestClient(client.app) as bob_client:
            login(bob_client, "bob", USER_PW)
            # a viewer may not sign anybody out
            r = bob_client.post(f"{API_PREFIX}/users/{bob}/sessions/revoke")
            assert r.status_code == 403
            r = client.post(f"{API_PREFIX}/users/{bob}/sessions/revoke")
            assert r.status_code == 200, r.text
            assert r.json()["id"] == bob
            r = bob_client.get(f"{API_PREFIX}/auth/me")
            assert r.status_code == 401 and err(r)["code"] == "session_revoked"
        # the admin's own session is untouched, and the act is on the account's trace
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 200
        (ev,) = _user_events(client.app, "user.sessions_revoked")
        assert ev.payload_json["target"] == bob
        assert client.post(f"{API_PREFIX}/users/nope/sessions/revoke").status_code == 404

    def test_an_oidc_account_can_be_signed_out_everywhere(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        # an OIDC account has no password to change: before the nonce, nothing but
        # deactivation could end its sessions
        app, _ = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        ann = _oidc_login(app, settings)
        try:
            ann_id = ann.get(f"{API_PREFIX}/auth/me").json()["id"]
            with TestClient(app) as admin:
                login(admin)
                r = admin.post(f"{API_PREFIX}/users/{ann_id}/sessions/revoke")
                assert r.status_code == 200, r.text
            r = ann.get(f"{API_PREFIX}/auth/me")
            assert r.status_code == 401 and err(r)["code"] == "session_revoked"
        finally:
            ann.__exit__(None, None, None)

    def test_the_upgrade_keeps_sessions_issued_before_the_nonce(self) -> None:
        # a users row migrated in with the empty nonce keeps the version it had, so the
        # upgrade does not sign every user out; the first rotation moves it
        import hashlib

        from crb.server.auth import credential_version, rotate_session_nonce
        from crb.store.models import User

        user = User(id="u1", subject="local:u", issuer="local", password_hash="$argon2id$x")
        user.session_nonce = ""
        before = hashlib.sha256(b"$argon2id$x").hexdigest()[:16]
        assert credential_version(user) == before
        rotate_session_nonce(user)
        assert user.session_nonce and credential_version(user) != before
        again = credential_version(user)
        rotate_session_nonce(user)
        assert credential_version(user) != again


class TestCsrfBoundToSession:
    """The CSRF token is HMAC(secret, uid, session version): an attacker who can plant a
    cookie (a sibling subdomain, a proxy) cannot choose a pair that passes."""

    def test_an_attacker_chosen_pair_is_refused(self, client: TestClient) -> None:
        login(client)
        client.cookies.set(CSRF_COOKIE, "attacker-chosen")
        client.headers["X-CSRF-Token"] = "attacker-chosen"
        r = client.post(
            f"{API_PREFIX}/users", json={"username": "x9", "password": USER_PW, "role": "viewer"}
        )
        assert r.status_code == 403 and err(r)["code"] == "csrf_failed"

    def test_the_token_is_the_session_hmac_and_dies_with_the_session(
        self, client: TestClient, settings: Settings
    ) -> None:
        from crb.server.auth import csrf_token_for, read_session_claims

        login(client)
        old = client.cookies[CSRF_COOKIE]
        uid, cv = read_session_claims(settings, client.cookies[SESSION_COOKIE])
        assert old == csrf_token_for(settings, uid, cv)
        assert client.get(f"{API_PREFIX}/auth/csrf").json()["token"] == old
        # a new session after logout has a new token; the old one no longer passes
        client.post(f"{API_PREFIX}/auth/logout")
        login(client)
        assert client.cookies[CSRF_COOKIE] != old
        r = client.post(
            f"{API_PREFIX}/users",
            json={"username": "x8", "password": USER_PW, "role": "viewer"},
            headers={"X-CSRF-Token": old},
        )
        assert r.status_code == 403 and err(r)["code"] == "csrf_failed"

    def test_another_accounts_token_is_refused(self, client: TestClient) -> None:
        login(client)
        client.post(
            f"{API_PREFIX}/users", json={"username": "eve", "password": USER_PW, "role": "admin"}
        )
        with TestClient(client.app) as eve:
            login(eve, "eve", USER_PW)
            eves = eve.cookies[CSRF_COOKIE]
        # the attacker plants their own valid pair in the victim's browser
        client.cookies.set(CSRF_COOKIE, eves)
        r = client.post(
            f"{API_PREFIX}/users",
            json={"username": "x7", "password": USER_PW, "role": "viewer"},
            headers={"X-CSRF-Token": eves},
        )
        assert r.status_code == 403 and err(r)["code"] == "csrf_failed"

    def test_secure_deployment_uses_host_prefixed_cookie_names(self, tmp_path: Path) -> None:
        app = create_app(make_settings(tmp_path, cookie_secure=True))
        with TestClient(app, base_url="https://testserver") as c:
            r = c.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
            assert r.status_code == 200, r.text
            set_cookies = r.headers.get_list("set-cookie")
            names = {v.split("=", 1)[0] for v in set_cookies}
            assert names == {"__Host-crb_session", "__Host-crb_csrf"}, names
            for v in set_cookies:
                low = v.lower()
                assert "secure" in low and "path=/" in low and "domain=" not in low
            c.headers["X-CSRF-Token"] = c.cookies["__Host-crb_csrf"]
            r = c.post(
                f"{API_PREFIX}/users",
                json={"username": "x6", "password": USER_PW, "role": "viewer"},
            )
            assert r.status_code == 201, r.text
            # a plain-named session cookie (plantable from a sibling host) is not a session
            token = c.cookies["__Host-crb_session"]
            c.cookies.clear()
            c.cookies.set("crb_session", token)
            assert c.get(f"{API_PREFIX}/auth/me").status_code == 401


class TestLoginRateLimitPerIp:
    """One address guessing across many usernames is bounded too, not only one username."""

    def test_the_limiter_has_an_ip_bucket(self) -> None:
        clock = {"t": 1000.0}
        rl = LoginRateLimiter(limit=5, window_s=60, clock=lambda: clock["t"], ip_limit=20)
        for i in range(20):
            rl.record_failure(f"user-{i}", "ip")
        # no single username reached 5, but the address reached 20
        assert rl.retry_after("root", "ip") == pytest.approx(60.0)
        assert rl.retry_after("root", "other-ip") is None
        # a success on one account does not clear the address's bucket
        rl.reset("user-0", "ip")
        assert rl.retry_after("root", "ip") is not None
        clock["t"] += 61
        assert rl.retry_after("root", "ip") is None

    def test_spraying_usernames_from_one_address_is_rate_limited(self, client: TestClient) -> None:
        for i in range(20):
            r = client.post(
                f"{API_PREFIX}/auth/login", json={"username": f"guess{i}", "password": "bad-pw"}
            )
            assert r.status_code == 401, (i, r.text)
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
        assert r.status_code == 429 and err(r)["code"] == "rate_limited"


class TestOidcRoleSource:
    """The IdP's claims set the role on first sign-in; afterwards an admin's change stands,
    unless the deployment says the IdP is the source of truth (``ROLE_FROM_CLAIMS=always``),
    in which case every override is recorded."""

    def _demote(self, app: Any, user_id: str) -> None:
        with TestClient(app) as admin:
            login(admin)
            r = admin.put(f"{API_PREFIX}/users/{user_id}/role", json={"role": "viewer"})
            assert r.status_code == 200, r.text

    def test_an_admins_change_survives_the_next_sign_in(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, _ = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        first = _oidc_login(app, settings)
        me = first.get(f"{API_PREFIX}/auth/me").json()
        first.__exit__(None, None, None)
        assert me["role"] == "operator"  # first sign-in: the claims decide
        self._demote(app, me["id"])
        again = _oidc_login(app, settings)
        try:
            assert again.get(f"{API_PREFIX}/auth/me").json()["role"] == "viewer"
        finally:
            again.__exit__(None, None, None)
        assert _user_events(app, "user.role_overridden") == []

    def test_always_lets_the_claims_win_and_records_it(self, tmp_path: Path) -> None:
        fake = FakeOidc({"sub": "entra-oid-9", "name": "Bo", "roles": ["crb-operators"]})
        settings = make_settings(tmp_path, oidc={**OIDC_SETTINGS, "role_from_claims": "always"})
        app = create_app(settings, oidc_client=fake)
        first = _oidc_login(app, settings)
        uid = first.get(f"{API_PREFIX}/auth/me").json()["id"]
        first.__exit__(None, None, None)
        self._demote(app, uid)
        again = _oidc_login(app, settings)
        try:
            assert again.get(f"{API_PREFIX}/auth/me").json()["role"] == "operator"
        finally:
            again.__exit__(None, None, None)
        (ev,) = _user_events(app, "user.role_overridden")
        assert ev.payload_json["target"] == uid
        assert ev.payload_json["from_role"] == "viewer" and ev.payload_json["role"] == "operator"

    def test_role_from_claims_accepts_only_the_two_values(self) -> None:
        assert OidcSettings().role_from_claims == "first_login"
        assert OidcSettings(role_from_claims="always").role_from_claims == "always"
        with pytest.raises(ValueError):
            OidcSettings(role_from_claims="sometimes")
