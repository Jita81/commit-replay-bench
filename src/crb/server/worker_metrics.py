"""What each worker's metrics listener did at start, recorded where ``/health`` reads it.

A worker serves its own Prometheus exposition (``CRB_METRICS_PORT``, J-TEL-1). Before pilot D5
a bind failure — a second stack on one machine holding 9464 — was one log line: the worker kept
running, its dashboards read absent, and ``/health`` said the worker was ``ok``. Now the worker
writes one ``worker.metrics`` system event at start with the listener's state (``listening`` on
``addr:port`` — the port ``auto`` chose included — ``off`` by choice, or ``degraded`` with the
reason and the fix), and the ``worker`` probe reads the latest one per worker. No table, no
migration: the events table is the record of what happened, and it is append-only.

Navigation
----------
What it is:   The write and the read of the ``worker.metrics`` event — each worker's metrics
              listener state at start.
What it does: ``record_exposition`` writes one ``system`` event on the worker's own metrics
              trace (never raises into the worker: a failed write is logged by
              ``append_event``); ``exposition_by_worker`` returns the latest recorded state per
              worker id for the ``worker`` probe.
How:          ``worker_metrics_trace(worker_id)`` = a fixed 32-character trace per worker →
              ``crb.store.events.append_event`` (the next ``seq`` under the write lock) → the
              probe selects the newest ``worker.metrics`` event on each trace.
Layer:        server — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/observability/metrics.py (``Exposition`` — what is recorded),
              src/crb/server/worker_main.py (``start_metrics`` starts the listener and records
              it), src/crb/server/routes/system.py (``probe_worker`` reads it),
              src/crb/store/events.py (``append_event``), docs/DEPLOYMENT.md (two stacks on one
              machine)
Tested by:    tests/test_worker.py, tests/test_server_system.py
Touch when:   never for a new repository; when the worker gains another start-time fact
              ``/health`` must show (record it the same way, on its own action).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.observability.events import StepStatus
from crb.observability.metrics import EXPOSITION_DEGRADED, Exposition
from crb.store.events import append_event
from crb.store.models import Event

#: The event action a worker writes once at start.
WORKER_METRICS_ACTION = "worker.metrics"


def worker_metrics_trace(worker_id: str) -> str:
    """The worker's own metrics trace: 32 hex characters, fixed for a worker id."""
    return hashlib.sha256(f"worker:metrics:{worker_id}".encode()).hexdigest()[:32]


def record_exposition(
    factory: sessionmaker[Session], worker_id: str, exposition: Exposition
) -> None:
    """One ``worker.metrics`` event: ``error`` status when the listener is ``degraded``,
    ``ok`` otherwise, the state in the payload. Never raises for an I/O failure (the store's
    ``append_event`` logs and drops it): a record that cannot be written must not stop the
    worker it describes."""
    append_event(
        factory,
        trace_id=worker_metrics_trace(worker_id),
        stage="system",
        action=WORKER_METRICS_ACTION,
        status=StepStatus.ERROR if exposition.state == EXPOSITION_DEGRADED else StepStatus.OK,
        actor=worker_id,
        error=exposition.reason if exposition.state == EXPOSITION_DEGRADED else "",
        payload={"worker_id": worker_id, **exposition.to_dict()},
    )


def exposition_by_worker(
    factory: sessionmaker[Session], worker_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """The latest recorded listener state per worker id (a worker with none is absent)."""
    traces = {worker_metrics_trace(w): w for w in worker_ids}
    if not traces:
        return {}
    out: dict[str, dict[str, Any]] = {}
    with factory() as s:
        rows = s.execute(
            select(Event.trace_id, Event.payload_json)
            .where(Event.trace_id.in_(list(traces)), Event.action == WORKER_METRICS_ACTION)
            .order_by(Event.seq.desc(), Event.id.desc())
        ).all()
    for trace_id, payload in rows:
        worker = traces[str(trace_id)]
        if worker not in out:
            body = dict(payload or {})
            out[worker] = {k: body.get(k) for k in ("state", "addr", "port", "requested", "reason")}
    return out


__all__ = [
    "WORKER_METRICS_ACTION",
    "exposition_by_worker",
    "record_exposition",
    "worker_metrics_trace",
]
