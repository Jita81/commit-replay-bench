"""The DB-backed ``StepEvent`` sink and its readers.

``events`` is an **append-only** table (the same triggers that protect the
grade ledger refuse ``UPDATE``/``DELETE``). Rows are the exact
:class:`~crb.observability.events.StepEvent` envelope so the API can serve them
over SSE with ``?after=<seq>`` resume and the UI can render any stage with one
shape.

Invariants
----------
* **A sink never raises into a run.** A failed insert (DB down, duplicate
  ``event_id``, constraint) is logged and dropped — ``dropped`` counts them — the
  run's verdicts do not depend on the event stream (the ledger is the record).
* **``seq`` is the resume cursor**, monotonic per ``trace_id``. The
  :class:`~crb.observability.events.Emitter` assigns it; when a run is executed
  more than once (a stale reclaim) the next executor must resume from
  :func:`last_seq` so cursors stay strictly increasing (see ``crb.server.worker``).
* Out-of-band system events (a reclaim, a worker note) go through
  :func:`append_event`, which allocates the next ``seq`` under the same write
  lock the ledger uses, so they never collide with a live emitter's sequence.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.observability.events import StepEvent, StepStatus
from crb.store.models import Event

_LOG = logging.getLogger(__name__)

DEFAULT_READ_LIMIT = 500
MAX_READ_LIMIT = 5000


def _to_model(e: StepEvent) -> Event:
    return Event(
        event_id=e.event_id,
        trace_id=e.trace_id,
        seq=e.seq,
        timestamp=e.timestamp,
        stage=e.stage,
        action=e.action,
        status=e.status.value,
        step_id=e.step_id,
        parent_step_id=e.parent_step_id,
        actor=e.actor,
        repo=e.repo,
        task_id=e.task_id,
        input_ref=e.input_ref,
        output_ref=e.output_ref,
        error_code=e.error_code,
        error_message=e.error_message,
        duration_ms=e.duration_ms,
        cost_usd=e.cost_usd,
        payload_json=dict(e.payload),
    )


def _from_model(m: Event) -> StepEvent:
    return StepEvent(
        trace_id=m.trace_id,
        stage=m.stage,
        action=m.action,
        status=StepStatus(m.status),
        step_id=m.step_id,
        parent_step_id=m.parent_step_id,
        actor=m.actor,
        repo=m.repo,
        task_id=m.task_id,
        input_ref=m.input_ref,
        output_ref=m.output_ref,
        error_code=m.error_code,
        error_message=m.error_message,
        duration_ms=m.duration_ms,
        cost_usd=m.cost_usd,
        payload=dict(m.payload_json or {}),
        timestamp=m.timestamp,
        seq=m.seq,
        event_id=m.event_id,
    )


def _lock(s: Session) -> None:
    """Serialise ``seq`` allocation the way :class:`crb.store.ledger.DbLedger` does."""
    dialect = s.get_bind().dialect.name
    if dialect == "sqlite":
        s.execute(text("BEGIN IMMEDIATE"))
    elif dialect == "postgresql":
        s.execute(text("SELECT pg_advisory_xact_lock(7332)"))


class DbEventSink:
    """Insert every event as one ``events`` row. Implements ``EventSink``.

    Each event is committed on its own so a reader (SSE) sees it promptly;
    :meth:`emit_many` batches when the caller has several in hand. Failures are
    logged and counted in ``dropped`` — never raised.
    """

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self.dropped = 0
        self.written = 0

    def emit(self, event: StepEvent) -> None:
        try:
            with self._factory() as s:
                s.add(_to_model(event))
                s.commit()
        except Exception as exc:  # an observer must never break a run
            self.dropped += 1
            _LOG.warning(
                "event dropped (trace=%s seq=%s %s/%s): %s: %s",
                event.trace_id,
                event.seq,
                event.stage,
                event.action,
                type(exc).__name__,
                exc,
            )
            return
        self.written += 1

    def emit_many(self, events: Iterable[StepEvent]) -> int:
        """Insert a batch in one transaction; on failure fall back to one-by-one so a
        single bad row cannot drop its neighbours. Returns the number written."""
        batch = list(events)
        if not batch:
            return 0
        try:
            with self._factory() as s:
                s.add_all(_to_model(e) for e in batch)
                s.commit()
        except Exception as exc:
            _LOG.warning(
                "event batch of %d failed (%s: %s); retrying one by one",
                len(batch),
                type(exc).__name__,
                exc,
            )
            before = self.written
            for e in batch:
                self.emit(e)
            return self.written - before
        self.written += len(batch)
        return len(batch)


def read_events(
    factory: sessionmaker[Session],
    trace_id: str,
    *,
    after_seq: int = 0,
    limit: int = DEFAULT_READ_LIMIT,
) -> list[StepEvent]:
    """Events of one trace with ``seq > after_seq``, ascending by ``seq`` (ties by
    insertion order). ``limit`` is clamped to ``MAX_READ_LIMIT``."""
    lim = max(1, min(int(limit), MAX_READ_LIMIT))
    with factory() as s:
        q = (
            select(Event)
            .where(Event.trace_id == trace_id, Event.seq > int(after_seq))
            .order_by(Event.seq, Event.id)
            .limit(lim)
        )
        return [_from_model(m) for m in s.execute(q).scalars()]


def last_seq(factory: sessionmaker[Session], trace_id: str) -> int:
    """The highest ``seq`` stored for a trace (``0`` when none)."""
    with factory() as s:
        v = s.execute(
            select(func.max(Event.seq)).where(Event.trace_id == trace_id)
        ).scalar_one_or_none()
        return int(v or 0)


def count_events(factory: sessionmaker[Session], trace_id: str) -> int:
    with factory() as s:
        return int(
            s.execute(select(func.count(Event.id)).where(Event.trace_id == trace_id)).scalar_one()
        )


def append_event(
    factory: sessionmaker[Session],
    *,
    trace_id: str,
    stage: str,
    action: str,
    status: StepStatus = StepStatus.OK,
    actor: str = "",
    repo: str = "",
    task_id: str = "",
    error: str = "",
    error_code: str = "",
    payload: dict[str, Any] | None = None,
) -> StepEvent | None:
    """Write one out-of-band event with the next ``seq`` for the trace.

    Used for system notes no live emitter owns (a stale-run reclaim, a cancel
    request). The sequence is allocated under the write lock so it cannot
    collide with a concurrent writer. Returns the stored event, or ``None`` if
    the write failed (logged, never raised).
    """
    try:
        with factory() as s:
            _lock(s)
            nxt = (
                int(
                    s.execute(
                        select(func.max(Event.seq)).where(Event.trace_id == trace_id)
                    ).scalar_one_or_none()
                    or 0
                )
                + 1
            )
            ev = StepEvent(
                trace_id=trace_id,
                stage=stage,
                action=action,
                status=status,
                step_id=task_id,
                actor=actor,
                repo=repo,
                task_id=task_id,
                error_code=error_code,
                error_message=error,
                payload=dict(payload or {}),
                seq=nxt,
            )
            s.add(_to_model(ev))
            s.commit()
            return ev
    except Exception as exc:
        _LOG.warning(
            "system event dropped (trace=%s %s/%s): %s: %s",
            trace_id,
            stage,
            action,
            type(exc).__name__,
            exc,
        )
        return None


__all__ = [
    "DEFAULT_READ_LIMIT",
    "MAX_READ_LIMIT",
    "DbEventSink",
    "append_event",
    "count_events",
    "last_seq",
    "read_events",
]
