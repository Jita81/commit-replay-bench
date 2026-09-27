"""``/builders/logins`` and ``/builders/{builder}/login/verify`` — the login a run would use.

Pilot D1: a run was queued on a Claude Code login that answered HTTP 401 while every screen
read the login as present. These two routes put the login's STATE where a person can act on
it: ``GET /builders/logins`` reads each builder login this deployment uses by default as
``verified`` / ``unverified`` / ``invalid`` with its age — from the recorded verifications,
never by calling a model — and ``POST /builders/{builder}/login/verify`` verifies it once (one
no-tool Haiku turn through the builder's own environment, at most once every 10 s across the
deployment) and records the outcome, which the next submit and the ``/health`` ``builders``
probe then read. The Settings screen's Claude Code login card calls both; the refusal a
submit meets (``builder_login_invalid``) sends the person there.

Navigation
----------
What it is:   The route module for the builder logins' verification state and the Verify that
              refreshes it.
What it does: Lists every builder with a verify under the deployment's default auth mode, its
              state, age, outcome, source label and at most four characters of the token;
              verifies one on request (operator and above), rate-limited deployment-wide, and
              records it for the submit gate and the health probe. Never returns a token.
How:          ``LOGIN_VERIFIERS`` → ``login_state`` (one indexed event read each) for the list;
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
    login_state,
    run_verification,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.secrets import VerifyLimiterDep

router = APIRouter(tags=["builders"])
_ERR = {"model": ErrorEnvelope}


class LoginStateOut(BaseModel):
    """:meth:`crb.server.builder_login.LoginState.to_dict` — never a token."""

    builder: str
    auth: str
    state: str = Field(description="one of " + " | ".join(LOGIN_STATES))
    status: str = ""
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
    items: list[LoginStateOut]


@router.get(
    "/builders/logins",
    response_model=LoginStateList,
    responses={401: _ERR},
    summary="Each builder login this deployment uses: verified, unverified or invalid, with its age",
)
def list_builder_logins(viewer: ViewerDep, db: DbDep, settings: SettingsDep) -> LoginStateList:
    """Read from the recorded verifications only: listing never calls a model."""
    del viewer
    ttl = settings.builder.login_ttl_s
    return LoginStateList(
        items=[
            LoginStateOut(**login_state(db, name, v.default_auth(), ttl_s=ttl).to_dict())
            for name, v in sorted(LOGIN_VERIFIERS.items())
        ]
    )


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
    if builder == "claude_code" and mode not in ("cli", "api_key"):
        raise ApiError(422, "validation_error", f"auth must be 'cli' or 'api_key', not {mode!r}")
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
    return LoginStateOut(**state.to_dict())


__all__ = ["router"]
