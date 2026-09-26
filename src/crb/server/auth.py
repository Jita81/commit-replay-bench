"""Authentication and authorisation primitives.

* **Local accounts** — argon2id hashes (``argon2-cffi``). Verification is constant-time
  by construction, and an unknown username still pays for one verification so the
  response time does not reveal whether the account exists.
* **Sessions** — the ``crb_session`` cookie (``__Host-crb_session`` when cookies are
  secure) is an ``itsdangerous`` signed, timestamped payload ``{uid, iat, cv}``. HttpOnly,
  SameSite=Lax, Secure per settings. Expiry is checked on every request against
  ``session_ttl``. ``cv`` is the :func:`credential_version` the session was issued under —
  a fingerprint of the account's password hash AND its ``session_nonce`` — so a password
  change (which re-salts the hash) and a rotated nonce (:func:`rotate_session_nonce`: on
  logout and on "sign out everywhere") each end every session of that account on its next
  request, without a table of sessions. The nonce is per account, so signing out ends the
  account's sessions on every device. A deactivated account is refused on every request
  while it is inactive; ``active`` is not part of the version, so re-activating within
  ``session_ttl`` restores the sessions issued before the deactivation — sign the account
  out everywhere as well to end them for good.
* **Lifecycle** — :func:`set_password` and :func:`set_user_active` are the one
  implementation the admin routes and the ``crb users`` break-glass CLI share: a password
  is hashed here and never logged; the last active admin can never be deactivated
  (``409 last_admin``); an OIDC account never gains a local password (``409 not_local``).
* **CSRF** — a token bound to the session: ``HMAC(secret, uid, cv)``
  (:func:`csrf_token_for`), served in the non-HttpOnly ``crb_csrf`` cookie
  (``__Host-crb_csrf`` when secure) and required as the ``X-CSRF-Token`` header on every
  unsafe method (the app middleware recomputes it from the signed session cookie). A pair
  planted by someone who can set cookies but not read the secret never passes, and a
  token dies with the session it was minted for.
* **RBAC** — one ascending ladder ``viewer < operator < approver < admin``;
  :func:`require_role` admits the named role and everything above it.
* **OIDC** — authorization-code + PKCE via ``authlib``. The provider round-trips go
  through the :class:`OidcClient` protocol so the app can inject a fake and the tests
  never touch the network. Roles come from ``role_claim``/``groups`` via ``role_map``;
  the default is ``viewer``. Users are upserted by ``(issuer, subject)``. The claims set
  the role on an account's FIRST sign-in only; afterwards the role is the admin's to
  change, unless ``CRB_OIDC__ROLE_FROM_CLAIMS=always`` makes the provider the source of
  truth — then each sign-in whose claims move the role records ``user.role_overridden``.
* **Login rate limit** — 5 failures per minute per ``(username, ip)`` and 20 per minute
  per ``ip``, in memory. It bounds online guessing on one process; production fronts it
  with the proxy's limiter (docs/DEPLOYMENT.md), which sees every replica.

Navigation
----------
What it is:   The authentication and authorisation primitives every route depends on —
              local accounts, signed cookie sessions, CSRF tokens, the role ladder, the login
              rate limit, and the OIDC (PKCE) client behind a protocol.
What it does: Verifies passwords in constant time (an unknown user pays for a verification
              too), issues and reads the timestamped session cookie bound to the account's
              credential version (a password change or a rotated session nonce — logout,
              sign out everywhere — ends the account's sessions), derives the CSRF token
              from the session (``HMAC(secret, uid, cv)``),
              admits a caller by role rank, maps IdP claims to a role (``admin_groups`` wins,
              default ``viewer``; applied on first sign-in unless ``role_from_claims`` is
              ``always``), upserts OIDC users by ``(issuer, subject)``, limits failed
              sign-ins per ``(username, ip)`` and per ``ip``, seeds the
              bootstrap admin only while the users table is empty, and owns the account
              lifecycle primitives (``set_password``, ``set_user_active`` with the last-admin
              guard) the admin routes and the ``crb users`` CLI share. Never logs or returns
              a password or token.
How:          argon2id via ``argon2-cffi``; ``itsdangerous`` timed serialisers with a salt
              per cookie kind (``__Host-`` names when secure); ``credential_version`` = a
              SHA-256 prefix of the stored hash and the ``users.session_nonce``;
              ``require_role`` is a dependency factory over ``ROLE_RANK``;
              ``AuthlibOidcClient`` does discovery → PKCE authorization URL → code exchange
              → ID-token validation against the JWKS → optional userinfo merge.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/routes/auth.py (login / logout / OIDC start + callback — the
              HTTP surface over these primitives), src/crb/server/routes/admin.py (the
              ``/users`` lifecycle routes over ``set_password`` / ``set_user_active``),
              src/crb/cli/commands/users.py (the break-glass CLI over the same primitives),
              src/crb/server/settings.py (``ROLE_RANK``, ``OidcSettings``, ``session_ttl``,
              the secret key), src/crb/server/app.py (``CsrfMiddleware`` uses
              ``csrf_matches``; the lifespan seeds the admin), src/crb/store/models.py
              (``User``), src/crb/server/deps.py (``ApiError``, ``Principal``),
              docs/SECURITY.md#34-authentication-and-authorisation--crbserverauth
Tested by:    tests/test_server_auth.py, tests/test_server_admin_users.py,
              tests/test_cli_users.py, tests/test_server_app.py
Touch when:   never for a new repository; adding a role means extending ``ROLE_LADDER`` in
              settings.py, adding a ``*Dep`` alias here, and updating docs/API.md and
              docs/SECURITY.md; changing cookie or session semantics needs a note in
              docs/SECURITY.md and the UI's auth flow (ui/src/api/client.ts).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
import uuid
import warnings
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import HTTPConnection

from crb.server.deps import ApiError, DbDep, Principal, SettingsDep
from crb.server.settings import (
    MIN_PASSWORD_LENGTH,
    ROLE_LADDER,
    ROLE_RANK,
    OidcSettings,
    Settings,
)
from crb.store.models import User

with warnings.catch_warnings():
    # authlib 1.8 deprecates its jose/httpx modules in favour of joserfc/httpx2 while
    # still shipping them; the replacement is not yet a declared dependency of crb.
    # authlib.deprecate installs an "always" filter on import, so it must load BEFORE
    # our "ignore" filter for ours to take precedence (catch_warnings restores both).
    import authlib.deprecate  # noqa: F401

    warnings.simplefilter("ignore", DeprecationWarning)
    from authlib.integrations.httpx_client import OAuth2Client
    from authlib.jose import JsonWebKey, jwt
    from authlib.oidc.core import CodeIDToken

log = logging.getLogger("crb.server.auth")

SESSION_COOKIE = "crb_session"
CSRF_COOKIE = "crb_csrf"
#: The prefix a secure deployment gives its session and CSRF cookies: the browser accepts a
#: ``__Host-`` cookie only when it is Secure, has ``Path=/`` and no ``Domain``, so a sibling
#: host or a plain-http response can never plant or shadow one.
HOST_PREFIX = "__Host-"
CSRF_HEADER = "X-CSRF-Token"
OIDC_COOKIE = "crb_oidc"
OIDC_STATE_TTL_S = 600
LOCAL_ISSUER = "local"

_SESSION_SALT = "crb.session.v1"
_CSRF_KEY_LABEL = b"crb.csrf.v2"
_OIDC_SALT = "crb.oidc.v1"
_GITHUB_SETUP_SALT = "crb.github-setup.v1"
#: The cookie that binds an install link's ``state`` to the browser that fetched it: the
#: state carries a nonce, the cookie carries the same nonce, and the setup callback needs
#: both — a state alone (a link forwarded, a stale tab in another session) writes nothing.
GITHUB_SETUP_COOKIE = "crb_github_setup"
#: How long an install link's ``state`` stays valid: long enough to install the app on an
#: organisation, short enough that a leaked link is not a standing capability.
GITHUB_SETUP_STATE_TTL_S = 30 * 60

USERNAME_MAX = 64
_USERNAME_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._@-")

# --- passwords -------------------------------------------------------------------

hasher = PasswordHasher()
#: A hash of a random secret; verified against on unknown usernames so that a
#: missing account costs the same time as a wrong password.
_DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))


def hash_password(password: str) -> str:
    """argon2id hash of ``password``; refuses one shorter than ``MIN_PASSWORD_LENGTH``."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time as far as argon2 allows; never raises."""
    try:
        return bool(hasher.verify(password_hash or _DUMMY_HASH, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_username(username: str) -> str:
    """The stripped username, or 422 (``validation_error``) for a bad length or character."""
    name = username.strip()
    if not (2 <= len(name) <= USERNAME_MAX) or any(c not in _USERNAME_ALLOWED for c in name):
        raise ApiError(
            422,
            "validation_error",
            "username must be 2-64 characters from [A-Za-z0-9._@-]",
            detail={"field": "username"},
        )
    return name


def validate_role(role: str) -> str:
    """``role`` unchanged, or 422 listing the allowed ladder."""
    if role not in ROLE_RANK:
        raise ApiError(
            422,
            "validation_error",
            f"unknown role {role!r}",
            detail={"field": "role", "allowed": list(ROLE_LADDER)},
        )
    return role


# --- users -----------------------------------------------------------------------


def local_subject(username: str) -> str:
    """The ``users.subject`` of a local account (namespaced so it cannot collide with an
    OIDC ``sub``)."""
    return f"local:{username}"


def new_user_id() -> str:
    """A fresh 32-hex user id."""
    return uuid.uuid4().hex


def find_local_user(db: Session, username: str) -> User | None:
    """The local account for ``username``, or ``None``."""
    return db.execute(
        select(User).where(User.issuer == LOCAL_ISSUER, User.subject == local_subject(username))
    ).scalar_one_or_none()


def create_local_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str = "viewer",
    display_name: str = "",
    email: str = "",
) -> User:
    """Create a local account; the caller commits. 409 if the username is taken."""
    name = validate_username(username)
    validate_role(role)
    try:
        pw_hash = hash_password(password)
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc), detail={"field": "password"}) from exc
    if find_local_user(db, name) is not None:
        raise ApiError(409, "user_exists", f"user {name!r} already exists")
    user = User(
        id=new_user_id(),
        subject=local_subject(name),
        issuer=LOCAL_ISSUER,
        email=email,
        display_name=display_name or name,
        role=role,
        password_hash=pw_hash,
    )
    db.add(user)
    db.flush()
    return user


def authenticate_local(db: Session, username: str, password: str) -> User | None:
    """Return the user on success, else ``None``; timing does not depend on existence."""
    user = find_local_user(db, username)
    stored = user.password_hash if user is not None else ""
    # Always verify — against the dummy hash when there is no user — so the cost is the
    # same on both paths; the checks are combined AFTER, not short-circuited before.
    ok = verify_password(stored, password)
    if user is None or not ok or not user.active:
        return None
    # Transparent upgrade when argon2's parameters have moved on since the hash was made.
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(password)
    return user


def count_users(db: Session) -> int:
    """All accounts (active or not) — the bootstrap gate counts every row."""
    return int(db.execute(select(func.count(User.id))).scalar_one())


def lock_users_table(db: Session) -> None:
    """Serialise a read-then-write on ``users`` for the rest of this transaction: SQLite
    takes its write lock now (``BEGIN IMMEDIATE``), Postgres a transaction-scoped advisory
    lock (id 7336 — one id per table, see ``crb.store.jobs``). Other dialects: no-op."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        # pysqlite defers BEGIN until the first write, so this is safe after the auth
        # lookup's SELECTs; if a write already happened the write lock is already held.
        try:
            db.execute(text("BEGIN IMMEDIATE"))
        except OperationalError as exc:
            if "within a transaction" not in str(exc):
                raise
    elif dialect == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(7336)"))


def count_active_admins(db: Session) -> int:
    """Active admins — the admin routes refuse to demote or disable the last one."""
    return int(
        db.execute(
            select(func.count(User.id)).where(User.role == "admin", User.active.is_(True))
        ).scalar_one()
    )


def credential_version(user: User) -> str:
    """The version stamp a session is bound to: a 16-hex prefix of the SHA-256 of the
    stored password hash and the account's ``session_nonce``. argon2 salts every hash, so
    setting a password — even to the same value — changes it; :func:`rotate_session_nonce`
    changes it too (logout, "sign out everywhere"), which is how an OIDC account (no hash)
    has its sessions ended. Every session issued under the old version stops verifying.
    An account whose nonce is still empty (every row the 0009 migration added the column
    to) keeps the version it had before the column existed, so the upgrade signs nobody
    out."""
    nonce = user.session_nonce or ""
    material = user.password_hash or ""
    if nonce:
        material = f"{material}\x00{nonce}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def rotate_session_nonce(user: User) -> None:
    """Give ``user`` a fresh ``session_nonce`` (128 random bits); the caller commits. Every
    session the account holds — on every device — ends on its next request."""
    user.session_nonce = secrets.token_hex(16)


def is_local_account(user: User) -> bool:
    """A local (password) account, as opposed to one an identity provider owns."""
    return user.issuer == LOCAL_ISSUER


def set_password(user: User, password: str) -> None:
    """Replace ``user``'s password with a fresh argon2id hash; the caller commits.

    409 ``not_local`` for an OIDC account (its credential is the provider's, and a hash on
    it could never be used — ``find_local_user`` looks only under the local issuer);
    422 ``validation_error`` below ``MIN_PASSWORD_LENGTH``. The clear text is never stored,
    logged or returned; the new hash re-salts, so :func:`credential_version` moves and the
    account's existing sessions end (see :func:`current_user`).
    """
    if not is_local_account(user):
        raise ApiError(
            409,
            "not_local",
            "this account signs in through the organisation's identity provider; "
            "it has no local password",
        )
    try:
        user.password_hash = hash_password(password)
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc), detail={"field": "password"}) from exc


def set_user_active(db: Session, user: User, active: bool) -> bool:
    """Activate or deactivate ``user``; the caller commits. Returns whether the flag changed.

    Deactivating the last active admin is refused with 409 ``last_admin`` — a deployment
    can never reach a state nobody can administer. The lock is taken FIRST and ``user`` is
    re-read under it (:func:`lock_users_table`, then ``Session.refresh``): the caller loaded
    ``user`` before the lock, and a role change committed in between (promote this account,
    demote the other admin) would otherwise let a guard that trusted the stale snapshot
    deactivate the last admin (verifier, 2026-09-21 — the ``set_role`` route already locked
    before its read; this is the same ordering). Read, count and update are one serialised
    transaction, so two concurrent deactivations cannot both see "2 admins". Idempotent:
    setting the flag it already holds changes nothing and returns ``False``.
    """
    lock_users_table(db)
    db.refresh(user)
    if user.active == active:
        return False
    if not active and user.role == "admin" and count_active_admins(db) <= 1:
        raise ApiError(
            409,
            "last_admin",
            "refusing to deactivate the last active admin",
            detail={"allowed": list(ROLE_LADDER)},
        )
    user.active = active
    return True


def bootstrap_admin_if_empty(factory: sessionmaker[Session], settings: Settings) -> bool:
    """Seed the configured admin ONLY when the users table is empty. Returns True if seeded.

    The notice is deliberately loud: it is the only moment a password from the
    environment becomes an account, and the operator should rotate it afterwards.
    """
    cfg = settings.bootstrap_admin
    if not cfg.configured or cfg.password is None:
        return False
    with factory() as db:
        if count_users(db) > 0:
            return False
        create_local_user(
            db,
            username=cfg.username,
            password=cfg.password.get_secret_value(),
            role="admin",
            display_name=cfg.username,
        )
        db.commit()
    log.warning(
        "bootstrap admin %r created from CRB_BOOTSTRAP_ADMIN__* (one-time; users table was empty). "
        "Rotate the password and unset the variables.",
        cfg.username,
    )
    return True


# --- cookies + sessions ----------------------------------------------------------


def _serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    # One key, a salt per cookie kind: a session token can never be replayed as an OIDC
    # state cookie or vice versa.
    return URLSafeTimedSerializer(settings.secret_key_value, salt=salt)


def issue_session(settings: Settings, user_id: str, credential_version: str = "") -> str:
    """A signed, timestamped session token for ``user_id`` (nothing stored server-side),
    bound to ``credential_version`` — the :func:`credential_version` of the account at
    issue; :func:`current_user` refuses the token once the account's version has moved."""
    return str(
        _serializer(settings, _SESSION_SALT).dumps(
            {"uid": user_id, "iat": int(time.time()), "cv": credential_version}
        )
    )


def read_session_claims(settings: Settings, token: str) -> tuple[str, str]:
    """``(user id, credential version)`` from a session token, or :class:`ApiError` 401.
    A token issued before versions were stamped carries ``""`` and never matches a real
    account's version — one re-login after the upgrade, never a session that outlives a
    password change."""
    try:
        data = _serializer(settings, _SESSION_SALT).loads(token, max_age=settings.session_ttl)
    except SignatureExpired as exc:
        raise ApiError(401, "session_expired", "session expired; log in again") from exc
    except BadSignature as exc:
        raise ApiError(401, "unauthenticated", "invalid session") from exc
    uid = data.get("uid") if isinstance(data, dict) else None
    if not isinstance(uid, str) or not uid:
        raise ApiError(401, "unauthenticated", "invalid session")
    cv = data.get("cv", "")
    return uid, cv if isinstance(cv, str) else ""


def read_session(settings: Settings, token: str) -> str:
    """Return the user id or raise :class:`ApiError` 401."""
    return read_session_claims(settings, token)[0]


def session_cookie_name(settings: Settings) -> str:
    """``__Host-crb_session`` when cookies are secure, else ``crb_session`` (a plain-http
    development deployment cannot set a ``__Host-`` cookie)."""
    return HOST_PREFIX + SESSION_COOKIE if settings.resolved_cookie_secure else SESSION_COOKIE


def session_token_of(conn: HTTPConnection, settings: Settings) -> str:
    """The session cookie's value as EVERY reader sees it, or ``""``.

    The CSRF middleware, :func:`current_user` and logout all read the session through this,
    over Starlette's lenient cookie parser. Two parsers disagreeing is a bypass: a strict
    one that gives up on a header with one malformed cookie (a space, JSON, a consent date)
    would skip the CSRF check while the lenient one still authenticated the request."""
    return conn.cookies.get(session_cookie_name(settings), "")


def csrf_cookie_name(settings: Settings) -> str:
    """``__Host-crb_csrf`` when cookies are secure, else ``crb_csrf``."""
    return HOST_PREFIX + CSRF_COOKIE if settings.resolved_cookie_secure else CSRF_COOKIE


def _set_cookie(
    response: Response,
    settings: Settings,
    name: str,
    value: str,
    *,
    max_age: int,
    httponly: bool,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=settings.resolved_cookie_secure,
        httponly=httponly,
        samesite="lax",
    )


def set_session_cookie(
    response: Response, settings: Settings, user_id: str, credential_version: str = ""
) -> None:
    """Issue a session and set it as the HttpOnly ``crb_session`` cookie. Callers that
    hold the ``User`` pass :func:`credential_version` so the session ends with the
    password it was issued under."""
    _set_cookie(
        response,
        settings,
        session_cookie_name(settings),
        issue_session(settings, user_id, credential_version),
        max_age=settings.session_ttl,
        httponly=True,
    )


def csrf_token_for(settings: Settings, user_id: str, credential_version: str) -> str:
    """The CSRF token of one session: ``HMAC-SHA256(secret, label | uid | cv)``, URL-safe.
    Deterministic, so the middleware recomputes it from the signed session cookie with no
    server-side state; bound to the account AND its credential version, so it cannot be
    chosen by whoever plants cookies and it dies with the session (a rotated nonce or a new
    password moves ``cv``)."""
    key = hmac.new(settings.secret_key_value.encode(), _CSRF_KEY_LABEL, hashlib.sha256).digest()
    mac = hmac.new(key, f"{user_id}\x00{credential_version}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def set_csrf_cookie(
    response: Response, settings: Settings, user_id: str, credential_version: str
) -> str:
    """Set the readable (non-HttpOnly) CSRF cookie the UI echoes as a header — the
    :func:`csrf_token_for` of the session being issued — and return the token."""
    token = csrf_token_for(settings, user_id, credential_version)
    _set_cookie(
        response,
        settings,
        csrf_cookie_name(settings),
        token,
        max_age=settings.session_ttl,
        httponly=False,
    )
    return token


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Logout: expire the session, CSRF and OIDC cookies with the same attributes they were
    set with."""
    for name in (session_cookie_name(settings), csrf_cookie_name(settings), OIDC_COOKIE):
        response.delete_cookie(
            name, path="/", secure=settings.resolved_cookie_secure, samesite="lax"
        )


def csrf_valid(settings: Settings, session_token: str, header_token: str | None) -> bool:
    """Whether ``header_token`` is the CSRF token of the session ``session_token`` carries.

    The session's signature is checked but not its age: an expired session is the auth
    dependency's to refuse (401 ``session_expired``, which the UI turns into a sign-in),
    not a CSRF failure. Never raises; constant-time compare."""
    if not header_token:
        return False
    try:
        data = _serializer(settings, _SESSION_SALT).loads(session_token)
    except BadSignature:
        return False
    if not isinstance(data, dict):
        return False
    uid, cv = data.get("uid"), data.get("cv", "")
    if not isinstance(uid, str) or not uid or not isinstance(cv, str):
        return False
    expected = csrf_token_for(settings, uid, cv)
    return hmac.compare_digest(expected.encode(), header_token.encode())


def session_signature_valid(settings: Settings, session_token: str) -> bool:
    """Whether ``session_token`` was signed by this deployment (age not checked). A cookie
    that fails this carries no credential, so a request riding only it has nothing a
    forged cross-site request could abuse."""
    try:
        _serializer(settings, _SESSION_SALT).loads(session_token)
    except BadSignature:
        return False
    return True


# --- dependencies ----------------------------------------------------------------


def current_user(request: Request, settings: SettingsDep, db: DbDep) -> Principal:
    """The logged-in principal, or 401 (``unauthenticated`` / ``session_expired``)."""
    token = session_token_of(request, settings)
    if not token:
        raise ApiError(401, "unauthenticated", "login required")
    uid, cv = read_session_claims(settings, token)
    user = db.get(User, uid)
    if user is None or not user.active:
        raise ApiError(401, "unauthenticated", "account unknown or disabled")
    if not hmac.compare_digest(cv.encode(), credential_version(user).encode()):
        # The password changed or the nonce was rotated (logout, sign out everywhere)
        # after this session was issued, or the token predates version stamping: the
        # session is over, whoever holds the cookie.
        raise ApiError(401, "session_revoked", "session no longer valid; log in again")
    request.state.user_id = user.id
    return Principal.model_validate(user)


CurrentUser = Annotated[Principal, Depends(current_user)]


def require_role(role: str) -> Callable[[Principal], Principal]:
    """Dependency factory: the caller must hold ``role`` or a higher rung of the ladder."""
    needed = ROLE_RANK[validate_role(role)]

    def _dep(user: CurrentUser) -> Principal:
        if ROLE_RANK.get(user.role, -1) < needed:
            raise ApiError(
                403,
                "forbidden",
                f"role {role!r} required",
                detail={"required": role, "actual": user.role},
            )
        return user

    _dep.__name__ = f"require_{role}"
    return _dep


def require_role_now(user: Principal, role: str) -> None:
    """The same check as :func:`require_role`, applied inside a handler — for a route whose
    read is open to viewers but whose *side effect* (a query flag that recomputes and
    writes) needs a higher rung."""
    if ROLE_RANK.get(user.role, -1) < ROLE_RANK[validate_role(role)]:
        raise ApiError(
            403,
            "forbidden",
            f"role {role!r} required",
            detail={"required": role, "actual": user.role},
        )


ViewerDep = Annotated[Principal, Depends(require_role("viewer"))]
OperatorDep = Annotated[Principal, Depends(require_role("operator"))]
ApproverDep = Annotated[Principal, Depends(require_role("approver"))]
AdminDep = Annotated[Principal, Depends(require_role("admin"))]


# --- login rate limit ------------------------------------------------------------


#: Failed sign-ins per minute from one address, whatever the usernames: bounds a spray of
#: guesses across many accounts, which the per-``(username, ip)`` bucket cannot see.
LOGIN_IP_LIMIT = 20


class LoginRateLimiter:
    """Sliding-window failure counters: one bucket per ``(username, ip)`` (``limit``) and
    one per ``ip`` (``ip_limit``); a caller is limited when either is full. A success
    clears only its own ``(username, ip)`` bucket — the address's bucket drains with the
    window, so an attacker holding one valid account cannot reset it. Thread-safe, in
    memory, per process: production fronts it with the proxy's limiter."""

    def __init__(
        self,
        limit: int = 5,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        ip_limit: int = LOGIN_IP_LIMIT,
    ) -> None:
        self.limit = limit
        self.ip_limit = ip_limit
        self.window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._ops = 0

    @staticmethod
    def _ip_key(ip: str) -> tuple[str, str]:
        # "" is never a username (validate_username refuses it), so ("", ip) is the
        # address's own bucket and cannot collide with an account's
        return ("", ip)

    def _prune(self, key: tuple[str, str], now: float) -> deque[float]:
        q = self._failures.setdefault(key, deque())
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
        return q

    def _sweep(self, now: float) -> None:
        self._ops += 1
        if self._ops % 1000 == 0:
            for key in list(self._failures):
                self._prune(key, now)

    def retry_after(self, username: str, ip: str) -> float | None:
        """Seconds until the caller may try again, or ``None`` when not limited."""
        now = self._clock()
        with self._lock:
            self._sweep(now)
            waits = []
            for key, limit in (((username, ip), self.limit), (self._ip_key(ip), self.ip_limit)):
                q = self._prune(key, now)
                if len(q) >= limit:
                    waits.append(max(0.0, self.window_s - (now - q[-limit])))
            return max(waits) if waits else None

    def record_failure(self, username: str, ip: str) -> None:
        """Count one failed login for the ``(username, ip)`` key and for the address."""
        now = self._clock()
        with self._lock:
            self._failures.setdefault((username, ip), deque()).append(now)
            self._failures.setdefault(self._ip_key(ip), deque()).append(now)

    def reset(self, username: str, ip: str) -> None:
        """Forget the key's failures (a successful login)."""
        with self._lock:
            self._failures.pop((username, ip), None)


# --- OIDC ------------------------------------------------------------------------


class OidcClient(Protocol):
    """The two provider round-trips. Implemented by :class:`AuthlibOidcClient`; faked in tests."""

    def authorization_url(
        self, *, state: str, nonce: str, code_verifier: str, redirect_uri: str
    ) -> str: ...

    def exchange(
        self, *, code: str, code_verifier: str, nonce: str, redirect_uri: str
    ) -> Mapping[str, Any]:
        """Exchange the code; return validated ID-token claims (+ userinfo if fetched)."""
        ...


@dataclass(frozen=True)
class OidcState:
    """What the ``crb_oidc`` cookie carries between ``/start`` and ``/callback``."""

    state: str
    nonce: str
    code_verifier: str
    next_path: str = "/"

    def to_dict(self) -> dict[str, str]:
        """The cookie payload (short keys: the cookie is size-limited)."""
        return {
            "state": self.state,
            "nonce": self.nonce,
            "cv": self.code_verifier,
            "next": self.next_path,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OidcState:
        """Inverse of :meth:`to_dict`; ``KeyError`` on a payload missing a field."""
        return cls(
            state=str(d["state"]),
            nonce=str(d["nonce"]),
            code_verifier=str(d["cv"]),
            next_path=str(d.get("next", "/")),
        )

    @classmethod
    def fresh(cls, next_path: str = "/") -> OidcState:
        """New random state, nonce and PKCE verifier; ``next_path`` sanitised."""
        return cls(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(24),
            code_verifier=secrets.token_urlsafe(64),
            next_path=safe_next_path(next_path),
        )


def safe_next_path(candidate: str | None) -> str:
    """Only same-origin absolute paths survive; anything else becomes ``/`` (no open redirect)."""
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    if "\\" in candidate or "\n" in candidate or "\r" in candidate:
        return "/"
    return candidate


def set_oidc_cookie(response: Response, settings: Settings, st: OidcState) -> None:
    """Carry the pending login's state between ``/start`` and ``/callback`` (10 minutes)."""
    token = str(_serializer(settings, _OIDC_SALT).dumps(st.to_dict()))
    _set_cookie(response, settings, OIDC_COOKIE, token, max_age=OIDC_STATE_TTL_S, httponly=True)


def read_oidc_cookie(settings: Settings, token: str | None) -> OidcState:
    """The pending login's state, or 400 with a code saying what is wrong with the cookie."""
    if not token:
        raise ApiError(400, "oidc_state_missing", "no pending OIDC login (cookie missing)")
    try:
        data = _serializer(settings, _OIDC_SALT).loads(token, max_age=OIDC_STATE_TTL_S)
    except SignatureExpired as exc:
        raise ApiError(400, "oidc_state_expired", "OIDC login took too long; retry") from exc
    except BadSignature as exc:
        raise ApiError(400, "oidc_state_invalid", "OIDC state cookie is invalid") from exc
    try:
        return OidcState.from_dict(data)
    except (KeyError, TypeError) as exc:
        raise ApiError(400, "oidc_state_invalid", "OIDC state cookie is malformed") from exc


def issue_github_setup_state(settings: Settings, user_id: str, nonce: str) -> str:
    """The ``state`` an install link carries so the GitHub App's setup callback can prove
    the operator who receives it is the one who started the install, in the browser that
    started it (CWE-352): signed, bound to the principal AND to ``nonce`` — the value the
    :data:`GITHUB_SETUP_COOKIE` set on the same response carries — thirty minutes. GitHub
    passes the state through untouched."""
    return str(_serializer(settings, _GITHUB_SETUP_SALT).dumps({"sub": user_id, "nonce": nonce}))


def new_github_setup_nonce() -> str:
    """A fresh nonce for one install link (128 bits, URL-safe)."""
    return secrets.token_urlsafe(16)


def set_github_setup_cookie(response: Response, settings: Settings, nonce: str) -> None:
    """Bind the install link to this browser for the state's lifetime (httponly)."""
    _set_cookie(
        response,
        settings,
        GITHUB_SETUP_COOKIE,
        nonce,
        max_age=GITHUB_SETUP_STATE_TTL_S,
        httponly=True,
    )


def clear_github_setup_cookie(response: Response, settings: Settings) -> None:
    """Consume the nonce: a state is good for one callback in the browser that minted it."""
    response.delete_cookie(
        GITHUB_SETUP_COOKIE, path="/", secure=settings.resolved_cookie_secure, samesite="lax"
    )


def verify_github_setup_state(
    settings: Settings, state: str | None, user_id: str, nonce: str | None
) -> bool:
    """True only for a state this deployment signed, for this principal, carrying the
    nonce this browser's cookie holds, inside the TTL. Never raises: a callback without a
    valid state is not an error, it is one that may not write (the operator records the
    installation through the CSRF-protected sync)."""
    if not state or not nonce:
        return False
    try:
        data = _serializer(settings, _GITHUB_SETUP_SALT).loads(
            state, max_age=GITHUB_SETUP_STATE_TTL_S
        )
    except (SignatureExpired, BadSignature):
        return False
    if not isinstance(data, dict) or data.get("sub") != user_id:
        return False
    expected = str(data.get("nonce", ""))
    return bool(expected) and hmac.compare_digest(expected.encode(), nonce.encode())


def _claim_values(claims: Mapping[str, Any], name: str) -> list[str]:
    """A claim as a list of strings whether the IdP sent a string, a list or nothing."""
    raw = claims.get(name)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list | tuple | set):
        return [str(v) for v in raw]
    return [str(raw)]


def map_role(claims: Mapping[str, Any], oidc: OidcSettings) -> str:
    """Highest role granted by ``role_claim``/``groups`` via ``role_map``; ``admin_groups`` wins."""
    values = _claim_values(claims, oidc.role_claim)
    if oidc.role_claim != "groups":
        values += _claim_values(claims, "groups")
    if any(v in oidc.admin_groups for v in values):
        return "admin"
    best = "viewer"
    for v in values:
        mapped = oidc.role_map.get(v)
        if mapped in ROLE_RANK and ROLE_RANK[mapped] > ROLE_RANK[best]:
            best = mapped
    return best


def upsert_oidc_user(
    db: Session,
    *,
    issuer: str,
    claims: Mapping[str, Any],
    role: str,
    role_from_claims: str = "first_login",
) -> User:
    """Find-or-create by ``(issuer, subject)``; refresh the profile fields from the IdP.

    ``role`` (the claims' mapping) is set on a NEW account. On an existing one it replaces
    the stored role only when ``role_from_claims == "always"`` — otherwise an admin's
    change would be silently reverted at the account's next sign-in. The caller records
    ``user.role_overridden`` when it compares the role before and after."""
    subject = str(claims.get("sub") or "")
    if not subject:
        raise ApiError(502, "oidc_exchange_failed", "ID token carries no subject")
    email = str(claims.get("email") or claims.get("preferred_username") or "")
    display = str(claims.get("name") or claims.get("preferred_username") or email or subject)
    user = db.execute(
        select(User).where(User.issuer == issuer, User.subject == subject)
    ).scalar_one_or_none()
    if user is None:
        user = User(
            id=new_user_id(),
            subject=subject,
            issuer=issuer,
            email=email,
            display_name=display,
            role=role,
        )
        db.add(user)
    else:
        user.email = email or user.email
        user.display_name = display or user.display_name
        if role_from_claims == "always":
            user.role = role
    db.flush()
    return user


@dataclass
class AuthlibOidcClient:
    """The production :class:`OidcClient`: discovery, PKCE authorization URL, code exchange,
    ID-token validation against the issuer's JWKS, optional userinfo enrichment."""

    oidc: OidcSettings
    timeout_s: float = 10.0
    _discovery: dict[str, Any] = field(default_factory=dict, repr=False)

    def discovery(self) -> dict[str, Any]:
        """The issuer's ``.well-known/openid-configuration`` (fetched once, then cached)."""
        if self._discovery:
            return self._discovery
        url = self.oidc.issuer.rstrip("/") + "/.well-known/openid-configuration"
        r = httpx.get(url, timeout=self.timeout_s)
        r.raise_for_status()
        doc = r.json()
        if not isinstance(doc, dict):
            raise ApiError(502, "oidc_discovery_failed", "discovery document is not an object")
        # Every endpoint we will later call must be TLS: a discovery document that points
        # the token exchange or the JWKS fetch at http:// is refused, not followed.
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            value = str(doc.get(key) or "")
            if not value.lower().startswith("https://"):
                raise ApiError(
                    502, "oidc_discovery_failed", f"discovery {key} is not an https:// URL"
                )
        self._discovery = doc
        return doc

    def _client(self, redirect_uri: str) -> Any:
        """An authlib ``OAuth2Client`` for one round-trip (PKCE S256 always on)."""
        secret = self.oidc.client_secret.get_secret_value() if self.oidc.client_secret else None
        return OAuth2Client(
            client_id=self.oidc.client_id,
            client_secret=secret,
            scope=self.oidc.scopes,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
            timeout=self.timeout_s,
        )

    def authorization_url(
        self, *, state: str, nonce: str, code_verifier: str, redirect_uri: str
    ) -> str:
        """Where to send the browser (``code_verifier`` becomes the S256 challenge)."""
        endpoint = str(self.discovery()["authorization_endpoint"])
        url, _ = self._client(redirect_uri).create_authorization_url(
            endpoint, state=state, code_verifier=code_verifier, nonce=nonce
        )
        return str(url)

    def exchange(
        self, *, code: str, code_verifier: str, nonce: str, redirect_uri: str
    ) -> Mapping[str, Any]:
        doc = self.discovery()
        client = self._client(redirect_uri)
        token = client.fetch_token(
            str(doc["token_endpoint"]), code=code, code_verifier=code_verifier
        )
        id_token = token.get("id_token")
        if not id_token:
            raise ApiError(502, "oidc_exchange_failed", "token response carries no id_token")
        # The ID token is verified against the issuer's published keys, with issuer,
        # audience and nonce all required — never trusted because it arrived over TLS.
        jwks_resp = httpx.get(str(doc["jwks_uri"]), timeout=self.timeout_s)
        jwks_resp.raise_for_status()
        key_set = JsonWebKey.import_key_set(jwks_resp.json())
        claims = jwt.decode(
            id_token,
            key_set,
            claims_cls=CodeIDToken,
            claims_options={
                "iss": {"essential": True, "values": [str(doc.get("issuer", self.oidc.issuer))]},
                "aud": {"essential": True, "values": [self.oidc.client_id]},
            },
            claims_params={"nonce": nonce},
        )
        claims.validate()
        merged: dict[str, Any] = dict(claims)
        userinfo = doc.get("userinfo_endpoint")
        access = token.get("access_token")
        if userinfo and access:
            r = httpx.get(
                str(userinfo),
                headers={"Authorization": f"Bearer {access}"},
                timeout=self.timeout_s,
            )
            if r.status_code == 200 and isinstance(r.json(), dict):
                # setdefault: userinfo may ADD claims (groups, email) but never override
                # what the signed ID token said.
                for k, v in r.json().items():
                    merged.setdefault(k, v)
        return merged


__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "GITHUB_SETUP_COOKIE",
    "GITHUB_SETUP_STATE_TTL_S",
    "HOST_PREFIX",
    "LOCAL_ISSUER",
    "LOGIN_IP_LIMIT",
    "OIDC_COOKIE",
    "SESSION_COOKIE",
    "AdminDep",
    "ApproverDep",
    "AuthlibOidcClient",
    "CurrentUser",
    "LoginRateLimiter",
    "OidcClient",
    "OidcState",
    "OperatorDep",
    "ViewerDep",
    "authenticate_local",
    "bootstrap_admin_if_empty",
    "clear_auth_cookies",
    "clear_github_setup_cookie",
    "count_active_admins",
    "count_users",
    "create_local_user",
    "credential_version",
    "csrf_cookie_name",
    "csrf_token_for",
    "csrf_valid",
    "current_user",
    "find_local_user",
    "hash_password",
    "is_local_account",
    "issue_github_setup_state",
    "issue_session",
    "map_role",
    "new_github_setup_nonce",
    "read_oidc_cookie",
    "read_session",
    "read_session_claims",
    "require_role",
    "rotate_session_nonce",
    "safe_next_path",
    "session_cookie_name",
    "session_signature_valid",
    "session_token_of",
    "set_csrf_cookie",
    "set_github_setup_cookie",
    "set_oidc_cookie",
    "set_password",
    "set_session_cookie",
    "set_user_active",
    "upsert_oidc_user",
    "validate_role",
    "validate_username",
    "verify_github_setup_state",
    "verify_password",
]
