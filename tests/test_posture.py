"""crb.core.posture — a posture is an identity: stamped, hashed, and pooled by its class.

Navigation
----------
What it is:   The tests for ``Posture``, ``posture_id``, ``posture_class`` and
              ``resolve_posture`` (ADR-0019 §1).
What it does: Pins that the id follows the image's content id and never its tag, that it
              moves with the toolchain, the tree, the limits, the dependency mode and the
              apparatus, that a local posture keys the EXACT toolchain version, and that the
              class — what statistics pool on — survives a monthly image re-pin.
How:          A scripted executor (posture facts + a toolchain answer) and a small runner
              whose command environment names the worktree; no daemon, no network.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/posture.py (under test), src/crb/core/execution.py (the posture
              facts each executor reports), src/crb/core/runners/base.py (``toolchain_argv``
              and the command whose environment is hashed), src/crb/core/version.py (the
              apparatus version a posture carries)
Tested by:    tests/test_posture.py
Touch when:   a fact joins the posture (a field, a line here proving the id moves with it).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from crb.core.execution import Command, ExecResult, SandboxUnavailable
from crb.core.posture import Posture, PostureMismatch, resolve_posture
from crb.core.runners.base import BaseRunner
from crb.core.runners.base import TestRun as Run
from crb.core.spec import Language, RepoConfig


class _Exec:
    def __init__(
        self, facts: dict[str, str], version: str = "go version go1.26.8 linux/arm64", rc: int = 0
    ) -> None:
        self.name = facts["executor"]
        self.facts = facts
        self.version = version
        self.rc = rc
        self.cmds: list[Command] = []

    def run(self, cmd: Command) -> ExecResult:
        self.cmds.append(cmd)
        return ExecResult(self.rc, self.version + "\n", "")

    def tool(self, name: str, host_override: str | None = None) -> str:
        return name

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    def posture_facts(self) -> dict[str, str]:
        return dict(self.facts)


class _GoLike(BaseRunner):
    name = "go"

    def toolchain_argv(self, executor: Any) -> tuple[str, ...]:
        return ("go", "version")

    def command(self, root: Path, scope: Any, *, executor: Any, timeout: int) -> Command:
        # the worktree's own path in the environment must not make two worktrees two postures
        return Command(
            ("go", "test"), root, env={"GOFLAGS": "-count=1", "WT": str(root)}, timeout=timeout
        )

    def parse(self, result: ExecResult, root: Path) -> Run:
        return Run(result.returncode, frozenset())


DOCKER = {
    "executor": "docker",
    "image_ref": "crb-sandbox-go:main-8ab88ad",
    "image_id": "sha256:" + "0e79" * 16,
    "tree": "readonly",
    "network": "none",
    "user": "65534:65534",
    "limits": "mem=2g,cpus=2,pids=512,tmp=512m,work=2g",
}
LOCAL = {"executor": "local", "tree": "inplace", "network": "host"}


def _resolve(facts: dict[str, str], tmp: Path, **kw: Any) -> Posture:
    runner = _GoLike(RepoConfig(name="g", language=Language.GO))
    ex = _Exec(facts, **{k: v for k, v in kw.items() if k in ("version", "rc")})
    return resolve_posture(
        ex, runner, deps_mode=kw.get("deps_mode", "sealed"), root=tmp, timeout=30
    )


def test_posture_id_ignores_the_tag_and_follows_the_image_id(tmp_path: Path) -> None:
    a = _resolve(DOCKER, tmp_path)
    retagged = _resolve({**DOCKER, "image_ref": "registry.example/crb-go:2026-10"}, tmp_path)
    assert a.posture_id == retagged.posture_id  # a new name for the same bytes
    assert a.posture_id.startswith("pst_") and len(a.posture_id) == 4 + 24
    rebuilt = _resolve({**DOCKER, "image_id": "sha256:" + "ffff" * 16}, tmp_path)
    assert rebuilt.posture_id != a.posture_id  # different bytes under the same tag
    assert a.image_ref == "crb-sandbox-go:main-8ab88ad"
    back = Posture.from_dict(a.to_dict())
    assert back == a and back.posture_id == a.posture_id
    assert a.to_dict()["posture_id"] == a.posture_id  # readers see it; loaders ignore it


def test_posture_id_moves_with_toolchain_tree_limits_deps_mode_and_apparatus(
    tmp_path: Path,
) -> None:
    base = _resolve(DOCKER, tmp_path)
    moved = {
        "toolchain": _resolve(DOCKER, tmp_path, version="go version go1.26.9 linux/arm64"),
        "tree": dataclasses.replace(base, tree="copy"),
        "limits": _resolve(
            {**DOCKER, "limits": "mem=4g,cpus=2,pids=512,tmp=512m,work=2g"}, tmp_path
        ),
        "deps_mode": _resolve(DOCKER, tmp_path, deps_mode="host-env"),
        "apparatus": dataclasses.replace(base, apparatus_version="9.9"),
        "runner_env": dataclasses.replace(base, runner_env="0" * 64),
    }
    for why, other in moved.items():
        assert other.posture_id != base.posture_id, why
    # the worktree path in the runner's environment is not part of the posture
    elsewhere = tmp_path / "other-worktree"
    elsewhere.mkdir()
    assert _resolve(DOCKER, elsewhere).posture_id == base.posture_id


def test_local_posture_keys_the_exact_toolchain_version(tmp_path: Path) -> None:
    host = _resolve(
        LOCAL, tmp_path, version="go version go1.26.4 darwin/arm64", deps_mode="host-env"
    )
    assert host.toolchain == "go version go1.26.4 darwin/arm64"  # exact, never major.minor
    patch = _resolve(
        LOCAL, tmp_path, version="go version go1.26.5 darwin/arm64", deps_mode="host-env"
    )
    assert patch.posture_id != host.posture_id
    assert host.posture_class == "local/inplace/host-env"
    with pytest.raises(SandboxUnavailable, match="toolchain"):
        _resolve(LOCAL, tmp_path, rc=127)


def test_posture_class_survives_an_image_repin(tmp_path: Path) -> None:
    a = _resolve(DOCKER, tmp_path)
    repinned = _resolve(
        {**DOCKER, "image_ref": "crb-sandbox-go:2026-10", "image_id": "sha256:" + "abcd" * 16},
        tmp_path,
        version="go version go1.26.9 linux/arm64",
    )
    assert repinned.posture_id != a.posture_id
    assert repinned.posture_class == a.posture_class == "docker/readonly/sealed"


def test_posture_mismatch_is_a_run_stopping_sandbox_error() -> None:
    assert issubclass(PostureMismatch, SandboxUnavailable)


def test_the_toolchain_probe_reads_no_tree(tmp_path: Path) -> None:
    """A version probe reads nothing of the tree it is resolved in (``mine`` resolves the
    posture in the clone, ``.git`` and all): its command says so (``tree=False``), so a
    sandbox neither copies nor walks it — never a ``tree_copy_failed`` reported as "cannot
    read the toolchain version" (CodeRabbit on PR #56)."""
    ex = _Exec(DOCKER)
    resolve_posture(
        ex, _GoLike(RepoConfig(name="g", language=Language.GO)), deps_mode="sealed", root=tmp_path
    )
    assert [c.argv for c in ex.cmds] == [("go", "version")]
    assert ex.cmds[0].tree is False


def test_the_expected_class_is_the_workers_choice_of_executor_tree_and_provider() -> None:
    """One rule for the API's default filter and the worker's route gate (CodeRabbit on PR
    #56): the sandbox is always sealed with the repository's tree; the host executor is
    sealed exactly when provisioning is on (``make_deps_provider`` binds a set per task)."""
    from crb.core.posture import expected_posture_class

    assert expected_posture_class("docker", tree="", provisioning=False) == "docker/copy/sealed"
    assert expected_posture_class("docker", tree="readonly", provisioning=True) == (
        "docker/readonly/sealed"
    )
    assert expected_posture_class("local", tree="copy", provisioning=False) == (
        "local/inplace/host-env"
    )
    assert expected_posture_class("", tree="", provisioning=True) == "local/inplace/sealed"
