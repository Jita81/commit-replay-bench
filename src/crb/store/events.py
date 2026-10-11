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
  An event added to a caller's own transaction (the server's ``append_system_event``)
  takes the same lock first, through :func:`lock_event_writes` — one lock for every
  writer that allocates a ``seq``, so no two can read the same last one (EI-1).
* **Every row is chained, by construction** (ADR-0029, F51). A ``before_flush`` hook on
  every ``Session`` gives each new ``Event`` its ``prev_hash`` (the table's head) and
  ``row_hash`` (:func:`crb.core.event_chain.event_row_hash`) under the events write lock,
  in insertion order, overwriting anything the writer set. The sink, ``append_event``, the
  routes' ``append_system_event`` and any plain ``add`` all flush, so none can skip it.
  A writer that bypasses the ORM (a Core insert, the release before revision 0013) is
  refused by the database: the chain columns have no default and a CHECK requires a
  SHA-256 in each, and the unique index on ``prev_hash`` refuses a second row on one
  predecessor. Genesis is the predecessor of the first row of an empty table only; a head
  that is not a hash raises :class:`EventChainHeadError` (P-254).

Navigation
----------
What it is:   The database ``EventSink`` and the readers the SSE route and the worker use.
What it does: Writes every ``StepEvent`` as one ``events`` row and never raises into the run
              (drops are counted and logged); chains every new row of the table, from any
              writer, in that writer's flush; reads a trace's events in ``seq`` order with a
              resume cursor; allocates the next ``seq`` for out-of-band system events under
              the same write lock the ledger uses, and lends that lock to a caller that
              reads a trace's ``seq`` itself (``lock_event_writes``: the server's audited
              commit, ``append_system_event`` and the unsealed-override record) before any
              ``users`` row the transaction writes (P-786); chains every
              new row in its writer's own flush under that same lock; walks the whole chain
              and reads its head; and, for the page that reads it often, walks only the events
              written since its last clean walk between bounded full walks
              (``EventChainVerifier``).
How:          ``DbEventSink.emit`` = one row, one commit; ``emit_many`` = one transaction
              with a per-row fallback; ``read_events`` = ``seq > after`` ordered by
              ``(seq, id)`` with a clamped limit; ``append_event`` = lock → ``max(seq)+1`` →
              insert; ``lock_event_writes`` is that lock, for a writer adding an event to
              its own caller's transaction and for the chain's flush hook alike;
              ``_chain_new_events`` (``before_flush``) = lock → head → hash each new row in
              insertion order; ``verify_events`` = keyset pages by id → ``walk_event_chain``;
              ``EventChainVerifier`` = the last clean walk's (id, head, count) re-checked, then
              a walk resumed from it; ``events_head`` = count + last ``row_hash``;
              ``append_event_checked`` = lock → decide the payload → insert, raising instead
              of dropping (the registered readings of ADR-0026 item 2).
Layer:        store — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/observability/events.py (``StepEvent`` / ``Emitter`` — the envelope
              and the sequence assigner), src/crb/store/models.py (the ``Event`` columns),
              src/crb/store/jobs.py (writes reclaim / cancel notes through ``append_event``),
              src/crb/server/worker.py (installs the sink and resumes from ``last_seq``),
              src/crb/server/routes/runs.py (serves ``read_events`` over SSE;
              ``append_system_event`` takes ``lock_event_writes``),
              src/crb/core/event_chain.py (the hash rule and the walk),
              src/crb/server/routes/ledger.py (``/ledger/verify`` serves the walk and head)
Tested by:    tests/test_store_events.py, tests/test_store_events_chain.py,
              tests/test_store_jobs.py, tests/test_server_routes_runs.py,
              tests/test_advisory_lock_owners.py
Touch when:   never for a new repository; when ``StepEvent`` gains a field (a migration and
              both mappers change together); when a new out-of-band system action is
              introduced (use ``append_event``, never a raw insert — the ``seq`` cursor must
              stay monotonic per trace).
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Column, func, select, text
from sqlalchemy import event as sa_event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from crb.core.event_chain import GENESIS_HASH, EventChainReport, event_row_hash, walk_event_chain
from crb.observability.events import StepEvent, StepStatus
from crb.store.models import Event, User

_LOG = logging.getLogger(__name__)

DEFAULT_READ_LIMIT = 500
MAX_READ_LIMIT = 5000


def _to_model(e: StepEvent) -> Event:
    # Field-by-field on purpose (no **asdict): the envelope and the row must stay explicit
    # so a new StepEvent field is a visible decision here, not a silent JSON spill.
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


def lock_event_writes(s: Session) -> None:
    """Hold the ``events`` write lock for the rest of ``s``'s transaction, so the trace's
    last ``seq`` read after this call is still the last when the transaction commits.

    Every out-of-band writer takes it before it reads ``max(seq)``: :func:`append_event`,
    the sink's re-allocation, the server's ``append_system_event`` — which adds its event
    to a CALLER's transaction and so may already have written there (EI-1, DL-080) — and
    the server's audited commit, ``commit_audited`` (P-196) — and the chain's flush hook,
    which must read the head under it (ADR-0029). It is the one helper for this
    lock: a second copy is refused by ``tests/test_advisory_lock_owners.py`` (P-224).
    SQLite: ``BEGIN IMMEDIATE``; when a transaction is already open it cannot run, and an
    open transaction proves nothing (pysqlite opens one at the first write, which holds the
    write lock, but a caller's deferred ``BEGIN`` holds none), so a zero-row write takes the
    database's write lock explicitly — a no-op when the transaction has written, a wait (or
    "database is locked") when it has not — rather than swallow the refused ``BEGIN
    IMMEDIATE`` and carry on (P-429's rule: no lock helper carries on after that error).
    SQLite does take the write lock before it refuses (``OP_Transaction`` runs before
    ``OP_AutoCommit``'s error), so a swallowing helper held it by accident of that order;
    the explicit write removes the dependence on it.
    PostgreSQL: a transaction-scoped advisory lock (id 7332 — one id per table, see
    ``crb.store.jobs``), re-entrant within the transaction. Other dialects: no-op."""
    refuse_events_after_users_rows(s)
    dialect = s.get_bind().dialect.name
    # no autoflush on ANY dialect: a pending ORM write flushed by the lock's own statement
    # would run before the lock — on SQLite it would open the transaction first, on
    # PostgreSQL a pending ``UPDATE users`` would lock its row BEFORE the events lock, while
    # a sign-in holds the events lock and then writes that row: a deadlock. Unflushed, it
    # is written later, under the lock (the users ROW ranks after the events lock, P-786).
    with s.no_autoflush:
        if dialect == "sqlite":
            driver = s.connection().connection.driver_connection
            if getattr(driver, "in_transaction", False):
                s.execute(text("DELETE FROM events WHERE 0"))
            else:
                s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7332)"))  # events
    write_locks_held(s).add(EVENTS_LOCK)


#: A row lock on an existing ``users`` row, as :func:`write_locks_held` records it: a flush
#: that updated or deleted one. It ranks AFTER the events lock (the sign-in holds events,
#: then writes its row), so asking for the events lock while holding it is refused (P-786).
USERS_ROWS = "users rows"


def _note_users_rows(session: Session, _flush_context: Any) -> None:
    """``after_flush``: record that this transaction now holds a ``users`` row lock."""
    if any(isinstance(o, User) for o in session.deleted) or any(
        isinstance(o, User) and session.is_modified(o) for o in session.dirty
    ):
        write_locks_held(session).add(USERS_ROWS)


if not sa_event.contains(Session, "after_flush", _note_users_rows):
    sa_event.listen(Session, "after_flush", _note_users_rows)


def refuse_events_after_users_rows(s: Session) -> None:
    """Raise :class:`LockOrderError` when ``s`` already wrote an existing ``users`` row and
    now asks for the events lock it does not yet hold: the order every sign-in uses is the
    events lock, then the row, so the other order deadlocks on PostgreSQL."""
    held = write_locks_held(s)
    if USERS_ROWS in held and EVENTS_LOCK not in held:
        raise LockOrderError(
            "the events write lock was asked for after a users row was written in one "
            "transaction; write the row after the lock (leave it unflushed), or an admin act "
            "and a sign-in of the same account deadlock on PostgreSQL"
        )


#: The ``events`` write lock's name in :func:`write_locks_held`.
EVENTS_LOCK = "events"
#: The ``users`` lock's name (``crb.server.auth.lock_users_table``).
USERS_LOCK = "users"
#: Locks a transaction must take BEFORE the ``events`` lock, never after it (P-227): every
#: admin act holds ``users`` and then records its event, so a path that holds ``events``
#: and then asks for ``users`` deadlocks against it on PostgreSQL.
TAKEN_BEFORE_EVENTS = frozenset({USERS_LOCK})

_LOCKS_KEY = "crb.write_locks_held"


class LockOrderError(RuntimeError):
    """A write lock was asked for after a lock that must come after it (P-227)."""


def write_locks_held(s: Session) -> set[str]:
    """The names of the write locks ``s``'s CURRENT transaction holds, as the helpers that
    take them record them. A new transaction starts with none: the set is keyed on the
    transaction object, so a commit or a rollback forgets it."""
    tx = s.get_transaction()
    held = s.info.get(_LOCKS_KEY)
    if held is None or held[0] is not tx:
        held = (tx, set())
        s.info[_LOCKS_KEY] = held
    return set() if tx is None else held[1]


def refuse_after_events_lock(s: Session, name: str) -> None:
    """Raise :class:`LockOrderError` when ``s`` already holds the ``events`` write lock and
    asks for ``name``, a lock in :data:`TAKEN_BEFORE_EVENTS` it does not yet hold. Re-taking
    a lock the transaction holds is never an inversion. Called by the helper that takes
    ``name`` BEFORE it waits for it, so the inverted order fails at once on every dialect
    instead of deadlocking on PostgreSQL."""
    held = write_locks_held(s)
    if name in TAKEN_BEFORE_EVENTS and EVENTS_LOCK in held and name not in held:
        raise LockOrderError(
            f"the {name} lock was asked for after the events write lock in one transaction; "
            f"take the {name} lock first (commit_audited's `before=`), or two writers "
            "deadlock on PostgreSQL (P-227)"
        )


# ---------------------------------------------------------------------------
# The chain (ADR-0029): every new ``events`` row is chained in its writer's own flush
# ---------------------------------------------------------------------------

#: The columns a row's hash covers, by attribute name (everything but the id and the chain).
_HASHED_COLUMNS: dict[str, Any] = {
    c.key: c for c in Event.__table__.columns if c.key not in ("id", "prev_hash", "row_hash")
}


def _take_chain_lock(session: Session) -> None:
    """Hold the write lock before the head is read, so two writers cannot read one head.

    The one helper for the ``events`` lock, :func:`lock_event_writes`, re-entrant within the
    transaction on PostgreSQL; on SQLite, inside an open transaction, it takes the database's
    write lock explicitly (a zero-row write, P-429), so the head it reads is the latest. A
    second copy of the lock here would be the class P-224 closed."""
    lock_event_writes(session)


def _column_default(col: Column[Any]) -> Any:
    """The value the INSERT would give an unset column — applied before hashing, so the row
    hashes as it will be stored (a Python-side default is otherwise filled in only when the
    statement is compiled, after this hook)."""
    d = col.default
    if d is None:
        return None
    if getattr(d, "is_scalar", False):
        return getattr(d, "arg", None)
    if getattr(d, "is_callable", False):
        return d.arg(None)  # type: ignore[attr-defined]
    return None


def _stored_values(obj: Event) -> dict[str, Any]:
    for key, col in _HASHED_COLUMNS.items():
        if getattr(obj, key) is None:
            default = _column_default(col)
            if default is not None:
                setattr(obj, key, default)
    return {key: getattr(obj, key) for key in _HASHED_COLUMNS}


class EventChainHeadError(RuntimeError):
    """The ``events`` table has rows but its last ``row_hash`` is not a SHA-256: a row reached
    the table without the chain (only possible with the CHECK constraint lifted). Nothing
    more is chained onto it — the operator restores the table or re-chains it (ADR-0029)."""


_HEX = frozenset("0123456789abcdef")


def _predecessor(head: str | None) -> str:
    """The ``prev_hash`` of the next row: genesis for an EMPTY table only (``head`` is
    ``None``); otherwise the head, which must be a SHA-256 in hex (P-254 — a head of ``''``
    read as genesis once made every later write collide with the first row)."""
    if head is None:
        return GENESIS_HASH
    if len(head) != 64 or not set(head) <= _HEX:
        raise EventChainHeadError(
            f"the events chain's head {head!r} is not a SHA-256: a row was written without "
            "the chain; verify the audit trail (crb ledger verify --store) before writing more"
        )
    return head


def _chain_new_events(session: Session, _flush_context: Any, _instances: Any) -> None:
    """``before_flush``: give every pending ``Event`` its ``prev_hash`` and ``row_hash``,
    in insertion order, onto the table's head — whatever the writer set, so no writer can
    choose its own hashes and none can forget them."""
    new = [o for o in session.new if isinstance(o, Event)]
    if not new:
        return
    new.sort(key=lambda o: sa_inspect(o).insert_order or 0)
    _take_chain_lock(session)
    head = (
        session.connection()
        .execute(select(Event.row_hash).order_by(Event.id.desc()).limit(1))
        .scalar_one_or_none()
    )
    prev = _predecessor(head)
    for obj in new:
        obj.prev_hash = prev
        obj.row_hash = event_row_hash(_stored_values(obj), prev)
        prev = obj.row_hash


if not sa_event.contains(Session, "before_flush", _chain_new_events):
    sa_event.listen(Session, "before_flush", _chain_new_events)


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
        #: Events whose ``seq`` collided with a concurrent writer and were re-numbered.
        self.realloc = 0

    def emit(self, event: StepEvent) -> None:
        try:
            try:
                with self._factory() as s:
                    s.add(_to_model(event))
                    s.commit()
            except IntegrityError as exc:
                if "uq_events_trace_seq" not in str(exc) and "trace_id" not in str(exc):
                    raise
                # Another writer (an out-of-band ``append_event``) took this ``seq``:
                # re-allocate under the write lock so the resume cursor stays dense
                # instead of dropping the event (revision 0004, 2026-09-15).
                self._emit_reallocated(event)
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

    def _emit_reallocated(self, event: StepEvent) -> None:
        with self._factory() as s:
            lock_event_writes(s)
            nxt = (
                int(
                    s.execute(
                        select(func.max(Event.seq)).where(Event.trace_id == event.trace_id)
                    ).scalar_one_or_none()
                    or 0
                )
                + 1
            )
            m = _to_model(event)
            m.seq = nxt
            s.add(m)
            s.commit()
        self.realloc += 1

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
    lim = max(1, min(int(limit), MAX_READ_LIMIT))  # a caller cannot ask for the whole table
    with factory() as s:
        q = (
            select(Event)
            .where(Event.trace_id == trace_id, Event.seq > int(after_seq))
            .order_by(Event.seq, Event.id)
            .limit(lim)
        )
        return [_from_model(m) for m in s.execute(q).scalars()]


def events_of_action(factory: sessionmaker[Session], trace_id: str, action: str) -> list[StepEvent]:
    """Every event of one trace with this ``action``, ascending by ``seq`` — not clamped:
    a caller that sums them (a run's spend cap summing its test author's calls) needs all
    of them, and one action of one trace is a small set."""
    with factory() as s:
        q = (
            select(Event)
            .where(Event.trace_id == trace_id, Event.action == action)
            .order_by(Event.seq, Event.id)
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
    """How many events a trace holds (the run detail's counter)."""
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
    the write failed (logged, never raised). A malformed event (unknown stage)
    raises ``ValueError`` — that is a programming error, not an I/O failure.
    """
    # Validation (stage, redaction) happens here, OUTSIDE the guard: a malformed
    # event is a programming error and must surface; only I/O is swallowed below.
    template = StepEvent(
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
    )
    try:
        with factory() as s:
            lock_event_writes(s)
            nxt = (
                int(
                    s.execute(
                        select(func.max(Event.seq)).where(Event.trace_id == trace_id)
                    ).scalar_one_or_none()
                    or 0
                )
                + 1
            )
            ev = StepEvent.from_dict({**template.to_dict(), "seq": nxt})
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


# ---------------------------------------------------------------------------
# Verification and the head (F51, G-601)
# ---------------------------------------------------------------------------

VERIFY_BATCH = 1000


def _chain_rows(
    s: Session, batch: int = VERIFY_BATCH, *, after: int = 0
) -> Iterator[dict[str, Any]]:
    """Every ``events`` row with an id above ``after``, in id order as a plain mapping,
    keyset-paged."""
    last = after
    while True:
        chunk = list(
            s.execute(select(Event).where(Event.id > last).order_by(Event.id).limit(batch))
            .scalars()
            .all()
        )
        if not chunk:
            return
        for m in chunk:
            row = {key: getattr(m, key) for key in _HASHED_COLUMNS}
            row.update(id=m.id, prev_hash=m.prev_hash, row_hash=m.row_hash)
            yield row
        last = chunk[-1].id


def verify_events_in(s: Session) -> EventChainReport:
    """Walk the whole ``events`` chain on an open session (never raises on a break); the
    report is stamped with the time of this full walk."""
    return replace(walk_event_chain(_chain_rows(s)), full_walk_at=_utc_now())


def verify_events(factory: sessionmaker[Session]) -> EventChainReport:
    """Walk the whole ``events`` chain: an edited, a deleted or a moved row is reported by
    id. What it cannot see — rows cut from the end, a table replaced wholesale — is what the
    head recorded outside the store is for (docs/DEPLOYMENT.md §8)."""
    with factory() as s:
        return verify_events_in(s)


#: The longest a tail walk may lean on an earlier full walk: every ``/ledger/verify`` after
#: this re-hashes the whole chain again (P-257).
FULL_WALK_EVERY_S = 300.0


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class _Walked:
    """What the last clean walk covered: its last row id, that row's hash, the row count."""

    last_id: int
    head: str
    rows: int
    full_at: float
    full_at_iso: str


class EventChainVerifier:
    """The audit trail's walk for a page that is read often (P-257).

    A full walk re-hashes every row — the audit trail holds every step of every run, so it
    grows without bound. Between full walks (at most ``full_every_s`` apart, measured on
    ``clock``) this re-hashes only the rows appended since the last clean walk, starting
    from its head, and only after checking that the row it ended on still carries that
    hash and that the number of rows up to it is unchanged. Anything else — a first read,
    an expired full walk, ``full=True``, a changed prefix, a chain that was broken last
    time — walks in full. What a tail walk cannot see is an edit, underneath the triggers,
    to a row before the head that leaves the count and the head unchanged; the next full
    walk (``full_walk_at`` on every report says when the last one ran) finds it. One
    instance per process; thread-safe."""

    def __init__(
        self, *, full_every_s: float = FULL_WALK_EVERY_S, clock: Callable[[], float] | None = None
    ) -> None:
        self._every = float(full_every_s)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._walked: _Walked | None = None

    def verify(self, s: Session, *, full: bool = False) -> EventChainReport:
        with self._lock:
            now = self._clock()
            w = self._walked
            if w is not None and not full and now - w.full_at < self._every and self._holds(s, w):
                report = walk_event_chain(
                    _chain_rows(s, after=w.last_id), prev=w.head, verified=w.rows
                )
                report = replace(report, full_walk_at=w.full_at_iso)
                full_at, full_at_iso = w.full_at, w.full_at_iso
            else:
                report = verify_events_in(s)
                full_at, full_at_iso = now, report.full_walk_at
            self._walked = None
            if report.ok and report.rows:
                # the id of the row the walk ended on (``row_hash`` is unique), not max(id):
                # a row appended after the walk must be walked by the next read
                last_id = s.execute(
                    select(Event.id).where(Event.row_hash == report.head)
                ).scalar_one_or_none()
                if last_id is not None:
                    self._walked = _Walked(
                        int(last_id), report.head, report.rows, full_at, full_at_iso
                    )
            return report

    @staticmethod
    def _holds(s: Session, w: _Walked) -> bool:
        """The prefix the last walk covered is still there: the row it ended on still hashes,
        from its stored values, to the head it ended with, and the number of rows up to it
        is unchanged."""
        row = s.get(Event, w.last_id, populate_existing=True)
        if row is None or row.row_hash != w.head:
            return False
        try:
            if event_row_hash(_stored_values(row), row.prev_hash) != w.head:
                return False
        except (TypeError, ValueError):  # an unreadable row: the full walk names it (P-344)
            return False
        n = s.execute(select(func.count(Event.id)).where(Event.id <= w.last_id)).scalar_one()
        return int(n) == w.rows


def events_head(factory: sessionmaker[Session]) -> tuple[int, str]:
    """``(rows, head row_hash)`` of the ``events`` chain; ``(0, "")`` when it is empty."""
    with factory() as s:
        n = int(s.execute(select(func.count(Event.id))).scalar_one())
        head = s.execute(
            select(Event.row_hash).order_by(Event.id.desc()).limit(1)
        ).scalar_one_or_none()
    return n, head or ""


def append_event_checked(
    factory: sessionmaker[Session],
    *,
    trace_id: str,
    stage: str,
    action: str,
    build: Callable[[Session], dict[str, Any]],
    actor: str = "",
    repo: str = "",
) -> StepEvent:
    """Write one event whose payload is decided UNDER the write lock: ``build(session)``
    reads what it must (and may raise to refuse) and returns the payload; the event is
    inserted with the next ``seq`` in the same transaction. Unlike :func:`append_event`
    nothing is swallowed — a record that decides something (a registered reading, whose
    budget two concurrent writers must not both spend) is written or the caller hears why."""
    with factory() as s:
        lock_event_writes(s)
        payload = build(s)
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
            status=StepStatus.OK,
            actor=actor,
            repo=repo,
            payload=dict(payload),
            seq=nxt,
        )
        s.add(_to_model(ev))
        s.commit()
        return ev


__all__ = [
    "DEFAULT_READ_LIMIT",
    "EVENTS_LOCK",
    "FULL_WALK_EVERY_S",
    "MAX_READ_LIMIT",
    "TAKEN_BEFORE_EVENTS",
    "USERS_LOCK",
    "DbEventSink",
    "EventChainHeadError",
    "EventChainVerifier",
    "LockOrderError",
    "append_event",
    "append_event_checked",
    "count_events",
    "events_head",
    "events_of_action",
    "last_seq",
    "lock_event_writes",
    "read_events",
    "refuse_after_events_lock",
    "verify_events",
    "verify_events_in",
    "write_locks_held",
]
