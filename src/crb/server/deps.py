"""Request-scoped dependencies and the shared response models.

Everything a route needs comes off ``request.app.state`` (populated by the
lifespan in :mod:`crb.server.app`): settings, the session factory, the OIDC
client. Routes never import module-level singletons, so two apps with two
databases can live in one process (which is exactly what the tests do).

:class:`ApiError` is the one exception routes raise for a non-success outcome;
the app converts it (and every other error) into the API.md envelope::

    {"error": {"code": "<snake_case>", "message": "...", "detail": {...}}}

Navigation
----------
What it is:   The request-scoped dependencies every route module imports, and the shared
              error / principal response models.
What it does: Hands a route its ``Settings``, session factory or per-request ORM session off
              ``request.app.state``; defines ``ApiError`` (status + stable snake_case code +
              detail) as the only way a route reports a non-success; resolves the caller's
              address honouring ``X-Forwarded-For`` only from a trusted proxy.
How:          FastAPI ``Depends`` accessors over ``app.state``; ``get_db`` yields one session
              per request and rolls back on any exception (routes commit explicitly).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/app.py (populates ``app.state`` in the lifespan and converts
              ``ApiError`` into the envelope), src/crb/server/settings.py (``Settings`` and
              ``trusted_proxies``), src/crb/server/auth.py (builds ``current_user`` on these),
              docs/API.md (the error envelope shape and codes)
Tested by:    tests/test_server_app.py, tests/test_server_auth.py
Touch when:   never for a new repository; when a new app-state object must reach routes (add
              an accessor + ``Annotated`` alias here, populate it in the lifespan); adding an
              error code means adding it to docs/API.md too.
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
        """The response body — the envelope of the module docstring."""
        return error_body(self.code, self.message, self.detail)


def error_body(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """The one error shape (docs/API.md); middleware and handlers all build it here."""
    return {"error": {"code": code, "message": message, "detail": dict(detail or {})}}


class ErrorBody(BaseModel):
    """The ``error`` object of the envelope, as the OpenAPI schema documents it."""

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
    """The app's ``Settings`` (set by ``create_app``)."""
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """The app's bound ``sessionmaker`` (set by the lifespan; a caller-supplied one in tests)."""
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
