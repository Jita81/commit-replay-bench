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
              the changing browser signed in while another session ends, that an OIDC
              account is refused (409 ``not_local``), that deactivation ENDS sessions
              (the nonce rotates: an old cookie is ``session_revoked`` after
              re-activation, by the route, the role route and the host door, AUTH-3) and
              the last active admin cannot be deactivated (409 ``last_admin``), that
              ``GET /users`` rows carry ``active`` and ``last_login``, that every change
              lands as one event with actor and target
              and never a password, that those events are ordinary ``events`` rows —
              trigger-protected, not hash-chained (the chain is the ledger's) — and that a
              password set by any door rotates the session nonce, so the old sessions end
              even when the stored hash does not move (#52's revocation, P-149), and that
              the users lock serialises two concurrent last-admin deactivations and refuses
              rather than run unlocked when a transaction is already open (P-430).
How:          ``create_app`` over a temp SQLite file with the bootstrap admin; a second
              ``TestClient`` on the started app (no second lifespan) where two sessions
              must be told apart; events read straight from the ``events`` table on the
              account's ``users:<id>`` trace; the lock cases drive two sessions (one on a
              thread) or open a deferred ``BEGIN`` before the lock.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/routes/admin.py (under test), src/crb/server/auth.py
              (``credential_version``, ``set_password``, ``set_user_active``, the session
              binding in ``current_user``), src/crb/server/routes/auth.py (login issues the
              bound cookie), src/crb/store/models.py (``User``, ``Event``), docs/API.md#admin
Tested by:    tests/test_server_admin_users.py
Touch when:   never for a new repository; a lifecycle route or a ``user.*`` event is added; the
              session binding changes.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text

from crb.server.app import API_PREFIX, create_app
from crb.server.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    count_active_admins,
    create_local_user,
    lock_users_table,
    new_user_id,
    set_user_active,
)
from crb.server.deps import ApiError
from crb.server.routes import admin as admin_routes
from crb.server.routes.admin import user_trace_id
from crb.server.settings import Settings
from crb.store.models import Event, Grade, Signoff, User

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
        from crb.server.auth import credential_version, csrf_token_for, issue_session

        oidc = add_oidc_user(app)
        with app.state.session_factory() as s:
            user = s.get(User, oidc)
            assert user is not None
            cv = credential_version(user)
            token = issue_session(app.state.settings, oidc, cv)
        client.cookies.set(SESSION_COOKIE, token)
        # the CSRF token is bound to the session (D4): the one the server would have set
        csrf = csrf_token_for(app.state.settings, oidc, cv)
        client.cookies.set(CSRF_COOKIE, csrf)
        client.headers["X-CSRF-Token"] = csrf
        assert client.get(f"{API_PREFIX}/auth/me").json()["id"] == oidc
        r = client.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": "whatever-it-is", "new_password": NEW_PW},
        )
        assert r.status_code == 409 and err(r)["code"] == "not_local"


# --- active -----------------------------------------------------------------------------------


class TestActive:
    def test_deactivate_ends_sessions_for_good_and_reactivate_allows_login(
        self, client: TestClient
    ) -> None:
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
        # AUTH-3 (the operator's security review, 2026-09-27): deactivation ENDS the
        # sessions — it rotates the account's session nonce — so a cookie issued before it
        # (a stolen one included) never comes back when the account is turned on again.
        r = target.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"
        login(target, "carol", USER_PW)  # the person signs in afresh
        assert target.get(f"{API_PREFIX}/auth/me").status_code == 200

    def test_the_host_door_ends_the_sessions_too(self, client: TestClient, app: Any) -> None:
        """``crb users deactivate`` and the route share :func:`set_user_active`, so the
        rotation lives there, not in the route."""
        admin, target = client, other_client(client)
        login(admin)
        uid = create(admin, "dora", "viewer")
        login(target, "dora", USER_PW)
        with app.state.session_factory() as s:
            user = s.get(User, uid)
            assert user is not None
            nonce = user.session_nonce
            assert set_user_active(s, user, False, sign_in=None)
            assert user.session_nonce != nonce
            s.commit()
        with app.state.session_factory() as s:
            user = s.get(User, uid)
            assert user is not None
            nonce = user.session_nonce
            assert set_user_active(s, user, True, sign_in=None)
            assert user.session_nonce == nonce  # turning it on ends nothing more
            s.commit()
        r = target.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"

    def test_the_role_route_deactivating_ends_the_sessions_too(self, client: TestClient) -> None:
        """``PUT /users/{id}/role`` can turn an account off as well (``active: false``); it
        writes the flag through the same primitive, so it ends the sessions the same way."""
        admin, target = client, other_client(client)
        login(admin)
        uid = create(admin, "erin", "operator")
        login(target, "erin", USER_PW)
        r = admin.put(f"{API_PREFIX}/users/{uid}/role", json={"role": "viewer", "active": False})
        assert r.status_code == 200 and r.json()["active"] is False
        r = admin.put(f"{API_PREFIX}/users/{uid}/active", json={"active": True})
        assert r.status_code == 200
        r = target.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"

    def test_api_md_states_that_deactivation_ends_sessions_for_good(self) -> None:
        """docs/API.md must describe what the route above proves: deactivation ends every
        session of the account (``session_revoked`` after re-activation); the person signs
        in again once an admin re-activates the account. It must not say re-activation
        resumes them (the contract before AUTH-3)."""
        api_md = (Path(__file__).parents[1] / "docs" / "API.md").read_text()
        roles = api_md[api_md.index("- **Roles**") : api_md.index("- **Errors**")]
        assert "resume" not in roles
        assert "re-activate" in roles and "session_revoked" in roles
        assert "ends every session" in roles

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

    def test_guard_reads_the_row_under_the_lock_not_the_callers_snapshot(
        self, client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two admins, root and x. Request A loads x (an operator) before the users lock;
        between that read and the lock another session promotes x to admin and demotes
        root. A guard that trusted A's snapshot ("x is an operator, no admin at stake")
        deactivated the last admin — reproduced by the verifier on 2026-09-21. The guard
        must decide on the row as it is under the lock: 409 ``last_admin``, and one active
        admin remains."""
        login(client)
        root = client.get(f"{API_PREFIX}/auth/me").json()["id"]
        x = create(client, "xx", "operator")
        real_get_user = admin_routes._get_user

        def get_then_race(db: Any, user_id: str) -> Any:
            user = real_get_user(db, user_id)
            if user_id == x:
                with app.state.session_factory() as other:
                    other.get(User, x).role = "admin"
                    other.get(User, root).role = "operator"
                    other.commit()
            return user

        monkeypatch.setattr(admin_routes, "_get_user", get_then_race)
        r = client.put(f"{API_PREFIX}/users/{x}/active", json={"active": False})
        assert r.status_code == 409 and err(r)["code"] == "last_admin"
        with app.state.session_factory() as s:
            assert count_active_admins(s) == 1
            assert s.get(User, x).active is True
        assert [e.action for e in events_for(app, x)] == ["user.created"]  # nothing written

    def test_primitive_refreshes_under_the_lock(self, client: TestClient, app: Any) -> None:
        """The same interleaving on ``set_user_active`` directly — the one implementation
        both doors (route and ``crb users deactivate``) share, so fixing it here fixes both.
        Mirrors the verifier's two-session reproduction (scratchpad verify-U-race.py)."""
        with app.state.session_factory() as s:
            y = create_local_user(s, username="yy", password=USER_PW, role="admin").id
            x = create_local_user(s, username="xx", password=USER_PW, role="operator").id
            z = create_local_user(s, username="zz", password=USER_PW, role="viewer").id
            for u in s.execute(select(User).where(User.subject == "local:root")).scalars():
                u.active = False  # leave y as the only other admin
            s.commit()
        a, b = app.state.session_factory(), app.state.session_factory()
        try:
            x_in_a = a.get(User, x)
            assert x_in_a.role == "operator"
            b.get(User, x).role = "admin"
            b.get(User, y).role = "operator"
            b.commit()
            with pytest.raises(ApiError) as excinfo:
                set_user_active(a, x_in_a, False, sign_in=None)
            assert excinfo.value.status_code == 409 and excinfo.value.code == "last_admin"
            a.rollback()
            # Idempotency is decided on the refreshed row too: a snapshot that still says
            # "active" after another session deactivated the account is a no-op (``False``),
            # so the caller writes no second ``user.deactivated`` event.
            z_in_a = a.get(User, z)
            assert z_in_a.active is True
            b.get(User, z).active = False
            b.commit()
            assert set_user_active(a, z_in_a, False, sign_in=None) is False
            assert set_user_active(a, z_in_a, True, sign_in=None) is True
            a.commit()
        finally:
            a.close()
            b.close()
        with app.state.session_factory() as s:
            assert count_active_admins(s) == 1 and s.get(User, x).role == "admin"
            assert s.get(User, z).active is True

    def test_a_transaction_already_open_makes_the_users_lock_refuse(
        self, client: TestClient, app: Any
    ) -> None:
        """P-430: the users lock fails closed. A deferred ``BEGIN`` holds no write lock, so
        when one is already open ``BEGIN IMMEDIATE`` cannot run and nothing proves the
        session is serialised: the lock must raise, never return as if it held it. Taking
        it again in the transaction that took it is not that case (the write lock lasts to
        the transaction's end), and that proof ends with the transaction."""
        del client  # started: the lifespan binds the session factory
        with app.state.session_factory() as s:
            lock_users_table(s)
            lock_users_table(s)  # the same transaction already holds the write lock
            s.commit()
            s.execute(text("BEGIN"))  # a transaction, but no write lock
            with pytest.raises(RuntimeError, match="already open"):
                lock_users_table(s)

    def test_a_transaction_already_open_refuses_a_deactivation_rather_than_run_unlocked(
        self, client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P-430 at the route: a deferred ``BEGIN`` opened before the users lock (here after
        the target's read) makes ``PUT /users/{id}/active`` refuse with nothing written,
        not deactivate the account with its last-admin guard unserialised."""
        login(client)
        x = create(client, "xx", "operator")
        real_get_user = admin_routes._get_user

        def get_then_begin(db: Any, user_id: str) -> Any:
            user = real_get_user(db, user_id)
            db.execute(text("BEGIN"))  # a transaction, but no write lock
            return user

        monkeypatch.setattr(admin_routes, "_get_user", get_then_begin)
        try:
            r = client.put(f"{API_PREFIX}/users/{x}/active", json={"active": False})
        except RuntimeError as exc:
            assert "already open" in str(exc)
            r = None
        assert r is None or r.status_code == 500, r.text
        with app.state.session_factory() as s:
            assert s.get(User, x).active is True
        assert [e.action for e in events_for(app, x)] == ["user.created"]  # nothing written

    def test_the_lock_serialises_two_concurrent_last_admin_deactivations(
        self, client: TestClient, app: Any
    ) -> None:
        """Two admins, two sessions, each deactivating the other admin. Without the lock
        each would count "2 admins" and together leave none. Under it the second waits for
        the first to commit, re-reads, counts 1 and is refused 409 ``last_admin``."""
        del client  # started: the lifespan binds the session factory
        with app.state.session_factory() as s:
            y = create_local_user(s, username="yy", password=USER_PW, role="admin").id
            root = s.execute(select(User).where(User.subject == "local:root")).scalar_one().id
            s.commit()
        a, b = app.state.session_factory(), app.state.session_factory()
        started, outcome = threading.Event(), {}

        def second() -> None:
            started.set()
            try:
                outcome["changed"] = set_user_active(b, b.get(User, y), False, sign_in=None)
            except ApiError as exc:
                outcome["refused"] = exc.code
            finally:
                b.rollback()

        try:
            # a holds the lock
            assert set_user_active(a, a.get(User, root), False, sign_in=None) is True
            t = threading.Thread(target=second)
            t.start()
            started.wait(5)
            t.join(0.5)
            assert t.is_alive(), outcome  # b is waiting for a's write lock, not counting
            a.commit()
            t.join(10)
            assert not t.is_alive()
        finally:
            a.close()
            b.close()
        assert outcome == {"refused": "last_admin"}
        with app.state.session_factory() as s:
            assert count_active_admins(s) == 1 and s.get(User, y).active is True


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

    # the account's CHANGES; its sign-ins (user.login*) are on the same trail, pinned in
    # tests/test_server_auth.py::TestSignInIsAudited
    trail = events_for(app, uid)
    # one trace, no gaps: the sign-ins take their seq on the same trail as the changes
    assert [e.seq for e in trail] == list(range(1, len(trail) + 1))
    evs = [e for e in trail if not e.action.startswith("user.login")]
    assert [e.action for e in evs] == [
        "user.created",
        "user.password_set",
        "user.deactivated",
        "user.activated",
        "user.role_set",
        "user.password_set",
    ]
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
    assert [e.action for e in events_for(app, root)] == ["user.login", "user.login"]


def test_account_events_use_the_unchained_events_table(client: TestClient, app: Any) -> None:
    """The ``user.*`` events are the same mechanism as every other system event
    (``repo.created``, ``run.cancel_requested``…): an ``events`` row, append-only by DB
    trigger, with NO ``prev_hash`` / ``row_hash`` — the hash chain is the ledger's
    (grades / sign-offs / reviews / factory evidence), ADR-0002 §5, ARCHITECTURE §7.3.
    Chaining ``events`` is a repo-wide change (backlog F51), not an account-route one."""
    login(client, "root", ROOT_PW)
    uid = create(client, "frank", "operator")
    (ev,) = events_for(app, uid)
    assert ev.action == "user.created"
    for col in ("prev_hash", "row_hash"):
        assert col not in Event.__table__.columns, f"events.{col} exists: update F51 + docs"
        assert not hasattr(ev, col)
        assert col in Grade.__table__.columns and col in Signoff.__table__.columns


# --- the account's audit trail is served ----------------------------------------------------


class TestAccountEventsRoute:
    """``GET /users/{id}/events`` — the other half of the audit: the ``user.*`` events are
    written by every lifecycle route and, until now, nothing served them (G-464)."""

    def test_serves_the_accounts_own_events_newest_first(
        self, client: TestClient, app: Any
    ) -> None:
        login(client)
        uid = create(client, "gina", "viewer")
        client.put(f"{API_PREFIX}/users/{uid}/role", json={"role": "operator"})
        client.put(f"{API_PREFIX}/users/{uid}/password", json={"password": NEW_PW})
        client.put(f"{API_PREFIX}/users/{uid}/active", json={"active": False})
        r = client.get(f"{API_PREFIX}/users/{uid}/events")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 4
        actions = [e["action"] for e in body["items"]]
        assert actions == [
            "user.deactivated",
            "user.password_set",
            "user.role_set",
            "user.created",
        ]
        # served as written: actor and target, never a password
        assert all(e["actor"] for e in body["items"])
        assert all(e["payload"]["target"] == uid for e in body["items"])
        assert NEW_PW not in r.text and USER_PW not in r.text

    def test_only_that_accounts_events_and_an_unknown_id_is_404(
        self, client: TestClient, app: Any
    ) -> None:
        login(client)
        one = create(client, "hank")
        two = create(client, "iris")
        r = client.get(f"{API_PREFIX}/users/{one}/events")
        assert r.status_code == 200 and r.json()["total"] == 1
        assert {e["payload"]["username"] for e in r.json()["items"]} == {"hank"}
        assert two not in r.text
        r = client.get(f"{API_PREFIX}/users/nobody/events")
        assert r.status_code == 404 and err(r)["code"] == "not_found"

    @pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
    def test_below_admin_is_refused(self, client: TestClient, role: str) -> None:
        login(client)
        target = create(client, "target")
        create(client, "reader", role)
        login(client, "reader", USER_PW)
        r = client.get(f"{API_PREFIX}/users/{target}/events")
        assert r.status_code == 403 and err(r)["code"] == "forbidden"

    def test_api_md_lists_the_route(self) -> None:
        text = Path("docs/API.md").read_text(encoding="utf-8")
        assert "`/users/{id}/events`" in text


# --- a password set ends sessions through the session nonce (#52), not only the re-salt -----


def _freeze_hash(monkeypatch: pytest.MonkeyPatch, app: Any, username: str) -> str:
    """From now on every new hash is the one ``username`` already has, so a password set can
    only end sessions by rotating the nonce. Returns the account id."""
    import crb.server.auth as auth_mod

    with app.state.session_factory() as s:
        user = s.execute(select(User).where(User.subject == f"local:{username}")).scalar_one()
        frozen, uid = user.password_hash, user.id
    monkeypatch.setattr(auth_mod, "hash_password", lambda _password: frozen)
    return str(uid)


def _nonce_and_hash(app: Any, uid: str) -> tuple[str, str]:
    with app.state.session_factory() as s:
        user = s.get(User, uid)
        assert user is not None
        return str(user.session_nonce or ""), str(user.password_hash)


class TestPasswordSetRotatesTheSessionNonce:
    """#52 made a session revocable by binding it to ``credential_version`` = the password
    hash AND ``users.session_nonce``. A password set used to end sessions only because argon2
    re-salts the hash; these pin that it goes through #52's own mechanism — the nonce
    rotates — so the old sessions end even when the stored hash does not move."""

    def test_an_admin_set_password_ends_the_targets_sessions(
        self, client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin, target = client, other_client(client)
        login(admin)
        create(admin, "nora", "operator")
        login(target, "nora", USER_PW)
        uid = _freeze_hash(monkeypatch, app, "nora")
        nonce_before, hash_before = _nonce_and_hash(app, uid)
        r = admin.put(f"{API_PREFIX}/users/{uid}/password", json={"password": NEW_PW})
        assert r.status_code == 200, r.text
        nonce_after, hash_after = _nonce_and_hash(app, uid)
        assert hash_after == hash_before  # the re-salt moved nothing here
        assert nonce_after and nonce_after != nonce_before
        r = target.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"

    def test_a_self_change_keeps_this_browser_and_ends_the_other(
        self, client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        here, elsewhere = client, other_client(client)
        login(here)
        login(elsewhere)
        uid = _freeze_hash(monkeypatch, app, "root")
        nonce_before, _ = _nonce_and_hash(app, uid)
        r = here.put(
            f"{API_PREFIX}/users/me/password",
            json={"current_password": ROOT_PW, "new_password": NEW_PW},
        )
        assert r.status_code == 200, r.text
        assert _nonce_and_hash(app, uid)[0] != nonce_before
        here.headers["X-CSRF-Token"] = here.cookies[CSRF_COOKIE]
        assert here.get(f"{API_PREFIX}/auth/me").status_code == 200
        r = elsewhere.get(f"{API_PREFIX}/auth/me")
        assert r.status_code == 401 and err(r)["code"] == "session_revoked"

    def test_the_host_verb_uses_the_same_primitive(
        self, client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``crb users set-password`` calls :func:`set_password`, so it rotates the nonce too."""
        from crb.server.auth import set_password

        uid = _freeze_hash(monkeypatch, app, "root")
        with app.state.session_factory() as s:
            user = s.get(User, uid)
            assert user is not None
            nonce = user.session_nonce
            set_password(user, NEW_PW)
            assert user.session_nonce and user.session_nonce != nonce
