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

Navigation
----------
What it is:   The Go toolchain suite — the full instrument on a real ``go test -json``.
What it does: Pins, on ``fixtures.langs.gorepo``, that the miner finds the feat commit, RED at the
              parent with the baseline captured and the gold GREEN, that gold grades clean, noop
              is not green, tamper is disqualified, a regression in the other package fails belt
              3 and in the target package fails belt 2 (Go's target scope is the whole package),
              the scope mapping (``calc/x_test.go`` → ``./calc``), the belt-scope policies, the
              command shape, and ``parse`` on the real JSON stream including the unattributed
              build-failure path.
How:          Module-scoped fixture build → ``iter_candidates`` / ``qualify`` / ``grade`` with a
              ``LocalExecutor``; skipped without ``go`` on PATH.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/runners/go_runner.py (under test), tests/fixtures/langs/gorepo.py
              (the fixture), tests/conftest_langs.py (the probes), tests/test_runners_parsers.py
              (the parser on canned output), docs/CONTRIBUTING.md (how to add a runner)
Tested by:    tests/test_runners_go.py
Touch when:   the go runner's argv or parser changes; onboarding a Go module whose package
              layout the scope mapping cannot address.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import Candidate, qualify
from crb.core.runners import get_runner
from crb.core.runners.base import BARE, BaseRunner
from crb.core.spec import BELT_AFFECTED_DIRS, BELT_TARGET_ONLY, RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures.posture import grade_adhoc as grade

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
    """The feat task qualified once through the real miner; a skip reason here
    is a fixture failure.
    """
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
    """A fresh worktree per test at the parent with the feat tests overlaid (RED), removed
    afterwards.
    """
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
    assert cmd.exec_tmp is True  # go test execs the binaries it builds under /tmp
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


# ---------------------------------------------------------------------------
# A sealed dependency set bound to the command (ADR-0019)
# ---------------------------------------------------------------------------


def _sealed_gomod(tmp_path: Path):  # type: ignore[no-untyped-def]
    from crb.provision.store import BundleStore

    store = BundleStore(tmp_path / "deps")
    st = store.stage()
    (st / "out" / "gomod" / "cache").mkdir(parents=True)
    key = "dep_" + "9" * 64
    store.seal(st, {"lang": "go", "key": key})
    return store, key


def test_command_binds_the_bundle_offline_under_docker(tmp_path: Path) -> None:
    from crb.core.deps import DepsBinding
    from crb.core.execution import DockerExecutor, DockerSettings
    from crb.provision import go as go_recipe

    store, key = _sealed_gomod(tmp_path)
    mount = store.mount(key, "go", "gomod", "/deps/gomod")
    binding = DepsBinding(
        role="gold",
        lang="go",
        scheme="go.modcache.v1",
        key=key,
        mounts=(mount,),
        env=go_recipe.binding_env(),
        local_env=go_recipe.local_env(mount.host_path),
    )
    runner = get_runner(gorepo.config())
    ex = DockerExecutor(
        DockerSettings(image="crb-sandbox-go:x", docker_binary="/usr/bin/true"), verify_daemon=False
    )
    runner.deps = binding
    cmd = runner.command(tmp_path, ("./calc",), executor=ex, timeout=60)
    assert cmd.env == {
        "GOFLAGS": "-count=1 -mod=mod",
        "GOTOOLCHAIN": "local",
        "CGO_ENABLED": "0",
        "GOCACHE": "/tmp/gocache",
        "GOMODCACHE": "/deps/gomod",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOVCS": "*:off",
        "GOWORK": "off",
        "GOENV": "off",
    }
    assert cmd.ro_mounts == (mount,) and cmd.exec_tmp is True
    argv = ex.build_argv(cmd)
    assert f"type=bind,src={mount.host_path.resolve()},dst=/deps/gomod,readonly" in argv
    assert "/tmp/gomod" not in " ".join(argv)
    # on the host the same binding points at the store's own path, and mounts nothing
    local = runner.command(tmp_path, ("./calc",), executor=LocalExecutor(), timeout=60)
    assert local.env["GOMODCACHE"] == str(mount.host_path) and local.env["GOPROXY"] == "off"
    assert local.ro_mounts == ()
    # the env probe is `go list -deps -test ./...`, offline, with the same binding
    probe = runner.env_probe_command(tmp_path, (), executor=ex, timeout=60)
    assert probe is not None
    assert probe.argv == ("go", "list", "-deps", "-test", "./...")
    assert probe.env["GOPROXY"] == "off" and probe.ro_mounts == (mount,)


def test_command_is_unchanged_without_a_binding(tmp_path: Path) -> None:
    from crb.core.execution import DockerExecutor, DockerSettings

    runner = get_runner(gorepo.config())
    ex = DockerExecutor(
        DockerSettings(image="crb-sandbox-go:x", docker_binary="/usr/bin/true"), verify_daemon=False
    )
    cmd = runner.command(tmp_path, ("./calc",), executor=ex, timeout=60)
    assert cmd.env == {
        "GOFLAGS": "-count=1 -mod=mod",
        "GOTOOLCHAIN": "local",
        "CGO_ENABLED": "0",
        "GOCACHE": "/tmp/gocache",
        "GOMODCACHE": "/tmp/gomod",
    }
    assert cmd.ro_mounts == () and cmd.writable_paths == () and cmd.exec_tmp is True
    local = runner.command(tmp_path, ("./calc",), executor=LocalExecutor(), timeout=60)
    assert local.env == {"GOFLAGS": "-count=1 -mod=mod", "GOTOOLCHAIN": "local", "CGO_ENABLED": "0"}
