"""crb.core.formatting — the format step with the repositories' real formatters.

Navigation
----------
What it is:   The suite for the format step: which formatter a repository's own configuration
              names, running it in write mode over the changed source files, and the record.
What it does: Pins, with the real tools, that ``gofmt`` rewrites a changed Go file and leaves an
              unchanged or test file alone; that ``ruff format`` runs only where the repository
              configures it; that black configured but absent, prettier configured but absent,
              nothing configured and ``{disabled: true}`` are each skipped with their own named
              reason (never a guessed formatter); that a formatter failure leaves the file as
              the builder wrote it and is recorded.
How:          Hermetic git fixture repositories (``tests/fixtures/langs``), the runners' own
              ``lint_plan`` detection, ``formatters_for`` → ``run_formatters`` on a
              ``LocalExecutor``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0021-working-by-construction.md
Works with:   src/crb/core/formatting.py (under test), src/crb/core/lint.py (the plan the step
              reuses), tests/fixtures/langs/gorepo.py and tests/fixtures/langs/__init__.py
              (the repositories)
Tested by:    tests/test_formatting.py
Touch when:   a formatter is added to ``FORMATTER_WRITE`` or detection changes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from crb.core import formatting as fm
from crb.core.execution import LocalExecutor
from crb.core.lint import LintPlan, LintTool
from crb.core.runners import get_runner
from crb.core.spec import Language, RepoConfig
from fixtures.langs import commit_all, init_repo, write_files

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs  # type: ignore[no-redef]

RUFF = shutil.which("ruff") or str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "ruff")


@pytest.mark.skipif(not langs.has_tool("gofmt"), reason="gofmt not on PATH")
@pytest.mark.toolchain("go")
def test_gofmt_rewrites_the_changed_source_and_nothing_else(tmp_path: Path) -> None:
    gorepo = langs.fixture_module("gorepo")
    root, _ = gorepo.build(tmp_path)
    cfg = gorepo.config()
    ugly = "package calc\n\nfunc Add(a,b int) int {return a+b}\n"
    (root / gorepo.SRC_ADD).write_text(ugly, encoding="utf-8")
    (root / gorepo.TEST_ADD).write_text(
        (root / gorepo.TEST_ADD).read_text(encoding="utf-8") + "\nfunc  x() {}\n",
        encoding="utf-8",
    )
    test_before = (root / gorepo.TEST_ADD).read_text(encoding="utf-8")
    ex = LocalExecutor()
    plan = get_runner(cfg).lint_plan(root, ex)
    formatters, skipped = fm.formatters_for(plan, root)
    assert [f.name for f in formatters] == ["gofmt"] and skipped == ""
    run = fm.run_formatters(formatters, ex, root, [gorepo.SRC_ADD, gorepo.SRC_TWICE])
    assert run.ran == ("gofmt",) and run.changed == (gorepo.SRC_ADD,)
    assert run.label() == "ran=gofmt;changed=1"
    assert (root / gorepo.SRC_ADD).read_text(encoding="utf-8") == (
        "package calc\n\nfunc Add(a, b int) int { return a + b }\n"
    )
    assert (root / gorepo.TEST_ADD).read_text(encoding="utf-8") == test_before


@pytest.mark.skipif(not langs.has_tool("gofmt"), reason="gofmt not on PATH")
@pytest.mark.toolchain("go")
def test_a_formatter_that_fails_leaves_the_file_and_says_so(tmp_path: Path) -> None:
    gorepo = langs.fixture_module("gorepo")
    root, _ = gorepo.build(tmp_path)
    broken = "package calc\n\nfunc Add(a, b int int {\n"
    (root / gorepo.SRC_ADD).write_text(broken, encoding="utf-8")
    ex = LocalExecutor()
    formatters, _ = fm.formatters_for(get_runner(gorepo.config()).lint_plan(root, ex), root)
    run = fm.run_formatters(formatters, ex, root, [gorepo.SRC_ADD])
    assert run.errors == ("gofmt:rc=2",) and run.changed == ()
    assert (root / gorepo.SRC_ADD).read_text(encoding="utf-8") == broken
    assert run.label() == "ran=gofmt;changed=0;errors=gofmt:rc=2"


def _python_repo(tmp_path: Path, pyproject: str) -> Path:
    root = tmp_path / "py"
    init_repo(root)
    write_files(
        root,
        {
            "pyproject.toml": pyproject,
            "pkg/__init__.py": "",
            "pkg/calc.py": "def add(a,b):\n    return a+b\n",
            "tests/test_calc.py": "def test_x( ):\n    pass\n",
        },
    )
    commit_all(root, "chore: initial")
    return root


@pytest.mark.skipif(not Path(RUFF).exists(), reason="ruff not available")
def test_ruff_format_runs_only_where_the_repository_configures_it(tmp_path: Path) -> None:
    cfg = RepoConfig(
        name="pyfix",
        language=Language.PYTHON,
        test_prefix="tests/",
        runner_opts={"python": str(Path(RUFF).parent / "python")},
    )
    root = _python_repo(tmp_path, '[project]\nname = "pkg"\n\n[tool.ruff.format]\n')
    plan = LintPlan(
        (LintTool("ruff-format", (RUFF, "format", "--check"), exts=(".py",)),), "ruff-format"
    )
    formatters, skipped = fm.formatters_for(plan, root)
    assert [f.argv[1:] for f in formatters] == [("format", "-q")] and skipped == ""
    run = fm.run_formatters(formatters, LocalExecutor(), root, ["pkg/calc.py"])
    assert run.changed == ("pkg/calc.py",)
    assert (root / "pkg/calc.py").read_text(
        encoding="utf-8"
    ) == "def add(a, b):\n    return a + b\n"
    # the runner's own detection agrees that this repository formats with ruff
    detected = get_runner(cfg).lint_plan(root, LocalExecutor())
    assert detected is not None and "ruff-format" in {t.name for t in detected.tools}


@pytest.mark.skipif(not Path(RUFF).exists(), reason="ruff not available")
def test_a_ruff_outside_the_repositorys_pin_never_formats_and_says_so(tmp_path: Path) -> None:
    """Belt 5 refuses to judge with a ruff the repository's pin forbids; the format step
    and the preflight's fixers must not rewrite files with it either (P-031)."""
    from crb.core.lint import fix_commands, python_plan

    root = _python_repo(
        tmp_path,
        '[project]\nname = "pkg"\n\n[project.optional-dependencies]\ndev = ["ruff==0.0.1"]\n'
        "\n[tool.ruff]\n\n[tool.ruff.format]\n",
    )
    plan = python_plan(root, str(Path(RUFF).resolve()))
    assert plan is not None and all(t.refuse for t in plan.tools)
    before = (root / "pkg/calc.py").read_bytes()
    formatters, skipped = fm.formatters_for(plan, root)
    assert formatters == [] and skipped == "formatter_refused:ruff-format"
    run = fm.run_formatters(formatters, LocalExecutor(), root, ["pkg/calc.py"], skipped=skipped)
    assert run.label() == "skipped=formatter_refused:ruff-format"
    assert (root / "pkg/calc.py").read_bytes() == before
    assert fix_commands(plan, ["pkg/calc.py"]) == []


def test_cargo_fmt_formats_the_whole_crate_so_it_is_a_named_skip(tmp_path: Path) -> None:
    """``cargo fmt`` formats every target of the crate, tests included — it cannot be held
    to the changed source files, so it never runs as the format step (P-031)."""
    plan = LintPlan((LintTool("cargo-fmt", ("cargo", "fmt", "--check"), paths="all"),), "cargo")
    formatters, skipped = fm.formatters_for(plan, tmp_path)
    assert formatters == [] and skipped == "formatter_not_file_scoped:cargo-fmt"


def test_black_configured_but_not_installed_is_a_named_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _python_repo(tmp_path, '[project]\nname = "pkg"\n\n[tool.black]\nline-length = 88\n')
    monkeypatch.setattr(fm.shutil, "which", lambda name: None)
    formatters, skipped = fm.formatters_for(None, root)
    assert formatters == [] and skipped == "formatter_not_installed:black"
    run = fm.run_formatters(formatters, LocalExecutor(), root, ["pkg/calc.py"], skipped=skipped)
    assert run.label() == "skipped=formatter_not_installed:black"
    assert (root / "pkg/calc.py").read_text(encoding="utf-8") == "def add(a,b):\n    return a+b\n"
    fake = tmp_path / "black"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    formatters, skipped = fm.formatters_for(None, root, black=str(fake))
    assert [f.name for f in formatters] == ["black"] and skipped == ""


def test_prettier_configured_but_absent_nothing_configured_and_disabled_are_named(
    tmp_path: Path,
) -> None:
    noderepo = langs.fixture_module("noderepo")
    root, _ = noderepo.build(tmp_path, "node", extra={".prettierrc": "{}\n"})
    ex = LocalExecutor()
    plan = get_runner(noderepo.config("node")).lint_plan(root, ex)
    assert fm.formatters_for(plan, root)[1] == "formatter_not_installed:prettier"
    bare, _ = noderepo.build(tmp_path / "bare", "node")
    assert fm.formatters_for(None, bare) == ([], "no_formatter_configured")
    assert fm.formatters_for(None, bare, {"disabled": True}) == ([], "disabled")
    declared, skipped = fm.formatters_for(None, bare, {"command": ["fmt", "-w"], "exts": [".js"]})
    assert declared == [fm.Formatter("declared", ("fmt", "-w"), (".js",))] and skipped == ""


def test_no_changed_source_file_is_its_own_skip(tmp_path: Path) -> None:
    plan = LintPlan((LintTool("gofmt", ("gofmt", "-l"), exts=(".go",)),), "gofmt")
    formatters, _ = fm.formatters_for(plan, tmp_path)
    assert fm.run_formatters(formatters, LocalExecutor(), tmp_path, []).label() == (
        "skipped=no_changed_source_files"
    )
