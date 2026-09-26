"""crb.core.finish_gate — the checklist, the leak guard and the verification, with real tools.

Navigation
----------
What it is:   The unit suite for the finish gate's core: checklist lines, the oracle-leak guard,
              the parent baseline of declared commands and the post-build verification.
What it does: Pins that the checklist is numbered, capped and made of operating facts; that a
              line naming a held-out test path is refused; that ``verify`` fails on a real
              ``gofmt`` rejection of a changed file, passes once it is formatted, records a
              declared command already red at the parent as ``pre_existing`` (never gating) and
              a command that cannot run as an error (never gating).
How:          The Go fixture repository with the Go runner's own belt-5 plan; declared commands
              as small shell commands in the worktree; ``LocalExecutor``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md
Works with:   src/crb/core/finish_gate.py (under test), src/crb/core/checks.py
              (``CheckCommand``), src/crb/core/lint.py (the plan), tests/fixtures/langs/gorepo.py
              (the Go repository the checks run in)
Tested by:    tests/test_finish_gate.py
Touch when:   the checklist's content or the gating rule changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.core import finish_gate as fg
from crb.core.checks import CheckCommand
from crb.core.execution import LocalExecutor
from crb.core.lint import LintPlan, LintTool
from crb.core.runners import get_runner

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs  # type: ignore[no-redef]


def test_the_checklist_is_numbered_operating_facts_and_capped() -> None:
    plan = LintPlan(
        (
            LintTool("gofmt", ("gofmt", "-l"), exts=(".go",), stdout_is_findings=True),
            LintTool("tsc", ("tsc", "--noEmit"), paths="all"),
        ),
        "gofmt",
    )
    lines = fg.checklist(
        plan, (CheckCommand("vet", ("go", "vet", "./...")),), test_command="go test -json"
    )
    assert lines == (
        "1. gofmt: gofmt -l <changed .go files> — must print nothing",
        "2. tsc: tsc --noEmit",
        "3. vet: go vet ./...",
        "4. tests: go test -json <existing test files near your change>",
    )
    many = tuple(CheckCommand(f"c{i}", ("true",)) for i in range(12))
    assert len(fg.checklist(None, many)) == fg.MAX_CHECKLIST_LINES


def test_a_checklist_that_names_the_oracle_is_refused() -> None:
    lines = fg.checklist(None, (CheckCommand("t", ("pytest", "tests/test_subtract.py")),))
    with pytest.raises(fg.OracleLeak, match="test_subtract"):
        fg.assert_no_oracle(lines, ("tests/test_subtract.py",))
    fg.assert_no_oracle(lines, ("tests/test_other.py", "./...", ""))  # no leak, no raise


@pytest.mark.skipif(not langs.has_tool("gofmt"), reason="gofmt not on PATH")
@pytest.mark.toolchain("go")
def test_verify_gates_on_a_real_gofmt_rejection_and_passes_once_formatted(tmp_path: Path) -> None:
    gorepo = langs.fixture_module("gorepo")
    root, _ = gorepo.build(tmp_path)
    ex = LocalExecutor()
    plan = get_runner(gorepo.config()).lint_plan(root, ex)
    (root / gorepo.SRC_ADD).write_text(
        "package calc\n\nfunc Add(a,b int) int {return a+b}\n", encoding="utf-8"
    )
    run = fg.verify(plan, (), ex, root, [gorepo.SRC_ADD])
    assert not run.passed and run.failing == ("lint",)
    assert run.label() == "fail:lint" and "[gofmt]" in run.findings()
    (root / gorepo.SRC_ADD).write_text(
        "package calc\n\nfunc Add(a, b int) int { return a + b }\n", encoding="utf-8"
    )
    assert fg.verify(plan, (), ex, root, [gorepo.SRC_ADD]).label() == "pass"


def test_a_command_red_at_the_parent_never_gates_and_one_that_cannot_run_never_gates(
    tmp_path: Path,
) -> None:
    ex = LocalExecutor()
    (tmp_path / "marker").write_text("x", encoding="utf-8")
    red_before = CheckCommand("legacy", ("sh", "-c", "exit 3"))
    now_red = CheckCommand("style", ("sh", "-c", "test ! -f marker"))
    missing = CheckCommand("ghost", ("/nonexistent/tool",))
    baseline = {"legacy": False, "style": True, "ghost": None}
    run = fg.verify(None, (red_before, now_red, missing), ex, tmp_path, [], baseline=baseline)
    by = {r.name: r for r in run.results}
    assert by["legacy"].pre_existing and not by["legacy"].gates
    assert by["style"].gates and run.failing == ("style",)
    assert by["ghost"].ok is None and by["ghost"].error and not by["ghost"].gates
    assert run.label() == "fail:style;pre:legacy;err:ghost"
    assert fg.command_baseline((red_before, now_red), ex, tmp_path) == {
        "legacy": False,
        "style": False,
    }
