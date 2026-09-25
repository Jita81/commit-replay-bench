"""The posture seam (ADR-0019, S0): dependency bindings, posture facts, the provider protocol.

Navigation
----------
What it is:   The contract tests for ``crb.core.deps`` and the four call-site contracts the
              qualification and provisioning streams both code to.
What it does: Pins that bindings round-trip through a record, that the null provider is the
              host's environment locally and nothing at all in the sandbox, that the docker
              executor refuses a bundle mount and a copied tree until provisioning lands,
              that both executors report the facts a posture hashes, that ``run_for`` binds
              and restores a dependency binding, that ``env_error`` never enters an existing
              pack, and that the Go environment probe is offline.
How:          Pure constructions, a fake ``docker`` runner for the image probe, and a recording
              executor for the runner contract; no daemon, no network, no model.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/deps.py (under test), src/crb/core/execution.py (``ro_mounts``,
              ``posture_facts``, the tree modes), src/crb/core/runners/base.py (``run_for``
              and ``TestRun.env_error``), src/crb/core/runners/go_runner.py (the offline
              probe), src/crb/provision/__init__.py (``make_deps_provider``)
Tested by:    tests/test_deps_seam.py
Touch when:   the seam's shape changes — both streams code to it, so a change here is a change
              to ADR-0019's contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from crb.core.deps import (
    DEPS_HOST_ENV,
    DEPS_MODE_HOST_ENV,
    DEPS_MODE_SEALED,
    DEPS_NONE,
    HOST_ENV_DEPS,
    NO_DEPS,
    PROVISION_DISABLED,
    PROVISION_NO_LOCK,
    REFUSAL_TEXT,
    RUN_SCOPE_CODES,
    SCHEME_GO,
    BundleMount,
    ClosureViolation,
    DepsBinding,
    NullDepsProvider,
    ProvisionRefused,
    TaskDeps,
    refusal,
)
from crb.core.execution import (
    Command,
    DockerExecutor,
    DockerSettings,
    ExecResult,
    LocalExecutor,
    SandboxUnavailable,
)
from crb.core.runners.base import BaseRunner
from crb.core.runners.base import TestRun as Run
from crb.core.runners.go_runner import GoRunner
from crb.core.spec import Language, RepoConfig
from crb.provision import make_deps_provider


def _go_binding() -> DepsBinding:
    return DepsBinding(
        SCHEME_GO,
        key="k" * 16,
        digest="sha256:" + "d" * 64,
        mounts=(BundleMount(Path("/store/gomod-abc"), "/deps/gomod"),),
        env={"GOMODCACHE": "/deps/gomod", "GOPROXY": "off", "GOSUMDB": "off"},
        local_env={"GOMODCACHE": "/store/gomod-abc", "GOPROXY": "off"},
    )


def test_bindings_round_trip_through_a_qualification_dict() -> None:
    b = _go_binding()
    deps = TaskDeps(SCHEME_GO, parent=b, gold=b, builder=b)
    d = deps.to_dict()
    back = TaskDeps.from_dict(d)
    assert back == deps  # the selector is not data and does not take part
    assert back.to_dict() == d
    assert back.for_tree(Path("/anywhere")) == b  # no selector → the gold's binding
    assert DepsBinding.from_dict(NO_DEPS.to_dict()) == NO_DEPS
    with pytest.raises(ValueError, match="absolute"):
        BundleMount(Path("/x"), "relative/path")


def test_a_selector_can_refuse_the_closure() -> None:
    def outside(root: Path) -> DepsBinding:
        raise ClosureViolation(f"{root.name}: go.sum selects example.com/extra v1.2.3")

    deps = TaskDeps(SCHEME_GO, _go_binding(), _go_binding(), _go_binding(), selector=outside)
    with pytest.raises(ClosureViolation, match=r"example\.com/extra"):
        deps.for_tree(Path("/trial"))


def test_null_provider_is_host_env_locally_and_sealed_empty_under_docker(
    tmp_path: Path,
) -> None:
    config = RepoConfig(name="g", language=Language.GO)
    p = make_deps_provider(type("S", (), {"enabled": False})(), home=tmp_path)
    assert isinstance(p, NullDepsProvider)
    assert p.mode(config, "local") == DEPS_MODE_HOST_ENV
    assert p.mode(config, "docker") == DEPS_MODE_SEALED
    local = p.resolve(None, config, parent="a" * 40, gold="b" * 40, executor_name="local")  # type: ignore[arg-type]
    sealed = p.resolve(None, config, parent="a" * 40, gold="b" * 40, executor_name="docker")  # type: ignore[arg-type]
    assert local == TaskDeps.uniform(HOST_ENV_DEPS) and local.scheme == DEPS_HOST_ENV
    assert sealed == TaskDeps.uniform(NO_DEPS) and sealed.scheme == DEPS_NONE
    assert sealed.gold.mounts == () and sealed.gold.env == {}
    p.verify(sealed)  # nothing sealed, nothing to re-check


def test_refusals_carry_their_fix_their_guide_and_their_scope() -> None:
    r = refusal(PROVISION_DISABLED, "provisioning is off")
    assert r.scope == "run" and "CRB_PROVISION__ENABLED" in r.fix and r.doc.startswith("docs/")
    t = refusal(PROVISION_NO_LOCK, "no go.sum at 746ef07")
    assert t.scope == "task" and t.fix
    assert set(RUN_SCOPE_CODES) <= set(REFUSAL_TEXT)
    exc = ProvisionRefused(t)
    assert exc.refusal is t and "PROVISION_NO_LOCK" in str(exc)
    assert t.to_dict()["code"] == PROVISION_NO_LOCK


class _Inspect:
    """A fake ``subprocess.run`` for the docker probes: ``info`` and ``image inspect``."""

    def __init__(self, image_id: str = "sha256:" + "e" * 64, rc: int = 0) -> None:
        self.image_id, self.rc = image_id, rc
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                argv, self.rc, self.image_id if not self.rc else "", "no such image"
            )
        return subprocess.CompletedProcess(argv, 0, "27.0", "")


def _docker(**kw: Any) -> tuple[DockerExecutor, _Inspect]:
    fake = _Inspect(**kw)
    return DockerExecutor(
        DockerSettings(image="crb-sandbox-go:t", docker_binary="/fake/docker"), runner=fake
    ), fake


def test_docker_refuses_bundle_mounts_until_provisioning_lands(tmp_path: Path) -> None:
    d, _ = _docker()
    cmd = Command(("go", "test"), tmp_path, ro_mounts=(BundleMount(tmp_path, "/deps/gomod"),))
    with pytest.raises(SandboxUnavailable, match="stream D"):
        d.build_argv(cmd)
    with pytest.raises(ValueError, match="bind-mount"):
        LocalExecutor().run(cmd)


def test_copy_tree_refused_until_provisioning_lands() -> None:
    with pytest.raises(SandboxUnavailable, match="stream D"):
        DockerSettings(image="i", tree="copy")
    with pytest.raises(SandboxUnavailable, match="tree"):
        DockerSettings(image="i", tree="scratch")
    assert DockerSettings(image="i").tree == "readonly"
    assert DockerSettings(image="i").work_size == "2g"


def test_posture_facts_carry_the_keys_the_posture_hashes() -> None:
    assert LocalExecutor().posture_facts() == {
        "executor": "local",
        "tree": "inplace",
        "network": "host",
    }
    d, fake = _docker()
    facts = d.posture_facts()
    assert facts == {
        "executor": "docker",
        "image_ref": "crb-sandbox-go:t",
        "image_id": "sha256:" + "e" * 64,
        "tree": "readonly",
        "network": "none",
        "user": "65534:65534",
        "limits": "mem=2g,cpus=2,pids=512,tmp=512m,work=2g",
    }
    d.posture_facts()
    inspects = [c for c in fake.calls if c[1:3] == ["image", "inspect"]]
    assert len(inspects) == 1  # cached: one inspect per executor
    absent, _ = _docker(rc=1)
    with pytest.raises(SandboxUnavailable, match="not present"):
        absent.posture_facts()


class _Recorder:
    """An executor that records the commands it was given and answers green."""

    name = "local"

    def __init__(self, env_error: str = "") -> None:
        self.cmds: list[Command] = []
        self.env_error = env_error

    def run(self, cmd: Command) -> ExecResult:
        self.cmds.append(cmd)
        if self.env_error:
            return ExecResult(125, "", "copy failed", env_error=self.env_error)
        return ExecResult(0, "", "")

    def tool(self, name: str, host_override: str | None = None) -> str:
        return name

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    def posture_facts(self) -> dict[str, str]:
        return {"executor": self.name, "tree": "inplace", "network": "host"}


class _EchoRunner(BaseRunner):
    name = "echo"

    def command(self, root: Path, scope: Any, *, executor: Any, timeout: int) -> Command:
        return Command(("true",), root, env={"KEEP": "1", "GOPROXY": "direct"}, timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> Run:
        return Run(result.returncode, frozenset(), "", duration_s=result.duration_s)


def test_run_for_binds_and_restores_deps(tmp_path: Path) -> None:
    runner = _EchoRunner(RepoConfig(name="e", language=Language.PYTHON))
    ex = _Recorder()
    b = _go_binding()
    runner.run_for(ex, tmp_path, (), timeout=5, authored=None, deps=b)  # type: ignore[arg-type]
    assert runner.deps is None and runner.authored is None  # restored
    first = ex.cmds[-1]
    # local executor: the binding's local_env, over the runner's own values
    assert first.env["GOMODCACHE"] == "/store/gomod-abc" and first.env["GOPROXY"] == "off"
    assert first.env["KEEP"] == "1"
    assert first.ro_mounts == b.mounts
    runner.run_for(ex, tmp_path, (), timeout=5, authored=None)  # type: ignore[arg-type]
    assert ex.cmds[-1].env == {"KEEP": "1", "GOPROXY": "direct"} and ex.cmds[-1].ro_mounts == ()


def test_env_error_is_not_in_existing_packs(tmp_path: Path) -> None:
    plain = Run(1, frozenset({"t::a"}), "tail")
    assert "env_error" not in plain.to_dict()
    runner = _EchoRunner(RepoConfig(name="e", language=Language.PYTHON))
    run = runner.run(_Recorder(env_error="tree_copy_failed: no space"), tmp_path, (), timeout=5)  # type: ignore[arg-type]
    assert run.env_error == "tree_copy_failed: no space"
    assert run.red and run.to_dict()["env_error"] == "tree_copy_failed: no space"


def test_go_env_probe_is_offline(tmp_path: Path) -> None:
    go = GoRunner(RepoConfig(name="g", language=Language.GO))
    cmd = go.env_probe_command(tmp_path, (), executor=LocalExecutor(), timeout=60)
    assert cmd is not None
    assert cmd.argv[1:] == ("list", "-deps", "-test", "./...")
    assert cmd.env["GOPROXY"] == "off" and cmd.env["GOTOOLCHAIN"] == "local"
    assert cmd.env["GOFLAGS"] == "-mod=mod" and not cmd.network
    d, _ = _docker()
    sealed = go.env_probe_command(tmp_path, (), executor=d, timeout=60)
    assert sealed is not None and sealed.env["GOMODCACHE"] == "/tmp/gomod"
    assert go.toolchain_argv(LocalExecutor())[1:] == ("version",)
    assert (
        BaseRunner(RepoConfig(name="e", language=Language.PYTHON)).toolchain_argv(LocalExecutor())
        == ()
    )
