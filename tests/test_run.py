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
              that an honest gold still grades clean under the same pre-flight. Pins that no
              fragment of the held-out commit's sha reaches the builder (worktree path, ``.git``
              pointer, environment, prompt; assessment 2026-09-25 B1), that the run's events map
              the opaque name back to the task, and that no worktree destination in the source
              tree is built from a commit sha.
How:          A ``RunSpec`` over ``pyrepo`` with a ``BuildAttempt`` that performs the edit; the
              ledger row is read back and the chain verified. The leakage cases drive the real
              ``claude_code`` adapter with a recording spawn (tests/fixtures/leakage.py) and scan
              what it was handed with the fixture's real sha; the source ratchet reads
              ``src/crb`` line by line.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/run.py (under test), src/crb/core/workspace.py
              (``enforce_integrity``, ``opaque_dest``), tests/fixtures/leakage.py (the sha
              scan), tests/test_builders_adapter.py (the full ``run`` end to end),
              tests/test_grade.py (the same findings at the grader)
Tested by:    tests/test_run.py
Touch when:   a new integrity violation is added to the workspace (mirror the case here so the
              run path and the CLI stay in step); a new place creates a worktree a builder or a
              grader runs in (it must take ``opaque_dest``, or the ratchet here fails).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from crb.builders.adapter import build_fn_for, ladder_from_spec
from crb.builders.base import Budget
from crb.core.evidence import BuilderRef
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.run import BuildAttempt, RunSpec, run_task
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.leakage import RecordingSpawn, leaks

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


# ---------------------------------------------------------------------------
# B1 (assessment 2026-09-25): the held-out commit's sha never reaches the builder
# ---------------------------------------------------------------------------


def _claude_build_fn(spec: RunSpec, spawn: RecordingSpawn, **kw: Any) -> Any:
    """The real ``claude_code`` adapter path with the CLI process replaced by ``spawn``."""
    return build_fn_for(
        ladder_from_spec(["claude_code:claude-opus-5"]),
        budget=Budget(max_turns=5, max_tool_calls=10, wall_clock_s=60),
        runner=spec.runner,
        executor=spec.executor,
        config=spec.config,
        builder_overrides={
            "spawn": spawn,
            "claude_binary": "/fake/claude",
            "keep_transcript": True,
        },
        **kw,
    )


@pytest.mark.parametrize("mode", ["sighted", "blind"])
def test_the_builder_is_handed_no_fragment_of_the_task_sha(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """The worktree path, its ``.git`` pointer, the builder's environment and its prompt
    (argv) carry no 7-character substring of the task's real sha, in either mode."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real-0000000000000000")
    sha = feat_task.task_id
    assert len(sha) == 40  # the fixture's REAL commit sha, not a stand-in
    spec = RunSpec(
        run_id="run-leak",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp_path / "scratch",
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        evidence_dir=tmp_path / "evidence",
        mode=mode,
        ladder=("claude_code:claude-opus-5",),
    )
    spawn = RecordingSpawn()
    events: list[tuple[str, dict[str, Any]]] = []
    run_task(
        spec,
        pyrepo.repo,
        feat_task,
        _claude_build_fn(spec, spawn),
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    assert spawn.cwd is not None, "the builder was never started"
    assert leaks(sha, str(spawn.cwd)) == [], f"worktree path {spawn.cwd}"
    assert leaks(sha, spawn.git_file) == [], f".git pointer {spawn.git_file!r}"
    assert leaks(sha, *(f"{k}={v}" for k, v in spawn.env.items())) == []
    assert leaks(sha, *spawn.argv) == [], "the prompt names the sha"
    # the mapping lives in the run's events, never in the path
    (prep,) = [p for a, p in events if a == "prep.start"]
    assert prep["task"] == sha and prep["worktree"] == spawn.cwd.name


def test_every_attempt_gets_its_own_opaque_worktree(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    """Two rungs of one task: two distinct names, neither derived from the task or the run."""
    seen: list[Path] = []

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        seen.append(ws.root)
        return _attempt()  # an empty build: not clean, so the ladder climbs

    spec = _spec(pyrepo, runner, executor, tmp_path)
    run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert len(seen) == 2 and seen[0] != seen[1]
    for root in seen:
        assert leaks(feat_task.task_id, root.name) == []
        assert spec.run_id not in root.name


#: Where a worktree destination is built: a path joined with an f-string.
_DEST = re.compile(r"/\s*f[\"'][^\"']*\{[^}]*(short_id|sha\[|task_id\[|\.sha\b|task_id\})")
#: Forward mode (the factory): the commit a worktree is named after is the harness's own
#: RED-proven oracle commit or the base the builder already stands on — never a held-out
#: answer. Every other destination must be opaque (``crb.core.workspace.opaque_dest``).
_FORWARD_MODE = {
    "src/crb/factory/build.py",
    "src/crb/factory/review.py",
    "src/crb/factory/testfirst.py",
}


def test_no_worktree_destination_is_built_from_a_commit_sha() -> None:
    """The ratchet for the class, not the instance: a new ``scratch / f"…{task.short_id}…"``
    anywhere outside forward mode fails here before it can reach a builder; and nothing
    under ``crb.builders`` names a task's ``short_id`` (the container label, the transcript
    file) at all."""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted((root / "src" / "crb").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if rel not in _FORWARD_MODE and _DEST.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
            if rel.startswith("src/crb/builders/") and "short_id" in line:
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert offenders == [], "worktree names built from a commit sha:\n" + "\n".join(offenders)
