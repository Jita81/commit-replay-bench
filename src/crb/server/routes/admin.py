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
``user.deactivated``; actor and target ids, never a password). A password change ends
the account's other sessions (the cookie is bound to the credential version); the
response to a self-change carries a fresh cookie so the person is not logged out of the
browser they changed it in. Deactivation refuses the account's requests while it is
inactive; it does not move the credential version, so re-activating within the session
lifetime restores the sessions issued before — to contain a compromised account, set a
new password as well. The same primitives serve the ``crb users`` CLI on the host.

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
              self password), ``/settings`` and ``/settings/secrets``.
What it does: Lists and creates local accounts, changes roles and the active flag without
              ever orphaning the last active admin (409 ``last_admin``), sets a password as
              an admin or as oneself (current password required; 409 ``not_local`` for an
              OIDC account), records every account change as a ``system`` event with actor
              and target, serves the redacted settings view with the builders' configured
              flags, and stores / removes / verifies the Claude Code login token while
              answering only statuses (never a value).
How:          Every handler takes ``AdminDep`` (the secrets status list takes ``ViewerDep``
              because a status is non-secret, and projects a viewer's copy down to
              presence; the self password change ``CurrentUser``); the lifecycle handlers call
              ``set_password`` / ``set_user_active`` in src/crb/server/auth.py and
              ``append_system_event`` in one transaction; the secrets handlers delegate to
              src/crb/server/secrets.py and translate its exceptions into 422 / 409 / 429.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/auth.py (``create_local_user``, ``set_password``,
              ``set_user_active``, ``count_active_admins``, ``credential_version``),
              src/crb/server/routes/runs.py (``append_system_event`` / ``system_trace_id`` —
              the account audit trail), src/crb/cli/commands/users.py (the break-glass CLI
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

import math
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crb.builders.claude_code import CLI_TOKEN_SECRET, VERIFY_STATUSES
from crb.core.routing import POLICY_VERSION
from crb.core.secrets_file import SecretsInsecure
from crb.core.version import APPARATUS_VERSION
from crb.observability.probes import probe_builders
from crb.server.auth import (
    LOCAL_ISSUER,
    AdminDep,
    CurrentUser,
    LoginRateLimiter,
    ViewerDep,
    count_active_admins,
    create_local_user,
    credential_version,
    is_local_account,
    lock_users_table,
    set_csrf_cookie,
    set_password,
    set_session_cookie,
    set_user_active,
    validate_role,
    verify_password,
)
from crb.server.claude_login import LoginError
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep, client_ip
from crb.server.routes.runs import append_system_event, event_to_dict, system_trace_id
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
from crb.store.models import Event, User

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
def set_role(user_id: str, body: RoleChange, admin: AdminDep, db: DbDep) -> UserOut:
    """Change role and/or active flag; refuses the change that would leave no admin."""
    validate_role(body.role)
    # Count and update in one serialised transaction: two concurrent demotions of the two
    # remaining admins each saw "2 admins" and together left none (CodeRabbit on PR #4,
    # 2026-09-15). SQLite takes the write lock up front; Postgres an advisory lock.
    lock_users_table(db)
    user = _get_user(db, user_id)
    new_active = user.active if body.active is None else body.active
    loses_admin = user.role == "admin" and user.active and (body.role != "admin" or not new_active)
    if loses_admin and count_active_admins(db) <= 1:
        raise ApiError(
            409,
            "last_admin",
            "refusing to demote or deactivate the last active admin",
            detail={"allowed": list(ROLE_LADDER)},
        )
    was_role, was_active = user.role, user.active
    user.role = body.role
    user.active = new_active
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
    retry = limiter.retry_after(username, ip)
    if retry is not None:
        wait = math.ceil(retry)
        raise ApiError(
            429,
            "rate_limited",
            "too many failed attempts; try again later",
            detail={"retry_after_s": wait},
            headers={"Retry-After": str(wait)},
        )
    if not verify_password(user.password_hash, body.current_password):
        limiter.record_failure(username, ip)
        raise ApiError(401, "invalid_credentials", "current password is incorrect")
    limiter.reset(username, ip)
    set_password(user, body.new_password)
    record_user_event(db, action="user.password_set", actor=me.id, target=user, by="self")
    db.commit()
    set_session_cookie(response, settings, user.id, credential_version(user))
    set_csrf_cookie(response, settings)
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
    user = _get_user(db, user_id)
    set_password(user, body.password)
    record_user_event(db, action="user.password_set", actor=admin.id, target=user, by="admin")
    db.commit()
    if user.id == admin.id:
        set_session_cookie(response, settings, user.id, credential_version(user))
        set_csrf_cookie(response, settings)
    return _user_out(user)


@router.put(
    "/users/{user_id}/active",
    response_model=UserOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Activate or deactivate a user; never deactivates the last active admin",
)
def set_active(user_id: str, body: ActiveChange, admin: AdminDep, db: DbDep) -> UserOut:
    """Deactivating refuses every request of the account while it is inactive (re-activating
    within the session lifetime restores sessions issued before; a password set ends them
    for good); 409 ``last_admin`` when it would leave no active admin. Idempotent. The
    idempotency and last-admin decisions are ``set_user_active``'s, taken under the users
    lock on a re-read row — the ``user`` loaded here is only the handle."""
    user = _get_user(db, user_id)
    if not set_user_active(db, user, body.active):
        db.rollback()  # nothing to write: release the users lock now, not at teardown
        return _user_out(user)
    record_user_event(
        db,
        action="user.activated" if body.active else "user.deactivated",
        actor=admin.id,
        target=user,
    )
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


@router.get(
    "/settings/secrets",
    response_model=SecretsStatusList,
    responses={401: _ERR},
    summary="Statuses of the operator-supplied secrets (never values); any signed-in role",
)
def list_secrets(user: ViewerDep, secrets: SecretsDep) -> SecretsStatusList:
    """Readable by every role: a status is non-secret by construction (presence, at most
    four trailing characters, who set it when) and an operator needs it to know whether
    an ``auth: cli`` run can authenticate. A viewer gets presence only — exactly ``{name,
    present}`` per item — and only admins learn the directory path."""
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
    body: ClaudeCodeTokenIn, admin: AdminDep, secrets: SecretsDep
) -> SecretStatusOut:
    """Store the token; the response is its status, never the value."""
    try:
        stored = secrets.set(CLI_TOKEN_SECRET, body.token, set_by=admin.display_name or admin.id)
    except ValueError as exc:
        raise ApiError(422, "invalid_token", str(exc)) from None
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None
    return _status_out(stored)


@router.delete(
    _CLAUDE_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR},
    summary="Remove the stored Claude Code login token",
)
def delete_claude_code_token(admin: AdminDep, secrets: SecretsDep) -> SecretStatusOut:
    """Remove the stored token (idempotent)."""
    del admin
    try:
        return _status_out(secrets.delete(CLI_TOKEN_SECRET))
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None


_TRACKER_TOKEN_PATH = "/settings/secrets/tracker-token"  # noqa: S105 — a URL path


@router.put(
    _TRACKER_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Store the tracker token the intake listener polls with (ADO PAT or Jira API token)",
)
def put_tracker_token(
    body: TrackerTokenIn, admin: AdminDep, secrets: SecretsDep
) -> SecretStatusOut:
    """Store the credential owner-only on the API host; the response is its status — the
    fingerprint and who set it when — never the value. One credential per deployment: the
    listener on every repository polls with it (ADR-0017)."""
    try:
        stored = secrets.set(
            TRACKER_TOKEN_SECRET, body.token, set_by=admin.display_name or admin.id
        )
    except ValueError as exc:
        raise ApiError(422, "invalid_token", str(exc)) from None
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None
    return _status_out(stored)


@router.delete(
    _TRACKER_TOKEN_PATH,
    response_model=SecretStatusOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR},
    summary="Remove the stored tracker token (every listener then stops with no_secret)",
)
def delete_tracker_token(admin: AdminDep, secrets: SecretsDep) -> SecretStatusOut:
    """Remove the credential (idempotent). Nothing is polled afterwards: every listener
    stops with ``no_secret`` and says so on the Intake screen."""
    del admin
    try:
        return _status_out(secrets.delete(TRACKER_TOKEN_SECRET))
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None


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
def start_claude_login(admin: AdminDep, broker: LoginBrokerDep) -> LoginSessionOut:
    """The front end opens ``url`` in a new tab; the person approves on Anthropic's page
    and pastes the code it shows into ``POST …/login/{id}/code``. The minted token goes
    straight into the owner-only secrets store on the API host — it is never returned."""
    try:
        broker.sweep()
        return _session_out(broker.start(started_by=admin.display_name or admin.id))
    except LoginError as exc:
        raise _login_error(exc) from None


@router.get(
    _LOGIN_PATH + "/{session_id}",
    response_model=LoginSessionOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="The sign-in session's state (poll while `exchanging`)",
)
def get_claude_login(session_id: str, admin: AdminDep, broker: LoginBrokerDep) -> LoginSessionOut:
    del admin
    try:
        return _session_out(broker.state(session_id))
    except LoginError as exc:
        raise _login_error(exc) from None


@router.post(
    _LOGIN_PATH + "/{session_id}/code",
    response_model=LoginSessionOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Deliver the code Anthropic showed; the helper exchanges it and stores the token",
)
def submit_claude_login_code(
    session_id: str, body: LoginCodeIn, admin: AdminDep, broker: LoginBrokerDep
) -> LoginSessionOut:
    del admin
    try:
        return _session_out(broker.submit_code(session_id, body.code))
    except LoginError as exc:
        raise _login_error(exc) from None


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
    admin: AdminDep, secrets: SecretsDep, limiter: VerifyLimiterDep, settings: SettingsDep
) -> LoginCheckOut:
    """Run the builder's login probe with the stored token (429 inside the rate window)."""
    del admin
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
    return LoginCheckOut(**check.to_dict())


__all__ = ["router"]
