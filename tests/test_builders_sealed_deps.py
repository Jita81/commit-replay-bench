"""The sealed session's dependency set reaches what the builder is shown and what gates it.

Navigation
----------
What it is:   The suite for F87-1b: the commands a brief carries and the finish gate's checks,
              when the builder runs in a sealed container session that mounts the task's
              BUILDER set (ADR-0019).
What it does: Pins that the brief's test command, its harness command and the S1 arm's
              authored-test command name the set the session mounted (``GOMODCACHE`` is the
              session's ``/deps/gomod``, never the Go runner's own ``/tmp/gomod``; Python's
              ``PYTHONPATH`` reaches ``/deps/site``); that with no session the command is
              byte-for-byte what it was; that a command that would still point the toolchain
              elsewhere, or a set that is not the builder's, stops the run before the builder
              is paid; and that the finish gate measures its parent baseline and re-runs its
              declared commands under that same set, measured apart from an unsealed rung.
How:          The Go fixture's feat commit through the run's own ``BuildFn`` with a fake
              container session (no daemon) and a docker-named executor that records every
              command and runs none; ``sighted_test_command`` called directly for the guard
              and the Python shape.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0012-builder-in-a-sealed-container.md, docs/adr/0024-working-by-construction.md
Works with:   src/crb/builders/adapter.py (under test: ``sighted_test_command``,
              ``session_env_overrides``, the gate's binding), src/crb/builders/container.py
              (``builder_deps_view``: the set as the session mounts it), src/crb/core/finish_gate.py
              (``command_baseline`` / ``verify`` under a binding), src/crb/core/deps.py (the
              bindings), tests/test_replay_s1_arm.py (the Go fixture's sealed bindings and the
              recording executor this suite reuses), tests/test_ratchet_sealed_deps.py (the
              ratchet that keeps every such call bound)
Tested by:    tests/test_builders_sealed_deps.py
Touch when:   never for a new repository; the session's dependency view, the brief's commands
              or the finish gate's binding change.
"""

from __future__ import annotations

import dataclasses
import shlex
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import Budget, BuildOutcome, EscalationLadder, Rung
from crb.builders.brief import S1Arm
from crb.builders.container import BuilderContainerSettings, builder_deps_view
from crb.core.checks import RepoChecks, resolve
from crb.core.deps import SCHEME_PY, BundleMount, DepsBinding, TaskDeps, register_store_root
from crb.core.execution import Command, ExecResult, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED
from crb.core.runners.go_runner import GoRunner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from crb.provision import python as ppy
from test_replay_s1_arm import (
    GO_AUTHORED,
    GO_AUTHORED_SRC,
    _Docker,
    _go_events,
    _Idle,
    _sealed_go_deps,
    gorepo,
)

#: The Go runner's command as a brief carried it with no binding (the honest-shell corpus
#: keeps the same line): inside the sealed container its ``GOMODCACHE`` overrode the
#: session's ``/deps/gomod`` and no module resolved with the network off (F87-1).
UNBOUND_GO = (
    "CGO_ENABLED=0 GOCACHE=/tmp/gocache GOFLAGS='-count=1 -mod=mod' GOMODCACHE=/tmp/gomod "
    "GOTOOLCHAIN=local go test -json ./calc"
)
VET = {"name": "vet", "argv": ["go", "vet", "./..."]}
#: A worker that runs as root names its builder user explicitly (tests/test_builders_container).
SETTINGS = BuilderContainerSettings(image="crb-builder:test", user="10001:10001")


class _Briefed(_Idle):
    """Registered as ``briefed`` (sealable) and ``host`` (not): records each brief."""

    briefs: ClassVar[list[Any]] = []

    def build(
        self, workspace: Any, brief: Any, budget: Budget, *, on_event: Any = None
    ) -> BuildOutcome:
        _Briefed.briefs.append(brief)
        return super().build(workspace, brief, budget, on_event=on_event)


class _Session:
    """Stands in for ``ContainerSession``: no daemon; records the task's sets it was given."""

    given: ClassVar[list[Any]] = []

    def __init__(self, settings: BuilderContainerSettings, checkout: Any, **kw: Any) -> None:
        _Session.given.append(kw.get("deps"))

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def overrides_for(self, builder: str) -> dict[str, Any]:
        return {}


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "briefed", _Briefed)
    monkeypatch.setitem(builders_pkg._REGISTRY, "host", _Briefed)
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"briefed"}))
    monkeypatch.setattr(_Briefed, "briefs", [])
    monkeypatch.setattr(_Idle, "calls", 0)
    monkeypatch.setattr(_Session, "given", [])


def _attempts(
    tmp_path: Path,
    executor: _Docker,
    deps: TaskDeps,
    *,
    mode: str,
    rungs: tuple[str, ...] = ("briefed",),
    s1: bool = False,
    container: BuilderContainerSettings | None = SETTINGS,
    checks: Any = None,
) -> list[Any]:
    """One attempt per rung of the Go fixture's feat commit through the run's own
    ``BuildFn``, each in its own worktree, with the task's sets ``deps``."""
    root, feat = gorepo.build(tmp_path)
    repo, cfg = GitRepo(root), gorepo.config()
    task = TaskSpec(
        task_id=feat,
        repo=cfg.name,
        subject="feat: add Sub",
        authored=repo.author_date(feat),
        test_files=(gorepo.TEST_SUB,),
        src_files=(gorepo.SRC_SUB,),
        target_tests=("./calc",),
        belt_scope=(),
        language="go",
    )

    def author(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return GO_AUTHORED, GO_AUTHORED_SRC

    ladder = EscalationLadder(tuple(Rung(b, f"m{i}") for i, b in enumerate(rungs)))
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=GoRunner(cfg),
        executor=executor,
        config=cfg,
        s1=S1Arm(author=author, author_model="t1") if s1 else None,
        deps_for=lambda t: deps,
        container=container,
        session_factory=_Session,  # type: ignore[arg-type]
        checks=checks,
    )
    out = []
    for i, label in enumerate(adapter.ladder_labels(ladder)):
        with Workspace.create(repo, feat, tmp_path / f"ws{i}", config=cfg) as ws:
            if mode == MODE_SIGHTED:
                ws.overlay_tests(task.test_files)  # as the run does before a sighted build
            out.append(fn(ws, task, mode, label))
    return out


def _assigned(command: str) -> dict[str, str]:
    """The ``KEY=value`` words that lead ``command`` (its environment prefix)."""
    out: dict[str, str] = {}
    for word in shlex.split(command):
        key, eq, value = word.partition("=")
        if not eq:
            break
        out[key] = value
    return out


def test_brief_commands_do_not_override_the_container_modcache(tmp_path: Path) -> None:
    """F87-1b: the brief's commands were rendered with no binding, so their prefix carried
    the Go runner's ``GOMODCACHE=/tmp/gomod``; the builder copied it inside the sealed
    container, it overrode the session's ``/deps/gomod`` and nothing resolved with the
    network off. Rendered under the builder set with the session's view laid over, every
    command names the set the session mounted — the S3/A0 test command, the harness
    command, and the S1 arm's authored-test command alike."""
    deps = _sealed_go_deps(tmp_path)
    view = builder_deps_view(deps.builder)[1]
    _attempts(tmp_path / "sighted", _Docker(ExecResult(0, "", "")), deps, mode="sighted")
    red = ExecResult(1, _go_events(("run", "TestNew"), ("fail", "TestNew")), "")
    (s1,) = _attempts(tmp_path / "s1", _Docker(red), deps, mode="blind", s1=True)
    assert not (s1.error or "").startswith("authoring:"), s1.error
    sighted, authored = _Briefed.briefs
    commands = {
        "test_command": sighted.test_command,
        "harness_command": sighted.harness_command,
        "S1 test_command": authored.test_command,
    }
    for name, cmd in commands.items():
        assert cmd, f"{name} is empty"
        assert "GOMODCACHE=/tmp/gomod" not in cmd, (name, cmd)
        env = _assigned(cmd)
        assert env.get("GOMODCACHE") == view["GOMODCACHE"] == "/deps/gomod", (name, cmd)
        assert adapter.session_env_overrides(cmd, view) == [], (name, cmd)
    # the session was handed the very set the commands name, and only the builder's
    assert {id(d.builder) for d in _Session.given} == {id(deps.builder)}
    # no session (the builder on the host): the command is exactly what it always was
    _Briefed.briefs.clear()
    _attempts(
        tmp_path / "host", _Docker(ExecResult(0, "", "")), deps, mode="sighted", rungs=("host",)
    )
    (host,) = _Briefed.briefs
    assert host.test_command == UNBOUND_GO


def test_a_brief_command_that_overrides_the_session_set_stops_the_run(tmp_path: Path) -> None:
    """The guard: a prefix whose assignment differs from the sealed session's dependency
    env is read as overriding it — the unbound Go command is — and ``sighted_test_command``
    refuses to render one (a runner whose own words reassign the set). A set that is not
    the builder's is refused before anything renders, and through the ``BuildFn`` the
    refusal stops the run: no attempt row, no label, the builder never paid."""
    deps = _sealed_go_deps(tmp_path)
    view = builder_deps_view(deps.builder)[1]
    assert adapter.session_env_overrides(UNBOUND_GO, view) == [
        "GOMODCACHE=/tmp/gomod (the session sets /deps/gomod)"
    ]
    assert adapter.session_env_overrides(UNBOUND_GO, {}) == []  # no session, nothing to hold
    assert adapter.session_env_overrides("GOMODCACHE='unclosed go test", view) == sorted(view)
    root, _ = gorepo.build(tmp_path / "repo")
    cfg = gorepo.config()

    class Reassigning(GoRunner):
        def command(self, *a: Any, **k: Any) -> Command:
            cmd = super().command(*a, **k)
            return dataclasses.replace(cmd, argv=("GOMODCACHE=/tmp/gomod", *cmd.argv))

    ex = _Docker(ExecResult(0, "", ""))
    with pytest.raises(SandboxUnavailable, match="GOMODCACHE=/tmp/gomod"):
        adapter.sighted_test_command(Reassigning(cfg), ex, root, ("./calc",), deps=deps.builder)
    with pytest.raises(SandboxUnavailable, match="'parent'"):
        adapter.sighted_test_command(GoRunner(cfg), ex, root, ("./calc",), deps=deps.parent)
    # one sealed set serving all three roles is not the builder's either: the run stops
    uniform = TaskDeps.uniform(deps.parent)
    with pytest.raises(SandboxUnavailable, match="'parent'"):
        _attempts(tmp_path / "uniform", ex, uniform, mode="sighted")
    assert _Idle.calls == 0 and _Briefed.briefs == []


def test_the_python_brief_command_reads_the_session_site(tmp_path: Path) -> None:
    """Python/click is the same class of fault: unbound, the brief's ``PYTHONPATH`` was the
    checkout alone and the sealed site at ``/deps/site`` was off it, so the builder's own
    ``python -m pytest`` could not import the repository's dependencies. Bound, the prefix
    carries the site on ``PYTHONPATH`` and the session's ``PATH`` and ``PYTHONNOUSERSITE``."""
    store = register_store_root(tmp_path / "store")
    key = "dep_" + "c" * 64
    host = store / "python" / key / "site"
    host.mkdir(parents=True)
    builder = DepsBinding(
        role="builder",
        lang="python",
        scheme=SCHEME_PY,
        key=key,
        digest="sha256:" + "c" * 64,
        mounts=(BundleMount(host, ppy.INSIDE, key),),
        env={"PYTHONNOUSERSITE": "1", "PATH": f"{ppy.INSIDE}/bin:{ppy.IMAGE_PATH}"},
        local_env={"PYTHONNOUSERSITE": "1"},
    )
    view = builder_deps_view(builder)[1]
    root = tmp_path / "click"
    root.mkdir()
    runner = PytestRunner(RepoConfig(name="click", language=Language.PYTHON, runner="pytest"))
    ex = _Docker(ExecResult(0, "", ""))
    unbound = _assigned(adapter.sighted_test_command(runner, ex, root, ("tests/t.py",), deps=None))
    assert ppy.INSIDE not in unbound["PYTHONPATH"].split(":"), unbound
    bound = _assigned(adapter.sighted_test_command(runner, ex, root, ("tests/t.py",), deps=builder))
    assert ppy.INSIDE in bound["PYTHONPATH"].split(":"), bound
    assert bound["PATH"] == view["PATH"] and bound["PYTHONNOUSERSITE"] == "1", bound


def test_the_finish_gate_runs_under_the_session_set(tmp_path: Path) -> None:
    """F87-1b, the A0+L lever: the gate's declared commands ran with no binding, so under
    the sealed posture ``go vet ./...`` resolved no module, was red at the parent on every
    commit, was recorded ``pre_existing`` and never gated. The baseline and the re-run now
    both carry the builder set the session mounts (its env, and under docker its read-only
    mount — never the parent's or the gold's), and a rung that runs unsealed is measured
    apart, unbound, as before."""
    deps = _sealed_go_deps(tmp_path)
    checks = resolve(RepoChecks.from_config({"finish_gate": True, "commands": [VET]}), None)
    ex = _Docker(ExecResult(0, "", ""))
    sealed, host = _attempts(
        tmp_path, ex, deps, mode="sighted", rungs=("briefed", "host"), checks=checks
    )
    assert sealed.labels.get("finish_gate", "").startswith("before=pass"), sealed.labels
    vets = [c for c, _ in ex.ran("vet")]
    assert len(vets) == 4, [c.ro_mounts for c in vets]  # each rung: its baseline, its re-run
    for cmd in vets[:2]:
        assert cmd.env.get("GOMODCACHE") == "/deps/gomod" and cmd.env.get("GOPROXY") == "off"
        assert cmd.ro_mounts == deps.builder.mounts, cmd.ro_mounts
    for cmd in vets[2:]:
        assert "GOMODCACHE" not in cmd.env and cmd.ro_mounts == (), (cmd.env, cmd.ro_mounts)
    assert host.labels.get("finish_gate", "").startswith("before=pass"), host.labels
