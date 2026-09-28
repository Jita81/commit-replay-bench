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
              manage users, the last-admin guard, and user lists never include hashes; the
              OIDC flow — state + PKCE cookie on start, a mapped user on callback, and every
              callback failure (state missing or forged, a provider refusal, a failed exchange,
              a disabled account) a redirect to ``/login?error=<code>`` with no provider words;
              that every sign-in and refused sign-in is a ``user.*`` event (a refused name that
              is no account recorded without the name; a lost ``seq`` race retried, and a
              second writer reading the trail only after the first committed); that a burst
              of guesses sent at once is held to five per account and twenty per address and
              a right password behind it is refused, at sign-in and at the self password
              change (AUTH-1); that ``role_from_claims=always`` never demotes the last active
              admin and every role-changing path asks the one guard (AUTH-2); that a logout
              is ``user.sessions_ended`` (EI-8); and that /login's session sentence matches
              ``session_ttl`` (P-148).
How:          ``create_app(oidc_client=FakeOidc(...))`` — no network; a ``TestClient`` per
              settings variant.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/auth.py (under test), src/crb/server/routes/auth.py (the login /
              logout / users routes), src/crb/server/settings.py (``OidcSettings``),
              src/crb/store/models.py (the ``users`` table), docs/SECURITY.md (authentication
              and authorisation, §3.4), docs/DEPLOYMENT.md (Entra ID → ``CRB_OIDC__*``, §4.1)
Tested by:    tests/test_server_auth.py
Touch when:   never for a new repository; a role is added to the ladder (the map and the RBAC
              matrices in every route suite); the OIDC claims mapping changes; never so that a
              mutating route skips CSRF.
"""

from __future__ import annotations

import contextlib
import os
import threading
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
    LoginRateLimited,
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
        for _ in range(5):
            rl.acquire("u", "ip")  # five attempts that never succeed: five failures
        with pytest.raises(LoginRateLimited) as limited:
            rl.acquire("u", "ip")
        assert limited.value.retry_after_s == pytest.approx(60.0)
        rl.acquire("u", "other-ip")  # keyed by (user, ip)
        rl.acquire("v", "ip")
        clock["t"] += 61
        for _ in range(4):
            rl.acquire("u", "ip")
        rl.succeed(rl.acquire("u", "ip"))  # a success forgets the key's failures
        rl.acquire("u", "ip")

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
            assert r.status_code == 302
            assert r.headers["location"] == "/login?error=oidc_state_missing"
        # Upsert by (issuer, subject): a second login with new groups refreshes the profile
        # but not the role — the claims set it on the FIRST sign-in only (D4; the
        # ``always`` mode is TestOidcRoleSource's)
        fake.claims["roles"] = ["crb-approvers"]
        fake.claims["groups"] = ["grp-crb-admins"]
        fake.claims["name"] = "Ann Renamed"
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": pending.state},
                follow_redirects=False,
            )
            assert r.status_code == 302 and r.headers["location"] == "/"
            me = c.get(f"{API_PREFIX}/auth/me").json()
            assert me["role"] == "operator" and me["display_name"] == "Ann Renamed"
        with TestClient(app) as admin:
            login(admin)
            users = admin.get(f"{API_PREFIX}/users").json()
            oidc_users = [u for u in users["items"] if u["issuer"] == ISSUER]
            assert len(oidc_users) == 1 and oidc_users[0]["subject"] == "entra-oid-123"

    # A failed callback (state missing or forged, a provider refusal, a failed exchange, a
    # disabled account) returns to /login with its code: TestOidcFailureReturnsToLogin.

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

    def test_a_logout_is_one_event_on_the_accounts_trail(self, client: TestClient) -> None:
        """EI-8 (the operator's security review, 2026-09-27): a logout rotates the account's
        nonce and ends its sessions on every device — an account change — yet wrote no
        event, while an admin's "sign out everywhere" did. It is ``user.sessions_ended``
        with the account as actor; a logout that ends nothing (no session, a stale or
        forged one) records nothing."""
        login(client)
        me = client.get(f"{API_PREFIX}/auth/me").json()["id"]
        assert client.post(f"{API_PREFIX}/auth/logout").status_code == 204
        (ev,) = _user_events(client.app, "user.sessions_ended")
        assert ev.actor == me and ev.payload_json["target"] == me
        assert ev.payload_json["by"] == "self"
        # the cookie is gone, and a second logout ends nothing: no second event
        assert client.post(f"{API_PREFIX}/auth/logout").status_code == 204
        assert len(_user_events(client.app, "user.sessions_ended")) == 1

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


#: Cookies a browser really sends that a strict RFC 6265 parser rejects outright: a space,
#: a JSON value, a backslash, a consent banner's date, a non-ASCII byte. Any one of them,
#: planted by a sibling host with ``Domain=``, must not hide the session from the CSRF check.
_MALFORMED_COOKIES = [
    pytest.param(b"junk=a b", id="space"),
    pytest.param(b'prefs={"theme": "dark"}', id="json"),
    pytest.param(b"bs=a\\b", id="backslash"),
    pytest.param(
        b"OptanonConsent=isGpcEnabled=0&datestamp=Thu Sep 25 2026 10:00:00 GMT+0100",
        id="consent-date",
    ),
    pytest.param("lang=café".encode("latin-1"), id="non-ascii"),
]


class TestCsrfSeesTheSameCookiesAsAuth:
    """The CSRF middleware and the auth dependency must read the SAME session cookie from the
    SAME ``Cookie`` header. If the middleware's parser gives up on a header the auth parser
    accepts, the check is skipped while the request still authenticates — a forged POST
    with no CSRF token then succeeds."""

    @pytest.mark.parametrize("secure", [False, True], ids=["dev", "secure"])
    @pytest.mark.parametrize("position", ["before", "after"])
    @pytest.mark.parametrize("junk", _MALFORMED_COOKIES)
    def test_a_malformed_neighbour_cookie_does_not_skip_the_check(
        self, tmp_path: Path, secure: bool, position: str, junk: bytes
    ) -> None:
        app = create_app(make_settings(tmp_path, cookie_secure=secure))
        base = "https://testserver" if secure else "http://testserver"
        name = ("__Host-" if secure else "") + SESSION_COOKIE
        with TestClient(app, base_url=base) as victim:
            r = victim.post(
                f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW}
            )
            assert r.status_code == 200, r.text
            session = victim.cookies[name]
            csrf = victim.cookies[("__Host-" if secure else "") + CSRF_COOKIE]
        pair = f"{name}={session}".encode()
        header = b"; ".join([junk, pair] if position == "before" else [pair, junk])
        body = {"username": "forged", "password": USER_PW, "role": "admin"}
        with TestClient(app, base_url=base) as attacker:
            # the auth dependency still sees the session through the junk ...
            me = attacker.get(f"{API_PREFIX}/auth/me", headers={"cookie": header})
            assert me.status_code == 200, me.text
            # ... so a forged POST without the token must be refused ...
            r = attacker.post(f"{API_PREFIX}/users", json=body, headers={"cookie": header})
            assert r.status_code == 403, r.text
            assert err(r)["code"] == "csrf_failed"
            # ... and the real page, which sends the token, is not locked out by the junk
            ok = attacker.post(
                f"{API_PREFIX}/users",
                json=body,
                headers={"cookie": header, "X-CSRF-Token": csrf},
            )
            assert ok.status_code == 201, ok.text

    def test_the_server_has_one_cookie_parser(self) -> None:
        """Prevention: a second, stricter parser anywhere in the server is how the two
        readers diverged. Every server module reads cookies through Starlette's parser
        (``request.cookies`` / :func:`crb.server.auth.request_cookies`), never its own."""
        import crb.server

        root = Path(crb.server.__file__).parent
        offenders = sorted(
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if "SimpleCookie" in p.read_text(encoding="utf-8")
        )
        assert offenders == [], f"a second cookie parser is back in: {offenders}"


class TestLoginRateLimitPerIp:
    """One address guessing across many usernames is bounded too, not only one username."""

    def test_the_limiter_has_an_ip_bucket(self) -> None:
        clock = {"t": 1000.0}
        rl = LoginRateLimiter(limit=5, window_s=60, clock=lambda: clock["t"], ip_limit=20)
        first = rl.acquire("user-0", "ip")
        for i in range(1, 20):
            rl.acquire(f"user-{i}", "ip")
        # no single username reached 5, but the address reached 20
        with pytest.raises(LoginRateLimited) as limited:
            rl.acquire("root", "ip")
        assert limited.value.retry_after_s == pytest.approx(60.0)
        rl.acquire("root", "other-ip")
        # a success on one account gives back its own slot and no other: one more attempt
        rl.succeed(first)
        rl.acquire("root", "ip")
        with pytest.raises(LoginRateLimited):
            rl.acquire("root", "ip")
        clock["t"] += 61
        rl.acquire("root", "ip")

    def test_spraying_usernames_from_one_address_is_rate_limited(self, client: TestClient) -> None:
        for i in range(20):
            r = client.post(
                f"{API_PREFIX}/auth/login", json={"username": f"guess{i}", "password": "bad-pw"}
            )
            assert r.status_code == 401, (i, r.text)
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
        assert r.status_code == 429 and err(r)["code"] == "rate_limited"


def _held_guesses(
    monkeypatch: pytest.MonkeyPatch, target: str, correct: str, *, hold_s: float = 10.0
) -> tuple[list[str], threading.Event]:
    """Patch the password check ``target`` (``module:function``) so each evaluation is
    recorded and a WRONG guess is held in flight until the returned event is set (or
    ``hold_s`` passes) — the argon2 verify's window, widened so a burst's interleaving is the
    test's, not the host's. A correct password is never held."""
    import importlib

    module_name, fn_name = target.split(":")
    module = importlib.import_module(module_name)
    real = getattr(module, fn_name)
    evaluated: list[str] = []
    lock = threading.Lock()
    release = threading.Event()

    def held(*args: Any) -> Any:
        with lock:
            evaluated.append(str(args[1]) if fn_name == "authenticate_local" else "me")
        if args[-1] != correct:
            release.wait(hold_s)
        return real(*args)

    monkeypatch.setattr(module, fn_name, held)
    return evaluated, release


def _wait_for(pred: Any, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not pred():
        assert time.monotonic() < deadline, "the burst never reached the password check"
        time.sleep(0.01)


class TestLoginLimiterUnderConcurrency:
    """AUTH-1 (the operator's security review, 2026-09-27): the limiter was read before the
    ~50 ms argon2 verify and written after it, so a concurrent burst from one address had
    13-39 guesses evaluated in a second against a cap of five, and a correct guess inside
    the burst signed in. The check and the reservation are now one step (``acquire``)."""

    def test_the_limiter_grants_exactly_the_cap_to_a_simultaneous_burst(self) -> None:
        rl = LoginRateLimiter(limit=5, window_s=60, ip_limit=20)
        granted: list[bool] = []

        def burst(usernames: list[str]) -> None:
            start = threading.Barrier(len(usernames))

            def one(username: str) -> None:
                start.wait()
                try:
                    rl.acquire(username, "ip")
                except LoginRateLimited:
                    granted.append(False)
                else:
                    granted.append(True)

            threads = [threading.Thread(target=one, args=(u,)) for u in usernames]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        burst(["u"] * 50)
        assert granted.count(True) == 5
        granted.clear()
        # the address's bucket is bounded the same way across usernames
        burst([f"v{i % 25}" for i in range(50)])
        assert granted.count(True) == 15  # twenty per address, five already taken by "u"

    def test_a_success_releases_its_own_slot_and_nothing_else(self) -> None:
        clock = {"t": 1000.0}
        rl = LoginRateLimiter(limit=5, window_s=60, clock=lambda: clock["t"], ip_limit=20)
        for _ in range(30):  # thirty good sign-ins from one address are never limited
            rl.succeed(rl.acquire("root", "ip"))
        for i in range(20):
            rl.acquire(f"user-{i}", "ip")  # twenty failures: the address is full
        with pytest.raises(LoginRateLimited) as full:
            rl.acquire("root", "ip")
        assert full.value.retry_after_s == pytest.approx(60.0)
        clock["t"] += 61
        rl.acquire("root", "ip")

    def test_a_correct_password_behind_five_guesses_in_flight_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        evaluated, release = _held_guesses(
            monkeypatch, "crb.server.routes.auth:authenticate_local", ROOT_PW
        )
        codes: list[int] = []

        def guess(n: int) -> None:
            r = client.post(
                f"{API_PREFIX}/auth/login", json={"username": "root", "password": f"wrong-{n}"}
            )
            codes.append(r.status_code)

        threads = [threading.Thread(target=guess, args=(n,)) for n in range(5)]
        try:
            for t in threads:
                t.start()
            _wait_for(lambda: len(evaluated) == 5)
            r = client.post(
                f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW}
            )
            assert r.status_code == 429, r.text  # the sixth attempt, though it is right
            assert err(r)["code"] == "rate_limited"
        finally:
            release.set()
            for t in threads:
                t.join()
        assert sorted(codes) == [401] * 5
        assert len(evaluated) == 5  # the correct password was never evaluated

    def test_a_burst_evaluates_at_most_five_per_account_and_twenty_per_address(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from concurrent.futures import ThreadPoolExecutor

        evaluated, release = _held_guesses(
            monkeypatch, "crb.server.routes.auth:authenticate_local", ROOT_PW, hold_s=0.3
        )

        def guess(username: str, n: int) -> int:
            r = client.post(
                f"{API_PREFIX}/auth/login", json={"username": username, "password": f"bad-{n}"}
            )
            return r.status_code

        with ThreadPoolExecutor(max_workers=40) as pool:
            codes = list(pool.map(guess, ["root"] * 40, range(40)))
        assert evaluated.count("root") <= 5, len(evaluated)
        assert codes.count(401) == evaluated.count("root")
        assert codes.count(429) == 40 - codes.count(401)
        with ThreadPoolExecutor(max_workers=40) as pool:
            list(pool.map(guess, [f"spray{i % 20}" for i in range(40)], range(40)))
        assert len(evaluated) <= 20, len(evaluated)  # one address, every username
        release.set()
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
        assert r.status_code == 429

    def test_the_audited_commit_reads_a_trail_only_after_the_last_writer_committed(
        self, client: TestClient
    ) -> None:
        """Found by the burst test above: refused sign-ins released at one moment all write
        to the one shared unknown-account trail; each read the trail's last ``seq`` before
        the others committed, and the audited commit's three retries ran out, answering 500.
        The events lock is now taken before the read, so a second writer reads only after the
        first committed and neither ever retries. Staged: the first writer waits after its
        read for the second to read too (a barrier that times out when the lock holds the
        second back)."""
        from sqlalchemy import func, select

        from crb.server.routes.runs import append_system_event, commit_audited
        from crb.store.models import Event

        factory = client.app.state.session_factory
        both_read = threading.Barrier(2, timeout=1.5)
        runs = {"a": 0, "b": 0}
        failures: list[BaseException] = []

        def writer(name: str) -> None:
            with factory() as db:

                def write() -> None:
                    runs[name] += 1
                    db.execute(select(func.max(Event.seq)).where(Event.trace_id == "t-audit"))
                    with contextlib.suppress(threading.BrokenBarrierError):
                        both_read.wait()
                    append_system_event(
                        db, trace_id="t-audit", action="user.login_failed", payload={"w": name}
                    )

                try:
                    commit_audited(db, write)
                except BaseException as exc:  # a lost race on every retry
                    failures.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert failures == []
        assert runs == {"a": 1, "b": 1}  # neither writer read a stale seq and retried
        with factory() as db:
            seqs = sorted(
                db.execute(select(Event.seq).where(Event.trace_id == "t-audit")).scalars()
            )
        assert seqs == [1, 2]

    def test_a_borrowed_session_guessing_its_current_password_is_bounded_the_same_way(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        login(client)
        evaluated, release = _held_guesses(
            monkeypatch, "crb.server.routes.admin:verify_password", ROOT_PW
        )
        new_pw = "a-brand-new-long-password"
        codes: list[int] = []

        def guess(n: int) -> None:
            r = client.put(
                f"{API_PREFIX}/users/me/password",
                json={"current_password": f"wrong-guess-{n}", "new_password": new_pw},
            )
            codes.append(r.status_code)

        threads = [threading.Thread(target=guess, args=(n,)) for n in range(5)]
        try:
            for t in threads:
                t.start()
            _wait_for(lambda: len(evaluated) == 5)
            r = client.put(
                f"{API_PREFIX}/users/me/password",
                json={"current_password": ROOT_PW, "new_password": new_pw},
            )
            assert r.status_code == 429, r.text
        finally:
            release.set()
            for t in threads:
                t.join()
        assert sorted(codes) == [401] * 5
        assert len(evaluated) == 5


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

    def test_always_never_demotes_the_last_active_admin(self, tmp_path: Path) -> None:
        """AUTH-2 (the operator's security review, 2026-09-27): under ``always`` a sign-in
        whose claims no longer map to admin (a directory clean-up, a group-id typo) demoted
        the only active admin, leaving a deployment nobody could administer. The demotion is
        refused, the role kept, and the conflict recorded; with a second admin the claims win."""
        from crb.server.auth import count_active_admins

        fake = FakeOidc({"sub": "entra-oid-1", "name": "Ada", "groups": ["grp-crb-admins"]})
        settings = make_settings(
            tmp_path, bootstrap_admin={}, oidc={**OIDC_SETTINGS, "role_from_claims": "always"}
        )
        app = create_app(settings, oidc_client=fake)
        first = _oidc_login(app, settings)
        uid = first.get(f"{API_PREFIX}/auth/me").json()["id"]
        assert first.get(f"{API_PREFIX}/auth/me").json()["role"] == "admin"
        first.__exit__(None, None, None)
        fake.claims["groups"] = []  # the provider no longer says admin
        again = _oidc_login(app, settings)
        try:
            assert again.get(f"{API_PREFIX}/auth/me").json()["role"] == "admin"
            with app.state.session_factory() as s:
                assert count_active_admins(s) == 1
            assert _user_events(app, "user.role_overridden") == []
            (ev,) = _user_events(app, "user.role_override_refused")
            assert ev.actor == uid and ev.payload_json["target"] == uid
            assert ev.payload_json["role"] == "admin"
            assert ev.payload_json["from_claims"] == "viewer"
            assert ev.payload_json["reason"] == "last_admin"
            assert ev.payload_json["by"] == "oidc_claims" and ev.payload_json["issuer"] == ISSUER
            # a second active admin: the provider is the source of truth again
            r = again.post(
                f"{API_PREFIX}/users",
                json={"username": "second", "password": USER_PW, "role": "admin"},
            )
            assert r.status_code == 201, r.text
        finally:
            again.__exit__(None, None, None)
        third = _oidc_login(app, settings)
        try:
            assert third.get(f"{API_PREFIX}/auth/me").json()["role"] == "viewer"
        finally:
            third.__exit__(None, None, None)
        (ev,) = _user_events(app, "user.role_overridden")
        assert ev.payload_json["from_role"] == "admin" and ev.payload_json["role"] == "viewer"

    def test_an_admin_nobody_can_sign_in_as_never_counts_as_the_other_admin(
        self, tmp_path: Path
    ) -> None:
        """AUTH-2's residual (the skeptic, 2026-09-27): the recommended production setup keeps
        the bootstrap admin active with local sign-in off (DEPLOYMENT §8), so the last-admin
        count saw two admins while only the OIDC one could sign in — and the claims, the
        role route and the active route could each strip that one. The count is of admins
        who can sign in to THIS deployment; the stranded local admin is not one of them."""
        fake = FakeOidc({"sub": "entra-oid-1", "name": "Ada", "groups": ["grp-crb-admins"]})
        settings = make_settings(
            tmp_path,
            local_auth_enabled=False,  # the bootstrap root stays active; nobody can use it
            oidc={**OIDC_SETTINGS, "role_from_claims": "always"},
        )
        app = create_app(settings, oidc_client=fake)
        first = _oidc_login(app, settings)
        try:
            me = first.get(f"{API_PREFIX}/auth/me").json()
            assert me["role"] == "admin"
            # the role route and the active route refuse to strip the one usable admin
            for path, body in (
                ("role", {"role": "viewer"}),
                ("role", {"role": "admin", "active": False}),
                ("active", {"active": False}),
            ):
                r = first.put(f"{API_PREFIX}/users/{me['id']}/{path}", json=body)
                assert r.status_code == 409, (path, body, r.text)
                assert r.json()["error"]["code"] == "last_admin"
        finally:
            first.__exit__(None, None, None)
        fake.claims["groups"] = []  # the provider no longer says admin
        again = _oidc_login(app, settings)
        try:
            assert again.get(f"{API_PREFIX}/auth/me").json()["role"] == "admin"
            # deactivating the stranded local admin is no lockout, so it is allowed
            users = again.get(f"{API_PREFIX}/users").json()["items"]
            root = next(u for u in users if u["username"] == "root")
            r = again.put(f"{API_PREFIX}/users/{root['id']}/active", json={"active": False})
            assert r.status_code == 200, r.text
        finally:
            again.__exit__(None, None, None)
        (ev,) = _user_events(app, "user.role_override_refused")
        assert ev.payload_json["target"] == me["id"] and ev.payload_json["reason"] == "last_admin"
        assert _user_events(app, "user.role_overridden") == []

    def test_the_last_admin_rule_counts_only_admins_who_can_sign_in(self, tmp_path: Path) -> None:
        """The unit under AUTH-2's residual: ``SignInPaths`` admits a local account only while
        local sign-in is on and an OIDC account only from the configured issuer; the rule
        refuses to take the last such admin, and still never leaves zero active admins."""
        from sqlalchemy import select

        from crb.server.auth import SignInPaths, local_subject, would_orphan_admins
        from crb.store.models import User

        app = create_app(make_settings(tmp_path))
        with TestClient(app), app.state.session_factory() as db:
            root = db.execute(
                select(User).where(User.subject == local_subject("root"))
            ).scalar_one()
            ada = User(id="u-ada", subject="oid-ada", issuer=ISSUER + "/", role="admin")
            old = User(id="u-old", subject="oid-old", issuer="https://old.example/t", role="admin")
            db.add_all([ada, old])
            db.flush()
            oidc_only = SignInPaths(local=False, oidc_issuers=frozenset({ISSUER}))
            local_only = SignInPaths(local=True, oidc_issuers=frozenset())
            assert oidc_only.admits(ada) and not oidc_only.admits(root)
            assert not oidc_only.admits(old) and local_only.admits(root)
            # the one usable admin, whichever path it signs in by
            assert would_orphan_admins(db, ada, role="viewer", active=True, sign_in=oidc_only)
            assert would_orphan_admins(db, root, role="admin", active=False, sign_in=local_only)
            # an admin nobody can sign in as can go; so can anyone while two can sign in
            assert not would_orphan_admins(db, root, role="viewer", active=True, sign_in=oidc_only)
            both = SignInPaths.of(make_settings(tmp_path, oidc=OIDC_SETTINGS))
            assert both.admits(ada) and both.admits(root)
            assert not would_orphan_admins(db, ada, role="viewer", active=True, sign_in=both)
            # unknown paths (the break-glass CLI): every active admin counts, as before
            assert not would_orphan_admins(db, ada, role="viewer", active=True, sign_in=None)
            db.rollback()

    def test_every_role_change_path_uses_the_one_last_admin_guard(self) -> None:
        """Prevention (AUTH-2, AUTH-3): the last-admin rule lived in two places and the OIDC
        upsert, a third path that changes a role, had none; and the role route wrote the
        active flag itself, so a deactivation there ended no session. In ``crb``, a function
        that assigns ``.role`` asks ``would_orphan_admins``; only ``set_account_active``
        assigns ``.active``, and a function that calls it asks ``would_orphan_admins`` too
        (``create_local_user`` and a new OIDC account set a role on a row nobody else
        holds, as a constructor keyword)."""
        import ast

        import crb.server

        root = Path(crb.server.__file__).parents[1]  # src/crb
        unguarded: list[str] = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                assigns = {
                    t.attr
                    for node in ast.walk(fn)
                    if isinstance(node, ast.Assign)
                    for t in node.targets
                    if isinstance(t, ast.Attribute) and t.attr in {"role", "active"}
                }
                calls = {
                    getattr(n.func, "id", getattr(n.func, "attr", ""))
                    for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                }
                where = f"{path.relative_to(root)}::{fn.name}"
                if "active" in assigns and fn.name != "set_account_active":
                    unguarded.append(f"{where} writes .active itself")
                changes = "role" in assigns or "set_account_active" in calls
                if changes and "would_orphan_admins" not in calls:
                    unguarded.append(f"{where} skips the last-admin guard")
        assert unguarded == [], unguarded

    def test_role_from_claims_accepts_only_the_two_values(self) -> None:
        assert OidcSettings().role_from_claims == "first_login"
        assert OidcSettings(role_from_claims="always").role_from_claims == "always"
        with pytest.raises(ValueError):
            OidcSettings(role_from_claims="sometimes")


# --- a sign-in is an audit event; an OIDC failure goes back to /login (G-190, G-188) -------


def _trail(app: Any, username: str) -> list[Any]:
    """The ``user.*`` events on ``username``'s own trace, oldest first."""
    from sqlalchemy import select

    from crb.server.routes.admin import user_trace_id
    from crb.store.models import Event, User

    with app.state.session_factory() as s:
        user = s.execute(select(User).where(User.subject == f"local:{username}")).scalar_one()
        rows = list(
            s.execute(
                select(Event).where(Event.trace_id == user_trace_id(user.id)).order_by(Event.seq)
            ).scalars()
        )
        s.expunge_all()
        return rows


def _racing_user_login(calls: dict[str, int], *, lose_times: int) -> Any:
    """A ``record_user_event`` that stages a lost ``seq`` race on the first ``lose_times``
    ``user.login`` writes: it adds a twin row with the same ``(trace_id, seq)`` to the
    transaction, so the commit breaks ``uq_events_trace_seq`` exactly as a concurrent
    sign-in's would."""
    from crb.server.routes.admin import record_user_event as real_record
    from crb.store.models import Event

    def racing(db: Any, **kw: Any) -> None:
        real_record(db, **kw)
        if kw["action"] != "user.login":
            return
        calls["login"] += 1
        if calls["login"] <= lose_times:
            (mine,) = [o for o in db.new if isinstance(o, Event) and o.action == "user.login"]
            twin = Event(
                **{c.name: getattr(mine, c.name) for c in Event.__table__.columns if c.name != "id"}
            )
            twin.event_id = "f" * 32
            db.add(twin)

    return racing


class TestSignInIsAudited:
    """G-190: who signed in, and who tried, is on the account's own trail — the History the
    Users card renders — not only in the server log."""

    def test_a_local_sign_in_writes_user_login_with_the_account_as_actor(
        self, client: TestClient
    ) -> None:
        login(client)
        app = client.app
        (ev,) = [e for e in _trail(app, "root") if e.action.startswith("user.login")]
        assert ev.action == "user.login"
        assert ev.actor == ev.payload_json["target"]
        assert ev.payload_json["method"] == "local"
        assert ev.payload_json["username"] == "root"

    def test_a_failed_sign_in_to_an_account_is_recorded_without_the_password(
        self, client: TestClient
    ) -> None:
        r = client.post(
            f"{API_PREFIX}/auth/login", json={"username": "root", "password": "wrong-password-1"}
        )
        assert r.status_code == 401
        evs = [e for e in _trail(client.app, "root") if e.action.startswith("user.login")]
        assert [e.action for e in evs] == ["user.login_failed"]
        assert evs[0].actor == "anonymous"
        assert evs[0].payload_json["method"] == "local"
        blob = repr(evs[0].payload_json) + evs[0].error_message
        assert "wrong-password-1" not in blob and "argon2" not in blob

    def test_an_unknown_username_is_counted_but_never_stored(self, client: TestClient) -> None:
        """A person who types their password into the username box must not have it written
        to the audit table: the event carries no name. It is still written, so a refusal
        costs the same whether or not the account exists."""
        from sqlalchemy import select

        from crb.store.models import Event

        typed = "my-secret-typed-here"
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": typed, "password": "x" * 12})
        assert r.status_code == 401
        with client.app.state.session_factory() as s:
            evs = list(
                s.execute(select(Event).where(Event.action == "user.login_failed")).scalars()
            )
            assert len(evs) == 1
            assert evs[0].payload_json == {"method": "local", "reason": "unknown_account"}
            assert typed not in repr(evs[0].payload_json) + evs[0].error_message

    def test_a_lost_race_for_the_trace_seq_is_retried_not_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two sign-ins to one account can read the same last ``seq`` on its trail; the
        loser's commit breaks the unique ``(trace_id, seq)``. The sign-in rolls back and
        writes again rather than answering a 500 (DL-068). The race is staged by adding a
        second row with the same ``(trace_id, seq)`` to the first attempt's transaction."""
        import crb.server.routes.auth as routes_auth
        from crb.server.routes.admin import record_user_event as real_record
        from crb.store.models import Event

        calls = {"n": 0}

        def racing(db: Any, **kw: Any) -> None:
            real_record(db, **kw)
            calls["n"] += 1
            if calls["n"] == 1:
                (mine,) = [o for o in db.new if isinstance(o, Event)]
                twin = Event(
                    **{
                        c.name: getattr(mine, c.name)
                        for c in Event.__table__.columns
                        if c.name != "id"
                    }
                )
                twin.event_id = "f" * 32
                db.add(twin)

        monkeypatch.setattr(routes_auth, "record_user_event", racing)
        login(client)
        assert calls["n"] == 2
        actions = [e.action for e in _trail(client.app, "root")]
        assert actions.count("user.login") == 1

    def test_an_unknown_username_never_reaches_the_server_log(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A password typed into the username box must not be stored anywhere we write —
        not the audit table (above) and not the server log either. A name that is a local
        account is logged (an operator needs it); any other is logged as unknown."""
        import logging

        caplog.set_level(logging.DEBUG)
        typed = "Summer2026-my-real-password"
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": typed, "password": "x" * 12})
        assert r.status_code == 401
        leaked = [rec for rec in caplog.records if typed in repr(vars(rec))]
        assert not leaked, [(rec.name, rec.getMessage()) for rec in leaked]
        client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": "x" * 12})
        named = [rec for rec in caplog.records if getattr(rec, "username", None) == "root"]
        assert named, "a failed sign-in to a real account still names the account in the log"

    def test_an_oidc_sign_in_that_loses_the_seq_race_is_retried_not_refused(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DL-068 (3) holds for the organisation door too: the callback's ``user.login`` is
        written through the retrying commit, so a lost race is written again, not a 500."""
        import crb.server.routes.auth as routes_auth

        calls = {"login": 0}
        monkeypatch.setattr(
            routes_auth, "record_user_event", _racing_user_login(calls, lose_times=1)
        )
        app, _ = oidc_app
        c = _oidc_login(app, make_settings(tmp_path, oidc=OIDC_SETTINGS))
        try:
            me = c.get(f"{API_PREFIX}/auth/me").json()
        finally:
            c.__exit__(None, None, None)
        assert calls["login"] == 2
        evs = _user_events(app, "user.login")
        assert len(evs) == 1 and evs[0].actor == me["id"]

    def test_an_oidc_sign_in_that_keeps_losing_returns_to_login_not_a_500(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DL-068 (4): every callback failure is a redirect. A race lost on every attempt
        lands on ``/login?error=oidc_failed`` with no session, never a raw 500."""
        import crb.server.routes.auth as routes_auth

        calls = {"login": 0}
        monkeypatch.setattr(
            routes_auth, "record_user_event", _racing_user_login(calls, lose_times=99)
        )
        app, _ = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        with TestClient(app, raise_server_exceptions=False) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start?next=/runs", follow_redirects=False)
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": pending.state},
                follow_redirects=False,
            )
            assert r.status_code == 302, r.text
            loc = urlparse(r.headers["location"])
            assert loc.path == "/login"
            assert parse_qs(loc.query) == {"error": ["oidc_failed"], "next": ["/runs"]}
            assert SESSION_COOKIE not in c.cookies
        assert _user_events(app, "user.login") == []

    def test_a_rate_limited_attempt_writes_no_event(self, client: TestClient) -> None:
        for _ in range(5):
            client.post(
                f"{API_PREFIX}/auth/login", json={"username": "root", "password": "bad-password"}
            )
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
        assert r.status_code == 429
        evs = [e for e in _trail(client.app, "root") if e.action.startswith("user.login")]
        assert [e.action for e in evs] == ["user.login_failed"] * 5

    def test_an_oidc_sign_in_writes_user_login(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, _ = oidc_app
        c = _oidc_login(app, make_settings(tmp_path, oidc=OIDC_SETTINGS))
        try:
            me = c.get(f"{API_PREFIX}/auth/me").json()
        finally:
            c.__exit__(None, None, None)
        evs = _user_events(app, "user.login")
        assert len(evs) == 1 and evs[0].actor == me["id"]
        assert evs[0].payload_json["method"] == "oidc"

    def test_api_md_lists_both_events(self) -> None:
        text = Path("docs/API.md").read_text(encoding="utf-8")
        assert "`user.login`" in text and "`user.login_failed`" in text


class TestOidcFailureReturnsToLogin:
    """G-188 / G-412: a failed provider round-trip lands on ``/login?error=<code>`` with the
    form, never on a raw JSON envelope. Only a known code travels in the URL — never the
    provider's own words."""

    def _location(self, r: Any) -> tuple[str, dict[str, list[str]]]:
        assert r.status_code == 302, r.text
        loc = urlparse(r.headers["location"])
        return loc.path, parse_qs(loc.query)

    def test_a_provider_refusal_returns_with_its_code_and_next(
        self, oidc_app: tuple[Any, FakeOidc]
    ) -> None:
        app, _ = oidc_app
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start?next=/runs", follow_redirects=False)
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"error": "access_denied", "error_description": "user <b>cancelled</b>"},
                follow_redirects=False,
            )
            path, q = self._location(r)
            assert path == "/login"
            assert q == {"error": ["oidc_provider_error"], "next": ["/runs"]}
            assert "cancelled" not in r.headers["location"]
            assert SESSION_COOKIE not in c.cookies and OIDC_COOKIE not in c.cookies

    def test_a_missing_or_forged_state_returns_with_its_code(
        self, oidc_app: tuple[Any, FakeOidc]
    ) -> None:
        app, _ = oidc_app
        with TestClient(app) as c:
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": "x"},
                follow_redirects=False,
            )
            path, q = self._location(r)
            assert (path, q) == ("/login", {"error": ["oidc_state_missing"]})
            c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": "forged"},
                follow_redirects=False,
            )
            path, q = self._location(r)
            assert path == "/login" and q["error"] == ["oidc_state_mismatch"]
            assert SESSION_COOKIE not in c.cookies

    def test_an_exchange_failure_returns_with_its_code_and_hides_the_reason(
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
            path, q = self._location(r)
            assert path == "/login" and q["error"] == ["oidc_exchange_failed"]
            assert "invalid_grant" not in r.text + r.headers["location"]
            assert SESSION_COOKIE not in c.cookies

    def test_a_disabled_account_returns_with_its_code_and_is_recorded(
        self, oidc_app: tuple[Any, FakeOidc], tmp_path: Path
    ) -> None:
        app, _ = oidc_app
        settings = make_settings(tmp_path, oidc=OIDC_SETTINGS)
        c = _oidc_login(app, settings)
        me = c.get(f"{API_PREFIX}/auth/me").json()
        c.__exit__(None, None, None)
        with TestClient(app) as admin:
            login(admin)
            r = admin.put(f"{API_PREFIX}/users/{me['id']}/active", json={"active": False})
            assert r.status_code == 200, r.text
        with TestClient(app) as c:
            c.get(f"{API_PREFIX}/auth/oidc/start", follow_redirects=False)
            pending = read_oidc_cookie(settings, c.cookies[OIDC_COOKIE])
            r = c.get(
                f"{API_PREFIX}/auth/oidc/callback",
                params={"code": "good-code", "state": pending.state},
                follow_redirects=False,
            )
            path, q = self._location(r)
            assert path == "/login" and q["error"] == ["account_disabled"]
            assert SESSION_COOKIE not in c.cookies
        failed = _user_events(app, "user.login_failed")
        assert len(failed) == 1 and failed[0].payload_json["reason"] == "account_disabled"

    def test_an_unconfigured_deployment_still_answers_404(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/auth/oidc/callback", follow_redirects=False)
        assert r.status_code == 404 and err(r)["code"] == "oidc_not_configured"


def test_the_sign_in_page_states_the_session_length_the_server_sets(tmp_path: Path) -> None:
    """P-148: /login told people a session "expires with the browser" while the cookie
    carried ``Max-Age`` = ``session_ttl`` (8 hours). The page's sentence and the server's
    default are now held to each other: change one without the other and this fails."""
    import re

    page = Path("ui/src/screens/Login/LoginPage.tsx").read_text(encoding="utf-8")
    assert "expire with the browser" not in page
    m = re.search(r"A session lasts (\d+) hours unless this deployment sets another length", page)
    assert m, "the sign-in page no longer states the session length"
    default_ttl = Settings.model_fields["session_ttl"].default
    assert int(m.group(1)) * 3600 == default_ttl
    with TestClient(create_app(make_settings(tmp_path))) as c:
        r = c.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
        cookie = next(v for v in r.headers.get_list("set-cookie") if v.startswith(SESSION_COOKIE))
        assert f"Max-Age={default_ttl}" in cookie


def _hint(key: str) -> str:
    """The text of one hint in ui/src/help/hints.ts, as the bubble shows it."""
    import re

    source = Path("ui/src/help/hints.ts").read_text(encoding="utf-8")
    m = re.search(rf"'{re.escape(key)}':\s*'((?:[^'\\]|\\.)*)'", source)
    assert m, f"no hint {key!r}"
    return m.group(1)


def test_the_recovery_hints_state_the_numbers_the_server_enforces() -> None:
    """recover-an-account.truth.4: the numbers that decide a recovery act are stated in the
    hint of the field or control they govern, and they are the server's numbers. Change the
    floor, the limiter or the session length without the hint (or drop the number from the
    hint) and this fails."""
    from crb.server.auth import LoginRateLimiter
    from crb.server.settings import MIN_PASSWORD_LENGTH

    floor = f"at least {MIN_PASSWORD_LENGTH} characters"
    for key in (
        "field.settings.set_password",
        "field.settings.new_password",
        "field.settings.my_new_password",
    ):
        assert floor in _hint(key), key

    limiter = LoginRateLimiter()
    words = {5: "Five", 3: "Three", 10: "Ten"}
    assert limiter.window_s == 60.0
    tries = _hint("field.settings.my_current_password")
    assert f"{words[limiter.limit]} wrong attempts in a minute" in tries
    assert "for this account from this address" in tries
    assert "how many seconds to wait" in tries

    # AUTH-3: no session lifetime decides a re-activation any more — deactivation ends the
    # sessions — so the hint says that instead of a number
    assert "reactivating it brings none of them back" in _hint("toggle.settings.user_active")


def test_the_current_password_hint_states_the_address_wide_limit_too() -> None:
    """recover-an-account.truth.4: ``PUT /users/me/password`` reserves its attempt in the
    login limiter, so BOTH of its buckets govern the current-password field — five a minute
    for this account from this address, and twenty a minute from this address whatever the
    account. The hint stated only the first; a person behind a shared address could be
    refused with no number on the screen that explained it."""
    from crb.server.auth import LoginRateLimiter

    limiter = LoginRateLimiter()
    words = {20: "Twenty", 10: "Ten", 30: "Thirty"}
    tries = _hint("field.settings.my_current_password")
    assert f"{words[limiter.ip_limit]} a minute from this address".lower() in tries.lower(), tries


def test_the_last_admin_copy_names_the_admin_who_can_sign_in() -> None:
    """P-200's rule counts only admins who can sign in by a path the deployment has switched
    on, but the active toggle's hint and the ``user.role_override_refused`` line still said
    "the last active admin", so an administrator could keep a second admin nobody can sign in
    as and read the screen as safe. Both now name the admin who can sign in."""
    import re

    assert "another active admin can still sign in" in _hint("toggle.settings.user_active")
    verdict = Path("ui/src/lib/verdict.ts").read_text(encoding="utf-8")
    m = re.search(r"'user\.role_override_refused':\s*'((?:[^'\\]|\\.)*)'", verdict)
    assert m, "no user.role_override_refused line"
    assert "no active admin who can sign in" in m.group(1)


def test_every_sign_in_record_commits_through_the_retry() -> None:
    """P-153: the retrying commit (DL-068) once covered local sign-in only; the organisation
    callback wrote ``user.login`` and called ``db.commit()`` itself, so a lost race answered a
    raw 500. In routes/auth.py a function that writes an audit event (directly, through a
    nested helper, or through ``_record_failed_login``) never commits by itself: it hands the
    write to ``commit_audited``. Only ``commit_audited`` and event-free functions commit."""
    import ast

    tree = ast.parse(Path("src/crb/server/routes/auth.py").read_text(encoding="utf-8"))
    writers = {"record_user_event", "append_system_event", "_record_failed_login"}

    def called(node: ast.AST) -> set[str]:
        names: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                f = sub.func
                names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
        return names

    offenders = [
        fn.name
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef)
        and fn.name != "commit_audited"
        and "commit" in called(fn)
        and called(fn) & writers
    ]
    assert offenders == [], f"commit an audit event through commit_audited: {offenders}"
    commits_audited = [
        fn.name
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef) and "commit_audited" in called(fn)
    ]
    assert {"login", "_complete_oidc"} <= set(commits_audited)
