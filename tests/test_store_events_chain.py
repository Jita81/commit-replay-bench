"""The ``events`` table is hash-chained by construction, on SQLite and PostgreSQL (F51,
ADR-0041).

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
              the database itself refuses a second row on the same predecessor; and that the
              head served is the last row's hash.
How:          The shared ``backend`` fixture (SQLite always, PostgreSQL when
              ``CRB_TEST_POSTGRES_URL`` is set); raw SQL for the tampering; two threads over
              one session factory for the race.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0041-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/events.py (the flush hook, ``verify_events``, ``events_head``),
              src/crb/core/event_chain.py (the hash rule), tests/conftest_store.py (backends)
Tested by:    tests/test_store_events_chain.py
Touch when:   a new writer of ``events`` is added (it must pass through a session flush), or
              the chain rule changes.
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
        ("DELETE FROM events WHERE id = 3", 4, "prev_hash"),
        (
            "UPDATE events SET id = 100 WHERE id = 3; "
            "UPDATE events SET id = 3 WHERE id = 4; "
            "UPDATE events SET id = 4 WHERE id = 100",
            3,
            "prev_hash",
        ),
    ],
    ids=["edited", "deleted", "reordered"],
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
