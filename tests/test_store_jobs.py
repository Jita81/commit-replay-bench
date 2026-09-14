"""The job queue on a temp SQLite database: atomic claims, liveness, reclaim,
cancellation, ownership and listing."""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from crb.store import init_db, make_engine, make_session_factory
from crb.store.events import read_events
from crb.store.jobs import (
    RECLAIMS_KEY,
    RUN_KINDS,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobQueue,
    StaleClaim,
    age_s,
    parse_ts,
)
from crb.store.models import Repo, Run


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    init_db(engine)
    f = make_session_factory(engine)
    with f() as s:
        s.add(Repo(name="r1", language="python", runner="pytest", clone_path="/x", config_json={}))
        s.commit()
    return f


@pytest.fixture
def queue(factory: sessionmaker[Session]) -> JobQueue:
    return JobQueue(factory, max_reclaims=2)


def _enqueue(queue: JobQueue, **kw: object) -> Run:
    base: dict[str, object] = {"repo": "r1", "kind": "replay"}
    base.update(kw)
    return queue.enqueue(Run(**base))  # type: ignore[arg-type]


# --- enqueue -------------------------------------------------------------------------


def test_enqueue_fills_defaults_and_validates(queue: JobQueue) -> None:
    run = _enqueue(queue)
    assert run.id and run.status == STATUS_QUEUED and run.mode == "sighted"
    assert run.created and not run.started and not run.finished and not run.worker_id
    blind = _enqueue(queue, kind="blind")
    assert blind.mode == "blind"
    with pytest.raises(ValueError, match="unknown run kind"):
        _enqueue(queue, kind="factory-of-doom")
    with pytest.raises(ValueError, match="needs a repo"):
        queue.enqueue(Run(repo="", kind="replay"))
    assert set(RUN_KINDS) == {
        "setup",
        "probe",
        "mine",
        "replay",
        "blind",
        "oracle",
        "controls",
        "label",
    }


def test_enqueue_forces_queued_state_even_if_caller_says_otherwise(queue: JobQueue) -> None:
    run = _enqueue(queue, status="succeeded", worker_id="zombie", cancel_requested=True)
    assert run.status == STATUS_QUEUED and run.worker_id == "" and run.cancel_requested is False


# --- claim ---------------------------------------------------------------------------


def test_claim_is_fifo_and_marks_running(queue: JobQueue) -> None:
    a = _enqueue(queue)
    a.created = "2020-01-01T00:00:00+00:00"  # force ordering: a is older
    with queue._factory() as s:
        s.merge(a)
        s.commit()
    b = _enqueue(queue)
    got = queue.claim_next("w1")
    assert got is not None and got.id == a.id
    assert got.status == STATUS_RUNNING and got.worker_id == "w1"
    assert got.started and got.heartbeat
    nxt = queue.claim_next("w1")
    assert nxt is not None and nxt.id == b.id
    assert queue.claim_next("w1") is None


def test_two_claims_one_wins(queue: JobQueue) -> None:
    run = _enqueue(queue)
    first = queue.claim_next("w1")
    second = queue.claim_next("w2")
    assert first is not None and first.id == run.id and first.worker_id == "w1"
    assert second is None
    assert queue.get(run.id).worker_id == "w1"  # type: ignore[union-attr]


def test_concurrent_claims_exactly_one_winner(queue: JobQueue) -> None:
    """Eight threads race for one queued run through the real DB lock."""
    run = _enqueue(queue)
    wins: list[str] = []
    barrier = threading.Barrier(8)

    def claim(w: str) -> None:
        barrier.wait()
        got = queue.claim_next(w)
        if got is not None:
            wins.append(w)

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert queue.get(run.id).worker_id == wins[0]  # type: ignore[union-attr]


def test_claim_filters_by_kind_and_repo(queue: JobQueue, factory: sessionmaker[Session]) -> None:
    with factory() as s:
        s.add(Repo(name="r2", language="python", runner="pytest", clone_path="/y", config_json={}))
        s.commit()
    _enqueue(queue, kind="mine")
    rep = _enqueue(queue, kind="replay", repo="r2")
    assert queue.claim_next("w", kinds=["oracle"]) is None
    got = queue.claim_next("w", kinds=["replay", "blind"], repo="r2")
    assert got is not None and got.id == rep.id
    assert queue.claim_next("w", repo="r2") is None
    assert queue.claim_next("w", kinds=["mine"]) is not None


def test_claim_requires_worker_id(queue: JobQueue) -> None:
    with pytest.raises(ValueError):
        queue.claim_next("")


# --- heartbeat / progress / finish -------------------------------------------------


def test_heartbeat_only_for_running_owner(queue: JobQueue) -> None:
    run = _enqueue(queue)
    assert queue.heartbeat(run.id) is False  # queued: nobody is alive on it
    queue.claim_next("w1")
    assert queue.heartbeat(run.id, worker_id="w1") is True
    assert queue.heartbeat(run.id, worker_id="w2") is False
    assert queue.heartbeat(run.id) is True  # unscoped refresh allowed
    queue.finish(run.id, STATUS_SUCCEEDED)
    assert queue.heartbeat(run.id) is False
    assert queue.heartbeat("nope") is False


def test_progress_and_finish_record_counts_and_timestamps(queue: JobQueue) -> None:
    run = _enqueue(queue)
    queue.claim_next("w1")
    queue.progress(run.id, 2, 5, {"tasks": 2}, worker_id="w1")
    got = queue.get(run.id)
    assert got is not None
    assert (got.progress_done, got.progress_total, got.counts_json) == (2, 5, {"tasks": 2})
    done = queue.finish(run.id, STATUS_SUCCEEDED, counts={"tasks": 5, "clean": 3}, worker_id="w1")
    assert done.status == STATUS_SUCCEEDED and done.finished and done.heartbeat == ""
    assert done.counts_json == {"tasks": 5, "clean": 3} and done.error == ""
    # a second finish is a no-op (history cannot be rewritten)
    again = queue.finish(run.id, STATUS_FAILED, error="late")
    assert again.status == STATUS_SUCCEEDED and again.error == ""


def test_finish_requires_terminal_status(queue: JobQueue) -> None:
    run = _enqueue(queue)
    queue.claim_next("w1")
    with pytest.raises(ValueError):
        queue.finish(run.id, STATUS_RUNNING)
    with pytest.raises(LookupError):
        queue.finish("missing", STATUS_FAILED)


def test_zombie_worker_cannot_overwrite(queue: JobQueue) -> None:
    run = _enqueue(queue)
    queue.claim_next("w1")
    with pytest.raises(StaleClaim):
        queue.progress(run.id, 1, 1, worker_id="w2")
    with pytest.raises(StaleClaim):
        queue.finish(run.id, STATUS_FAILED, worker_id="w2")
    with pytest.raises(StaleClaim):
        queue.set_apparatus(run.id, {"x": 1}, worker_id="w2")
    queue.set_apparatus(run.id, {"runner": "pytest"}, worker_id="w1")
    assert queue.get(run.id).apparatus_json == {"runner": "pytest"}  # type: ignore[union-attr]


# --- cancel ------------------------------------------------------------------------


def test_cancel_queued_run_is_terminal_immediately(queue: JobQueue) -> None:
    run = _enqueue(queue)
    got = queue.request_cancel(run.id)
    assert got is not None and got.status == STATUS_CANCELLED and got.finished
    assert got.cancel_requested is True
    assert queue.claim_next("w1") is None  # never handed to a worker
    assert queue.request_cancel("missing") is None


def test_cancel_running_run_sets_flag_and_records_event(queue: JobQueue) -> None:
    run = _enqueue(queue)
    queue.claim_next("w1")
    assert queue.is_cancel_requested(run.id) is False
    got = queue.request_cancel(run.id)
    assert got is not None and got.status == STATUS_RUNNING and got.cancel_requested
    assert queue.is_cancel_requested(run.id) is True
    events = read_events(queue._factory, run.id)
    assert [e.action for e in events] == ["run.cancel_requested"]
    assert events[0].stage == "system" and events[0].seq == 1
    # the worker then finishes it cancelled with whatever it measured
    done = queue.finish(run.id, STATUS_CANCELLED, counts={"tasks": 1}, worker_id="w1")
    assert done.status == STATUS_CANCELLED and done.counts_json == {"tasks": 1}
    assert queue.request_cancel(run.id).status == STATUS_CANCELLED  # type: ignore[union-attr]


def test_cancel_flag_on_a_queued_run_is_honoured_at_claim(
    queue: JobQueue, factory: sessionmaker[Session]
) -> None:
    """A run re-queued by a reclaim keeps its cancel flag; the next claimer finalises it."""
    run = _enqueue(queue)
    with factory() as s:
        row = s.get(Run, run.id)
        assert row is not None
        row.cancel_requested = True
        s.commit()
    assert queue.claim_next("w1") is None
    assert queue.get(run.id).status == STATUS_CANCELLED  # type: ignore[union-attr]


# --- stale reclaim -------------------------------------------------------------------


def test_reclaim_stale_requeues_and_records_event(queue: JobQueue) -> None:
    run = _enqueue(queue)
    queue.claim_next("w1")
    queue.progress(run.id, 1, 3, {"tasks": 1}, worker_id="w1")
    assert queue.reclaim_stale(120) == []  # fresh heartbeat: nothing to do
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=600)
    reclaimed = queue.reclaim_stale(120, now=later)
    assert [r.id for r in reclaimed] == [run.id]
    got = queue.get(run.id)
    assert got is not None
    assert got.status == STATUS_QUEUED and got.worker_id == "" and got.heartbeat == ""
    assert got.started == ""
    assert got.counts_json == {"tasks": 1, RECLAIMS_KEY: 1}  # partial counts survive
    ev = read_events(queue._factory, run.id)
    assert [e.action for e in ev] == ["run.reclaimed"]
    assert ev[0].payload["previous_worker"] == "w1"
    assert ev[0].payload["stale_s"] >= 600 and ev[0].payload["reclaims"] == 1
    # it can be claimed again, by anyone
    again = queue.claim_next("w2")
    assert again is not None and again.id == run.id and again.worker_id == "w2"
    # the reclaim counter rides along into the final summary
    done = queue.finish(run.id, STATUS_SUCCEEDED, counts={"tasks": 3}, worker_id="w2")
    assert done.counts_json == {"tasks": 3, RECLAIMS_KEY: 1}


def test_reclaim_gives_up_after_max_reclaims(queue: JobQueue) -> None:
    run = _enqueue(queue)
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=600)
    for i in range(1, 3):  # max_reclaims=2 → two honest reclaims
        queue.claim_next(f"w{i}")
        (r,) = queue.reclaim_stale(120, now=later)
        assert r.status == STATUS_QUEUED and r.counts_json[RECLAIMS_KEY] == i
    queue.claim_next("w3")
    (r,) = queue.reclaim_stale(120, now=later)
    assert r.status == STATUS_FAILED and "abandoned" in r.error and r.finished
    actions = [e.action for e in read_events(queue._factory, run.id)]
    assert actions == ["run.reclaimed", "run.reclaimed", "run.abandoned"]
    assert queue.claim_next("w4") is None


def test_reclaim_ignores_live_and_terminal_runs(queue: JobQueue) -> None:
    live = _enqueue(queue)
    done = _enqueue(queue)
    queue.claim_next("w1")
    queue.claim_next("w2")
    queue.finish(done.id, STATUS_SUCCEEDED)
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)
    assert queue.reclaim_stale(120, now=later) == []
    much_later = later + dt.timedelta(seconds=600)
    assert [r.id for r in queue.reclaim_stale(120, now=much_later)] == [live.id]


def test_reclaim_treats_unparseable_liveness_as_dead(
    queue: JobQueue, factory: sessionmaker[Session]
) -> None:
    run = _enqueue(queue)
    queue.claim_next("w1")
    with factory() as s:
        row = s.get(Run, run.id)
        assert row is not None
        row.heartbeat = "not-a-timestamp"
        row.started = ""
        row.created = ""
        s.commit()
    (r,) = queue.reclaim_stale(120)
    assert r.status == STATUS_QUEUED
    ev = read_events(factory, run.id)
    assert ev[0].payload["stale_s"] is None


# --- list ----------------------------------------------------------------------------


def test_list_runs_filters_and_paginates(queue: JobQueue) -> None:
    a = _enqueue(queue, kind="mine")
    b = _enqueue(queue, kind="replay")
    c = _enqueue(queue, kind="replay")
    queue.claim_next("w", kinds=["replay"])
    items, total = queue.list_runs()
    assert total == 3 and {r.id for r in items} == {a.id, b.id, c.id}
    items, total = queue.list_runs(kind="replay", status=STATUS_RUNNING)
    assert total == 1 and items[0].id == b.id
    items, total = queue.list_runs(repo="r1", limit=2)
    assert total == 3 and len(items) == 2
    items, total = queue.list_runs(limit=2, offset=2)
    assert total == 3 and len(items) == 1
    assert queue.list_runs(repo="nope")[1] == 0


# --- pure helpers ----------------------------------------------------------------------


def test_timestamp_helpers() -> None:
    now = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)
    assert parse_ts("") is None and parse_ts("garbage") is None
    assert parse_ts("2026-01-01T11:59:00+00:00") == now - dt.timedelta(minutes=1)
    assert parse_ts("2026-01-01T11:59:00") == now - dt.timedelta(minutes=1)  # naive = UTC
    assert age_s("2026-01-01T11:58:00+00:00", now) == 120.0
    assert age_s("", now) is None
