"""``/auth/*`` — local login, OIDC (authorization code + PKCE), session, CSRF.

Local login is rate limited per ``(username, client ip)`` and per client ip; a failure
never says which half was wrong. Logout rotates the account's session nonce, so it ends
every session of the account, not only this browser's cookie. OIDC state, nonce and the PKCE verifier travel in a signed,
short-lived, HttpOnly cookie, so the callback can only complete a login this
browser started. ``next`` is constrained to a same-origin path.

``POST /auth/dev-autologin`` exists for a development stack only (ADR-0027): with
``CRB_AUTH__DEV_AUTOLOGIN`` naming a local account, a browser on the same machine is signed
in as it without a password. Anything that is not plainly local — a remote peer, a proxy's
forwarding header, another host name, a cross-site request — gets the same 404 as "off".

Navigation
----------
What it is:   The ``/auth/*`` route module — local login / logout / me / csrf, the OIDC
              start + callback pair, and the development-only automatic sign-in.
What it does: Rate-limits local login per ``(username, ip)`` and per ``ip`` and answers
              one indistinct 401 for any failure; sets the session and the session-bound
              CSRF cookies on success; logout rotates the account's session nonce (every
              session ends); drives the authorization-code + PKCE flow with the state kept
              in a signed short-lived cookie; maps IdP claims to a role on first sign-in
              (every sign-in under ``role_from_claims=always``, recorded as
              ``user.role_overridden``) and upserts the user; refuses a disabled account and
              any ``next`` that is not a same-origin path; on a development stack signs a
              local browser in as the configured account (an audit event and a warning each
              time) with exactly the session a password sign-in issues, and answers "off"
              to anything not plainly local.
How:          Thin handlers over src/crb/server/auth.py — ``authenticate_local`` →
              cookies; ``OidcState.fresh`` → provider URL → cookie; callback: cookie →
              ``exchange`` → ``map_role`` → ``upsert_oidc_user`` → cookies → redirect;
              automatic sign-in: setting → ``dev_autologin_refusal`` → ``find_local_user`` →
              ``record_user_event`` → the same cookies as a password sign-in.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0027-dev-autologin-on-loopback.md
Works with:   src/crb/server/auth.py (every primitive used here), src/crb/server/app.py
              (``/auth/login`` is CSRF-exempt; the limiter lives on ``app.state``),
              src/crb/server/settings.py (``OidcSettings``, ``local_auth_enabled``),
              ui/src/api/client.ts (the UI's login and CSRF echo), ui/src/api/hooks.ts
              (``useMe`` asks for an automatic sign-in), src/crb/server/routes/admin.py
              (``record_user_event``), docs/API.md#auth
Tested by:    tests/test_server_auth.py, tests/test_server_dev_autologin.py
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
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
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
    dev_autologin_refusal,
    find_local_user,
    map_role,
    read_oidc_cookie,
    read_session_claims,
    rotate_session_nonce,
    session_token_of,
    set_csrf_cookie,
    set_oidc_cookie,
    set_session_cookie,
    upsert_oidc_user,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, Principal, SettingsDep, client_ip
from crb.server.routes.admin import record_user_event
from crb.server.settings import Settings
from crb.store.models import User

log = logging.getLogger("crb.server.auth")

router = APIRouter(tags=["auth"])

_ERR = {"model": ErrorEnvelope}
OIDC_CALLBACK_PATH = "/auth/oidc/callback"


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


class LoginRequest(BaseModel):
    """``POST /auth/login`` body. Bounds only; the real checks are in ``authenticate_local``."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class CsrfToken(BaseModel):
    """``GET /auth/csrf`` body: the token the UI must echo as ``X-CSRF-Token``."""

    token: str


def _issue_session(
    request: Request, response: Response, settings: Settings, user: User
) -> Principal:
    """Set the session and its CSRF cookie for ``user`` — the ONE place a sign-in (password
    or development automatic) turns into cookies, so both carry the same credential version
    (the session nonce included) and the same session-bound CSRF token."""
    request.state.user_id = user.id
    cv = credential_version(user)
    set_session_cookie(response, settings, user.id, cv)
    set_csrf_cookie(response, settings, user.id, cv)
    return Principal.model_validate(user)


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
        raise ApiError(401, "invalid_credentials", "username or password is incorrect")
    limiter.reset(body.username, ip)
    user.last_login = _now()
    db.commit()
    return _issue_session(request, response, settings, user)


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


# --- automatic sign-in (development stacks only, ADR-0027) --------------------------

#: One answer for "off" and for every request that may not use it, so a request from
#: another machine (or through a proxy) cannot tell a stack with it switched on from one
#: without; the log line carries the real reason.
_AUTOLOGIN_OFF = ("dev_autologin_off", "automatic sign-in is not switched on")


@router.post(
    "/auth/dev-autologin",
    response_model=Principal,
    responses={403: _ERR, 404: _ERR},
    summary="Development stacks only: sign in a browser on this machine without a password",
)
def dev_autologin(
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
) -> Principal:
    """Sign the caller in as ``CRB_AUTH__DEV_AUTOLOGIN``'s account — only when the setting is
    on (the settings refuse it outside ``CRB_ENV=dev`` and on a non-loopback bind) AND
    :func:`dev_autologin_refusal` finds this request local. The cookies come from
    :func:`_issue_session`, the one a password sign-in uses — the credential version with the
    session nonce, the session-bound CSRF token — so the role ladder, sign-out, "sign out
    everywhere" and a password change end it exactly as they do a typed password's session.
    It checks no password, so the login limiter is neither consulted nor reset — not the
    address's bucket, and not the account's own, which a password success clears. Every sign-in
    appends ``auth.dev_autologin`` on the account's trace and logs one warning line."""
    username = settings.auth.dev_autologin
    if not username:
        raise ApiError(404, *_AUTOLOGIN_OFF)
    peer = request.client.host if request.client else ""
    refusal = dev_autologin_refusal(request)
    if refusal:
        log.warning("automatic sign-in refused for %s: %s", peer or "unknown", refusal)
        raise ApiError(404, *_AUTOLOGIN_OFF)
    user = find_local_user(db, username)
    if user is None or not user.active:
        why = (
            f"there is no local account {username!r}"
            if user is None
            else f"the account {username!r} is disabled"
        )
        log.warning(
            "automatic sign-in signed nobody in: %s (CRB_AUTH__DEV_AUTOLOGIN; create or "
            "re-activate the account, or name another)",
            why,
        )
        raise ApiError(
            403,
            "dev_autologin_unavailable",
            "automatic sign-in is on, but its account cannot sign in; the API log says why",
        )
    user.last_login = _now()
    record_user_event(db, action="auth.dev_autologin", actor=user.id, target=user, client=peer)
    db.commit()
    log.warning(
        "automatic sign-in: %r signed in from %s without a password "
        "(CRB_AUTH__DEV_AUTOLOGIN — development only)",
        username,
        peer,
    )
    return _issue_session(request, response, settings, user)


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
    responses={400: _ERR, 404: _ERR, 502: _ERR},
    summary="Complete an OIDC login; establishes the session and redirects to `next`",
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
    client = _oidc_client(request)
    pending = read_oidc_cookie(settings, request.cookies.get(OIDC_COOKIE))
    if error:
        raise ApiError(
            400,
            "oidc_provider_error",
            "the identity provider refused the login",
            detail={"error": redact(error), "description": redact(error_description or "")},
        )
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
    db.commit()
    request.state.user_id = user.id
    response = RedirectResponse(pending.next_path, status_code=status.HTTP_302_FOUND)
    cv = credential_version(user)
    set_session_cookie(response, settings, user.id, cv)
    set_csrf_cookie(response, settings, user.id, cv)
    response.delete_cookie(
        OIDC_COOKIE, path="/", secure=settings.resolved_cookie_secure, samesite="lax"
    )
    return response


__all__ = ["router"]
