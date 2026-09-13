"""``create_app()`` — the FastAPI application factory.

Responsibilities (and nothing else — domain routes live in :mod:`crb.server.routes`):

* **Lifespan**: open the database, create tables, prove the append-only triggers are
  live (:func:`crb.store.ledger.assert_append_only`), seed the bootstrap admin when the
  users table is empty.
* **Middleware** (outermost first): CORS (only when origins are configured) → request id
  → access log + HTTP metrics → security headers → CSRF double-submit → domain-error
  envelope. All are pure ASGI so SSE streams (W2-B) pass through unbuffered.
* **Error envelope**: every non-success response is
  ``{"error": {"code", "message", "detail"}}`` (API.md). ``FalseQ1Violation`` /
  ``SignoffRefused`` / ``LedgerIntegrityError`` → ``409 false_q1_refused``;
  ``SandboxUnavailable`` → ``503 sandbox_unavailable``. Those are matched by class
  NAME (walking the MRO) so this module never imports a sibling workstream's types.
* **Router seam**: :func:`register_routers` imports every submodule of
  ``crb.server.routes`` that exposes ``router`` and mounts it under ``/api/v1``.
  A missing package is tolerated; a broken module is not (fail closed at startup).

Invariant: the server never computes a verdict and never rewrites a ledger row.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from http.cookies import CookieError, SimpleCookie
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crb.core.redact import redact
from crb.core.version import __version__
from crb.server import http_metrics
from crb.server.auth import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    AuthlibOidcClient,
    LoginRateLimiter,
    OidcClient,
    bootstrap_admin_if_empty,
    csrf_matches,
)
from crb.server.deps import ApiError, client_ip, error_body
from crb.server.settings import Settings
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.ledger import assert_append_only

log = logging.getLogger("crb.server")
access_log = logging.getLogger("crb.server.access")

API_PREFIX = "/api/v1"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Unsafe routes that cannot carry a CSRF token yet (no session exists before login).
CSRF_EXEMPT_PATHS = frozenset({f"{API_PREFIX}/auth/login"})

#: Exception class names (anywhere in the MRO) mapped to the reserved envelope codes.
FALSE_Q1_EXCEPTIONS = frozenset({"FalseQ1Violation", "SignoffRefused", "LedgerIntegrityError"})
SANDBOX_EXCEPTIONS = frozenset({"SandboxUnavailable"})

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "service_unavailable",
}

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


# --- middleware (pure ASGI) --------------------------------------------------------


class RequestIdMiddleware:
    """Assign (or accept a well-formed) ``X-Request-ID``; echo it on the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get("x-request-id", "")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = rid
            await send(message)

        await self.app(scope, receive, send_with_id)


def route_template(scope: Scope) -> str:
    """The matched route's path template (``/api/v1/users/{user_id}``), or ``unmatched``.

    FastAPI ≥ 0.128 keeps the prefix-resolved path on its include context
    (``scope["fastapi"]["effective_route_context"]``); older releases (and routes
    added straight onto the app) carry it on ``scope["route"]``. Both are tried.
    """
    fastapi_scope = scope.get("fastapi")
    context = (
        fastapi_scope.get("effective_route_context") if isinstance(fastapi_scope, dict) else None
    )
    for candidate in (context, scope.get("route")):
        template = getattr(candidate, "path_format", "") or getattr(candidate, "path", "")
        if template:
            return str(template)
    return "unmatched"


class ObservabilityMiddleware:
    """One JSON access-log line and one metrics observation per request.

    Logs the matched route template and the redacted path — never the query string,
    never a body. Metrics are labelled by the template so ids stay out of Prometheus.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = {"code": 500}

        async def send_tracking(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        finally:
            self._record(scope, status["code"], time.perf_counter() - started)

    def _record(self, scope: Scope, status: int, duration_s: float) -> None:
        method = str(scope.get("method", ""))
        template = route_template(scope)
        state = scope.get("state") or {}
        try:
            http_metrics.observe(method, template, status, duration_s)
            access_log.info(
                "%s %s %d",
                method,
                redact(str(scope.get("path", ""))),
                status,
                extra={
                    "method": method,
                    "path": redact(str(scope.get("path", ""))),
                    "route": template,
                    "status": status,
                    "duration_ms": round(duration_s * 1000, 2),
                    "request_id": str(state.get("request_id", "")),
                    "user_id": str(state.get("user_id", "")),
                    "client": client_ip(Request(scope), self.settings),
                },
            )
        except Exception:  # pragma: no cover — observability must never break a request
            log.exception("access log/metrics failed")


class SecurityHeadersMiddleware:
    """Add the hardening headers unless the route already set one."""

    def __init__(
        self, app: ASGIApp, *, hsts: bool = False, skip_csp_paths: Iterable[str] = ()
    ) -> None:
        self.app = app
        self.hsts = hsts
        self.skip_csp_paths = frozenset(skip_csp_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))

        async def send_secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name == "Content-Security-Policy" and path in self.skip_csp_paths:
                        continue
                    headers.setdefault(name, value)
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
                if path.startswith(API_PREFIX):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_secured)


class CsrfMiddleware:
    """Double-submit check on unsafe methods for requests riding a session cookie.

    A request with no session cookie has no ambient credential to abuse, so it is
    left to the auth dependency (401). Login is exempt: there is no token before it.
    """

    def __init__(self, app: ASGIApp, *, exempt_paths: Iterable[str] = CSRF_EXEMPT_PATHS) -> None:
        self.app = app
        self.exempt = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS:
            path = str(scope.get("path", ""))
            if path not in self.exempt:
                headers = Headers(scope=scope)
                cookies = _parse_cookies(headers.get("cookie", ""))
                if SESSION_COOKIE in cookies and not csrf_matches(
                    cookies.get(CSRF_COOKIE), headers.get(CSRF_HEADER.lower())
                ):
                    response = JSONResponse(
                        status_code=403,
                        content=error_body(
                            "csrf_failed",
                            f"{CSRF_HEADER} header must match the {CSRF_COOKIE} cookie",
                        ),
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _parse_cookies(header: str) -> dict[str, str]:
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(header)
    except CookieError:  # a malformed cookie header is just "no cookies"
        return {}
    return {k: m.value for k, m in jar.items()}


def _mro_names(exc: BaseException) -> set[str]:
    return {klass.__name__ for klass in type(exc).__mro__}


class DomainErrorMiddleware:
    """Map the engine's fail-closed exceptions to their reserved envelope codes by NAME."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = {"yes": False}

        async def send_marking(message: Message) -> None:
            if message["type"] == "http.response.start":
                started["yes"] = True
            await send(message)

        try:
            await self.app(scope, receive, send_marking)
        except Exception as exc:
            names = _mro_names(exc)
            if started["yes"]:
                raise
            if names & FALSE_Q1_EXCEPTIONS:
                status, code = 409, "false_q1_refused"
            elif names & SANDBOX_EXCEPTIONS:
                status, code = 503, "sandbox_unavailable"
            else:
                raise
            log.warning("%s -> %d %s: %s", type(exc).__name__, status, code, redact(str(exc)))
            response = JSONResponse(
                status_code=status,
                content=error_body(code, redact(str(exc)), {"exception": type(exc).__name__}),
            )
            await response(scope, receive, send_marking)


# --- error handlers ----------------------------------------------------------------


def _envelope(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> Any:
    return JSONResponse(status_code=status, content=error_body(code, message, detail))


async def _handle_api_error(_: Request, exc: Exception) -> Any:
    assert isinstance(exc, ApiError)
    return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=exc.headers)


async def _handle_http_exception(_: Request, exc: Exception) -> Any:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
    detail: dict[str, Any] = (
        {} if isinstance(exc.detail, str | type(None)) else {"detail": exc.detail}
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(message), jsonable_encoder(detail)),
        headers=dict(exc.headers or {}),
    )


def _scrub_validation_errors(errors: Iterable[Any]) -> list[dict[str, Any]]:
    """Keep location/type/message; drop ``input`` (it may be a password) and doc URLs."""
    out: list[dict[str, Any]] = []
    for e in errors:
        if isinstance(e, dict):
            out.append({k: v for k, v in e.items() if k in ("loc", "msg", "type")})
    return out


async def _handle_validation(_: Request, exc: Exception) -> Any:
    assert isinstance(exc, RequestValidationError)
    errors = _scrub_validation_errors(jsonable_encoder(exc.errors()))
    return _envelope(422, "validation_error", "request validation failed", {"errors": errors})


async def _handle_unexpected(request: Request, exc: Exception) -> Any:
    """500 envelope. Runs in Starlette's outermost ServerErrorMiddleware — OUTSIDE our
    header middlewares — so the request id and hardening headers are set here by hand."""
    rid = str(getattr(request.state, "request_id", ""))
    log.error(
        "unhandled %s (request_id=%s): %s",
        type(exc).__name__,
        rid,
        redact(str(exc)),
        exc_info=exc,
    )
    headers = {**SECURITY_HEADERS, "Cache-Control": "no-store"}
    if rid:
        headers["X-Request-ID"] = rid
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "internal error", {"request_id": rid}),
        headers=headers,
    )


# --- router seam -------------------------------------------------------------------


def register_routers(app: FastAPI, *, prefix: str = API_PREFIX) -> list[str]:
    """Mount ``router`` from every ``crb.server.routes.*`` submodule under ``prefix``.

    Returns the module names mounted, in the deterministic (sorted) order used.
    Absence of the package is tolerated; an import error inside a module is not.
    """
    try:
        pkg = importlib.import_module("crb.server.routes")
    except ModuleNotFoundError as exc:
        if exc.name == "crb.server.routes":
            log.warning("crb.server.routes not present; no domain routes mounted")
            return []
        raise
    mounted: list[str] = []
    for name in sorted(m.name for m in pkgutil.iter_modules(pkg.__path__)):
        module = importlib.import_module(f"crb.server.routes.{name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            app.include_router(router, prefix=prefix)
            mounted.append(name)
    log.info("routers mounted under %s: %s", prefix, ", ".join(mounted) or "none")
    return mounted


# --- factory -----------------------------------------------------------------------


def _lifespan_factory(
    settings: Settings, session_factory: sessionmaker[Session] | None
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_engine = session_factory is None
        engine: Engine
        if session_factory is None:
            engine = make_engine(settings.resolved_database_url)
            factory = make_session_factory(engine)
        else:
            factory = session_factory
            bound = factory.kw.get("bind")
            if not isinstance(bound, Engine):
                raise RuntimeError("session_factory must be bound to an Engine")
            engine = bound
        init_db(engine)
        assert_append_only(factory)  # raises LedgerIntegrityError → refuse to start
        app.state.engine = engine
        app.state.session_factory = factory
        bootstrap_admin_if_empty(factory, settings)
        app.state.started_at = time.time()
        log.info(
            "crb server ready",
            extra={"version": __version__, "env": settings.env, "db": settings.database_dialect},
        )
        try:
            yield
        finally:
            if owns_engine:
                engine.dispose()

    return lifespan


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    *,
    oidc_client: OidcClient | None = None,
    mount_routes: bool = True,
) -> FastAPI:
    """Build the application.

    ``settings`` defaults to the environment. ``session_factory`` lets a caller (or a
    test) supply its own bound sessionmaker; otherwise the lifespan opens
    ``settings.resolved_database_url``. ``oidc_client`` is the seam for a fake
    provider. ``mount_routes=False`` yields the bare core (middleware + errors) for
    tests that register only their own routes.
    """
    settings = settings or Settings()
    app = FastAPI(
        title="Commit Replay Bench",
        version=__version__,
        lifespan=_lifespan_factory(settings, session_factory),
        docs_url=f"{API_PREFIX}/docs" if settings.is_dev else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.engine = None
    app.state.started_at = 0.0
    app.state.login_limiter = LoginRateLimiter()
    if oidc_client is not None:
        app.state.oidc_client = oidc_client
    elif settings.oidc.enabled:
        app.state.oidc_client = AuthlibOidcClient(settings.oidc)
    else:
        app.state.oidc_client = None

    # Middleware: each add_middleware wraps the previous, so the LAST added is OUTERMOST.
    app.add_middleware(DomainErrorMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.resolved_cookie_secure,
        skip_csp_paths=(f"{API_PREFIX}/docs",) if settings.is_dev else (),
    )
    app.add_middleware(ObservabilityMiddleware, settings=settings)
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", CSRF_HEADER, "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(Exception, _handle_unexpected)

    if mount_routes:
        register_routers(app)
    return app


__all__ = [
    "API_PREFIX",
    "CSRF_EXEMPT_PATHS",
    "FALSE_Q1_EXCEPTIONS",
    "SANDBOX_EXCEPTIONS",
    "SECURITY_HEADERS",
    "CsrfMiddleware",
    "DomainErrorMiddleware",
    "ObservabilityMiddleware",
    "RequestIdMiddleware",
    "SecurityHeadersMiddleware",
    "create_app",
    "register_routers",
    "route_template",
]
