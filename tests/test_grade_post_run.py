"""What the tests wrote is kept in the pack, and no belt reads it (G-955; ADR-0025 item 13).

Belts 4 and 5 read the builder's changes as they stood before the first test ran (ADR-0019
§7), so a file a test run writes is never the builder's. The external assessment of
2026-09-25 (A6) asked that the post-run set be kept as a diagnostic in the pack rather than
dropped: the grade now records ``touched_post_run`` — the files touched after the belt runs
and not before them.

Navigation
----------
What it is:   The test of the post-run diagnostic on a real grade.
What it does: Pins that a file a test run writes is in ``touched_post_run`` and in the pack's
              grade, never among the builder's changed files, and that the grade stays clean;
              that a grade stopping after the tests ran (a RED target) still names it; and that
              a grade stopping before any test ran names nothing (P-120).
How:          The pyrepo trial — with the gold, and without it (RED) — graded with a runner that
              writes an artefact into the tree before running the real tests.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md; ADR-0025 item 13 (stream G;
              the draft stream R commits)
Works with:   src/crb/core/grade.py (``touched_post_run``), src/crb/core/workspace.py
              (``touched_files``), tests/fixtures/pyrepo.py (the gold trial the grade runs on)
Tested by:    tests/test_grade_post_run.py
Touch when:   a belt starts reading the post-run tree (it must not: ADR-0019 §7).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core.execution import LocalExecutor
from crb.core.runners import base as rb
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.posture import grade_adhoc

ARTEFACT = "build/report.txt"


def test_a_file_the_tests_write_is_kept_as_a_diagnostic_and_read_by_no_belt(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr.apply_gold(trial)
    real_run = runner.run

    def run(ex: Any, root: Path, scope: Any, *, timeout: int = 0) -> rb.TestRun:
        (Path(root) / ARTEFACT).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / ARTEFACT).write_text("written by the tests\n", encoding="utf-8")
        return real_run(ex, root, scope, timeout=timeout)

    monkeypatch.setattr(runner, "run", run)
    res = grade_adhoc(trial, feat_task, config=pyrepo.config, runner=runner, executor=executor)
    assert res.clean, res.to_dict()
    assert ARTEFACT in res.touched_post_run
    assert res.changed_files == (pr.SRC,)  # belt 4 read the tree before the first test
    assert ARTEFACT in res.to_dict()["touched_post_run"]


def test_a_grade_that_stops_after_the_tests_ran_still_names_what_they_wrote(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target that stays RED returns before belt 5; the tests ran all the same, so what
    they wrote is in the pack (every return after the first test run)."""
    real_run = runner.run

    def run(ex: Any, root: Path, scope: Any, *, timeout: int = 0) -> rb.TestRun:
        (Path(root) / ARTEFACT).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / ARTEFACT).write_text("written by the tests\n", encoding="utf-8")
        return real_run(ex, root, scope, timeout=timeout)

    monkeypatch.setattr(runner, "run", run)
    res = grade_adhoc(trial, feat_task, config=pyrepo.config, runner=runner, executor=executor)
    assert not res.clean and res.belts.target_green is False
    assert res.touched_post_run == (ARTEFACT,)
    assert res.to_dict()["touched_post_run"] == [ARTEFACT]


def test_a_grade_that_stops_before_any_test_ran_names_nothing(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """A disqualification before the first run: nothing ran, so nothing is post-run — a
    builder's own untracked file is its change, never the tests'."""
    (trial.root / "tests" / "conftest.py").write_text("x = 1\n", encoding="utf-8")
    res = grade_adhoc(trial, feat_task, config=pyrepo.config, runner=runner, executor=executor)
    assert res.disqualified and res.touched_post_run == ()


def test_a_grade_that_wrote_nothing_after_the_builder_leaves_the_pack_as_it_was() -> None:
    from crb.core import grade as g

    res = g.GradeResult("a" * 40, "r", "sighted", clean=False, belts=g.Belts(True))
    assert "touched_post_run" not in res.to_dict()
