"""JavaScript: the full instrument on the four real runners — ``node --test``,
``vitest``, ``jest``, ``mocha`` — parametrised over :mod:`tests.fixtures.langs.noderepo`.

Per tool, with a :class:`LocalExecutor`:

1. ``iter_candidates`` finds the feat commit;
2. ``qualify`` → RED at the parent (``sub.test.js`` cannot load ``../src/sub``),
   baseline captured, gold GREEN;
3. gold overlay grades ``clean``;  4. no-op → ``target_green=False``;
5. tampered test → DQ;  6. regression in ``add`` → belt 3 fails with ``"add works"``;
7. scope mapping (test files ARE the scope) and ``parse`` of the real reporter
   output (JUnit XML for node, JSON for the other three).

``node --test`` is dependency-free. vitest / jest / mocha are installed once per
session into ``tests/.cache/node_modules_<tool>`` and symlinked into the
fixture; a failed install (no network) skips that tool with npm's reason.

Runs only when ``node`` is on PATH (``@pytest.mark.toolchain("node")``).
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

noderepo = langs.fixture_module("noderepo")

pytestmark = [
    pytest.mark.toolchain("node"),
    pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH"),
]


# ---------------------------------------------------------------------------
# Fixtures — one repo + one qualification per tool; a fresh worktree per trial
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=noderepo.TOOLS)
def tool(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="module")
def built(tool: str, tmp_path_factory: pytest.TempPathFactory) -> tuple[GitRepo, str]:
    node_modules = None if tool == "node" else langs.npm_cache(tool)
    root, feat_sha = noderepo.build(tmp_path_factory.mktemp(tool), tool, node_modules=node_modules)
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config(tool: str) -> RepoConfig:
    return noderepo.config(tool)


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


def _write_add(ws: Workspace, tool: str, *, broken: bool) -> None:
    (ws.root / noderepo.SRC_ADD).write_text(
        noderepo.add_source(tool, broken=broken), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1–2  mining
# ---------------------------------------------------------------------------


def test_iter_candidates_finds_feat_commit(candidate: Candidate, built: tuple[GitRepo, str], tool):
    assert candidate.sha == built[1]
    assert candidate.src_files == (noderepo.SRC_SUB,)
    assert candidate.test_files == (noderepo.test_sub(tool),)


def test_qualify_red_at_parent_baseline_captured_gold_clean(task: TaskSpec, tool: str):
    assert task.red_checked is True
    assert task.gold_clean is True, task.gold_note
    assert task.target_tests == (noderepo.test_sub(tool),)
    assert task.belt_scope == BARE
    assert task.language == "javascript"
    if tool == "node":
        # node's JUnit reporter attributes a file that fails to load to the file itself,
        # so the parent baseline records it (and belt 3 is relative to that).
        assert task.baseline_failing == (noderepo.test_sub(tool),)
        assert "baseline_parse_error" not in task.labels
    else:
        # vitest / jest report a suite that failed to load with no test ids
        # (→ "unattributed"); mocha prints the load error instead of its JSON
        # (→ "mocha json missing"). Either way: empty baseline + parse error recorded.
        assert task.baseline_failing == ()
        assert task.labels.get("baseline_parse_error")


# ---------------------------------------------------------------------------
# 3–6  grading
# ---------------------------------------------------------------------------


def test_grade_gold_overlay_is_clean(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is True, res.to_dict()
    assert res.belts.all_true
    assert res.changed_files == (noderepo.SRC_SUB,)
    assert res.diff is not None and res.diff.files == (noderepo.SRC_SUB,)
    assert res.target_run is not None and res.target_run.failing == frozenset()
    assert res.belt_run is not None and res.belt_run.failing == frozenset()


def test_worktree_gets_node_modules(trial, tool):
    # Workspace._post_create re-links the main clone's node_modules into the worktree
    link = trial.root / "node_modules"
    if tool == "node":
        assert not link.exists()
    else:
        assert link.is_symlink() and (link / ".bin" / tool).exists()
        assert "node_modules" not in trial.touched_files()  # git-ignored


def test_grade_noop_worktree_is_not_green(trial, task, config, runner, executor):
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.tests_unmodified is True
    assert res.belts.target_green is False
    assert res.target_run is not None and res.target_run.red


def test_grade_tampered_test_is_disqualified(trial, task, config, runner, executor, tool):
    trial.overlay_sources(task.src_files)
    p = trial.root / noderepo.test_sub(tool)
    p.write_text(p.read_text(encoding="utf-8") + "\n// tampered\n", encoding="utf-8")
    res = _grade(trial, task, config, runner, executor)
    assert res.disqualified is True and res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.tamper_files == (noderepo.test_sub(tool),)


def test_grade_regression_fails_belt3(trial, task, config, runner, executor, tool):
    trial.overlay_sources(task.src_files)
    _write_add(trial, tool, broken=True)
    res = _grade(trial, task, config, runner, executor)
    assert res.clean is False
    assert res.belts.target_green is True  # the target file never imports add
    assert res.belts.no_new_failures is False
    assert res.new_failures == (noderepo.ADD_TEST_ID,)
    assert set(res.changed_files) == {noderepo.SRC_SUB, noderepo.SRC_ADD}


# ---------------------------------------------------------------------------
# 7  scope mapping + parse against the real tool
# ---------------------------------------------------------------------------


def test_target_scope_is_the_test_files(runner: BaseRunner, tool: str):
    sub, add = noderepo.test_sub(tool), noderepo.test_add(tool)
    assert runner.target_scope([sub]) == (sub,)
    assert runner.target_scope([sub, add, sub]) == (add, sub)


def test_belt_scope_policies(config: RepoConfig, tool: str):
    sub = noderepo.test_sub(tool)
    assert get_runner(noderepo.config(tool, BELT_TARGET_ONLY)).belt_scope((sub,), [sub]) == (sub,)
    assert get_runner(noderepo.config(tool, BELT_AFFECTED_DIRS)).belt_scope((sub,), [sub]) == (
        noderepo.test_dir(tool) + "/",
    )
    assert get_runner(config).belt_scope((sub,), [sub]) == BARE


def test_command_shape(runner: BaseRunner, executor: LocalExecutor, built, tool: str):
    root = built[0].path
    sub = noderepo.test_sub(tool)
    cmd = runner.command(root, (sub,), executor=executor, timeout=60)
    assert cmd.argv[-1] == sub
    assert cmd.env["NODE_ENV"] == "test"
    assert cmd.env["NODE_PATH"] == str(root / "node_modules")
    if tool == "node":
        assert cmd.argv[1:4] == (
            "--test",
            "--test-reporter=junit",
            "--test-reporter-destination=stdout",
        )
    else:
        assert cmd.argv[0] == str(root / "node_modules" / ".bin" / tool)  # repo-local binary
    reporter = {
        "node": "--test-reporter=junit",
        "vitest": "--reporter=json",
        "jest": "--json",
        "mocha": "json",
    }[tool]
    assert reporter in cmd.argv


def test_parse_attributes_failures_from_reporter_output(trial, task, runner, executor, tool):
    trial.overlay_sources(task.src_files)
    _write_add(trial, tool, broken=True)
    red = runner.run(executor, trial.root, (noderepo.test_add(tool),))
    assert red.returncode != 0 and not red.timed_out
    assert red.failing == frozenset({noderepo.ADD_TEST_ID})
    assert red.parse_error == ""
    _write_add(trial, tool, broken=False)
    green = runner.run(executor, trial.root, BARE)  # default discovery finds both files
    assert green.green and green.failing == frozenset()


def test_parse_load_failure_fails_closed(trial, runner, executor, tool):
    # parent + overlaid sub.test.js: ../src/sub does not exist
    run = runner.run(executor, trial.root, (noderepo.test_sub(tool),))
    assert run.red
    if tool == "node":
        assert run.failing == frozenset({noderepo.test_sub(tool)})
    elif tool == "mocha":
        assert run.failing == frozenset()
        assert run.parse_error == "mocha json missing"
    else:
        assert run.failing == frozenset()
        assert run.parse_error.startswith("unattributed failure")
