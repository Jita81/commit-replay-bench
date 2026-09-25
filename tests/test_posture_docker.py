"""The sealed posture, proven against a real daemon on a Go repository WITH a dependency.

ADR-0019 closes the 2026-09-25 finding: in the shipped Go sandbox (``--network=none``, a
read-only tree, an empty module cache) every target of a repository with a third-party
module failed to BUILD, and the replay charged each failure to the model. This module
runs the real thing — the shipped image, the real ``go`` runner, a real two-commit Go
repository whose package imports a module that is not in the standard library — with no
mocks on the sealed path:

* **as shipped** (no module cache, no provisioning), the task is refused at qualification
  ``QUAL_ENV_UNLOADABLE`` — the environment probe (``go list -deps -test ./...`` offline)
  cannot load the module graph — so no replay could ever be built for it; a task that WAS
  qualified in that posture and then lost its dependencies is graded, and its failure is
  ``harness`` with ``error: environment: …`` because the gold, run NOW in the same
  container image, fails the same way: never ``builder_red``; and the host's
  qualification is refused outright (``PostureMismatch``) — the exact shape of run
  ``0c44ff24…``;
* **with the dependency present in the image** (a derived image ``FROM`` the shipped one,
  its module cache filled OFFLINE from a ``file://`` proxy — the escape hatch ADR-0019
  keeps; per-task provisioning is stream D), the task qualifies, a do-nothing trial is
  ``builder_red`` with the ``gold_green`` witness that ran in the sandbox, the gold is
  clean, and a test that writes into its package (the finding's D5) sits in the baseline
  measured IN the sandbox — which the host's baseline does not carry — so it is never
  charged as a "new failure".

Worktrees live under ``tests/.cache`` (the VM behind colima / Docker Desktop cannot
bind-mount pytest's ``tmp_path``). The module proxy and the module cache are built on the
host with the host's ``go`` from files this module writes — nothing reaches a network.

Navigation
----------
What it is:   The docker-marked proof of ADR-0019's sealed posture on a real Go repository with
              a third-party module.
What it does: Builds the repository, a ``file://`` module proxy and a host module cache; runs
              ``qualify_task`` and ``grade`` through ``DockerExecutor`` on the shipped Go image
              and on a derived image with the cache baked in; asserts the refusals, the
              environment rows, the witnessed blame and the in-posture baseline.
How:          Real ``docker`` (colima locally, CI's docker jobs), real ``go`` in the image, the
              real ``GoRunner``; the only host tool is ``go`` to write ``go.sum`` and fill the
              cache from the local proxy.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/qualify.py (``qualify_task``, ``GoldWitness``),
              src/crb/core/grade.py (the witness and the environment error),
              src/crb/core/posture.py (``resolve_posture`` on the live image),
              src/crb/core/runners/go_runner.py (the offline environment probe),
              deploy/sandbox/Dockerfile.go (the shipped image), tests/conftest_langs.py (the
              image and the cache directory)
Tested by:    tests/test_posture_docker.py
Touch when:   the sealed posture's contract changes (provisioning lands: stream D adds the
              per-task module cache — the "as shipped" half then reads provisioning off).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from crb.core import ledger as lg
from crb.core.deps import DEPS_MODE_HOST_ENV, DEPS_MODE_SEALED, HOST_ENV_DEPS, NO_DEPS, TaskDeps
from crb.core.execution import DockerExecutor, DockerSettings, Executor, LocalExecutor
from crb.core.git import GitRepo
from crb.core.grade import (
    BLAME_GOLD_GREEN,
    ENV_CODE_GOLD_CONTROL_RED,
    GradeContext,
    GradeResult,
    grade,
)
from crb.core.posture import Posture, PostureMismatch, resolve_posture
from crb.core.qualify import (
    QUAL_ENV_UNLOADABLE,
    GoldWitness,
    Qualification,
    context_for,
    delta_against,
    qualify_task,
)
from crb.core.runners import get_runner
from crb.core.runners.base import BaseRunner
from crb.core.spec import BELT_BARE, Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures.langs import commit_all, init_repo, write_files

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

pytestmark = [pytest.mark.docker, pytest.mark.slow]

MODULE = "example.com/depcalc"
DEP = "example.com/extlib"
DEP_VERSION = "v1.0.0"
CALC_PKG = f"{MODULE}/calc"
UTIL_PKG = f"{MODULE}/util"
#: A test that writes into its own package directory: green on the host, red on a
#: read-only tree — the finding's D5.
WRITES_ID = f"{UTIL_PKG}::TestWritesIntoItsPackage"

_INITIAL = {
    "go.mod": f"module {MODULE}\n\ngo 1.22\n\nrequire {DEP} {DEP_VERSION}\n",
    "calc/calc.go": (
        f'package calc\n\nimport "{DEP}"\n\n'
        "// Add returns a + b (through the dependency, so the package cannot build without it).\n"
        "func Add(a, b int) int { return extlib.Double(a)/2 + b }\n"
    ),
    "calc/calc_test.go": (
        'package calc\n\nimport "testing"\n\n'
        "func TestAdd(t *testing.T) {\n"
        '\tif got := Add(1, 2); got != 3 {\n\t\tt.Fatalf("Add(1, 2) = %d, want 3", got)\n\t}\n}\n'
    ),
    "util/util.go": 'package util\n\n// Name is the package\'s name.\nconst Name = "util"\n',
    "util/util_test.go": (
        'package util\n\nimport (\n\t"os"\n\t"testing"\n)\n\n'
        "func TestWritesIntoItsPackage(t *testing.T) {\n"
        '\tif err := os.WriteFile("scratch.txt", []byte("x"), 0o644); err != nil {\n'
        '\t\tt.Fatalf("cannot write into the package: %v", err)\n\t}\n'
        '\t_ = os.Remove("scratch.txt")\n}\n'
    ),
}
_FEAT = {
    "calc/sub.go": "package calc\n\n// Sub returns a - b.\nfunc Sub(a, b int) int { return a - b }\n",
    "calc/sub_test.go": (
        'package calc\n\nimport "testing"\n\n'
        "func TestSub(t *testing.T) {\n"
        '\tif got := Sub(3, 2); got != 1 {\n\t\tt.Fatalf("Sub(3, 2) = %d, want 1", got)\n\t}\n}\n'
    ),
}
_DEP_SRC = "package extlib\n\n// Double returns 2 * a.\nfunc Double(a int) int { return 2 * a }\n"


def _file_proxy(root: Path) -> Path:
    """A GOPROXY directory serving ``example.com/extlib@v1.0.0`` — written here, offline."""
    at = root / DEP / "@v"
    at.mkdir(parents=True, exist_ok=True)
    (at / "list").write_text(f"{DEP_VERSION}\n")
    (at / f"{DEP_VERSION}.info").write_text(
        json.dumps({"Version": DEP_VERSION, "Time": "2026-01-01T00:00:00Z"})
    )
    mod = f"module {DEP}\n\ngo 1.22\n"
    (at / f"{DEP_VERSION}.mod").write_text(mod)
    with zipfile.ZipFile(at / f"{DEP_VERSION}.zip", "w") as z:
        z.writestr(f"{DEP}@{DEP_VERSION}/go.mod", mod)
        z.writestr(f"{DEP}@{DEP_VERSION}/extlib.go", _DEP_SRC)
    return root


def _go_env(proxy: Path, gomod: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "GOCACHE")}
    env.update(
        {
            "GOPROXY": f"file://{proxy}",
            "GOSUMDB": "off",
            "GOFLAGS": "-mod=mod",
            "GOMODCACHE": str(gomod),
            "GOTOOLCHAIN": "local",
            "GOVCS": "*:off",
        }
    )
    return env


def _rmtree(path: Path) -> None:
    """Remove a tree that holds Go's read-only module cache (its directories are 0555)."""
    for dirpath, _dirs, _files in os.walk(path):
        os.chmod(dirpath, stat.S_IRWXU)
    shutil.rmtree(path, ignore_errors=True)


@dataclass(frozen=True)
class Rig:
    """Everything the proofs share: the repository, its task, the host cache, the images."""

    repo: GitRepo
    task: TaskSpec
    config: RepoConfig
    baked_config: RepoConfig
    shipped: str
    baked: str
    host_env: dict[str, str]
    scratch: Path


def _config(**opts: object) -> RepoConfig:
    return RepoConfig(
        name="depcalc",
        language=Language.GO,
        runner="go",
        belt_scope=BELT_BARE,
        runner_opts=dict(opts),
    )


@pytest.fixture(scope="module")
def rig() -> Iterator[Rig]:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    if shutil.which("go") is None:
        pytest.skip("the host needs go to write go.sum and fill the module cache offline")
    shipped = langs.ensure_shipped_sandbox_image("go")
    root = langs.CACHE_DIR / "sandbox" / f"posture-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        proxy = _file_proxy(root / "proxy")
        gomod = root / "ctx" / "gomod"
        env = _go_env(proxy, gomod)
        repo_dir = root / "repo"

        init_repo(repo_dir)
        write_files(repo_dir, _INITIAL)
        subprocess.run(
            ["go", "mod", "tidy"], cwd=repo_dir, env=env, check=True, capture_output=True
        )
        assert (repo_dir / "go.sum").read_text().count(DEP) == 2
        commit_all(repo_dir, "chore: initial calc with a dependency")
        write_files(repo_dir, _FEAT)
        feat = commit_all(repo_dir, "feat: add sub")
        # the derived image: the shipped one + the dependency's module cache, no network
        baked = "crb-posture-go-baked:test"
        (root / "ctx" / "Dockerfile").write_text(f"FROM {shipped}\nCOPY gomod /opt/gomod\n")
        subprocess.run(
            ["docker", "build", "-q", "-t", baked, str(root / "ctx")],
            check=True,
            capture_output=True,
            timeout=600,
        )
        config = _config()
        repo = GitRepo(repo_dir)
        task = TaskSpec(
            task_id=feat,
            repo=config.name,
            subject="feat: add sub",
            authored=repo.author_date(feat),
            test_files=("calc/sub_test.go",),
            src_files=("calc/sub.go",),
            target_tests=("./calc",),
            belt_scope=(),
            language="go",
        )
        host_env = {
            **LocalExecutor._host_base_env(),
            "GOMODCACHE": str(gomod),
            "GOPROXY": "off",
            "GOSUMDB": "off",
        }
        yield Rig(
            repo,
            task,
            config,
            _config(gomodcache="/opt/gomod"),
            shipped,
            baked,
            host_env,
            root / "scratch",
        )
    finally:
        _rmtree(root)


def _docker(image: str) -> DockerExecutor:
    return DockerExecutor(DockerSettings(image=image))


def _qualify(
    rig: Rig, executor: Executor, config: RepoConfig, mode: str
) -> tuple[Posture, Qualification]:
    runner = get_runner(config)
    posture = resolve_posture(executor, runner, deps_mode=mode, root=rig.repo.path)
    deps = TaskDeps.uniform(NO_DEPS if executor.name == "docker" else HOST_ENV_DEPS)
    q = qualify_task(
        rig.repo,
        config,
        rig.task,
        posture=posture,
        deps=deps,
        runner=runner,
        executor=executor,
        scratch=rig.scratch,
        timeout=600,
    )
    return posture, q


def _trial(rig: Rig, name: str, *, gold: bool) -> Workspace:
    ws = Workspace.create(
        rig.repo, rig.task.task_id, rig.scratch / f"trial-{name}", config=rig.config
    )
    ws.overlay_tests(rig.task.test_files)
    if gold:
        ws.overlay_sources(rig.task.src_files)
    return ws


def _grade(
    rig: Rig,
    ws: Workspace,
    ctx: GradeContext,
    executor: Executor,
    runner: BaseRunner,
    config: RepoConfig,
) -> GradeResult:
    return grade(
        ws,
        ctx.spec(rig.task),
        ctx=ctx,
        config=config,
        runner=runner,
        executor=executor,
        timeout=600,
    )


def _witness(
    rig: Rig, runner: BaseRunner, executor: Executor, binding: object = NO_DEPS
) -> GoldWitness:
    return GoldWitness(
        rig.repo,
        rig.config,
        rig.task,
        runner=runner,
        executor=executor,
        scratch=rig.scratch,
        binding=binding,
        timeout=600,  # type: ignore[arg-type]
    )


def test_the_sealed_posture_as_shipped_refuses_the_task_and_never_blames_the_model(
    rig: Rig,
) -> None:
    sealed = _docker(rig.shipped)
    runner = get_runner(rig.config)
    posture, q = _qualify(rig, sealed, rig.config, DEPS_MODE_SEALED)
    assert posture.posture_class == "docker/readonly/sealed" and posture.image_id.startswith(
        "sha256:"
    )
    assert posture.toolchain.startswith("go version go1.")
    # D1: the module graph cannot load offline — the task is refused, never RED
    assert q.state == "unqualified" and q.code == QUAL_ENV_UNLOADABLE, q.message
    assert q.env_probe["ran"] and q.env_probe["ok"] is False and q.red == {}

    # run 0c44ff24's shape: a task qualified on the HOST, graded in the sandbox — refused
    host = LocalExecutor(base_env=rig.host_env)
    _, host_q = _qualify(rig, host, rig.config, DEPS_MODE_HOST_ENV)
    assert host_q.is_qualified, host_q.message
    host_posture = Posture.from_dict(host_q.posture)
    host_ctx = context_for(
        rig.task,
        posture=host_posture,
        qualification=host_q,
        deps=TaskDeps.uniform(HOST_ENV_DEPS),
        witness=None,
    )
    ws = _trial(rig, "host-ctx", gold=False)
    try:
        with pytest.raises(PostureMismatch, match="executor"):
            _grade(rig, ws, host_ctx, sealed, runner, rig.config)
    finally:
        ws.remove()

    # D2: a task qualified in this posture that then lost its dependencies (the cache the
    # qualification saw is gone) — the do-nothing trial fails to build, and so does the
    # gold, run NOW in the same image: an environment row, never builder_red
    moved = Qualification.from_dict(
        {
            **host_q.to_dict(),
            "qualification_id": "",
            "posture_id": posture.posture_id,
            "posture": posture.to_dict(),
            "fingerprint": "",
        }
    )
    ctx = context_for(
        rig.task,
        posture=posture,
        qualification=moved,
        deps=TaskDeps.uniform(NO_DEPS),
        witness=_witness(rig, runner, sealed),
    )
    ws = _trial(rig, "sealed-noop", gold=False)
    try:
        res = _grade(rig, ws, ctx, sealed, runner, rig.config)
    finally:
        ws.remove()
    assert res.belts.target_green is False
    assert res.error.startswith(f"environment: gold control red in {posture.posture_id}")
    assert res.env_code == ENV_CODE_GOLD_CONTROL_RED and not res.blamed
    assert res.control is not None and res.control.green is False
    row = lg.grade_row_from_result(res, ctx.spec(rig.task), pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_HARNESS  # counted against autonomy, never the model
    assert row.labels["posture_class"] == "docker/readonly/sealed"
    assert lg.LABEL_BLAME_CONTROL not in row.labels
    split = lg.failure_split([row])
    assert split.n == 1 and split.model_n == 0


def test_the_sealed_posture_grades_a_repository_with_a_dependency_offline(rig: Rig) -> None:
    baked = _docker(rig.baked)
    config = rig.baked_config
    runner = get_runner(config)
    posture, q = _qualify(rig, baked, config, DEPS_MODE_SEALED)
    assert posture.image_ref == rig.baked and posture.network == "none"
    assert q.is_qualified, f"{q.code}: {q.message}"
    assert q.env_probe["ok"] is True and q.red["kind"] == "build_failed"
    # D5: the test that writes into its package is red HERE (read-only tree), so it is in
    # the baseline measured in this posture — and not in the host's
    assert WRITES_ID in q.baseline
    host = LocalExecutor(base_env=rig.host_env)
    _, host_q = _qualify(rig, host, rig.config, DEPS_MODE_HOST_ENV)
    assert host_q.is_qualified and WRITES_ID not in host_q.baseline
    delta = delta_against(q, [host_q])
    assert delta["only_here"] == [WRITES_ID] and delta["same_fingerprint"] is False

    ctx = context_for(
        rig.task,
        posture=posture,
        qualification=q,
        deps=TaskDeps.uniform(NO_DEPS),
        witness=_witness(rig, runner, baked),
    )
    # the gold is clean in the sandbox: belt 3 subtracts the IN-posture baseline
    ws = _trial(rig, "baked-gold", gold=True)
    try:
        gold = _grade(rig, ws, ctx, baked, runner, config)
    finally:
        ws.remove()
    assert gold.clean, (gold.note, gold.error, gold.new_failures)
    # a do-nothing trial is the builder's failure — and the row names the witness that ran
    ws = _trial(rig, "baked-noop", gold=False)
    try:
        noop = _grade(rig, ws, ctx, baked, runner, config)
    finally:
        ws.remove()
    assert noop.belts.target_green is False and not noop.error
    assert noop.blame_control == BLAME_GOLD_GREEN and noop.control is not None
    assert noop.control.green and noop.control.scope == ("./calc",)
    row = lg.grade_row_from_result(noop, ctx.spec(rig.task), pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_BUILDER_RED
    assert row.labels["blame_control"] == "gold_green"
    assert row.labels["posture_id"] == posture.posture_id
