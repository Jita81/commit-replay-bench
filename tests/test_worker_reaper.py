"""The worker's unconfirmed container kills: visible on the run, and reaped by the loop.

Navigation
----------
What it is:   The worker's reaper tests, moved out of tests/test_worker.py so the suite's
              shards stay inside their time budget (files are the shard unit).
What it does: Pins that a sealed attempt whose container kill went UNCONFIRMED is visible
              (``run.kill_unconfirmed`` on the trace, the note on the run's error,
              ``kill_confirmed: false`` in the pack) and reaped (the loop's pass writes
              ``run.kill_reaped`` / ``run.kill_reap_failed``; the check-in row counts what is
              pending); that the run's own docker executor (the grade stage's test run) reports
              an unconfirmed kill through the same seam (event under the task, note, reaper
              queue); and that a reap pass is budgeted to ``heartbeat_s / 2`` so a daemon that
              answers nothing cannot hold the loop past the worker's liveness bound — the
              check-in still lands.
How:          The ``Harness`` and ``h`` fixture of tests/test_worker.py, with a scripted docker
              session and a slow daemon standing in for the real one; no docker, no network.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/worker.py (under test), src/crb/server/reaper.py (the reaper the
              loop drives), tests/test_worker.py (the shared harness)
Tested by:    tests/test_worker_reaper.py
Touch when:   never for a new repository; the kill-confirmation seam or the reaper's budget
              changes.
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter as adapter_mod
from crb.builders.base import BuildBrief
from crb.builders.container import BuilderContainerSettings, SealedCheckout, UnconfirmedKill
from crb.core.evidence import verify_pack
from crb.core.execution import ExecResult, LocalExecutor
from crb.core.workspace import Workspace
from crb.observability.events import StepStatus
from crb.server import worker as worker_mod
from crb.server.reaper import ContainerReaper
from crb.store.jobs import STATUS_CANCELLED
from crb.store.models import WorkerRow
from fixtures import pyrepo as pr
from test_worker import FakeBuilder, Harness, _seed_qualified


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    """``test_worker``'s autouse registration is module-local; restore ``fake`` per test."""
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    """The worker harness with the repo registered and its one mined task on file."""
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


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


def _scripted_docker(dir_: Path, *, gone: bool) -> str:
    """A ``docker`` for the reaper: ``inspect`` answers "No such container" (gone) or
    Running=true (never lets go); ``rm -f`` succeeds or fails with it. A daemon that is slow
    to answer is ``_SlowDaemon``, in process (P-014)."""
    dir_.mkdir(parents=True, exist_ok=True)
    script = dir_ / "docker"
    inspect = 'echo "Error: No such container: $4" >&2; exit 1' if gone else "echo true"
    rm = ":" if gone else "exit 1"
    script.write_text(f'#!/bin/sh\ncase "$1" in\n  inspect) {inspect} ;;\n  rm) {rm} ;;\nesac\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _realistic_heartbeat(h: Harness, heartbeat_s: float = 2.0) -> None:
    """The harness polls at 50 ms; a reap pass is budgeted to ``heartbeat_s / 2``, so a
    test that expects a scripted ``docker`` to be reached in one pass needs a real one."""
    h.worker.settings = replace(h.worker.settings, heartbeat_s=heartbeat_s)


@pytest.fixture
def sealed_unconfirmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The worker's docker builder posture with the session doubled: every sealed attempt
    reports an unconfirmed kill. The worker runs as uid 0 here (a root container), so the
    posture must name its non-root user rather than inherit the worker's uid; pytest's base
    temporary directory is created first because its ownership check reads ``os.getuid``."""
    tmp_path_factory.getbasetemp()
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "getgid", lambda: 0)
    monkeypatch.setenv("CRB_BUILDER__EXECUTOR", "docker")
    monkeypatch.setenv("CRB_BUILDER__USER", "10001:10001")
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


class _SlowDaemon:
    """A daemon that takes ``delay_s`` to answer anything, in process: each question sleeps
    the smaller of the delay and the call's timeout, then answers "still running" or times
    out. No process is spawned, so a loaded machine cannot turn spawn latency into a red
    build (docs/PREVENTION.md P-014); the delay dwarfs the budget, so the bound still
    discriminates."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def stopped(self, docker: str, name: str, *, timeout_s: float) -> bool | None:
        time.sleep(min(self.delay_s, timeout_s))
        return None if self.delay_s > timeout_s else False

    def runner(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        timeout = float(kw["timeout"])
        time.sleep(min(self.delay_s, timeout))
        if self.delay_s > timeout:
            raise subprocess.TimeoutExpired(argv, timeout)
        return subprocess.CompletedProcess(argv, 1, "", "refused")


def test_reap_pass_is_budgeted_so_the_check_in_still_lands(h: Harness, tmp_path: Path) -> None:
    """A daemon that answers nothing inside the budget (every call takes 10 s) with two
    containers queued: a pass ends within ``heartbeat_s / 2`` — the entry it ran out on
    counts one attempt with the reason, the entry it never reached is untouched — and the
    polling loop's check-in row is never older than the worker's liveness bound
    (``3 × heartbeat_s``) while passes are running."""
    heartbeat_s = 2.0
    _realistic_heartbeat(h, heartbeat_s)
    assert h.worker.reap_budget_s == heartbeat_s / 2
    daemon = _SlowDaemon(delay_s=10.0)
    h.worker.reaper = ContainerReaper(
        h.worker.reaper.path, runner=daemon.runner, stopped=daemon.stopped
    )
    h.worker.reaper.add("crb-build-slow-1", run_id="r1", task_id="t1")
    h.worker.reaper.add("crb-build-slow-2", run_id="r2", task_id="t2")
    t0 = time.monotonic()
    assert h.worker.reap() == 0
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, elapsed  # the 1 s budget, not 10 s x (inspect + rm + inspect)
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
