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
