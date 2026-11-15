"""The builder-side tool check: the test command handed to a builder must start in the
builder's own environment, or the attempt is refused before any model call.

A Python repository whose ``uv.lock`` holds no runtime dependency and ``pytest`` only in a dev
group resolves to no dependency recipe, so its sealed builder gets no ``/deps`` site and is
handed ``python -m pytest …`` inside a builder image with no ``pytest``. Every attempt was
then paid for a builder that could not run the command its brief gave it. The adapter now
runs the runner's own tool check, derived from that very command, in the builder's
environment first.

Navigation
----------
What it is:   The suite for ``tool_check_command`` / ``builder_tool_refusal``
              (src/crb/builders/toolcheck.py) and their call in ``build_fn_for``'s
              ``attempt_of`` (src/crb/builders/adapter.py).
What it does: Pins that a non-zero exit, a timeout, a cancellation, an environment error and a
              check that raised each refuse the attempt with ``runner tool missing: pytest``
              (a ``harness`` row) before the builder is instantiated or called and before the
              S1 author (a model call) runs; that exit 0 lets the attempt proceed; that the
              check is the handed command with only its argv replaced (and, when executed,
              its wall clock bounded); that an event names the command and its outcome; that
              a sealed builder is checked against the container settings; and that the
              lock this happens on (``uv.lock``, pytest only in a dev group) resolves to no
              recipe, so the handed command carries no sealed site.
How:          The pyrepo fixture with the real ``PytestRunner``; a scripted executor injected
              through ``build_fn_for(tool_check_executor=…)``; a counting fake builder; an S1
              author that records its calls.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/builders/toolcheck.py (the check under test),
              src/crb/builders/adapter.py (``attempt_of``, where it runs),
              src/crb/core/provision.py (``LockInputs.from_git``),
              tests/fixtures/tool_check.py (the scripted executor)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the check's derivation or its refusal changes.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import STOP_DONE, Budget, BuildBrief, BuildOutcome, EscalationLadder, Rung
from crb.builders.brief import S1Arm
from crb.builders.container import (
    BuilderContainerSettings,
    builder_executor,
    harness_link_mounts,
)
from crb.builders.toolcheck import (
    RUNNER_TOOL_MISSING,
    TOOL_CHECK_TIMEOUT_S,
    builder_tool_refusal,
    tool_check_command,
)
from crb.core.execution import (
    TREE_READONLY,
    Command,
    ExecResult,
    LocalExecutor,
    UnconfirmedKill,
)
from crb.core.git import GitRepo
from crb.core.ledger import FAILURE_HARNESS, derive_failure_kind
from crb.core.provision import RECIPE_NONE, LockInputs
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import Language, RepoConfig
from crb.core.workspace import Workspace
from crb.provision import SealedProvider
from crb.provision.config import ProvisionConfig
from fixtures import pyrepo as pr
from fixtures.tool_check import ScriptedExecutor

_CONTAINER = BuilderContainerSettings(image="crb-builder:test", user="10001:10001")


class CountingBuilder:
    """Counts every instantiation and every build; builds nothing."""

    name = "counting"
    made: ClassVar[int] = 0
    built: ClassVar[int] = 0

    def __init__(self, *, model: str, provider: str = "", **_: Any) -> None:
        self.model, self.provider = model, provider
        CountingBuilder.made += 1

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Budget, **_: Any
    ) -> BuildOutcome:
        CountingBuilder.built += 1
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=True,
            stop_reason=STOP_DONE,
            budget=budget,
        )


class _Session:
    """Stands in for ``ContainerSession``: no daemon, no overrides."""

    def __init__(self, settings: BuilderContainerSettings, checkout: Any, **kw: Any) -> None:
        self.checkout = checkout

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def overrides_for(self, builder: str) -> dict[str, Any]:
        return {}


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "counting", CountingBuilder)
    CountingBuilder.made = 0
    CountingBuilder.built = 0


class _Order:
    """What ran, in order: the tool check, the S1 author (the model call before the build)."""

    def __init__(self, result: ExecResult | None = None, raises: BaseException | None = None):
        self.calls: list[str] = []
        self.settings_seen: list[Any] = []
        order = self

        class _Probe(ScriptedExecutor):
            def run(self, cmd: Command) -> ExecResult:
                order.calls.append("tool_check")
                return super().run(cmd)

        self.probe = _Probe(
            result=result if result is not None else ExecResult(0, "pytest 8\n", ""),
            raises=raises,
        )

    def executor_for(self, settings: Any, ws: Any) -> ScriptedExecutor:
        self.settings_seen.append(settings)
        return self.probe

    def author(self, ws: Any, subject: str, message: str) -> tuple[str, str]:
        self.calls.append("author")
        raise RuntimeError("the author stops here")


def _attempt(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    order: _Order,
    *,
    s1: bool = False,
    sealed: bool = False,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    extra: dict[str, Any] = {}
    if sealed:
        assert monkeypatch is not None
        monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"counting"}))
        extra = {"container": _CONTAINER, "session_factory": _Session}
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("counting", "m"),)),
        budget=Budget(),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        config=pyrepo.config,
        on_event=lambda a, p: events.append((a, dict(p))),
        s1=S1Arm(author=order.author, author_model="t1") if s1 else None,
        tool_check_executor=order.executor_for,
        **extra,
    )
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=not s1)
    try:
        return fn(ws, pyrepo.feat_task(), "blind" if s1 else "sighted", "counting:m"), events
    finally:
        ws.remove()


_REFUSING: dict[str, tuple[ExecResult | None, BaseException | None, str]] = {
    "nonzero_exit": (
        ExecResult(1, "", "/usr/local/bin/python: No module named pytest\n"),
        None,
        "exit 1: /usr/local/bin/python: No module named pytest",
    ),
    "timeout": (ExecResult(124, "", "", timed_out=True), None, "timed out"),
    "cancelled": (ExecResult(130, "", "", cancelled=True), None, "cancelled before it finished"),
    "env_error": (
        ExecResult(0, "", "copy failed", env_error="tree_copy_failed"),
        None,
        "environment error (tree_copy_failed): copy failed",
    ),
    "raised": (None, OSError("exec format error"), "the check could not run: OSError"),
}


@pytest.mark.parametrize("case", list(_REFUSING))
def test_a_tool_check_that_does_not_pass_refuses_before_any_builder_or_model_call(
    pyrepo: pr.PyRepo, tmp_path: Path, case: str
) -> None:
    result, raises, says = _REFUSING[case]
    order = _Order(result, raises)
    attempt, events = _attempt(pyrepo, tmp_path, order, s1=True)
    assert attempt.error.startswith(RUNNER_TOOL_MISSING + "pytest — ")
    assert says in attempt.error and "refused before any builder call" in attempt.error
    # the check ran, and nothing after it: no S1 author (a model call), no builder
    assert order.calls == ["tool_check"]
    assert CountingBuilder.made == 0 and CountingBuilder.built == 0
    assert (
        derive_failure_kind(clean=False, disqualified=False, error=attempt.error) == FAILURE_HARNESS
    )
    # one documented ``builder.refused`` names the check's command, where it ran and why
    (refused,) = [p for a, p in events if a == "builder.refused"]
    assert refused["error"] == attempt.error
    assert "builder's own environment (host)" in refused["error"]
    shown = " ".join(("-m", "pytest", *_STARTUP_OVERRIDES, "--version"))
    assert shown + "` " + says in refused["error"]


def test_a_passing_tool_check_runs_before_the_model_and_lets_the_attempt_proceed(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    order = _Order()
    attempt, _ = _attempt(pyrepo, tmp_path, order, s1=True)
    # the check came first; then the S1 author — the first model call — was reached
    assert order.calls == ["tool_check", "author"]
    assert attempt.error.startswith("authoring:")


def test_exit_zero_lets_the_builder_build(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    order = _Order()
    attempt, events = _attempt(pyrepo, tmp_path, order)
    assert attempt.error == "" and CountingBuilder.made == 1 and CountingBuilder.built == 1
    assert order.calls == ["tool_check"]
    assert "builder.refused" not in [a for a, _ in events]


def test_a_sealed_builder_is_checked_in_its_container(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = _Order(ExecResult(1, "", "No module named pytest"))
    attempt, events = _attempt(pyrepo, tmp_path, order, sealed=True, monkeypatch=monkeypatch)
    assert order.settings_seen == [_CONTAINER]
    assert attempt.error.startswith(RUNNER_TOOL_MISSING + "pytest")
    assert "builder's own environment (docker)" in attempt.error
    assert attempt.labels["builder_executor"] == "docker"
    assert CountingBuilder.made == 0 and CountingBuilder.built == 0
    refused = next(p for a, p in events if a == "builder.refused")
    assert "builder's own environment (docker)" in refused["error"]


def test_the_check_is_the_handed_command_with_only_its_argv_replaced(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    order = _Order()
    runner = PytestRunner(pyrepo.config)
    executor = LocalExecutor()
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("counting", "m"),)),
        budget=Budget(),
        runner=runner,
        executor=executor,
        config=pyrepo.config,
        tool_check_executor=order.executor_for,
    )
    ws = pyrepo.trial(tmp_path / "h")
    try:
        handed = adapter.handed_test_command(runner, executor, ws.root, (), deps=None)
        fn(ws, pyrepo.feat_task(), "sighted", "counting:m")
    finally:
        ws.remove()
    assert handed is not None
    derived = tool_check_command(runner, handed)
    assert derived is not None
    tool, check = derived
    assert tool == "pytest" and check.argv == (
        handed.argv[0],
        "-m",
        "pytest",
        *_STARTUP_OVERRIDES,
        "--version",
    )
    for f in dataclasses.fields(Command):
        if f.name != "argv":
            assert getattr(check, f.name) == getattr(handed, f.name), f.name
    # the attempt ran exactly this check, with only its wall clock bounded on top
    (ran,) = order.probe.seen
    assert ran == dataclasses.replace(check, timeout=min(check.timeout, TOOL_CHECK_TIMEOUT_S))


#: The startup overrides the runner's command passes before any test runs: a project's own
#: ``addopts`` and two plugins are neutralised. The check must start pytest the same way.
_STARTUP_OVERRIDES = ("-p", "no:cacheprovider", "-p", "no:randomly", "-o", "addopts=")


def test_the_pytest_check_keeps_the_runners_startup_overrides(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    # A project whose addopts names an absent plugin (``-p xdist``) fails ``pytest --version``
    # on pytest 8 although the runner's own command, with ``-o addopts=``, starts.
    runner = PytestRunner(pyrepo.config)
    cmd = runner.command(tmp_path, ("tests/test_a.py",), executor=LocalExecutor(), timeout=60)
    derived = runner.tool_check(cmd.argv)
    assert derived == ("pytest", (cmd.argv[0], "-m", "pytest", *_STARTUP_OVERRIDES, "--version"))


def test_an_unconfirmed_kill_of_the_tool_check_reaches_the_reaper(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    kill = UnconfirmedKill(container="crb-tool-check-x", bound_s=5.0)

    class _Unconfirmed(ScriptedExecutor):
        """A docker executor whose kill of the timed-out check was never confirmed."""

        def run(self, cmd: Command) -> ExecResult:
            self.unconfirmed_kills = [kill]
            return super().run(cmd)

    probe = _Unconfirmed(ExecResult(124, "", "", timed_out=True))
    handed: list[tuple[str, UnconfirmedKill]] = []
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("counting", "m"),)),
        budget=Budget(),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        config=pyrepo.config,
        tool_check_executor=lambda _s, _w: probe,
        on_kill_unconfirmed=lambda task_id, k: handed.append((task_id, k)),
    )
    ws = pyrepo.trial(tmp_path / "k")
    task = pyrepo.feat_task()
    try:
        attempt = fn(ws, task, "sighted", "counting:m")
    finally:
        ws.remove()
    assert attempt.error.startswith(RUNNER_TOOL_MISSING + "pytest")
    assert handed == [(task.task_id, kill)]
    assert CountingBuilder.made == 0


def test_a_runner_without_a_check_is_not_refused(pyrepo: pr.PyRepo) -> None:
    class NoCheck(PytestRunner):
        def tool_check(self, argv: Any) -> None:
            return None

    handed = Command(("python", "-m", "pytest"), root=Path("."))
    assert tool_check_command(NoCheck(pyrepo.config), handed) is None
    probe = ScriptedExecutor()
    assert builder_tool_refusal(
        PytestRunner(pyrepo.config), probe, "pytest", handed, where="host"
    ) == ("ok", "")


# --- the lock this happens on --------------------------------------------------------------

_DEV_ONLY_LOCK = """\
version = 1
requires-python = ">=3.10"

[[package]]
name = "demo"
version = "0.1.0"
source = { virtual = "." }

[package.dev-dependencies]
dev = [
    { name = "pytest" },
]

[package.metadata.requires-dev]
dev = [{ name = "pytest", specifier = ">=8" }]

[[package]]
name = "pytest"
version = "8.4.1"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/pytest-8.4.1-py3-none-any.whl", hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000" },
]
"""

_DEV_ONLY_PYPROJECT = """\
[project]
name = "demo"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]
"""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _dev_only_repo(root: Path) -> tuple[GitRepo, str, str]:
    """A repository whose ``uv.lock`` holds no runtime dependency and pytest only in ``dev``:
    the parent commit, then a gold commit that changes the code."""
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "pyproject.toml").write_text(_DEV_ONLY_PYPROJECT, encoding="utf-8")
    (root / "uv.lock").write_text(_DEV_ONLY_LOCK, encoding="utf-8")
    (root / "demo.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    parent = _git(root, "rev-parse", "HEAD")
    (root / "demo.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "feat: two")
    return GitRepo(root), parent, _git(root, "rev-parse", "HEAD")


def test_a_uv_lock_with_pytest_only_in_a_dev_group_resolves_to_no_recipe_and_no_sealed_site(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, parent, gold = _dev_only_repo(tmp_path / "dev-only")
    config = RepoConfig(name="dev-only", language=Language.PYTHON)
    inputs = LockInputs.from_git(repo, gold, config)
    # the lock is read (it is the input), but with no deps_groups the dev group is not
    assert inputs.recipe == RECIPE_NONE and inputs.py_pins == ()
    assert [f.path for f in inputs.files] == ["uv.lock"]
    # the sealed provider binds nothing, so the builder gets no sealed set to mount
    deps = SealedProvider(ProvisionConfig(store=tmp_path / "store")).resolve(
        repo, config, gold=gold, parent=parent
    )
    assert not deps.builder.sealed
    # …and the command the sealed builder is handed carries no sealed site: only the builder
    # image can put pytest there, which is what the tool check asks before any model call
    order = _Order(ExecResult(1, "", "No module named pytest"))
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"counting"}))
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("counting", "m"),)),
        budget=Budget(),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        config=pyrepo.config,
        container=_CONTAINER,
        session_factory=_Session,
        deps_for=lambda _t: deps,
        tool_check_executor=order.executor_for,
    )
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "counting:m")
    finally:
        ws.remove()
    (ran,) = order.probe.seen
    assert ran.ro_mounts == ()
    assert not any("/deps" in v for v in ran.env.values())
    assert attempt.error.startswith(RUNNER_TOOL_MISSING + "pytest")
    assert CountingBuilder.made == 0 and CountingBuilder.built == 0


# --- where the check runs by default ---------------------------------------------------------


def test_by_default_a_sealed_builder_is_checked_in_the_builder_image(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    probe = ScriptedExecutor(ExecResult(1, "", "No module named pytest"))

    def spy(settings: Any, **kw: Any) -> ScriptedExecutor:
        seen.update(settings=settings, **kw)
        return probe

    monkeypatch.setattr(adapter, "builder_executor", spy)
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"counting"}))
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("counting", "m"),)),
        budget=Budget(),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        config=pyrepo.config,
        container=_CONTAINER,
        session_factory=_Session,
    )
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "counting:m")
        mounts = harness_link_mounts(ws)
    finally:
        ws.remove()
    # the builder's own image and limits, the harness links the session mounts, the
    # worktree read-only: never the run's (grader's) executor
    assert seen["settings"] is _CONTAINER
    assert seen["tree"] == TREE_READONLY and seen["ro_mounts"] == mounts
    assert len(probe.seen) == 1 and attempt.error.startswith(RUNNER_TOOL_MISSING + "pytest")
    assert CountingBuilder.made == 0


def test_the_builder_executor_carries_every_limit_of_the_builder_settings() -> None:
    settings = BuilderContainerSettings(
        image="crb-builder-python:test",
        user="10001:10001",
        memory="3g",
        cpus="3",
        pids_limit=77,
        tmp_size="2g",
        docker_binary="/usr/bin/docker",
        extra_ro_mounts={"/opt/cache": "/cache"},
    )
    ex = builder_executor(settings, ro_mounts={"/opt/links": "/opt/links"}, tree=TREE_READONLY)
    s = ex.settings
    shared = ("image", "user", "memory", "cpus", "pids_limit", "tmp_size", "docker_binary")
    assert {f: getattr(s, f) for f in shared} == {f: getattr(settings, f) for f in shared}
    assert s.extra_ro_mounts == {"/opt/cache": "/cache", "/opt/links": "/opt/links"}
    assert s.tree == TREE_READONLY
