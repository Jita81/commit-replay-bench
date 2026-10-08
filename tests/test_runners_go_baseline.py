"""A Go baseline that names no failing test can never let a wrong patch grade clean (pilot
finding D6, ADR-0048).

In the dress rehearsal 17 of the 46 gold-clean cobra XS and S tasks carried
``baseline_parse_error: unattributed failure (rc=1, no failing ids parsed)`` with an empty
baseline: the commit's new test names a symbol the parent does not have, so at the parent
the target package does not compile and ``go test`` names no test. These tests fix exactly
what the qualification records for such a task and what belts 2 and 3 do with it, and they
close the one way a package failure could hide beside a named baseline failure.

Navigation
----------
What it is:   The Go suite for unattributed baselines and package failures that name no test.
What it does: Pins that a build-failure RED at the parent is qualified with its unattributed
              baseline recorded and an empty baseline; that with that baseline a patch leaving
              another test failing, or leaving another package unable to compile, never grades
              clean; that a package which fails without naming a test fails belt 3 even
              when every test id the run did name is in the baseline (the false Q1 this closes);
              that a belt narrower than the module still fails a patch that breaks a package
              outside it (the module build gate), and that every belt-scope run goes through
              that gate; and which unattributed baselines the miner accepts without its gold
              check.
How:          ``gorepo`` built with extra packages → the real miner's qualification → trial
              worktrees graded by ``grade`` on a ``LocalExecutor``; one canned ``go test -json``
              stream for the parser without a toolchain.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0048-the-host-posture-declares-its-environment.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/runners/go_runner.py (``parse``), src/crb/core/runners/base.py (the
              fail-closed rule), src/crb/core/qualify.py (the recorded baseline),
              src/crb/core/grade.py (belts 2 and 3), tests/fixtures/langs/gorepo.py (the fixture)
Tested by:    tests/test_runners_go_baseline.py
Touch when:   never for a new repository; the Go parser or the belt-3 rule changes.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from crb.core.execution import ExecResult, LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import qualify
from crb.core.qualify import QUAL_BASELINE_UNATTRIBUTED
from crb.core.runners import get_runner
from crb.core.spec import BELT_BARE, BELT_TARGET_ONLY, Language, RepoConfig, TaskSpec
from fixtures.posture import grade_adhoc as grade

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

gorepo = langs.fixture_module("gorepo")

needs_go = pytest.mark.toolchain("go")

#: A test in ``util`` that is red at the parent and stays red: a named baseline failure.
_RED_AT_BASE = (
    'package util\n\nimport "testing"\n\n'
    "func TestRedAtBase(t *testing.T) {\n"
    '\tt.Fatal("red at the parent and after it")\n'
    "}\n"
)
#: A third package with a passing test: the package a wrong patch breaks.
_OTHER = "package other\n\n// Other is a neighbour.\nfunc Other() int { return 1 }\n"
_OTHER_TEST = (
    'package other\n\nimport "testing"\n\n'
    "func TestOther(t *testing.T) {\n"
    "\tif Other() != 1 {\n"
    '\t\tt.Fatal("Other")\n'
    "\t}\n}\n"
)
#: gofmt-clean Go that does not compile: the patch that breaks a package's build.
_OTHER_BROKEN = (
    "package other\n\n// Other is a neighbour.\nfunc Other() int { return undefinedName }\n"
)
_TWICE_BROKEN = (
    "package util\n\n// Twice returns 2 * a.\nfunc Twice(a int) int { return undefinedName }\n"
)


def _qualified(tmp_path: Path, belt_scope, extra=None) -> tuple[GitRepo, TaskSpec, object, object]:
    root, feat_sha = gorepo.build(tmp_path / "repo", extra=extra)
    repo, config = GitRepo(root), gorepo.config(belt_scope)
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
    return repo, outcome.task, outcome.qualification, (config, runner, ex)


def _trial(repo: GitRepo, task: TaskSpec, dest: Path, config):
    ws = langs.trial_worktree(repo, langs.feat_candidate(repo, config, task.task_id), dest, config)
    ws.overlay_sources(task.src_files)
    return ws


# ---------------------------------------------------------------------------
# What the qualification records for the pilot's shape (cobra: belt scope = target package)
# ---------------------------------------------------------------------------


@needs_go
def test_a_build_failure_red_is_qualified_with_its_unattributed_baseline_recorded(
    tmp_path: Path,
) -> None:
    _, task, q, _ = _qualified(tmp_path, BELT_TARGET_ONLY)
    assert q.is_qualified
    assert q.red["kind"] == "build_failed" and q.red["failing"] == []
    assert q.red["baseline_parse_error"].startswith("unattributed failure")
    assert q.baseline_failing == () and task.baseline_failing == ()
    assert q.env_probe["ran"] is True and q.env_probe["ok"] is True


@needs_go
def test_with_an_unattributed_baseline_another_failing_test_never_grades_clean(
    tmp_path: Path,
) -> None:
    repo, task, _, (config, runner, ex) = _qualified(tmp_path, BELT_TARGET_ONLY)
    ws = _trial(repo, task, tmp_path / "trial", config)
    try:
        (ws.root / gorepo.SRC_ADD).write_text(gorepo.BREAK_ADD, encoding="utf-8")
        res = grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()
    assert res.clean is False
    assert res.belts.target_green is False  # the target scope is the whole package
    assert res.target_run is not None
    assert res.target_run.failing == frozenset({f"{gorepo.CALC_PKG}::TestAdd"})


@needs_go
def test_with_an_unattributed_baseline_a_failing_test_elsewhere_fails_belt_3(
    tmp_path: Path,
) -> None:
    repo, task, q, (config, runner, ex) = _qualified(tmp_path, BELT_BARE)
    assert q.baseline_failing == () and q.red["baseline_parse_error"]
    ws = _trial(repo, task, tmp_path / "trial", config)
    try:
        (ws.root / gorepo.SRC_TWICE).write_text(gorepo.BREAK_TWICE, encoding="utf-8")
        res = grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()
    assert res.clean is False and res.belts.no_new_failures is False
    assert res.new_failures == (f"{gorepo.UTIL_PKG}::TestTwice",)


@needs_go
def test_with_an_unattributed_baseline_a_package_that_stops_compiling_fails_belt_3(
    tmp_path: Path,
) -> None:
    repo, task, _, (config, runner, ex) = _qualified(tmp_path, BELT_BARE)
    ws = _trial(repo, task, tmp_path / "trial", config)
    try:
        (ws.root / gorepo.SRC_TWICE).write_text(_TWICE_BROKEN, encoding="utf-8")
        res = grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()
    assert res.clean is False
    assert res.belts.target_green is True and res.belts.no_new_failures is False
    assert res.belt_run is not None and res.belt_run.parse_error.startswith("unattributed failure")


# ---------------------------------------------------------------------------
# The false Q1 this closes: a package failure beside a named baseline failure
# ---------------------------------------------------------------------------


@needs_go
def test_a_package_failing_without_a_test_fails_belt_3_beside_named_baseline_failures(
    tmp_path: Path,
) -> None:
    extra = {
        "util/red_test.go": _RED_AT_BASE,
        "other/other.go": _OTHER,
        "other/other_test.go": _OTHER_TEST,
    }
    repo, task, q, (config, runner, ex) = _qualified(tmp_path, BELT_BARE, extra)
    red_at_base = f"{gorepo.UTIL_PKG}::TestRedAtBase"
    assert red_at_base in q.baseline_failing and q.is_qualified
    ws = _trial(repo, task, tmp_path / "trial", config)
    try:
        (ws.root / "other" / "other.go").write_text(_OTHER_BROKEN, encoding="utf-8")
        res = grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()
    # every test id the run named is in the baseline; the package that no longer compiles
    # named none — it must still fail the belt, never subtract to "no new failures"
    assert res.belt_run is not None and res.belt_run.failing == frozenset({red_at_base})
    assert res.belt_run.parse_error.startswith("unattributed failure")
    assert "example.com/m/other" in res.belt_run.parse_error
    assert res.belts.no_new_failures is False and res.clean is False


@needs_go
def test_a_red_that_is_partly_a_build_failure_qualifies_as_one(tmp_path: Path) -> None:
    """Two target packages: at the parent one does not compile (its new test names a new
    symbol) and the other's new test fails. The RED names one test and one package that
    named none — it is a build-failure RED (proven loadable by the probe), and the belt
    scope's unattributed package is explained by it, recorded, never a baseline id."""
    from fixtures.langs import two_commit_repo

    initial = dict(gorepo._INITIAL)
    initial["util/half.go"] = (
        "package util\n\n// Half is wrong at the parent.\nfunc Half(a int) int { return a }\n"
    )
    feat = {
        **gorepo._FEAT,
        "util/half.go": "package util\n\n// Half returns a / 2.\nfunc Half(a int) int { return a / 2 }\n",
        "util/half_test.go": (
            'package util\n\nimport "testing"\n\n'
            "func TestHalf(t *testing.T) {\n"
            "\tif Half(4) != 2 {\n"
            '\t\tt.Fatal("Half")\n'
            "\t}\n}\n"
        ),
    }
    root, feat_sha = two_commit_repo(tmp_path / "two", initial, feat)
    repo, config = GitRepo(root), gorepo.config(BELT_BARE)
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
    )
    q = outcome.qualification
    assert q is not None and q.is_qualified, outcome.skipped_reason
    assert q.red["kind"] == "build_failed"
    assert q.red["failing"] == [f"{gorepo.UTIL_PKG}::TestHalf"]
    assert q.red["baseline_parse_error"].startswith("unattributed failure")
    assert q.baseline_failing == (f"{gorepo.UTIL_PKG}::TestHalf",)


def test_the_parser_names_a_package_that_failed_without_a_test() -> None:
    events = [
        {"Action": "build-fail", "ImportPath": "ex.com/m/a [ex.com/m/a.test]"},
        {"Action": "fail", "Package": "ex.com/m/a", "FailedBuild": "ex.com/m/a [ex.com/m/a.test]"},
        {"Action": "run", "Package": "ex.com/m/b", "Test": "TestB"},
        {"Action": "fail", "Package": "ex.com/m/b", "Test": "TestB"},
        {"Action": "output", "Package": "ex.com/m/b", "Output": "FAIL\n"},
        {"Action": "fail", "Package": "ex.com/m/b"},
        {"Action": "output", "Package": "ex.com/m/c", "Output": "PASS\n"},
        {"Action": "pass", "Package": "ex.com/m/c"},
    ]
    out = "\n".join(json.dumps(e) for e in events)
    run = get_runner(gorepo.config()).parse(ExecResult(1, out, ""), Path("."))
    assert run.failing == frozenset({"ex.com/m/b::TestB"})
    assert run.parse_error == (
        "unattributed failure (package ex.com/m/a failed without naming a test)"
    )
    assert run.red


def test_the_parser_leaves_a_run_whose_every_failure_is_named_alone() -> None:
    events = [
        {"Action": "fail", "Package": "ex.com/m/b", "Test": "TestB"},
        {"Action": "output", "Package": "ex.com/m/b", "Output": "FAIL\n"},
        {"Action": "fail", "Package": "ex.com/m/b"},
    ]
    out = "\n".join(json.dumps(e) for e in events)
    run = get_runner(gorepo.config()).parse(ExecResult(1, out, ""), Path("."))
    assert run.failing == frozenset({"ex.com/m/b::TestB"}) and run.parse_error == ""


# ---------------------------------------------------------------------------
# The module build gate: a belt narrower than the module still sees every package build
# ---------------------------------------------------------------------------


@needs_go
def test_a_patch_that_breaks_a_package_outside_a_target_only_belt_never_grades_clean(
    tmp_path: Path,
) -> None:
    """The pilot's own belt shape (cobra: the belt scope is the target package alone). A
    patch that stops ``util`` compiling is outside ``./calc``, so the belt run alone never
    sees it; the module build gate does."""
    repo, task, q, (config, runner, ex) = _qualified(tmp_path, BELT_TARGET_ONLY)
    assert task.belt_scope == ("./calc",)
    assert q.red["baseline_parse_error"].startswith("unattributed failure")
    ws = _trial(repo, task, tmp_path / "trial", config)
    try:
        (ws.root / gorepo.SRC_TWICE).write_text(_TWICE_BROKEN, encoding="utf-8")
        res = grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()
    assert res.belts.target_green is True
    assert res.belt_run is not None
    assert res.belt_run.parse_error.startswith("unattributed failure (the module build gate")
    assert res.belts.no_new_failures is False and res.clean is False


@needs_go
def test_the_gold_of_a_target_only_belt_still_grades_clean_through_the_gate(
    tmp_path: Path,
) -> None:
    """The gate costs a correct patch nothing: the gold itself grades clean."""
    repo, task, _, (config, runner, ex) = _qualified(tmp_path, BELT_TARGET_ONLY)
    ws = _trial(repo, task, tmp_path / "trial", config)
    try:
        res = grade(ws, task, config=config, runner=runner, executor=ex)
    finally:
        ws.remove()
    assert res.clean is True, res.note


def test_the_gate_runs_only_when_the_belt_is_narrower_than_the_module() -> None:
    runner = get_runner(gorepo.config(BELT_TARGET_ONLY))
    assert runner.module_gate_scope(("./calc",)) == ("./...",)
    assert runner.module_gate_scope(()) is None
    assert runner.module_gate_scope(("./...",)) is None
    assert runner.module_gate_scope(("./calc", "./...")) is None
    pytest_runner = get_runner(RepoConfig(name="py", language=Language.PYTHON, runner="pytest"))
    assert pytest_runner.module_gate_scope(("tests/test_a.py",)) is None


def test_every_belt_scope_run_goes_through_the_module_build_gate() -> None:
    """The gate is part of belt 3's instrument wherever a belt scope is run — the grade, the
    qualification's baseline and gold, the miner and the factory. A new caller that ran a
    belt scope with ``run_for`` would skip it; this refuses that call."""
    src = Path(__file__).resolve().parents[1] / "src" / "crb"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run_for"
            ):
                continue
            names = {
                n.id if isinstance(n, ast.Name) else n.attr
                for arg in (*node.args, *(k.value for k in node.keywords))
                for n in ast.walk(arg)
                if isinstance(n, (ast.Name, ast.Attribute))
            }
            if any("belt" in n for n in names):
                offenders.append(f"{path.relative_to(src)}:{node.lineno}")
    assert offenders == [], f"run a belt scope with run_belt_for: {offenders}"


# ---------------------------------------------------------------------------
# The miner without the gold check: which unattributed baselines it accepts
# ---------------------------------------------------------------------------


def _half_repo(tmp_path: Path, extra: dict[str, str] | None = None):
    """``util.Half`` is wrong at the parent; the commit fixes it and adds ``TestHalf``, which
    compiles at the parent and fails there (a RED that names its test)."""
    from fixtures.langs import two_commit_repo

    initial = {
        **gorepo._INITIAL,
        "util/half.go": (
            "package util\n\n// Half is wrong at the parent.\nfunc Half(a int) int { return a }\n"
        ),
        **(extra or {}),
    }
    feat = {
        "util/half.go": "package util\n\n// Half returns a / 2.\nfunc Half(a int) int { return a / 2 }\n",
        "util/half_test.go": (
            'package util\n\nimport "testing"\n\n'
            "func TestHalf(t *testing.T) {\n"
            "\tif Half(4) != 2 {\n"
            '\t\tt.Fatal("Half")\n'
            "\t}\n}\n"
        ),
    }
    return two_commit_repo(tmp_path / "half", initial, feat)


@needs_go
def test_the_miner_without_the_gold_check_refuses_a_named_red_beside_an_unattributed_baseline(
    tmp_path: Path,
) -> None:
    root, feat_sha = _half_repo(tmp_path, {"other/other.go": _OTHER_BROKEN})
    repo, config = GitRepo(root), gorepo.config(BELT_BARE)
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        gold=False,
    )
    assert outcome.task is None
    assert outcome.skipped_reason.startswith(QUAL_BASELINE_UNATTRIBUTED)


@needs_go
def test_the_miner_without_the_gold_check_accepts_a_red_that_is_partly_a_build_failure(
    tmp_path: Path,
) -> None:
    """``TestHalf`` fails by name and ``calc``'s new test does not compile at the parent: the
    unattributed baseline is explained by the RED's own build failure and recorded."""
    from fixtures.langs import two_commit_repo

    initial = {
        **gorepo._INITIAL,
        "util/half.go": (
            "package util\n\n// Half is wrong at the parent.\nfunc Half(a int) int { return a }\n"
        ),
    }
    feat = {
        **gorepo._FEAT,
        "util/half.go": "package util\n\n// Half returns a / 2.\nfunc Half(a int) int { return a / 2 }\n",
        "util/half_test.go": (
            'package util\n\nimport "testing"\n\n'
            "func TestHalf(t *testing.T) {\n"
            "\tif Half(4) != 2 {\n"
            '\t\tt.Fatal("Half")\n'
            "\t}\n}\n"
        ),
    }
    root, feat_sha = two_commit_repo(tmp_path / "two", initial, feat)
    repo, config = GitRepo(root), gorepo.config(BELT_BARE)
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        gold=False,
    )
    assert outcome.task is not None, outcome.skipped_reason
    assert outcome.task.labels["baseline_parse_error"].startswith("unattributed failure")
    assert outcome.task.baseline_failing == (f"{gorepo.UTIL_PKG}::TestHalf",)
