"""The DB event sink: round-trip fidelity, seq-ordered resumable reads, append-only
enforcement, and the never-raise contract.

Navigation
----------
What it is:   The database event sink's test suite — round-trip fidelity, seq-ordered resumable
              reads, append-only enforcement and the never-raise contract.
What it does: Pins that every ``StepEvent`` field survives the round trip, that reads are ordered
              by ``seq`` and resumable from ``after``, that the read limit is clamped, that
              ``emit_many`` batches and falls back row by row, that a failed insert is logged and
              dropped — never raised into the run — even when the factory itself is broken, that
              the table is append-only, that ``append_event`` allocates the next ``seq`` and
              never raises, and that ``append_event_checked`` stores the ``task_id`` and
              ``step_id`` it is given (P-792) while a caller that names neither writes and chains
              the row it wrote before.
How:          A temp SQLite session factory; ``DbEventSink`` through an ``Emitter``; the
              ``append_event_checked`` cases on the shared ``backend`` fixture (SQLite always,
              PostgreSQL when ``CRB_TEST_POSTGRES_URL`` is set), each row's hash recomputed from
              a hand-listed body.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/events.py (under test), src/crb/observability/events.py (the
              ``StepEvent`` envelope and ``Emitter``), src/crb/server/routes/runs.py (SSE reads
              the same table), tests/test_server_routes_runs.py, tests/conftest_store.py
              (the backends), src/crb/core/event_chain.py (the hash rule)
Tested by:    tests/test_store_events.py
Touch when:   never for a new repository; a field is added to ``StepEvent`` (the round-trip case
              must list it); the read limit or batching changes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.event_chain import GENESIS_HASH, event_row_hash
from crb.observability.events import Emitter, StepEvent, StepStatus
from crb.store import init_db, make_engine, make_session_factory
from crb.store.events import (
    MAX_READ_LIMIT,
    DbEventSink,
    append_event,
    append_event_checked,
    count_events,
    last_seq,
    read_events,
    verify_events,
)
from crb.store.models import Event

try:
    from tests.conftest_store import SHA, Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import SHA, Backend, backend, pg_schema  # noqa: F401


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory over a fresh SQLite file with every table and trigger installed."""
    engine = make_engine(f"sqlite:///{tmp_path / 'events.db'}")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def db(backend: Backend) -> Backend:
    """The shared backend (SQLite always, PostgreSQL when ``CRB_TEST_POSTGRES_URL`` is set)
    with every table and trigger installed."""
    init_db(backend.engine)
    return backend


def test_round_trip_preserves_every_field(factory: sessionmaker[Session]) -> None:
    sink = DbEventSink(factory)
    ev = StepEvent(
        trace_id="t1",
        stage="grade",
        action="grade.belt",
        status=StepStatus.ERROR,
        step_id="s1",
        parent_step_id="p1",
        actor="alice",
        repo="r1",
        task_id="abc1234",
        input_ref="in",
        output_ref="out",
        error_code="E",
        error_message="boom token=abcdefghij",
        duration_ms=12,
        cost_usd=0.5,
        payload={"belt": "target_green", "value": False, "nested": {"k": [1, 2]}},
        seq=7,
    )
    sink.emit(ev)
    assert sink.written == 1 and sink.dropped == 0
    (got,) = read_events(factory, "t1")
    assert got.to_dict() == ev.to_dict()
    assert got.error_message == "boom token=[REDACTED]"  # redacted at construction, stored so


def test_read_is_seq_ordered_and_resumable(factory: sessionmaker[Session]) -> None:
    sink = DbEventSink(factory)
    em = Emitter(sink, trace_id="run1", actor="w", repo="r1")
    for i in range(5):
        em.emit("system", f"a.{i}", i=i)
    Emitter(sink, trace_id="other").emit("system", "x.y")
    all_events = read_events(factory, "run1")
    assert [e.seq for e in all_events] == [1, 2, 3, 4, 5]
    assert [e.action for e in all_events] == [f"a.{i}" for i in range(5)]
    assert [e.seq for e in read_events(factory, "run1", after_seq=3)] == [4, 5]
    assert [e.seq for e in read_events(factory, "run1", limit=2)] == [1, 2]
    assert [e.seq for e in read_events(factory, "run1", after_seq=2, limit=2)] == [3, 4]
    assert read_events(factory, "run1", after_seq=5) == []
    assert last_seq(factory, "run1") == 5 and last_seq(factory, "nope") == 0
    assert count_events(factory, "run1") == 5 and count_events(factory, "other") == 1


def test_read_limit_is_clamped(factory: sessionmaker[Session]) -> None:
    sink = DbEventSink(factory)
    em = Emitter(sink, trace_id="t")
    em.emit("system", "a")
    # one batch (a single transaction) rather than 5000 fsync'd commits
    sink.emit_many(
        StepEvent(trace_id="t", seq=i + 2, stage="system", action=f"a{i}")
        for i in range(MAX_READ_LIMIT + 4)
    )
    assert len(read_events(factory, "t", limit=0)) == 1  # min 1
    # the upper clamp is MEASURED: more rows than the cap exist, and the cap wins
    assert len(read_events(factory, "t", limit=MAX_READ_LIMIT * 10)) == MAX_READ_LIMIT


def test_emit_many_batches(factory: sessionmaker[Session]) -> None:
    sink = DbEventSink(factory)
    events = [
        StepEvent(trace_id="b", stage="mine", action="mine.candidate", seq=i) for i in range(1, 4)
    ]
    assert sink.emit_many(events) == 3
    assert sink.emit_many([]) == 0
    assert [e.seq for e in read_events(factory, "b")] == [1, 2, 3]
    assert sink.written == 3


def test_failed_insert_is_logged_and_dropped_never_raised(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    sink = DbEventSink(factory)
    ev = StepEvent(trace_id="d", stage="system", action="dup", seq=1)
    sink.emit(ev)
    with caplog.at_level(logging.WARNING, logger="crb.store.events"):
        sink.emit(ev)  # same event_id → unique-constraint failure
    assert sink.written == 1 and sink.dropped == 1
    assert any("event dropped" in r.message for r in caplog.records)
    assert count_events(factory, "d") == 1


def test_emit_many_falls_back_row_by_row(factory: sessionmaker[Session]) -> None:
    sink = DbEventSink(factory)
    good = StepEvent(trace_id="m", stage="system", action="ok", seq=1)
    sink.emit(good)
    other = StepEvent(trace_id="m", stage="system", action="ok2", seq=2)
    assert sink.emit_many([good, other]) == 1  # the duplicate drops, the other lands
    assert sink.dropped == 1
    assert [e.action for e in read_events(factory, "m")] == ["ok", "ok2"]


def test_sink_survives_a_broken_factory(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> Session:
        raise RuntimeError("db is down")

    sink = DbEventSink(broken)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        sink.emit(StepEvent(trace_id="x", stage="system", action="a", seq=1))
        assert sink.emit_many([StepEvent(trace_id="x", stage="system", action="b", seq=2)]) == 0
    assert sink.dropped == 2 and sink.written == 0


def test_events_table_is_append_only(factory: sessionmaker[Session]) -> None:
    DbEventSink(factory).emit(StepEvent(trace_id="ao", stage="system", action="a", seq=1))
    with factory() as s:
        with pytest.raises(Exception, match="append-only"):
            s.execute(text("UPDATE events SET action = 'b' WHERE trace_id = 'ao'"))
            s.commit()
        s.rollback()
        with pytest.raises(Exception, match="append-only"):
            s.execute(text("DELETE FROM events WHERE trace_id = 'ao'"))
            s.commit()
        s.rollback()
    assert [e.action for e in read_events(factory, "ao")] == ["a"]


def test_append_event_allocates_next_seq(factory: sessionmaker[Session]) -> None:
    sink = DbEventSink(factory)
    Emitter(sink, trace_id="s").emit("system", "live.1")
    ev = append_event(
        factory,
        trace_id="s",
        stage="system",
        action="run.reclaimed",
        repo="r1",
        actor="queue",
        payload={"previous_worker": "w1"},
    )
    assert ev is not None and ev.seq == 2 and ev.repo == "r1"
    ev2 = append_event(factory, trace_id="s", stage="system", action="run.note")
    assert ev2 is not None and ev2.seq == 3
    first = append_event(factory, trace_id="fresh", stage="system", action="a")
    assert first is not None and first.seq == 1
    assert [e.action for e in read_events(factory, "s")] == ["live.1", "run.reclaimed", "run.note"]


def test_append_event_error_status_and_never_raises(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    ev = append_event(
        factory,
        trace_id="e",
        stage="system",
        action="run.abandoned",
        status=StepStatus.ERROR,
        error="gave up",
        error_code="Abandoned",
    )
    assert ev is not None and ev.status is StepStatus.ERROR and ev.error_message == "gave up"
    with pytest.raises(ValueError):  # an invalid stage is a programming error, surfaced
        append_event(factory, trace_id="e", stage="not-a-stage", action="x")

    def broken() -> Session:
        raise RuntimeError("down")

    with caplog.at_level(logging.WARNING):
        assert append_event(broken, trace_id="e", stage="system", action="x") is None  # type: ignore[arg-type]
    assert any("system event dropped" in r.message for r in caplog.records)


def test_seq_collision_is_reallocated_under_the_lock_never_dropped(
    factory: sessionmaker[Session],
) -> None:
    """``(trace_id, seq)`` is UNIQUE (revision 0004): when an out-of-band ``append_event``
    takes the number a live emitter was about to use, the sink re-numbers the live event
    under the write lock instead of dropping it — the resume cursor stays dense."""
    sink = DbEventSink(factory)
    em = Emitter(sink, trace_id="t")
    em.emit("system", "live.1")  # seq 1
    assert append_event(factory, trace_id="t", stage="system", action="cancel.requested")
    em.emit("system", "live.2")  # the emitter's counter says 2 — already taken
    seqs = [(e.action, e.seq) for e in read_events(factory, "t")]
    assert seqs == [("live.1", 1), ("cancel.requested", 2), ("live.2", 3)]
    assert sink.written == 2 and sink.dropped == 0 and sink.realloc == 1
    # and the database refuses a raw duplicate outright
    with factory() as s, pytest.raises(Exception, match=r"uq_events_trace_seq|UNIQUE|unique"):
        s.execute(
            text(
                "INSERT INTO events (event_id, trace_id, seq, timestamp, stage, action, status, "
                "step_id, parent_step_id, actor, repo, task_id, input_ref, output_ref, "
                "error_code, error_message, payload_json, prev_hash, row_hash) VALUES ('x', "
                "'t', 3, 'ts', 'system', 'dup', 'ok', '', '', '', '', '', '', '', '', '', '{}', "
                ":prev, :row)"
            ),
            # well-formed chain columns (revision 0013's CHECK), so only the seq can refuse it
            {"prev": "c" * 64, "row": "d" * 64},
        )
        s.commit()


def _stored(b: Backend, trace_id: str) -> list[Event]:
    with b.factory() as s:
        return list(
            s.execute(select(Event).where(Event.trace_id == trace_id).order_by(Event.id)).scalars()
        )


def _body_as_today(ev: StepEvent, *, step_id: str = "", task_id: str = "") -> dict[str, Any]:
    """The hashed values of a row ``append_event_checked`` writes, listed by hand: only the
    trace, stage, action, actor, repo and payload come from the caller (and now the step and
    task ids); every other column is the envelope's default. A column that drifted from this
    list would change the row's hash."""
    return {
        "event_id": ev.event_id,
        "trace_id": ev.trace_id,
        "seq": ev.seq,
        "timestamp": ev.timestamp,
        "stage": "system",
        "action": ev.action,
        "status": "ok",
        "step_id": step_id,
        "parent_step_id": "",
        "actor": "worker-1",
        "repo": "r1",
        "task_id": task_id,
        "input_ref": "",
        "output_ref": "",
        "error_code": "",
        "error_message": "",
        "duration_ms": None,
        "cost_usd": None,
        "payload": {"v": 1},
    }


def test_append_event_checked_records_task_and_step_ids(db: Backend) -> None:
    """A reading's reservation (P-792) is keyed by its trace, arm and commit, so the locked
    writer must store the ``task_id`` and ``step_id`` it is given — before this, it had no
    way to name them and every checked event read ``''`` for both. The returned event, the
    read and the stored row all carry them, and the row hashes them into the chain."""
    trace = "rdg_" + "a" * 24
    ev = append_event_checked(
        db.factory,
        trace_id=trace,
        stage="system",
        action="reading.reserved",
        build=lambda _s: {"v": 1},
        actor="worker-1",
        repo="r1",
        task_id=SHA,
        step_id="S1@" + "x" * 61,  # the String(64) column's full width
    )
    assert (ev.task_id, ev.step_id, ev.seq) == (SHA, "S1@" + "x" * 61, 1)
    (got,) = read_events(db.factory, trace)
    assert got.to_dict() == ev.to_dict()
    (row,) = _stored(db, trace)
    assert (row.task_id, row.step_id, row.parent_step_id) == (SHA, "S1@" + "x" * 61, "")
    assert row.prev_hash == GENESIS_HASH
    assert row.row_hash == event_row_hash(
        _body_as_today(ev, step_id="S1@" + "x" * 61, task_id=SHA), GENESIS_HASH
    )
    # a second event on another arm of the same trace takes the next seq and chains on
    ev2 = append_event_checked(
        db.factory,
        trace_id=trace,
        stage="system",
        action="reading.reserved",
        build=lambda _s: {"v": 1},
        actor="worker-1",
        repo="r1",
        task_id=SHA,
        step_id="A0+L",
    )
    assert (ev2.seq, ev2.step_id) == (2, "A0+L")
    rows = _stored(db, trace)
    assert [(r.step_id, r.task_id) for r in rows] == [("S1@" + "x" * 61, SHA), ("A0+L", SHA)]
    assert rows[1].prev_hash == rows[0].row_hash
    report = verify_events(db.factory)
    assert report.ok and report.rows == 2 and report.head == rows[1].row_hash


def test_append_event_checked_defaults_are_unchanged(db: Backend) -> None:
    """The new keywords default to the envelope's own ``''``, so every existing caller (the
    readings, campaigns, acceptance and runs routes, which name neither) writes the row it
    wrote before: both ids empty, and a ``row_hash`` equal to the hash of the hand-listed
    body that has no ids. An event written with the defaults and one written with the ids
    given as ``''`` are the same row, and both chain."""
    trace = "rdg_" + "b" * 24
    kw: dict[str, Any] = {
        "trace_id": trace,
        "stage": "system",
        "action": "reading.registered",
        "build": lambda _s: {"v": 1},
        "actor": "worker-1",
        "repo": "r1",
    }
    plain = append_event_checked(db.factory, **kw)
    explicit = append_event_checked(db.factory, **kw, task_id="", step_id="")
    first, second = _stored(db, trace)
    for ev, row, prev in ((plain, first, GENESIS_HASH), (explicit, second, first.row_hash)):
        assert (ev.task_id, ev.step_id) == ("", "")
        assert (row.task_id, row.step_id) == ("", "")
        assert row.prev_hash == prev
        assert row.row_hash == event_row_hash(_body_as_today(ev), prev)
    (r1, r2) = read_events(db.factory, trace)
    assert r1.to_dict() == plain.to_dict() and r2.to_dict() == explicit.to_dict()
    assert {k: v for k, v in r1.to_dict().items() if k not in ("event_id", "seq", "timestamp")} == {
        k: v for k, v in r2.to_dict().items() if k not in ("event_id", "seq", "timestamp")
    }
    report = verify_events(db.factory)
    assert report.ok and report.rows == 2
