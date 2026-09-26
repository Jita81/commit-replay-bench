"""The worker end to end on a temp SQLite database and the ``pyrepo`` fixture: every
run kind, cancellation between tasks, fail-closed sandbox, stale-claim resume, the
``--once`` entrypoint and the polling loop. No docker, no network, no model.

Navigation
----------
What it is:   The worker's test suite, end to end on a temp SQLite database and the ``pyrepo``
              fixture — every run kind, cancellation, the fail-closed sandbox, stale-claim
              resume, ``--once`` and the polling loop.
What it does: Pins a replay run end to end (and blind), not-clean plus the ladder climb, that
              consecutive provider outages stop the run (263 of the first 534 rows on the dev
              stack were usage-limit refusals), the ladder from builder columns and task ids,
              replay without a ladder failing closed, gold-dirty tasks excluded by default,
              cancel between tasks keeping partial counts and cancel-before-start honoured, mine
              upserting tasks and rejecting an unknown pool, probe and setup runs (auto-setup
              first when not ready; failing closed when it fails; runners bound to the repo's
              ``env_dir``), docker unavailable or without an image failing closed, oracle and
              controls runs recording their events (a violation failing the gate), unknown repo
              / kind failing cleanly, stale-claim reclaim with event seq resuming, the heartbeat
              thread, ``run_forever`` processing then stopping and surviving a broken iteration,
              stage routing, the ``--once`` entrypoint and settings from args / env, that a
              run where every attempt errors is ``failed`` not ``succeeded``, and that a sealed
              attempt whose container kill went UNCONFIRMED is visible (``run.kill_unconfirmed``
              on the trace, the note on the run's error, ``kill_confirmed: false`` in the pack)
              and reaped (the loop's pass writes ``run.kill_reaped`` / ``run.kill_reap_failed``;
              the check-in row counts what is pending); that the run's own docker executor
              (the grade stage's test run) reports an unconfirmed kill through the same seam
              (event under the task, note, reaper queue); and that a reap pass is budgeted to
              ``heartbeat_s / 2`` so a daemon that answers nothing cannot hold the loop past
              the worker's liveness bound — the check-in still lands.
How:          ``Harness`` wires a fresh store, the queue, a ``DbEventSink`` and the fake ``gold``
              / ``noop`` builder around ``Worker.run_one``; no docker, no network, no model.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/worker.py (under test), src/crb/store/jobs.py (the queue),
              src/crb/builders/adapter.py (the build path), src/crb/server/reaper.py (the
              reaper the loop drives), src/crb/core/oracle/controls.py
              (the controls run kind), tests/fixtures/pyrepo.py (the repository fixture),
              tests/test_worker_clone.py and tests/test_worker_budget_ladder.py (the same
              harness for one kind or seam each; so are the other test_worker_*.py files)
Tested by:    tests/test_worker.py
Touch when:   a run kind is added (``stage_for``, a run case here and the queue's
              ``RUN_KINDS``); a new way for a run to end must decide ``failed`` vs
              ``succeeded`` honestly.
"""

from __future__ import annotations

import json
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import crb.builders as builders_pkg
from crb.builders import adapter as adapter_mod
from crb.builders.base import (
    STOP_DONE,
    STOP_MAX_TURNS,
    STOP_MODEL_ERROR,
    Budget,
    BuildBrief,
    BuildOutcome,
)
from crb.builders.container import BuilderContainerSettings, SealedCheckout, UnconfirmedKill
from crb.core.evidence import verify_pack
from crb.core.execution import ExecResult, LocalExecutor, SandboxUnavailable
from crb.core.ledger import verify_chain
from crb.core.oracle import controls as nc
from crb.core.runners.base import SetupResult, SetupStep
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from crb.observability.events import JsonlSink, StepStatus
from crb.server import worker as worker_mod
from crb.server import worker_main
from crb.server.worker import Worker, WorkerSettings, docker_settings_for, stage_for
from crb.store import init_db, make_engine, make_session_factory
from crb.store.events import DbEventSink, read_events
from crb.store.jobs import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobQueue,
)
from crb.store.models import Repo, Run, Task, WorkerRow
from fixtures import pyrepo as pr

# --- a scripted builder ----------------------------------------------------------------


class FakeBuilder:
    """``behaviour``: ``gold`` applies the human patch, ``noop`` does nothing.
    ``hook`` (a test-set callable) runs on every build — used to cancel mid-run."""

    name = "fake"
    briefs: ClassVar[list[BuildBrief]] = []
    hook: ClassVar[Callable[[Workspace, BuildBrief], None] | None] = None

    def __init__(
        self, *, model: str, provider: str = "", behaviour: str = "gold", **_: Any
    ) -> None:
        self.model = model
        self.provider = provider
        self.behaviour = behaviour

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Budget, **_: Any
    ) -> BuildOutcome:
        FakeBuilder.briefs.append(brief)
        if FakeBuilder.hook is not None:
            FakeBuilder.hook(workspace, brief)
        base = {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "mode": brief.mode,
        }
        if self.behaviour == "gold":
            pr.apply_gold(workspace)
            return BuildOutcome(
                **base,
                done=True,
                stop_reason=STOP_DONE,
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.01,
                latency_s=0.1,
                budget=budget,
            )
        if self.behaviour == "multiply":
            # the factory's fixture item: append multiply() to the calc source
            src = workspace.root / pr.SRC
            src.write_text(
                src.read_text(encoding="utf-8")
                + "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
                encoding="utf-8",
            )
            return BuildOutcome(
                **base,
                done=True,
                stop_reason=STOP_DONE,
                cost_usd=0.02,
                latency_s=0.2,
                budget=budget,
            )
        if self.behaviour == "outage":
            return BuildOutcome(
                **base,
                done=False,
                stop_reason=STOP_MODEL_ERROR,
                errors=("model_error: You've hit your limit · resets 3pm",),
                budget=budget,
            )
        return BuildOutcome(**base, done=False, stop_reason=STOP_MAX_TURNS, turns=1, budget=budget)


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


# --- harness -----------------------------------------------------------------------------


class Harness:
    """One worker over a fresh SQLite store under ``tmp_path``: the queue, fast poll / heartbeat
    settings, and helpers to seed the repo and tasks, enqueue a run and read back rows and events.
    """

    def __init__(self, tmp_path: Path, pyrepo: pr.PyRepo) -> None:
        self.home = tmp_path / "home"
        self.url = f"sqlite:///{self.home / 'crb.db'}"
        self.pyrepo = pyrepo
        engine = make_engine(self.url)
        init_db(engine)
        self.factory: sessionmaker[Session] = make_session_factory(engine)
        self.queue = JobQueue(self.factory)
        self.settings = WorkerSettings(
            database_url=self.url,
            home=self.home,
            worker_id="w-test",
            poll_s=0.05,
            heartbeat_s=0.05,
            stale_after_s=5.0,
        )
        self.worker = Worker(self.settings, engine=engine)

    def add_repo(self, **overrides: Any) -> None:
        """Register ``pyrepo`` as the fixture repository (its config, with
        ``overrides`` merged in).
        """
        cfg = self.pyrepo.config.to_dict()
        cfg.update(overrides)
        with self.factory() as s:
            s.add(
                Repo(
                    name=pr.REPO_NAME,
                    language="python",
                    runner="pytest",
                    clone_path=str(self.pyrepo.path),
                    config_json=cfg,
                )
            )
            s.commit()

    def add_task(self, task: TaskSpec) -> None:
        """Upsert one mined task into the ``tasks`` table."""
        with self.factory() as s:
            s.merge(
                Task(
                    repo=task.repo,
                    task_id=task.task_id,
                    pool=task.pool,
                    size=task.size,
                    capability_class=task.capability_class,
                    language=task.language,
                    authored=task.authored,
                    subject=task.subject,
                    red_checked=task.red_checked,
                    gold_clean=task.gold_clean,
                    spec_json=task.to_dict(),
                )
            )
            s.commit()

    def enqueue(self, kind: str, **fields: Any) -> Run:
        """Enqueue a run of ``kind`` for the fixture repository; replay / blind runs default to the
        fake builder's ladder unless ``fields`` say otherwise.
        """
        base: dict[str, Any] = {"repo": pr.REPO_NAME, "kind": kind, "actor": "tester"}
        if kind in {"replay", "blind"} and "ladder_json" not in fields and "builder" not in fields:
            base["ladder_json"] = ["fake:m@p"]
        base.update(fields)
        return self.queue.enqueue(Run(**base))

    def run_one(self) -> Run:
        """Claim and process exactly one run; a ``None`` (nothing queued) is a test error."""
        run = self.worker.run_once()
        assert run is not None
        return run

    def events(self, run_id: str) -> list[Any]:
        """Every event of ``run_id`` in ``seq`` order."""
        return read_events(self.factory, run_id, limit=5000)

    def tasks(self) -> list[Task]:
        """Every task row, ordered by id."""
        with self.factory() as s:
            return list(s.execute(select(Task).order_by(Task.task_id)).scalars().all())

    def repo_row(self) -> Repo:
        """The fixture repository's ``repos`` row as the worker left it."""
        with self.factory() as s:
            row = s.get(Repo, pr.REPO_NAME)
            assert row is not None
            return row


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    """The harness with the repo registered and its one mined task on file."""
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


# --- replay ---------------------------------------------------------------------------------


def test_replay_run_end_to_end(h: Harness) -> None:
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.id == run.id and done.status == STATUS_SUCCEEDED, done.error
    assert done.worker_id == "w-test" and done.finished and done.heartbeat == ""
    assert (done.progress_done, done.progress_total) == (1, 1)
    # counts_json IS the RunSummary
    assert done.counts_json == {
        "run_id": run.id,
        "tasks": 1,
        "clean": 1,
        "disqualified": 0,
        "errors": 0,
        "first_pass_clean": 1,
        "rows": 1,
        "duration_s": done.counts_json["duration_s"],
        "stopped_reason": "",
        "total": 1,
    }
    assert done.apparatus_json["runner"] == "pytest" and done.apparatus_json["executor"] == {
        "executor": "local"
    }
    assert done.apparatus_json["extra"]["worker"] == "w-test"
    # ledger: one clean row for this run, chain verified, pack stored + verified
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert len(rows) == 1 and rows[0].clean and rows[0].mode == "sighted"
    assert rows[0].builder == "fake" and rows[0].model == "m" and rows[0].provider == "p"
    assert rows[0].actor == "tester" and rows[0].trial == "r1" and rows[0].cost_usd == 0.01
    assert verify_chain(rows) == 1 and h.worker.ledger.verify() == 1
    pack = h.worker.ledger.get_pack(rows[0].evidence_pack_hash)
    assert pack is not None and verify_pack(pack) and pack["run_id"] == run.id
    assert (h.home / "evidence" / f"{rows[0].evidence_pack_hash}.json").exists()
    # events: seq-ordered from 1, claimed first, finished last, belts in between, DB == JSONL
    ev = h.events(run.id)
    assert [e.seq for e in ev] == list(range(1, len(ev) + 1))
    actions = [e.action for e in ev]
    assert actions[0] == "run.claimed" and actions[-1] == "run.finished"
    assert "run.start" in actions and "run.done" in actions
    assert actions.count("grade.belt") == 4 and "ledger.append" in actions
    assert "build.start" in actions and "build.done" in actions
    belt = next(e for e in ev if e.action == "grade.belt")
    assert belt.stage == "grade" and belt.task_id == h.pyrepo.feat_sha and belt.repo == pr.REPO_NAME
    assert all(e.trace_id == run.id and e.actor == "tester" for e in ev)
    fin = ev[-1]
    assert fin.stage == "system" and fin.payload["final_status"] == STATUS_SUCCEEDED
    jsonl = list(JsonlSink(h.home / "events" / f"{run.id}.jsonl").read())
    assert [e.to_dict() for e in jsonl] == [e.to_dict() for e in ev]
    # the brief was sighted and never carried the source paths
    (brief,) = FakeBuilder.briefs
    assert (
        brief.sighted
        and brief.test_files == (pr.TEST_SUBTRACT,)
        and pr.SRC not in brief.task_text()
    )
    assert brief.message.startswith("feat: add subtract")


def test_blind_run(h: Harness) -> None:
    run = h.enqueue("blind")
    assert run.mode == "blind"
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED and done.counts_json["clean"] == 1
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.mode == "blind" and row.clean
    (brief,) = FakeBuilder.briefs
    assert brief.blind and brief.test_files == () and brief.test_command == ""


def test_replay_not_clean_and_ladder_climb(h: Harness) -> None:
    run = h.enqueue(
        "replay", ladder_json=["fake:m0", "fake:m1"], params_json={"budget": {"max_turns": 2}}
    )
    # rung 0 is a noop (config via builder_overrides is not exposed; use two registered behaviours)
    builders_pkg._REGISTRY["fake"] = lambda **cfg: FakeBuilder(
        behaviour="noop" if cfg["model"] == "m0" else "gold", **cfg
    )
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED
    c = done.counts_json
    assert (c["tasks"], c["clean"], c["rows"], c["first_pass_clean"]) == (1, 1, 2, 0)
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert [(r.trial, r.model, r.clean) for r in rows] == [("r1", "m0", False), ("r2", "m1", True)]
    assert rows[0].labels["rung"] == "r1"
    assert done.apparatus_json["extra"]["budget"]["max_turns"] == 2


def test_replay_stops_after_consecutive_provider_outages(h: Harness) -> None:
    """263 of the first 534 rows on the dev stack were usage-limit refusals written in
    seconds (2026-09-15): after `outage_stop` (default 3) consecutive refused attempts the run
    stops FAILED with the reason, instead of burning the queue one refused row at a time."""
    builders_pkg._REGISTRY["fake"] = lambda **cfg: FakeBuilder(behaviour="outage", **cfg)
    run = h.enqueue("replay", ladder_json=["fake:m0", "fake:m1", "fake:m2"])
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith(
        "provider outage: 3 consecutive attempts refused; last: model_error"
    )
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert len(rows) == 3 and {r.failure_kind for r in rows} == {"outage"}
    assert done.counts_json["stopped_reason"].startswith("provider outage")
    assert any(e.action == "run.outage_stop" for e in h.events(run.id))
    # `outage_stop: 0` disables the breaker: every task is attempted, the all-errored rule applies
    h.enqueue("replay", ladder_json=["fake:m0"], params_json={"outage_stop": 0})
    again = h.run_one()
    assert again.status == STATUS_FAILED and again.error.startswith("all 1 attempt(s) errored")


def test_ladder_from_builder_columns_and_task_ids(h: Harness) -> None:
    run = h.enqueue(
        "replay",
        builder="fake",
        model="mm",
        provider="pp",
        params_json={"task_ids": [h.pyrepo.feat_sha, "deadbeefcafe"]},
    )
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED and done.counts_json["tasks"] == 1
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert (row.builder, row.model, row.provider) == ("fake", "mm", "pp")
    skip = [e for e in h.events(run.id) if e.action == "run.skip"]
    assert (
        skip
        and skip[0].payload["task_ids"] == ["deadbeefcafe"]
        and skip[0].status is StepStatus.SKIPPED
    )


def test_replay_without_ladder_fails_closed(h: Harness) -> None:
    h.enqueue("replay", ladder_json=[])
    done = h.run_one()
    assert done.status == STATUS_FAILED and "needs a ladder" in done.error
    assert done.counts_json == {"tasks": 0, "total": 1, "rows": 0, "clean": 0}
    err = [e for e in h.events(done.id) if e.action == "run.error"]
    assert err and err[0].status is StepStatus.ERROR and err[0].error_code == "ValueError"


def test_gold_dirty_tasks_are_excluded_by_default(h: Harness) -> None:
    dirty = h.pyrepo.feat_task(gold_clean=False, gold_note="bad")
    h.add_task(dirty)  # overwrites the feat task as gold-dirty
    h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED and done.counts_json["tasks"] == 0
    assert done.counts_json["total"] == 0 and FakeBuilder.briefs == []


def test_cancel_between_tasks_keeps_partial_counts(h: Harness) -> None:
    green_sha = h.pyrepo.add_green_commit()
    second = h.pyrepo.feat_task(
        task_id=green_sha,
        subject="second",
        test_files=[pr.TEST_CALC],
        target_tests=[pr.TEST_CALC],
        baseline_failing=[],
        authored=h.pyrepo.repo.author_date(green_sha),
    )
    h.add_task(second)
    # ADR-0019: both qualified in this posture (the second as it was before its oracle went
    # green), so the gate admits two and the cancel decides how many are built
    _seed_qualified(h, h.pyrepo.feat_task())
    _seed_qualified(h, second)
    run = h.enqueue("replay", params_json={"canary": False})

    def cancel_during_first_build(_ws: Workspace, _brief: BuildBrief) -> None:
        got = h.queue.request_cancel(run.id, actor="tester")
        assert got is not None and got.status == STATUS_RUNNING and got.cancel_requested
        time.sleep(0.12)  # let the heartbeat thread tick at least once while running

    FakeBuilder.hook = cancel_during_first_build
    done = h.run_one()
    assert done.status == STATUS_CANCELLED and done.error == ""
    assert done.counts_json["tasks"] == 1 and done.counts_json["rows"] == 1
    assert done.counts_json["stopped_reason"] == "cancelled" and done.counts_json["total"] == 2
    assert len(FakeBuilder.briefs) == 1  # the second task was never built
    assert len(list(h.worker.ledger.rows(run_id=run.id))) == 1
    actions = [e.action for e in h.events(run.id)]
    assert "run.cancel_requested" in actions and actions[-1] == "run.finished"
    assert h.events(run.id)[-1].payload["final_status"] == STATUS_CANCELLED


def test_cancel_requested_before_start_is_honoured(h: Harness) -> None:
    run = h.enqueue("replay")
    # claimed by a worker that then died before executing; cancel arrives; reclaim → our worker
    with h.factory() as s:
        row = s.get(Run, run.id)
        assert row is not None
        row.cancel_requested = True
        s.commit()
    assert h.worker.run_once() is None  # the claim finalises the cancel; nothing to execute
    assert h.queue.get(run.id).status == STATUS_CANCELLED  # type: ignore[union-attr]
    assert FakeBuilder.briefs == []


# --- an unconfirmed container kill is visible and reaped ----------------------------------------


class UnconfirmedSession:
    """Stands in for ``ContainerSession`` (no daemon): the builder runs on the sealed
    checkout host-side, and the session reports ONE container whose kill went unconfirmed."""

    container: ClassVar[str] = "crb-build-fake-0badc0de"

    def __init__(
        self, settings: BuilderContainerSettings, checkout: SealedCheckout, **kw: Any
    ) -> None:
        self.settings = settings
        self.checkout = checkout

    def __enter__(self) -> UnconfirmedSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def overrides_for(self, builder: str) -> dict[str, Any]:
        return {}

    def unconfirmed_kills(self) -> list[UnconfirmedKill]:
        return [UnconfirmedKill(container=self.container, bound_s=10.0)]


def _scripted_docker(dir_: Path, *, gone: bool, delay_s: float = 0.0) -> str:
    """A ``docker`` for the reaper: ``inspect`` answers "No such container" (gone) or
    Running=true (never lets go); ``rm -f`` succeeds or fails with it. ``delay_s`` makes
    every call sleep first — a daemon that is slow to answer."""
    dir_.mkdir(parents=True, exist_ok=True)
    script = dir_ / "docker"
    inspect = 'echo "Error: No such container: $4" >&2; exit 1' if gone else "echo true"
    rm = ":" if gone else "exit 1"
    delay = f"sleep {delay_s:g}; " if delay_s else ""
    script.write_text(
        f'#!/bin/sh\n{delay}case "$1" in\n  inspect) {inspect} ;;\n  rm) {rm} ;;\nesac\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _realistic_heartbeat(h: Harness, heartbeat_s: float = 2.0) -> None:
    """The harness polls at 50 ms; a reap pass is budgeted to ``heartbeat_s / 2``, so a
    test that expects a scripted ``docker`` to be reached in one pass needs a real one."""
    h.worker.settings = replace(h.worker.settings, heartbeat_s=heartbeat_s)


@pytest.fixture
def sealed_unconfirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker's docker builder posture with the session doubled: every sealed attempt
    reports an unconfirmed kill."""
    monkeypatch.setenv("CRB_BUILDER__EXECUTOR", "docker")
    monkeypatch.setenv("CRB_BUILDER__IMAGE", "crb-builder:test")
    monkeypatch.setattr(adapter_mod, "SEALABLE_BUILDERS", frozenset({"fake"}))
    real = worker_mod.build_fn_for

    def with_double(*a: Any, **kw: Any) -> Any:
        return real(*a, **{**kw, "session_factory": UnconfirmedSession})

    monkeypatch.setattr(worker_mod, "build_fn_for", with_double)


def _worker_row(h: Harness) -> WorkerRow:
    with h.factory() as s:
        row = s.get(WorkerRow, "w-test")
        assert row is not None
        return row


def test_unconfirmed_kill_is_recorded_on_the_run_and_queued_for_the_reaper(
    h: Harness, sealed_unconfirmed: None
) -> None:
    """A cancelled sealed attempt whose container the daemon never reported stopped: the
    run still ends ``cancelled`` (it did stop building) but never silently — a system
    ``run.kill_unconfirmed`` (status error) on its trace, the by-hand note on its error,
    ``kill_confirmed: false`` in the attempt's evidence pack, the container in the reaper's
    durable queue, and the check-in row counting it for the health probe."""
    green_sha = h.pyrepo.add_green_commit()
    h.add_task(
        h.pyrepo.feat_task(
            task_id=green_sha,
            subject="second",
            test_files=[pr.TEST_CALC],
            target_tests=[pr.TEST_CALC],
            baseline_failing=[],
            authored=h.pyrepo.repo.author_date(green_sha),
        )
    )
    _seed_qualified(h, h.pyrepo.feat_task())
    _seed_qualified(h, h.pyrepo.feat_task(task_id=green_sha, baseline_failing=[]))
    run = h.enqueue("replay", params_json={"canary": False})

    def cancel_during_build(_ws: Workspace, _brief: BuildBrief) -> None:
        h.queue.request_cancel(run.id, actor="tester")

    FakeBuilder.hook = cancel_during_build
    done = h.run_one()
    name = UnconfirmedSession.container
    assert done.status == STATUS_CANCELLED  # still cancelled: it did stop building
    assert done.error == (
        f"container {name} may still be running — it will be reaped by the worker; "
        f"`docker rm -f {name}` reaps it by hand"
    )
    events = h.events(run.id)
    (ev,) = [e for e in events if e.action == "run.kill_unconfirmed"]
    assert ev.stage == "system" and ev.status == StepStatus.ERROR
    assert ev.payload == {"container": name, "run_id": run.id, "bound_s": 10.0}
    assert name in ev.error_message and "may still be running" in ev.error_message
    # the pack says so — a reader of the row's evidence sees the unconfirmed kill
    (row,) = list(h.worker.ledger.rows(run_id=run.id))  # the one task built before the cancel
    assert ev.task_id == row.task_id
    pack = h.worker.ledger.get_pack(row.evidence_pack_hash)
    assert pack is not None and verify_pack(pack)
    assert pack["notes"]["kill_confirmed"] is False and pack["notes"]["container"] == name
    # queued durably, and counted on the worker's row
    assert [e.container for e in h.worker.reaper.pending()] == [name]
    assert (h.home / "unconfirmed-containers.json").exists()
    assert _worker_row(h).unconfirmed_containers == 1


def test_reaper_pass_reaps_and_records_on_the_run_trace(
    h: Harness, sealed_unconfirmed: None, tmp_path: Path
) -> None:
    run = h.enqueue("replay")
    FakeBuilder.hook = lambda _ws, _brief: h.queue.request_cancel(run.id, actor="tester")
    h.run_one()
    name = UnconfirmedSession.container
    h.worker.reaper.docker = _scripted_docker(tmp_path / "gone", gone=True)
    _realistic_heartbeat(h)
    assert h.worker.reap() == 1
    (ev,) = [e for e in h.events(run.id) if e.action == "run.kill_reaped"]
    assert ev.stage == "system" and ev.status == StepStatus.OK
    assert ev.payload == {"container": name, "attempts": 1}
    assert ev.task_id == h.pyrepo.feat_task().task_id  # the queued entry remembers its task
    assert h.worker.reaper.pending() == [] and h.worker.reap() == 0
    h.worker.checkin()
    assert _worker_row(h).unconfirmed_containers == 0


def test_reaper_gives_up_at_the_bound_and_says_so_on_the_trace(
    h: Harness, sealed_unconfirmed: None, tmp_path: Path
) -> None:
    run = h.enqueue("replay")
    FakeBuilder.hook = lambda _ws, _brief: h.queue.request_cancel(run.id, actor="tester")
    h.run_one()
    name = UnconfirmedSession.container
    h.worker.reaper.docker = _scripted_docker(tmp_path / "stuck", gone=False)
    h.worker.reaper.max_attempts = 2
    _realistic_heartbeat(h)
    assert h.worker.reap() == 0  # attempt 1: still pending
    assert h.worker.reaper.pending()[0].attempts == 1
    assert h.worker.reap() == 1  # attempt 2: the bound
    (ev,) = [e for e in h.events(run.id) if e.action == "run.kill_reap_failed"]
    assert ev.stage == "system" and ev.status == StepStatus.ERROR
    assert ev.payload["container"] == name and ev.payload["attempts"] == 2
    assert f"docker rm -f {name}" in ev.error_message
    assert h.worker.reaper.pending() == []
    assert not [e for e in h.events(run.id) if e.action == "run.kill_reaped"]


def test_reaper_runs_from_the_polling_loop(
    h: Harness, sealed_unconfirmed: None, tmp_path: Path
) -> None:
    """The loop reaps every poll: a queued container is gone from the file, and the run's
    trace carries ``run.kill_reaped``, without any run being claimed."""
    run = h.enqueue("replay")
    FakeBuilder.hook = lambda _ws, _brief: h.queue.request_cancel(run.id, actor="tester")
    h.run_one()
    h.worker.reaper.docker = _scripted_docker(tmp_path / "gone", gone=True)
    _realistic_heartbeat(h)
    stop = threading.Event()
    t = threading.Thread(target=h.worker.run_forever, args=(stop,), daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and h.worker.reaper.pending_count():
        time.sleep(0.05)
    stop.set()
    t.join(timeout=5)
    assert h.worker.reaper.pending() == []
    assert [e.action for e in h.events(run.id) if e.action.startswith("run.kill_")] == [
        "run.kill_unconfirmed",
        "run.kill_reaped",
    ]


def test_reap_pass_is_budgeted_so_the_check_in_still_lands(h: Harness, tmp_path: Path) -> None:
    """A daemon that answers nothing (every call sleeps past the budget) with two
    containers queued: a pass ends within ``heartbeat_s / 2`` — the entry it ran out on
    counts one attempt with the reason, the entry it never reached is untouched — and the
    polling loop's check-in row is never older than the worker's liveness bound
    (``3 × heartbeat_s``) while passes are running."""
    heartbeat_s = 1.0
    _realistic_heartbeat(h, heartbeat_s)
    assert h.worker.reap_budget_s == heartbeat_s / 2
    h.worker.reaper.docker = _scripted_docker(tmp_path / "slow", gone=False, delay_s=3.0)
    h.worker.reaper.add("crb-build-slow-1", run_id="r1", task_id="t1")
    h.worker.reaper.add("crb-build-slow-2", run_id="r2", task_id="t2")
    t0 = time.monotonic()
    assert h.worker.reap() == 0
    elapsed = time.monotonic() - t0
    assert elapsed < heartbeat_s, elapsed  # the budget, not 3 s × (inspect + rm + inspect)
    first, second = h.worker.reaper.pending()
    assert first.attempts == 1 and "pass budget exhausted" in first.last_error
    assert second.attempts == 0 and second.last_error == ""
    # the loop: passes every poll, the check-in every heartbeat — sampled while it runs
    stop = threading.Event()
    t = threading.Thread(target=h.worker.run_forever, args=(stop,), daemon=True)
    t.start()
    ages: list[float] = []
    deadline = time.monotonic() + 3 * heartbeat_s
    while time.monotonic() < deadline:
        time.sleep(0.2)
        row = _worker_row(h)
        ages.append(time.monotonic() - h.worker._last_checkin)
        assert row.unconfirmed_containers == 2
    stop.set()
    t.join(timeout=10)
    assert ages and max(ages) < 3 * heartbeat_s, ages


class _UnconfirmedGradeExecutor(LocalExecutor):
    """The run's executor with a docker executor's cancel path scripted: the first
    command it is asked to run is "cancelled" and its container kill goes unconfirmed —
    reported through ``on_kill_unconfirmed`` exactly as ``DockerExecutor`` does."""

    container: ClassVar[str] = "crb-grade-0badc0de"
    instances: ClassVar[list[_UnconfirmedGradeExecutor]] = []

    def __init__(self, *, cancel: Any, on_kill_unconfirmed: Any, request_cancel: Any) -> None:
        super().__init__(cancel=cancel)
        self.report = on_kill_unconfirmed
        self.request_cancel = request_cancel
        self.commands: list[tuple[str, ...]] = []
        self.scripted = False
        _UnconfirmedGradeExecutor.instances.append(self)

    def run(self, cmd: Any) -> ExecResult:
        self.commands.append(tuple(cmd.argv))
        # the posture probe (`python -V`) runs as it would; the FIRST test run — the grade
        # stage's — is the one whose container kill goes unconfirmed
        if "pytest" not in " ".join(cmd.argv) or self.scripted:
            return super().run(cmd)
        self.scripted = True
        self.request_cancel()
        self.report(UnconfirmedKill(container=self.container, bound_s=10.0))
        return ExecResult(
            130, "", "", False, 0.1, True, kill_confirmed=False, container=self.container
        )


def test_grade_stage_unconfirmed_kill_is_recorded_under_the_task_and_queued(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The non-stream path: a cancel that lands while the grade stage's test run is
    in flight, whose ``docker kill`` the daemon never confirmed, reaches the worker through
    the executor's ``on_kill_unconfirmed`` — ``run.kill_unconfirmed`` on the trace under
    the task being graded, the by-hand note on the run's error, the container in the
    reaper's queue and on the check-in row. The run still ends ``cancelled``."""
    _UnconfirmedGradeExecutor.instances.clear()
    green_sha = h.pyrepo.add_green_commit()
    h.add_task(
        h.pyrepo.feat_task(
            task_id=green_sha,
            subject="second",
            test_files=[pr.TEST_CALC],
            target_tests=[pr.TEST_CALC],
            baseline_failing=[],
            authored=h.pyrepo.repo.author_date(green_sha),
        )
    )
    _seed_qualified(h, h.pyrepo.feat_task())
    _seed_qualified(h, h.pyrepo.feat_task(task_id=green_sha, baseline_failing=[]))
    run = h.enqueue("replay", params_json={"canary": False})
    real = worker_mod.make_executor

    def scripted(kind: str, **kw: Any) -> Any:
        assert kw.get("on_kill_unconfirmed") is not None  # the worker wires the seam
        return _UnconfirmedGradeExecutor(
            cancel=kw["cancel"],
            on_kill_unconfirmed=kw["on_kill_unconfirmed"],
            request_cancel=lambda: h.queue.request_cancel(run.id, actor="tester"),
        )

    monkeypatch.setattr(worker_mod, "make_executor", scripted)
    done = h.run_one()
    monkeypatch.setattr(worker_mod, "make_executor", real)
    name = _UnconfirmedGradeExecutor.container
    assert done.status == STATUS_CANCELLED  # cancel is honoured between tasks: one of two ran
    assert done.error == (
        f"container {name} may still be running — it will be reaped by the worker; "
        f"`docker rm -f {name}` reaps it by hand"
    )
    (ev,) = [e for e in h.events(run.id) if e.action == "run.kill_unconfirmed"]
    assert ev.stage == "system" and ev.status == StepStatus.ERROR
    (row,) = list(h.worker.ledger.rows(run_id=run.id))  # the one task graded before the cancel
    assert ev.task_id == row.task_id  # filed under the task whose tests were running
    assert ev.payload == {"container": name, "run_id": run.id, "bound_s": 10.0}
    (executor,) = _UnconfirmedGradeExecutor.instances
    assert executor.commands and any("pytest" in " ".join(c) for c in executor.commands)
    assert [e.container for e in h.worker.reaper.pending()] == [name]
    assert _worker_row(h).unconfirmed_containers == 1


# --- mine --------------------------------------------------------------------------------------


def test_mine_run_upserts_tasks(h: Harness) -> None:
    # start from an empty task table so the miner has work to do
    with h.factory() as s:
        for t in s.execute(select(Task)).scalars().all():
            s.delete(t)
        s.commit()
    run = h.enqueue("mine", params_json={"target": 5, "max_candidates": 10})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    c = done.counts_json
    assert c["found"] == 1 and c["gold_clean"] == 1 and c["gold_dirty"] == 0 and c["examined"] >= 1
    assert c["known"] == 0 and c["pool"] == "standard"
    (task,) = h.tasks()
    assert task.task_id == h.pyrepo.feat_sha and task.gold_clean is True and task.red_checked
    spec = TaskSpec.from_dict(task.spec_json)
    assert spec.test_files == (pr.TEST_SUBTRACT,) and spec.baseline_failing == (pr.TEST_SUBTRACT,)
    assert (done.progress_done, done.progress_total) == (1, 5)
    actions = [e.action for e in h.events(run.id)]
    assert "mine.candidate" in actions and "mine.red" in actions and "mine.gold" in actions
    assert "mine.task" in actions and "mine.done" in actions
    mine_ev = next(e for e in h.events(run.id) if e.action == "mine.red")
    assert mine_ev.stage == "mine" and mine_ev.task_id == h.pyrepo.feat_sha
    # a second mine run knows the task and finds nothing new; a bad-gold commit is kept but flagged
    h.pyrepo.add_bad_gold_commit()
    h.enqueue("mine", params_json={"target": 5})
    again = h.run_one()
    assert again.status == STATUS_SUCCEEDED
    assert again.counts_json["known"] == 1 and again.counts_json["gold_dirty"] == 1
    assert {t.gold_clean for t in h.tasks()} == {True, False}
    # `task_ids` = RE-QUALIFY those commits even though they are known (the miner
    # changed); the stored spec is replaced, nothing else is walked
    with h.factory() as s:
        row = next(
            t for t in s.execute(select(Task)).scalars().all() if t.task_id == h.pyrepo.feat_sha
        )
        stale = dict(row.spec_json)
        stale["target_tests"] = ["tests/stale.py"]
        row.spec_json = stale
        s.commit()
    # the walk uses the pool the task was STORED under (its shape caps), not the run's:
    # under the hard pool's caps (4–8 source files) this one-file commit is no candidate
    h.enqueue("mine", params_json={"task_ids": [h.pyrepo.feat_sha], "pool": "hard"})
    requal = h.run_one()
    assert requal.status == STATUS_SUCCEEDED, requal.error
    assert requal.counts_json["examined"] == 1 and requal.counts_json["found"] == 1
    assert requal.counts_json["known"] == 0 and requal.counts_json["pool"] == "standard"
    assert next(t for t in h.tasks() if t.task_id == h.pyrepo.feat_sha).pool == "standard"
    fresh = next(t for t in h.tasks() if t.task_id == h.pyrepo.feat_sha)
    assert TaskSpec.from_dict(fresh.spec_json).target_tests == (pr.TEST_SUBTRACT,)
    assert (requal.progress_done, requal.progress_total) == (1, 1)


def test_mine_rejects_unknown_pool(h: Harness) -> None:
    h.enqueue("mine", params_json={"pool": "impossible"})
    done = h.run_one()
    assert done.status == STATUS_FAILED and "pool must be" in done.error


# --- probe -------------------------------------------------------------------------------------


def test_probe_run_sets_status(h: Harness) -> None:
    h.enqueue("probe")  # config.probe is empty → the runner's default discovery (green at HEAD)
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["green"] is True and done.counts_json["scope"] == []
    repo = h.repo_row()
    assert repo.probe_status == "ok"
    actions = [e.action for e in h.events(done.id)]
    assert "probe.start" in actions and "probe.done" in actions and "run.executor" in actions


def test_probe_failure_is_recorded(tmp_path: Path, pyrepo: pr.PyRepo) -> None:
    h = Harness(tmp_path, pyrepo)
    h.add_repo(probe="tests/does_not_exist.py")
    h.enqueue("probe")
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("probe not green")
    repo = h.repo_row()
    assert repo.probe_status == "failed" and repo.probe_detail
    assert done.counts_json["green"] is False


# --- setup (the environment phase) -------------------------------------------------------------


class ScriptedSetupRunner(PytestRunner):
    """A pytest runner whose environment phase is scripted: ``ready`` answers
    ``environment_ready`` (consumed left to right, last value sticks) and ``outcome``
    is what ``setup`` returns after streaming its steps through ``on_step``."""

    ready: ClassVar[list[bool]] = [True]
    outcome: ClassVar[SetupResult] = SetupResult(True, (), "scripted", 0.0)
    calls: ClassVar[list[dict[str, Any]]] = []

    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        cls = type(self)
        if len(cls.ready) > 1:
            return cls.ready.pop(0)
        return cls.ready[0]

    def setup(
        self,
        executor: Any,
        root: Path,
        *,
        env_dir: Path,
        timeout: int,
        on_step: Callable[[SetupStep], None] | None = None,
    ) -> SetupResult:
        type(self).calls.append(
            {"executor": executor.name, "root": Path(root), "env_dir": env_dir, "timeout": timeout}
        )
        for step in type(self).outcome.steps:
            if on_step is not None:
                on_step(step)
        return type(self).outcome


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> type[ScriptedSetupRunner]:
    """Reset ``ScriptedSetupRunner``'s script and install it as the worker's ``get_runner``."""
    ScriptedSetupRunner.ready = [True]
    ScriptedSetupRunner.outcome = SetupResult(True, (), "scripted", 0.0)
    ScriptedSetupRunner.calls = []
    monkeypatch.setattr(worker_mod, "get_runner", lambda config: ScriptedSetupRunner(config))
    return ScriptedSetupRunner


_STEPS = (
    SetupStep(("uv", "venv", "/envs/pyrepo/venv"), 0, "", 0.2),
    SetupStep(
        ("uv", "pip", "install", "-e", ".[test]"),
        0,
        "Resolved 3 packages\nAuthorization: Bearer abcdefghijklmnop123456",
        1.5,
    ),
)


def test_setup_run_records_the_result_and_streams_steps(
    h: Harness, scripted: type[ScriptedSetupRunner]
) -> None:
    scripted.outcome = SetupResult(True, _STEPS, "ready", 1.7)
    run = h.enqueue("setup")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    env_dir = h.home / "envs" / pr.REPO_NAME
    # counts_json IS the SetupResult (+ where the env lives)
    assert done.counts_json == {**scripted.outcome.to_dict(), "env_dir": str(env_dir)}
    assert (done.progress_done, done.progress_total) == (2, 2)
    assert (
        done.apparatus_json["env_dir"] == str(env_dir) and done.apparatus_json["runner"] == "pytest"
    )
    # the runner was handed the clone and the repo's env_dir, on the run's executor
    (call,) = scripted.calls
    assert call == {"executor": "local", "root": h.pyrepo.path, "env_dir": env_dir, "timeout": 0}
    # events: start, one per step (redacted tail), done — all in the prep stage
    ev = h.events(run.id)
    actions = [e.action for e in ev]
    assert actions.count("setup.step") == 2 and "setup.start" in actions and "setup.done" in actions
    steps = [e for e in ev if e.action == "setup.step"]
    assert [e.payload["n"] for e in steps] == [1, 2] and all(e.stage == "prep" for e in steps)
    assert steps[1].payload["argv"] == ["uv", "pip", "install", "-e", ".[test]"]
    assert "[REDACTED]" in steps[1].payload["tail"] and "abcdefghijklmnop123456" not in str(
        steps[1].payload
    )
    assert all(e.status is StepStatus.OK for e in steps)
    fin = next(e for e in ev if e.action == "setup.done")
    assert (
        fin.payload["ok"] is True and fin.payload["steps"] == 2 and fin.payload["note"] == "ready"
    )
    # setup never touches the probe verdict
    assert h.repo_row().probe_status == "unknown"


def test_setup_run_failure_carries_the_last_tail(
    h: Harness, scripted: type[ScriptedSetupRunner]
) -> None:
    failed = SetupStep(("uv", "pip", "install", "-r", "req.txt"), 1, "ERROR: no such file", 0.3)
    scripted.outcome = SetupResult(False, (_STEPS[0], failed), "step 2 failed (rc=1): …", 0.5)
    done = h.run_one() if h.enqueue("setup") else None
    assert done is not None and done.status == STATUS_FAILED
    assert (
        done.error.startswith("setup failed: step 2 failed") and "ERROR: no such file" in done.error
    )
    assert done.counts_json["ok"] is False and len(done.counts_json["steps"]) == 2
    ev = h.events(done.id)
    bad = [e for e in ev if e.action == "setup.step" and e.status is StepStatus.ERROR]
    assert (
        len(bad) == 1
        and bad[0].payload["rc"] == 1
        and bad[0].error_message == "step 2 failed (rc=1)"
    )
    assert next(e for e in ev if e.action == "setup.done").status is StepStatus.ERROR
    assert h.repo_row().probe_status == "unknown"


def test_probe_runs_setup_first_when_the_environment_is_not_ready(
    h: Harness, scripted: type[ScriptedSetupRunner]
) -> None:
    scripted.ready = [False, True]  # not ready before setup, ready after
    scripted.outcome = SetupResult(True, _STEPS, "ready", 1.7)
    run = h.enqueue("probe")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["green"] is True
    assert done.counts_json["setup"] == scripted.outcome.to_dict()
    assert (
        len(scripted.calls) == 1 and scripted.calls[0]["env_dir"] == h.home / "envs" / pr.REPO_NAME
    )
    actions = [e.action for e in h.events(run.id)]
    auto = actions.index("setup.auto")
    assert (
        auto
        < actions.index("setup.step")
        < actions.index("setup.done")
        < actions.index("probe.start")
    )
    assert h.repo_row().probe_status == "ok"
    # ready from the start → no auto setup
    scripted.calls = []
    scripted.ready = [True]
    h.enqueue("probe")
    again = h.run_one()
    assert again.status == STATUS_SUCCEEDED and scripted.calls == []
    assert "setup.auto" not in [e.action for e in h.events(again.id)]
    assert "setup" not in again.counts_json


def test_probe_fails_closed_when_auto_setup_fails(
    h: Harness, scripted: type[ScriptedSetupRunner]
) -> None:
    scripted.ready = [False]
    failed = SetupStep(("npm", "ci"), 1, "npm ERR! network unreachable", 2.0)
    scripted.outcome = SetupResult(False, (failed,), "step 1 failed (rc=1): npm ci", 2.0)
    run = h.enqueue("probe")
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert (
        done.error.startswith("setup failed: step 1 failed") and "network unreachable" in done.error
    )
    assert done.counts_json["setup"]["ok"] is False and "green" not in done.counts_json
    repo = h.repo_row()
    assert repo.probe_status == "failed" and repo.probe_detail.startswith("setup failed")
    actions = [e.action for e in h.events(run.id)]
    assert "setup.auto" in actions and "probe.start" not in actions
    probe_done = next(e for e in h.events(run.id) if e.action == "probe.done")
    assert probe_done.status is StepStatus.ERROR and probe_done.payload["green"] is False


def test_runners_are_bound_to_the_repo_env_dir(
    h: Harness, scripted: type[ScriptedSetupRunner]
) -> None:
    """Every kind resolves its runner through the worker, which binds env_dir so a
    pytest runner without runner_opts.python would pick up the setup venv."""
    seen: list[Path | None] = []
    original = worker_mod.Worker._runner

    def spy(self: Worker, ctx: worker_mod.RunContext) -> Any:
        runner = original(self, ctx)
        seen.append(runner.env_dir)
        return runner

    h.worker._runner = spy.__get__(h.worker, Worker)  # type: ignore[method-assign]
    for kind in ("probe", "mine", "replay", "oracle", "controls"):
        h.enqueue(kind, params_json={"max_candidates": 3} if kind == "mine" else {})
        assert h.run_one().status == STATUS_SUCCEEDED
    assert seen and all(p == h.home / "envs" / pr.REPO_NAME for p in seen)


# --- fail-closed sandbox --------------------------------------------------------------------


def test_docker_unavailable_fails_closed(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(kind: str, *, docker: Any = None, **_kw: Any) -> Any:
        raise SandboxUnavailable("docker daemon not reachable")

    monkeypatch.setattr(worker_mod, "make_executor", refuse)
    run = h.enqueue("replay", params_json={"executor": "docker", "image": "crb/py:1"})
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error == "sandbox unavailable: docker daemon not reachable"
    assert done.counts_json["total"] == 1 and done.counts_json["tasks"] == 0  # preserved
    assert list(h.worker.ledger.rows(run_id=run.id)) == [] and FakeBuilder.briefs == []
    err = [e for e in h.events(run.id) if e.action == "run.error"]
    assert err and err[0].error_code == "SandboxUnavailable"
    # a probe under an unavailable sandbox marks the repo as not probed OK
    h.enqueue("probe", params_json={"executor": "docker", "image": "crb/py:1"})
    probe = h.run_one()
    assert probe.status == STATUS_FAILED and probe.error.startswith("sandbox unavailable")
    assert h.repo_row().probe_status == "failed"


def test_docker_without_any_image_fails_closed(h: Harness) -> None:
    """No --image, no params.image, no sandbox_image → DockerSettings refuses."""
    h.enqueue("replay", params_json={"executor": "docker"})
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("sandbox unavailable")


def test_docker_settings_resolution(h: Harness) -> None:
    from crb.core.execution import DockerSettings

    cfg = h.pyrepo.config
    base = DockerSettings(image="base:1", memory="4g")
    assert docker_settings_for(cfg, base, {}) is base
    over = docker_settings_for(cfg, base, {"image": "other:2"})
    assert over.image == "other:2" and over.memory == "4g"
    repo_cfg = cfg.__class__(
        **{**cfg.to_dict(), "language": cfg.language, "sandbox_image": "repo:3"}
    )
    assert docker_settings_for(repo_cfg, None, {}).image == "repo:3"
    # the worker's image is the DEFAULT for a repository without one: the repository's own
    # image wins (two toolchains on one worker), with the worker's caps; params still win
    repo_on_base = docker_settings_for(repo_cfg, base, {})
    assert repo_on_base.image == "repo:3" and repo_on_base.memory == "4g"
    assert docker_settings_for(repo_cfg, base, {"image": "other:2"}).image == "other:2"
    with pytest.raises(SandboxUnavailable):
        docker_settings_for(cfg, None, {})


# --- oracle / controls -----------------------------------------------------------------------


def test_oracle_run_scores_and_records_events(h: Harness) -> None:
    run = h.enqueue("oracle", params_json={"max_mutants": 10})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    c = done.counts_json
    assert c["tasks"] == 1 and c["scoreable"] == 1 and c["mutants"] >= 1
    assert c["oracle_strength"] is not None and c["oracle_strength_mean"] is not None
    assert c["cells"] and next(iter(c["cells"])) == "bug.fix/XS"
    scores = [e for e in h.events(run.id) if e.action == "oracle.score"]
    assert len(scores) == 1
    ev = scores[0]
    assert ev.stage == "oracle" and ev.task_id == h.pyrepo.feat_sha
    assert ev.payload["total"] == c["mutants"] and ev.payload["killed"] == c["killed"]
    assert ev.payload["schema"] == "crb.oracle_strength.v1" and "provenance" in ev.payload
    assert any(e.action == "oracle.mutation.scored" for e in h.events(run.id))
    assert done.apparatus_json["max_mutants"] == 10


def test_controls_run_records_report(h: Harness) -> None:
    run = h.enqueue("controls")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    c = done.counts_json
    assert c["tasks"] == 1 and c["rows"] == len(nc.CONTROLS) and c["passed"] is True
    assert c["violations"] == 0 and c["complete"] is True
    (report,) = [e for e in h.events(run.id) if e.action == "controls.report"]
    assert report.stage == "oracle" and report.payload["schema"] == nc.CONTROLS_SCHEMA
    assert [r["control"] for r in report.payload["rows"]] == list(nc.CONTROLS)
    assert report.payload["apparatus"]["worker"] == "w-test"


def test_controls_violation_fails_the_gate(h: Harness) -> None:
    """A task whose declared gold cannot satisfy its test → GOLD control VIOLATION."""
    bad = h.pyrepo.add_bad_gold_commit()
    bad_task = h.pyrepo.feat_task(
        task_id=bad,
        subject="bad",
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[pr.TEST_MULTIPLY],
        authored=h.pyrepo.repo.author_date(bad),
        gold_clean=True,
    )
    h.add_task(bad_task)
    # measured in this posture, the bad gold is refused before any control runs …
    h.enqueue("controls", params_json={"task_ids": [bad], "controls": [nc.GOLD, nc.NOOP]})
    refused = h.run_one()
    assert refused.status == STATUS_FAILED and refused.error.startswith("POSTURE_UNQUALIFIED")
    # … and a task qualified before its gold broke is caught by the GOLD control
    _seed_qualified(h, bad_task)
    h.enqueue(
        "controls",
        params_json={"task_ids": [bad], "controls": [nc.GOLD, nc.NOOP], "canary": False},
    )
    done = h.run_one()
    assert done.status == STATUS_FAILED and "gate FAILED" in done.error
    assert done.counts_json["violations"] == 1 and done.counts_json["passed"] is False


# --- worker mechanics --------------------------------------------------------------------------


def test_unknown_repo_and_kind_fail_cleanly(tmp_path: Path, pyrepo: pr.PyRepo) -> None:
    h = Harness(tmp_path, pyrepo)
    with h.factory() as s:
        s.add(
            Repo(
                name="ghost",
                language="python",
                runner="pytest",
                clone_path=str(tmp_path / "nope"),
                config_json={},
            )
        )
        s.commit()
    h.queue.enqueue(Run(repo="ghost", kind="probe"))
    done = h.run_one()
    assert done.status == STATUS_FAILED and "not a git repository" in done.error
    with h.factory() as s:
        s.add(
            Run(
                id="k1",
                repo="ghost",
                kind="teleport",
                status=STATUS_QUEUED,
                created="2020-01-01T00:00:00+00:00",
            )
        )
        s.commit()
    done = h.run_one()
    assert done.status == STATUS_FAILED and "unknown run kind" in done.error


def test_stale_claim_is_reclaimed_and_event_seq_resumes(h: Harness) -> None:
    run = h.enqueue("replay")
    # a previous worker claimed it, wrote three events, then died silently
    dead = h.queue.claim_next("w-dead")
    assert dead is not None
    sink = DbEventSink(h.factory)
    from crb.observability.events import Emitter

    em = Emitter(sink, trace_id=run.id)
    for _ in range(3):
        em.emit("system", "old.event")
    with h.factory() as s:
        row = s.get(Run, run.id)
        assert row is not None
        row.heartbeat = "2020-01-01T00:00:00+00:00"
        s.commit()
    done = h.run_one()  # reclaim → claim → execute
    assert done.status == STATUS_SUCCEEDED and done.worker_id == "w-test"
    assert done.counts_json["reclaims"] == 1 and done.counts_json["clean"] == 1
    ev = h.events(run.id)
    seqs = [e.seq for e in ev]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # strictly increasing, no dupes
    actions = [e.action for e in ev]
    assert actions[:3] == ["old.event"] * 3 and actions[3] == "run.reclaimed"
    assert actions[4] == "run.claimed" and actions[-1] == "run.finished"
    assert ev[3].payload["previous_worker"] == "w-dead"


def test_heartbeat_thread_refreshes_liveness(h: Harness) -> None:
    seen: list[str] = []
    run = h.enqueue("replay")

    def observe(_ws: Workspace, _brief: BuildBrief) -> None:
        before = h.queue.get(run.id).heartbeat  # type: ignore[union-attr]
        time.sleep(1.2)  # heartbeat_s = 0.05 → many ticks; stamps are second-precision
        after = h.queue.get(run.id).heartbeat  # type: ignore[union-attr]
        seen.extend([before, after])

    FakeBuilder.hook = observe
    assert h.run_one().status == STATUS_SUCCEEDED
    assert seen[0] and seen[1] and seen[1] > seen[0]


def test_run_forever_processes_then_stops(h: Harness) -> None:
    stop = threading.Event()
    t = threading.Thread(target=h.worker.run_forever, args=(stop,), daemon=True)
    t.start()
    run = h.enqueue("replay")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        got = h.queue.get(run.id)
        if got is not None and got.status == STATUS_SUCCEEDED:
            break
        time.sleep(0.05)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()
    assert h.queue.get(run.id).status == STATUS_SUCCEEDED  # type: ignore[union-attr]


def test_worker_checks_in_while_idle_and_names_its_run(h: Harness) -> None:
    """J-TEL-2: the loop upserts its ``workers`` row every ``heartbeat_s`` even when the
    queue is empty (the health probe's liveness source); while a run executes the row
    names it; a clean stop is stamped so the probe does not read it as a crash."""
    stop = threading.Event()
    t = threading.Thread(target=h.worker.run_forever, args=(stop,), daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    row: WorkerRow | None = None
    while time.monotonic() < deadline:
        with h.factory() as s:
            row = s.get(WorkerRow, "w-test")
        if row is not None and row.heartbeat:
            break
        time.sleep(0.05)
    assert row is not None, "the idle loop never checked in"
    assert row.hostname and row.executor == "local" and row.kinds == []
    assert row.started and row.heartbeat >= row.started and row.stopped == ""
    assert row.heartbeat_s == pytest.approx(0.05) and row.current_run_id == ""
    assert row.version
    first = row.heartbeat
    seen_run: list[str] = []

    def observe(_ws: Workspace, _brief: BuildBrief) -> None:
        with h.factory() as s:
            live = s.get(WorkerRow, "w-test")
            seen_run.append(live.current_run_id if live is not None else "")

    FakeBuilder.hook = observe
    run = h.enqueue("replay")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        got = h.queue.get(run.id)
        if got is not None and got.status == STATUS_SUCCEEDED:
            break
        time.sleep(0.05)
    time.sleep(1.1)  # second-precision stamps: let the idle check-in tick past ``first``
    stop.set()
    t.join(timeout=5)
    assert seen_run == [run.id]
    with h.factory() as s:
        row = s.get(WorkerRow, "w-test")
    assert row is not None
    assert row.heartbeat > first and row.current_run_id == "" and row.stopped


def test_run_forever_survives_a_broken_iteration(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    # the SECOND iteration signals: waiting on the event rather than on a 0.3 s sleep is what
    # makes this deterministic. Under the load of the full suite the sleep was not always long
    # enough for two iterations, so the assertion failed for want of a CPU slice, not a bug.
    iterated_twice = threading.Event()

    def flaky() -> Run | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db hiccup")
        iterated_twice.set()
        return None

    monkeypatch.setattr(h.worker, "run_once", flaky)
    stop = threading.Event()
    t = threading.Thread(target=h.worker.run_forever, args=(stop,), daemon=True)
    t.start()
    assert iterated_twice.wait(timeout=10), "the loop did not survive the broken iteration"
    stop.set()
    t.join(timeout=5)
    assert calls["n"] >= 2


def test_stage_routing_and_settings_validation() -> None:
    assert stage_for("grade.belt") == "grade" and stage_for("builder.build.attempt") == "build"
    assert stage_for("mine.red") == "mine" and stage_for("controls.done") == "oracle"
    assert stage_for("run.start") == "system" and stage_for("whatever") == "system"
    with pytest.raises(ValueError):
        WorkerSettings(poll_s=0)
    s = WorkerSettings(home="~/x", kinds=["replay"])  # type: ignore[arg-type]
    assert s.worker_id and s.kinds == ("replay",) and "~" not in str(s.home)


# --- entrypoint ---------------------------------------------------------------------------------


def test_once_main(h: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    run = h.enqueue("replay")
    argv = [
        "--database-url",
        h.url,
        "--home",
        str(h.home),
        "--worker-id",
        "w-cli",
        "--once",
        "--log-format",
        "text",
    ]
    assert worker_main.main(argv) == worker_main.EXIT_OK
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (
        out["run_id"] == run.id
        and out["status"] == STATUS_SUCCEEDED
        and out["counts"]["clean"] == 1
    )
    assert h.queue.get(run.id).worker_id == "w-cli"  # type: ignore[union-attr]
    with h.factory() as s:
        row = s.get(WorkerRow, "w-cli")
    assert row is not None and row.stopped and row.current_run_id == ""  # one-shot: left cleanly
    # nothing left: idle exit code
    assert worker_main.main(argv) == worker_main.EXIT_IDLE
    idle = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert idle == {"status": "idle", "worker_id": "w-cli"}


def test_main_rejects_bad_kinds_and_bad_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        worker_main.main(["--kinds", "replay,bogus", "--once"])
    assert exc.value.code == 2
    rc = worker_main.main(
        ["--database-url", "postgresql+psycopg://nope:1/x", "--home", str(tmp_path), "--once"]
    )
    assert rc == worker_main.EXIT_ERROR
    assert "error" in json.loads(capsys.readouterr().err.strip().splitlines()[-1])


def test_the_sandbox_tree_and_copy_size_hold_without_a_default_image(tmp_path: Path) -> None:
    """A deployment may leave the worker's image empty (each repository names its own
    ``sandbox_image``); ``CRB_SANDBOX__TREE`` and ``__WORK_SIZE`` still decide the posture
    of every docker run — never a silent ``copy`` with the default size — and a tree that
    is not one of the sandbox's trees stops the worker at start-up (CodeRabbit on PR #56)."""
    from crb.core.execution import TREE_READONLY
    from crb.core.spec import Language, RepoConfig

    args = worker_main.build_parser().parse_args(["--once"])
    env = {
        "CRB_HOME": str(tmp_path / "h"),
        "CRB_SANDBOX__EXECUTOR": "docker",
        "CRB_SANDBOX__TREE": "ReadOnly",
        "CRB_SANDBOX__WORK_SIZE": "3g",
    }
    s = worker_main.settings_from_args(args, env)
    assert s.docker is None
    assert s.sandbox_tree == TREE_READONLY and s.sandbox_work_size == "3g"
    repo_cfg = RepoConfig(name="r", language=Language.PYTHON, sandbox_image="repo:3")
    d = docker_settings_for(repo_cfg, None, {}, tree=s.sandbox_tree, work_size=s.sandbox_work_size)
    assert d.image == "repo:3" and d.tree == TREE_READONLY and d.work_size == "3g"
    with pytest.raises(ValueError, match="CRB_SANDBOX__TREE"):
        worker_main.settings_from_args(args, {**env, "CRB_SANDBOX__TREE": "copyy"})


def test_settings_from_args_env_fallbacks(tmp_path: Path) -> None:
    parser = worker_main.build_parser()
    args = parser.parse_args(["--once"])
    env = {
        "CRB_HOME": str(tmp_path / "h"),
        "CRB_EXECUTOR": "docker",
        "CRB_SANDBOX_IMAGE": "img:1",
        "CRB_WORKER_ID": "env-w",
    }
    s = worker_main.settings_from_args(args, env)
    assert s.home == tmp_path / "h" and s.executor == "docker"
    assert s.docker is not None and s.docker.image == "img:1" and s.worker_id == "env-w"
    # the deployment's keys — what compose / Helm set and the API reads — are honoured and
    # win over the short forms; without either the worker is `local` with no image
    deployed = worker_main.settings_from_args(
        args,
        {
            **env,
            "CRB_SANDBOX__EXECUTOR": "docker",
            "CRB_SANDBOX__IMAGE": "crb-sandbox-python:2026-09",
            "CRB_EXECUTOR": "local",
            "CRB_SANDBOX_IMAGE": "",
        },
    )
    assert deployed.executor == "docker"
    assert deployed.docker is not None and deployed.docker.image == "crb-sandbox-python:2026-09"
    only_deployed = worker_main.settings_from_args(
        args, {"CRB_HOME": str(tmp_path / "h"), "CRB_SANDBOX__EXECUTOR": "Docker"}
    )
    assert only_deployed.executor == "docker" and only_deployed.docker is None
    bare = worker_main.settings_from_args(args, {"CRB_HOME": str(tmp_path / "h")})
    assert bare.executor == "local" and bare.docker is None
    # J-TEL-1: the worker's own /metrics port — CRB_METRICS_PORT (default 9464; 0 = off),
    # gated by the same CRB_METRICS_ENABLED the API reads; the bind is loopback unless the
    # deployment says otherwise (the series name repositories, builders and installations)
    assert s.metrics_enabled is True and s.metrics_port == 9464
    assert s.metrics_host == "127.0.0.1"
    s_off = worker_main.settings_from_args(
        args, {**env, "CRB_METRICS_PORT": "0", "CRB_METRICS_ENABLED": "false"}
    )
    assert s_off.metrics_port == 0 and s_off.metrics_enabled is False
    with pytest.raises(ValueError, match="CRB_METRICS_PORT"):
        worker_main.settings_from_args(args, {**env, "CRB_METRICS_PORT": "70000"})
    s_all = worker_main.settings_from_args(args, {**env, "CRB_METRICS_HOST": "0.0.0.0"})
    assert s_all.metrics_host == "0.0.0.0"
    flag = parser.parse_args(["--once", "--metrics-host", "10.0.0.5"])
    assert (
        worker_main.settings_from_args(flag, {**env, "CRB_METRICS_HOST": "0.0.0.0"}).metrics_host
        == "10.0.0.5"
    )
    with pytest.raises(ValueError, match="CRB_METRICS_HOST"):
        worker_main.settings_from_args(args, {**env, "CRB_METRICS_HOST": "  "})
    args = parser.parse_args(
        ["--home", str(tmp_path / "flag"), "--executor", "local", "--kinds", "mine, probe"]
    )
    s2 = worker_main.settings_from_args(args, env)
    assert s2.home == tmp_path / "flag" and s2.executor == "local" and s2.kinds == ("mine", "probe")


def test_run_where_every_attempt_errors_is_failed_not_succeeded(h: Harness) -> None:
    """A provider 402 / missing credential on every task must not read as a success:
    the rows stay honest (never clean) and the run is `failed` with the first error."""
    from crb.builders.base import STOP_MODEL_ERROR, BuildOutcome

    class _Broken:
        name, model, provider = "broken", "m", "p"

        def __init__(self, **cfg: Any) -> None:
            pass

        def build(self, workspace: Any, brief: Any, budget: Any, *, on_event: Any = None) -> Any:
            return BuildOutcome(
                builder="broken",
                model="m",
                provider="p",
                mode=brief.mode,
                done=False,
                summary="",
                stop_reason=STOP_MODEL_ERROR,
                errors=("model_error: 402 payment required",),
                budget=budget,
            )

        def describe(self) -> dict[str, Any]:
            return {"builder": "broken"}

    builders_pkg._REGISTRY["broken"] = _Broken
    run = h.enqueue("replay", ladder_json=["broken:m@p"])
    done = h.run_one()
    assert done.id == run.id
    assert done.status == "failed"
    assert "attempt(s) errored" in done.error and "402" in done.error
    assert done.counts_json["errors"] == done.counts_json["rows"] == 1
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.clean is False and "402" in row.error


# --- factory (P6) ---------------------------------------------------------------------------


def _multiply_backlog(h: Harness) -> tuple[Any, Any, Any]:
    """Register the one-item ``bug.fix × XS`` backlog with its operator-authored oracle and
    the fake builder; returns ``(home, item, backlog)``."""
    from crb.factory.backlog import KIND_CODE, BacklogItem
    from crb.factory.testfirst import AuthoredTest
    from crb.server.factory_state import FactoryHome

    home = FactoryHome(h.home, pr.REPO_NAME)
    item = BacklogItem(
        id="I-1",
        title="Add multiply to calc",
        kind=KIND_CODE,
        description="calc needs multiply(a, b).",
        acceptance_criteria=("multiply(3, 4) == 12",),
        capability_class="bug.fix",
        size_estimate="XS",
        structural_facts=(
            "reproduction: `from calc import multiply` raises ImportError",
            "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
            "exact_value: multiply(3, 4) == 12",
        ),
    )
    backlog = home.register_backlog([item], actor="tester")
    home.save_authored(
        {
            "I-1": AuthoredTest(
                "tests/test_multiply.py",
                "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
                "operator:tester",
            )
        }
    )
    builders_pkg._REGISTRY["fake"] = lambda **cfg: FakeBuilder(behaviour="multiply", **cfg)
    return home, item, backlog


def test_factory_run_manufactures_a_frozen_backlog_item_end_to_end(h: Harness) -> None:
    """The forward-mode loop as a run kind: a frozen backlog with an operator-authored
    oracle → readiness → RED proof → build under the belts → (delivery refused, opt-in)
    → mechanical review → item outcome; a process_step=factory ledger row; the evidence
    chain under CRB_HOME/factory/<repo>/; live counts on the run."""
    from crb.core.ledger import PROCESS_FACTORY
    from crb.factory import evidence as fe
    from crb.server.factory_state import FactoryHome

    home, _item, backlog = _multiply_backlog(h)
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    c = done.counts_json
    assert (c["items"], c["done"], c["accepted"]) == (1, 1, 1) and c["by_status"] == {"accepted": 1}
    assert c["outcomes"][0]["status"] == "accepted"
    assert (done.progress_done, done.progress_total) == (1, 1)
    assert done.apparatus_json["backlog_hash"] == backlog.backlog_hash
    # the ledger row is a factory row, clean, chained
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert len(rows) == 1 and rows[0].process_step == PROCESS_FACTORY and rows[0].clean
    assert rows[0].builder == "fake" and rows[0].evidence_pack_hash
    # the evidence chain: freeze (from registration) then the loop's steps, verified
    kinds = [e.kind for e in home.events()]
    assert kinds[0] == fe.EV_BACKLOG_FROZEN and fe.EV_RED_PROOF in kinds and fe.EV_BUILD in kinds
    assert (
        fe.EV_DELIVERY_REFUSED in kinds
        and fe.EV_VERDICT in kinds
        and kinds[-1] == fe.EV_ITEM_OUTCOME
    )
    assert home.evidence().verify() == len(kinds)
    view = home.task_views()[0]
    assert (view.status, view.red_proof, view.build_status, view.review_verdict) == (
        "accepted",
        True,
        "clean",
        "accept",
    )
    # the run's StepEvents carry stage=factory and the item id
    actions = [e.action for e in h.events(run.id) if e.stage == "factory"]
    assert "item.start" in actions and "review.verdict" in actions and "item.done" in actions
    # THE ROUTE GATE (DL-038): with delivery opted in, the worker hands the loop the
    # capability map's decision for the item's cell — the SAME signed map the API serves.
    # The first factory run above wrote one sighted process_step=factory row into the
    # fixture's bug.fix XS cell, so the map now says `calibrate (n_below_min)` for it →
    # delivery WITHHELD (recorded with the measured route, no PR attempted), and the item
    # is still built, reviewed and accepted. The reading is the PRE-run map (DL-045): the
    # first run's row counts (n=1), the gated run's own row does not — and it is on the
    # route event, read at readiness, before the build
    h.enqueue("factory", ladder_json=["fake:m0"], params_json={"deliver": True})
    gated = h.run_one()
    assert gated.status == STATUS_SUCCEEDED, gated.error
    assert gated.counts_json["by_status"] == {"accepted": 1}
    routes = [e for e in home.events() if e.kind == fe.EV_ROUTE]
    cell = routes[-1].payload["cell_route"]
    assert cell["route"] == "calibrate" and cell["n"] == 1 and cell["reason_code"] == "n_below_min"
    assert cell["apparatus_versions"] == [rows[0].apparatus_version]
    assert len(list(h.worker.ledger.rows(run_id=gated.id))) == 1  # its own row landed after
    refused = [e for e in home.events() if e.kind == fe.EV_DELIVERY_REFUSED]
    assert refused and refused[-1].payload["reason"].startswith(
        "route gate: the cell routes calibrate"
    )
    assert refused[-1].payload["measured_route"] == "calibrate"
    assert refused[-1].payload["reason_code"] == "n_below_min"
    assert refused[-1].payload["policy_version"] == "routing.v1"
    withheld = [e.action for e in h.events(gated.id) if e.stage == "factory"]
    assert "delivery.withheld" in withheld and "delivery.opened" not in withheld
    # an approver's override reaches delivery — which then fails closed on the missing
    # credentials, the next gate in line — and the override is on the evidence chain
    h.enqueue(
        "factory",
        ladder_json=["fake:m0"],
        params_json={"deliver": True, "deliver_override_by": "approver:ada"},
    )
    overridden = h.run_one()
    assert overridden.status == STATUS_SUCCEEDED
    assert overridden.counts_json["by_status"] == {"delivery_failed": 1}
    routes = [e for e in home.events() if e.kind == fe.EV_ROUTE and e.payload.get("override_by")]
    assert routes and routes[-1].payload["override_by"] == "approver:ada"
    assert "delivery.override" in [
        e.action for e in h.events(overridden.id) if e.stage == "factory"
    ]
    # a run queued against a backlog that was re-registered before the worker claimed it
    # fails closed on the pinned hash (the API stamps params.backlog_hash at enqueue)
    h.enqueue("factory", ladder_json=["fake:m0"], params_json={"backlog_hash": "f" * 64})
    stale = h.run_one()
    assert stale.status == STATUS_FAILED and "backlog changed since" in stale.error
    # an evolution registered between enqueue and claim moves only the evolutions chain
    # (the frozen hash stays): the pin covers that chain too, so the run fails closed
    # rather than work an item the person who queued it never saw (verifier 2026-09-22)
    from dataclasses import replace as dc_replace

    active = home.load_backlog()
    assert active is not None
    h.enqueue(
        "factory",
        ladder_json=["fake:m0"],
        params_json={"backlog_hash": active.backlog_hash, "evolutions_hash": ""},
    )
    home.register_evolution(
        dc_replace(_item, id=f"{_item.id}-v2", supersedes=_item.id), actor="tester"
    )
    evolved = h.run_one()
    assert evolved.status == STATUS_FAILED and "backlog evolved since" in evolved.error
    assert "re-queue" in evolved.error
    # no backlog → the run fails closed with the instruction
    home2 = FactoryHome(h.home, "nope")
    assert home2.load_backlog() is None
    (home.dir / "backlog.json").unlink()
    h.enqueue("factory", ladder_json=["fake:m0"])
    again = h.run_one()
    assert again.status == STATUS_FAILED and "no frozen backlog" in again.error


def test_route_lookup_reads_the_map_as_it_stood_before_the_run(h: Harness) -> None:
    """DL-045 (B-1b finding 2 — PR bodies said ``n=27`` where the freeze saw 26): the
    worker's route lookup for a run EXCLUDES that run's own ledger rows, so a clean build
    cannot nudge the cell that licenses its own delivery. Rows of every other run count."""
    home, item, _ = _multiply_backlog(h)
    first = h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    second = h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    rows = list(h.worker.ledger.rows(repo=pr.REPO_NAME))
    assert {r.run_id for r in rows if r.process_step == "factory"} == {first.id, second.id}
    # the map with everything: two factory rows in bug.fix × XS
    everything = h.worker._route_lookup(pr.REPO_NAME)(item)
    assert everything is not None and everything["n"] == 2
    assert everything["apparatus_versions"] == [rows[-1].apparatus_version]
    # as the second run saw it: its own row excluded, the first run's counted
    before_second = h.worker._route_lookup(pr.REPO_NAME, second.id)(item)
    assert before_second is not None and before_second["n"] == 1
    # excluding the FIRST run's row today still counts the second's (n=1): the filter is
    # by run id, not by time — and an unknown run id excludes nothing
    minus_first = h.worker._route_lookup(pr.REPO_NAME, first.id)(item)
    assert minus_first is not None and minus_first["n"] == 1
    assert h.worker._route_lookup(pr.REPO_NAME, "not-a-run")(item) == everything
    # what each run actually saw is on its route event: the first run found the cell
    # unmeasured (None — its own row could not count), the second saw exactly one row
    cells = [e.payload["cell_route"] for e in home.events() if e.kind == "route.decided"]
    assert cells[0] is None and len(cells) == 2
    assert cells[1] == {k: before_second[k] for k in cells[1]}  # the evidence-facing slice
    assert cells[1]["n"] == 1 and cells[1]["apparatus_versions"] == [rows[-1].apparatus_version]


def test_github_settings_read_only_their_own_keys_and_refuse_a_malformed_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker reads ``CRB_GITHUB__*`` the way the API does and nothing else: an
    unrelated server setting it does not use cannot stop it, and a malformed GitHub value
    stops it rather than starting a worker that quietly has no enterprise connection."""
    import pydantic

    monkeypatch.setenv("CRB_GITHUB__APP_ID", "12345")
    monkeypatch.setenv("CRB_GITHUB__APP_SLUG", "crb-bench")
    monkeypatch.setenv("CRB_SESSION_TTL_S", "not-a-number")  # a server key: irrelevant here
    shared = worker_main._shared_settings()
    gh = shared.github
    assert gh.app_id == "12345" and gh.app_slug == "crb-bench"
    assert shared.metrics_enabled is True and shared.metrics_port == 9464
    assert shared.metrics_host == "127.0.0.1"
    monkeypatch.setenv("CRB_METRICS_HOST", "0.0.0.0")
    assert worker_main._shared_settings().metrics_host == "0.0.0.0"
    monkeypatch.setenv("CRB_GITHUB__API_URL", "ftp://not-https")
    with pytest.raises(pydantic.ValidationError):
        worker_main._shared_settings()


def test_delivery_credentials_follow_a_linked_row_to_its_own_https_remote() -> None:
    """After ``POST /repos/{name}/github-link`` a row carries ``config_json.github`` and an
    https URL on the app's host: the worker resolves a delivery provider for THAT remote and
    for no other — the CWE-201 rule (a token goes only to the host the link was made for)
    holds for a linked row exactly as for a connected one. A stub app stands in for GitHub;
    no key, no network."""
    from crb.server.settings import GitHubAppSettings

    class _Inst:
        can_deliver = True

    class _StubApp:
        def installation(self, iid: int) -> _Inst:
            assert iid == 78
            return _Inst()

        def installation_token(self, iid: int) -> str:
            return f"ghs_stub_{iid}"

    worker = Worker.__new__(Worker)
    worker.settings = WorkerSettings(
        home=Path("/nonexistent"),
        github=GitHubAppSettings(app_id="1", app_slug="crb", private_key="-----BEGIN"),
    )
    worker._github_app_client = _StubApp()  # type: ignore[assignment]
    linked = {
        "language": "go",
        "runner": "go",
        "url": "https://github.com/acme/cobra.git",
        "github": {"installation_id": 78, "full_name": "acme/cobra"},
    }
    provider = worker._delivery_credentials(linked, linked["url"])
    assert provider is not None and provider.resolve("cobra").remote == linked["url"]
    # the link names the installation, but the remote decides where a token may go
    assert worker._delivery_credentials(linked, "https://evil.example/acme/cobra.git") is None
    assert worker._delivery_credentials(linked, "http://github.com/acme/cobra.git") is None
    # a row with no link (a URL-only registration) gets no credentials at all
    assert worker._delivery_credentials({"url": linked["url"]}, linked["url"]) is None


# --- ADR-0019: the posture gate --------------------------------------------------------------


def _live_posture(h: Harness) -> Any:
    from crb.core.deps import NullDepsProvider
    from crb.server.posture_gate import resolve_run_posture

    runner = PytestRunner(h.pyrepo.config)
    return resolve_run_posture(
        LocalExecutor(), runner, h.pyrepo.config, NullDepsProvider(), root=h.pyrepo.path
    )


def _seed_qualified(h: Harness, task: TaskSpec, *, posture_id: str = "", **kw: Any) -> Any:
    """Append a ``qualified`` record for ``task`` (in the live posture unless named)."""
    from crb.core.qualify import STATE_QUALIFIED, Qualification
    from crb.store import qualifications as sq

    posture = _live_posture(h)
    q = Qualification(
        qualification_id="",
        repo=task.repo,
        task_id=task.task_id,
        posture_id=posture_id or posture.posture_id,
        posture=posture.to_dict(),
        state=STATE_QUALIFIED,
        red={"kind": "tests_failed", "failing": []},
        baseline_failing=task.baseline_failing,
        gold={"clean": True, "lint": None},
        **kw,
    )
    with h.factory() as s:
        sq.append(s, q)
    return q


def _records(h: Harness) -> list[Any]:
    from crb.core.qualify import Qualification
    from crb.store.models import TaskQualification

    with h.factory() as s:
        rows = s.execute(select(TaskQualification).order_by(TaskQualification.seq)).scalars().all()
        return [Qualification.from_dict(r.body_json) for r in rows]


def test_replay_with_no_qualified_task_fails_before_spend(h: Harness) -> None:
    run = h.enqueue("replay", params_json={"qualify_first": False})
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith("POSTURE_UNQUALIFIED: 0 of 1 task(s) qualified")
    assert "crb repo qualify" in done.error and "no model money" in done.error
    assert FakeBuilder.briefs == []  # no builder was called
    assert list(h.worker.ledger.rows(run_id=run.id)) == []
    ev = h.events(run.id)
    refused = next(e for e in ev if e.action == "run.posture_refused")
    assert refused.payload["code"] == "POSTURE_UNQUALIFIED"
    assert refused.payload["refusals"][0]["code"] == "POSTURE_UNQUALIFIED"
    assert refused.payload["refusals"][0]["fix"]
    assert any(e.action == "run.posture" for e in ev)


def test_qualify_first_qualifies_then_replays_only_the_qualified(h: Harness) -> None:
    green = h.pyrepo.add_green_commit()
    h.add_task(
        h.pyrepo.feat_task(
            task_id=green,
            test_files=[pr.TEST_CALC],
            target_tests=[pr.TEST_CALC],
            baseline_failing=[],
            subject="refactor: green at parent",
        )
    )
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["tasks"] == 1 and done.counts_json["clean"] == 1
    assert done.counts_json["refusals"] == {"QUAL_NOT_RED": 1}
    records = _records(h)
    assert sorted(q.state for q in records) == ["qualified", "unqualified"]
    (row,) = list(h.worker.ledger.rows(run_id=run.id))
    assert row.labels["qualification_id"] == next(
        q.qualification_id for q in records if q.is_qualified
    )
    assert row.labels["posture_id"] == _live_posture(h).posture_id
    ev = h.events(run.id)
    canary = next(e for e in ev if e.action == "run.canary")
    assert canary.payload["clean"] is True
    assert sum(1 for e in ev if e.action == "qualify.task") == 2


def test_posture_drift_fails_at_zero_spend(h: Harness) -> None:
    _seed_qualified(h, h.pyrepo.feat_task(), posture_id="pst_" + "d" * 24)
    run = h.enqueue("replay", params_json={"qualify_first": False})
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("POSTURE_DRIFT:")
    assert "qualify again" in done.error
    assert FakeBuilder.briefs == [] and list(h.worker.ledger.rows(run_id=run.id)) == []


def test_canary_not_clean_fails_before_the_first_build(h: Harness) -> None:
    bad = h.pyrepo.add_bad_gold_commit()
    task = h.pyrepo.feat_task(
        task_id=bad,
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[],
        subject="feat: add multiply (breaks add)",
    )
    with h.factory() as s:
        s.query(Task).delete()
        s.commit()
    h.add_task(task)
    # qualified here once — the posture then moved under it (the gold now breaks belt 3)
    _seed_qualified(h, task)
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("POSTURE_CANARY_FAILED:")
    assert FakeBuilder.briefs == [] and list(h.worker.ledger.rows(run_id=run.id)) == []
    canary = next(e for e in h.events(run.id) if e.action == "run.canary")
    assert canary.payload["clean"] is False


def test_two_environment_rows_stop_the_run_and_revoke_the_qualifications(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.core.grade import BLAME_GOLD_GREEN, ControlRun
    from crb.server import posture_gate

    class RedGold:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def control(self, scope: Any, *, why: str, allow_failing: Any = None) -> ControlRun:
            return ControlRun(BLAME_GOLD_GREEN, tuple(scope), False, rc=1, tail="lookup failed")

    monkeypatch.setattr(posture_gate, "GoldWitness", RedGold)
    monkeypatch.setitem(
        builders_pkg._REGISTRY, "fake", lambda **cfg: FakeBuilder(behaviour="noop", **cfg)
    )
    bad = h.pyrepo.add_bad_gold_commit()
    second = h.pyrepo.feat_task(
        task_id=bad,
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[],
    )
    h.add_task(second)
    _seed_qualified(h, h.pyrepo.feat_task())
    _seed_qualified(h, second)
    run = h.enqueue(
        "replay",
        ladder_json=["fake:m0", "fake:m1"],
        params_json={"canary": False, "task_ids": [h.pyrepo.feat_sha, bad]},
    )
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("environment: 2 consecutive")
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert len(rows) == 2 and all(r.failure_kind == "harness" for r in rows)
    assert all(r.labels["env_code"] == "GOLD_CONTROL_RED" for r in rows)
    assert all(r.trial == "r1" for r in rows)  # each ladder stopped at its first rung
    states = [q.state for q in _records(h)]
    assert states.count("revoked") == 2  # both qualifications revoked, as new records
    assert any(e.action == "run.environment_stop" for e in h.events(run.id))


def test_only_a_control_that_ran_red_revokes_a_qualification(tmp_path: Path) -> None:
    """QUAL_ENV_WITNESS_RED says the gold failed here during a replay, so only a row whose
    control RAN red (``env_code`` ``GOLD_CONTROL_RED``) may revoke. An environment row no
    control witnessed (``TEST_RUN_ENVIRONMENT``) leaves the record in force."""
    from types import SimpleNamespace

    from crb.core.execution import LocalExecutor
    from crb.server.posture_gate import PostureGate
    from fixtures.posture import discovery_qualification

    task = pr.build(tmp_path / "repo").feat_task()
    q = discovery_qualification(task, LocalExecutor())
    gate = PostureGate(
        repo=None,  # type: ignore[arg-type]  # on_environment reads none of these
        config=None,  # type: ignore[arg-type]
        runner=None,  # type: ignore[arg-type]
        executor=None,  # type: ignore[arg-type]
        scratch=tmp_path,
        provider=None,  # type: ignore[arg-type]
        posture=None,  # type: ignore[arg-type]
    )
    gate.qualifications[task.task_id] = q
    unwitnessed = SimpleNamespace(
        error="environment: tree_copy_failed", labels={"env_code": "TEST_RUN_ENVIRONMENT"}
    )
    gate.on_environment(task, unwitnessed)  # type: ignore[arg-type]
    assert gate.qualifications[task.task_id] is q and q.is_qualified
    red = SimpleNamespace(
        error="environment: gold control red in pst_x: belt 2",
        labels={"env_code": "GOLD_CONTROL_RED"},
    )
    gate.on_environment(task, red)  # type: ignore[arg-type]
    revoked = gate.qualifications[task.task_id]
    assert revoked.state == "revoked" and revoked.code == "QUAL_ENV_WITNESS_RED"


def test_qualify_run_spends_nothing(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("a qualify run constructed a builder")

    monkeypatch.setattr(builders_pkg, "get_builder", refuse)
    monkeypatch.setattr(builders_pkg, "builder_for_rung", refuse)
    run = h.enqueue("qualify")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["qualified"] == 1 and done.counts_json["unqualified"] == 0
    assert done.counts_json["cost_usd"] == 0.0 and done.counts_json["by_code"] == {}
    assert done.counts_json["posture_id"] == _live_posture(h).posture_id
    assert list(h.worker.ledger.rows(run_id=run.id)) == []  # no grade row: nothing was built
    (q,) = _records(h)
    assert q.is_qualified and q.run_id == run.id
    assert any(e.action == "qualify.done" for e in h.events(run.id))


def test_mine_in_docker_without_provisioning_says_what_to_do(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sealed posture as shipped cannot load a module graph (ADR-0019 D1): the mine's
    qualification refuses each candidate QUAL_ENV_UNLOADABLE and the run stops with what to
    do, instead of mining tasks every replay would then charge to the model. (The real
    sealed image is exercised in tests/test_posture_docker.py.)"""
    import sys as _sys

    from crb.core.execution import Command

    def unloadable(self: Any, root: Path, scope: Any, *, executor: Any, timeout: int) -> Command:
        return Command((_sys.executable, "-c", "import sys; sys.exit(1)"), root, timeout=timeout)

    monkeypatch.setattr(PytestRunner, "env_probe_command", unloadable)
    for i in range(3):
        pr._write(h.pyrepo.path, pr.SRC, pr.SRC_FEAT.replace("A tiny calculator.", f"v{i}."))
        pr._write(
            h.pyrepo.path,
            pr.TEST_CALC,
            pr.TEST_CALC_SRC + f"\n\ndef test_zero_{i}():\n    assert add(0, 0) == 0\n",
        )
        pr._commit(h.pyrepo.path, f"refactor: v{i}")
    run = h.enqueue("mine", params_json={"target": 5})
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert "QUAL_ENV_UNLOADABLE" in done.error
    assert "switch provisioning on and qualify" in done.error
    skips = [e for e in h.events(run.id) if e.action == "mine.skip"]
    assert skips and all(e.payload.get("code") == "QUAL_ENV_UNLOADABLE" for e in skips)


def test_route_gate_reads_the_deployment_posture_only(h: Harness) -> None:
    """ADR-0019 §8: a cell measured in another posture never licenses a delivery here. The
    same factory rows read under the worker's own class count; under another class, none."""
    home, item, _ = _multiply_backlog(h)
    first = h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    rows = [r for r in h.worker.ledger.rows(repo=pr.REPO_NAME) if r.run_id == first.id]
    assert rows and all(r.posture_class == "local/inplace/host-env" for r in rows)
    here = h.worker._route_lookup(pr.REPO_NAME)(item)  # this worker: local/inplace/host-env
    assert here is not None and here["n"] == len(rows)
    assert h.worker._route_lookup(pr.REPO_NAME, "", "docker/copy/sealed")(item) is None
    del home
