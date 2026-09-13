"""Go: the full instrument on a real ``go test -json`` toolchain.

Proves, on :mod:`tests.fixtures.langs.gorepo` with a :class:`LocalExecutor`:

1. ``iter_candidates`` finds the feat commit;
2. ``qualify`` → RED at the parent, baseline captured, gold GREEN (``gold_clean``);
3. a gold-overlaid worktree grades ``clean``;
4. a no-op worktree is ``target_green=False``;
5. a tampered target test is disqualified;
6. a regression in a neighbouring unit fails belt 3 (other package) / belt 2
   (same package — Go's target scope is the whole package);
7. scope mapping (``calc/x_test.go`` → ``./calc``) and ``parse`` against the real
   ``-json`` stream, including the unattributed build-failure path.

Runs only when ``go`` is on PATH (``@pytest.mark.toolchain("go")``).
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

gorepo = langs.fixture_module("gorepo")

pytestmark = [
    pytest.mark.toolchain("go"),
    pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH"),
]


# ---------------------------------------------------------------------------
# Fixtures (module-scoped: one repo, one qualification; fresh worktree per trial)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[GitRepo, str]:
    root, feat_sha = gorepo.build(tmp_path_factory.mktemp("go"))
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config() -> RepoConfig:
    return gorepo.config()


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


# ---------------------------------------------------------------------------
# 1–2  mining
# ---------------------------------------------------------------------------


def test_iter_candidates_finds_feat_commit(candidate: Candidate, built: tuple[GitRepo, str]):
    assert candidate.sha == built[1]
    assert candidate.src_files == (gorepo.SRC_SUB,)
    assert candidate.test_files == (gorepo.TEST_SUB,)


def test_qualify_red_at_parent_baseline_captured_gold_clean(task: TaskSpec):
    assert task.red_checked is True
    assert task.gold_clean is True, task.gold_note
    assert task.target_tests == ("./calc",)
    assert task.belt_scope == BARE  # config is BELT_BARE → ./...
    assert task.language == "go"
    # At the parent the overlaid test does not compile: the belt run is RED but
    # unattributed, so the baseline is empty and the parse error is recorded.
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
    assert res.changed_files == (gorepo.SRC_SUB,)
    assert res.diff is not None and res.diff.files == (gorepo.SRC_SUB,)
    assert res.target_run is not None and res.target_run.failing == frozenset()
    assert res.belt_run is not None and res.belt_run.failing == frozenset()


def test_grade_noop_worktree_is_not_green(trial, task, config, runner, executor):
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.tests_unmodified is True
    assert res.belts.target_green is False
    assert res.belts.no_new_failures is None  # never reached
    assert res.target_run is not None and "unattributed" in res.target_run.parse_error


def test_grade_tampered_test_is_disqualified(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    p = trial.root / gorepo.TEST_SUB
    p.write_text(p.read_text(encoding="utf-8") + "\n// tampered\n", encoding="utf-8")
    res = _grade(trial, task, config, runner, executor)
    assert res.disqualified is True
    assert res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.tamper_files == (gorepo.TEST_SUB,)
    assert res.target_run is None  # DQ short-circuits before any test runs


def test_grade_regression_in_other_package_fails_belt3(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    (trial.root / gorepo.SRC_TWICE).write_text(gorepo.BREAK_TWICE, encoding="utf-8")
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.target_green is True
    assert res.belts.no_new_failures is False
    assert res.new_failures == (f"{gorepo.UTIL_PKG}::TestTwice",)
    assert res.belts.source_changed is True
    assert set(res.changed_files) == {gorepo.SRC_SUB, gorepo.SRC_TWICE}


def test_grade_regression_in_target_package_fails_belt2(trial, task, config, runner, executor):
    # Go's target scope is the package: breaking Add is seen by the target run.
    trial.overlay_sources(task.src_files)
    (trial.root / gorepo.SRC_ADD).write_text(gorepo.BREAK_ADD, encoding="utf-8")
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.target_green is False
    assert res.target_run is not None
    assert res.target_run.failing == frozenset({f"{gorepo.CALC_PKG}::TestAdd"})


# ---------------------------------------------------------------------------
# 7  scope mapping + parse against the real tool
# ---------------------------------------------------------------------------


def test_target_scope_maps_test_files_to_packages(runner: BaseRunner):
    assert runner.target_scope([gorepo.TEST_SUB]) == ("./calc",)
    assert runner.target_scope([gorepo.TEST_SUB, gorepo.TEST_ADD]) == ("./calc",)
    assert runner.target_scope([gorepo.TEST_SUB, gorepo.TEST_TWICE]) == ("./calc", "./util")
    assert runner.target_scope(["root_test.go"]) == ("./",)


def test_belt_scope_policies(config: RepoConfig):
    target = ("./calc",)
    assert get_runner(gorepo.config(BELT_TARGET_ONLY)).belt_scope(target, [gorepo.TEST_SUB]) == (
        "./calc",
    )
    assert get_runner(config).belt_scope(target, [gorepo.TEST_SUB]) == BARE
    assert get_runner(gorepo.config(("./calc", "./util"))).belt_scope(target, []) == (
        "./calc",
        "./util",
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT (src/crb/core/runners/go_runner.py): GoRunner inherits BaseRunner.belt_scope, "
        "so AFFECTED_DIRS yields 'calc/' — go interprets that as an import path "
        "('package calc is not in std'), not './calc'. Fix: override belt_scope to return "
        "self.target_scope(test_files) for AFFECTED_DIRS."
    ),
)
def test_belt_scope_affected_dirs_is_addressable(trial, task, executor):
    r = get_runner(gorepo.config(BELT_AFFECTED_DIRS))
    scope = r.belt_scope(task.target_tests, task.test_files)
    assert scope == ("./calc",)
    trial.overlay_sources(task.src_files)
    assert r.run(executor, trial.root, scope).green


def test_command_shape(runner: BaseRunner, executor: LocalExecutor, tmp_path: Path):
    cmd = runner.command(tmp_path, ("./calc",), executor=executor, timeout=60)
    assert cmd.argv[1:] == ("test", "-json", "./calc")
    assert cmd.argv[0].endswith("go")
    assert "-count=1" in cmd.env["GOFLAGS"]
    assert cmd.env["GOTOOLCHAIN"] == "local"
    assert cmd.env["CGO_ENABLED"] == "0"
    bare = runner.command(tmp_path, BARE, executor=executor, timeout=60)
    assert bare.argv[-1] == "./..."


def test_parse_attributes_failures_from_json_stream(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    (trial.root / gorepo.SRC_ADD).write_text(gorepo.BREAK_ADD, encoding="utf-8")
    red = runner.run(executor, trial.root, ("./calc",))
    assert red.returncode != 0 and not red.timed_out
    assert red.failing == frozenset({f"{gorepo.CALC_PKG}::TestAdd"})
    assert red.parse_error == ""
    assert "TestAdd" in red.tail

    (trial.root / gorepo.SRC_ADD).write_text(gorepo._INITIAL[gorepo.SRC_ADD], encoding="utf-8")
    green = runner.run(executor, trial.root, ("./calc",))
    assert green.green and green.failing == frozenset()


def test_parse_build_failure_fails_closed(trial, runner, executor):
    # parent + overlaid sub_test.go: undefined Sub → build-fail event, no Test ids
    run = runner.run(executor, trial.root, ("./calc",))
    assert run.red
    assert run.failing == frozenset()
    assert run.parse_error.startswith("unattributed failure")
    assert "undefined: Sub" in run.tail
