"""The format step and the finish gate around a real build and a real grade.

Navigation
----------
What it is:   The integration suite for the "clean means working" switches in the builder
              adapter: a scripted fixture builder on the Python fixture repository, graded for
              real by pytest and the repository's own formatter.
What it does: Pins that the format step turns a correct but unformatted patch into a clean
              row (and that without it the same patch fails belt 5); that the finish gate puts
              the checklist in the brief, re-runs it, spends ONE bounded repair call with the
              failing output and records ``before → repair → after`` on the row; that a blind
              checklist naming the held-out oracle is refused before any builder call; that an
              attempt that errored gets no step (named skip); and that with no switchboard the
              rows carry none of the labels.
How:          ``adapter.build_fn_for(..., checks=resolve(...))`` driven by ``crb.core.run.run``
              over ``tests/fixtures/pyrepo.py``; the formatter is the real ``ruff format``, the
              declared check a real shell command in the worktree; the builder is scripted.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0024-working-by-construction.md
Works with:   src/crb/builders/adapter.py (under test), src/crb/core/formatting.py (the
              format step it drives), src/crb/core/finish_gate.py (the gate it drives),
              src/crb/core/checks.py (the switchboard the run resolves), tests/fixtures/pyrepo.py
              (the repository graded for real)
Tested by:    tests/test_builders_finish_gate.py
Touch when:   the adapter's order of steps (build → format → gate → pre-flight → grade) or a
              row label changes.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import (
    STOP_DONE,
    STOP_MODEL_ERROR,
    Budget,
    BuildBrief,
    BuildOutcome,
    EscalationLadder,
    EventFn,
    Rung,
)
from crb.core.checks import RepoChecks, resolve
from crb.core.execution import LocalExecutor
from crb.core.ledger import GradeRow, JsonlLedger
from crb.core.lint import LintPlan, LintTool
from crb.core.run import RunSpec, run
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.posture import witnessed_context_for

RUFF = shutil.which("ruff") or str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "ruff")

#: The gold, written the way a model might: correct, and not how ``ruff format`` writes it.
UGLY_SUBTRACT = "\n\ndef subtract(a,b):\n    return a-b\n"
#: A test file the builder adds, as unformatted as the source.
UGLY_TEST = "tests/test_extra.py"
UGLY_TEST_SRC = "def test_extra( ):\n    assert  True\n"


class ScriptedBuilder:
    """Registered as ``scripted``; ``behaviour`` picks the edit."""

    name = "scripted"
    briefs: ClassVar[list[BuildBrief]] = []

    def __init__(self, *, model: str, provider: str = "", behaviour: str = "", **_: Any) -> None:
        if behaviour == "unavailable":
            raise RuntimeError("no such model on this endpoint")
        self.model, self.provider, self.behaviour = model, provider, behaviour

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        ScriptedBuilder.briefs.append(brief)
        base = {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "mode": brief.mode,
        }
        src = workspace.root / pr.SRC
        if self.behaviour == "model_error":
            return BuildOutcome(**base, stop_reason=STOP_MODEL_ERROR, errors=("model_error: boom",))
        if self.behaviour == "raise":
            raise RuntimeError("the CLI crashed")
        if brief.gate_note and self.behaviour == "todo_repair_error":
            # the repair call never reached the model (a 429, a dead credential)
            return BuildOutcome(
                **base,
                stop_reason=STOP_MODEL_ERROR,
                errors=("model_error: 429 rate limited",),
                cost_usd=0.005,
            )
        if brief.gate_note:
            # the repair call: fix what the gate reported, nothing else
            src.write_text(
                src.read_text(encoding="utf-8").replace("# TODO\n", ""), encoding="utf-8"
            )
        else:
            text = src.read_text(encoding="utf-8") + UGLY_SUBTRACT
            if self.behaviour.startswith("todo"):
                text += "# TODO\n"
            src.write_text(text, encoding="utf-8")
            if self.behaviour == "newtest":
                # a NEW test file, unformatted: the format step must never touch it
                (workspace.root / UGLY_TEST).write_text(UGLY_TEST_SRC, encoding="utf-8")
        return BuildOutcome(
            **base, done=True, stop_reason=STOP_DONE, cost_usd=0.01, latency_s=0.1, budget=budget
        )


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "scripted", ScriptedBuilder)
    ScriptedBuilder.briefs = []


class _FormattedRunner(PytestRunner):
    """The fixture repository with ``ruff format`` as its configured formatter (belt 5)."""

    def lint_plan(self, root: Path, executor: Any) -> LintPlan | None:
        return LintPlan(
            (LintTool("ruff-format", (RUFF, "format", "--check"), exts=(".py",)),), "ruff-format"
        )


def _run(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    behaviour: str,
    checks: dict[str, Any] | None,
    *,
    mode: str = "sighted",
    run_checks: dict[str, Any] | None = None,
) -> tuple[list[GradeRow], list[tuple[str, dict[str, Any]]]]:
    runner = _FormattedRunner(pyrepo.config)
    ladder = EscalationLadder((Rung("scripted", "m", config={"behaviour": behaviour}),))
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-checks",
        config=pyrepo.config,
        runner=runner,
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        mode=mode,
        ladder=adapter.ladder_labels(ladder),
        # ADR-0019 (PR #56): every run grades each task in its own posture context
        context_for=witnessed_context_for(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=LocalExecutor(),
            scratch=tmp_path / "scratch",
            # the fixture's gold passes belt 5, so a lint rejection is the model's (ADR-0019)
            gold_lint=True,
        ),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    resolved = (
        None
        if checks is None and run_checks is None
        else resolve(RepoChecks.from_config(checks), run_checks)
    )
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=runner,
        executor=LocalExecutor(),
        config=pyrepo.config,
        on_event=lambda a, p: events.append((a, dict(p))),
        checks=resolved,
    )
    run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    return list(ledger.rows()), events


needs_ruff = pytest.mark.skipif(not Path(RUFF).exists(), reason="ruff not available")


@needs_ruff
def test_without_the_format_step_a_correct_unformatted_patch_fails_belt_5(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    (row,), _ = _run(pyrepo, tmp_path, "", None)
    assert row.target_green is True and row.repo_lint_clean is False and not row.clean
    assert not {"checks", "format_step", "finish_gate"} & set(row.labels)


@needs_ruff
def test_the_format_step_makes_the_graded_patch_the_formatted_one(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    (row,), events = _run(pyrepo, tmp_path, "", None, run_checks={"format_step": True})
    assert row.clean is True and row.repo_lint_clean is True
    assert row.labels["checks"].startswith("fmt=1:run;gate=0:default;api=0:default;cfg=default")
    assert row.labels["format_step"] == "ran=ruff-format;changed=1"
    assert row.builder == "scripted"  # the same arm name: the label, not the name, records it
    assert any(a == "builder.format_step" for a, _ in events)
    assert len(ScriptedBuilder.briefs) == 1 and not ScriptedBuilder.briefs[0].finish_checks


@needs_ruff
def test_the_format_step_never_touches_a_test_file_the_builder_wrote(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The format step's file list excludes test files at the adapter, not only by what the
    workspace reports: a builder's own new test file is never formatted (P-032)."""
    _, events = _run(pyrepo, tmp_path, "newtest", None, run_checks={"format_step": True})
    (fmt,) = [p for a, p in events if a == "builder.format_step"]
    assert fmt["ran"] == ["ruff-format"]
    assert fmt["changed"] == [pr.SRC]


@needs_ruff
def test_the_finish_gate_verifies_repairs_once_and_records_before_and_after(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    style = {"name": "style", "argv": ["sh", "-c", f"! grep -q TODO {pr.SRC}"]}
    checks = {"format_step": True, "finish_gate": True, "commands": [style]}
    (row,), events = _run(pyrepo, tmp_path, "todo", checks)
    first, second = ScriptedBuilder.briefs
    assert first.finish_checks[0].startswith("1. ruff-format: ")
    assert first.finish_checks[1] == f"2. style: sh -c ! grep -q TODO {pr.SRC}"
    assert "FINISH GATE — the repository's own checks" in first.task_text()
    assert first.gate_note == "" and "[style]" in second.gate_note
    assert "FINISH GATE FAILED" in second.task_text()
    assert row.labels["finish_gate"] == "before=fail:style;repair=1;after=pass"
    # the first formatting record survives the repair; the repair's own is appended
    assert row.labels["format_step"].startswith(
        "ran=ruff-format;changed=1;repair:ran=ruff-format;changed="
    )
    assert row.labels["checks"].startswith("fmt=1:repo;gate=1:repo;api=0:default;cfg=")
    assert row.clean is True and row.cost_usd == 0.02  # both calls are one attempt's spend
    assert any(a == "builder.finish_gate" and p["passed"] for a, p in events)


@needs_ruff
def test_with_no_repair_turn_the_gate_records_the_failure_and_the_grade_still_judges(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    style = {"name": "style", "argv": ["sh", "-c", f"! grep -q TODO {pr.SRC}"]}
    checks = {"finish_gate": True, "finish_repair_turns": 0, "commands": [style]}
    (row,), _ = _run(pyrepo, tmp_path, "todo", checks)
    assert len(ScriptedBuilder.briefs) == 1
    assert row.labels["finish_gate"] == "before=fail:lint+style"
    assert row.repo_lint_clean is False and not row.clean  # the belts, not the gate, decide


def test_a_blind_checklist_that_names_the_oracle_is_refused_before_any_spend(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    leak = {"name": "peek", "argv": ["pytest", pr.TEST_SUBTRACT], "blind_only": True}
    (row,), _ = _run(pyrepo, tmp_path, "", {"finish_gate": True, "commands": [leak]}, mode="blind")
    assert ScriptedBuilder.briefs == []
    assert "finish gate refused" in row.error and not row.clean
    assert row.failure_kind == "harness"


def test_an_attempt_that_errored_gets_no_step_and_says_why(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    (row,), _ = _run(pyrepo, tmp_path, "model_error", {"format_step": True, "finish_gate": True})
    assert row.labels["format_step"] == "skipped=attempt_not_admissible"
    assert row.labels["finish_gate"] == "skipped=attempt_not_admissible"


STYLE = {"name": "style", "argv": ["sh", "-c", f"! grep -q TODO {pr.SRC}"]}
LEAK = {"name": "peek", "argv": ["pytest", pr.TEST_SUBTRACT], "blind_only": True}


@pytest.mark.parametrize(
    ("behaviour", "checks", "mode"),
    [
        ("", {"format_step": True}, "sighted"),  # an honest build, stamped by the steps
        ("model_error", {"format_step": True, "finish_gate": True}, "sighted"),
        ("raise", {"format_step": True}, "sighted"),  # the builder raised
        ("unavailable", {"api_stable": True}, "sighted"),  # the builder never built
        ("", {"finish_gate": True, "commands": [LEAK]}, "blind"),  # refused before spend
    ],
)
def test_every_attempt_of_a_checks_on_run_carries_the_checks_stamp(
    pyrepo: pr.PyRepo, tmp_path: Path, behaviour: str, checks: dict[str, Any], mode: str
) -> None:
    """ADR-0024 §5 and §6: every row of a run with a switch on carries ``labels.checks``,
    and the arm is read from that stamp. An attempt that failed before the build returned
    (a refusal, a builder that raised or could not be built) once carried no stamp, so it
    read as arm ``off`` and joined the other arm's cells (CodeRabbit, PR #57)."""
    resolved = resolve(RepoChecks.from_config(checks), None)
    (row,), _ = _run(pyrepo, tmp_path, behaviour, checks, mode=mode)
    assert row.labels["checks"] == resolved.label()
    assert row.checks_arm == resolved.arm


@needs_ruff
def test_a_repair_that_ends_in_a_model_error_keeps_the_first_attempts_patch(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A repair call that never reached the model (a 429, a dead credential) must not turn
    the first build into an errored attempt: its patch was admissible, so it is graded, the
    repair's spend is counted and the gate's label says the repair failed (CodeRabbit,
    PR #57)."""
    checks = {"finish_gate": True, "commands": [STYLE]}
    (row,), events = _run(pyrepo, tmp_path, "todo_repair_error", checks)
    assert len(ScriptedBuilder.briefs) == 2
    assert row.error == "" and row.failure_kind != "outage"
    assert row.target_green is True  # the first build's patch reached the belts
    assert not any(a == "builder.discard" for a, _ in events)
    assert row.labels["finish_gate"] == (
        "before=fail:lint+style;repair_error=model_error;repair=1;after=fail:lint+style"
    )
    assert row.cost_usd == pytest.approx(0.015)  # both calls are one attempt's spend


def test_the_gate_baseline_is_measured_once_per_task_and_mode(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declared commands' verdicts at the parent depend on the task, the mode and the
    commands, never on the rung: a ladder re-ran every command (up to 8, 600 s each) before
    every rung's build (CodeRabbit, PR #57). Measured once, reused on each rung."""
    calls: list[int] = []
    real = adapter.command_baseline

    def counting(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(adapter, "command_baseline", counting)
    runner = _FormattedRunner(pyrepo.config)
    ladder = EscalationLadder(
        (Rung("scripted", "m1", config={"behaviour": ""}), Rung("scripted", "m2"))
    )
    checks = resolve(RepoChecks.from_config({"finish_gate": True, "commands": [STYLE]}), None)
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=runner,
        executor=LocalExecutor(),
        config=pyrepo.config,
        checks=checks,
    )
    task = pyrepo.feat_task()
    for i, label in enumerate(adapter.ladder_labels(ladder) * 2):
        ws = pyrepo.trial(tmp_path / f"t{i}")
        try:
            fn(ws, task, "sighted", label)
        finally:
            ws.remove()
    assert len(calls) == 1
    ws = pyrepo.trial(tmp_path / "blind")
    try:
        fn(ws, task, "blind", adapter.ladder_labels(ladder)[0])  # another mode: measured again
    finally:
        ws.remove()
    assert len(calls) == 2
