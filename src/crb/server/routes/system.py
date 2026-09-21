"""``/health``, ``/health/live``, ``/metrics``, ``/version`` — unauthenticated; bind to an
internal interface.

``/health`` (the DEEP probe — readiness) aggregates the observability probes with three
store-level checks:

* ``db``          — the database answers.
* ``migrations``  — the database's Alembic revision IS the code's head
  (:func:`crb.store.migrate.head_status_on`). ``down`` (503) when it is behind, ahead or
  empty — a long-lived pod whose store drifted must leave the Service, and the go-live
  checklist may point here truthfully; both revisions are in the detail. A ``create_all``
  store whose schema equals the head (a ``crb serve`` without ``crb migrate``) is
  ``degraded``, not down: complete, but unstamped until ``crb migrate`` runs.
* ``append_only`` — the ledger triggers exist AND an ``UPDATE`` on ``grades`` is refused
  (:func:`crb.store.ledger.assert_append_only`). Missing triggers = ``down``.
* ``ledger``      — row count and ``false_q1`` computed in SQL with the same belt
  semantics as :func:`crb.core.ledger.false_q1_total`; any false-Q1 row = ``down``.
  The same numbers refresh the ``crb_false_q1_total`` / ``crb_ledger_rows`` gauges.
* ``worker``      — running runs whose ``heartbeat`` is older than
  ``worker_heartbeat_stale_s`` are reported as stale (``degraded``).
* ``sandbox``     — the docker daemon answers (``docker`` executor) — **role-aware**:
  the sandbox is the WORKER's instrument. A process whose role is ``api`` (the
  ``serve`` container: no docker socket, by design — see ``deploy/Dockerfile``)
  reports the probe ``skipped``, never ``degraded``/``down``: a missing socket there
  is the intended posture, not a fault, and must not fail the API's health. The
  role is read from ``CRB_ROLE`` (:func:`process_role`; ``api`` | ``worker`` |
  ``all``, default ``all`` = one process does both, so everything is probed).

``/health/live`` (LIVENESS) answers "this process is up and can reach its database"
and nothing else — never the sandbox, the toolchains, the builders or the ledger.
It is what the image ``HEALTHCHECK`` and the Helm liveness probe hit: a liveness
probe that fails on a *dependency* (a docker socket the API is not meant to have, a
transient builder outage) restarts a healthy process.

``status`` is ``down`` → HTTP 503 so a load balancer can act on it; ``degraded``
still answers 200 (the instrument can measure, with caveats); ``skipped`` is neither
(a probe this role does not own) and never lowers the aggregate.

Navigation
----------
What it is:   The ``/health``, ``/health/live``, ``/metrics`` and ``/version`` routes — the
              unauthenticated operational surface.
What it does: Readiness aggregates the store probes (db, migrations at head, append-only
              triggers proven live, ledger false-Q1 = 0, worker heartbeats) with the
              observability probes
              (sandbox — skipped for the ``api`` role — toolchains, builders) and answers
              503 when any is ``down``; liveness checks the database only; ``/metrics``
              refreshes the ledger gauges then renders the shared registry.
How:          ``collect_health`` = the probe list → ``probes.aggregate`` → stamp;
              ``migrations_result`` turns a ``HeadStatus`` into the probe (``crb doctor``
              renders the same function from a bare URL);
              ``ledger_counts`` is the SQL twin of ``false_q1_total`` over the stored
              belts; ``process_role`` reads ``CRB_ROLE`` so the API container never fails
              on the docker socket it is not meant to have.
Layer:        server — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0011-repo-lint-belt.md (belt 5 in the false-Q1 predicate)
Works with:   src/crb/observability/probes.py (the probe vocabulary and ``aggregate``),
              src/crb/store/migrate.py (``head_status_on`` — the one head check),
              src/crb/cli/commands/service.py (``crb doctor`` renders ``migrations_result``
              and ``probe_worker``),
              src/crb/store/ledger.py (``assert_append_only``), src/crb/observability/metrics.py
              (the gauges and the registry), src/crb/server/routes/signoffs.py (the same
              false-Q1 predicate, kept in step), deploy/entrypoint.sh + deploy/Dockerfile
              (``CRB_ROLE`` per container and the ``HEALTHCHECK`` on ``/health/live``),
              docs/API.md#health--metrics-no-auth-bind-to-an-internal-interface
Tested by:    tests/test_server_system.py, tests/test_deploy_health_probes.py
Touch when:   never for a new repository; adding a probe means deciding which role owns it
              (``skipped`` elsewhere) and whether it may fail readiness; a new belt means
              extending the predicate here AND in ``FALSE_Q1_PREDICATE`` (signoffs.py) AND
              ``false_q1_total`` in src/crb/core/ledger.py together.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import BELT_SET_V3_LEGACY, BELT_SET_V5
from crb.core.routing import POLICY_VERSION
from crb.core.version import APPARATUS_VERSION, __version__
from crb.observability import metrics, probes
from crb.observability.probes import DEGRADED, DOWN, OK, ProbeResult
from crb.server.deps import ApiError, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.settings import Settings
from crb.store.ledger import assert_append_only
from crb.store.migrate import HeadStatus, head_status_on
from crb.store.models import APPEND_ONLY_TABLES, Grade, Run, User

try:  # pragma: no cover — extra installed in [server]
    from prometheus_client import CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

router = APIRouter(tags=["system"])
_ERR = {"model": ErrorEnvelope}

#: A probe this process's role does not own — neither a pass nor a fault. Extends the
#: ``ok | degraded | down`` vocabulary of :mod:`crb.observability.probes` (its proper
#: home; that module is outside this change's file set — see the finish report).
#: :func:`probes.aggregate` lowers the aggregate only for ``degraded`` / ``down``.
SKIPPED = "skipped"

#: Process roles. ``api`` = the ``serve`` container (HTTP, no docker socket); ``worker``
#: = the queue consumer (owns the sandbox); ``all`` = one process does both.
ROLE_API = "api"
ROLE_WORKER = "worker"
ROLE_ALL = "all"
ROLES: tuple[str, ...] = (ROLE_API, ROLE_WORKER, ROLE_ALL)
#: With no ``CRB_ROLE`` the process assumes it does everything, so EVERY probe is
#: evaluated: an unset or unrecognised role never hides a probe (fail closed).
DEFAULT_ROLE = ROLE_ALL
ROLE_ENV = "CRB_ROLE"


def process_role(environ: Mapping[str, str] | None = None) -> str:
    """The role this process runs as, from ``CRB_ROLE`` (``api`` | ``worker`` | ``all``;
    case-insensitive; default and fallback for anything else: ``all``).

    Read here, once, rather than through :class:`Settings`: ``settings.py`` is the
    proper home for the field (reported as a follow-up); the documented contract is
    this function's, and the Helm chart / compose set the variable per container.
    """
    raw = (os.environ if environ is None else environ).get(ROLE_ENV, DEFAULT_ROLE)
    role = str(raw or "").strip().lower()
    return role if role in ROLES else DEFAULT_ROLE


# --- store-level probes -------------------------------------------------------------


def probe_db(factory: sessionmaker[Session]) -> ProbeResult:
    """``db``: the database answers ``SELECT 1`` (plus the user count as a data point)."""

    def _ping() -> dict[str, Any]:
        with factory() as s:
            s.execute(text("SELECT 1"))
            users = int(s.execute(select(func.count(User.id))).scalar_one())
            return {"dialect": s.get_bind().dialect.name, "users": users}

    return probes.probe_callable("db", _ping)


#: The fix every not-at-head reading names (the entrypoint / Helm Job runs the same command).
MIGRATE_FIX = "run `crb migrate` (the migrate Job / `python -m crb.store.migrate upgrade`)"


def migrations_result(st: HeadStatus) -> ProbeResult:
    """``migrations`` from a :class:`HeadStatus` — shared with ``crb doctor`` so the two
    surfaces cannot disagree. ``ok`` at head; ``degraded`` for a ``create_all`` schema that
    equals the head but carries no ``alembic_version`` (complete; ``crb migrate`` stamps it);
    ``down`` otherwise, naming both revisions and the fix."""
    data = st.to_dict()
    if st.at_head:
        return ProbeResult("migrations", OK, f"database at {st.head} = code head", data)
    if st.database is not None:
        return ProbeResult(
            "migrations",
            DOWN,
            f"database at {st.database}, code head {st.head} — {MIGRATE_FIX}",
            data,
        )
    if st.matches_models:
        return ProbeResult(
            "migrations",
            DEGRADED,
            f"schema matches head {st.head} but carries no alembic_version (a create_all "
            "store) — run `crb migrate` to stamp it",
            data,
        )
    where = "empty" if st.unversioned_at is None else f"unversioned schema at {st.unversioned_at}"
    return ProbeResult(
        "migrations",
        DOWN,
        f"database not migrated ({where}), code head {st.head} — {MIGRATE_FIX}",
        data,
    )


def probe_migrations(factory: sessionmaker[Session]) -> ProbeResult:
    """``migrations``: the store's Alembic revision against the packaged head, read on a
    session's own connection (one ``SELECT`` on ``alembic_version`` for a versioned store)."""
    try:
        with factory() as s:
            st = head_status_on(s.connection())
    except Exception as exc:
        return ProbeResult("migrations", DOWN, f"{type(exc).__name__}: {exc}")
    return migrations_result(st)


def _count_triggers(s: Session) -> int:
    """How many of the expected ``<table>_no_update`` / ``_no_delete`` triggers exist."""
    dialect = s.get_bind().dialect.name
    names = [f"{t}_{kind}" for t in APPEND_ONLY_TABLES for kind in ("no_update", "no_delete")]
    if dialect == "sqlite":
        rows = s.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars()
    elif dialect == "postgresql":
        rows = s.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars()
    else:  # pragma: no cover — unsupported by policy
        return 0
    present = set(rows)
    return sum(1 for n in names if n in present)


def probe_append_only(factory: sessionmaker[Session]) -> ProbeResult:
    """``append_only``: every trigger present AND an UPDATE on ``grades`` refused —
    counting alone would pass a trigger that exists but does not fire."""
    expected = 2 * len(APPEND_ONLY_TABLES)
    try:
        with factory() as s:
            found = _count_triggers(s)
        assert_append_only(factory)
    except Exception as exc:
        return ProbeResult("append_only", DOWN, f"{type(exc).__name__}: {exc}")
    if found < expected:
        return ProbeResult(
            "append_only",
            DOWN,
            f"{found}/{expected} append-only triggers present",
            {"triggers": found, "expected": expected},
        )
    return ProbeResult(
        "append_only",
        OK,
        "triggers present; UPDATE on grades refused",
        {"triggers": found, "expected": expected},
    )


def ledger_counts(factory: sessionmaker[Session]) -> tuple[int, int]:
    """``(rows, false_q1)`` — a clean row whose recorded belts are not all True is false-Q1
    (belt 5 counts only where recorded — ``v5`` — and only when it rejected: ``NULL``
    there is *not evaluated*, ADR-0011)."""
    not_all_true = or_(
        Grade.tests_unmodified.is_not(True),
        Grade.target_green.is_not(True),
        Grade.no_new_failures.is_not(True),
        (Grade.belt_set != BELT_SET_V3_LEGACY) & Grade.source_changed.is_not(True),
        (Grade.belt_set == BELT_SET_V5) & Grade.repo_lint_clean.is_(False),
    )
    with factory() as s:
        rows = int(s.execute(select(func.count(Grade.seq))).scalar_one())
        fq1 = int(
            s.execute(
                select(func.count(Grade.seq)).where(Grade.clean.is_(True), not_all_true)
            ).scalar_one()
        )
    return rows, fq1


def refresh_ledger_gauges(factory: sessionmaker[Session]) -> tuple[int, int]:
    """Recount and push ``crb_ledger_rows`` / ``crb_false_q1_total``; returns the pair."""
    rows, fq1 = ledger_counts(factory)
    metrics.set_ledger_health(rows=rows, false_q1=fq1)
    return rows, fq1


def probe_ledger(factory: sessionmaker[Session]) -> ProbeResult:
    """``ledger``: ``down`` on any false-Q1 row — the honesty floor is a readiness condition."""
    try:
        rows, fq1 = refresh_ledger_gauges(factory)
    except Exception as exc:
        return ProbeResult("ledger", DOWN, f"{type(exc).__name__}: {exc}")
    data = {"rows": rows, "false_q1": fq1}
    if fq1:
        return ProbeResult("ledger", DOWN, f"false_q1={fq1} — honesty floor breached", data)
    return ProbeResult("ledger", OK, f"{rows} rows, false_q1=0", data)


def _parse_ts(value: str) -> _dt.datetime | None:
    """ISO-8601 → aware UTC datetime, ``None`` when unparseable (treated as stale)."""
    try:
        ts = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.UTC)


def probe_worker(factory: sessionmaker[Session], stale_s: int) -> ProbeResult:
    """``worker``: ``degraded`` when a running run's heartbeat is older than ``stale_s``
    (the queue will reclaim it; the probe is the early warning)."""
    try:
        with factory() as s:
            running = list(
                s.execute(
                    select(Run.id, Run.worker_id, Run.heartbeat).where(Run.status == "running")
                ).all()
            )
            queued = int(
                s.execute(select(func.count(Run.id)).where(Run.status == "queued")).scalar_one()
            )
    except Exception as exc:
        return ProbeResult("worker", DOWN, f"{type(exc).__name__}: {exc}")
    now = _dt.datetime.now(_dt.UTC)
    stale: list[str] = []
    for run_id, _worker, heartbeat in running:
        ts = _parse_ts(heartbeat) if heartbeat else None
        if ts is None or (now - ts).total_seconds() > stale_s:
            stale.append(str(run_id))
    data = {"running": len(running), "queued": queued, "stale": stale, "stale_after_s": stale_s}
    if stale:
        return ProbeResult(
            "worker", DEGRADED, f"{len(stale)} running run(s) with a stale heartbeat", data
        )
    if not running:
        return ProbeResult("worker", OK, "idle" if not queued else f"idle, {queued} queued", data)
    return ProbeResult("worker", OK, f"{len(running)} running, heartbeats fresh", data)


def probe_sandbox(settings: Settings, role: str = ROLE_ALL) -> ProbeResult:
    """The sandbox executor, as seen from a process of ``role``.

    The sandbox belongs to the worker. An ``api`` process reports ``skipped``: the
    ``serve`` container carries the docker CLIENT only and no socket — by design
    (``deploy/Dockerfile``, ``docs/SECURITY.md``) — so probing the daemon there would
    always read ``down`` and take the API with it. ``worker`` / ``all`` probe it.
    """
    executor = settings.sandbox.executor
    if role == ROLE_API:
        return ProbeResult(
            "sandbox",
            SKIPPED,
            "not probed here: the sandbox is the worker's — this process is the API "
            f"({ROLE_ENV}={ROLE_API})",
            {"executor": executor, "role": role},
        )
    if executor == "docker":
        return probes.probe_docker(timeout=5)
    return ProbeResult(
        "sandbox",
        DEGRADED,
        "local executor — test runs are NOT isolated (dev only)",
        {"executor": "local"},
    )


def _stamp(out: dict[str, Any], role: str) -> dict[str, Any]:
    """Add version, apparatus, role and time to an aggregated probe result."""
    out["version"] = __version__
    out["apparatus"] = APPARATUS_VERSION
    out["role"] = role
    out["checked_at"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    return out


def collect_health(
    factory: sessionmaker[Session], settings: Settings, *, role: str | None = None
) -> dict[str, Any]:
    """The deep probe (readiness). ``role`` defaults to :func:`process_role`."""
    role = process_role() if role is None else role
    results = [
        probe_db(factory),
        probe_migrations(factory),
        probe_append_only(factory),
        probe_ledger(factory),
        probe_sandbox(settings, role),
        probes.probe_toolchains(),
        probes.probe_builders(),
        probe_worker(factory, settings.worker_heartbeat_stale_s),
    ]
    return _stamp(probes.aggregate(results), role)


def collect_liveness(factory: sessionmaker[Session], *, role: str | None = None) -> dict[str, Any]:
    """Liveness: the process is up and its database answers. Exactly ONE probe (``db``);
    never the sandbox, the toolchains, the builders, the ledger or the worker — a
    liveness check that fails on a dependency restarts a healthy process."""
    role = process_role() if role is None else role
    return _stamp(probes.aggregate([probe_db(factory)]), role)


# --- routes -------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Deep health / readiness (503 when any probe is down; sandbox skipped for CRB_ROLE=api)",
)
def health(response: Response, factory: SessionFactoryDep, settings: SettingsDep) -> dict[str, Any]:
    """Readiness: 503 only on ``down`` — ``degraded`` still serves (with caveats)."""
    out = collect_health(factory, settings)
    if out["status"] == DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return out


@router.get(
    "/health/live",
    summary="Liveness: process up + database reachable (503 otherwise); never probes the sandbox",
)
def health_live(response: Response, factory: SessionFactoryDep) -> dict[str, Any]:
    """Liveness: the process and its database, nothing else (see ``collect_liveness``)."""
    out = collect_liveness(factory)
    if out["status"] == DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return out


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    responses={404: _ERR, 503: _ERR},
    summary="Prometheus exposition (crb_false_q1_total must read 0)",
)
def prometheus_metrics(factory: SessionFactoryDep, settings: SettingsDep) -> Response:
    """The exposition; the ledger gauges are refreshed on every scrape so
    ``crb_false_q1_total`` is never stale."""
    if not settings.metrics_enabled:
        raise ApiError(404, "metrics_disabled", "CRB_METRICS_ENABLED is false")
    if not metrics.available():
        raise ApiError(503, "metrics_unavailable", "prometheus_client is not installed")
    refresh_ledger_gauges(factory)
    return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)


@router.get("/version", summary="Package, apparatus and routing-policy versions")
def version(request: Request) -> dict[str, Any]:
    """Package, apparatus and routing-policy versions plus uptime — what a claim cites."""
    started = float(getattr(request.app.state, "started_at", 0.0) or 0.0)
    return {
        "crb": __version__,
        "apparatus": APPARATUS_VERSION,
        "policy": POLICY_VERSION,
        "uptime_s": int(time.time() - started) if started else 0,
        # whether an organisation sign-in exists is a fact the login page and the posture
        # page both need before anyone is signed in; it names no provider and no secret
        "oidc_enabled": getattr(request.app.state, "oidc_client", None) is not None,
    }


__all__ = [
    "DEFAULT_ROLE",
    "MIGRATE_FIX",
    "ROLES",
    "ROLE_ALL",
    "ROLE_API",
    "ROLE_ENV",
    "ROLE_WORKER",
    "SKIPPED",
    "collect_health",
    "collect_liveness",
    "ledger_counts",
    "migrations_result",
    "probe_migrations",
    "probe_worker",
    "process_role",
    "refresh_ledger_gauges",
    "router",
]
