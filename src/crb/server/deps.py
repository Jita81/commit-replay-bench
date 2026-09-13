"""Request-scoped dependencies and the shared response models.

Everything a route needs comes off ``request.app.state`` (populated by the
lifespan in :mod:`crb.server.app`): settings, the session factory, the OIDC
client. Routes never import module-level singletons, so two apps with two
databases can live in one process (which is exactly what the tests do).

:class:`ApiError` is the one exception routes raise for a non-success outcome;
the app converts it (and every other error) into the API.md envelope::

    {"error": {"code": "<snake_case>", "message": "...", "detail": {...}}}
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from crb.server.settings import Settings


class ApiError(Exception):
    """A non-success outcome with an explicit HTTP status and a stable snake_case code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail: dict[str, Any] = dict(detail or {})
        self.headers: dict[str, str] = dict(headers or {})

    def body(self) -> dict[str, Any]:
        return error_body(self.code, self.message, self.detail)


def error_body(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": dict(detail or {})}}


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """The only shape a non-2xx/3xx response ever has."""

    error: ErrorBody


class Principal(BaseModel):
    """The authenticated caller as ``/auth/me`` reports it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    email: str
    role: str
    issuer: str


# --- app-state accessors ---------------------------------------------------------


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def get_db(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> Iterator[Session]:
    """One ORM session per request. Routes commit explicitly; errors roll back."""
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]
DbDep = Annotated[Session, Depends(get_db)]


def request_id(request: Request) -> str:
    """The request id the middleware assigned (echoed as ``X-Request-ID``)."""
    return str(getattr(request.state, "request_id", ""))


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's address: the socket peer, or — only when that peer is a trusted
    proxy — the nearest untrusted hop in ``X-Forwarded-For`` (walked right to left)."""
    direct = request.client.host if request.client else ""
    trusted = set(settings.trusted_proxies)
    if direct and direct in trusted:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        for hop in reversed([h for h in hops if h]):
            if hop not in trusted:
                return hop
    return direct


__all__ = [
    "ApiError",
    "DbDep",
    "ErrorBody",
    "ErrorEnvelope",
    "Principal",
    "SessionFactoryDep",
    "SettingsDep",
    "client_ip",
    "error_body",
    "get_db",
    "get_session_factory",
    "get_settings",
    "request_id",
]
