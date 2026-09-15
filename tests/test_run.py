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

from crb.core.evidence import BuilderRef
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.run import BuildAttempt, RunSpec, run_task
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

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
