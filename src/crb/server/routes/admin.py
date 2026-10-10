"""``/users``, ``/settings`` and ``/settings/secrets`` — admin only (``/users/me/password``
is any signed-in local account).

Lockout protection: the last active admin can neither be demoted nor deactivated,
so a deployment can never reach a state where nobody can administer it.
Settings are served through :meth:`Settings.redacted_dict` only.

User lifecycle (F23): an admin sets any local account's password
(``PUT /users/{id}/password``) or active flag (``PUT /users/{id}/active``); a person
changes their own password with the current one (``PUT /users/me/password``). Every
change is one transaction with a ``system`` event on the account's trace
(``user.created`` / ``user.role_set`` / ``user.password_set`` / ``user.activated`` /
``user.deactivated`` / ``user.sessions_revoked``; actor and target ids, never a
password). A password change ends the account's other sessions (the cookie is bound to
the credential version); the response to a self-change carries a fresh cookie so the
person is not logged out of the browser they changed it in. "Sign out everywhere"
(``POST /users/{id}/sessions/revoke``) rotates the account's session nonce, which ends
every session it holds — the one way to end an OIDC account's sessions, which has no
password here. Deactivation refuses the account's requests while it is inactive and
rotates the same nonce, so its sessions end for good: re-activating it brings none back
(AUTH-3). The same primitives serve the ``crb users`` CLI on the host.

An invited account (``/invitations``) that the admin opens here instead — activates it, on
its own or with a role change, or sets its password — has its unused link withdrawn in the
same transaction (:func:`supersede_invitations`, reason ``superseded: …``): a one-time link
must never outlive another way into the same account (P-353).

Secrets (``/settings/secrets/*``) go through :mod:`crb.server.secrets`: a value is
accepted on ``PUT`` and written owner-only to disk; every response — including the
``PUT`` itself — is a :class:`SecretStatusOut` (presence, ≤4-char fingerprint,
who/when), never the value. ``PUT``/``DELETE``/``verify`` are admin-only; the status
list is readable by any signed-in role (it is non-secret by construction) — a **viewer**
sees presence only (:class:`SecretPresenceOut`, exactly ``{name, present}``; the
fingerprint, who set it and when are the operating roles' business, F25). ``verify``
runs the builder's own login probe and is rate-limited to one per 10 s so it cannot
be used to burn quota.

Navigation
----------
What it is:   The admin route module — ``/users`` (list, create, role, password, active,
              sign out everywhere, self password, the account's events), ``/settings`` and
              ``/settings/secrets``.
What it does: Lists and creates local accounts, changes roles and the active flag without
              ever orphaning the last active admin, or the last one who can sign in by this
              deployment's paths (409 ``last_admin``), sets a password as
              an admin or as oneself (current password required; 409 ``not_local`` for an
              OIDC account), records every account change as a ``system`` event with actor
              and target, serves each account's own ``user.*`` trail newest first
              (``GET /users/{id}/events``), serves the redacted settings view with the
              builders' configured flags, and stores / removes / verifies the Claude Code
              login token and the tracker token while answering only statuses (never a
              value) — every store and removal, and every token the sign-in helper stored,
              one ``settings.secret_set`` / ``settings.secret_deleted`` event naming the
              admin (EI-8; a helper-stored token is recorded by the next read of the secrets
              list or of a sign-in, with the helper's ``stored_at``); a write that records
              nothing is named in the test that says why.
How:          Every handler takes ``AdminDep`` (the secrets status list takes ``ViewerDep``
              because a status is non-secret, and projects a viewer's copy down to
              presence; the self password change ``CurrentUser``); the lifecycle handlers call
              ``set_password`` / ``set_user_active`` in src/crb/server/auth.py and
              ``append_system_event`` in one transaction; the secrets handlers delegate to
              src/crb/server/secrets.py and translate its exceptions into 422 / 409 / 429.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/auth.py (``create_local_user``, ``set_password``,
              ``set_user_active``, ``would_orphan_admins``, ``credential_version``),
              src/crb/server/routes/runs.py (``append_system_event`` / ``system_trace_id`` —
              the account audit trail), src/crb/server/routes/invitations.py (the link an
              admin act here withdraws), src/crb/cli/commands/users.py (the break-glass CLI
              over the same primitives and events), src/crb/server/secrets.py
              (``SecretsFile``, the verify limiter), src/crb/server/settings.py
              (``redacted_dict``), src/crb/observability/probes.py (``probe_builders`` for
              the configured flags), ui/src/api/types.ts (the ``Settings`` shape the UI
              renders), docs/API.md#admin
Tested by:    tests/test_server_admin_users.py, tests/test_server_routes_admin_secrets.py,
              tests/test_server_auth.py, tests/test_server_system.py
Touch when:   never for a new repository; adding a secret means a route pair here plus a
              ``SecretSpec`` in src/crb/server/secrets.py; adding a settings field means
              ``redacted_dict`` first, then the UI type; a new account action needs a
              ``user.*`` event here AND in the CLI.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crb.builders.claude_code import (
    AUTH_CLI,
    CLI_TOKEN_SECRET,
    TOKEN_SOURCE_SECRETS_FILE,
    VERIFY_STATUSES,
)
from crb.core.routing import POLICY_VERSION
from crb.core.secrets_file import SecretsInsecure
from crb.core.version import APPARATUS_VERSION
from crb.observability.probes import probe_builders
from crb.server.auth import (
    LOCAL_ISSUER,
    AdminDep,
    CurrentUser,
    LoginRateLimited,
    LoginRateLimiter,
    SignInPaths,
    ViewerDep,
    clear_auth_cookies,
    create_local_user,
    credential_version,
    is_local_account,
    lock_users_table,
    rate_limited_error,
    rotate_session_nonce,
    set_account_active,
    set_csrf_cookie,
    set_password,
    set_session_cookie,
    set_user_active,
    validate_role,
    verify_password,
    would_orphan_admins,
)
from crb.server.builder_login import TRIGGER_STORED_TOKEN, record_verification, resolution_of
from crb.server.claude_login import STATE_DONE, LoginError
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    SessionFactoryDep,
    SettingsDep,
    client_ip,
)
from crb.server.routes.runs import (
    append_system_event,
    commit_audited,
    event_to_dict,
    system_trace_id,
)
from crb.server.schemas import Page, PageDep, StepEventOut
from crb.server.secrets import (
    CLAUDE_CODE_TOKEN_MAX_LEN,
    TRACKER_TOKEN_MAX_LEN,
    TRACKER_TOKEN_SECRET,
    LoginBrokerDep,
    SecretsDep,
    VerifyLimiterDep,
)
from crb.server.settings import MIN_PASSWORD_LENGTH, ROLE_LADDER
from crb.store.models import Event, Invitation, User

router = APIRouter(tags=["admin"])
_ERR = {"model": ErrorEnvelope}


class UserOut(BaseModel):
    """A user as the admin API reports it — never ``password_hash``. ``username`` is what
    a person types at the local login (the ``subject`` without its ``local:`` namespace);
    for an OIDC account it is the provider's subject, which the admin never typed."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    subject: str
    username: str = ""
    issuer: str
    email: str
    display_name: str
    role: str
    active: bool
    created: str
    last_login: str


class UserList(BaseModel):
    """``GET /users`` body."""

    items: list[UserOut]
    total: int


def _user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.username = _username(user)
    return out


class CreateUserRequest(BaseModel):
    """``POST /users`` body; the password bound mirrors ``MIN_PASSWORD_LENGTH``."""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    role: str = "viewer"
    display_name: str = Field(default="", max_length=256)
    email: str = Field(default="", max_length=256)


class RoleChange(BaseModel):
    """``PUT /users/{id}/role`` body; ``active`` omitted leaves the flag as it is."""

    role: str
    active: bool | None = None


class PasswordSet(BaseModel):
    """``PUT /users/{id}/password`` body (an admin sets it; the bound mirrors
    ``MIN_PASSWORD_LENGTH``). Never echoed, never logged."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class PasswordChange(BaseModel):
    """``PUT /users/me/password`` body: the current password proves it is the account's
    owner and not a borrowed session that is changing it."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class ActiveChange(BaseModel):
    """``PUT /users/{id}/active`` body."""

    model_config = ConfigDict(extra="forbid")

    active: bool


def user_trace_id(user_id: str) -> str:
    """The ``system`` trace every event about one account lands on (``users:<id>``)."""
    return system_trace_id("users", user_id)


def record_user_event(
    db: Session, *, action: str, actor: str, target: User, **payload: Any
) -> None:
    """One ``user.*`` event on the target's trace, in the caller's transaction. The payload
    names the target (id, username, role, active) and what changed — never a password
    or a hash."""
    append_system_event(
        db,
        trace_id=user_trace_id(target.id),
        action=action,
        actor=actor,
        payload={
            "target": target.id,
            "username": _username(target),
            "role": target.role,
            "active": target.active,
            **payload,
        },
    )


#: The first word of the reason a link is withdrawn with when the account it would open was
#: opened another way (P-353).
SUPERSEDED = "superseded"


def supersede_invitations(db: Session, user: User, *, actor: str, how: str) -> int:
    """Withdraw every unused, unexpired invitation to ``user``; the caller commits.

    A one-time link is a way into one account. When that account is opened another way —
    the admin activates it or sets its password, or the accept route finds it already
    active — the link must stop working at that moment, not when it expires: otherwise
    whoever holds it could still set a new password, end the person's sessions and take a
    signing account (the independent verifiers' attack on stream S, P-353). Each link is
    marked revoked with the reason ``superseded: <how>`` and a ``user.invite_revoked``
    event on the account's trace — never the token. Returns how many were withdrawn."""
    now = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()
    pending = db.execute(
        select(Invitation).where(
            Invitation.user_id == user.id, Invitation.accepted == "", Invitation.revoked == ""
        )
    ).scalars()
    withdrawn = 0
    for inv in pending:
        if inv.expires and inv.expires <= now:
            continue  # an expired link opens nothing already, and its state says so
        inv.revoked = now
        inv.revoked_reason = f"{SUPERSEDED}: {how}"
        record_user_event(
            db,
            action="user.invite_revoked",
            actor=actor,
            target=user,
            invitation=inv.id,
            reason=inv.revoked_reason,
        )
        withdrawn += 1
    return withdrawn


def sign_in_trace_id(user_id: str) -> str:
    """The ``system`` trace every sign-in of one account lands on (``signins:<id>``) — apart
    from the account trail, because a sign-in changes nothing about the account."""
    return system_trace_id("signins", user_id)


def record_sign_in(db: Session, *, user: User, by: str) -> None:
    """One ``user.signed_in`` event, in the caller's transaction: every successful sign-in,
    so a recovery is timed to the first after a reset (ADR-0028 §8, DL-220). The payload
    names the account and the way in — never a password or a hash."""
    append_system_event(
        db,
        trace_id=sign_in_trace_id(user.id),
        action="user.signed_in",
        actor=user.id,
        payload={"target": user.id, "by": by},
    )


def _username(user: User) -> str:
    return user.subject.removeprefix("local:") if user.issuer == LOCAL_ISSUER else user.subject


def _get_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", f"no user {user_id!r}")
    return user


# --- secrets (request/response models live here on purpose: schemas.py is shared) ------


class SecretStatusOut(BaseModel):
    """What the API says about a stored secret. ``fingerprint`` is at most the last
    four characters of the value (empty when absent); nothing else of the value."""

    name: str
    present: bool
    fingerprint: str = Field(default="", max_length=4)
    set_at: str = ""
    set_by: str = ""


class SecretPresenceOut(BaseModel):
    """A viewer's copy of a status: presence only. A distinct model, not a blanked
    :class:`SecretStatusOut`, so the wire shape is exactly ``{name, present}`` (F25)."""

    name: str
    present: bool


class SecretsStatusList(BaseModel):
    """``GET /settings/secrets`` body. ``items`` are :class:`SecretStatusOut` for operators
    and above, :class:`SecretPresenceOut` for a viewer — one list, never mixed."""

    items: list[SecretStatusOut] | list[SecretPresenceOut]
    #: Where the files live on the API host (admins only — so they can find / mount /
    #: rotate); ``""`` for every other role.
    secrets_dir: str = ""


class ClaudeCodeTokenIn(BaseModel):
    """The pasted ``claude setup-token`` value. Validated for shape in the route."""

    token: str = Field(min_length=1, max_length=CLAUDE_CODE_TOKEN_MAX_LEN)


class TrackerTokenIn(BaseModel):
    """The pasted tracker credential — an Azure DevOps personal access token or a Jira
    API token. Validated for shape in the route; the value is never echoed back."""

    token: str = Field(min_length=1, max_length=TRACKER_TOKEN_MAX_LEN)


class LoginSessionOut(BaseModel):
    """A Claude sign-in session (``crb.server.claude_login.SessionState``): its state, the
    URL to open while ``awaiting_code``, a redacted ``detail``, and — once ``done`` — the
    stored token's four-character fingerprint. Never a code, never the token."""

    id: str
    state: str = Field(
        description="pending_url | awaiting_code | exchanging | done | failed | expired | cancelled"
    )
    url: str = ""
    detail: str = ""
    started_at: str = ""
    expires_at: str = ""
    fingerprint: str = Field(default="", max_length=4)


class LoginCodeIn(BaseModel):
    """The code Anthropic's page shows after the person approves (optionally ``#state``)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=8, max_length=512)


class LoginCheckOut(BaseModel):
    """The verify probe's outcome (``crb.builders.claude_code.LoginCheck``)."""

    status: str = Field(description="one of " + " | ".join(VERIFY_STATUSES))
    detail: str = ""
    source: str = ""
    fingerprint: str = Field(default="", max_length=4)
    model: str = ""
    cli_version: str = ""
    duration_s: float = 0.0
    cost_usd: float | None = None


@router.get("/users", response_model=UserList, responses={401: _ERR, 403: _ERR})
def list_users(admin: AdminDep, db: DbDep) -> UserList:
    """Every account, oldest first."""
    del admin
    users = list(db.execute(select(User).order_by(User.created, User.id)).scalars())
    return UserList(items=[_user_out(u) for u in users], total=len(users))


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Create a local account",
)
def create_user(body: CreateUserRequest, admin: AdminDep, db: DbDep) -> UserOut:
    """Create a local account (409 when the username is taken)."""
    user = create_local_user(
        db,
        username=body.username,
        password=body.password,
        role=body.role,
        display_name=body.display_name,
        email=body.email,
    )
    record_user_event(db, action="user.created", actor=admin.id, target=user)
    db.commit()
    return _user_out(user)


@router.put(
    "/users/{user_id}/role",
    response_model=UserOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Change a user's role (and optionally active flag); never orphans the last admin",
)
def set_role(
    user_id: str, body: RoleChange, admin: AdminDep, db: DbDep, settings: SettingsDep
) -> UserOut:
    """Change role and/or active flag; refuses the change that would leave no admin."""
    validate_role(body.role)
    # Count and update in one serialised transaction: two concurrent demotions of the two
    # remaining admins each saw "2 admins" and together left none (CodeRabbit on PR #4,
    # 2026-09-15). SQLite takes the write lock up front; Postgres an advisory lock.
    lock_users_table(db)
    user = _get_user(db, user_id)
    new_active = user.active if body.active is None else body.active
    sign_in = SignInPaths.of(settings)
    if would_orphan_admins(db, user, role=body.role, active=new_active, sign_in=sign_in):
        raise ApiError(
            409,
            "last_admin",
            "refusing to demote or deactivate the last active admin",
            detail={"allowed": list(ROLE_LADDER)},
        )
    was_role, was_active = user.role, user.active
    user.role = body.role
    set_account_active(user, new_active)  # turning it off ends its sessions (AUTH-3)
    if user.role != was_role:
        record_user_event(
            db, action="user.role_set", actor=admin.id, target=user, from_role=was_role
        )
    if user.active != was_active:
        record_user_event(
            db,
            action="user.activated" if user.active else "user.deactivated",
            actor=admin.id,
            target=user,
        )
        if user.active:
            supersede_invitations(db, user, actor=admin.id, how="the admin activated the account")
    db.commit()
    return _user_out(user)


@router.put(
    "/users/me/password",
    response_model=UserOut,
    responses={401: _ERR, 409: _ERR, 422: _ERR, 429: _ERR},
    summary="Change your own password (current password required); other sessions end",
)
def change_own_password(  # noqa: PLR0917 — FastAPI injects each dependency by name
    body: PasswordChange,
    me: CurrentUser,
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
) -> UserOut:
    """The caller's own account: the current password must verify (401
    ``invalid_credentials`` otherwise — the same envelope as a failed login, and the same
    per-(username, ip) limiter, so a borrowed session cannot guess it online), the new one
    is hashed and stored, and a fresh session cookie is set on this response so the
    browser that made the change stays signed in while every other session ends."""
    user = _get_user(db, me.id)
    if not is_local_account(user):
        raise ApiError(
            409,
            "not_local",
            "this account signs in through the organisation's identity provider; "
            "change its password there",
        )
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = client_ip(request, settings)
    username = _username(user)
    # reserved before the verify, as the login does (AUTH-1): a burst cannot outrun it
    try:
        slot = limiter.acquire(username, ip)
    except LoginRateLimited as exc:
        raise rate_limited_error(exc, "too many failed attempts; try again later") from None
    if not verify_password(user.password_hash, body.current_password):
        raise ApiError(401, "invalid_credentials", "current password is incorrect")
    limiter.succeed(slot)
    set_password(user, body.new_password)
    record_user_event(db, action="user.password_set", actor=me.id, target=user, by="self")
    db.commit()
    cv = credential_version(user)
    set_session_cookie(response, settings, user.id, cv)
    set_csrf_cookie(response, settings, user.id, cv)
    return _user_out(user)


@router.put(
    "/users/{user_id}/password",
    response_model=UserOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Set a user's password (admin); the user's sessions end",
)
def set_user_password(  # noqa: PLR0917 — FastAPI injects each dependency by name
    user_id: str,
    body: PasswordSet,
    admin: AdminDep,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
) -> UserOut:
    """Set a local account's password. Every session the account holds ends on its next
    request; when the admin sets their own, this response re-issues their cookie."""
    # Under the lock an acceptance of the account's link holds: one that had read the link
    # as pending went on to replace this password with the person's and stamp the withdrawn
    # link accepted (CodeRabbit on #81, 2026-10-10; docs/PREVENTION.md P-785).
    lock_users_table(db)
    user = _get_user(db, user_id)
    set_password(user, body.password)
    record_user_event(db, action="user.password_set", actor=admin.id, target=user, by="admin")
    supersede_invitations(db, user, actor=admin.id, how="the admin set the account's password")
    db.commit()
    if user.id == admin.id:
        cv = credential_version(user)
        set_session_cookie(response, settings, user.id, cv)
        set_csrf_cookie(response, settings, user.id, cv)
    return _user_out(user)


@router.post(
    "/users/{user_id}/sessions/revoke",
    response_model=UserOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="Sign a user out everywhere (admin): every session the account holds ends",
)
def revoke_user_sessions(
    user_id: str, admin: AdminDep, response: Response, settings: SettingsDep, db: DbDep
) -> UserOut:
    """Rotate the account's session nonce: every session it holds, on every device, ends on
    its next request — a local account or an OIDC one (which has no password here to
    change). The account can sign in again at once; to keep it out, deactivate it as well.
    Recorded as ``user.sessions_revoked``. When an admin signs themself out everywhere,
    this response clears their cookies too."""
    user = _get_user(db, user_id)
    rotate_session_nonce(user)
    record_user_event(db, action="user.sessions_revoked", actor=admin.id, target=user)
    db.commit()
    if user.id == admin.id:
        clear_auth_cookies(response, settings)
    return _user_out(user)


@router.put(
    "/users/{user_id}/active",
    response_model=UserOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Activate or deactivate a user; never deactivates the last active admin",
)
def set_active(
    user_id: str, body: ActiveChange, admin: AdminDep, db: DbDep, settings: SettingsDep
) -> UserOut:
    """Deactivating refuses every request of the account while it is inactive and ends every
    session it held for good (re-activating brings none back, AUTH-3); 409 ``last_admin``
    when it would leave no active admin, or none who can sign in. Idempotent. The
    idempotency and last-admin decisions are ``set_user_active``'s, taken under the users
    lock on a re-read row — the ``user`` loaded here is only the handle."""
    # Activating withdraws the account's link, so the lock comes before any read, as in every
    # route that withdraws or spends a link (docs/PREVENTION.md P-785); ``set_user_active``
    # takes it again, which re-enters it, and still re-reads the row.
    lock_users_table(db)
    user = _get_user(db, user_id)
    if not set_user_active(db, user, body.active, sign_in=SignInPaths.of(settings)):
        db.rollback()  # nothing to write: release the users lock now, not at teardown
        return _user_out(user)
    record_user_event(
        db,
        action="user.activated" if body.active else "user.deactivated",
        actor=admin.id,
        target=user,
    )
    if body.active:
        supersede_invitations(db, user, actor=admin.id, how="the admin activated the account")
    db.commit()
    return _user_out(user)


@router.get(
    "/users/{user_id}/events",
    response_model=Page[StepEventOut],
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="The account's audit trail: its user.* events, newest first (admin)",
)
def list_user_events(user_id: str, admin: AdminDep, db: DbDep, page: PageDep) -> Page[StepEventOut]:
    """Every ``user.*`` event on this account's own trace (``users:<id>``), newest first.

    The events are written by every lifecycle route above and by ``crb users`` on the host;
    this is the read side, so an auditor can see in the product who reset or disabled the
    account and when. Payloads are served verbatim as they were written — never recomputed,
    and they never hold a password or a hash (:func:`record_user_event`).
    """
    del admin
    _get_user(db, user_id)  # 404 before an empty page, so an unknown id is never "no events"
    trace = user_trace_id(user_id)
    total = int(
        db.execute(select(func.count(Event.id)).where(Event.trace_id == trace)).scalar_one()
    )
    items = list(
        db.execute(
            select(Event)
            .where(Event.trace_id == trace)
            .order_by(Event.seq.desc(), Event.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        ).scalars()
    )
    return Page[StepEventOut](
        items=[StepEventOut(**event_to_dict(m)) for m in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/settings", responses={401: _ERR, 403: _ERR}, summary="Non-secret settings")
def get_settings_view(admin: AdminDep, settings: SettingsDep) -> dict[str, Any]:
    """The UI's ``Settings`` shape (see ``ui/src/api/types.ts``) plus the full redacted
    settings under ``raw``. Secrets are reported only as configured yes/no."""
    del admin
    raw = settings.redacted_dict()
    probe = probe_builders()
    builders = [
        {"name": name, "configured": bool(flag)} for name, flag in sorted(probe.data.items())
    ]
    return {
        "builders": builders,
        "sandbox_mode": str(raw.get("sandbox", {}).get("executor", "")),
        "retention": dict(raw.get("retention", {})),
        "oidc_enabled": bool(raw.get("oidc", {}).get("enabled", False)),
        "ledger_backend": str(raw.get("database", {}).get("dialect", "")),
        "apparatus_version": APPARATUS_VERSION,
        "policy_version": POLICY_VERSION,
        "raw": raw,
    }


# --- /settings/secrets ---------------------------------------------------------------------

_CLAUDE_TOKEN_PATH = "/settings/secrets/claude-code-token"  # noqa: S105 — a URL path


def _status_out(status: Any) -> SecretStatusOut:
    """``SecretStatus`` → the response model."""
    return SecretStatusOut(**status.to_dict())


#: The ``system`` trace every change to a deployment credential lands on (EI-8).
SECRETS_TRACE = system_trace_id("settings", "secrets")


def _record_secret_change(
    db: Session, *, removed: bool, actor: str, secret: str, **payload: Any
) -> None:
    """One ``settings.secret_set`` / ``settings.secret_deleted`` event on
    :data:`SECRETS_TRACE`, in the caller's transaction: the actor is the account that made
    the change, the payload names the secret and at most its four-character fingerprint —
    never a value (EI-8: the only provenance was ``set_by``, which a removal wipes)."""
    append_system_event(
        db,
        trace_id=SECRETS_TRACE,
        action="settings.secret_deleted" if removed else "settings.secret_set",
        actor=actor,
        payload={"secret": secret, **payload},
    )


def _stored(
    db: Session, actor: str, secrets: Any, secret: str, token: str, *, set_by: str
) -> SecretStatusOut:
    """Store ``token`` as ``secret`` and record it, answering its status; 422
    ``invalid_token`` on a bad shape, 409 ``secrets_insecure`` when the directory is refused.

    Inside the audited write, the event is recorded and flushed FIRST, with the fingerprint
    worked out from the value, and the file is written last, so only the commit follows
    it (P-440, P-443): writing it before the lock, or before the event, let a refused lock
    or a database error while recording answer 500 with the token already replaced and no
    event (EI-8). A file cannot join the transaction, so a crash, or a commit that fails
    after the write, can still leave the change unrecorded; a lost ``seq`` race writes the
    same value again, which is safe."""
    out: dict[str, Any] = {}

    def write() -> None:
        try:
            fp = secrets.fingerprint_of(secret, token)
        except ValueError as exc:
            raise ApiError(422, "invalid_token", str(exc)) from None
        _record_secret_change(
            db, removed=False, actor=actor, secret=secret, fingerprint=fp, via="api"
        )
        db.flush()
        try:
            out["status"] = secrets.set(secret, token, set_by=set_by)
        except ValueError as exc:
            raise ApiError(422, "invalid_token", str(exc)) from None
        except SecretsInsecure as exc:
            raise ApiError(409, "secrets_insecure", str(exc)) from None

    commit_audited(db, write)
    return _status_out(out["status"])


def _removed(db: Session, actor: str, secrets: Any, secret: str) -> SecretStatusOut:
    """Remove ``secret``, record the removal (with whether anything was there) and answer
    the now-absent status; 409 ``secrets_insecure`` when the directory is refused.

    Removed inside the audited write after its event is recorded and flushed, as
    :func:`_stored` stores (P-440, P-443). A lost ``seq`` race runs ``write`` again and the
    removal is safe to repeat, but a run after the file went finds nothing, so whether the
    secret existed is read on the first run only."""
    out: dict[str, Any] = {}

    def write() -> None:
        try:
            if "existed" not in out:
                out["existed"] = bool(secrets.status(secret).present)
        except SecretsInsecure as exc:
            raise ApiError(409, "secrets_insecure", str(exc)) from None
        _record_secret_change(
            db, removed=True, actor=actor, secret=secret, existed=out["existed"], via="api"
        )
        db.flush()
        try:
            out["status"] = secrets.delete(secret)
        except SecretsInsecure as exc:
            raise ApiError(409, "secrets_insecure", str(exc)) from None

    commit_audited(db, write)
    return _status_out(out["status"])


def _record_login_stored(db: Session, broker: Any, st: Any, observer: str) -> None:
    """The sign-in helper stores the Claude token with no database, so the API writes the
    event when it next sees the session ``done`` — once per session, decided under the
    events lock — with the account that started the sign-in as actor and the helper's own
    ``stored_at``, so a late record still says when the token was stored. ``observer``
    names the actor only for an older session that did not record who started it, and only
    when the reader is an admin; otherwise (``""``) such a session waits for an admin read."""
    if st.state != STATE_DONE:
        return

    def recorded() -> bool:
        return (
            db.execute(
                select(Event.id)
                .where(
                    Event.trace_id == SECRETS_TRACE,
                    Event.action == "settings.secret_set",
                    Event.payload_json["session"].as_string() == st.id,
                )
                .limit(1)
            ).first()
            is not None
        )

    # The common case — a session recorded long ago — takes no lock and commits nothing: a
    # read every role polls must not serialise against every writer (P-230). Only a session
    # with no record takes the events lock, and it is checked again under it.
    if recorded():
        db.rollback()
        return
    try:
        meta = broker.meta(st.id)
    except (LoginError, OSError, ValueError):  # removed or damaged since it was listed
        meta = {}
    actor = str(meta.get("started_by_id") or observer)
    if not actor:
        return

    def write() -> None:
        if recorded():
            return
        stamp = {"stored_at": st.stored_at} if st.stored_at else {}
        _record_secret_change(
            db,
            removed=False,
            actor=actor,
            secret=CLI_TOKEN_SECRET,
            fingerprint=st.fingerprint,
            via="login",
            session=st.id,
            **stamp,
        )

    commit_audited(db, write)


def record_stored_logins(db: Session, broker: Any, observer: str = "") -> None:
    """Record every sign-in the helper finished that no read has recorded yet (EI-8): the
    secrets list, a new sign-in and the API's start call this, so an admin who pasted the
    code and closed the tab still leaves the event."""
    for done in broker.done_sessions():
        _record_login_stored(db, broker, done, observer)


@router.get(
    "/settings/secrets",
    response_model=SecretsStatusList,
    responses={401: _ERR},
    summary="Statuses of the operator-supplied secrets (never values); any signed-in role",
)
def list_secrets(
    user: ViewerDep, secrets: SecretsDep, broker: LoginBrokerDep, db: DbDep
) -> SecretsStatusList:
    """Readable by every role: a status is non-secret by construction (presence, at most
    four trailing characters, who set it when) and an operator needs it to know whether
    an ``auth: cli`` run can authenticate. A viewer gets presence only — exactly ``{name,
    present}`` per item — and only admins learn the directory path. A token the sign-in
    helper stored that nothing has recorded yet is recorded here first (EI-8)."""
    record_stored_logins(db, broker, user.id if user.role == "admin" else "")
    statuses = secrets.statuses()
    items: list[SecretStatusOut] | list[SecretPresenceOut]
    if user.role == "viewer":
        items = [SecretPresenceOut(name=st.name, present=st.present) for st in statuses]
    else:
        items = [_status_out(st) for st in statuses]
    return SecretsStatusList(
        items=items,
        secrets_dir=str(secrets.path) if user.role == "admin" else "",
    )


@router.put(
    _CLAUDE_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Store the Claude Code login token (claude setup-token) owner-only on the API host",
)
def put_claude_code_token(
    body: ClaudeCodeTokenIn, admin: AdminDep, secrets: SecretsDep, db: DbDep
) -> SecretStatusOut:
    """Store the token; the response is its status, never the value. Recorded as
    ``settings.secret_set`` naming the admin (EI-8)."""
    return _stored(
        db,
        admin.id,
        secrets,
        CLI_TOKEN_SECRET,
        body.token,
        set_by=admin.display_name or admin.id,
    )


@router.delete(
    _CLAUDE_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR},
    summary="Remove the stored Claude Code login token",
)
def delete_claude_code_token(admin: AdminDep, secrets: SecretsDep, db: DbDep) -> SecretStatusOut:
    """Remove the stored token (idempotent); recorded as ``settings.secret_deleted`` naming
    the admin, every time (EI-8)."""
    return _removed(db, admin.id, secrets, CLI_TOKEN_SECRET)


_TRACKER_TOKEN_PATH = "/settings/secrets/tracker-token"  # noqa: S105 — a URL path


@router.put(
    _TRACKER_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Store the tracker token the intake listener polls with (ADO PAT or Jira API token)",
)
def put_tracker_token(
    body: TrackerTokenIn, admin: AdminDep, secrets: SecretsDep, db: DbDep
) -> SecretStatusOut:
    """Store the credential owner-only on the API host; the response is its status — the
    fingerprint and who set it when — never the value. One credential per deployment: the
    listener on every repository polls with it (ADR-0017). Recorded as
    ``settings.secret_set`` naming the admin (EI-8)."""
    return _stored(
        db,
        admin.id,
        secrets,
        TRACKER_TOKEN_SECRET,
        body.token,
        set_by=admin.display_name or admin.id,
    )


@router.delete(
    _TRACKER_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR},
    summary="Remove the stored tracker token (every listener then stops with no_secret)",
)
def delete_tracker_token(admin: AdminDep, secrets: SecretsDep, db: DbDep) -> SecretStatusOut:
    """Remove the credential (idempotent). Nothing is polled afterwards: every listener
    stops with ``no_secret`` and says so on the Intake screen. Recorded as
    ``settings.secret_deleted`` naming the admin, every time (EI-8)."""
    return _removed(db, admin.id, secrets, TRACKER_TOKEN_SECRET)


_LOGIN_PATH = _CLAUDE_TOKEN_PATH + "/login"


def _session_out(state: Any) -> LoginSessionOut:
    return LoginSessionOut(**state.to_dict())


def _login_error(exc: LoginError) -> ApiError:
    status = {
        "not_found": 404,
        "cli_missing": 503,
        "cli_timeout": 503,
        "cli_failed": 503,
        "login_in_progress": 409,
        "wrong_state": 409,
        "invalid_code": 422,
    }.get(exc.code, 500)
    return ApiError(status, exc.code, str(exc))


@router.post(
    _LOGIN_PATH,
    response_model=LoginSessionOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 503: _ERR},
    summary="Start a Claude sign-in: runs `claude setup-token` on the API host and returns the URL to open",
)
def start_claude_login(admin: AdminDep, broker: LoginBrokerDep, db: DbDep) -> LoginSessionOut:
    """The front end opens ``url`` in a new tab; the person approves on Anthropic's page
    and pastes the code it shows into ``POST …/login/{id}/code``. The minted token goes
    straight into the owner-only secrets store on the API host — it is never returned."""
    try:
        # a finished sign-in nobody read back is recorded before the sweep can remove it
        record_stored_logins(db, broker, admin.id)
        broker.sweep()
        return _session_out(
            broker.start(started_by=admin.display_name or admin.id, started_by_id=admin.id)
        )
    except LoginError as exc:
        raise _login_error(exc) from None


@router.get(
    _LOGIN_PATH + "/{session_id}",
    response_model=LoginSessionOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="The sign-in session's state (poll while `exchanging`)",
)
def get_claude_login(
    session_id: str, admin: AdminDep, broker: LoginBrokerDep, db: DbDep
) -> LoginSessionOut:
    try:
        st = broker.state(session_id)
        _record_login_stored(db, broker, st, admin.id)
    except LoginError as exc:
        raise _login_error(exc) from None
    return _session_out(st)


@router.post(
    _LOGIN_PATH + "/{session_id}/code",
    response_model=LoginSessionOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Deliver the code Anthropic showed; the helper exchanges it and stores the token",
)
def submit_claude_login_code(
    session_id: str, body: LoginCodeIn, admin: AdminDep, broker: LoginBrokerDep, db: DbDep
) -> LoginSessionOut:
    try:
        st = broker.submit_code(session_id, body.code)
        _record_login_stored(db, broker, st, admin.id)
    except LoginError as exc:
        raise _login_error(exc) from None
    return _session_out(st)


@router.delete(
    _LOGIN_PATH + "/{session_id}",
    response_model=LoginSessionOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="Cancel a sign-in session (stops the helper; nothing is stored)",
)
def cancel_claude_login(
    session_id: str, admin: AdminDep, broker: LoginBrokerDep
) -> LoginSessionOut:
    del admin
    try:
        return _session_out(broker.cancel(session_id))
    except LoginError as exc:
        raise _login_error(exc) from None


@router.post(
    _CLAUDE_TOKEN_PATH + "/verify",
    response_model=LoginCheckOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 429: _ERR},
    summary="Test the stored token: one no-tool Haiku turn through the builder's own environment",
)
def verify_claude_code_token(
    admin: AdminDep,
    secrets: SecretsDep,
    limiter: VerifyLimiterDep,
    settings: SettingsDep,
    factory: SessionFactoryDep,
) -> LoginCheckOut:
    """Run the builder's login probe with the stored token (429 inside the rate window). When
    the stored token IS the login a ``cli`` build would use (no token in the worker's
    environment overrides it), the outcome is recorded for the run preflight and the
    ``builders`` probe, like Verify under the login card (pilot D1)."""
    retry = limiter.acquire()
    if retry is not None:
        wait = math.ceil(retry)
        raise ApiError(
            429,
            "rate_limited",
            f"verify runs at most once every {int(limiter.min_interval_s)} s; retry in {wait} s",
            detail={"retry_after_s": wait},
            headers={"Retry-After": str(wait)},
        )
    try:
        check = secrets.verify(CLI_TOKEN_SECRET, binary=settings.builder.claude_binary)
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None
    if check is None:
        raise ApiError(404, "not_found", "no Claude Code token is stored — save one first")
    resolution = resolution_of("claude_code", AUTH_CLI)
    if resolution == (TOKEN_SOURCE_SECRETS_FILE, check.fingerprint):
        record_verification(
            factory,
            "claude_code",
            AUTH_CLI,
            check,
            trigger=TRIGGER_STORED_TOKEN,
            actor=admin.id,
            resolution=resolution,
        )
    return LoginCheckOut(**check.to_dict())


__all__ = ["router"]
