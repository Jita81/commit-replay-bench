"""The go-live checklist as a reading: each line proven, attested or unproven (ADR-0031).

docs/DEPLOYMENT.md §8 lists what must hold before a deployment goes live. Some lines are
checks this product can run itself — the health check is green, the ledger verifies, people
sign in through the organisation's provider, every repository qualifies in the sealed
posture, tests and the builder run sealed. The others are acts only the operator can do on
their own infrastructure — an egress test from a worker pod, a rehearsed restore, a
penetration test. Before this module the product said nothing about any of them.

Every line now has one state:

* ``proven`` — a product line whose check passed when this reading was taken;
* ``attested`` — an operator line an admin has recorded as done through the product: who
  recorded it, when the act was performed, when it was recorded and what was done (one
  ``golive.attested`` event on the ``golive`` system trace);
* ``unproven`` — anything else, with the reason: a product check that failed (and what
  failed), or an operator line with no attestation in force.

A product line can never be attested: an attestation cannot stand in for a check the product
runs (409 ``proven_by_product``). An attestation is withdrawn by another event
(``golive.withdrawn``), never by editing one — the events table is append-only. Nothing here
invents a record: a line reads ``attested`` only when a person recorded it.

Navigation
----------
What it is:   The go-live checklist's lines, their product checks and the attestation
              record, folded into one reading.
What it does: Defines the fourteen lines of DEPLOYMENT §8 (id, title, who proves it, the
              source of its state, its guide anchor); evaluates each product line from facts
              the caller passes in (the health body, the ledger verification, the settings,
              whether an organisation sign-in is configured) and from the users,
              qualifications (each repository's latest docker posture), runs (the worker's
              own stamp of where it ran) and events tables — never from a setting alone;
              names stale local admins only to an admin; reads the attestation in force per
              operator line; writes ``golive.attested`` / ``golive.withdrawn`` events, the
              day of the act bounded on both sides with a day's slack; counts the lines by
              state for the platform stream's own numbers.
How:          ``LINES`` → ``evaluate(session, settings, health, ledger, oidc_enabled)`` →
              ``GoLiveReading`` (``to_dict``); ``attest`` / ``withdraw`` validate the line
              and append one event with ``append_system_event`` (the caller commits).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md,
              docs/adr/0023-production-refuses-the-unsealed-posture.md,
              docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/server/routes/golive.py (the routes that serve and record it),
              src/crb/server/routes/system.py (``collect_health`` — the health body),
              src/crb/server/routes/ledger.py (``verify_ledger``), src/crb/server/flow.py
              (the platform stream counts proven lines), src/crb/server/routes/runs.py
              (``append_system_event``), ui/src/screens/Posture/GoLiveList.tsx (the reading
              on /posture), ui/src/screens/Settings/AttestationsCard.tsx (the recording),
              docs/DEPLOYMENT.md#8-go-live-checklist (the lines, each marked)
Tested by:    tests/test_golive.py, tests/test_server_routes_golive.py
Touch when:   never for a new repository; a line is added to DEPLOYMENT §8 (add it to
              ``LINES`` with who proves it, and to the guide in the same change); a product
              check learns to read a line the operator used to attest (move it, and say so
              in the ADR).
Claims:       ``proven`` means the check passed when the reading was taken, not that it will
              stay passed; ``attested`` means a named admin recorded the act, not that the
              product verified it (docs/EVIDENCE-AND-CLAIMS.md#1-the-four-tags).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.server.flow_record import MOMENT_OBSERVED, install_moments
from crb.server.routes.admin import user_trace_id
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.settings import SEALED_EXECUTOR, Settings
from crb.store import qualifications as store_q
from crb.store.models import Event, Repo, Run, User

PROVEN = "proven"
ATTESTED = "attested"
UNPROVEN = "unproven"
STATES: tuple[str, ...] = (PROVEN, ATTESTED, UNPROVEN)

BY_PRODUCT = "product"
BY_OPERATOR = "operator"

ATTESTED_ACTION = "golive.attested"
WITHDRAWN_ACTION = "golive.withdrawn"
#: The one system trace every go-live attestation is written to.
TRACE_ID = system_trace_id("golive")

DOC = "DEPLOYMENT#8-go-live-checklist"
STATEMENT_MAX = 500


@dataclass(frozen=True)
class Line:
    """One line of DEPLOYMENT §8: ``proves`` is who can make it true in the product."""

    id: str
    title: str
    proves: str
    source: str
    doc: str = DOC


#: The checklist, in the guide's order. ``source`` says where the state comes from.
LINES: tuple[Line, ...] = (
    Line(
        "image-digest",
        "The running image is a released digest, verified with deploy/verify-image.sh",
        BY_OPERATOR,
        "an admin's attestation (the product cannot read the digest it runs from)",
    ),
    Line(
        "health-green",
        "The health check is green: database, migrations at head, append-only, ledger, "
        "builders and worker",
        BY_PRODUCT,
        "GET /health, read when this page was loaded",
    ),
    Line(
        "doctor",
        "crb doctor passes on the API host and on the worker host",
        BY_OPERATOR,
        "an admin's attestation (crb doctor runs on each host, outside the product)",
    ),
    Line(
        "ledger-verified",
        "The ledger verifies: chain intact and false-Q1 = 0",
        BY_PRODUCT,
        "GET /ledger/verify, read when this page was loaded",
    ),
    Line(
        "row-hash-recorded",
        "The last row_hash is recorded outside this deployment",
        BY_OPERATOR,
        "an admin's attestation (where the hash is kept is outside the product)",
    ),
    Line(
        "sign-in",
        "People sign in through the organisation's provider; local sign-in is off and the "
        "bootstrap admin is rotated or deactivated",
        BY_PRODUCT,
        "the settings, the accounts and their events (an OpenID Connect account that has "
        "signed in is the live proof)",
        "DEPLOYMENT#41-entra-id--crboidc",
    ),
    Line(
        "egress-denied",
        "An egress test from a worker pod to a public address fails",
        BY_OPERATOR,
        "an admin's attestation (the test runs in the cluster, outside the product)",
    ),
    Line(
        "repo-probe",
        "crb repo probe is green inside the sandbox for every configured repository",
        BY_OPERATOR,
        "an admin's attestation (crb repo probe runs on the worker host)",
    ),
    Line(
        "repos-qualified",
        "Every connected repository qualifies in the sealed posture, and provisioning is not down",
        BY_PRODUCT,
        "the qualification records in each repository's latest docker posture and the "
        "provision probe of GET /health",
        "DEPLOYMENT#34-the-workers-sandbox--choose-deliberately",
    ),
    Line(
        "backups-pitr",
        "Point-in-time recovery is on and a restore has been rehearsed and verified against "
        "the chain",
        BY_OPERATOR,
        "an admin's attestation (backups live in the database service, outside the product)",
        "DEPLOYMENT#5-backup-and-restore",
    ),
    Line(
        "false-q1-alert",
        "An alert fires on any non-zero crb_false_q1_total",
        BY_OPERATOR,
        "an admin's attestation (alert rules live in the monitoring system)",
        "DEPLOYMENT#92-alert-rules",
    ),
    Line(
        "login-rate-limit",
        "The reverse proxy limits sign-in attempts per client address",
        BY_OPERATOR,
        "an admin's attestation (the proxy is outside the product)",
    ),
    Line(
        "sealed-posture",
        "Tests and the builder both run sealed in docker",
        BY_PRODUCT,
        "the posture of GET /health and where the worker stamped its last run as running "
        "(ADR-0023)",
        "DEPLOYMENT#34-the-workers-sandbox--choose-deliberately",
    ),
    Line(
        "penetration-test",
        "A penetration test of this deployment has been done and its findings handled",
        BY_OPERATOR,
        "an admin's attestation (the test is commissioned outside the product)",
        "SECURITY#5-what-this-document-does-not-claim",
    ),
)

LINES_BY_ID: Mapping[str, Line] = {ln.id: ln for ln in LINES}


class UnknownLine(KeyError):
    """No go-live line has this id."""


class ProvenByProduct(ValueError):
    """The line is one the product proves: an attestation cannot stand in for the check."""


class NotAttested(ValueError):
    """There is no attestation in force to withdraw."""


@dataclass(frozen=True)
class Attestation:
    """Who recorded the act, when it was performed, when it was recorded, and what was done."""

    line: str
    by: str
    actor: str
    performed_on: str
    recorded_at: str
    statement: str

    def to_dict(self) -> dict[str, str]:
        return {
            "by": self.by,
            "actor": self.actor,
            "performed_on": self.performed_on,
            "recorded_at": self.recorded_at,
            "statement": self.statement,
        }


@dataclass(frozen=True)
class LineState:
    line: Line
    state: str
    detail: str
    attestation: Attestation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.line.id,
            "title": self.line.title,
            "proves": self.line.proves,
            "source": self.line.source,
            "doc": self.line.doc,
            "state": self.state,
            "detail": self.detail,
            "attestation": self.attestation.to_dict() if self.attestation else None,
        }


@dataclass(frozen=True)
class GoLiveReading:
    lines: tuple[LineState, ...]
    checked_at: str = field(
        default_factory=lambda: _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    )

    def counts(self) -> dict[str, int]:
        out = {"lines": len(self.lines), PROVEN: 0, ATTESTED: 0, UNPROVEN: 0}
        for ls in self.lines:
            out[ls.state] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [ls.to_dict() for ls in self.lines],
            "counts": self.counts(),
            "checked_at": self.checked_at,
        }


# --- the attestation record -------------------------------------------------------------


def attestations(session: Session) -> dict[str, Attestation]:
    """line id → the attestation in force (the latest ``golive.attested`` not followed by a
    ``golive.withdrawn`` for the same line)."""
    rows = session.execute(
        select(Event).where(Event.trace_id == TRACE_ID).order_by(Event.seq, Event.id)
    ).scalars()
    out: dict[str, Attestation] = {}
    for ev in rows:
        payload = dict(ev.payload_json or {})
        line = str(payload.get("line") or "")
        if line not in LINES_BY_ID:
            continue
        if ev.action == WITHDRAWN_ACTION:
            out.pop(line, None)
        elif ev.action == ATTESTED_ACTION:
            out[line] = Attestation(
                line=line,
                by=str(payload.get("by") or ""),
                actor=ev.actor,
                performed_on=str(payload.get("performed_on") or ""),
                recorded_at=ev.timestamp,
                statement=str(payload.get("statement") or ""),
            )
    return out


def _line(line_id: str) -> Line:
    line = LINES_BY_ID.get(line_id)
    if line is None:
        raise UnknownLine(line_id)
    return line


def attest(
    session: Session,
    line_id: str,
    *,
    actor: str,
    by: str,
    statement: str,
    performed_on: _dt.date,
    today: _dt.date | None = None,
) -> None:
    """Append one ``golive.attested`` event (the caller commits). Raises
    :class:`UnknownLine`, :class:`ProvenByProduct`, or ``ValueError`` for an empty statement
    or an act dated outside the bounds :func:`_check_day` sets."""
    line = _line(line_id)
    if line.proves != BY_OPERATOR:
        raise ProvenByProduct(line_id)
    text = " ".join(statement.split())
    if not text:
        raise ValueError("say what was done: the statement is empty")
    if len(text) > STATEMENT_MAX:
        raise ValueError(f"the statement is longer than {STATEMENT_MAX} characters")
    _check_day(session, line.id, performed_on, today or _dt.datetime.now(_dt.UTC).date())
    append_system_event(
        session,
        trace_id=TRACE_ID,
        action=ATTESTED_ACTION,
        actor=actor,
        payload={
            "line": line.id,
            "by": by,
            "performed_on": performed_on.isoformat(),
            "statement": text,
        },
    )


#: No place is more than a day ahead of or behind UTC, so a calendar day the admin reads on
#: their own clock is within one day of the UTC day the server reads.
_ONE_DAY = _dt.timedelta(days=1)


def _day_of(timestamp: str) -> _dt.date | None:
    try:
        return _dt.datetime.fromisoformat(timestamp).date()
    except ValueError:
        return None


def _check_day(session: Session, line_id: str, day: _dt.date, today: _dt.date) -> None:
    """The day of an act is a calendar day on the admin's clock, compared with days on the
    server's (UTC), so each bound gives one day's slack. Refused: a day after tomorrow in UTC
    (the future everywhere); a day more than one before the withdrawal the attestation
    follows (the act it withdrew cannot come back on the same evidence); a day more than one
    before the deployment was installed, when the install was observed (an act on a
    deployment cannot predate it)."""
    if day > today + _ONE_DAY:
        raise ValueError("the act cannot be dated in the future")
    withdrawn = session.execute(
        select(Event.timestamp, Event.payload_json)
        .where(Event.trace_id == TRACE_ID, Event.action == WITHDRAWN_ACTION)
        .order_by(Event.seq.desc())
    ).all()
    last = next(
        (ts for ts, payload in withdrawn if dict(payload or {}).get("line") == line_id), None
    )
    when = _day_of(last) if last else None
    if when is not None and day < when - _ONE_DAY:
        raise ValueError(
            f"the last attestation of {line_id!r} was withdrawn on {when.isoformat()}; an act "
            "dated before that cannot stand in for it — record the act done since"
        )
    installed_at, moment, _ = install_moments(session)
    installed = _day_of(installed_at) if installed_at and moment == MOMENT_OBSERVED else None
    if installed is not None and day < installed - _ONE_DAY:
        raise ValueError(
            f"this deployment was installed on {installed.isoformat()}; an act on it cannot "
            "be dated before that"
        )


def withdraw(session: Session, line_id: str, *, actor: str, by: str) -> None:
    """Append one ``golive.withdrawn`` event (the caller commits); the line reads unproven
    again. Raises :class:`UnknownLine` or :class:`NotAttested`."""
    line = _line(line_id)
    if line.id not in attestations(session):
        raise NotAttested(line_id)
    append_system_event(
        session,
        trace_id=TRACE_ID,
        action=WITHDRAWN_ACTION,
        actor=actor,
        payload={"line": line.id, "by": by},
    )


# --- the product checks -----------------------------------------------------------------


def _check_health(health: Mapping[str, Any]) -> tuple[bool, str]:
    probes = [p for p in health.get("probes") or [] if isinstance(p, Mapping)]
    if not probes:
        return False, "the health check could not be read"
    bad = [
        f"{p.get('name')} is {p.get('status')}"
        for p in probes
        if p.get("status") not in {"ok", "skipped"}
    ]
    if bad:
        return False, "not green: " + "; ".join(str(b) for b in bad)
    return True, f"{len(probes)} probes ok or skipped"


def _check_ledger(ledger: Mapping[str, Any] | None) -> tuple[bool, str]:
    if not ledger:
        return False, "the ledger verification could not be read"
    rows = int(ledger.get("rows") or 0)
    fq1 = int(ledger.get("false_q1_total") or 0)
    if ledger.get("ok"):
        return True, f"{rows} rows, chain intact, false-Q1 = {fq1}"
    if ledger.get("chain_ok") is False or ledger.get("broken_at") is not None:
        return False, f"the chain is broken at seq {ledger.get('broken_at')}"
    return False, str(ledger.get("detail") or f"false-Q1 = {fq1}")


def _password_rotated(session: Session, user: User) -> bool:
    ev = session.execute(
        select(Event.id)
        .where(Event.trace_id == user_trace_id(user.id), Event.action == "user.password_set")
        .limit(1)
    ).scalar_one_or_none()
    return ev is not None


def _check_sign_in(
    session: Session, settings: Settings, *, oidc_enabled: bool, names: bool
) -> tuple[bool, str]:
    users = list(session.execute(select(User)).scalars())
    missing: list[str] = []
    if not oidc_enabled:
        missing.append("OpenID Connect is not configured (CRB_OIDC__*)")
    elif not any(u.issuer != "local" and u.active and u.last_login for u in users):
        missing.append("no organisation account has signed in yet")
    if settings.local_auth_enabled:
        missing.append("local sign-in is on (CRB_LOCAL_AUTH_ENABLED)")
    if settings.bootstrap_admin.configured:
        missing.append("CRB_BOOTSTRAP_ADMIN__* is still set")
    stale = sorted(
        u.subject.removeprefix("local:")
        for u in users
        if u.issuer == "local"
        and u.active
        and u.role == "admin"
        and not _password_rotated(session, u)
    )
    if stale and names:
        missing.append(
            "an active local admin has never had its password set since it was created: "
            + ", ".join(stale)
        )
    elif stale:
        # the login names are half a credential: only an admin reads them (GET /users)
        missing.append(
            f"{len(stale)} active local admin{'' if len(stale) == 1 else 's'} "
            f"{'has' if len(stale) == 1 else 'have'} never had its password set since it was "
            "created (an admin reads which on this page or on Settings)"
        )
    if missing:
        return False, "; ".join(missing)
    return (
        True,
        "an organisation account has signed in, local sign-in is off and no bootstrap admin remains",
    )


def _check_repos(session: Session, health: Mapping[str, Any]) -> tuple[bool, str]:
    """Each connected repository, read in its latest docker posture — the posture the gate
    grades in until a newer one is recorded. A task qualified in an older posture never
    satisfies the gate in this one (ADR-0019), so it never proves the line either."""
    provision = next(
        (
            p
            for p in health.get("probes") or []
            if isinstance(p, Mapping) and p.get("name") == "provision"
        ),
        None,
    )
    repos = sorted(r.name for r in session.execute(select(Repo)).scalars())
    if not repos:
        return False, "no repository is connected yet"
    missing: list[str] = []
    for repo in repos:
        posture = store_q.latest_posture_for(session, repo, executor=SEALED_EXECUTOR)
        if not posture:
            missing.append(f"{repo} (no task qualified in a docker posture)")
        elif not any(
            q.is_qualified for q in store_q.latest_by_task(session, repo, posture).values()
        ):
            missing.append(f"{repo} (no task qualified in {posture}, its latest docker posture)")
    problems: list[str] = []
    if provision is not None and provision.get("status") == "down":
        problems.append(f"provisioning is down: {provision.get('detail')}")
    if missing:
        problems.append(
            f"{len(missing)} of {len(repos)} repositories have no task qualified in the sealed "
            "posture: " + ", ".join(missing)
        )
    if problems:
        return False, "; ".join(problems)
    return True, (
        f"{len(repos)} of {len(repos)} repositories have a task qualified in their latest "
        "docker posture"
    )


#: How many recent runs are read for the worker's own stamp of where it ran.
_STAMPED_RUNS = 50


def _last_stamped_run(session: Session) -> Run | None:
    """The latest run whose apparatus the worker stamped with its executor."""
    rows = session.execute(
        select(Run).order_by(Run.created.desc(), Run.id.desc()).limit(_STAMPED_RUNS)
    ).scalars()
    return next(
        (r for r in rows if isinstance(dict(r.apparatus_json or {}).get("executor"), Mapping)),
        None,
    )


def _check_sealed(session: Session, health: Mapping[str, Any]) -> tuple[bool, str]:
    """Configured sealed is not measured sealed. The line needs all three: this deployment's
    settings say docker for both; no factory build runs its builder on the host
    (``factory_builds`` ``refused`` — ADR-0023); and the last run the worker stamped ran its
    tests in docker and carries no unsealed override. A production worker whose builder is
    not docker starts only under the override and then stamps it on every run, so the stamp's
    absence there is the builder measured."""
    posture = health.get("posture")
    if not isinstance(posture, Mapping):
        return False, "the posture could not be read"
    problems: list[str] = []
    if not posture.get("sealed"):
        problems.append(
            f"tests run {posture.get('sandbox_executor')}, the builder runs "
            f"{posture.get('builder_executor')}"
        )
    factory = posture.get("factory_builds")
    if factory == "host":
        problems.append("a factory build runs its builder on the host, in no container (ADR-0023)")
    elif factory != "refused":
        problems.append("where a factory build runs is not reported")
    run = _last_stamped_run(session)
    if run is None:
        problems.append(
            "no run has recorded where it ran yet: the settings alone are not a measurement"
        )
    else:
        apparatus = dict(run.apparatus_json or {})
        ran = str(dict(apparatus.get("executor") or {}).get("executor") or "")
        if ran != SEALED_EXECUTOR:
            problems.append(
                f"the last run the worker stamped ({run.id[:8]}) ran its tests "
                f"{ran or 'somewhere it did not record'}"
            )
        if apparatus.get("unsealed_prod_override"):
            problems.append(
                f"the last run the worker stamped ({run.id[:8]}) ran under the unsealed "
                "override: its builder ran on the host"
            )
    if problems:
        return False, "; ".join(problems)
    return True, (
        "configured in docker for both, factory builds refused, and the last run the worker "
        f"stamped ({run.id[:8] if run else ''}) ran its tests in docker with no unsealed override"
    )


def evaluate(
    session: Session,
    settings: Settings,
    *,
    health: Mapping[str, Any],
    ledger: Mapping[str, Any] | None,
    oidc_enabled: bool,
    names: bool = False,
) -> GoLiveReading:
    """Every line's state now. ``health`` is the ``/health`` body, ``ledger`` the
    ``/ledger/verify`` body (``None`` when it could not be read). ``names`` is whether the
    reader may see local admins' login names (an admin): anyone else reads how many."""
    checks = {
        "health-green": lambda: _check_health(health),
        "ledger-verified": lambda: _check_ledger(ledger),
        "sign-in": lambda: _check_sign_in(
            session, settings, oidc_enabled=oidc_enabled, names=names
        ),
        "repos-qualified": lambda: _check_repos(session, health),
        "sealed-posture": lambda: _check_sealed(session, health),
    }
    records = attestations(session)
    out: list[LineState] = []
    for line in LINES:
        if line.proves == BY_PRODUCT:
            ok, detail = checks[line.id]()
            out.append(LineState(line, PROVEN if ok else UNPROVEN, detail))
            continue
        rec = records.get(line.id)
        if rec is None:
            out.append(LineState(line, UNPROVEN, "no attestation is recorded"))
        else:
            out.append(
                LineState(
                    line,
                    ATTESTED,
                    f"{rec.by} recorded on {rec.recorded_at[:10]} that it was done on "
                    f"{rec.performed_on}",
                    rec,
                )
            )
    return GoLiveReading(tuple(out))


__all__ = [
    "ATTESTED",
    "ATTESTED_ACTION",
    "BY_OPERATOR",
    "BY_PRODUCT",
    "LINES",
    "LINES_BY_ID",
    "PROVEN",
    "STATES",
    "TRACE_ID",
    "UNPROVEN",
    "WITHDRAWN_ACTION",
    "Attestation",
    "GoLiveReading",
    "Line",
    "LineState",
    "NotAttested",
    "ProvenByProduct",
    "UnknownLine",
    "attest",
    "attestations",
    "evaluate",
    "withdraw",
]
