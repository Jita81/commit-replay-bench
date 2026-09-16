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
              the table is append-only, and that ``append_event`` allocates the next ``seq`` and
              never raises.
How:          A temp SQLite session factory; ``DbEventSink`` through an ``Emitter``.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/events.py (under test), src/crb/observability/events.py (the
              ``StepEvent`` envelope and ``Emitter``), src/crb/server/routes/runs.py (SSE reads
              the same table), tests/test_server_routes_runs.py
Tested by:    tests/test_store_events.py
Touch when:   a field is added to ``StepEvent`` (the round-trip case must list it); the read
              limit or batching changes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from crb.observability.events import Emitter, StepEvent, StepStatus
from crb.store import init_db, make_engine, make_session_factory
from crb.store.events import (
    MAX_READ_LIMIT,
    DbEventSink,
    append_event,
    count_events,
    last_seq,
    read_events,
)


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory over a fresh SQLite file with every table and trigger installed."""
    engine = make_engine(f"sqlite:///{tmp_path / 'events.db'}")
    init_db(engine)
    return make_session_factory(engine)


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
                "error_code, error_message, payload_json) VALUES ('x', 't', 3, 'ts', 'system', "
                "'dup', 'ok', '', '', '', '', '', '', '', '', '', '{}')"
            )
        )
        s.commit()
