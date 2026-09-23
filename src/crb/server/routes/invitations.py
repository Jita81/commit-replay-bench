"""``/invitations`` and ``/two-person-readiness`` — bringing the second person in (G-518).

The two-person rule (ADR-0016) means a deployment with one account can sign nothing: the
API refuses a sign-off from the person who produced the evidence, and no setting relaxes
it. Until this module, the product told the admin to invite an approver and could not
invite one: an admin created a local account and typed a password on somebody else's
behalf, out of band, and nothing recorded whether that person ever arrived.

An invitation instead:

* ``POST /invitations`` (admin) creates the account **inactive**, with a password nobody
  knows (32 random bytes, never returned), and mints a one-time token. The response
  carries the token and the link ONCE; only its SHA-256 hash is stored, so a leaked
  database row cannot be redeemed.
* ``POST /invitations/accept`` needs no session — it is the link's own page. The person
  sets their own password, and the account is activated at that moment. The token is
  spent; a second attempt is a 409.
* ``POST /invitations/{id}/revoke`` (admin) withdraws a link that has not been used and
  leaves the (still inactive) account alone — deleting an account is not this route's job.
* ``GET /invitations`` (admin) lists what was invited and where each one stands
  (``pending`` / ``accepted`` / ``expired`` / ``revoked``), never a token or a hash.
* ``GET /two-person-readiness`` (any signed-in role) answers the question Home's task 7
  asks: can this deployment produce a signature the two-person rule will accept? An
  admin's presence is not an answer — an account that can sign and has never signed in
  cannot sign, and a deployment where the only approver is the only operator cannot
  either. The reading names its reason code so the screen explains rather than nags.

Every write is one transaction with a ``user.*`` event on the account's own trace
(``user.invited`` / ``user.invite_accepted`` / ``user.invite_revoked``), actor and target
ids, never a token and never a password.

Navigation
----------
What it is:   The invitation routes — create, list, revoke, accept — and the deployment's
              two-person readiness reading.
What it does: Turns "invite an approver" from an out-of-band act into a recorded one: an
              inactive account plus a one-time link (hash stored, token shown once,
              expiring), redeemed by the person themselves setting their own password, and
              a readiness reading that says whether a sign-off the two-person rule accepts
              is possible at all — with the reason when it is not.
How:          ``secrets.token_urlsafe`` for the token and ``hashlib.sha256`` for what is
              stored; ``create_local_user`` / ``set_password`` / ``set_user_active`` from
              src/crb/server/auth.py under ``lock_users_table``; ``record_user_event`` from
              src/crb/server/routes/admin.py for the audit trail; the login limiter for the
              unauthenticated accept path.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
              (why the second person cannot be waived, which is why inviting one is a
              product feature)
Works with:   src/crb/store/models.py (``Invitation``, ``User``),
              src/crb/store/migrations/versions/v0009_invitations.py (the table),
              src/crb/server/routes/admin.py (``record_user_event``, ``UserOut`` — the same
              account lifecycle and audit trail), src/crb/server/auth.py (the password and
              active primitives, the login limiter), src/crb/core/signoff.py (the
              two-person clause this readiness is about),
              ui/src/screens/Settings/InviteApproverCard.tsx (the admin's surface),
              ui/src/screens/Invite/AcceptInvitePage.tsx (the link's page),
              ui/src/screens/Home/HomePage.tsx (task 7 reads the readiness), docs/API.md
Tested by:    tests/test_server_invitations.py
Touch when:   the role ladder changes (the readiness rule names the signing roles); never
              for a new repository.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
import secrets
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.server.auth import (
    LOCAL_ISSUER,
    AdminDep,
    LoginRateLimiter,
    ViewerDep,
    create_local_user,
    is_local_account,
    lock_users_table,
    set_password,
    set_user_active,
    validate_role,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep, client_ip
from crb.server.routes.admin import record_user_event
from crb.server.settings import MIN_PASSWORD_LENGTH, ROLE_RANK
from crb.store.models import Invitation, User

router = APIRouter(tags=["invitations"])
_ERR = {"model": ErrorEnvelope}

#: The roles an invitation may carry: only a role that can actually sign a cell is worth
#: inviting for (``approver`` and above). A viewer or operator account is created in
#: Settings — this route exists to close the two-person gap.
INVITABLE_ROLES: tuple[str, ...] = ("approver", "admin")
#: How long a link lives by default, and the bounds an admin may choose between.
DEFAULT_EXPIRY_HOURS = 72
MIN_EXPIRY_HOURS = 1
MAX_EXPIRY_HOURS = 336  # two weeks
#: The one-time token's entropy, in bytes, before URL-safe encoding.
TOKEN_BYTES = 32
#: The rate-limiter identity the unauthenticated accept path is counted under (the token is
#: not a username, and must not become one in a counter keyed by name).
_ACCEPT_LIMIT_KEY = "invitation:accept"

STATE_PENDING = "pending"
STATE_ACCEPTED = "accepted"
STATE_EXPIRED = "expired"
STATE_REVOKED = "revoked"

#: The two-person readiness reason codes, in the order the reading tries them.
READY = "ready"
NO_APPROVER = "no_approver"
APPROVER_NEVER_SIGNED_IN = "approver_never_signed_in"
SINGLE_PERSON = "single_person"

_REASONS: dict[str, str] = {
    READY: (
        "an account that can sign has signed in, and at least one other account has too, so "
        "a sign-off the two-person rule accepts is possible. The product can see accounts, "
        "not people: two accounts one person holds would still be refused by a reviewer, not "
        "by this check"
    ),
    NO_APPROVER: (
        "no active account can sign a cell: invite an approver (the two-person rule cannot "
        "be waived by any setting)"
    ),
    APPROVER_NEVER_SIGNED_IN: (
        "the only account that can sign has never signed in, so it can sign nothing yet — "
        "the invitation has not been used"
    ),
    SINGLE_PERSON: (
        "only one account has ever signed in: whoever runs the measurements would be signing "
        "their own evidence, which the API refuses (same_actor)"
    ),
}


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0)


def _iso(when: _dt.datetime) -> str:
    return when.isoformat()


def token_hash(token: str) -> str:
    """What is stored for a one-time token: its SHA-256 hex. The token is never stored, so
    a database dump cannot be redeemed."""
    return hashlib.sha256(token.encode()).hexdigest()


class InvitationOut(BaseModel):
    """An invitation as the API reports it — never the token and never its hash."""

    id: str
    user_id: str
    username: str
    display_name: str
    email: str
    role: str
    state: str
    created: str
    expires: str
    accepted: str
    revoked: str
    created_by: str
    revoked_reason: str
    #: Has the invited account ever signed in? (``""`` = never.)
    last_login: str


class InvitationList(BaseModel):
    """``GET /invitations`` body."""

    items: list[InvitationOut]
    total: int


class InvitationCreated(BaseModel):
    """The ONE response that carries the link. The token appears here and nowhere else —
    not in the list, not in an event, not in a log; a lost link is re-invited, never
    recovered."""

    invitation: InvitationOut
    #: The link to give the person. Absolute when the deployment knows its own address
    #: (``CRB_PUBLIC_URL``), else the path alone with ``public_url_missing`` set.
    accept_url: str
    token: str
    #: True when the deployment has no ``public_url``, so the link is a path the admin must
    #: prefix with this deployment's address by hand.
    public_url_missing: bool = False


class InviteRequest(BaseModel):
    """``POST /invitations`` body."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=2, max_length=64)
    role: str = "approver"
    display_name: str = Field(default="", max_length=256)
    email: str = Field(default="", max_length=256)
    expires_hours: int = Field(
        default=DEFAULT_EXPIRY_HOURS, ge=MIN_EXPIRY_HOURS, le=MAX_EXPIRY_HOURS
    )


class RevokeRequest(BaseModel):
    """``POST /invitations/{id}/revoke`` body — the reason is recorded, so it is required."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class AcceptRequest(BaseModel):
    """``POST /invitations/accept`` body: the token from the link and the password the
    person chooses. Never echoed, never logged."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=8, max_length=512)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class AcceptedOut(BaseModel):
    """What the link's page says afterwards: which account is now live, in what role, and
    that the next step is to sign in. No session is issued here — the person signs in with
    the password they just chose, so the first thing the account does is prove it."""

    username: str
    display_name: str
    role: str
    accepted: str


class TwoPersonReadinessOut(BaseModel):
    """Can this deployment produce a sign-off the two-person rule will accept?

    ``ready`` is the whole answer; ``reason_code`` and ``reason`` say why when it is False.
    The counts are the reading's own evidence, so a screen can show what is missing rather
    than repeat the sentence.
    """

    ready: bool
    reason_code: str
    reason: str
    #: Active accounts whose role can sign a cell (``approver`` or ``admin``).
    approvers_active: int
    #: …of those, how many have ever signed in (an account that never has cannot sign).
    approvers_signed_in: int
    #: Active accounts other than those approvers — who would run the measurements.
    other_active_accounts: int
    #: Active accounts that have EVER signed in. An account that never has can neither run
    #: anything nor sign anything, so it cannot be either of the two people.
    accounts_signed_in: int
    #: Invitations still waiting to be used.
    invitations_pending: int


def _username(user: User) -> str:
    return user.subject.removeprefix("local:") if user.issuer == LOCAL_ISSUER else user.subject


def invitation_state(inv: Invitation, *, now: _dt.datetime | None = None) -> str:
    """Where an invitation stands, in the order that decides it: accepted, revoked, expired,
    else pending. Accepted first — a link that was used stays used whatever the clock says."""
    if inv.accepted:
        return STATE_ACCEPTED
    if inv.revoked:
        return STATE_REVOKED
    if inv.expires and inv.expires <= _iso(now or _now()):
        return STATE_EXPIRED
    return STATE_PENDING


def _out(inv: Invitation, user: User | None) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        user_id=inv.user_id,
        username=_username(user) if user is not None else "",
        display_name=user.display_name if user is not None else "",
        email=user.email if user is not None else "",
        role=inv.role,
        state=invitation_state(inv),
        created=inv.created,
        expires=inv.expires,
        accepted=inv.accepted,
        revoked=inv.revoked,
        created_by=inv.created_by,
        revoked_reason=inv.revoked_reason,
        last_login=user.last_login if user is not None else "",
    )


def _users_by_id(db: Session, ids: list[str]) -> dict[str, User]:
    if not ids:
        return {}
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    return {u.id: u for u in rows}


@router.get("/invitations", response_model=InvitationList, responses={401: _ERR, 403: _ERR})
def list_invitations(admin: AdminDep, db: DbDep) -> InvitationList:
    """Every invitation, newest first, with the state each one is in. No token, no hash."""
    del admin
    rows = list(db.execute(select(Invitation).order_by(Invitation.created.desc())).scalars().all())
    users = _users_by_id(db, [r.user_id for r in rows])
    return InvitationList(items=[_out(r, users.get(r.user_id)) for r in rows], total=len(rows))


@router.post(
    "/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Invite the second person: an inactive account plus a one-time link (admin)",
)
def create_invitation(
    body: InviteRequest, admin: AdminDep, db: DbDep, settings: SettingsDep
) -> InvitationCreated:
    """The account is created INACTIVE with a password nobody knows, so the link is the only
    way in and it expires. The token is in this response and nowhere else."""
    role = validate_role(body.role)
    if role not in INVITABLE_ROLES:
        raise ApiError(
            422,
            "validation_error",
            f"an invitation is for a role that can sign a cell: {', '.join(INVITABLE_ROLES)}",
            detail={"field": "role", "allowed": list(INVITABLE_ROLES)},
        )
    lock_users_table(db)
    user = create_local_user(
        db,
        username=body.username,
        # nobody knows this: the person sets their own on accept, and until then the account
        # is inactive as well — two reasons the invitation is the only way in
        password=secrets.token_urlsafe(TOKEN_BYTES),
        role=role,
        display_name=body.display_name,
        email=body.email,
    )
    user.active = False
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = _now()
    inv = Invitation(
        id=uuid.uuid4().hex,
        user_id=user.id,
        token_hash=token_hash(token),
        role=role,
        created=_iso(now),
        expires=_iso(now + _dt.timedelta(hours=body.expires_hours)),
        created_by=admin.id,
    )
    db.add(inv)
    db.flush()
    record_user_event(
        db,
        action="user.invited",
        actor=admin.id,
        target=user,
        invitation=inv.id,
        expires=inv.expires,
    )
    db.commit()
    base = str(settings.public_url or "").rstrip("/")
    path = f"/invite?token={quote(token, safe='')}"
    return InvitationCreated(
        invitation=_out(inv, user),
        accept_url=f"{base}{path}" if base else path,
        token=token,
        public_url_missing=not base,
    )


@router.post(
    "/invitations/{invitation_id}/revoke",
    response_model=InvitationOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Withdraw an unused invitation (admin); the inactive account is left alone",
)
def revoke_invitation(
    invitation_id: str, body: RevokeRequest, admin: AdminDep, db: DbDep
) -> InvitationOut:
    """The link stops working. The account stays as it is — inactive, unusable — because
    removing an account is a different act with a different record."""
    inv = db.get(Invitation, invitation_id)
    if inv is None:
        raise ApiError(404, "not_found", f"no invitation {invitation_id!r}")
    state = invitation_state(inv)
    if state == STATE_ACCEPTED:
        raise ApiError(
            409,
            "already_accepted",
            "this invitation was used: the account exists, so deactivate the account rather "
            "than the link",
        )
    if state == STATE_REVOKED:
        return _out(inv, db.get(User, inv.user_id))
    inv.revoked = _iso(_now())
    inv.revoked_reason = body.reason
    user = db.get(User, inv.user_id)
    if user is not None:
        record_user_event(
            db,
            action="user.invite_revoked",
            actor=admin.id,
            target=user,
            invitation=inv.id,
            reason=body.reason,
        )
    db.commit()
    return _out(inv, user)


@router.post(
    "/invitations/accept",
    response_model=AcceptedOut,
    responses={401: _ERR, 409: _ERR, 422: _ERR, 429: _ERR},
    summary="Redeem an invitation: set your own password; the account is activated",
)
def accept_invitation(
    body: AcceptRequest, request: Request, db: DbDep, settings: SettingsDep
) -> AcceptedOut:
    """No session is needed — this IS the link's page — so the path is rate-limited per IP
    and answers a bad, spent, revoked or expired token with the same 401 ``invalid_token``:
    what a caller learns from a wrong guess is nothing. No session is issued either: the
    person signs in with the password they have just chosen."""
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = client_ip(request, settings)
    retry = limiter.retry_after(_ACCEPT_LIMIT_KEY, ip)
    if retry is not None:
        wait = math.ceil(retry)
        raise ApiError(
            429,
            "rate_limited",
            "too many attempts; try again later",
            detail={"retry_after_s": wait},
            headers={"Retry-After": str(wait)},
        )
    lock_users_table(db)
    inv = db.execute(
        select(Invitation).where(Invitation.token_hash == token_hash(body.token))
    ).scalar_one_or_none()
    user = db.get(User, inv.user_id) if inv is not None else None
    if inv is None or user is None or invitation_state(inv) != STATE_PENDING:
        db.rollback()  # nothing to write: release the users lock now
        limiter.record_failure(_ACCEPT_LIMIT_KEY, ip)
        raise ApiError(
            401,
            "invalid_token",
            "this invitation link is not valid: it may have been used, withdrawn or expired "
            "— ask your admin for a new one",
        )
    if not is_local_account(user):
        db.rollback()
        raise ApiError(
            409,
            "not_local",
            "this account signs in through the organisation's identity provider; it needs no "
            "password here",
        )
    limiter.reset(_ACCEPT_LIMIT_KEY, ip)
    # activate FIRST: ``set_user_active`` re-reads the row under the users lock
    # (``Session.refresh``), which would discard a password set in this transaction
    set_user_active(db, user, True)
    set_password(user, body.password)
    inv.accepted = _iso(_now())
    record_user_event(
        db, action="user.invite_accepted", actor=user.id, target=user, invitation=inv.id
    )
    db.commit()
    return AcceptedOut(
        username=_username(user),
        display_name=user.display_name,
        role=user.role,
        accepted=inv.accepted,
    )


def two_person_readiness(db: Session) -> TwoPersonReadinessOut:
    """Whether a sign-off the two-person rule accepts is possible in this deployment.

    Three things must hold, and each failing one has its own reason code: an active account
    whose role can sign (``approver`` or above); that account having signed in at least once
    — an invited account that never arrived can sign nothing, and neither can one whose
    password was set and never used; and a SECOND account that has signed in, because the
    approver who produced the evidence is refused (``same_actor``, ADR-0016).

    It counts accounts, not people, and says so in its reason: two accounts held by one
    person would pass this check and still be wrong. That is a limit of what a deployment
    can observe, written down rather than papered over.
    """
    users = list(db.execute(select(User).where(User.active.is_(True))).scalars().all())
    approvers = [u for u in users if ROLE_RANK.get(u.role, -1) >= ROLE_RANK["approver"]]
    signed_in = [u for u in approvers if u.last_login]
    arrived = [u for u in users if u.last_login]
    others = len(users) - len(approvers)
    pending = sum(
        1
        for inv in db.execute(select(Invitation)).scalars().all()
        if invitation_state(inv) == STATE_PENDING
    )
    if not approvers:
        code = NO_APPROVER
    elif not signed_in:
        code = APPROVER_NEVER_SIGNED_IN
    elif len(arrived) < 2:
        # one account has ever arrived, and it is the one that would have to sign its own work
        code = SINGLE_PERSON
    else:
        code = READY
    return TwoPersonReadinessOut(
        ready=code == READY,
        reason_code=code,
        reason=_REASONS[code],
        approvers_active=len(approvers),
        approvers_signed_in=len(signed_in),
        other_active_accounts=others,
        accounts_signed_in=len(arrived),
        invitations_pending=pending,
    )


@router.get(
    "/two-person-readiness",
    response_model=TwoPersonReadinessOut,
    responses={401: _ERR},
    summary="Can this deployment produce a sign-off the two-person rule accepts?",
)
def get_two_person_readiness(viewer: ViewerDep, db: DbDep) -> TwoPersonReadinessOut:
    """Readable by every signed-in role: a viewer who cannot invite anybody still needs to
    know whether the deployment can license anything (Home task 7 shows the state to
    everyone and the action only to an admin)."""
    del viewer
    return two_person_readiness(db)


__all__ = [
    "DEFAULT_EXPIRY_HOURS",
    "INVITABLE_ROLES",
    "STATE_ACCEPTED",
    "STATE_EXPIRED",
    "STATE_PENDING",
    "STATE_REVOKED",
    "InvitationCreated",
    "InvitationOut",
    "TwoPersonReadinessOut",
    "invitation_state",
    "router",
    "token_hash",
    "two_person_readiness",
]
