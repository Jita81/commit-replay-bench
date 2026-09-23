"""The invitation routes and the two-person readiness reading (G-518).

Navigation
----------
What it is:   The test suite for ``POST /invitations``, ``GET /invitations``,
              ``POST /invitations/{id}/revoke``, ``POST /invitations/accept`` and
              ``GET /two-person-readiness``.
What it does: Pins that an invitation creates an INACTIVE account nobody can sign in to,
              that the token is returned once and stored only as a hash, that accepting it
              sets the person's own password and activates the account so they can sign in,
              that a token cannot be spent twice and that a wrong, revoked or expired one is
              the same 401 (and that five wrong ones trip the limiter: 429), that only an
              admin may invite or revoke and only a signing role may be invited, that every
              write lands as one ``user.*`` event with actor and target and never a token or
              a password, and that two-person readiness answers Home's task 7 honestly: an
              admin alone is not ready, an approver who has never signed in is not ready, and
              an approver who has signed in with somebody else on the deployment is.
How:          ``create_app`` over a temp SQLite file with the bootstrap admin; the invited
              person's link is redeemed from a SECOND client (no session) as the browser the
              link is opened in would; events read straight from the ``events`` table on the
              account's ``users:<id>`` trace; the clock is moved by writing an ``expires`` in
              the past through the ORM, never by sleeping.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
Works with:   src/crb/server/routes/invitations.py (under test),
              src/crb/store/models.py (``Invitation``, ``User``, ``Event``),
              src/crb/server/routes/admin.py (``record_user_event``, the account lifecycle),
              tests/test_server_admin_users.py (the sibling suite for the lifecycle routes),
              docs/API.md#admin
Tested by:    tests/test_server_invitations.py
Touch when:   an invitation state or route is added; the readiness rule changes.
"""

from __future__ import annotations

import datetime as _dt
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from crb.server.app import API_PREFIX, create_app
from crb.server.auth import CSRF_COOKIE
from crb.server.routes.admin import user_trace_id
from crb.server.routes.invitations import token_hash
from crb.server.settings import Settings
from crb.store.models import Event, Invitation, User

ROOT_PW = "correct-horse-battery-staple"
CHOSEN_PW = "the-approver-chose-this-one"


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
        public_url="https://crb.example.nhs.uk",
    )


@pytest.fixture
def app(tmp_path: Path) -> Any:
    return create_app(make_settings(tmp_path))


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> Any:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]
    return r


def err(r: Any) -> dict[str, Any]:
    body = r.json()
    assert set(body) == {"error"}
    return dict(body["error"])


def invite(c: TestClient, username: str = "walk-approver", **over: Any) -> dict[str, Any]:
    r = c.post(f"{API_PREFIX}/invitations", json={"username": username, **over})
    assert r.status_code == 201, r.text
    return dict(r.json())


def session(app: Any) -> Any:
    return app.state.session_factory


def events_for(app: Any, user_id: str) -> list[Event]:
    with session(app)() as s:
        return list(
            s.execute(
                select(Event).where(Event.trace_id == user_trace_id(user_id)).order_by(Event.seq)
            )
            .scalars()
            .all()
        )


# --- creating the invitation ----------------------------------------------------------


def test_an_invitation_creates_an_inactive_account_and_returns_the_link_once(
    client: TestClient, app: Any
) -> None:
    login(client)
    made = invite(client, display_name="Walk Approver", email="wa@example.nhs.uk")
    inv = made["invitation"]
    assert inv["state"] == "pending" and inv["role"] == "approver"
    assert inv["username"] == "walk-approver" and inv["last_login"] == ""
    # the link is absolute (this deployment knows its own address) and carries the token
    assert made["accept_url"] == f"https://crb.example.nhs.uk/invite?token={made['token']}"
    assert made["public_url_missing"] is False
    # the account exists, is INACTIVE, and nothing can sign in to it yet
    with session(app)() as s:
        user = s.get(User, inv["user_id"])
        assert user is not None and user.active is False and user.role == "approver"
        assert user.display_name == "Walk Approver"
        # only the HASH is stored: the row cannot be redeemed by whoever reads the database
        row = s.execute(select(Invitation)).scalars().one()
        assert row.token_hash == token_hash(made["token"])
        assert made["token"] not in row.token_hash
    # the list never carries the token or its hash
    listed = client.get(f"{API_PREFIX}/invitations").json()
    assert listed["total"] == 1 and "token" not in str(listed)
    assert listed["items"][0]["state"] == "pending"
    # one event, on the account's own trace, naming who invited whom and nothing secret
    (ev,) = events_for(app, inv["user_id"])
    assert ev.action == "user.invited" and ev.payload_json["target"] == inv["user_id"]
    assert ev.payload_json["invitation"] == inv["id"]
    assert made["token"] not in str(ev.payload_json)


def test_only_an_admin_may_invite_and_only_a_signing_role_may_be_invited(
    client: TestClient,
) -> None:
    login(client)
    # a viewer is not worth an invitation: this route exists to close the two-person gap
    r = client.post(f"{API_PREFIX}/invitations", json={"username": "reader", "role": "viewer"})
    assert r.status_code == 422 and err(r)["detail"]["allowed"] == ["approver", "admin"]
    r = client.post(f"{API_PREFIX}/invitations", json={"username": "x", "role": "wizard"})
    assert r.status_code == 422 and err(r)["code"] == "validation_error"
    # a taken username is the same 409 the create-user route gives
    invite(client, "taken")
    r = client.post(f"{API_PREFIX}/invitations", json={"username": "taken"})
    assert r.status_code == 409 and err(r)["code"] == "user_exists"
    # an operator may not invite
    made_op = client.post(
        f"{API_PREFIX}/users",
        json={"username": "op1", "password": "a-long-enough-password", "role": "operator"},
    )
    assert made_op.status_code == 201
    login(client, "op1", "a-long-enough-password")
    r = client.post(f"{API_PREFIX}/invitations", json={"username": "someone"})
    assert r.status_code == 403 and err(r)["code"] == "forbidden"


# --- accepting it ---------------------------------------------------------------------


def test_accepting_sets_the_persons_own_password_activates_the_account_and_spends_the_token(
    client: TestClient, app: Any
) -> None:
    login(client)
    made = invite(client)
    browser = TestClient(app)  # the link is opened in a browser with no session
    r = browser.post(
        f"{API_PREFIX}/invitations/accept", json={"token": made["token"], "password": CHOSEN_PW}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "walk-approver" and body["role"] == "approver" and body["accepted"]
    # no session was issued: the person proves the password by signing in with it
    assert CSRF_COOKIE not in browser.cookies
    login(browser, "walk-approver", CHOSEN_PW)
    assert browser.get(f"{API_PREFIX}/auth/me").json()["role"] == "approver"
    # the account is active, and the invitation is spent
    with session(app)() as s:
        user = s.get(User, made["invitation"]["user_id"])
        assert user is not None and user.active is True and user.last_login
    assert client.get(f"{API_PREFIX}/invitations").json()["items"][0]["state"] == "accepted"
    # a second attempt with the same link is refused, and says what to do
    again = TestClient(app).post(
        f"{API_PREFIX}/invitations/accept", json={"token": made["token"], "password": CHOSEN_PW}
    )
    assert again.status_code == 401 and err(again)["code"] == "invalid_token"
    assert "ask your admin for a new one" in err(again)["message"]
    # the acceptance is on the account's trace, by the account itself
    actions = [e.action for e in events_for(app, made["invitation"]["user_id"])]
    assert actions == ["user.invited", "user.invite_accepted"]
    accepted = events_for(app, made["invitation"]["user_id"])[1]
    assert accepted.actor == made["invitation"]["user_id"]
    assert CHOSEN_PW not in str(accepted.payload_json)


def test_a_wrong_revoked_or_expired_token_is_the_same_refusal_and_the_limiter_bites(
    client: TestClient, app: Any
) -> None:
    login(client)
    revoked = invite(client, "gone")
    r = client.post(
        f"{API_PREFIX}/invitations/{revoked['invitation']['id']}/revoke",
        json={"reason": "invited the wrong person"},
    )
    assert r.status_code == 200 and r.json()["state"] == "revoked"
    assert r.json()["revoked_reason"] == "invited the wrong person"
    expired = invite(client, "late")
    with session(app)() as s:
        row = s.get(Invitation, expired["invitation"]["id"])
        assert row is not None
        row.expires = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=1)).isoformat()
        s.commit()
    by_id = {i["id"]: i for i in client.get(f"{API_PREFIX}/invitations").json()["items"]}
    assert by_id[expired["invitation"]["id"]]["state"] == "expired"
    assert by_id[revoked["invitation"]["id"]]["state"] == "revoked"
    browser = TestClient(app)
    for token in (revoked["token"], expired["token"], "not-a-real-token-at-all"):
        r = browser.post(
            f"{API_PREFIX}/invitations/accept", json={"token": token, "password": CHOSEN_PW}
        )
        assert r.status_code == 401 and err(r)["code"] == "invalid_token"
    # neither account was touched by the attempts
    with session(app)() as s:
        for made in (revoked, expired):
            user = s.get(User, made["invitation"]["user_id"])
            assert user is not None and user.active is False
    # the fourth and fifth failures trip the per-IP limiter, which then refuses a GOOD token
    good = invite(client, "fine")
    for _ in range(2):
        r = browser.post(
            f"{API_PREFIX}/invitations/accept",
            json={"token": "wrong-but-long-enough-to-reach-the-handler", "password": CHOSEN_PW},
        )
        assert r.status_code == 401
    r = browser.post(
        f"{API_PREFIX}/invitations/accept", json={"token": good["token"], "password": CHOSEN_PW}
    )
    assert r.status_code == 429 and err(r)["code"] == "rate_limited"
    assert r.headers["Retry-After"]


def test_revoking_an_accepted_invitation_is_refused_and_says_what_to_do_instead(
    client: TestClient, app: Any
) -> None:
    login(client)
    made = invite(client)
    assert (
        TestClient(app)
        .post(
            f"{API_PREFIX}/invitations/accept",
            json={"token": made["token"], "password": CHOSEN_PW},
        )
        .status_code
        == 200
    )
    r = client.post(
        f"{API_PREFIX}/invitations/{made['invitation']['id']}/revoke", json={"reason": "changed"}
    )
    assert r.status_code == 409 and err(r)["code"] == "already_accepted"
    assert "deactivate the account" in err(r)["message"]
    # a revocation needs a reason at the API, not only in the UI
    other = invite(client, "second")
    r = client.post(f"{API_PREFIX}/invitations/{other['invitation']['id']}/revoke", json={})
    assert r.status_code == 422
    r = client.post(f"{API_PREFIX}/invitations/missing/revoke", json={"reason": "whatever"})
    assert r.status_code == 404


# --- what Home's task 7 reads ---------------------------------------------------------


def test_two_person_readiness_is_not_the_presence_of_an_admin(client: TestClient, app: Any) -> None:
    login(client)
    # the bootstrap admin alone: it CAN sign, and it is the only person there is
    r = client.get(f"{API_PREFIX}/two-person-readiness").json()
    assert r["ready"] is False and r["reason_code"] == "single_person"
    assert r["approvers_active"] == 1 and r["approvers_signed_in"] == 1
    assert r["other_active_accounts"] == 0 and r["invitations_pending"] == 0
    assert "same_actor" in r["reason"]
    # an operator to run the measurements, and an approver invited but not arrived: still
    # not ready, and the reason is the one that names the missing act
    made_op = client.post(
        f"{API_PREFIX}/users",
        json={"username": "op1", "password": "a-long-enough-password", "role": "operator"},
    )
    assert made_op.status_code == 201
    made = invite(client, "appr1")
    r = client.get(f"{API_PREFIX}/two-person-readiness").json()
    assert r["ready"] is False and r["reason_code"] == "single_person"
    # the invited account is inactive, so it is not an approver yet, and op1 has never
    # signed in: one account has arrived, and it would be signing its own work
    assert r["invitations_pending"] == 1 and r["accounts_signed_in"] == 1
    browser = TestClient(app)
    assert (
        browser.post(
            f"{API_PREFIX}/invitations/accept",
            json={"token": made["token"], "password": CHOSEN_PW},
        ).status_code
        == 200
    )
    # accepted but never signed in: an account that has not arrived can sign nothing, and the
    # admin is still the only account that has
    r = client.get(f"{API_PREFIX}/two-person-readiness").json()
    assert r["ready"] is False and r["reason_code"] == "single_person"
    assert r["approvers_active"] == 2 and r["approvers_signed_in"] == 1
    assert r["invitations_pending"] == 0  # the link was used
    login(browser, "appr1", CHOSEN_PW)
    r = client.get(f"{API_PREFIX}/two-person-readiness").json()
    assert r["ready"] is True and r["reason_code"] == "ready"
    assert r["approvers_signed_in"] == 2 and r["other_active_accounts"] == 1
    assert r["accounts_signed_in"] == 2
    # the reading counts ACCOUNTS and says so rather than claiming to count people
    assert "accounts, not people" in r["reason"]
    # a viewer reads the same state (the state is not an admin secret) and cannot invite
    assert (
        client.post(
            f"{API_PREFIX}/users",
            json={"username": "v1", "password": "a-long-enough-password", "role": "viewer"},
        ).status_code
        == 201
    )
    viewer = TestClient(app)
    login(viewer, "v1", "a-long-enough-password")
    assert viewer.get(f"{API_PREFIX}/two-person-readiness").json()["ready"] is True
    assert viewer.get(f"{API_PREFIX}/invitations").status_code == 403


def test_readiness_says_no_approver_and_then_names_the_unused_invitation(
    client: TestClient, app: Any
) -> None:
    """Two readings an admin's presence cannot give: nobody who can sign at all, and an
    approver account that exists and has never arrived."""
    login(client)
    assert (
        client.post(
            f"{API_PREFIX}/users",
            json={"username": "op1", "password": "a-long-enough-password", "role": "operator"},
        ).status_code
        == 201
    )
    made = invite(client, "appr1")
    # deactivate the only account that can sign — the bootstrap admin — through the ORM: the
    # API refuses it (last_admin), and the reading must still be honest about the state
    with session(app)() as s:
        admin = s.execute(select(User).where(User.role == "admin")).scalars().one()
        admin.active = False
        s.commit()
    # the admin's own session is refused now; the operator still reads the state
    login(client, "op1", "a-long-enough-password")
    r = client.get(f"{API_PREFIX}/two-person-readiness").json()
    assert r["ready"] is False and r["reason_code"] == "no_approver"
    assert r["approvers_active"] == 0 and "invite an approver" in r["reason"]
    assert r["invitations_pending"] == 1
    # the invitation is accepted: an approver account now exists and has never signed in
    assert (
        TestClient(app)
        .post(
            f"{API_PREFIX}/invitations/accept",
            json={"token": made["token"], "password": CHOSEN_PW},
        )
        .status_code
        == 200
    )
    r = client.get(f"{API_PREFIX}/two-person-readiness").json()
    assert r["ready"] is False and r["reason_code"] == "approver_never_signed_in"
    assert r["approvers_active"] == 1 and r["approvers_signed_in"] == 0
    assert "the invitation has not been used" in r["reason"]
