"""``create_app()`` — the FastAPI application factory.

Responsibilities (and nothing else — domain routes live in :mod:`crb.server.routes`):

* **Lifespan**: open the database, create tables, prove the append-only triggers are
  live (:func:`crb.store.ledger.assert_append_only`), seed the bootstrap admin when the
  users table is empty.
* **Middleware** (outermost first): CORS (only when origins are configured) → request id
  → access log + HTTP metrics → security headers → session-bound CSRF → domain-error
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

Navigation
----------
What it is:   The FastAPI application factory — ``create_app`` and the pure-ASGI middleware
              stack, error envelope and router seam it assembles.
What it does: Opens the store in the lifespan and refuses to start unless the append-only
              triggers are provably live; seeds the bootstrap admin once; wraps every
              request in request-id, access-log + metrics, security headers, CSRF and
              domain-error middleware; converts every failure into the one error envelope;
              mounts each ``crb.server.routes.*`` router under ``/api/v1`` and the built UI
              (if present) at ``/``.
How:          ``create_app`` builds the app and middleware (last added = outermost), registers
              the exception handlers, then ``register_routers`` walks the routes package;
              ``_lifespan_factory`` does the database work at startup, not import time.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md (the 409 mapping),
              docs/adr/0005-fail-closed-docker-sandbox.md (the 503 mapping)
Works with:   src/crb/server/deps.py (``ApiError`` and the envelope this renders),
              src/crb/server/auth.py (cookies, CSRF check, bootstrap admin, OIDC client),
              src/crb/server/settings.py (everything the factory reads), src/crb/store/db.py
              + src/crb/store/ledger.py (``init_db`` and ``assert_append_only`` at boot),
              src/crb/server/routes/__init__.py (the mounting contract),
              src/crb/server/http_metrics.py (the middleware's metrics sink), docs/API.md
              (the envelope and the reserved codes)
Tested by:    tests/test_server_app.py, tests/test_server_auth.py, tests/test_server_system.py
Touch when:   never for a new repository; adding a middleware means deciding its position in
              the stack (comment the order) and keeping it pure ASGI so SSE is not buffered;
              mapping a new engine exception to a reserved code means adding its NAME to the
              frozensets here and the code to docs/API.md.
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
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crb.core.redact import redact
from crb.core.version import __version__
from crb.observability import build_stamp
from crb.server import http_metrics
from crb.server.auth import (
    CSRF_HEADER,
    AuthlibOidcClient,
    LoginRateLimiter,
    OidcClient,
    bootstrap_admin_if_empty,
    csrf_valid,
    session_signature_valid,
    session_token_of,
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
        # A caller's id is honoured only when well-formed: a free-text header would
        # otherwise flow straight into every log line and the error envelope.
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
            # In ``finally`` so an exception that escapes the app is still one logged
            # request (status stays 500 unless a response start was seen).
            self._record(scope, status["code"], time.perf_counter() - started)

    def _record(self, scope: Scope, status: int, duration_s: float) -> None:
        """One log line + one metrics observation; never raises (see the except below)."""
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
                    # The dev-only Swagger page loads its assets from a CDN; the strict
                    # CSP would blank it, so it is the one path allowed to skip the header.
                    if name == "Content-Security-Policy" and path in self.skip_csp_paths:
                        continue
                    headers.setdefault(name, value)
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
                if path.startswith(API_PREFIX):
                    # API responses carry evidence and principals; a shared cache must
                    # never serve one caller's response to another.
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_secured)


class CsrfMiddleware:
    """Session-bound CSRF check on unsafe methods for requests riding a session cookie.

    The ``X-CSRF-Token`` header must be the session's own token — ``HMAC(secret, uid, cv)``
    recomputed from the signed session cookie (:func:`crb.server.auth.csrf_valid`) — not
    merely equal to a cookie, which anyone able to plant cookies could choose. A request
    with no session cookie, or with one this deployment never signed, has no ambient
    credential to abuse, so it is left to the auth dependency (401). Login is exempt: there
    is no session before it.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        exempt_paths: Iterable[str] = CSRF_EXEMPT_PATHS,
    ) -> None:
        self.app = app
        self.settings = settings
        self.exempt = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS:
            path = str(scope.get("path", ""))
            if path not in self.exempt:
                headers = Headers(scope=scope)
                # the SAME reader as the auth dependency: a stricter parser that gave up
                # on one malformed neighbour cookie would skip this check while the
                # request still authenticated
                session = session_token_of(HTTPConnection(scope), self.settings)
                if (
                    session
                    and session_signature_valid(self.settings, session)
                    and not csrf_valid(self.settings, session, headers.get(CSRF_HEADER.lower()))
                ):
                    response = JSONResponse(
                        status_code=403,
                        content=error_body(
                            "csrf_failed",
                            f"{CSRF_HEADER} header must carry this session's CSRF token "
                            "(GET /auth/csrf)",
                        ),
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _mro_names(exc: BaseException) -> set[str]:
    """Class names up the exception's MRO — matched by NAME so this module never imports
    the core or store types it maps (the layering rule, ADR-0008)."""
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
                # Headers already went out (an SSE stream, say): a JSON body now would
                # corrupt the response, so let the server close the connection instead.
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
    """A ``JSONResponse`` carrying the error envelope."""
    return JSONResponse(status_code=status, content=error_body(code, message, detail))


async def _handle_api_error(_: Request, exc: Exception) -> Any:
    """``ApiError`` → its own status, code and headers (e.g. ``Retry-After``)."""
    assert isinstance(exc, ApiError)
    return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=exc.headers)


async def _handle_http_exception(_: Request, exc: Exception) -> Any:
    """Starlette / FastAPI ``HTTPException`` (404, 405, auth-less 401 …) → the envelope,
    with the status translated to a stable snake_case code."""
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
    """422 with the scrubbed pydantic errors (no echoed input)."""
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
    """The startup / shutdown context: open (or adopt) the engine, prove the triggers,
    seed the admin, mount the UI; dispose the engine only if we opened it."""

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
        # A server whose ledger accepts UPDATE must not come up: the API would then be
        # serving verdicts it cannot vouch for. This is the only startup-time proof.
        assert_append_only(factory)  # raises LedgerIntegrityError → refuse to start
        app.state.engine = engine
        app.state.session_factory = factory
        bootstrap_admin_if_empty(factory, settings)
        # Mounted at startup (not in the factory) so routes a caller adds after
        # create_app() still take precedence over the catch-all SPA mount.
        if not getattr(app.state, "ui_mounted", False):
            app.state.ui_dist = mount_ui(app, settings)
            app.state.ui_mounted = True
        app.state.started_at = time.time()
        # the commit this process runs, captured NOW: a later `git pull` then reads as a
        # disagreement on /health (the `build` probe), never as fresh code
        app.state.source_commit = build_stamp.process_commit()
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
    # An injected client (tests) wins; else a real one only when OIDC is configured.
    if oidc_client is not None:
        app.state.oidc_client = oidc_client
    elif settings.oidc.enabled:
        app.state.oidc_client = AuthlibOidcClient(settings.oidc)
    else:
        app.state.oidc_client = None

    # Middleware: each add_middleware wraps the previous, so the LAST added is OUTERMOST.
    app.add_middleware(DomainErrorMiddleware)
    app.add_middleware(CsrfMiddleware, settings=settings)
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


class _SpaStaticFiles(StaticFiles):
    """Static files with an ``index.html`` fallback so client-side routes deep-link.

    Mounted LAST and only when the built UI exists. API paths are never reached
    here because the API routers are matched first.
    """

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


def resolve_ui_dist(settings: Settings) -> Path | None:
    """The built UI directory: ``CRB_UI_DIST`` if set, else the dev and container defaults;
    ``None`` when no ``index.html`` is found."""
    candidates = [settings.ui_dist] if settings.ui_dist else ["ui/dist", "/app/ui/dist"]
    for c in candidates:
        p = Path(c)
        if (p / "index.html").is_file():
            return p
    return None


def mount_ui(app: FastAPI, settings: Settings) -> Path | None:
    """Serve the built SPA at ``/`` when present; a no-op (with a log line) otherwise."""
    dist = resolve_ui_dist(settings)
    if dist is None:
        log.info("no built UI found (CRB_UI_DIST unset and ui/dist absent); API only")
        return None
    app.mount("/", _SpaStaticFiles(directory=str(dist), html=True), name="ui")
    log.info("serving UI from %s", dist)
    return dist


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
