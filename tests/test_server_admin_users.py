"""The user lifecycle routes (F23): password set / change, active flag, the last-admin
guard, session invalidation and the ``user.*`` audit events.

Navigation
----------
What it is:   The test suite for ``PUT /users/{id}/password``, ``PUT /users/me/password``,
              ``PUT /users/{id}/active`` and the ``user.*`` events they write.
What it does: Pins the RBAC matrix (viewer and operator are 403), that an admin-set password
              ends the target's existing session (the old cookie is 401 ``session_revoked``)
              while the new password logs in and the old does not, that a self-change needs
              the current password (five wrong ones trip the login limiter: 429) and keeps
              the changing browser signed in while another session ends, that an OIDC account is refused (409 ``not_local``), that
              deactivation ends sessions at once and the last active admin cannot be
              deactivated (409 ``last_admin``), that ``GET /users`` rows carry ``active`` and
              ``last_login``, and that every change lands as one event with actor and target
              and never a password.
How:          ``create_app`` over a temp SQLite file with the bootstrap admin; a second
              ``TestClient`` on the started app (no second lifespan) where two sessions
              must be told apart; events read straight from the ``events`` table on the
              account's ``users:<id>`` trace.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/routes/admin.py (under test), src/crb/server/auth.py
              (``credential_version``, ``set_password``, ``set_user_active``, the session
              binding in ``current_user``), src/crb/server/routes/auth.py (login issues the
              bound cookie), src/crb/store/models.py (``User``, ``Event``), docs/API.md#admin
Tested by:    tests/test_server_admin_users.py
Touch when:   a lifecycle route or a ``user.*`` event is added; the session binding changes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from crb.server.app import API_PREFIX, create_app
from crb.server.auth import CSRF_COOKIE, SESSION_COOKIE, new_user_id
from crb.server.routes.admin import user_trace_id
from crb.server.settings import Settings
from crb.store.models import Event, User

ROOT_PW = "correct-horse-battery-staple"
USER_PW = "another-long-password"
NEW_PW = "a-brand-new-long-password"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="dev",
        home=tmp_path,
        secret_key=SecretStr("s" * 40),
        sandbox={"executor": "local"},
        bootstrap_admin={"username": "root", "password": ROOT_PW},
        log_format="text",
    )


@pytest.fixture
def app(tmp_path: Path) -> Any:
    return create_app(make_settings(tmp_path))


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def other_client(started: TestClient) -> TestClient:
    """A second browser on the same started app (no lifespan of its own)."""
    return TestClient(started.app)


def login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> Any:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]
    return r


def err(r: Any) -> dict[str, Any]:
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "detail"}
    return dict(body["error"])


def create(c: TestClient, username: str, role: str = "viewer", password: str = USER_PW) -> str:
    r = c.post(
        f"{API_PREFIX}/users", json={"username": username, "password": password, "role": role}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def events_for(app: Any, user_id: str) -> list[Event]:
    with app.state.session_factory() as s:
        rows = list(
            s.execute(
                select(Event).where(Event.trace_id == user_trace_id(user_id)).order_by(Event.seq)
            ).scalars()
        )
        s.expunge_all()
        return rows


def add_oidc_user(app: Any, role: str = "viewer") -> str:
    uid = new_user_id()
    with app.state.session_factory() as s:
        s.add(
            User(
                id=uid,
                subject="sub-123",
                issuer="https://login.example/t",
                email="p@example.org",
                display_name="P",
                role=role,
            )
        )
        s.commit()
    return uid


# --- RBAC ---------------------------------------------------------------------------------


class TestRbac:
    @pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
    def test_non_admins_cannot_set_password_or_active(self, client: TestClient, role: str) -> None:
        login(client)
        uid = create(client, "someone", role)
        other = create(client, "target")
        login(client, "someone", USER_PW)
        r = client.put(f"{API_PREFIX}/users/{other}/password", json={"password": NEW_PW})
        assert r.status_code == 403 and err(r)["code"] == "forbidden"
        r = client.put(f"{API_PREFIX}/users/{other}/active", json={"active": False})
        assert r.status_code == 403 and err(r)["code"] == "forbidden"
        assert client.get(f"{API_PREFIX}/users").status_code == 403
        # …but everyone may change their own password.
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": USER_PW, "new_password": NEW_PW},
        )
        assert r.status_code == 200 and r.json()["id"] == uid

    def test_anonymous_is_401(self, client: TestClient) -> None:
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": USER_PW, "new_password": NEW_PW},
        )
        assert r.status_code == 401


# --- admin sets a password ------------------------------------------------------------------


class TestAdminSetsPassword:
    def test_sets_and_ends_the_targets_sessions(self, client: TestClient) -> None:
        admin, target = client, other_client(client)
        login(admin)
        uid = create(admin, "alice", "operator")
        login(target, "alice", USER_PW)
        assert target.get(f"{API_PREFIX}/auth/me").status_code == 200
        old_cookie = target.cookies[SESSION_COOKIE]

        r = admin.put(f"{API_PREFIX}/users/{uid}/password", json={"password": NEW_PW})
        assert r.status_code == 200, r.text
        assert r.json()["username"] == "alice"
        assert NEW_PW not in r.text and "password" not in r.json()

        # The session issued under the old password is over on its next request.
        r = target.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"
        assert target.cookies[SESSION_COOKIE] == old_cookie  # nothing re-issued
        # The old password no longer logs in; the new one does.
        r = target.post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": USER_PW})
        assert r.status_code == 401 and err(r)["code"] == "invalid_credentials"
        login(target, "alice", NEW_PW)
        assert target.get(f"{API_PREFIX}/auth/me").json()["id"] == uid

    def test_validation_unknown_and_oidc(self, client: TestClient, app: Any) -> None:
        login(client)
        uid = create(client, "bob")
        r = client.put(f"{API_PREFIX}/users/{uid}/password", json={"password": "short"})
        assert r.status_code == 422
        r = client.put(f"{API_PREFIX}/users/nope/password", json={"password": NEW_PW})
        assert r.status_code == 404 and err(r)["code"] == "not_found"
        oidc = add_oidc_user(app)
        r = client.put(f"{API_PREFIX}/users/{oidc}/password", json={"password": NEW_PW})
        assert r.status_code == 409 and err(r)["code"] == "not_local"
        r = client.put(f"{API_PREFIX}/users/{uid}/password", json={"password": NEW_PW, "extra": 1})
        assert r.status_code == 422

    def test_admin_setting_own_password_stays_signed_in(self, client: TestClient) -> None:
        login(client)
        root = client.get(f"{API_PREFIX}/auth/me").json()["id"]
        before = client.cookies[SESSION_COOKIE]
        r = client.put(f"{API_PREFIX}/users/{root}/password", json={"password": NEW_PW})
        assert r.status_code == 200
        assert client.cookies[SESSION_COOKIE] != before  # re-issued on this response
        client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
        assert client.get(f"{API_PREFIX}/users").status_code == 200
        login(client, "root", NEW_PW)


# --- self change ------------------------------------------------------------------------------


class TestSelfChange:
    def test_requires_current_password(self, client: TestClient) -> None:
        login(client)
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": "not-the-password", "new_password": NEW_PW},
        )
        assert r.status_code == 401 and err(r)["code"] == "invalid_credentials"
        # A wrong current password did not end the session…
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 200
        # …but a borrowed session cannot guess it online: the login limiter applies.
        for _ in range(4):
            r = client.put(
                f"{API_PREFIX}/users/me/password",
                json={"current_password": "still-not-it", "new_password": NEW_PW},
            )
            assert r.status_code == 401
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": ROOT_PW, "new_password": NEW_PW},
        )
        assert r.status_code == 429 and err(r)["code"] == "rate_limited"
        assert r.headers["Retry-After"]
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": ROOT_PW, "new_password": "short"},
        )
        assert r.status_code == 422

    def test_keeps_this_browser_and_ends_the_other(self, client: TestClient) -> None:
        here, elsewhere = client, other_client(client)
        login(here)
        login(elsewhere)
        r = here.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": ROOT_PW, "new_password": NEW_PW},
        )
        assert r.status_code == 200, r.text
        here.headers["X-CSRF-Token"] = here.cookies[CSRF_COOKIE]
        assert here.get(f"{API_PREFIX}/auth/me").status_code == 200
        r = elsewhere.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"
        login(elsewhere, "root", NEW_PW)

    def test_oidc_account_is_sent_to_its_provider(self, client: TestClient, app: Any) -> None:
        from crb.server.auth import credential_version, issue_session

        oidc = add_oidc_user(app)
        with app.state.session_factory() as s:
            user = s.get(User, oidc)
            assert user is not None
            token = issue_session(app.state.settings, oidc, credential_version(user))
        client.cookies.set(SESSION_COOKIE, token)
        client.cookies.set(CSRF_COOKIE, "t")
        client.headers["X-CSRF-Token"] = "t"
        assert client.get(f"{API_PREFIX}/auth/me").json()["id"] == oidc
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": "whatever-it-is", "new_password": NEW_PW},
        )
        assert r.status_code == 409 and err(r)["code"] == "not_local"


# --- active -----------------------------------------------------------------------------------


class TestActive:
    def test_deactivate_ends_sessions_and_reactivate_allows_login(self, client: TestClient) -> None:
        admin, target = client, other_client(client)
        login(admin)
        uid = create(admin, "carol", "approver")
        login(target, "carol", USER_PW)
        r = admin.put(f"{API_PREFIX}/users/{uid}/active", json={"active": False})
        assert r.status_code == 200 and r.json()["active"] is False
        r = target.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "unauthenticated"
        r = target.post(f"{API_PREFIX}/auth/login", json={"username": "carol", "password": USER_PW})
        assert r.status_code == 401
        # Idempotent.
        r = admin.put(f"{API_PREFIX}/users/{uid}/active", json={"active": False})
        assert r.status_code == 200 and r.json()["active"] is False
        r = admin.put(f"{API_PREFIX}/users/{uid}/active", json={"active": True})
        assert r.status_code == 200 and r.json()["active"] is True
        login(target, "carol", USER_PW)

    def test_last_admin_guard_and_second_admin(self, client: TestClient) -> None:
        login(client)
        root = client.get(f"{API_PREFIX}/auth/me").json()["id"]
        r = client.put(f"{API_PREFIX}/users/{root}/active", json={"active": False})
        assert r.status_code == 409 and err(r)["code"] == "last_admin"
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 200
        second = create(client, "admin2", "admin")
        r = client.put(f"{API_PREFIX}/users/{root}/active", json={"active": False})
        assert r.status_code == 200 and r.json()["active"] is False
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 401
        login(client, "admin2", USER_PW)
        r = client.put(f"{API_PREFIX}/users/{second}/active", json={"active": False})
        assert r.status_code == 409 and err(r)["code"] == "last_admin"
        r = client.put(f"{API_PREFIX}/users/nope/active", json={"active": False})
        assert r.status_code == 404
        r = client.put(f"{API_PREFIX}/users/{root}/active", json={"active": "maybe"})
        assert r.status_code == 422
        assert client.put(f"{API_PREFIX}/users/{root}/active", json={}).status_code == 422


# --- list rows --------------------------------------------------------------------------------


def test_list_rows_carry_active_and_last_login(client: TestClient) -> None:
    login(client)
    uid = create(client, "dave")
    rows = {u["username"]: u for u in client.get(f"{API_PREFIX}/users").json()["items"]}
    assert rows["root"]["active"] is True and rows["root"]["last_login"] != ""
    assert rows["dave"]["active"] is True and rows["dave"]["last_login"] == ""
    client.put(f"{API_PREFIX}/users/{uid}/active", json={"active": False})
    rows = {u["username"]: u for u in client.get(f"{API_PREFIX}/users").json()["items"]}
    assert rows["dave"]["active"] is False


# --- events -----------------------------------------------------------------------------------


def test_every_change_is_one_event_with_actor_and_target(client: TestClient, app: Any) -> None:
    login(client)
    root = client.get(f"{API_PREFIX}/auth/me").json()["id"]
    uid = create(client, "erin", "operator")
    assert (
        client.put(f"{API_PREFIX}/users/{uid}/password", json={"password": NEW_PW}).status_code
        == 200
    )
    assert client.put(f"{API_PREFIX}/users/{uid}/active", json={"active": False}).status_code == 200
    assert client.put(f"{API_PREFIX}/users/{uid}/active", json={"active": True}).status_code == 200
    assert (
        client.put(f"{API_PREFIX}/users/{uid}/role", json={"role": "approver"}).status_code == 200
    )
    login(client, "erin", NEW_PW)
    r = client.put(
        f"{API_PREFIX}/users/me/password",
        json={"current_password": NEW_PW, "new_password": USER_PW},
    )
    assert r.status_code == 200

    evs = events_for(app, uid)
    assert [e.action for e in evs] == [
        "user.created",
        "user.password_set",
        "user.deactivated",
        "user.activated",
        "user.role_set",
        "user.password_set",
    ]
    assert [e.seq for e in evs] == [1, 2, 3, 4, 5, 6]
    assert all(e.stage == "system" for e in evs)
    assert [e.actor for e in evs] == [root, root, root, root, root, uid]
    assert all(e.payload_json["target"] == uid for e in evs)
    assert all(e.payload_json["username"] == "erin" for e in evs)
    assert evs[1].payload_json["by"] == "admin" and evs[5].payload_json["by"] == "self"
    assert evs[4].payload_json["from_role"] == "operator"
    for e in evs:
        blob = repr(e.payload_json) + e.error_message + e.input_ref + e.output_ref
        assert NEW_PW not in blob and USER_PW not in blob and "argon2" not in blob
    # A refused change writes nothing.
    login(client, "root", ROOT_PW)
    r = client.put(f"{API_PREFIX}/users/{root}/active", json={"active": False})
    assert r.status_code == 409
    assert events_for(app, root) == []
