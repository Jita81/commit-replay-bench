"""JVM: the full instrument on a real Maven + surefire toolchain.

Proves, on :mod:`tests.fixtures.langs.jvmrepo` with a :class:`LocalExecutor`:

1. ``iter_candidates`` finds the feat commit;
2. ``qualify`` → RED at the parent (``SubTest`` does not compile), baseline
   captured, gold GREEN;
3. gold overlay grades ``clean``;  4. no-op → ``target_green=False``;
5. tampered test → DQ;  6. regression in ``Calc.add`` → belt 3 fails with
   ``ex.CalcTest::addWorks``;
7. scope mapping (``SubTest.java`` → ``-Dtest=SubTest``) and ``parse`` of the real
   surefire XML.

Maven needs its plugins and JUnit in ``~/.m2``: the module warms them up once,
online, and skips with Maven's own tail when that is impossible (offline host).

Two MavenRunner defects are pinned as strict xfails: the generic
``AFFECTED_DIRS`` scope selects ZERO tests and exits 0 (a silent-green belt),
and ``parse`` reads surefire XML left by a previous run in the same worktree.

Runs only when ``mvn`` is on PATH (``@pytest.mark.toolchain("mvn")``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.grade import grade
from crb.core.mine import Candidate, qualify
from crb.core.runners import get_runner
from crb.core.runners.base import BARE, BaseRunner
from crb.core.spec import BELT_AFFECTED_DIRS, BELT_TARGET_ONLY, RepoConfig, TaskSpec
from crb.core.workspace import Workspace

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

jvmrepo = langs.fixture_module("jvmrepo")

pytestmark = [
    pytest.mark.toolchain("mvn"),
    pytest.mark.skipif(not langs.has_tool("mvn"), reason="mvn not on PATH"),
    pytest.mark.skipif(
        not jvmrepo.java_home(), reason="no JDK: neither brew openjdk nor $JAVA_HOME"
    ),
]

_AFFECTED_DIRS_DEFECT = (
    "DEFECT (src/crb/core/runners/jvm_runner.py): MavenRunner inherits BaseRunner.belt_scope, "
    "so AFFECTED_DIRS yields 'src/test/java/ex/'; surefire's -Dtest= matches NO class for a "
    "path, and with failIfNoSpecifiedTests=false the run exits 0 having run zero tests — "
    "belt 3 is silently green (a false-Q1 vector). Fix: override belt_scope for AFFECTED_DIRS "
    "to strip test_prefix and emit surefire package globs ('ex/**/*'), verified to select "
    "every class in the directory."
)
_STALE_REPORTS_DEFECT = (
    "DEFECT (src/crb/core/runners/jvm_runner.py): parse() reads every target/surefire-reports/"
    "TEST-*.xml under root, and surefire does not clear that directory, so a narrower run "
    "after a wider failing run in the same worktree reports the previous run's failures. "
    "Fix: delete **/target/surefire-reports before executing (override run()), or only parse "
    "reports with mtime >= the run's start."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _warm(tmp_path_factory: pytest.TempPathFactory) -> None:
    langs.maven_warmup(tmp_path_factory.mktemp("mvn-warm"))


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[GitRepo, str]:
    root, feat_sha = jvmrepo.build(tmp_path_factory.mktemp("jvm"))
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config() -> RepoConfig:
    return jvmrepo.config()


@pytest.fixture(scope="module")
def runner(config: RepoConfig) -> BaseRunner:
    return get_runner(config)


@pytest.fixture(scope="module")
def executor() -> LocalExecutor:
    return LocalExecutor()


@pytest.fixture(scope="module")
def candidate(built: tuple[GitRepo, str], config: RepoConfig) -> Candidate:
    repo, feat_sha = built
    return langs.feat_candidate(repo, config, feat_sha)


@pytest.fixture(scope="module")
def task(
    built: tuple[GitRepo, str],
    config: RepoConfig,
    runner: BaseRunner,
    executor: LocalExecutor,
    candidate: Candidate,
    tmp_path_factory: pytest.TempPathFactory,
) -> TaskSpec:
    repo, _ = built
    outcome = qualify(
        repo,
        config,
        candidate,
        runner=runner,
        executor=executor,
        scratch=tmp_path_factory.mktemp("mine"),
    )
    assert outcome.task is not None, outcome.skipped_reason
    return outcome.task


@pytest.fixture
def trial(built: tuple[GitRepo, str], config: RepoConfig, candidate: Candidate, tmp_path: Path):
    repo, _ = built
    ws = langs.trial_worktree(repo, candidate, tmp_path / "trial", config)
    yield ws
    ws.remove()


def _grade(ws: Workspace, task: TaskSpec, config: RepoConfig, runner: BaseRunner, executor):
    return grade(ws, task, config=config, runner=runner, executor=executor)


def _write_calc(ws: Workspace, *, broken: bool) -> None:
    src = jvmrepo.CALC_JAVA_BROKEN if broken else jvmrepo.CALC_JAVA
    (ws.root / jvmrepo.SRC_CALC).write_text(src, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1–2  mining
# ---------------------------------------------------------------------------


def test_iter_candidates_finds_feat_commit(candidate: Candidate, built: tuple[GitRepo, str]):
    assert candidate.sha == built[1]
    assert candidate.src_files == (jvmrepo.SRC_SUB,)
    assert candidate.test_files == (jvmrepo.TEST_SUB,)


def test_qualify_red_at_parent_baseline_captured_gold_clean(task: TaskSpec):
    assert task.red_checked is True
    assert task.gold_clean is True, task.gold_note
    assert task.target_tests == ("SubTest",)
    assert task.belt_scope == BARE
    assert task.language == "jvm"
    # testCompile fails at the parent (Sub is undefined) → no surefire XML at all:
    # empty baseline, parse error recorded.
    assert task.baseline_failing == ()
    assert "unattributed" in task.labels.get("baseline_parse_error", "")


# ---------------------------------------------------------------------------
# 3–6  grading
# ---------------------------------------------------------------------------


def test_grade_gold_overlay_is_clean(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is True, res.to_dict()
    assert res.belts.all_true
    assert res.changed_files == (jvmrepo.SRC_SUB,)
    assert res.diff is not None and res.diff.files == (jvmrepo.SRC_SUB,)
    assert (trial.root / "target" / "surefire-reports").is_dir()  # ran for real
    assert trial.touched_files() == sorted({jvmrepo.SRC_SUB, jvmrepo.TEST_SUB})  # target/ ignored


def test_grade_noop_worktree_is_not_green(trial, task, config, runner, executor):
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.tests_unmodified is True
    assert res.belts.target_green is False
    assert res.target_run is not None and "unattributed" in res.target_run.parse_error
    assert "COMPILATION ERROR" in res.target_run.tail


def test_grade_tampered_test_is_disqualified(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    p = trial.root / jvmrepo.TEST_SUB
    p.write_text(p.read_text(encoding="utf-8") + "\n// tampered\n", encoding="utf-8")
    res = _grade(trial, task, config, runner, executor)
    assert res.disqualified is True and res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.tamper_files == (jvmrepo.TEST_SUB,)


def test_grade_regression_fails_belt3(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    _write_calc(trial, broken=True)
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.target_green is True  # -Dtest=SubTest does not touch Calc
    assert res.belts.no_new_failures is False
    assert res.new_failures == (jvmrepo.CALC_TEST_ID,)
    assert set(res.changed_files) == {jvmrepo.SRC_SUB, jvmrepo.SRC_CALC}


# ---------------------------------------------------------------------------
# 7  scope mapping + parse against the real tool
# ---------------------------------------------------------------------------


def test_target_scope_maps_test_files_to_class_names(runner: BaseRunner):
    assert runner.target_scope([jvmrepo.TEST_SUB]) == ("SubTest",)
    assert runner.target_scope([jvmrepo.TEST_SUB, jvmrepo.TEST_CALC]) == ("CalcTest", "SubTest")
    assert runner.target_scope(["mod/src/test/kotlin/a/b/FooTest.kt"]) == ("FooTest",)


def test_belt_scope_policies(config: RepoConfig):
    target = ("SubTest",)
    assert get_runner(jvmrepo.config(BELT_TARGET_ONLY)).belt_scope(target, [jvmrepo.TEST_SUB]) == (
        "SubTest",
    )
    assert get_runner(config).belt_scope(target, [jvmrepo.TEST_SUB]) == BARE
    assert get_runner(jvmrepo.config(("CalcTest", "SubTest"))).belt_scope(target, []) == (
        "CalcTest",
        "SubTest",
    )


def test_belt_scope_affected_dirs_actually_runs_the_directory(trial, task, executor):
    r = get_runner(jvmrepo.config(BELT_AFFECTED_DIRS))
    scope = r.belt_scope(task.target_tests, task.test_files)
    trial.overlay_sources(task.src_files)
    _write_calc(trial, broken=True)
    run = r.run(executor, trial.root, scope)
    # CalcTest lives in that directory and is broken: the belt MUST be red.
    assert run.red, f"scope {scope!r} ran zero tests and passed"
    assert jvmrepo.CALC_TEST_ID in run.failing


def test_command_shape(config: RepoConfig, executor: LocalExecutor, tmp_path: Path):
    online = get_runner(config).command(tmp_path, ("SubTest",), executor=executor, timeout=60)
    assert online.argv[0].endswith("mvn")
    assert online.argv[1:4] == ("-q", "-B", "-U")
    assert online.argv[4:] == (
        "test",
        "-Dtest=SubTest",
        "-DfailIfNoTests=false",
        "-Dsurefire.failIfNoSpecifiedTests=false",
    )
    assert online.env["JAVA_HOME"] == jvmrepo.java_home()
    assert online.writable_paths == ("target",)
    offline = get_runner(jvmrepo.config(offline=True)).command(
        tmp_path, BARE, executor=executor, timeout=60
    )
    assert "-o" in offline.argv and "-U" not in offline.argv
    assert offline.argv[-1] == "test"  # BARE adds no -Dtest


def test_parse_attributes_failures_from_surefire_xml(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    _write_calc(trial, broken=True)
    red = runner.run(executor, trial.root, BARE)
    assert red.returncode != 0 and not red.timed_out
    assert red.failing == frozenset({jvmrepo.CALC_TEST_ID})
    assert red.parse_error == ""
    _write_calc(trial, broken=False)
    green = runner.run(executor, trial.root, ("SubTest",))
    assert green.green


def test_parse_ignores_reports_from_a_previous_run(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    _write_calc(trial, broken=True)
    assert runner.run(executor, trial.root, BARE).failing == frozenset({jvmrepo.CALC_TEST_ID})
    _write_calc(trial, broken=False)
    narrower = runner.run(executor, trial.root, ("SubTest",))
    assert narrower.returncode == 0
    assert narrower.failing == frozenset(), "stale TEST-ex.CalcTest.xml was attributed"
