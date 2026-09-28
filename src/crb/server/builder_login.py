"""A run cannot start on a dead builder login: the verification cache and the submit gate.

Pilot D1 (2026-09-27): a canary was queued on a Claude Code login that answered HTTP 401. The
submit gate checked the credential's PRESENCE (P-003), the health page's ``builders`` probe read
``ok`` from the same presence, and the row was filed as a provider outage. A login that is
present is not a login that works — only running the CLI once proves that.

What lives here
---------------
* **The verification record.** Every verification of a builder's login — the one a submit runs,
  the Verify on Settings, the stored-token verify — is one ``builder.login.verified`` system
  event on the ``(builder, auth)`` trace (:func:`login_trace`): the outcome, the source LABEL
  (``env`` / ``secrets_file`` / ``keychain``), at most four characters of the token, the CLI
  version, who or what asked, and when. Never the token. The latest event IS the cache: shared
  by every API replica, append-only, and the audit trail of who verified what.
* **The state a reader sees** (:class:`LoginState`): ``verified`` (the last verification passed
  within :attr:`~crb.server.settings.BuilderSettings.login_ttl_s`), ``invalid`` (it failed
  within that time — 401, no CLI, a timeout: the gate fails closed on each) or ``unverified``
  (none, too old, or made for a different token than the one a build would now use).
* **The submit gate** (:func:`login_refusal`, called by ``submit_refusals`` — the ONE gate every
  route that enqueues a run goes through, P-093): for each builder a replay, blind or factory run
  would call that exposes a verify, a fresh ``verified`` passes; a fresh ``invalid`` is refused
  422 ``builder_login_invalid`` before anything is queued or spent, naming the builder, the auth
  mode and the token source label; an ``unverified`` login is verified ONCE first (one no-tool
  Haiku turn), recorded, then judged. Each refusal is a ``builder.login.refused`` event.
* **The worker's own evidence** (:func:`record_refused_login`): a build that meets a refused
  login records it ``invalid`` at once, so the next submit is refused without a verify.
* **The claim check** (:func:`claim_refusal`): the worker reads the same state at claim, from
  the cache only, and fails a run whose login was recorded invalid after it was queued, before
  any build (``trigger: claim``).
* **Every mode, by role** (:func:`login_readings`): the list and the probe read each auth mode
  a run could use, not only the default; a viewer and ``/health`` get
  :data:`PUBLIC_LOGIN_FIELDS` only — presence and state, never the fingerprint or source (F25).
* **The registry** (:data:`LOGIN_VERIFIERS`): which builders expose a verify, and
  :data:`LOGIN_VERIFY_EXEMPT` says why each other one does not — a test holds every registered
  builder to one or the other, so a new builder cannot skip the gate silently.

The ``/health`` ``builders`` probe reads the same state and never calls a model; a verification
happens only at a submit whose login is not fresh, or when a person presses Verify.

Navigation
----------
What it is:   The builder-login verification cache (system events), the state it reads as, the
              submit gate that refuses a run on a login that is not verified, and the registry of
              builders that expose a verify.
What it does: Records every verification as one event (never a token); reads the latest as
              ``verified`` / ``invalid`` / ``unverified`` with its age against the TTL and the
              current token source; refuses a build run whose builder's login is invalid, and
              verifies once first when it is not fresh — before anything is queued or spent.
How:          ``LOGIN_VERIFIERS[builder]`` = ``(verify, resolve)`` → ``latest_verification`` (one
              indexed read) → ``LoginState.of`` → at submit, a per-``(builder, auth)`` lock around
              "read → verify if stale → record" so concurrent submits verify once →
              ``ApiError(422, "builder_login_invalid")`` + ``builder.login.refused``; at claim,
              ``claim_refusal`` → ``record_claim_refusal``.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/claude_code.py (``verify_login`` / ``login_resolution`` — the one
              verify and the source it names), src/crb/server/routes/runs.py
              (``submit_refusals`` calls ``login_refusal``), src/crb/server/routes/builders.py
              (``GET /builders/logins``, ``POST /builders/{builder}/login/verify``),
              src/crb/server/routes/system.py (the ``builders`` probe),
              src/crb/server/routes/admin.py
              (the stored-token verify records here), src/crb/server/worker.py (a build that
              meets a refused login records it; the claim check),
              src/crb/store/events.py (``append_event``),
              src/crb/server/settings.py (``BuilderSettings.login_ttl_s``)
Tested by:    tests/test_builder_login.py
Touch when:   never for a new repository; a builder gains a verify (add it to
              ``LOGIN_VERIFIERS`` and drop it from ``LOGIN_VERIFY_EXEMPT``); a new place verifies
              a login (record it with ``record_verification``).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.builders.claude_code import (
    AUTH_MODES,
    VERIFY_ERROR,
    VERIFY_INVALID,
    VERIFY_OK,
    LoginCheck,
    credential_missing,
    default_auth,
    login_resolution,
    verify_login,
)
from crb.core.ledger import FAILURE_OUTAGE, OUTAGE_CAUSE_AUTH, derive_outage_cause
from crb.core.redact import redact_and_cap
from crb.observability.events import StepStatus
from crb.server.deps import ApiError
from crb.store.events import append_event
from crb.store.models import Event, Run

log = logging.getLogger("crb.server.builder_login")

#: The event a verification writes, and the one a refused submit writes.
VERIFIED_ACTION = "builder.login.verified"
REFUSED_ACTION = "builder.login.refused"
#: The refusal's error code (docs/API.md "Conventions").
LOGIN_INVALID_CODE = "builder_login_invalid"
#: What a reader sees.
STATE_VERIFIED = "verified"
STATE_UNVERIFIED = "unverified"
STATE_INVALID = "invalid"
LOGIN_STATES: tuple[str, ...] = (STATE_VERIFIED, STATE_UNVERIFIED, STATE_INVALID)
#: Who asked for a verification (``trigger`` in the event).
TRIGGER_SUBMIT = "submit"
TRIGGER_SETTINGS = "settings"
TRIGGER_STORED_TOKEN = "stored_token"  # noqa: S105 — a trigger NAME, not a secret
#: A build met the refusal itself (the worker records it; no verify was spent).
TRIGGER_BUILD = "build"
#: Where the person fixes a login — the refusal and the probe name it.
FIX_WHERE = "Settings → Claude Code login"
#: A run refused at CLAIM (the worker) rather than at submit: its login was recorded invalid
#: after it was queued (Q1's review).
TRIGGER_CLAIM = "claim"
#: What a viewer, and ``/health`` (which answers without a session), are served of a login:
#: its presence and state — never the fingerprint, the token source, the CLI version or the
#: verification's own words (the F25 rule ``/settings/secrets`` keeps; Q1's review).
PUBLIC_LOGIN_FIELDS: frozenset[str] = frozenset(
    {"builder", "auth", "state", "status", "present", "default", "checked_at", "age_s"}
    | {"ttl_s", "reason"}
)
#: The run kinds that call a builder (``crb.server.schemas.BUILD_KINDS`` — a replay, a measure
#: or budget sweep, which are replay / blind runs, and a factory run).
GATED_KINDS: frozenset[str] = frozenset({"replay", "blind", "factory"})

#: ``verify(auth, binary) -> LoginCheck`` — runs the builder's login once.
VerifyFn = Callable[[str, str], LoginCheck]
#: ``resolve(auth) -> (source, fingerprint)`` — where a build would take its login, no model call.
ResolveFn = Callable[[str], tuple[str, str]]


@dataclass(frozen=True)
class LoginVerifier:
    """A builder's verify and its source resolution, the auth mode it defaults to, the
    presence check (``missing(auth, secrets_dir=…)`` → ``""`` when a credential is present —
    P-003's check) that says whether the login is configured at all, and every auth mode it
    has (each is read, not only the default — Q1's review)."""

    verify: VerifyFn
    resolve: ResolveFn
    default_auth: Callable[[], str]
    missing: Callable[..., str] = credential_missing
    modes: tuple[str, ...] = AUTH_MODES


def _claude_code_verify(auth: str, binary: str) -> LoginCheck:
    return verify_login(auth=auth, binary=binary)


#: Every builder that exposes a verify. The suite pins the claude_code entry to a fake
#: (tests/conftest.py) so no test ever runs the real CLI.
LOGIN_VERIFIERS: dict[str, LoginVerifier] = {
    "claude_code": LoginVerifier(_claude_code_verify, login_resolution, default_auth),
}
#: Every other registered builder, with why it has no verify (tests/test_builder_login.py holds
#: every registered builder to one of the two).
LOGIN_VERIFY_EXEMPT: dict[str, str] = {
    "openai_agent": (
        "an OpenAI-compatible endpoint exposes no login to verify without a model call; its key "
        "is checked for presence at submit (P-003), and a key the provider refuses (HTTP 401 or "
        "403) or the worker lacks is written 'authentication failed' "
        "(crb.builders.base.model_error_text), which the ledger reads outage, cause auth"
    ),
    "editblock": "the same OpenAI-compatible client as openai_agent — presence at submit (P-003)",
    "fixture_gold": "the test-only fixture builder applies the gold diff and calls no model",
}


def login_trace(builder: str, auth: str) -> str:
    """The ``(builder, auth)`` trace every verification and refusal of that login lands on."""
    return hashlib.sha256(f"builder:login:{builder}:{auth}".encode()).hexdigest()[:32]


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _parse(ts: str) -> _dt.datetime | None:
    try:
        parsed = _dt.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.UTC)


@dataclass(frozen=True)
class LoginState:
    """A login as a reader sees it: the state, the last verification's outcome and its age.
    ``detail`` is the probe's own redacted words; nothing here is ever a token."""

    builder: str
    auth: str
    state: str
    ttl_s: int
    status: str = ""
    detail: str = ""
    source: str = ""
    fingerprint: str = ""
    cli_version: str = ""
    checked_at: str = ""
    age_s: float | None = None
    trigger: str = ""
    #: Why an ``unverified`` login is not verified (never verified / too old / a new token).
    reason: str = ""

    @classmethod
    def of(
        cls,
        builder: str,
        auth: str,
        last: Mapping[str, Any] | None,
        *,
        ttl_s: int,
        resolution: tuple[str, str] | None,
        now: _dt.datetime | None = None,
    ) -> LoginState:
        """Judge the latest recorded verification against the TTL and the token source a
        build would use now (``resolution``; ``None`` when it cannot be read)."""
        if not last:
            return cls(builder, auth, STATE_UNVERIFIED, ttl_s, reason="never verified")
        at = str(last.get("checked_at", "") or "")
        ts = _parse(at)
        age = None if ts is None else round(((now or _now()) - ts).total_seconds(), 1)
        base = cls(
            builder,
            auth,
            STATE_UNVERIFIED,
            ttl_s,
            status=str(last.get("status", "") or ""),
            detail=str(last.get("detail", "") or ""),
            source=str(last.get("source", "") or ""),
            fingerprint=str(last.get("fingerprint", "") or "")[:4],
            cli_version=str(last.get("cli_version", "") or ""),
            checked_at=at,
            age_s=age,
            trigger=str(last.get("trigger", "") or ""),
        )
        if age is None or age > ttl_s or age < 0:
            return _replace(base, reason=f"the last verification is older than {ttl_s} s")
        if resolution is not None and (base.source, base.fingerprint) != tuple(resolution):
            return _replace(
                base, reason="the login a build would use changed since it was last verified"
            )
        return _replace(base, state=STATE_VERIFIED if base.status == VERIFY_OK else STATE_INVALID)

    def to_dict(self) -> dict[str, Any]:
        return {
            "builder": self.builder,
            "auth": self.auth,
            "state": self.state,
            "status": self.status,
            "detail": self.detail,
            "source": self.source,
            "fingerprint": self.fingerprint,
            "cli_version": self.cli_version,
            "checked_at": self.checked_at or None,
            "age_s": self.age_s,
            "ttl_s": self.ttl_s,
            "trigger": self.trigger,
            "reason": self.reason,
        }

    def public_dict(self) -> dict[str, Any]:
        """:meth:`to_dict` cut to :data:`PUBLIC_LOGIN_FIELDS` — a viewer's and ``/health``'s."""
        return {k: v for k, v in self.to_dict().items() if k in PUBLIC_LOGIN_FIELDS}

    def public_sentence(self) -> str:
        """:meth:`sentence` without the token source or the verification's own words."""
        who = f"{self.builder} (auth {self.auth})"
        if self.state == STATE_UNVERIFIED:
            return f"{who}: not verified — {self.reason}"
        when = f"{self.age_s:.0f} s ago" if self.age_s is not None else "at an unknown time"
        if self.state == STATE_VERIFIED:
            return f"{who}: verified {when}"
        return f"{who}: {self.status} {when}"

    def sentence(self) -> str:
        """One line for the probe and the refusal: the login, its state, its age and why."""
        who = f"{self.builder} (auth {self.auth}, {self.source or 'no source'})"
        if self.state == STATE_UNVERIFIED:
            return f"{who}: not verified — {self.reason}"
        when = f"{self.age_s:.0f} s ago" if self.age_s is not None else "at an unknown time"
        if self.state == STATE_VERIFIED:
            return f"{who}: verified {when}"
        return f"{who}: {self.status} {when} — {self.detail or 'no detail'}"


def _replace(login: LoginState, **changes: Any) -> LoginState:
    return dataclasses.replace(login, **changes)


def latest_verification(session: Session, builder: str, auth: str) -> dict[str, Any] | None:
    """The newest ``builder.login.verified`` payload for ``(builder, auth)`` — one indexed read."""
    payload = session.execute(
        select(Event.payload_json)
        .where(Event.trace_id == login_trace(builder, auth), Event.action == VERIFIED_ACTION)
        .order_by(Event.seq.desc(), Event.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return dict(payload) if payload else None


def resolution_of(builder: str, auth: str) -> tuple[str, str] | None:
    """Where a build would take its login now, ``None`` when that cannot be read (an insecure
    secrets file — the verify then fails closed on its own)."""
    verifier = LOGIN_VERIFIERS.get(builder)
    if verifier is None:
        return None
    try:
        return verifier.resolve(auth)
    except PermissionError:
        return None


def login_state(
    session: Session, builder: str, auth: str, *, ttl_s: int, now: _dt.datetime | None = None
) -> LoginState:
    """The login as a reader sees it now — from the cache, never by calling a model."""
    return LoginState.of(
        builder,
        auth,
        latest_verification(session, builder, auth),
        ttl_s=ttl_s,
        resolution=resolution_of(builder, auth),
        now=now,
    )


def record_verification(
    factory: sessionmaker[Session],
    builder: str,
    auth: str,
    check: LoginCheck,
    *,
    trigger: str,
    actor: str = "",
    resolution: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """One ``builder.login.verified`` event for a verification that ran; returns the payload.
    The payload is :meth:`LoginCheck.to_dict` (redacted detail, ≤4-character fingerprint) plus
    who asked and when — never the token. ``resolution`` is the ``(source, fingerprint)`` a
    build resolved when the verification ran (what the cache is later compared with); the
    check's own labels stand when it is not given."""
    source, fp = resolution if resolution is not None else (check.source, check.fingerprint)
    payload = {
        "builder": builder,
        "auth": auth,
        **check.to_dict(),
        "source": source,
        "fingerprint": fp[:4],
        "checked_at": _now().isoformat(timespec="seconds"),
        "trigger": trigger,
    }
    append_event(
        factory,
        trace_id=login_trace(builder, auth),
        stage="system",
        action=VERIFIED_ACTION,
        status=StepStatus.OK if check.status == VERIFY_OK else StepStatus.ERROR,
        actor=actor,
        error="" if check.status == VERIFY_OK else check.detail,
        payload=payload,
    )
    log.info(
        "builder login verified",
        extra={"builder": builder, "auth": auth, "status": check.status, "trigger": trigger},
    )
    return payload


def run_verification(
    factory: sessionmaker[Session],
    builder: str,
    auth: str,
    *,
    binary: str = "",
    trigger: str,
    actor: str = "",
) -> dict[str, Any]:
    """Verify ``builder``'s login under ``auth`` once and record it against the token source
    a build resolved at that moment (a builder with no verify is a ``KeyError`` — the callers
    check :data:`LOGIN_VERIFIERS` first)."""
    resolution = resolution_of(builder, auth)
    try:
        check = LOGIN_VERIFIERS[builder].verify(auth, binary)
    except Exception as exc:  # a verify that cannot run is a failed verification, never a 500
        log.warning("builder login verify raised", extra={"builder": builder, "auth": auth})
        detail = redact_and_cap(
            f"the verify could not run: {type(exc).__name__}: {exc}", max_chars=600
        )
        check = LoginCheck(VERIFY_ERROR, detail)
    return record_verification(
        factory, builder, auth, check, trigger=trigger, actor=actor, resolution=resolution
    )


def record_refused_login(
    factory: sessionmaker[Session], builder: str, auth: str, error: str, *, actor: str = ""
) -> bool:
    """A build met a refused login — its error reads ``outage`` with cause ``auth`` by the
    ledger's own rule — so the login is recorded ``invalid`` at once (``trigger: build``): the
    next submit on it is refused without spending a verify (pilot D1). A provider's refusal
    (a usage limit, a 429) records nothing: the login may be fine. ``builder`` may carry an
    arm suffix (``claude_code+preflight``). ``True`` when a record was written."""
    name = builder.split("+", 1)[0]
    verifier = LOGIN_VERIFIERS.get(name)
    if verifier is None or derive_outage_cause(FAILURE_OUTAGE, error) != OUTAGE_CAUSE_AUTH:
        return False
    mode = auth.strip() or verifier.default_auth()
    detail = redact_and_cap(error.removeprefix("model_error:").strip(), max_chars=600)
    record_verification(
        factory,
        name,
        mode,
        LoginCheck(VERIFY_INVALID, detail),
        trigger=TRIGGER_BUILD,
        actor=actor,
        resolution=resolution_of(name, mode),
    )
    return True


@dataclass(frozen=True)
class LoginReading:
    """One ``(builder, auth)`` login as the list and the probe read it: its state, whether its
    credential is present, and whether it is the mode a run uses when it names none."""

    login: LoginState
    present: bool
    default: bool

    def to_dict(self, *, full: bool) -> dict[str, Any]:
        """The operating roles' view (``full``) or the presence-only view (a viewer, ``/health``)."""
        body = self.login.to_dict() if full else self.login.public_dict()
        return {**body, "present": self.present, "default": self.default}

    def sentence(self, *, full: bool) -> str:
        return self.login.sentence() if full else self.login.public_sentence()


def login_readings(session: Session, *, ttl_s: int, secrets_dir: Any = None) -> list[LoginReading]:
    """Every login a run could use: for each builder with a verify, its default auth mode and
    every other mode whose credential is present or that has a recorded verification (Q1's
    review — a ``cli`` refusal on an ``api_key``-default deployment was invisible). The default
    comes first. From the cache only: never a model call."""
    out: list[LoginReading] = []
    for name, verifier in sorted(LOGIN_VERIFIERS.items()):
        default = verifier.default_auth()
        for auth in sorted(verifier.modes, key=lambda m: (m != default, m)):
            present = not verifier.missing(auth, secrets_dir=secrets_dir)
            recorded = latest_verification(session, name, auth) is not None
            if auth != default and not present and not recorded:
                continue
            state = login_state(session, name, auth, ttl_s=ttl_s)
            out.append(LoginReading(state, present, auth == default))
    return out


def claim_refusal(factory: sessionmaker[Session], run: Run, *, ttl_s: int) -> LoginState | None:
    """The invalid login a queued run would build on, read at CLAIM from the cache — no verify,
    no model call (Q1's review: the submit gate held at submit only, so a run queued while its
    login worked was still started after the login was recorded invalid). ``None`` when every
    login the run would call is verified or unverified; an unverified one is left to the
    build, which records a refusal it meets."""
    for builder, auth in run_logins(run):
        if auth not in LOGIN_VERIFIERS[builder].modes:
            continue
        with factory() as s:
            state = login_state(s, builder, auth, ttl_s=ttl_s)
        if state.state == STATE_INVALID:
            return state
    return None


def record_claim_refusal(
    factory: sessionmaker[Session], run: Run, login: LoginState, *, actor: str
) -> str:
    """One ``builder.login.refused`` event (``trigger: claim``) for a run the worker failed
    before any build; returns the run's error line."""
    detail = {**login.to_dict(), **_fix(login.auth)}
    append_event(
        factory,
        trace_id=login_trace(login.builder, login.auth),
        stage="system",
        action=REFUSED_ACTION,
        status=StepStatus.ERROR,
        actor=actor,
        repo=run.repo,
        error=login.sentence(),
        payload={**detail, "run_kind": run.kind, "run_id": run.id, "trigger": TRIGGER_CLAIM},
    )
    return (
        f"{LOGIN_INVALID_CODE}: the {login.builder} login this {run.kind} run would use was "
        f"recorded invalid after it was queued — {login.sentence()}. Nothing was built and "
        f"nothing was spent; fix the login under {FIX_WHERE}, then submit the run again"
    )


def _fix(auth: str) -> dict[str, str]:
    """Where a refused login is fixed — the Settings card, told which mode to verify."""
    return {"fix": FIX_WHERE, "fix_path": f"/settings?auth={auth}#claude-code-login"}


_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(builder: str, auth: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault((builder, auth), threading.Lock())


def fresh_state(
    factory: sessionmaker[Session],
    builder: str,
    auth: str,
    *,
    ttl_s: int,
    binary: str = "",
    actor: str = "",
) -> LoginState:
    """The login's state for a submit: from the cache when it is fresh, else after ONE
    verification (recorded). Concurrent submits for one login verify once."""
    with _lock_for(builder, auth):
        with factory() as s:
            state = login_state(s, builder, auth, ttl_s=ttl_s)
        if state.state != STATE_UNVERIFIED:
            return state
        run_verification(factory, builder, auth, binary=binary, trigger=TRIGGER_SUBMIT, actor=actor)
        with factory() as s:
            return login_state(s, builder, auth, ttl_s=ttl_s)


def run_logins(run: Run) -> list[tuple[str, str]]:
    """``(builder, auth)`` for every builder with a verify that ``run`` would call — none for a
    run kind that calls no builder."""
    from crb.server.routes.runs import run_builders  # noqa: PLC0415 — runs imports this module

    if run.kind not in GATED_KINDS:
        return []
    cfg = dict((run.params_json or {}).get("builder_config") or {})
    out: list[tuple[str, str]] = []
    for name in run_builders(run):
        verifier = LOGIN_VERIFIERS.get(name)
        if verifier is None:
            continue
        auth = str(cfg.get("auth", "") or "").strip() or verifier.default_auth()
        out.append((name, auth))
    return list(dict.fromkeys(out))


def login_refusal(
    factory: sessionmaker[Session], run: Run, *, ttl_s: int, binary: str = ""
) -> None:
    """422 ``builder_login_invalid`` — before the run is queued and before any spend — when a
    builder the run would call has a login that failed its verification (pilot D1). A login
    that is not fresh is verified once first. The refusal names the builder, the auth mode,
    the token source label, the outcome and its age, and where to fix it; it is recorded as a
    ``builder.login.refused`` event. Never the token."""
    for builder, auth in run_logins(run):
        modes = LOGIN_VERIFIERS[builder].modes
        if auth not in modes:
            # Q1's review: an auth the builder does not have reached the real verify and raised
            raise ApiError(
                422,
                "validation_error",
                f"builder_config auth {auth!r} is not an auth mode of {builder}: one of "
                f"{', '.join(modes)}",
                detail={"builder": builder, "auth": auth, "modes": list(modes)},
            )
        state = fresh_state(factory, builder, auth, ttl_s=ttl_s, binary=binary, actor=run.actor)
        if state.state == STATE_VERIFIED:
            continue
        detail = {**state.to_dict(), **_fix(auth)}
        append_event(
            factory,
            trace_id=login_trace(builder, auth),
            stage="system",
            action=REFUSED_ACTION,
            status=StepStatus.ERROR,
            actor=run.actor,
            repo=run.repo,
            error=state.sentence(),
            payload={**detail, "run_kind": run.kind},
        )
        raise ApiError(
            422,
            LOGIN_INVALID_CODE,
            f"the {builder} login a {run.kind} run would use does not work: {state.sentence()}. "
            f"Nothing was queued and nothing was spent — fix the login under {FIX_WHERE} "
            "(sign in again or store a new token, then Verify), and submit again",
            detail=detail,
        )


__all__ = [
    "FIX_WHERE",
    "GATED_KINDS",
    "LOGIN_INVALID_CODE",
    "LOGIN_STATES",
    "LOGIN_VERIFIERS",
    "LOGIN_VERIFY_EXEMPT",
    "PUBLIC_LOGIN_FIELDS",
    "REFUSED_ACTION",
    "STATE_INVALID",
    "STATE_UNVERIFIED",
    "STATE_VERIFIED",
    "TRIGGER_BUILD",
    "TRIGGER_CLAIM",
    "TRIGGER_SETTINGS",
    "TRIGGER_STORED_TOKEN",
    "TRIGGER_SUBMIT",
    "VERIFIED_ACTION",
    "LoginReading",
    "LoginState",
    "LoginVerifier",
    "claim_refusal",
    "fresh_state",
    "latest_verification",
    "login_readings",
    "login_refusal",
    "login_state",
    "login_trace",
    "record_claim_refusal",
    "record_refused_login",
    "record_verification",
    "resolution_of",
    "run_logins",
    "run_verification",
]
