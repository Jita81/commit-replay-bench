"""``/users``, ``/settings`` and ``/settings/secrets`` — admin only.

Lockout protection: the last active admin can neither be demoted nor deactivated,
so a deployment can never reach a state where nobody can administer it.
Settings are served through :meth:`Settings.redacted_dict` only.

Secrets (``/settings/secrets/*``) go through :mod:`crb.server.secrets`: a value is
accepted on ``PUT`` and written owner-only to disk; every response — including the
``PUT`` itself — is a :class:`SecretStatusOut` (presence, ≤4-char fingerprint,
who/when), never the value. ``PUT``/``DELETE``/``verify`` are admin-only; the status
list is readable by any signed-in role (it is non-secret by construction) — a **viewer**
sees presence only (``{name, present}``; the fingerprint, who set it and when are the
operating roles' business, F25). ``verify``
runs the builder's own login probe and is rate-limited to one per 10 s so it cannot
be used to burn quota.

Navigation
----------
What it is:   The admin route module — ``/users``, ``/settings`` and ``/settings/secrets``.
What it does: Lists and creates local accounts, changes roles without ever orphaning the
              last active admin (409 ``last_admin``), serves the redacted settings view
              with the builders' configured flags, and stores / removes / verifies the
              Claude Code login token while answering only statuses (never a value).
How:          Every handler takes ``AdminDep`` (the secrets status list takes ``ViewerDep``
              because a status is non-secret, and projects a viewer's copy down to presence);
              the secrets handlers delegate to
              src/crb/server/secrets.py and translate its exceptions into 422 / 409 / 429.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/auth.py (``create_local_user``, ``count_active_admins``),
              src/crb/server/secrets.py (``SecretsFile``, the verify limiter),
              src/crb/server/settings.py (``redacted_dict``), src/crb/observability/probes.py
              (``probe_builders`` for the configured flags), ui/src/api/types.ts (the
              ``Settings`` shape the UI renders), docs/API.md#admin
Tested by:    tests/test_server_routes_admin_secrets.py, tests/test_server_auth.py,
              tests/test_server_system.py
Touch when:   never for a new repository; adding a secret means a route pair here plus a
              ``SecretSpec`` in src/crb/server/secrets.py; adding a settings field means
              ``redacted_dict`` first, then the UI type.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from crb.builders.claude_code import CLI_TOKEN_SECRET, VERIFY_STATUSES
from crb.core.routing import POLICY_VERSION
from crb.core.secrets_file import SecretsInsecure
from crb.core.version import APPARATUS_VERSION
from crb.observability.probes import probe_builders
from crb.server.auth import (
    LOCAL_ISSUER,
    AdminDep,
    ViewerDep,
    count_active_admins,
    create_local_user,
    lock_users_table,
    validate_role,
)
from crb.server.claude_login import LoginError
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.secrets import (
    CLAUDE_CODE_TOKEN_MAX_LEN,
    LoginBrokerDep,
    SecretsDep,
    VerifyLimiterDep,
)
from crb.server.settings import MIN_PASSWORD_LENGTH, ROLE_LADDER
from crb.store.models import User

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
    out.username = (
        user.subject.removeprefix("local:") if user.issuer == LOCAL_ISSUER else user.subject
    )
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


# --- secrets (request/response models live here on purpose: schemas.py is shared) ------


class SecretStatusOut(BaseModel):
    """What the API says about a stored secret. ``fingerprint`` is at most the last
    four characters of the value (empty when absent); nothing else of the value."""

    name: str
    present: bool
    fingerprint: str = Field(default="", max_length=4)
    set_at: str = ""
    set_by: str = ""


class SecretsStatusList(BaseModel):
    """``GET /settings/secrets`` body."""

    items: list[SecretStatusOut]
    #: Where the files live on the API host (admins only — so they can find / mount /
    #: rotate); ``""`` for every other role.
    secrets_dir: str = ""


class ClaudeCodeTokenIn(BaseModel):
    """The pasted ``claude setup-token`` value. Validated for shape in the route."""

    token: str = Field(min_length=1, max_length=CLAUDE_CODE_TOKEN_MAX_LEN)


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
    del admin
    user = create_local_user(
        db,
        username=body.username,
        password=body.password,
        role=body.role,
        display_name=body.display_name,
        email=body.email,
    )
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
    del admin
    validate_role(body.role)
    # Count and update in one serialised transaction: two concurrent demotions of the two
    # remaining admins each saw "2 admins" and together left none (CodeRabbit on PR #4,
    # 2026-09-15). SQLite takes the write lock up front; Postgres an advisory lock.
    lock_users_table(db)
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", f"no user {user_id!r}")
    new_active = user.active if body.active is None else body.active
    loses_admin = user.role == "admin" and user.active and (body.role != "admin" or not new_active)
    if loses_admin and count_active_admins(db) <= 1:
        raise ApiError(
            409,
            "last_admin",
            "refusing to demote or deactivate the last active admin",
            detail={"allowed": list(ROLE_LADDER)},
        )
    user.role = body.role
    user.active = new_active
    db.commit()
    return _user_out(user)


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
    an ``auth: cli`` run can authenticate. A viewer gets presence only — ``{name,
    present}`` with the other fields empty — and only admins learn the directory path."""
    items = [_status_out(s) for s in secrets.statuses()]
    if user.role == "viewer":
        items = [SecretStatusOut(name=i.name, present=i.present) for i in items]
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
