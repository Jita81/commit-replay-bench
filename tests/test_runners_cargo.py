"""Rust: the full instrument on a real ``cargo test`` toolchain.

Proves, on :mod:`tests.fixtures.langs.rustrepo` with a :class:`LocalExecutor`:

1. ``iter_candidates`` finds the feat commit (``src/lib.rs`` modified + ``src/sub.rs``
   + ``tests/sub.rs`` new);
2. ``qualify`` → RED at the parent (``tests/sub.rs`` does not compile), baseline
   captured, gold GREEN;
3. gold overlay grades ``clean``;  4. no-op → ``target_green=False``;
5. tampered test → DQ;  6. regression in ``add`` → belt 3 fails;
7. scope mapping (``tests/sub.rs`` → ``--test sub``) and ``parse`` against the real
   harness output.

Two CargoRunner defects are pinned as strict xfails (see the reasons): the
``--quiet`` harness format hides the ``test … FAILED`` lines the parser needs,
and without ``--no-fail-fast`` cargo stops at the first failing binary.

Runs only when ``cargo`` is on PATH (``@pytest.mark.toolchain("cargo")``).
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

rustrepo = langs.fixture_module("rustrepo")

pytestmark = [
    pytest.mark.toolchain("cargo"),
    pytest.mark.skipif(not langs.has_tool("cargo"), reason="cargo not on PATH"),
]

_QUIET_FORMAT_DEFECT = (
    "DEFECT (src/crb/core/runners/cargo_runner.py): `cargo test --quiet` makes the harness "
    "print `name --- FAILED` (rustc ≥1.8x), not `test name ... FAILED`, so _FAILED never "
    "matches and every RED run is 'unattributed' (baseline can never record a pre-existing "
    "failure). Fix: drop `--quiet` (the stable verbose format) — or match both formats: "
    r"r'^(?:test )?(\S+) (?:\.\.\.|---) FAILED$'."
)
_FAIL_FAST_DEFECT = (
    "DEFECT (src/crb/core/runners/cargo_runner.py): without `--no-fail-fast` cargo stops "
    "after the first failing test binary, so belt 3's failing set is truncated (the "
    "integration binary never runs once the lib unit tests fail). Fix: add `--no-fail-fast`."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[GitRepo, str]:
    root, feat_sha = rustrepo.build(tmp_path_factory.mktemp("rust"))
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config() -> RepoConfig:
    return rustrepo.config()


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


def _break_add(ws: Workspace) -> None:
    (ws.root / rustrepo.SRC_LIB).write_text(rustrepo.LIB_BROKEN, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1–2  mining
# ---------------------------------------------------------------------------


def test_iter_candidates_finds_feat_commit(candidate: Candidate, built: tuple[GitRepo, str]):
    assert candidate.sha == built[1]
    assert set(candidate.src_files) == {rustrepo.SRC_LIB, rustrepo.SRC_SUB}
    assert candidate.test_files == (rustrepo.TEST_SUB,)


def test_qualify_red_at_parent_baseline_captured_gold_clean(task: TaskSpec):
    assert task.red_checked is True
    assert task.gold_clean is True, task.gold_note
    assert task.target_tests == ("sub",)
    assert task.belt_scope == BARE
    assert task.language == "rust"
    # tests/sub.rs cannot compile at the parent → cargo aborts before any harness
    # runs → nothing attributable: empty baseline + recorded parse error.
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
    assert set(res.changed_files) == {rustrepo.SRC_LIB, rustrepo.SRC_SUB}
    assert res.diff is not None and set(res.diff.files) == {rustrepo.SRC_LIB, rustrepo.SRC_SUB}
    # the build wrote target/ but it is git-ignored: nothing else counts as touched
    assert trial.touched_files() == sorted({rustrepo.SRC_LIB, rustrepo.SRC_SUB, rustrepo.TEST_SUB})


def test_grade_noop_worktree_is_not_green(trial, task, config, runner, executor):
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.tests_unmodified is True
    assert res.belts.target_green is False
    assert res.target_run is not None and res.target_run.red
    assert "unattributed" in res.target_run.parse_error


def test_grade_tampered_test_is_disqualified(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    p = trial.root / rustrepo.TEST_SUB
    p.write_text(p.read_text(encoding="utf-8") + "\n// tampered\n", encoding="utf-8")
    res = _grade(trial, task, config, runner, executor)
    assert res.disqualified is True and res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.tamper_files == (rustrepo.TEST_SUB,)


def test_grade_regression_fails_belt3(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    _break_add(trial)
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.target_green is True  # --test sub builds and passes on its own
    assert res.belts.no_new_failures is False
    assert res.belt_run is not None and res.belt_run.red


@pytest.mark.xfail(strict=True, reason=_QUIET_FORMAT_DEFECT)
def test_grade_regression_names_the_broken_tests(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    _break_add(trial)
    res = _grade(trial, task, config, runner, executor)
    assert res.belts.no_new_failures is False
    assert rustrepo.UNIT_ADD_ID in res.new_failures
    assert res.belt_run is not None and res.belt_run.parse_error == ""


# ---------------------------------------------------------------------------
# 7  scope mapping + parse against the real tool
# ---------------------------------------------------------------------------


def test_target_scope_maps_integration_files_to_test_binaries(runner: BaseRunner):
    assert runner.target_scope([rustrepo.TEST_SUB]) == ("sub",)
    assert runner.target_scope([rustrepo.TEST_SUB, rustrepo.TEST_CALC]) == ("calc", "sub")
    assert runner.target_scope(["tests/builder/env.rs"]) == ("builder",)
    # a unit test inside src/ is not an integration binary → run everything
    assert runner.target_scope(["src/lib.rs"]) == ("ALL",)


def test_belt_scope_policies(config: RepoConfig):
    target = ("sub",)
    assert get_runner(rustrepo.config(BELT_TARGET_ONLY)).belt_scope(
        target, [rustrepo.TEST_SUB]
    ) == ("sub",)
    assert get_runner(config).belt_scope(target, [rustrepo.TEST_SUB]) == BARE
    # AFFECTED_DIRS yields 'tests/' which is not a cargo test target: it must fail
    # closed (cargo errors: no test target named `tests/`), never read as green.
    dirs = get_runner(rustrepo.config(BELT_AFFECTED_DIRS)).belt_scope(target, [rustrepo.TEST_SUB])
    assert dirs == ("tests/",)


def test_affected_dirs_scope_fails_closed(trial, task, executor):
    r = get_runner(rustrepo.config(BELT_AFFECTED_DIRS))
    trial.overlay_sources(task.src_files)
    run = r.run(executor, trial.root, ("tests/",))
    assert run.red and run.parse_error.startswith("unattributed")


def test_command_shape(runner: BaseRunner, executor: LocalExecutor, tmp_path: Path):
    cmd = runner.command(tmp_path, ("sub",), executor=executor, timeout=60)
    assert cmd.argv[0].endswith("cargo")
    assert cmd.argv[1] == "test"
    assert "--offline" in cmd.argv and "--locked" not in cmd.argv
    assert cmd.argv[-2:] == ("--test", "sub")
    assert cmd.env["CARGO_TARGET_DIR"] == str(tmp_path / "target")
    assert cmd.env["CARGO_TERM_COLOR"] == "never"
    assert cmd.writable_paths == ("target",)
    assert "--test" not in runner.command(tmp_path, ("ALL",), executor=executor, timeout=60).argv
    assert "--test" not in runner.command(tmp_path, BARE, executor=executor, timeout=60).argv


def test_parse_green_run(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    run = runner.run(executor, trial.root, ("sub",))
    assert run.green and run.failing == frozenset() and run.parse_error == ""


def test_parse_red_run_fails_closed_without_ids(trial, task, runner, executor):
    # What the parser does TODAY on a real failure under --quiet: no ids, but the
    # fail-closed rule still makes the run RED (this is the honest floor).
    trial.overlay_sources(task.src_files)
    _break_add(trial)
    run = runner.run(executor, trial.root, BARE)
    assert run.red and run.returncode != 0
    assert "FAILED" in run.tail


@pytest.mark.xfail(strict=True, reason=_QUIET_FORMAT_DEFECT)
def test_parse_attributes_unit_test_failure(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    _break_add(trial)
    run = runner.run(executor, trial.root, BARE)
    assert rustrepo.UNIT_ADD_ID in run.failing
    assert run.parse_error == ""


@pytest.mark.xfail(strict=True, reason=_FAIL_FAST_DEFECT)
def test_parse_reports_every_failing_binary(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    _break_add(trial)
    run = runner.run(executor, trial.root, BARE)
    # both the lib unit test AND the integration test break; cargo must run both
    assert rustrepo.INTEGRATION_ADD_ID in run.tail
