"""``/users``, ``/settings`` and ``/settings/secrets`` — admin only.

Lockout protection: the last active admin can neither be demoted nor deactivated,
so a deployment can never reach a state where nobody can administer it.
Settings are served through :meth:`Settings.redacted_dict` only.

Secrets (``/settings/secrets/*``) go through :mod:`crb.server.secrets`: a value is
accepted on ``PUT`` and written owner-only to disk; every response — including the
``PUT`` itself — is a :class:`SecretStatusOut` (presence, ≤4-char fingerprint,
who/when), never the value. ``PUT``/``DELETE``/``verify`` are admin-only; the status
list is readable by any signed-in role (it is non-secret by construction). ``verify``
runs the builder's own login probe and is rate-limited to one per 10 s so it cannot
be used to burn quota.
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
    AdminDep,
    ViewerDep,
    count_active_admins,
    create_local_user,
    validate_role,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.secrets import (
    CLAUDE_CODE_TOKEN_MAX_LEN,
    SecretsDep,
    VerifyLimiterDep,
)
from crb.server.settings import MIN_PASSWORD_LENGTH, ROLE_LADDER
from crb.store.models import User

router = APIRouter(tags=["admin"])
_ERR = {"model": ErrorEnvelope}


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject: str
    issuer: str
    email: str
    display_name: str
    role: str
    active: bool
    created: str
    last_login: str


class UserList(BaseModel):
    items: list[UserOut]
    total: int


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    role: str = "viewer"
    display_name: str = Field(default="", max_length=256)
    email: str = Field(default="", max_length=256)


class RoleChange(BaseModel):
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
    items: list[SecretStatusOut]
    #: Where the files live on the API host (admins only — so they can find / mount /
    #: rotate); ``""`` for every other role.
    secrets_dir: str = ""


class ClaudeCodeTokenIn(BaseModel):
    """The pasted ``claude setup-token`` value. Validated for shape in the route."""

    token: str = Field(min_length=1, max_length=CLAUDE_CODE_TOKEN_MAX_LEN)


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
    del admin
    users = list(db.execute(select(User).order_by(User.created, User.id)).scalars())
    return UserList(items=[UserOut.model_validate(u) for u in users], total=len(users))


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Create a local account",
)
def create_user(body: CreateUserRequest, admin: AdminDep, db: DbDep) -> UserOut:
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
    return UserOut.model_validate(user)


@router.put(
    "/users/{user_id}/role",
    response_model=UserOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Change a user's role (and optionally active flag); never orphans the last admin",
)
def set_role(user_id: str, body: RoleChange, admin: AdminDep, db: DbDep) -> UserOut:
    del admin
    validate_role(body.role)
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
    return UserOut.model_validate(user)


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
    an ``auth: cli`` run can authenticate. Only admins learn the directory path."""
    return SecretsStatusList(
        items=[_status_out(s) for s in secrets.statuses()],
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
    del admin
    try:
        return _status_out(secrets.delete(CLI_TOKEN_SECRET))
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None


@router.post(
    _CLAUDE_TOKEN_PATH + "/verify",
    response_model=LoginCheckOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 429: _ERR},
    summary="Test the stored token: one no-tool Haiku turn through the builder's own environment",
)
def verify_claude_code_token(
    admin: AdminDep, secrets: SecretsDep, limiter: VerifyLimiterDep
) -> LoginCheckOut:
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
        check = secrets.verify(CLI_TOKEN_SECRET)
    except SecretsInsecure as exc:
        raise ApiError(409, "secrets_insecure", str(exc)) from None
    if check is None:
        raise ApiError(404, "not_found", "no Claude Code token is stored — save one first")
    return LoginCheckOut(**check.to_dict())


__all__ = ["router"]
