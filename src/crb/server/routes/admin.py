"""``/users`` and ``/settings`` — admin only.

Lockout protection: the last active admin can neither be demoted nor deactivated,
so a deployment can never reach a state where nobody can administer it.
Settings are served through :meth:`Settings.redacted_dict` only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from crb.core.routing import POLICY_VERSION
from crb.core.version import APPARATUS_VERSION
from crb.observability.probes import probe_builders
from crb.server.auth import AdminDep, count_active_admins, create_local_user, validate_role
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
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


__all__ = ["router"]
