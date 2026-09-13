"""Shared helpers for the toolchain / sandbox integration tests.

Deliberately NOT a ``conftest.py`` (that file belongs to the core test suite):
test modules import this explicitly. It owns three things:

* **availability probes** — :func:`has_tool`, :func:`docker_available`;
* **once-per-session warm-ups** — the npm dev-dependency caches under
  ``tests/.cache/node_modules_<tool>``, the Maven local-repository warm-up, and
  the sandbox image build. Each is memoised in-process and, where it makes
  sense, on disk, and each turns "cannot warm up" into a *pytest skip with the
  reason* rather than a failure: a missing network is not a defect;
* **the shared instrument steps** the per-language modules repeat — find the
  feat candidate, open a fresh trial worktree at the parent with the commit's
  tests overlaid.

Everything here runs real toolchains; nothing here decides verdicts.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import Candidate, iter_candidates
from crb.core.runners import get_runner
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace

TESTS_DIR = Path(__file__).resolve().parent
CACHE_DIR = TESTS_DIR / ".cache"

#: Pinned majors for the npm-installed test tools (the runner invokes the binary
#: from ``node_modules/.bin`` directly; the version only needs a stable reporter).
NPM_PACKAGES: dict[str, str] = {"jest": "jest@29", "vitest": "vitest@3", "mocha": "mocha@11"}

NPM_INSTALL_TIMEOUT_S = 300
MAVEN_WARMUP_TIMEOUT_S = 600
DOCKER_BUILD_TIMEOUT_S = 900


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


_DOCKER_REASON: dict[str, str] = {}


def docker_unavailable_reason() -> str:
    """'' when a daemon answers ``docker info``; else why not (memoised per process)."""
    if "reason" in _DOCKER_REASON:
        return _DOCKER_REASON["reason"]
    docker = shutil.which("docker")
    if not docker:
        reason = "docker binary not on PATH"
    else:
        try:
            p = subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            reason = (
                ""
                if p.returncode == 0
                else f"docker daemon not reachable: {(p.stderr or p.stdout).strip()[:200]}"
            )
        except (OSError, subprocess.SubprocessError) as e:
            reason = f"docker probe failed: {e}"
    _DOCKER_REASON["reason"] = reason
    return reason


def docker_available() -> bool:
    return docker_unavailable_reason() == ""


# ---------------------------------------------------------------------------
# Fixture modules (tests/ may or may not be a package — the conftest owner decides)
# ---------------------------------------------------------------------------


def fixture_module(name: str) -> ModuleType:
    """Import ``tests/fixtures/langs/<name>.py`` as a package submodule."""
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))
    return importlib.import_module(f"fixtures.langs.{name}")


# ---------------------------------------------------------------------------
# Once-per-session warm-ups
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    keep_out = CACHE_DIR / ".gitignore"
    if not keep_out.exists():
        keep_out.write_text("*\n", encoding="utf-8")
    return CACHE_DIR


_NPM: dict[str, Path | str] = {}


def npm_cache(tool: str) -> Path:
    """``node_modules`` holding ``tool``'s dev dependency, installed once and reused.

    On disk: ``tests/.cache/node_modules_<tool>/node_modules`` (survives sessions).
    Skips the calling test — with npm's own reason — when the install fails.
    """
    if tool not in NPM_PACKAGES:
        raise ValueError(f"no npm package pinned for {tool!r}")
    hit = _NPM.get(tool)
    if isinstance(hit, str):
        pytest.skip(hit)
    if isinstance(hit, Path):
        return hit
    prefix = _cache_dir() / f"node_modules_{tool}"
    nm = prefix / "node_modules"
    if not (nm / ".bin" / tool).exists():
        if not has_tool("npm"):
            _NPM[tool] = reason = "npm not on PATH"
            pytest.skip(reason)
        prefix.mkdir(parents=True, exist_ok=True)
        try:
            p = subprocess.run(
                [
                    "npm",
                    "install",
                    "--prefix",
                    str(prefix),
                    "--no-audit",
                    "--no-fund",
                    "--no-package-lock",
                    "--loglevel=error",
                    NPM_PACKAGES[tool],
                ],
                capture_output=True,
                text=True,
                timeout=NPM_INSTALL_TIMEOUT_S,
                check=False,
            )
            err = "" if p.returncode == 0 else (p.stderr or p.stdout).strip()[-400:]
        except subprocess.TimeoutExpired:
            err = f"timed out after {NPM_INSTALL_TIMEOUT_S}s"
        if err or not (nm / ".bin" / tool).exists():
            _NPM[tool] = reason = (
                f"npm install {NPM_PACKAGES[tool]} failed (no network?): {err or 'binary missing'}"
            )
            pytest.skip(reason)
    _NPM[tool] = nm
    return nm


_MAVEN: dict[str, str] = {}


def maven_warmup(scratch: Path) -> None:
    """Resolve the JVM fixture's plugins + junit into ``~/.m2`` once per session.

    Runs the real :class:`MavenRunner` online (``offline=False`` → ``-U``) on a
    throwaway build of the fixture. Skips the calling test with Maven's tail when
    the resolution fails (typically: no network and a cold local repository).
    """
    if "reason" in _MAVEN:
        if _MAVEN["reason"]:
            pytest.skip(_MAVEN["reason"])
        return
    jvmrepo = fixture_module("jvmrepo")
    root, _ = jvmrepo.build(Path(scratch) / "mvn-warmup")
    cfg = jvmrepo.config(offline=False)
    run = get_runner(cfg).run(LocalExecutor(), root, (), timeout=MAVEN_WARMUP_TIMEOUT_S)
    if run.green:
        _MAVEN["reason"] = ""
        return
    _MAVEN["reason"] = reason = "maven warm-up failed (offline / cold ~/.m2?): " + (
        "timed out" if run.timed_out else run.tail[-400:]
    )
    pytest.skip(reason)


_IMAGES: dict[str, str] = {}


def ensure_docker_image(tag: str, dockerfile: str) -> None:
    """Build ``tag`` from an inline Dockerfile once per session (reused if present)."""
    if tag in _IMAGES:
        if _IMAGES[tag]:
            pytest.skip(_IMAGES[tag])
        return
    reason = docker_unavailable_reason()
    if reason:
        _IMAGES[tag] = reason
        pytest.skip(reason)
    docker = shutil.which("docker") or "docker"
    have = subprocess.run(
        [docker, "image", "inspect", tag], capture_output=True, text=True, timeout=60, check=False
    )
    if have.returncode != 0:
        try:
            p = subprocess.run(
                [docker, "build", "-t", tag, "-"],
                input=dockerfile,
                capture_output=True,
                text=True,
                timeout=DOCKER_BUILD_TIMEOUT_S,
                check=False,
            )
            err = "" if p.returncode == 0 else (p.stderr or p.stdout).strip()[-400:]
        except subprocess.TimeoutExpired:
            err = f"timed out after {DOCKER_BUILD_TIMEOUT_S}s"
        if err:
            _IMAGES[tag] = reason = f"docker build {tag} failed (no network?): {err}"
            pytest.skip(reason)
    _IMAGES[tag] = ""


# ---------------------------------------------------------------------------
# Shared instrument steps
# ---------------------------------------------------------------------------


def feat_candidate(repo: GitRepo, config: RepoConfig, feat_sha: str) -> Candidate:
    """The mined :class:`Candidate` for the fixture's feat commit (fails if unmined)."""
    for cand in iter_candidates(repo, config, log_n=50):
        if cand.sha == feat_sha:
            return cand
    raise AssertionError(f"iter_candidates did not yield the feat commit {feat_sha[:10]}")


def trial_worktree(
    repo: GitRepo,
    cand: Candidate,
    dest: Path,
    config: RepoConfig,
    *,
    sources: Sequence[str] = (),
) -> Workspace:
    """A fresh worktree at the parent with the commit's tests overlaid — the state
    every builder starts from. ``sources`` additionally overlays the gold files."""
    ws = Workspace.create(repo, cand.sha, Path(dest), config=config)
    ws.overlay_tests(cand.test_files)
    if sources:
        ws.overlay_sources(list(sources))
    return ws
