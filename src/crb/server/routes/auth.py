"""``/auth/*`` — local login, OIDC (authorization code + PKCE), session, CSRF.

Local login is rate limited per ``(username, client ip)`` and per client ip; a failure
never says which half was wrong. Every sign-in, and every refused one, is an audit event.
Logout rotates the account's session nonce, so it ends every session of the account, not
only this browser's cookie. OIDC state, nonce and the PKCE verifier travel in a signed,
short-lived, HttpOnly cookie, so the callback can only complete a login this
browser started. ``next`` is constrained to a same-origin path.

Navigation
----------
What it is:   The ``/auth/*`` route module — local login / logout / me / csrf and the OIDC
              start + callback pair.
What it does: Rate-limits local login per ``(username, ip)`` and per ``ip`` and answers
              one indistinct 401 for any failure; sets the session and the session-bound
              CSRF cookies on success; logout rotates the account's session nonce (every
              session ends); drives the authorization-code + PKCE flow with the state kept
              in a signed short-lived cookie; maps IdP claims to a role on first sign-in
              (every sign-in under ``role_from_claims=always``, recorded as
              ``user.role_overridden``) and upserts the user; refuses a disabled account and
              any ``next`` that is not a same-origin path. Every sign-in writes
              ``user.login`` and every refused local one ``user.login_failed`` (a name that
              is no account: recorded without the name, DL-071); every callback failure
              redirects to ``/login?error=<code>`` from ``OIDC_FAILURE_CODES``.
How:          Thin handlers over src/crb/server/auth.py — ``authenticate_local`` →
              ``_commit_audited`` (the event with its state change; a lost ``seq`` race is
              retried) → cookies; ``OidcState.fresh`` → provider URL → cookie; callback:
              cookie → ``_complete_oidc`` (``exchange`` → ``map_role`` →
              ``upsert_oidc_user`` → event) → cookies → redirect, or ``_back_to_login``.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/auth.py (every primitive used here), src/crb/server/routes/admin.py
              (``record_user_event`` — the account trail), src/crb/server/routes/runs.py
              (``append_system_event`` for a refusal with no account), src/crb/server/app.py
              (``/auth/login`` is CSRF-exempt; the limiter lives on ``app.state``),
              src/crb/server/settings.py (``OidcSettings``, ``local_auth_enabled``),
              ui/src/api/client.ts (the UI's login and CSRF echo),
              ui/src/screens/Login/LoginPage.tsx (``OIDC_FAILURE_REASONS``), docs/API.md#auth
Tested by:    tests/test_server_auth.py
Touch when:   never for a new repository; when the IdP's claim layout changes (that is
              ``CRB_OIDC__ROLE_CLAIM`` / ``ROLE_MAP`` configuration, not code); adding a
              login method needs docs/SECURITY.md#34-authentication-and-authorisation--crbserverauth
              updated and a test in tests/test_server_auth.py.
"""

from __future__ import annotations

import datetime as _dt
import hmac
import logging
import math
from collections.abc import Callable
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crb.core.redact import redact
from crb.server.auth import (
    OIDC_COOKIE,
    CurrentUser,
    LoginRateLimiter,
    OidcClient,
    OidcState,
    authenticate_local,
    clear_auth_cookies,
    credential_version,
    find_local_user,
    map_role,
    read_oidc_cookie,
    read_session_claims,
    rotate_session_nonce,
    safe_next_path,
    session_token_of,
    set_csrf_cookie,
    set_oidc_cookie,
    set_session_cookie,
    upsert_oidc_user,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, Principal, SettingsDep, client_ip
from crb.server.routes.admin import record_user_event
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.settings import Settings
from crb.store.models import User

log = logging.getLogger("crb.server.auth")

router = APIRouter(tags=["auth"])

_ERR = {"model": ErrorEnvelope}
OIDC_CALLBACK_PATH = "/auth/oidc/callback"


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


#: The actor of an attempt made before anyone is signed in.
ANONYMOUS_ACTOR = "anonymous"

#: The codes an OIDC failure may carry back to ``/login?error=``. Anything else becomes
#: ``oidc_failed``: the URL never carries the provider's own words or an unknown code.
OIDC_FAILURE_CODES = frozenset(
    {
        "oidc_provider_error",
        "oidc_state_missing",
        "oidc_state_expired",
        "oidc_state_invalid",
        "oidc_state_mismatch",
        "oidc_exchange_failed",
        "oidc_discovery_failed",
        "account_disabled",
    }
)

#: Attempts at one audited commit before a trace-``seq`` conflict is allowed to surface.
_AUDIT_ATTEMPTS = 3


def _commit_audited(db: Session, write: Callable[[], None]) -> None:
    """Apply ``write`` (a state change and its ``user.*`` event) and commit them together.

    Two sign-ins to one account can read the same last ``seq`` on its trace; the loser's
    insert then breaks ``uq_events_trace_seq``. That is a lost race, not a refused sign-in,
    so the transaction is rolled back and ``write`` runs again on fresh rows (DL-071).
    """
    for attempt in range(_AUDIT_ATTEMPTS):
        write()
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            if attempt == _AUDIT_ATTEMPTS - 1:
                raise


def _record_failed_login(db: Session, username: str) -> None:
    """``user.login_failed`` for one refused local sign-in (DL-071).

    On the account's own trail when the name is a local account (its History shows who
    tried); otherwise one event with NO name on a shared trace — a person who typed their
    password into the username box must not have it stored, and writing on both paths keeps
    the response time from saying whether the account exists."""
    known = find_local_user(db, username) if username else None
    if known is not None:
        record_user_event(
            db,
            action="user.login_failed",
            actor=ANONYMOUS_ACTOR,
            target=known,
            method="local",
            reason="invalid_credentials" if known.active else "account_disabled",
        )
        return
    append_system_event(
        db,
        trace_id=system_trace_id("users", "unknown"),
        action="user.login_failed",
        actor=ANONYMOUS_ACTOR,
        payload={"method": "local", "reason": "unknown_account"},
    )


class LoginRequest(BaseModel):
    """``POST /auth/login`` body. Bounds only; the real checks are in ``authenticate_local``."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class CsrfToken(BaseModel):
    """``GET /auth/csrf`` body: the token the UI must echo as ``X-CSRF-Token``."""

    token: str


@router.post(
    "/auth/login",
    response_model=Principal,
    responses={401: _ERR, 403: _ERR, 429: _ERR},
    summary="Log in with a local account; sets the session and CSRF cookies",
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
) -> Principal:
    if not settings.local_auth_enabled:
        raise ApiError(403, "local_auth_disabled", "local login is disabled; use OIDC")
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = client_ip(request, settings)
    retry = limiter.retry_after(body.username, ip)
    if retry is not None:
        raise ApiError(
            429,
            "rate_limited",
            "too many failed logins; try again later",
            detail={"retry_after_s": math.ceil(retry)},
            headers={"Retry-After": str(math.ceil(retry))},
        )
    user = authenticate_local(db, body.username, body.password)
    if user is None:
        # One message for every failure: an attacker must not learn which half was wrong.
        limiter.record_failure(body.username, ip)
        log.info("login failed", extra={"username": body.username, "client": ip})
        _commit_audited(db, lambda: _record_failed_login(db, body.username))
        raise ApiError(401, "invalid_credentials", "username or password is incorrect")
    limiter.reset(body.username, ip)
    uid = user.id

    def _signed_in() -> None:
        account = db.get(User, uid)
        if account is None:  # deleted between the check and the write
            raise ApiError(401, "invalid_credentials", "username or password is incorrect")
        account.last_login = _now()
        record_user_event(db, action="user.login", actor=uid, target=account, method="local")

    _commit_audited(db, _signed_in)
    user = db.get(User, uid) or user
    request.state.user_id = user.id
    cv = credential_version(user)
    set_session_cookie(response, settings, user.id, cv)
    set_csrf_cookie(response, settings, user.id, cv)
    return Principal.model_validate(user)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the account's sessions on every device and clear the cookies (idempotent)",
)
def logout(request: Request, settings: SettingsDep, db: DbDep) -> Response:
    """Clearing the cookie alone would leave a copied token valid until it expires, so a
    CURRENT session's logout rotates the account's session nonce: every session the account
    holds, here and on any other device, ends on its next request. A stale, forged or
    absent cookie rotates nothing (it cannot be used to sign somebody else out) and still
    gets the cookies cleared."""
    token = session_token_of(request, settings)
    if token:
        try:
            uid, cv = read_session_claims(settings, token)
        except ApiError:
            uid, cv = "", ""
        user = db.get(User, uid) if uid else None
        if user is not None and hmac.compare_digest(cv.encode(), credential_version(user).encode()):
            rotate_session_nonce(user)
            db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response, settings)
    return response


@router.get("/auth/me", response_model=Principal, responses={401: _ERR})
def me(user: CurrentUser) -> Principal:
    return user


@router.get(
    "/auth/csrf",
    response_model=CsrfToken,
    responses={401: _ERR},
    summary="Return (and if needed mint) the CSRF token for this session",
)
def csrf(user: CurrentUser, response: Response, settings: SettingsDep, db: DbDep) -> CsrfToken:
    """The session's own token (``HMAC(secret, uid, cv)``), re-set as the cookie."""
    account = db.get(User, user.id)
    if account is None:  # deleted between the auth dependency and here
        raise ApiError(401, "unauthenticated", "account unknown or disabled")
    return CsrfToken(
        token=set_csrf_cookie(response, settings, account.id, credential_version(account))
    )


# --- OIDC --------------------------------------------------------------------------


def _stored_role(db: Session, issuer: str, claims: dict[str, Any]) -> str | None:
    """The role an existing OIDC account holds before this sign-in, or ``None`` for a new
    one (the subject is checked again by ``upsert_oidc_user``)."""
    subject = str(claims.get("sub") or "")
    if not subject:
        return None
    user = db.execute(
        select(User).where(User.issuer == issuer, User.subject == subject)
    ).scalar_one_or_none()
    return None if user is None else str(user.role)


def _oidc_client(request: Request) -> OidcClient:
    """The app's OIDC client, or 404 when OIDC is not configured for this deployment."""
    client: OidcClient | None = request.app.state.oidc_client
    if client is None:
        raise ApiError(404, "oidc_not_configured", "OIDC login is not configured")
    return client


def _redirect_uri(request: Request, settings: Settings) -> str:
    """The callback URL registered with the IdP: the configured one, else derived from
    this request (behind a proxy that means ``CRB_TRUSTED_PROXIES`` must be set)."""
    if settings.oidc.redirect_url:
        return settings.oidc.redirect_url
    root = str(request.scope.get("root_path", "")).rstrip("/")
    return str(request.url.replace(path=f"{root}/api/v1{OIDC_CALLBACK_PATH}", query=""))


@router.get(
    "/auth/oidc/start",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={404: _ERR},
    summary="Begin an OIDC login (PKCE); state lives in a signed cookie",
)
def oidc_start(
    request: Request,
    settings: SettingsDep,
    next: Annotated[str | None, Query(max_length=512)] = None,
) -> Response:
    client = _oidc_client(request)
    st = OidcState.fresh(next or "/")
    url = client.authorization_url(
        state=st.state,
        nonce=st.nonce,
        code_verifier=st.code_verifier,
        redirect_uri=_redirect_uri(request, settings),
    )
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    set_oidc_cookie(response, settings, st)
    return response


@router.get(
    OIDC_CALLBACK_PATH,
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={404: _ERR},
    summary="Complete an OIDC login: redirects to `next`, or to `/login?error=` on a failure",
)
def oidc_callback(
    request: Request,
    settings: SettingsDep,
    db: DbDep,
    *,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
    error_description: Annotated[str | None, Query(max_length=1024)] = None,
) -> Response:
    """Complete the login and redirect to ``next``; any failure after the provider hand-off
    redirects to ``/login?error=<code>`` (and ``&next=``) instead of answering a JSON
    envelope, so the person lands on the form with the reason (G-188). The code is one of
    :data:`OIDC_FAILURE_CODES`; the provider's own text stays in the server log."""
    client = _oidc_client(request)
    next_path = ""
    try:
        pending = read_oidc_cookie(settings, request.cookies.get(OIDC_COOKIE))
        next_path = pending.next_path
        user = _complete_oidc(
            request,
            settings,
            db,
            client,
            pending,
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
    except ApiError as exc:
        db.rollback()
        log.info("oidc sign-in refused", extra={"code": exc.code, "status": exc.status_code})
        return _back_to_login(settings, exc.code, next_path)
    request.state.user_id = user.id
    response = RedirectResponse(pending.next_path, status_code=status.HTTP_302_FOUND)
    cv = credential_version(user)
    set_session_cookie(response, settings, user.id, cv)
    set_csrf_cookie(response, settings, user.id, cv)
    _drop_oidc_cookie(response, settings)
    return response


def _drop_oidc_cookie(response: Response, settings: Settings) -> None:
    """The pending-login cookie is single use, on success and on failure alike."""
    response.delete_cookie(
        OIDC_COOKIE, path="/", secure=settings.resolved_cookie_secure, samesite="lax"
    )


def _back_to_login(settings: Settings, code: str, next_path: str) -> Response:
    """``302`` to ``/login?error=<code>[&next=<path>]`` with the pending cookie dropped."""
    query: dict[str, str] = {"error": code if code in OIDC_FAILURE_CODES else "oidc_failed"}
    if next_path and next_path != "/":
        query["next"] = safe_next_path(next_path)
    response = RedirectResponse(f"/login?{urlencode(query)}", status_code=status.HTTP_302_FOUND)
    _drop_oidc_cookie(response, settings)
    return response


def _complete_oidc(
    request: Request,
    settings: Settings,
    db: Session,
    client: OidcClient,
    pending: OidcState,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    error_description: str | None,
) -> User:
    """The callback's work: provider error → state check → exchange → role → upsert →
    audit. Raises :class:`ApiError` with the failure's code; commits on success."""
    if error:
        log.info(
            "oidc provider refused the login",
            extra={"error": redact(error), "description": redact(error_description or "")},
        )
        raise ApiError(400, "oidc_provider_error", "the identity provider refused the login")
    # The state in the query must be the one THIS browser's cookie carries: that is the
    # CSRF defence of the code flow (a forged callback has no matching cookie).
    if not code or not state or not hmac.compare_digest(state, pending.state):
        raise ApiError(400, "oidc_state_mismatch", "OIDC state does not match this browser")
    try:
        claims: dict[str, Any] = dict(
            client.exchange(
                code=code,
                code_verifier=pending.code_verifier,
                nonce=pending.nonce,
                redirect_uri=_redirect_uri(request, settings),
            )
        )
    except ApiError:
        raise
    except Exception as exc:
        log.warning("oidc exchange failed: %s: %s", type(exc).__name__, redact(str(exc)))
        raise ApiError(502, "oidc_exchange_failed", "could not complete the OIDC login") from exc
    issuer = str(claims.get("iss") or settings.oidc.issuer)
    role = map_role(claims, settings.oidc)
    source = settings.oidc.role_from_claims
    before = _stored_role(db, issuer, claims)
    user = upsert_oidc_user(db, issuer=issuer, claims=claims, role=role, role_from_claims=source)
    if not user.active:
        uid = user.id
        db.rollback()
        account = db.get(User, uid)
        if account is not None:
            _commit_audited(
                db,
                lambda: record_user_event(
                    db,
                    action="user.login_failed",
                    actor=ANONYMOUS_ACTOR,
                    target=account,
                    method="oidc",
                    reason="account_disabled",
                ),
            )
        raise ApiError(403, "account_disabled", "this account is disabled")
    if before is not None and before != user.role:
        # only reachable under ROLE_FROM_CLAIMS=always: the provider replaced a role an
        # admin may have set here, and that is never silent
        record_user_event(
            db,
            action="user.role_overridden",
            actor=user.id,
            target=user,
            from_role=before,
            by="oidc_claims",
            issuer=issuer,
        )
    user.last_login = _now()
    record_user_event(db, action="user.login", actor=user.id, target=user, method="oidc")
    db.commit()
    return user


__all__ = ["router"]
