"""The ``events`` table is hash-chained by construction, on SQLite and PostgreSQL (F51,
ADR-0029).

Every writer of the audit trail — the run's sink, the out-of-band ``append_event``, the
routes' ``append_system_event``, a plain ORM ``add`` — goes through one flush hook, so no
writer can forget the chain or choose its own hashes. These tests tamper with the table
underneath its triggers, the way a person with the database owner's role could, and expect
the walk to say where.

Navigation
----------
What it is:   The store suite for the chained ``events`` table: every writer chains, a
              tampered row is found, two writers cannot fork the chain.
What it does: Pins that rows written by each writer link from genesis and verify; that the
              hashes a caller puts on a row are replaced by the chain's; that an edited, a
              deleted and a reordered event (triggers dropped first) are each reported at
              the right id; that two threads writing at once leave one intact chain; that
              the database itself refuses a second row on the same predecessor and a row
              without the chain; that a head that is not a hash is a named error, never a
              second genesis; that the head served is the last row's hash; and that the
              page's verifier walks only new rows between full walks and walks in full when
              what it walked has changed or was broken.
How:          The shared ``backend`` fixture (SQLite always, PostgreSQL when
              ``CRB_TEST_POSTGRES_URL`` is set); raw SQL for the tampering; two threads over
              one session factory for the race.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/events.py (the flush hook, ``verify_events``, ``events_head``),
              src/crb/core/event_chain.py (the hash rule), tests/conftest_store.py (backends)
Tested by:    tests/test_store_events_chain.py
Touch when:   never for a new repository; a new writer of ``events`` is added (it must pass through
              a session flush), or the chain rule changes.
"""

from __future__ import annotations

import threading
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from crb.core.event_chain import GENESIS_HASH
from crb.observability.events import StepEvent
from crb.server.routes.runs import append_system_event
from crb.store import init_db
from crb.store.events import DbEventSink, append_event, events_head, verify_events
from crb.store.models import Event

try:
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


@pytest.fixture
def db(backend: Backend) -> Backend:
    init_db(backend.engine)
    return backend


def _drop_event_triggers(b: Backend) -> None:
    with b.engine.begin() as c:
        for name in ("events_no_update", "events_no_delete"):
            on = " ON events" if b.dialect == "postgresql" else ""
            c.execute(text(f"DROP TRIGGER IF EXISTS {name}{on}"))


def _write_through_every_writer(b: Backend) -> None:
    sink = DbEventSink(b.factory)
    sink.emit(StepEvent(trace_id="run1", stage="build", action="build.start", seq=1))
    sink.emit_many(
        [
            StepEvent(trace_id="run1", stage="build", action="build.end", seq=2, cost_usd=1),
            StepEvent(trace_id="run1", stage="grade", action="grade.belt", seq=3, duration_ms=7),
        ]
    )
    assert append_event(b.factory, trace_id="run1", stage="system", action="run.cancel_requested")
    with b.factory() as s:
        append_system_event(s, trace_id="users:1", action="user.created", actor="admin")
        s.commit()
    with b.factory() as s:  # a plain ORM add, the way a test or a new route might write
        s.add(
            Event(
                event_id="e" * 32,
                trace_id="plain",
                seq=1,
                timestamp="2026-09-27T10:00:00+00:00",
                stage="system",
                action="repo.created",
                status="ok",
            )
        )
        s.commit()
    assert sink.dropped == 0


def test_every_writer_chains_its_rows_from_genesis(db: Backend) -> None:
    _write_through_every_writer(db)
    with db.factory() as s:
        rows = list(s.execute(select(Event).order_by(Event.id)).scalars())
    assert len(rows) == 6
    assert rows[0].prev_hash == GENESIS_HASH
    assert all(b.prev_hash == a.row_hash for a, b in pairwise(rows))
    report = verify_events(db.factory)
    assert report.ok and report.rows == 6, report.detail
    assert events_head(db.factory) == (6, rows[-1].row_hash) == (6, report.head)


def test_a_writer_cannot_choose_its_own_hashes(db: Backend) -> None:
    with db.factory() as s:
        s.add(
            Event(
                event_id="f" * 32,
                trace_id="t",
                seq=1,
                timestamp="2026-09-27T10:00:00+00:00",
                stage="system",
                action="x",
                status="ok",
                prev_hash="a" * 64,
                row_hash="b" * 64,
            )
        )
        s.commit()
        (row,) = s.execute(select(Event)).scalars()
    assert row.prev_hash == GENESIS_HASH and row.row_hash != "b" * 64
    assert verify_events(db.factory).ok


@pytest.mark.parametrize(
    ("tamper", "broken_at", "word"),
    [
        ("UPDATE events SET actor = 'someone-else' WHERE id = 3", 3, "edited"),
        ("UPDATE events SET payload_json = '{\"forged\": true}' WHERE id = 3", 3, "edited"),
        ("DELETE FROM events WHERE id = 3", 4, "prev_hash"),
        (
            "UPDATE events SET id = 100 WHERE id = 3; "
            "UPDATE events SET id = 3 WHERE id = 4; "
            "UPDATE events SET id = 4 WHERE id = 100",
            3,
            "prev_hash",
        ),
    ],
    ids=["edited", "payload-edited", "deleted", "reordered"],
)
def test_a_tampered_event_is_found_underneath_the_triggers(
    db: Backend, tamper: str, broken_at: int, word: str
) -> None:
    _write_through_every_writer(db)
    assert verify_events(db.factory).ok
    _drop_event_triggers(db)
    with db.engine.begin() as c:
        for stmt in tamper.split("; "):
            c.execute(text(stmt))
    report = verify_events(db.factory)
    assert not report.ok and report.broken_at == broken_at and word in report.detail


def test_two_writers_at_once_do_not_fork_the_chain(db: Backend) -> None:
    errors: list[BaseException] = []
    per_writer = 25

    def sink_writer() -> None:
        try:
            sink = DbEventSink(db.factory)
            for i in range(1, per_writer + 1):
                sink.emit(StepEvent(trace_id="a", stage="build", action="build.step", seq=i))
            assert sink.dropped == 0
        except BaseException as exc:  # pragma: no cover — reported below
            errors.append(exc)

    def system_writer() -> None:
        try:
            for _ in range(per_writer):
                assert append_event(db.factory, trace_id="b", stage="system", action="run.note")
        except BaseException as exc:  # pragma: no cover — reported below
            errors.append(exc)

    threads = [threading.Thread(target=sink_writer), threading.Thread(target=system_writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    report = verify_events(db.factory)
    assert report.ok and report.rows == 2 * per_writer, report.detail
    with db.factory() as s:
        prevs = list(s.execute(select(Event.prev_hash)).scalars())
    assert len(set(prevs)) == len(prevs)  # one successor per row: no fork


def test_the_database_refuses_a_second_row_on_the_same_predecessor(db: Backend) -> None:
    """The flush hook serialises writers; the unique index is the second line — a writer
    that bypassed the hook still cannot fork the chain."""
    _write_through_every_writer(db)
    with db.factory() as s:
        first = s.execute(select(Event).order_by(Event.id).limit(1)).scalar_one()
        values: dict[str, Any] = {
            c.name: getattr(first, c.name) for c in Event.__table__.columns if c.name != "id"
        }
        values.update(event_id="9" * 32, trace_id="fork", row_hash="c" * 64)
        with pytest.raises(IntegrityError):
            s.execute(insert(Event).values(**values))
            s.commit()


def _previous_release_insert(b: Backend, n: int) -> None:
    """The INSERT the release before revision 0013 makes: every column but the chain's, so a
    server default (if one existed) would fill ``prev_hash`` and ``row_hash``. It stands for
    any writer that bypasses the flush hook — an old pod during the upgrade, a rollback, a
    Core ``insert(Event)``."""
    values: dict[str, Any] = {
        "event_id": f"{n:032x}",
        "trace_id": "old-release",
        "seq": n,
        "timestamp": "2026-09-27T10:00:00+00:00",
        "stage": "system",
        "action": "user.login",
        "status": "ok",
        "actor": "u1",
        "payload_json": {},
    }
    with b.engine.begin() as c:
        c.execute(insert(Event.__table__).values(**values))


def test_a_row_without_the_chain_is_refused_and_the_trail_keeps_recording(db: Backend) -> None:
    """P-246: the database refuses an unchained row outright, so one write from a writer
    that skipped the hook fails alone — it never becomes a head of ``''`` that turns every
    later write into a unique-index collision on genesis."""
    _write_through_every_writer(db)
    for n in (1, 2):  # a second attempt must fail the same way, not on a taken ''
        with pytest.raises(IntegrityError):
            _previous_release_insert(db, n)
    sink = DbEventSink(db.factory)
    sink.emit(StepEvent(trace_id="after", stage="build", action="build.start", seq=1))
    assert sink.dropped == 0 and sink.written == 1
    assert append_event(db.factory, trace_id="after", stage="system", action="run.note")
    with db.factory() as s:
        append_system_event(s, trace_id="users:1", action="user.login", actor="admin")
        s.commit()
    report = verify_events(db.factory)
    assert report.ok and report.rows == 9, report.detail


def _force_unchained_head(b: Backend) -> None:
    """Put a row with empty chain columns at the head the way only the database owner could:
    with the CHECK constraint lifted for one statement."""
    with b.engine.begin() as c:
        if b.dialect == "sqlite":
            c.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
        else:
            c.execute(text("ALTER TABLE events DROP CONSTRAINT ck_events_chain_hashes"))
        c.execute(
            text(
                "INSERT INTO events (event_id, trace_id, seq, timestamp, stage, action, status, "
                "step_id, parent_step_id, actor, repo, task_id, input_ref, output_ref, "
                "error_code, error_message, payload_json, prev_hash, row_hash) VALUES "
                "(:e, 'forced', 1, '2026-09-27T10:00:00+00:00', 'system', 'x', 'ok', '', '', "
                "'', '', '', '', '', '', '', '{}', '', '')"
            ),
            {"e": "d" * 32},
        )
        if b.dialect == "sqlite":
            c.exec_driver_sql("PRAGMA ignore_check_constraints = OFF")


def test_a_head_that_is_not_a_hash_is_a_named_break_never_a_new_genesis(db: Backend) -> None:
    """P-246: genesis is the predecessor of the first row of an EMPTY table only. A head
    that is not a SHA-256 is refused by name, so the writer never chains onto genesis a
    second time and the failure says what is wrong."""
    from crb.store.events import EventChainHeadError

    _write_through_every_writer(db)
    _force_unchained_head(db)
    with db.factory() as s:
        append_system_event(s, trace_id="users:1", action="user.login", actor="admin")
        with pytest.raises(EventChainHeadError, match="not a SHA-256"):
            s.commit()
    with db.factory() as s:
        prevs = list(s.execute(select(Event.prev_hash)).scalars())
    assert prevs.count(GENESIS_HASH) == 1


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_verifier_walks_only_new_rows_between_full_walks(db: Backend) -> None:
    """P-249: ``/ledger/verify`` is read on every Ledger and Posture page view, and the audit
    trail holds every step of every run. Between full walks (at most ``full_every_s`` apart)
    the verifier re-hashes only the rows appended since its last walk, starting from that
    walk's head — after checking the head row and the row count are still what it walked."""
    from crb.store.events import EventChainVerifier

    _write_through_every_writer(db)
    clock = _Clock()
    verifier = EventChainVerifier(full_every_s=300.0, clock=clock)
    with db.factory() as s:
        first = verifier.verify(s)
    assert first.ok and first.rows == 6 and first.walk == "full" and first.walked == 6
    assert append_event(db.factory, trace_id="run2", stage="system", action="run.note")
    clock.now += 60
    with db.factory() as s:
        tail = verifier.verify(s)
    assert tail.ok and tail.rows == 7 and tail.walk == "tail" and tail.walked == 1
    assert tail.head == events_head(db.factory)[1] == verify_events(db.factory).head
    assert tail.full_walk_at == first.full_walk_at
    clock.now += 300
    with db.factory() as s:
        again = verifier.verify(s)
    assert again.walk == "full" and again.walked == 7 and again.full_walk_at >= first.full_walk_at
    with db.factory() as s:
        forced = verifier.verify(s, full=True)
    assert forced.walk == "full" and forced.walked == 7


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE events SET actor = 'mallory' WHERE id = (SELECT MAX(id) FROM events)",
        "DELETE FROM events WHERE id = 2",
    ],
    ids=["head-edited", "prefix-deleted"],
)
def test_the_verifier_walks_everything_when_what_it_walked_has_changed(
    db: Backend, tamper: str
) -> None:
    """A tail walk trusts only a prefix it can still see unchanged: an edit to the row it
    ended on, or a row gone from before it, sends the next request back to a full walk,
    which reports the break."""
    from crb.store.events import EventChainVerifier

    _write_through_every_writer(db)
    verifier = EventChainVerifier(full_every_s=300.0, clock=_Clock())
    with db.factory() as s:
        assert verifier.verify(s).ok
    _drop_event_triggers(db)
    with db.engine.begin() as c:
        c.execute(text(tamper))
    with db.factory() as s:
        report = verifier.verify(s)
    assert report.walk == "full" and not report.ok, report.detail


def test_a_broken_chain_is_never_served_from_a_tail_walk(db: Backend) -> None:
    """Once a walk finds a break, every later read walks in full: the finding stays visible
    and is never overwritten by a tail that starts after it."""
    from crb.store.events import EventChainVerifier

    _write_through_every_writer(db)
    _drop_event_triggers(db)
    with db.engine.begin() as c:
        c.execute(text("UPDATE events SET actor = 'mallory' WHERE id = 3"))
    verifier = EventChainVerifier(full_every_s=300.0, clock=_Clock())
    with db.factory() as s:
        assert verifier.verify(s).broken_at == 3
    assert append_event(db.factory, trace_id="run2", stage="system", action="run.note")
    with db.factory() as s:
        report = verifier.verify(s)
    assert report.walk == "full" and report.broken_at == 3 and report.rows == 7
