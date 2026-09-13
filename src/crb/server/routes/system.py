"""``/health``, ``/metrics``, ``/version`` — unauthenticated; bind to an internal interface.

``/health`` aggregates the observability probes with three store-level checks:

* ``db``          — the database answers.
* ``append_only`` — the ledger triggers exist AND an ``UPDATE`` on ``grades`` is refused
  (:func:`crb.store.ledger.assert_append_only`). Missing triggers = ``down``.
* ``ledger``      — row count and ``false_q1`` computed in SQL with the same belt
  semantics as :func:`crb.core.ledger.false_q1_total`; any false-Q1 row = ``down``.
  The same numbers refresh the ``crb_false_q1_total`` / ``crb_ledger_rows`` gauges.
* ``worker``      — running runs whose ``heartbeat`` is older than
  ``worker_heartbeat_stale_s`` are reported as stale (``degraded``).

``status`` is ``down`` → HTTP 503 so a load balancer can act on it; ``degraded``
still answers 200 (the instrument can measure, with caveats).
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import BELT_SET_V3_LEGACY
from crb.core.routing import POLICY_VERSION
from crb.core.version import APPARATUS_VERSION, __version__
from crb.observability import metrics, probes
from crb.observability.probes import DEGRADED, DOWN, OK, ProbeResult
from crb.server.deps import ApiError, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.settings import Settings
from crb.store.ledger import assert_append_only
from crb.store.models import APPEND_ONLY_TABLES, Grade, Run, User

try:  # pragma: no cover — extra installed in [server]
    from prometheus_client import CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

router = APIRouter(tags=["system"])
_ERR = {"model": ErrorEnvelope}


# --- store-level probes -------------------------------------------------------------


def probe_db(factory: sessionmaker[Session]) -> ProbeResult:
    def _ping() -> dict[str, Any]:
        with factory() as s:
            s.execute(text("SELECT 1"))
            users = int(s.execute(select(func.count(User.id))).scalar_one())
            return {"dialect": s.get_bind().dialect.name, "users": users}

    return probes.probe_callable("db", _ping)


def _count_triggers(s: Session) -> int:
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
    """``(rows, false_q1)`` — a clean row whose recorded belts are not all True is false-Q1."""
    not_all_true = or_(
        Grade.tests_unmodified.is_not(True),
        Grade.target_green.is_not(True),
        Grade.no_new_failures.is_not(True),
        (Grade.belt_set != BELT_SET_V3_LEGACY) & Grade.source_changed.is_not(True),
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
    rows, fq1 = ledger_counts(factory)
    metrics.set_ledger_health(rows=rows, false_q1=fq1)
    return rows, fq1


def probe_ledger(factory: sessionmaker[Session]) -> ProbeResult:
    try:
        rows, fq1 = refresh_ledger_gauges(factory)
    except Exception as exc:
        return ProbeResult("ledger", DOWN, f"{type(exc).__name__}: {exc}")
    data = {"rows": rows, "false_q1": fq1}
    if fq1:
        return ProbeResult("ledger", DOWN, f"false_q1={fq1} — honesty floor breached", data)
    return ProbeResult("ledger", OK, f"{rows} rows, false_q1=0", data)


def _parse_ts(value: str) -> _dt.datetime | None:
    try:
        ts = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.UTC)


def probe_worker(factory: sessionmaker[Session], stale_s: int) -> ProbeResult:
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


def probe_sandbox(settings: Settings) -> ProbeResult:
    if settings.sandbox.executor == "docker":
        return probes.probe_docker(timeout=5)
    return ProbeResult(
        "sandbox",
        DEGRADED,
        "local executor — test runs are NOT isolated (dev only)",
        {"executor": "local"},
    )


def collect_health(factory: sessionmaker[Session], settings: Settings) -> dict[str, Any]:
    results = [
        probe_db(factory),
        probe_append_only(factory),
        probe_ledger(factory),
        probe_sandbox(settings),
        probes.probe_toolchains(),
        probes.probe_builders(),
        probe_worker(factory, settings.worker_heartbeat_stale_s),
    ]
    out = probes.aggregate(results)
    out["version"] = __version__
    out["apparatus"] = APPARATUS_VERSION
    out["checked_at"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    return out


# --- routes -------------------------------------------------------------------------


@router.get("/health", summary="Aggregate health (503 when any probe is down)")
def health(response: Response, factory: SessionFactoryDep, settings: SettingsDep) -> dict[str, Any]:
    out = collect_health(factory, settings)
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
    if not settings.metrics_enabled:
        raise ApiError(404, "metrics_disabled", "CRB_METRICS_ENABLED is false")
    if not metrics.available():
        raise ApiError(503, "metrics_unavailable", "prometheus_client is not installed")
    refresh_ledger_gauges(factory)
    return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)


@router.get("/version", summary="Package, apparatus and routing-policy versions")
def version(request: Request) -> dict[str, Any]:
    started = float(getattr(request.app.state, "started_at", 0.0) or 0.0)
    return {
        "crb": __version__,
        "apparatus": APPARATUS_VERSION,
        "policy": POLICY_VERSION,
        "uptime_s": int(time.time() - started) if started else 0,
    }


__all__ = ["collect_health", "ledger_counts", "refresh_ledger_gauges", "router"]
