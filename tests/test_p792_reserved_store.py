"""The database holds one reading reservation per (reading, arm, commit) — P-792, C19 and C1.

A reserved reading spends one commit per arm once: the reserver checks under the events lock
that no reservation exists for (reading, arm, commit) before it writes one. This suite pins
the backstop behind that check — revision 0018's partial unique index
``uq_events_reading_reserved`` on ``events(trace_id, step_id, task_id) WHERE action =
'reading.reserved'`` — and the one place its refusal is named: ``append_event_checked``
raises :class:`crb.store.events.ReservationExists` for that violation and re-raises every
other ``IntegrityError`` unchanged.

A reserved attempt that was settled — its run reclaimed, finished, or claimed by another
worker — must never land its row after the reading has read the commit as a miss (C1, the
zombie half of the enumeration's kill probe). The suite pins the guard that refuses it:
``DbLedger.append(row, guard=claim_guard(run, worker, claim))`` raises
:class:`crb.store.ledger.AttemptSettled` and writes nothing unless the run is still running
on that worker and claim, the race against a reclaim on PostgreSQL, and the one lock order
the guard depends on: the grades or events lock first, a ``runs`` row lock after.

Navigation
----------
What it is:   The store suite for a reading's reservations: the partial unique index, the
              error the locked writer maps its violation to, revision 0018's up and down, the
              claim guard on a reserved attempt's row, and the lock-order ratchet behind it.
What it does: Pins that a second ``reading.reserved`` row for one (trace, arm, commit) is
              refused by the database, for any writer, while another arm, another commit,
              another reading or another action with the same triple is stored (the index is
              partial, so a trace's ordinary events never collide on it); that
              ``append_event_checked`` turns that refusal into ``ReservationExists`` and leaves
              one row, an intact chain and the next ``seq`` free, while an ``IntegrityError``
              on any other constraint reaches the caller unchanged; that revision 0018
              creates the index from 0017, drops it on downgrade and creates it again; that a
              guarded append raises ``AttemptSettled`` with no row for a reclaimed (even when
              claimed back by the same worker), terminal, foreign, queued or unknown run and
              lands for the current claim; that on PostgreSQL a reclaim racing the guard
              either waits for the row's commit or is seen by the guard, never a row after a
              settled, no-row read; and that no function under src/crb asks for the grades
              or events lock while it holds a ``runs`` row lock.
How:          The shared ``backend`` fixture (SQLite always, PostgreSQL when
              ``CRB_TEST_POSTGRES_URL`` is set); plain ORM adds for the raw duplicates (the
              flush hook chains them); Alembic ``upgrade`` / ``downgrade`` on the backend's
              URL for the revision; a ``JobQueue`` claim and ``reclaim_stale(0.0)`` for the
              guard; two threads paused on ``threading.Event`` (inside the guard, or in the
              reclaim's ``after_flush``) with ``pg_blocking_pids`` naming who waits on whom
              for the race; an ``ast`` walk of every function's statements, branch by branch,
              for the lock order, proven on a planted tree.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (the ``Event`` index),
              src/crb/store/migrations/versions/v0018_reading_reservations.py (the revision),
              src/crb/store/events.py (``append_event_checked``, ``ReservationExists``),
              src/crb/core/reading.py (``READING_RESERVED_ACTION``),
              src/crb/store/ledger.py (``DbLedger.append``'s guard, ``AttemptSettled``),
              src/crb/store/jobs.py (``claim_guard``, ``reclaim_stale``),
              tests/test_store_migrate.py (head parity and drift with the partial index),
              tests/test_advisory_lock_owners.py (one owner per lock id; this suite adds
              their order), tests/conftest_store.py (the backends)
Tested by:    tests/test_p792_reserved_store.py
Touch when:   never for a new repository; the reservation's key or action changes (a new
              revision, never an edit of 0018), or the locked writer's error mapping changes;
              the claim guard's rule changes; a new helper takes the grades or events lock
              (add it to ``_TAKES_LOCK``).
"""

from __future__ import annotations

import ast
import datetime as dt
import re
import textwrap
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crb.core.reading import READING_RESERVED_ACTION
from crb.store import init_db, migrate
from crb.store.events import ReservationExists, append_event_checked, verify_events
from crb.store.jobs import (
    RECLAIMS_KEY,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobQueue,
    claim_guard,
)
from crb.store.ledger import AttemptSettled, DbLedger
from crb.store.models import Event, Repo, Run

try:
    from tests.conftest_store import SHA, Backend, backend, grade_row, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import SHA, Backend, backend, grade_row, pg_schema  # noqa: F401

#: The index revision 0018 adds and the predicate each dialect reflects it with.
INDEX = "uq_events_reading_reserved"
WHERE = {
    "sqlite": "action = 'reading.reserved'",
    "postgresql": "((action)::text = 'reading.reserved'::text)",
}
READING = "rdg_" + "a" * 24  # a reading id: 28 characters, inside ``trace_id``'s 32
OTHER_SHA = "b" * 40


@pytest.fixture
def db(backend: Backend) -> Backend:
    init_db(backend.engine)
    return backend


def _add(
    b: Backend,
    *,
    seq: int,
    step_id: str = "S1",
    task_id: str = SHA,
    action: str = READING_RESERVED_ACTION,
    trace_id: str = READING,
) -> None:
    """One event row through a plain ORM add — the writer that knows nothing of the
    reservation check, so only the database can refuse its duplicate."""
    with b.factory() as s:
        s.add(
            Event(
                event_id=uuid.uuid4().hex,
                trace_id=trace_id,
                seq=seq,
                timestamp="2026-10-11T10:00:00+00:00",
                stage="system",
                action=action,
                status="ok",
                step_id=step_id,
                task_id=task_id,
            )
        )
        s.commit()


def _rows(b: Backend, action: str = READING_RESERVED_ACTION) -> list[tuple[str, str, str]]:
    with b.factory() as s:
        return [
            (r.trace_id, r.step_id, r.task_id)
            for r in s.execute(
                select(Event).where(Event.action == action).order_by(Event.id)
            ).scalars()
        ]


def _violated(exc: IntegrityError) -> str:
    """What the driver says was violated: PostgreSQL names the constraint, SQLite the
    columns."""
    name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return str(name) if name else str(exc.orig)


def test_p792_index_refuses_duplicate_insert(db: Backend) -> None:
    """C19 / C1 (P-792): a second reservation of one commit on one arm of one reading is
    refused by the database itself — the backstop for a writer that never ran the in-lock
    check — and the refusal names the reservation index. The index is PARTIAL: another
    arm, another commit, another reading, and any other action on the same triple (a
    trace's ordinary events, which share ``step_id`` and ``task_id`` all the time) are
    stored, so a full unique index in its place would be a defect, not a stricter one."""
    _add(db, seq=1)
    with pytest.raises(IntegrityError) as caught:
        _add(db, seq=2)  # same (reading, arm, commit), a fresh seq: only the index refuses it
    expected = (
        INDEX
        if db.dialect == "postgresql"
        else "UNIQUE constraint failed: events.trace_id, events.step_id, events.task_id"
    )
    assert _violated(caught.value) == expected
    assert _rows(db) == [(READING, "S1", SHA)]

    _add(db, seq=3, step_id="A0+L")  # another arm of the same commit
    _add(db, seq=4, task_id=OTHER_SHA)  # another commit on the same arm
    _add(db, seq=1, trace_id="rdg_" + "c" * 24)  # another reading's reservation of it
    _add(db, seq=5, action="reading.registered")  # another action on the same triple...
    _add(db, seq=6, action="reading.registered")  # ...twice: the predicate leaves it free
    assert _rows(db) == [
        (READING, "S1", SHA),
        (READING, "A0+L", SHA),
        (READING, "S1", OTHER_SHA),
        ("rdg_" + "c" * 24, "S1", SHA),
    ]
    assert len(_rows(db, "reading.registered")) == 2
    report = verify_events(db.factory)  # the refused insert left no gap in the chain
    assert report.ok and report.rows == 6, report.detail


def _reserve(
    b: Backend,
    built: list[str],
    *,
    step_id: str = "S1",
    task_id: str = SHA,
    action: str = READING_RESERVED_ACTION,
) -> Any:
    def build(_s: object) -> dict[str, Any]:
        built.append(step_id)
        return {"arm": step_id}

    return append_event_checked(
        b.factory,
        trace_id=READING,
        stage="system",
        action=action,
        build=build,
        actor="worker-1",
        repo="r1",
        task_id=task_id,
        step_id=step_id,
    )


def test_p792_reservation_exists_maps_the_index_violation(db: Backend) -> None:
    """C1 (P-792): the locked writer names the backstop's refusal. A duplicate reservation
    that got past ``build`` (here ``build`` checks nothing, as a reserver with a defect in
    its check would) raises ``ReservationExists`` naming the reading, arm and commit —
    never a bare ``IntegrityError`` a caller would have to parse — and the database is left
    with one reservation, an intact chain and the next ``seq`` unspent. Every other
    integrity failure is not a reservation and is re-raised unchanged: an ordinary action,
    and a reservation that broke a different constraint."""
    built: list[str] = []
    first = _reserve(db, built)
    assert (first.seq, first.step_id, first.task_id) == (1, "S1", SHA)
    with pytest.raises(ReservationExists) as caught:
        _reserve(db, built)
    exc = caught.value
    assert (exc.trace_id, exc.step_id, exc.task_id) == (READING, "S1", SHA)
    assert isinstance(exc.__cause__, IntegrityError)
    assert READING in str(exc) and "S1" in str(exc) and SHA in str(exc)
    assert built == ["S1", "S1"]  # the duplicate reached the database: the index refused it
    assert _rows(db) == [(READING, "S1", SHA)]
    assert _reserve(db, built, step_id="A0+L").seq == 2  # the refused write spent no seq
    report = verify_events(db.factory)
    assert report.ok and report.rows == 2, report.detail

    # another constraint, on any action: an IntegrityError the caller sees as it was raised.
    # The probe index refuses a second (repo, actor, arm); neither write below is a second
    # reservation of (reading, arm, commit), so only the probe index can refuse it
    with db.engine.begin() as c:
        c.execute(text("CREATE UNIQUE INDEX uq_probe_events_arm ON events (repo, actor, step_id)"))
    probe = (
        "uq_probe_events_arm"
        if db.dialect == "postgresql"
        else "UNIQUE constraint failed: events.repo, events.actor, events.step_id"
    )
    for action, task_id in (("reading.note", SHA), (READING_RESERVED_ACTION, OTHER_SHA)):
        with pytest.raises(IntegrityError) as other:
            _reserve(db, built, task_id=task_id, action=action)
        assert type(other.value) is IntegrityError and _violated(other.value) == probe
    assert _rows(db) == [(READING, "S1", SHA), (READING, "A0+L", SHA)]
    assert _rows(db, "reading.note") == []


def _reserved_index(engine: Engine) -> dict[str, Any] | None:
    for ix in inspect(engine).get_indexes("events"):
        if ix["name"] == INDEX:
            return dict(ix)
    return None


def _downgrade(b: Backend, revision: str) -> None:
    cfg = migrate.alembic_config(b.url)
    with b.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, revision)


def test_v0018_upgrade_and_downgrade(backend: Backend) -> None:
    """Revision 0018 adds the reservation index to a 0017 store — unique, on (trace, arm,
    commit), partial on the reserved action, on SQLite and PostgreSQL alike — drops it on
    downgrade without touching a row, and adds it again on a second upgrade over the rows
    the first one let in."""
    migrate.upgrade(backend.url, revision="0017")
    assert migrate.current(backend.url) == "0017"
    assert _reserved_index(backend.engine) is None

    migrate.upgrade(backend.url, revision="0018")
    assert migrate.current(backend.url) == "0018"
    ix = _reserved_index(backend.engine)
    assert ix is not None
    assert ix["column_names"] == ["trace_id", "step_id", "task_id"] and bool(ix["unique"])
    where = ix["dialect_options"][f"{backend.dialect}_where"]
    assert str(where) == WHERE[backend.dialect]
    _add(backend, seq=1)
    with pytest.raises(IntegrityError):
        _add(backend, seq=2)

    _downgrade(backend, "0017")
    assert migrate.current(backend.url) == "0017"
    assert _reserved_index(backend.engine) is None
    assert _rows(backend) == [(READING, "S1", SHA)]  # a downgrade drops the index, no row

    migrate.upgrade(backend.url, revision="0018")
    assert migrate.current(backend.url) == "0018"
    again = _reserved_index(backend.engine)
    assert again is not None
    assert str(again["dialect_options"][f"{backend.dialect}_where"]) == WHERE[backend.dialect]
    assert _rows(backend) == [(READING, "S1", SHA)]


# --- C1: the claim guard on a reserved attempt's row ----------------------------------------

WORKER = "worker-1"


@pytest.fixture
def queue(db: Backend) -> JobQueue:
    with db.factory() as s:
        s.add(Repo(name="r1", language="python", runner="pytest", clone_path="/x", config_json={}))
        s.commit()
    return JobQueue(db.factory)


def _claimed(queue: JobQueue, worker: str = WORKER) -> Run:
    """A fresh run, claimed by ``worker`` (the only queued run, so FIFO cannot pick another)."""
    run = queue.enqueue(Run(repo="r1", kind="replay"))
    got = queue.claim_next(worker)
    assert got is not None and got.id == run.id and got.status == STATUS_RUNNING
    return got


def _claim(queue: JobQueue, run_id: str) -> int:
    """The run's claim counter: the queue's ``reclaims``, moved by every reclaim."""
    run = queue.get(run_id)
    assert run is not None
    return int((run.counts_json or {}).get(RECLAIMS_KEY, 0))


def _reclaim(queue: JobQueue) -> list[str]:
    """Reclaim every running run, as the reaper does once a heartbeat is stale."""
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=600)
    return [r.id for r in queue.reclaim_stale(120, now=later)]


def test_p792_claim_guard_refuses_a_reclaimed_attempt(queue: JobQueue, db: Backend) -> None:
    """C1 (P-792): an attempt whose run was reclaimed is settled — the reaper read it as a
    miss and the commit goes back to the queue — so its late row is refused with
    ``AttemptSettled`` and nothing is written. The claim, not the worker id, names the
    attempt: the same worker claiming the run back is a new attempt, and the old one's row is
    still refused while the new claim's lands."""
    ledger = DbLedger(db.factory)
    run = _claimed(queue)
    assert _claim(queue, run.id) == 0
    assert _reclaim(queue) == [run.id]
    assert _claim(queue, run.id) == 1
    with pytest.raises(AttemptSettled, match=run.id[:8]):
        ledger.append(grade_row(run_id=run.id), guard=claim_guard(run.id, WORKER, 0))
    assert ledger.count() == 0

    again = queue.claim_next(WORKER)  # the same worker id takes the run back
    assert again is not None and again.id == run.id
    assert (again.status, again.worker_id) == (STATUS_RUNNING, WORKER)
    with pytest.raises(AttemptSettled, match="claim 0"):
        ledger.append(grade_row(run_id=run.id), guard=claim_guard(run.id, WORKER, 0))
    assert ledger.count() == 0

    landed = ledger.append(grade_row(run_id=run.id), guard=claim_guard(run.id, WORKER, 1))
    assert [r.row_hash for r in ledger.rows()] == [landed.row_hash]
    assert ledger.verify() == 1


def test_p792_claim_guard_refuses_a_terminal_or_foreign_run(queue: JobQueue, db: Backend) -> None:
    """C1 (P-792): the guard admits a row only for a run that is running, on this worker,
    under this claim. Another worker's run, a finished run (succeeded, failed or cancelled), a
    queued run nobody claimed and an unknown run are each refused with ``AttemptSettled``
    and no row; the owner's own guard on the same run admits its row."""
    ledger = DbLedger(db.factory)
    foreign = _claimed(queue, "worker-2")
    with pytest.raises(AttemptSettled, match="worker-2"):
        ledger.append(grade_row(run_id=foreign.id), guard=claim_guard(foreign.id, WORKER, 0))
    assert ledger.count() == 0

    for status in (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED):
        run = _claimed(queue)
        queue.finish(run.id, status, worker_id=WORKER)
        with pytest.raises(AttemptSettled, match=status):
            ledger.append(grade_row(run_id=run.id), guard=claim_guard(run.id, WORKER, 0))
        assert ledger.count() == 0, status

    queued = queue.enqueue(Run(repo="r1", kind="replay"))  # last: no claim_next follows it
    with pytest.raises(AttemptSettled, match="queued"):
        ledger.append(grade_row(run_id=queued.id), guard=claim_guard(queued.id, WORKER, 0))
    unknown = "f" * 32
    with pytest.raises(AttemptSettled, match="does not exist"):
        ledger.append(grade_row(run_id=unknown), guard=claim_guard(unknown, WORKER, 0))
    assert ledger.count() == 0

    ledger.append(grade_row(run_id=foreign.id), guard=claim_guard(foreign.id, "worker-2", 0))
    assert ledger.count() == 1 and ledger.verify() == 1


def test_p792_claim_guard_admits_the_current_claim(queue: JobQueue, db: Backend) -> None:
    """C1 (P-792): the guard refuses only a settled attempt. The owner's current claim lands
    its row, chained as an unguarded append would be; the next owner after a reclaim is the
    current claim and lands its own; and a cancel request does not settle the attempt in
    flight (cancellation is cooperative: the worker stops between tasks, so the task it is
    on still records its row)."""
    ledger = DbLedger(db.factory)
    run = _claimed(queue)
    first = ledger.append(grade_row(run_id=run.id), guard=claim_guard(run.id, WORKER, 0))
    assert first.prev_hash != "" and ledger.count() == 1

    assert _reclaim(queue) == [run.id]
    nxt = queue.claim_next("worker-2")
    assert nxt is not None and nxt.id == run.id
    second = ledger.append(
        grade_row(run_id=run.id, task_id=OTHER_SHA), guard=claim_guard(run.id, "worker-2", 1)
    )
    assert second.prev_hash == first.row_hash

    asked = queue.request_cancel(run.id, actor="operator")
    assert asked is not None and asked.status == STATUS_RUNNING and asked.cancel_requested
    third = ledger.append(
        grade_row(run_id=run.id, task_id="c" * 40), guard=claim_guard(run.id, "worker-2", 1)
    )
    assert third.prev_hash == second.row_hash
    assert [r.row_hash for r in ledger.rows()] == [first.row_hash, second.row_hash, third.row_hash]
    assert ledger.verify() == 3


class _Thread(threading.Thread):
    """A thread that keeps what its call returned or raised, for the test to read."""

    def __init__(self, name: str, call: Callable[[], Any]) -> None:
        super().__init__(name=name, daemon=True)
        self._call = call
        self.result: Any = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.result = self._call()
        except BaseException as exc:  # the test asserts on it
            self.error = exc


def _pid(s: Session) -> int:
    return int(s.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar_one())


def _blocked_by(b: Backend, holder: int) -> set[int]:
    """The PostgreSQL backends waiting on a lock ``holder`` holds (a fresh connection, so
    the probe never waits itself)."""
    with b.engine.connect() as c:
        rows = c.execute(
            text("SELECT pid FROM pg_stat_activity WHERE :h = ANY(pg_blocking_pids(pid))"),
            {"h": holder},
        )
        return {int(r[0]) for r in rows}


def _until_blocked(b: Backend, holder: int, waiter: _Thread, pids: list[int] | None = None) -> bool:
    """Poll until a backend waits on a lock ``holder`` holds — the one in ``pids`` when it
    is given, any otherwise: ``False`` once ``waiter`` has finished without waiting (or after
    10 s)."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        blocked = _blocked_by(b, holder)
        if blocked and (pids is None or (bool(pids) and pids[0] in blocked)):
            return True
        if not waiter.is_alive():
            return False
        time.sleep(0.02)
    return False


def test_p792_guard_vs_reclaim_race(queue: JobQueue, db: Backend) -> None:
    """C1 (P-792) on PostgreSQL, the backend with concurrent writers: a reclaim racing the
    guard is serialised on the run's row, so the attempt is settled either before its row or
    after it, never a row after a settled, no-row read.

    Phase 1, the guard first: the attempt's guard holds the row (``FOR UPDATE``) and pauses;
    the reclaim must wait on it, so while it waits the run still reads running under claim 0
    with no row, the row lands, and only then is the run reclaimed. Without the row lock the
    reclaim commits under the paused guard, the run reads settled with no row, and the row
    the guard had already passed lands after it — the zombie.

    Phase 2, the reclaim first: the reclaim has written the run (its ``UPDATE`` flushed, not
    yet committed) and pauses; the guard must wait on it, and once the reclaim commits the
    guard re-reads the row (claim 2, queued) and refuses the attempt with no row."""
    if db.dialect != "postgresql":
        pytest.skip("the race needs concurrent writers: PostgreSQL (CRB_TEST_POSTGRES_URL)")
    ledger = DbLedger(db.factory)
    run = _claimed(queue)

    # phase 1 — the guard holds the row; the reclaim waits for its commit
    entered, release = threading.Event(), threading.Event()
    guard_pid: list[int] = []

    def paused_guard(s: Session) -> None:
        claim_guard(run.id, WORKER, 0)(s)
        guard_pid.append(_pid(s))
        entered.set()
        assert release.wait(20), "phase 1 was never released"

    attempt = _Thread(
        "attempt", lambda: ledger.append(grade_row(run_id=run.id), guard=paused_guard)
    )
    reaper = _Thread("reaper", lambda: _reclaim(queue))
    attempt.start()
    try:
        assert entered.wait(10), f"the append never ran its guard: {attempt.error!r}"
        reaper.start()
        waited = _until_blocked(db, guard_pid[0], reaper)
        unrowed = _claim(queue, run.id) == 1 and ledger.count() == 0  # read: settled, no row
    finally:
        release.set()
        attempt.join(20)
        if reaper.ident is not None:
            reaper.join(20)
    landed = ledger.count()
    assert not (unrowed and landed), "a row landed after the run was read settled with no row"
    assert waited, "the reclaim never waited on the guard's row lock"
    assert attempt.error is None and reaper.error is None, (attempt.error, reaper.error)
    assert landed == 1 and _claim(queue, run.id) == 1 and reaper.result == [run.id]

    # phase 2 — the reclaim holds the row; the guard waits, re-reads it and refuses
    again = queue.claim_next(WORKER)
    assert again is not None and again.id == run.id and _claim(queue, run.id) == 1
    flushed, go = threading.Event(), threading.Event()
    reaper_pid: list[int] = []
    late_pid: list[int] = []

    def hold(session: Session, _ctx: Any) -> None:
        # the reclaim's UPDATE has run, its commit has not: the run's row is held
        if threading.current_thread().name != "reclaimer" or flushed.is_set():
            return
        reaper_pid.append(_pid(session))
        flushed.set()
        assert go.wait(20), "phase 2 was never released"

    def late_guard(s: Session) -> None:
        late_pid.append(_pid(s))
        claim_guard(run.id, WORKER, 1)(s)

    sa_event.listen(db.factory, "after_flush", hold)
    reclaimer = _Thread("reclaimer", lambda: _reclaim(queue))
    late = _Thread(
        "late",
        lambda: ledger.append(grade_row(run_id=run.id, task_id=OTHER_SHA), guard=late_guard),
    )
    try:
        reclaimer.start()
        assert flushed.wait(10), f"the reclaim never flushed: {reclaimer.error!r}"
        late.start()
        blocked = _until_blocked(db, reaper_pid[0], late, late_pid)
    finally:
        go.set()
        reclaimer.join(20)
        if late.ident is not None:
            late.join(20)
        sa_event.remove(db.factory, "after_flush", hold)
    assert blocked, f"the guard never waited on the reclaim's row lock: {late.error!r}"
    assert isinstance(late.error, AttemptSettled), late.error
    assert reclaimer.error is None and reclaimer.result == [run.id]
    assert [r.task_id for r in ledger.rows()] == [SHA]  # the late row never landed
    assert _claim(queue, run.id) == 2 and ledger.verify() == 1


# --- the lock order the guard depends on ------------------------------------------------------
#
# The guard takes the grades lock (7331, ``DbLedger._lock``) and then the run's row
# (``FOR UPDATE``); the reservation takes the events lock (7332) and reads ``runs`` plainly.
# Both are safe only while nothing takes 7331 or 7332 while it holds a ``runs`` row lock: such
# a holder would wait on the guard's advisory lock while the guard waits on its row — a
# deadlock PostgreSQL breaks by killing one side when both are in one database session, and
# never detects (a hang) when the second wait is another session on the same thread. The walk
# below reads every function under src/crb, branch by branch, and fails on that order.

SRC = Path(__file__).resolve().parents[1] / "src" / "crb"

#: Calls that take the events (7332) or grades (7331) lock wherever they appear: the events
#: lock's helpers and the writers that take it, and an ``Event`` row (its flush hook takes the
#: events lock to chain it). Add a new taker here.
_TAKES_LOCK = frozenset(
    {
        "lock_event_writes",
        "_take_chain_lock",
        "append_event",
        "append_event_checked",
        "append_system_event",
        "Event",
    }
)
#: Ledger methods that take the grades lock: on a receiver that names a ledger, or on ``self``
#: inside ``DbLedger`` (another class's ``_lock`` is another table's lock).
_LEDGER_LOCKS = frozenset({"_lock", "append", "append_many", "import_rows"})
#: A ``with`` over one of these opens and closes a session or connection: its locks end there.
_SESSION_WITH = ("factory", "Session", "begin", "connect")
#: Raw SQL that locks a ``runs`` row.
_RAW_ROW_LOCK = re.compile(
    r"(?is)\bupdate\s+runs\b|\bfrom\s+runs\b.*\bfor\s+(no\s+key\s+)?update\b"
)

State = frozenset[int]  # the lines whose ``runs`` row lock may still be held at this point


@dataclass
class _Fn:
    where: str
    cls: str
    tainted: set[str]
    holds: set[int] = field(default_factory=set)
    found: set[tuple[int, str, int]] = field(default_factory=set)
    loops: list[tuple[list[State], list[State]]] = field(default_factory=list)


@dataclass(frozen=True)
class _Inversion:
    where: str
    line: int
    lock: str
    held_since: int

    def __str__(self) -> str:
        return (
            f"{self.where} line {self.line}: {self.lock} while the runs row locked at line "
            f"{self.held_since} may still be held"
        )


def _callee(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _mentions_run(node: ast.AST, tainted: set[str]) -> bool:
    return any(
        (isinstance(n, ast.Name) and (n.id == "Run" or n.id in tainted))
        or (isinstance(n, ast.Attribute) and n.attr == "Run")
        for n in ast.walk(node)
    )


def _tainted(fn: ast.AST) -> set[str]:
    """Names bound to a statement over ``runs`` (``q = select(Run)…``, ``q = q.where(…)``)."""
    names: set[str] = set()
    while True:
        before = len(names)
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
                if n.value is None or not _mentions_run(n.value, names):
                    continue
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                names |= {t.id for tg in targets for t in ast.walk(tg) if isinstance(t, ast.Name)}
        if len(names) == before:
            return names


def _holds(call: ast.Call, tainted: set[str]) -> bool:
    """Whether ``call`` locks a ``runs`` row until the transaction ends."""
    name, f = _callee(call), call.func
    if name == "with_for_update" and isinstance(f, ast.Attribute):
        return _mentions_run(f.value, tainted) or any(
            _mentions_run(k.value, tainted) for k in call.keywords
        )
    if name == "get" and any(k.arg == "with_for_update" for k in call.keywords):
        return bool(call.args) and _mentions_run(call.args[0], tainted)
    if name == "update":  # ``update(Run)``
        return bool(call.args) and isinstance(call.args[0], ast.Name) and call.args[0].id == "Run"
    if name in ("text", "exec_driver_sql") and call.args:
        sql = call.args[0]
        return isinstance(sql, ast.Constant) and bool(_RAW_ROW_LOCK.search(str(sql.value)))
    return name == "guard"  # ``DbLedger.append``'s guard: ``claim_guard``'s row lock


def _takes_lock(call: ast.Call, cls: str) -> str | None:
    """The grades or events lock ``call`` takes, by name, or ``None``."""
    name, f = _callee(call), call.func
    if name in _TAKES_LOCK:
        return name
    if name in _LEDGER_LOCKS and isinstance(f, ast.Attribute):
        receiver = ast.unparse(f.value)
        if "ledger" in receiver.lower() or (receiver == "self" and cls == "DbLedger"):
            return f"{receiver}.{name}"
    return None


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    """The calls in ``node`` in evaluation order — a call's receiver and arguments before the
    call — skipping a lambda's or a nested definition's body (it does not run here)."""
    if isinstance(node, ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return
    if isinstance(node, ast.Call):
        yield from _calls(node.func)
        for a in node.args:
            yield from _calls(a)
        for k in node.keywords:
            yield from _calls(k.value)
        yield node
        return
    if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp):
        for g in node.generators:
            yield from _calls(g)
        parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        for part in parts:
            yield from _calls(part)
        return
    for child in ast.iter_child_nodes(node):
        yield from _calls(child)


def _join(*states: State | None) -> State | None:
    live = [s for s in states if s is not None]
    return frozenset().union(*live) if live else None


def _expr(fn: _Fn, node: ast.AST, state: State) -> State:
    for call in _calls(node):
        lock = _takes_lock(call, fn.cls)
        if lock and state:
            fn.found.add((call.lineno, lock, min(state)))
        if _holds(call, fn.tainted):
            fn.holds.add(call.lineno)
            state = state | {call.lineno}
        elif isinstance(call.func, ast.Attribute) and call.func.attr in ("commit", "rollback"):
            state = frozenset()
    return state


def _block(fn: _Fn, body: list[ast.stmt], state: State | None) -> State | None:
    for stmt in body:
        if state is None:
            return None  # nothing after a return, raise, break or continue runs
        state = _stmt(fn, stmt, state)
    return state


def _is_session(w: ast.With | ast.AsyncWith) -> bool:
    return any(any(k in ast.unparse(i.context_expr) for k in _SESSION_WITH) for i in w.items)


def _stmt(fn: _Fn, stmt: ast.stmt, state: State) -> State | None:
    """The state after ``stmt`` falls through (``None`` when it cannot)."""
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return state  # its body runs when called: analysed as a function of its own
    if isinstance(stmt, ast.Return | ast.Raise):
        _expr(fn, stmt, state)
        return None
    if isinstance(stmt, ast.Break | ast.Continue):
        if fn.loops:
            conts, brks = fn.loops[-1]
            (brks if isinstance(stmt, ast.Break) else conts).append(state)
        return None
    if isinstance(stmt, ast.If):
        state = _expr(fn, stmt.test, state)
        return _join(_block(fn, stmt.body, state), _block(fn, stmt.orelse, state))
    if isinstance(stmt, ast.For | ast.AsyncFor | ast.While):
        head = stmt.test if isinstance(stmt, ast.While) else stmt.iter
        entry: State = _expr(fn, head, state)
        breaks: list[State] = []
        for _ in range(2):  # twice: what one pass leaves held meets the next pass's calls
            fn.loops.append(([], []))
            out = _block(fn, stmt.body, entry)
            conts, brks = fn.loops.pop()
            breaks += brks
            entry = _join(entry, out, *conts) or entry
            if isinstance(stmt, ast.While):
                entry = _expr(fn, stmt.test, entry)
        return _join(_block(fn, stmt.orelse, entry), *breaks)
    if isinstance(stmt, ast.With | ast.AsyncWith):
        before = state
        for item in stmt.items:
            state = _expr(fn, item.context_expr, state)
        out = _block(fn, stmt.body, state)
        if out is None:
            return None
        return before if _is_session(stmt) else out  # a closed session holds nothing
    if isinstance(stmt, ast.Try | ast.TryStar):
        body_out = _block(fn, stmt.body, state)
        # a handler can start anywhere in the body: with every row lock the body can take
        taken = frozenset(c.lineno for b in stmt.body for c in _calls(b) if _holds(c, fn.tainted))
        handler_entry = (_join(state, body_out) or state) | taken
        outs = [None if body_out is None else _block(fn, stmt.orelse, body_out)]
        outs += [_block(fn, h.body, handler_entry) for h in stmt.handlers]
        merged = _join(*outs)
        if not stmt.finalbody:
            return merged
        final = _block(fn, stmt.finalbody, handler_entry if merged is None else merged)
        return None if merged is None else final
    if isinstance(stmt, ast.Match):
        state = _expr(fn, stmt.subject, state)
        return _join(state, *(_block(fn, c.body, state) for c in stmt.cases))
    return _expr(fn, stmt, state)


def _functions(
    node: ast.AST, prefix: str = "", cls: str = ""
) -> Iterator[tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function under ``node``: its qualified name and its nearest class."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _functions(child, f"{prefix}{child.name}.", child.name)
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield f"{prefix}{child.name}", cls, child
            yield from _functions(child, f"{prefix}{child.name}.", cls)
        else:
            yield from _functions(child, prefix, cls)


def _scan(root: Path) -> tuple[list[_Inversion], set[str]]:
    """The inversions under ``root`` (a ``crb`` package directory), and the functions that
    take a ``runs`` row lock at all (so a clean verdict is not a vacuous one)."""
    found: list[_Inversion] = []
    holders: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        module = ".".join(path.relative_to(root.parent).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for qual, cls, node in _functions(tree):
            fn = _Fn(where=f"{module}:{qual}", cls=cls, tainted=_tainted(node))
            _block(fn, node.body, frozenset())
            if fn.holds:
                holders.add(fn.where)
            found += [_Inversion(fn.where, *f) for f in sorted(fn.found)]
    return found, holders


def test_p792_lock_order_ratchet() -> None:
    """C1 (P-792): the guard's order is the only order. No function under src/crb takes the
    grades or events lock while it may hold a ``runs`` row lock — on any branch, on a loop's
    next pass, or in another session from inside the one that holds the row; the walk is
    not vacuous (``claim_next``'s ``SKIP LOCKED`` claim, ``claim_guard``'s ``FOR UPDATE`` and
    ``DbLedger.append``'s guard call are row locks it sees); and the two queue writes the walk
    cannot see — ``request_cancel`` and ``reclaim_stale`` write the run through the ORM, so
    their row lock is the flush's — commit and close their session before they write the
    event that records them, outside it."""
    found, holders = _scan(SRC)
    assert found == [], "\n".join(str(i) for i in found)
    expected = {
        "crb.store.jobs:JobQueue.claim_next",
        "crb.store.jobs:claim_guard.guard",
        "crb.store.ledger:DbLedger.append",
    }
    assert expected <= holders, sorted(holders)

    tree = ast.parse((SRC / "store" / "jobs.py").read_text(encoding="utf-8"))
    methods = {qual: node for qual, _cls, node in _functions(tree)}
    for name in ("JobQueue.request_cancel", "JobQueue.reclaim_stale"):
        withs = [w for w in ast.walk(methods[name]) if isinstance(w, ast.With) and _is_session(w)]
        inside = {id(n) for w in withs for n in ast.walk(w)}
        assert withs, f"{name} no longer opens its own session"
        locks = [
            ast.unparse(c)
            for w in withs
            for c in ast.walk(w)
            if isinstance(c, ast.Call) and _takes_lock(c, "JobQueue")
        ]
        assert locks == [], f"{name} takes a lock inside the session that writes the run"
        after = [
            c
            for c in ast.walk(methods[name])
            if isinstance(c, ast.Call) and _callee(c) == "append_event" and id(c) not in inside
        ]
        assert after, f"{name} no longer writes its event after the run's commit"


_PLANTED = """
    from sqlalchemy import select, text, update

    from crb.store.events import append_event, append_event_checked, lock_event_writes
    from crb.store.models import Run


    def bad_events_lock(s, run_id):
        s.execute(select(Run).where(Run.id == run_id).with_for_update())
        lock_event_writes(s)


    def bad_ledger_append(s, ledger, row):
        q = select(Run).where(Run.status == "running")
        s.execute(q.with_for_update()).scalars().all()
        ledger.append(row)


    def bad_get(s, run_id):
        run = s.get(Run, run_id, with_for_update=True)
        append_system_event(s, run)


    def bad_branch(s, done):
        s.execute(select(Run).with_for_update())
        if done:
            s.commit()
            return
        append_event_checked(s)


    def bad_loop(s, ids):
        for run_id in ids:
            lock_event_writes(s)
            s.execute(select(Run).where(Run.id == run_id).with_for_update())


    def bad_update(s):
        s.execute(update(Run).values(status="queued"))
        lock_event_writes(s)


    def bad_raw(s):
        s.execute(text("SELECT * FROM runs WHERE id = :i FOR UPDATE"), {"i": "x"})
        s.add(Event(trace_id="x"))


    def bad_other_session(factory, run_id):
        with factory() as s:
            s.execute(select(Run).where(Run.id == run_id).with_for_update())
            append_event(factory, trace_id=run_id)


    class DbLedger:
        def append(self, s, guard):
            self._lock(s)
            guard(s)

        def append_then_lock(self, s, guard):
            guard(s)
            self._lock(s)


    def ok_commit(s):
        s.execute(select(Run).with_for_update())
        s.commit()
        lock_event_writes(s)


    def ok_after_session(factory):
        with factory() as s:
            s.execute(select(Run).with_for_update())
        lock_event_writes(factory)


    def ok_list_append(s, touched):
        s.execute(select(Run).with_for_update())
        touched.append(1)
        s.commit()


    class JobQueue:
        def claim(self, s):
            s.execute(select(Run).with_for_update())
            self._lock(s)
"""


def test_p792_lock_order_ratchet_flags_a_planted_inversion(tmp_path: Path) -> None:
    """The walk behind the ratchet flags each planted inversion — a row lock taken by
    ``FOR UPDATE``, by ``get(…, with_for_update=…)``, by ``update(Run)``, by raw SQL and by
    a guard, then the events or grades lock taken after it straight on, after a branch that
    only commits on its way out, on a loop's next pass, and in another session — and none of
    the shapes that are safe: the lock first (``claim_guard``'s), a commit or a closed session
    between, a list's ``append``, another table's ``_lock``."""
    store = tmp_path / "crb" / "store"
    store.mkdir(parents=True)
    (store / "bad.py").write_text(textwrap.dedent(_PLANTED), encoding="utf-8")
    found, holders = _scan(tmp_path / "crb")
    assert {i.where.removeprefix("crb.store.bad:") for i in found} == {
        "bad_events_lock",
        "bad_ledger_append",
        "bad_get",
        "bad_branch",
        "bad_loop",
        "bad_update",
        "bad_raw",
        "bad_other_session",
        "DbLedger.append_then_lock",
    }, "\n".join(str(i) for i in found)
    safe = {"DbLedger.append", "ok_commit", "ok_after_session", "ok_list_append", "JobQueue.claim"}
    assert {f"crb.store.bad:{n}" for n in safe} <= holders  # each held a row: none vacuous
