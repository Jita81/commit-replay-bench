"""A test process that stops before every test reported can never read as green or as "no new
failures" (stream Q2's verifiers, 2026-09-28; ADR-0048).

Two runners read a run from the tool's own report. When the process running the tests dies
part-way, the report is cut short and says less than happened:

* ``go test -json``: a test that calls ``os.Exit(1)`` (or a background goroutine that panics)
  leaves a ``run`` event with no ``pass`` or ``fail``; a test that panics is reported failed and
  the binary dies with it. Either way the tests after it never run. When the only failures
  named are in the baseline, belt 3 used to subtract them to "no new failures".
  An ``init`` that calls ``os.Exit(0)`` ends the binary before any test runs and ``go test``
  still prints ``ok``, so a target used to read green with no test run at all;
* ``pytest``: a ``KeyboardInterrupt`` or ``pytest.exit`` stops the session and the ``-rfE``
  summary lists only the failures so far; ``os._exit(0)`` ends the process with exit code 0
  and no summary at all.

Each of these is now an unattributed run (a ``parse_error``), which belt 2 reads as not green
and belt 3 as failed. A run that ends normally reads exactly as before.

Navigation
----------
What it is:   The suite for runs whose test process stopped before every test reported.
What it does: Pins that the Go parser names a test that started and never finished and makes
              the run unattributed; that a Go package which passed without its binary's own
              ``PASS`` line is unattributed; that a pytest session that was interrupted, exited
              early or printed no summary is unattributed; and, end to end on real toolchains,
              that a patch doing any of these never grades clean.
How:          Canned ``go test -json`` streams and pytest outputs for the parsers; ``gorepo``
              qualified by the real miner and graded by ``grade`` on a ``LocalExecutor``;
              ``PytestRunner.run`` on a temporary directory.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0048-the-host-posture-declares-its-environment.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/runners/go_runner.py (``parse``), src/crb/core/runners/pytest_runner.py
              (``parse``), src/crb/core/runners/base.py (the fail-closed rule),
              src/crb/core/grade.py (belts 2 and 3),
              tests/fixtures/langs/gorepo.py (the fixture module)
Tested by:    tests/test_runners_early_exit.py
Touch when:   never for a new repository; a runner's parser, or the rule that makes a run
              unattributed, changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core.execution import ExecResult, LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import qualify
from crb.core.runners import get_runner
from crb.core.spec import BELT_BARE, Language, RepoConfig
from fixtures.posture import grade_adhoc as grade

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

gorepo = langs.fixture_module("gorepo")

needs_go = pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")


def _go_parse(events: list[dict[str, str]], rc: int = 1):
    out = "\n".join(json.dumps(e) for e in events)
    return get_runner(gorepo.config()).parse(ExecResult(rc, out, ""), Path("."))


# ---------------------------------------------------------------------------
# The Go parser
# ---------------------------------------------------------------------------


def test_the_go_parser_names_a_test_that_started_and_never_finished() -> None:
    """go1.26's stream when ``TestY`` calls ``os.Exit(1)`` after ``TestX`` (red at the
    parent) failed: byte-identical fail events to the parent's run, ``TestZ`` never ran."""
    events = [
        {"Action": "run", "Package": "ex.com/m/b", "Test": "TestX"},
        {"Action": "fail", "Package": "ex.com/m/b", "Test": "TestX"},
        {"Action": "run", "Package": "ex.com/m/b", "Test": "TestY"},
        {"Action": "output", "Package": "ex.com/m/b", "Output": "FAIL\tex.com/m/b\t0.28s\n"},
        {"Action": "fail", "Package": "ex.com/m/b"},
    ]
    run = _go_parse(events)
    assert run.failing == frozenset({"ex.com/m/b::TestX", "ex.com/m/b::TestY"})
    assert run.parse_error == (
        "unattributed failure (package ex.com/m/b exited during TestY; later tests never ran)"
    )
    assert run.red


def test_the_go_parser_reads_a_binary_that_died_after_a_named_failure_as_unattributed() -> None:
    """``TestX`` panics: test2json reports it failed, the binary dies without its own ``FAIL``
    line and ``TestY`` never runs — the same fail events as a parent whose ``TestX`` failed."""
    events = [
        {"Action": "run", "Package": "ex.com/m/k", "Test": "TestX"},
        {"Action": "fail", "Package": "ex.com/m/k", "Test": "TestX"},
        {"Action": "output", "Package": "ex.com/m/k", "Output": "FAIL\tex.com/m/k\t0.34s\n"},
        {"Action": "fail", "Package": "ex.com/m/k"},
    ]
    run = _go_parse(events)
    assert run.failing == frozenset({"ex.com/m/k::TestX"})
    assert run.parse_error == (
        "unattributed failure (package ex.com/m/k's test binary ended without its own summary "
        "(a panic or an exit after a failure): later tests never ran)"
    )


def test_the_go_parser_reads_a_package_that_passed_without_its_own_pass_line_as_unattributed() -> (
    None
):
    """``func init() { os.Exit(0) }``: the binary ends before any test and ``go test`` still
    prints ``ok`` — no ``PASS`` line from the binary, no test run."""
    events = [
        {"Action": "start", "Package": "ex.com/m/e"},
        {"Action": "output", "Package": "ex.com/m/e", "Output": "ok  \tex.com/m/e\t0.26s\n"},
        {"Action": "pass", "Package": "ex.com/m/e"},
    ]
    run = _go_parse(events, rc=0)
    assert run.failing == frozenset()
    assert run.parse_error == (
        "unattributed failure (package ex.com/m/e passed without its test binary reporting "
        "PASS: it exited before its tests ran)"
    )
    assert run.green is False


def test_the_go_parser_leaves_normal_runs_alone() -> None:
    events = [
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestP"},
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestP/sub"},
        {"Action": "pass", "Package": "ex.com/m/g", "Test": "TestP/sub"},
        {"Action": "pass", "Package": "ex.com/m/g", "Test": "TestP"},
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestS"},
        {"Action": "skip", "Package": "ex.com/m/g", "Test": "TestS"},
        {"Action": "output", "Package": "ex.com/m/g", "Output": "PASS\n"},
        {"Action": "pass", "Package": "ex.com/m/g"},
        {
            "Action": "output",
            "Package": "ex.com/m/h",
            "Output": "?   \tex.com/m/h\t[no test files]\n",
        },
        {"Action": "skip", "Package": "ex.com/m/h"},
        {
            "Action": "output",
            "Package": "ex.com/m/i",
            "Output": "testing: warning: no tests to run\n",
        },
        {"Action": "output", "Package": "ex.com/m/i", "Output": "PASS\n"},
        {"Action": "pass", "Package": "ex.com/m/i"},
    ]
    run = _go_parse(events, rc=0)
    assert run.failing == frozenset() and run.parse_error == "" and run.green
    failed = [
        {"Action": "run", "Package": "ex.com/m/a", "Test": "TestX"},
        {"Action": "fail", "Package": "ex.com/m/a", "Test": "TestX"},
        {"Action": "run", "Package": "ex.com/m/a", "Test": "TestY"},
        {"Action": "pass", "Package": "ex.com/m/a", "Test": "TestY"},
        {"Action": "output", "Package": "ex.com/m/a", "Output": "FAIL\n"},
        {"Action": "fail", "Package": "ex.com/m/a"},
    ]
    red = _go_parse(failed)
    assert red.failing == frozenset({"ex.com/m/a::TestX"}) and red.parse_error == ""


# ---------------------------------------------------------------------------
# End to end on a real Go toolchain
# ---------------------------------------------------------------------------

#: Red at the parent and after it, in ``util`` before ``TestTwice`` (files run in name order).
_AA_RED = (
    'package util\n\nimport "testing"\n\n'
    "func TestAARedAtBase(t *testing.T) {\n"
    '\tt.Fatal("red at the parent and after it")\n'
    "}\n"
)
#: gofmt-clean: ``Twice`` ends the test binary part-way through the package.
_TWICE_EXITS = (
    'package util\n\nimport "os"\n\n'
    "// Twice returns 2 * a.\n"
    "func Twice(a int) int {\n"
    "\tos.Exit(1)\n"
    "\treturn a * 2\n"
    "}\n"
)
#: gofmt-clean: the target package's binary ends before any of its tests runs.
_CALC_EXITS_AT_INIT = (
    'package calc\n\nimport "os"\n\n'
    "func init() { os.Exit(0) }\n\n"
    "// Add returns a + b.\n"
    "func Add(a, b int) int { return a + b }\n"
)


def _qualified(tmp_path: Path, extra=None):
    root, feat_sha = gorepo.build(tmp_path / "repo", extra=extra)
    repo, config = GitRepo(root), gorepo.config(BELT_BARE)
    runner, ex = get_runner(config), LocalExecutor()
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=runner,
        executor=ex,
        scratch=tmp_path / "scratch",
    )
    assert outcome.task is not None and outcome.qualification is not None, outcome.skipped_reason
    return repo, outcome.task, outcome.qualification, config, runner, ex


def _graded(tmp_path: Path, repo, task, config, runner, ex, writes: dict[str, str]):
    ws = langs.trial_worktree(
        repo, langs.feat_candidate(repo, config, task.task_id), tmp_path / "trial", config
    )
    try:
        ws.overlay_sources(task.src_files)
        for rel, text in writes.items():
            (ws.root / rel).write_text(text, encoding="utf-8")
        return grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()


@needs_go
def test_a_patch_that_exits_a_baselined_red_package_mid_run_never_grades_clean(
    tmp_path: Path,
) -> None:
    repo, task, q, config, runner, ex = _qualified(tmp_path, {"util/aa_red_test.go": _AA_RED})
    red_at_base = f"{gorepo.UTIL_PKG}::TestAARedAtBase"
    assert red_at_base in q.baseline_failing and q.is_qualified
    res = _graded(tmp_path, repo, task, config, runner, ex, {gorepo.SRC_TWICE: _TWICE_EXITS})
    assert res.belts.target_green is True
    assert res.belt_run is not None
    assert f"{gorepo.UTIL_PKG}::TestTwice" in res.belt_run.failing
    assert "exited during TestTwice" in res.belt_run.parse_error
    assert res.belts.no_new_failures is False and res.clean is False


#: Red at the parent by assertion (``Twice(0)`` is 0 there); the patch makes it panic instead.
_AA_RED_TWICE = (
    'package util\n\nimport "testing"\n\n'
    "func TestAARedAtBase(t *testing.T) {\n"
    "\tif Twice(0) != 1 {\n"
    '\t\tt.Fatal("red at the parent and after it")\n'
    "\t}\n}\n"
)
#: gofmt-clean: panics on 0 (the baselined test now dies) and is wrong everywhere else.
_TWICE_PANICS = (
    "package util\n\n"
    "// Twice returns 2 * a.\n"
    "func Twice(a int) int {\n"
    "\tif a == 0 {\n"
    '\t\tpanic("zero")\n'
    "\t}\n"
    "\treturn a * 3\n"
    "}\n"
)


@needs_go
def test_a_patch_that_turns_a_baselined_failure_into_a_panic_never_grades_clean(
    tmp_path: Path,
) -> None:
    """The panic is reported as the baselined test failing; the binary dies and ``TestTwice``,
    which the patch broke, never runs."""
    repo, task, q, config, runner, ex = _qualified(tmp_path, {"util/aa_red_test.go": _AA_RED_TWICE})
    assert f"{gorepo.UTIL_PKG}::TestAARedAtBase" in q.baseline_failing and q.is_qualified
    res = _graded(tmp_path, repo, task, config, runner, ex, {gorepo.SRC_TWICE: _TWICE_PANICS})
    assert res.belt_run is not None
    assert f"{gorepo.UTIL_PKG}::TestTwice" not in res.belt_run.failing  # it never ran
    assert "ended without its own summary" in res.belt_run.parse_error
    assert res.belts.no_new_failures is False and res.clean is False


@needs_go
def test_a_patch_whose_init_exits_zero_never_reads_green(tmp_path: Path) -> None:
    repo, task, _, config, runner, ex = _qualified(tmp_path)
    res = _graded(tmp_path, repo, task, config, runner, ex, {gorepo.SRC_ADD: _CALC_EXITS_AT_INIT})
    assert res.target_run is not None and res.target_run.returncode == 0
    assert "without its test binary reporting PASS" in res.target_run.parse_error
    assert res.belts.target_green is False and res.clean is False


# ---------------------------------------------------------------------------
# pytest: an interrupted or cut-short session
# ---------------------------------------------------------------------------

_PY_RED = "def test_red_at_base():\n    assert 0\n"


def _pytest_run(tmp_path: Path, files: dict[str, str]):
    root = tmp_path / "py"
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    runner = get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))
    return runner.run(LocalExecutor(), root, tuple(sorted(files)))


@pytest.mark.parametrize(
    ("stop", "why"),
    [
        ("raise KeyboardInterrupt", "KeyboardInterrupt"),
        ("import pytest\n    pytest.exit('bye', returncode=1)", "Exit"),
        ("import pytest\n    pytest.exit('bye', returncode=0)", "Exit"),
    ],
)
def test_an_interrupted_pytest_session_is_unattributed(tmp_path: Path, stop: str, why: str) -> None:
    """The summary lists only the failures so far — the baselined ones — and ``test_c``
    never runs: it must never subtract to "no new failures"."""
    run = _pytest_run(
        tmp_path,
        {
            "test_a.py": _PY_RED,
            "test_b.py": f"def test_b():\n    {stop}\n",
            "test_c.py": "def test_c():\n    assert 0\n",
        },
    )
    assert "test_c.py::test_c" not in run.failing  # the report is cut short
    assert run.parse_error.startswith("unattributed failure (pytest stopped")
    assert why in run.parse_error
    assert run.red


def test_a_pytest_process_that_exits_zero_without_a_summary_is_never_green(
    tmp_path: Path,
) -> None:
    run = _pytest_run(
        tmp_path,
        {
            "test_a.py": "import os\n\n\ndef test_a():\n    os._exit(0)\n",
            "test_b.py": "def test_b():\n    assert 0\n",
        },
    )
    assert run.returncode == 0
    assert run.parse_error == (
        "unattributed failure (pytest exited 0 without reporting a result: the session "
        "never finished)"
    )
    assert run.green is False


def test_a_normal_pytest_run_reads_as_before(tmp_path: Path) -> None:
    green = _pytest_run(tmp_path / "g", {"test_ok.py": "def test_ok():\n    pass\n"})
    assert green.green and green.parse_error == ""
    red = _pytest_run(
        tmp_path / "r",
        {"test_a.py": _PY_RED, "test_col.py": "import nope\n\n\ndef test_x(): pass\n"},
    )
    assert red.failing == frozenset({"test_a.py::test_red_at_base", "test_col.py"})
    assert red.parse_error == ""


@pytest.mark.parametrize(
    ("rc", "out"),
    [
        (2, "FAILED test_a.py::test_red_at_base - assert 0\n1 failed in 0.1s\n"),
        (3, "INTERNALERROR> boom\nFAILED test_a.py::test_red_at_base\n"),
    ],
)
def test_a_pytest_exit_code_other_than_0_or_1_is_unattributed(rc: int, out: str) -> None:
    runner = get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))
    run = runner.parse(ExecResult(rc, out, ""), Path("."))
    assert run.parse_error == (
        f"unattributed failure (pytest stopped early: exit code {rc}; later tests never ran)"
    )
