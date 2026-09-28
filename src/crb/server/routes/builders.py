"""``/builders/logins`` and ``/builders/{builder}/login/verify`` — the login a run would use.

Pilot D1: a run was queued on a Claude Code login that answered HTTP 401 while every screen
read the login as present. These two routes put the login's STATE where a person can act on
it: ``GET /builders/logins`` reads each builder login a run could use — the deployment's
default auth mode and every other mode with a present credential or a recorded verification
(Q1's review) — as ``verified`` / ``unverified`` / ``invalid`` with its age, from the recorded
verifications, never by calling a model; a viewer is served presence and state only (F25).
``POST /builders/{builder}/login/verify?auth=`` verifies one mode once (one no-tool Haiku turn
through the builder's own environment, at most once every 10 s across the deployment) and
records the outcome, which the next submit, the worker's claim and the ``/health``
``builders`` probe then read. The Settings screen's Claude Code login card calls both; the refusal a
submit meets (``builder_login_invalid``) sends the person there.

Navigation
----------
What it is:   The route module for the builder logins' verification state and the Verify that
              refreshes it.
What it does: Lists every login a run could use (each builder with a verify, per auth mode):
              its state and age, and for operators and above its outcome, source label and at
              most four characters of the token (a viewer gets presence and state only);
              verifies one mode on request (operator and above), rate-limited deployment-wide,
              and records it for the submit gate and the health probe. Never returns a token.
How:          ``login_readings`` (one indexed event read per mode) for the list, cut to
              ``PUBLIC_LOGIN_FIELDS`` for a viewer;
              the verify acquires the shared ``VerifyRateLimiter``, then ``run_verification``
              (``trigger: settings``) and answers the state it leaves.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/server/builder_login.py (the cache, the state, the verifiers),
              src/crb/server/secrets.py (``VerifyLimiterDep`` — one limiter with the stored-token
              verify), ui/src/screens/Settings/ClaudeCodeLoginCard.tsx (the card that calls
              both), docs/API.md (the rows)
Tested by:    tests/test_builder_login.py
Touch when:   never for a new repository; a builder gains a verify (it appears here through
              ``LOGIN_VERIFIERS``).
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from crb.server.auth import OperatorDep, ViewerDep
from crb.server.builder_login import (
    LOGIN_STATES,
    LOGIN_VERIFIERS,
    TRIGGER_SETTINGS,
    login_readings,
    login_state,
    run_verification,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.secrets import VerifyLimiterDep, secrets_dir_for

router = APIRouter(tags=["builders"])
_ERR = {"model": ErrorEnvelope}


class LoginPresenceOut(BaseModel):
    """A viewer's copy of a login: presence and state only
    (:data:`crb.server.builder_login.PUBLIC_LOGIN_FIELDS`) — a distinct model, not a blanked
    :class:`LoginStateOut`, so the wire shape carries no fingerprint, source or detail (F25)."""

    builder: str
    auth: str
    state: str = Field(description="one of " + " | ".join(LOGIN_STATES))
    status: str = ""
    present: bool = False
    default: bool = False
    checked_at: str | None = None
    age_s: float | None = None
    ttl_s: int
    reason: str = ""


class LoginStateOut(BaseModel):
    """:meth:`crb.server.builder_login.LoginState.to_dict` — never a token."""

    builder: str
    auth: str
    state: str = Field(description="one of " + " | ".join(LOGIN_STATES))
    status: str = ""
    present: bool = False
    default: bool = False
    detail: str = ""
    source: str = ""
    fingerprint: str = Field(default="", max_length=4)
    cli_version: str = ""
    checked_at: str | None = None
    age_s: float | None = None
    ttl_s: int
    trigger: str = ""
    reason: str = ""


class LoginStateList(BaseModel):
    items: list[LoginStateOut] | list[LoginPresenceOut]


@router.get(
    "/builders/logins",
    response_model=LoginStateList,
    responses={401: _ERR},
    summary="Each builder login a run could use: verified, unverified or invalid, with its age",
)
def list_builder_logins(viewer: ViewerDep, db: DbDep, settings: SettingsDep) -> LoginStateList:
    """Read from the recorded verifications only: listing never calls a model. A viewer gets
    presence and state only."""
    readings = login_readings(
        db, ttl_s=settings.builder.login_ttl_s, secrets_dir=secrets_dir_for(settings)
    )
    items: list[LoginStateOut] | list[LoginPresenceOut]
    if viewer.role == "viewer":
        items = [LoginPresenceOut(**r.to_dict(full=False)) for r in readings]
    else:
        items = [LoginStateOut(**r.to_dict(full=True)) for r in readings]
    return LoginStateList(items=items)


@router.post(
    "/builders/{builder}/login/verify",
    response_model=LoginStateOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR, 429: _ERR},
    summary="Verify a builder's login once (one no-tool Haiku turn) and record the outcome",
)
def verify_builder_login(
    builder: str,
    *,
    operator: OperatorDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    limiter: VerifyLimiterDep,
    auth: str = Query(
        default="", max_length=16, description="the auth mode; default: the deployment's"
    ),
) -> LoginStateOut:
    """404 for a builder with no verify; 422 for an auth mode it does not have; 429 inside the
    deployment-wide rate window (shared with the stored-token verify)."""
    verifier = LOGIN_VERIFIERS.get(builder)
    if verifier is None:
        raise ApiError(404, "not_found", f"builder {builder!r} exposes no login to verify")
    mode = auth.strip() or verifier.default_auth()
    if mode not in verifier.modes:
        raise ApiError(
            422,
            "validation_error",
            f"auth must be one of {', '.join(verifier.modes)}, not {mode!r}",
        )
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
    run_verification(
        factory,
        builder,
        mode,
        binary=settings.builder.claude_binary,
        trigger=TRIGGER_SETTINGS,
        actor=operator.id,
    )
    with factory() as s:
        state = login_state(s, builder, mode, ttl_s=settings.builder.login_ttl_s)
    present = not verifier.missing(mode, secrets_dir=secrets_dir_for(settings))
    return LoginStateOut(
        **state.to_dict(), present=present, default=mode == verifier.default_auth()
    )


__all__ = ["router"]
