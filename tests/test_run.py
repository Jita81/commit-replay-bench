"""crb.core.run — the orchestrator grades under the same worktree-integrity pre-flight
as the CLI (independent review pass, 2026-09-14, finding 1(b): ``run_task`` graded a
worktree whose builder had committed the poison ``clean``; the CLI pinned HEAD, the
run path did not).

Navigation
----------
What it is:   The orchestrator's regression suite for the worktree-integrity pre-flight
              (independent review pass 2026-09-14, finding 1(b)).
What it does: Pins that ``run_task`` disqualifies a worktree whose builder committed the poison
              or hid it in ``info/exclude`` — the CLI pinned HEAD, the run path did not — and
              that an honest gold still grades clean under the same pre-flight.
How:          A ``RunSpec`` over ``pyrepo`` with a ``BuildAttempt`` that performs the edit; the
              ledger row is read back and the chain verified.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/run.py (under test), src/crb/core/workspace.py
              (``enforce_integrity``), tests/test_builders_adapter.py (the full ``run`` end to
              end), tests/test_grade.py (the same findings at the grader)
Tested by:    tests/test_run.py
Touch when:   a new integrity violation is added to the workspace (mirror the case here so the
              run path and the CLI stay in step).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core.evidence import BuilderRef
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.run import BuildAttempt, RunSpec, run_task
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.posture import witnessed_context_for

_POISON = 'import calc as _m\nexec("def subtract(a, b):\\n    return a - b\\n", _m.__dict__)\n'


def _spec(pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp: Path) -> RunSpec:
    return RunSpec(
        run_id="run-integrity",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp / "scratch",
        ledger=JsonlLedger(tmp / "ledger.jsonl"),
        evidence_dir=tmp / "evidence",
        ladder=("r1", "r2"),
        context_for=witnessed_context_for(
            pyrepo.repo, pyrepo.config, runner=runner, executor=executor, scratch=tmp / "scratch"
        ),
    )


def _attempt() -> BuildAttempt:
    return BuildAttempt(BuilderRef(name="fixture", model="m", provider="p", mode="sighted"))


def test_run_task_disqualifies_a_worktree_whose_builder_committed_the_poison(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        (ws.root / "conftest.py").write_text(_POISON, encoding="utf-8")
        with (ws.root / pr.SRC).open("a", encoding="utf-8") as fh:
            fh.write("# touched\n")
        pr.git(ws.root, "add", "-f", "conftest.py")
        pr.git(ws.root, "commit", "-q", "-m", "hide the poison")
        return _attempt()

    events: list[tuple[str, dict[str, Any]]] = []
    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(
        spec, pyrepo.repo, feat_task, build_fn, on_event=lambda a, p: events.append((a, dict(p)))
    )
    assert outcome.clean is False and outcome.disqualified is True
    assert outcome.attempts == 1  # a disqualified attempt stops the ladder
    (row,) = outcome.rows
    assert row.disqualified and row.dq_reason.startswith("worktree integrity")
    assert row.tests_unmodified is False and row.clean is False
    assert row.failure_kind == "disqualified"
    assert verify_chain(spec.ledger.rows()) == 1
    tamper = [p for a, p in events if a == "grade.tamper"]
    assert tamper and tamper[0]["kind"] == "worktree" and tamper[0]["files"] == [".git/HEAD"]


def test_run_task_disqualifies_a_poison_hidden_in_info_exclude(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    exclude = pyrepo.path / ".git" / "info" / "exclude"

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        (ws.root / "conftest.py").write_text(_POISON, encoding="utf-8")
        with (ws.root / pr.SRC).open("a", encoding="utf-8") as fh:
            fh.write("# touched\n")
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write("conftest.py\n")
        return _attempt()

    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert outcome.clean is False and outcome.disqualified is True
    (row,) = outcome.rows
    assert "info/exclude" in row.dq_reason
    assert "conftest.py" not in exclude.read_text(
        encoding="utf-8"
    )  # the shared file is clean again


def test_run_task_honest_gold_is_clean_under_the_pre_flight(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        pr.apply_gold(ws)
        return _attempt()

    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert outcome.clean is True and outcome.attempts == 1
    (row,) = outcome.rows
    assert row.clean and row.evidence_pack_hash and row.failure_kind == ""


# ---------------------------------------------------------------------------
# ADR-0019: the context before the builder; the environment stops the ladder
# ---------------------------------------------------------------------------


def test_unqualified_task_never_reaches_build_fn(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from crb.core.posture import PostureMismatch
    from crb.core.run import run

    calls: list[str] = []

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        calls.append(task.task_id)
        return _attempt()

    def unqualified(task: TaskSpec) -> Any:
        raise PostureMismatch(f"{task.task_id[:10]} is unqualified in pst_x (QUAL_NOT_RED)")

    spec = replace(_spec(pyrepo, runner, executor, tmp_path), context_for=unqualified)
    summary = run(spec, pyrepo.repo, [feat_task], build_fn)
    assert calls == []  # the builder was never called: nothing was spent
    assert summary.rows == 0 and "QUAL_NOT_RED" in summary.stopped_reason
    assert list(spec.ledger.rows()) == []
    with pytest.raises(ValueError, match="context_for"):
        replace(spec, context_for=None)


def test_an_environment_row_stops_the_ladder_and_reports_it(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from crb.core.grade import BLAME_GOLD_GREEN, ControlRun
    from crb.core.ledger import GradeRow
    from fixtures.posture import context

    class _RedGold:
        def control(self, scope: Any, *, why: str, allow_failing: Any = None) -> ControlRun:
            return ControlRun(
                BLAME_GOLD_GREEN, tuple(scope), False, rc=1, tail="network is unreachable"
            )

    reported: list[tuple[str, GradeRow]] = []
    builds: list[str] = []

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        builds.append(rung)
        return _attempt()  # does nothing: the target stays red

    spec = replace(
        _spec(pyrepo, runner, executor, tmp_path),
        context_for=lambda t: context(t, executor, witness=_RedGold())[1],
        on_environment=lambda t, row: reported.append((t.task_id, row)),
    )
    outcome = run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert builds == ["r1"]  # the ladder has r1 and r2: the second rung was never paid for
    (row,) = outcome.rows
    assert row.error.startswith("environment: gold control red") and row.failure_kind == "harness"
    assert reported == [(feat_task.task_id, row)]
