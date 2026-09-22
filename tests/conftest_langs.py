"""Shared helpers for the toolchain / sandbox integration tests.

Deliberately NOT a ``conftest.py`` (that file belongs to the core test suite):
test modules import this explicitly. It owns three things:

* **availability probes** — :func:`has_tool`, :func:`docker_available`;
* **once-per-session warm-ups** — the npm dev-dependency caches under
  ``tests/.cache/node_modules_<tool>``, the Maven local-repository warm-up, and
  the sandbox image builds (the inline python test image, and the shipped
  reference images under ``deploy/sandbox`` — either may instead be named by an
  environment variable when CI has already built it). Each is memoised
  in-process and, where it makes sense, on disk, and each turns "cannot warm up"
  into a *pytest skip with the reason* by default (a missing network is not a
  defect) — and into a FAILURE under ``CRB_TEST_STRICT_WARMUP=1`` (CI), where a
  broken pin or fixture is one;
* **the shared instrument steps** the per-language modules repeat — find the
  feat candidate, open a fresh trial worktree at the parent with the commit's
  tests overlaid.

Everything here runs real toolchains; nothing here decides verdicts.

Navigation
----------
What it is:   Shared helpers for the toolchain and sandbox integration suites (imported
              explicitly; not a conftest).
What it does: Answers "is go/node/mvn/cargo/docker available", warms the npm dev-dependency
              caches, the Maven local repository and the sandbox images once per session — the
              inline python test image (``CRB_TEST_SANDBOX_IMAGE`` names a present one instead)
              and the shipped reference images built from ``deploy/sandbox/Dockerfile.<lang>``
              (``CRB_TEST_SANDBOX_IMAGE_<LANG>`` likewise) — and performs the two instrument
              steps every language module repeats — mine the feat candidate, open a trial
              worktree at the parent with the tests overlaid. A warm-up that cannot complete is
              a skip with the reason offline and a failure in CI (``CRB_TEST_STRICT_WARMUP``); a
              missing tool or daemon is always a skip.
How:          Memoised probes → on-disk caches under ``tests/.cache`` → ``docker build`` from
              stdin or from a Dockerfile + context → ``iter_candidates`` + ``Workspace.create``
              + ``overlay_tests`` through the real runner and executor.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/langs/__init__.py (the two-commit fixture shape these steps rely
              on), src/crb/core/mine.py (``iter_candidates``), src/crb/core/workspace.py (the
              trial), src/crb/core/runners/__init__.py (``get_runner``), tests/test_runners_node.py
              and tests/test_runners_jvm.py (typical callers)
Tested by:    tests/test_conftest_langs.py (the warm-up policy, hermetically),
              tests/test_runners_go.py, tests/test_runners_node.py, tests/test_runners_jvm.py,
              tests/test_runners_cargo.py, tests/test_sandbox_docker.py,
              tests/test_sandbox_images_docker.py (every consumer)
Touch when:   adding a runner for a new language (add its availability probe and any per-session
              warm-up here, the fixture under tests/fixtures/langs/, and a ``test_runners_<lang>``
              module); a reference sandbox image is added under deploy/sandbox (extend
              ``SHIPPED_SANDBOX_LANGS`` and tests/test_sandbox_images_docker.py together); the
              per-session cache directory (``.cache`` under the tests tree) moves.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import NoReturn

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
    """True when ``name`` resolves on PATH (a toolchain gate, never a verdict)."""
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
    """True when a daemon answered ``docker info`` (memoised per process)."""
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


#: ``CRB_TEST_STRICT_WARMUP=1`` (set in CI, where the network is available) turns a failed
#: warm-up — an npm install, the Maven resolution, a docker build — into a test FAILURE
#: instead of a skip: a broken package pin, fixture or Dockerfile is a repository defect,
#: not unavailable infrastructure (CodeRabbit on PR #5, 2026-09-16). Locally, offline,
#: the skip stays so the hermetic suite still runs.
STRICT_WARMUP = os.environ.get("CRB_TEST_STRICT_WARMUP", "") not in ("", "0", "false")


def warmup_unavailable(reason: str) -> NoReturn:
    """Skip (default) or fail (strict) the calling test with the warm-up's own reason."""
    if STRICT_WARMUP:
        pytest.fail(f"[strict warm-up] {reason}", pytrace=False)
    pytest.skip(reason + " — set CRB_TEST_STRICT_WARMUP=1 to fail instead of skipping")


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
        warmup_unavailable(hit)
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
            warmup_unavailable(reason)
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
            warmup_unavailable(_MAVEN["reason"])
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
    warmup_unavailable(reason)


_IMAGES: dict[str, str] = {}

#: The python image the sandbox and sealed-builder suites run on: ``CRB_TEST_SANDBOX_IMAGE``
#: names one that is already present (CI passes the reference image it just built, so the
#: shipped bytes are what the walls are proven on); unset, the inline Dockerfile below is
#: built once per session as ``crb-test-py:local`` — the default is unchanged.
TEST_IMAGE_ENV = "CRB_TEST_SANDBOX_IMAGE"
TEST_IMAGE_DEFAULT = "crb-test-py:local"
TEST_IMAGE_DOCKERFILE = "FROM python:3.12-slim\nRUN pip install --no-cache-dir 'pytest>=8.3,<9'\n"

#: The reference sandbox images deploy/sandbox ships, by language: the Dockerfile each is
#: built from, the tag a local build gets, and the variable CI sets to the tag it built.
SANDBOX_DIR = TESTS_DIR.parent / "deploy" / "sandbox"
SHIPPED_SANDBOX_LANGS: tuple[str, ...] = ("python", "node", "go")


def shipped_sandbox_env(lang: str) -> str:
    """``CRB_TEST_SANDBOX_IMAGE_<LANG>`` — set to a present tag to test THAT image."""
    return f"CRB_TEST_SANDBOX_IMAGE_{lang.upper()}"


def shipped_sandbox_dockerfile(lang: str) -> Path:
    """``deploy/sandbox/Dockerfile.<lang>``."""
    return SANDBOX_DIR / f"Dockerfile.{lang}"


def sandbox_test_image() -> str:
    """The tag the python sandbox suites use (env override, else the session-built default)."""
    return os.environ.get(TEST_IMAGE_ENV) or TEST_IMAGE_DEFAULT


def ensure_sandbox_test_image() -> str:
    """:func:`sandbox_test_image`, ready in the daemon: an env-named image must already be
    present (never built here — the point is to test the bytes CI built); the default is
    built once per session from the inline Dockerfile. Returns the tag."""
    tag = sandbox_test_image()
    if os.environ.get(TEST_IMAGE_ENV):
        require_docker_image(tag, f"{TEST_IMAGE_ENV}={tag}")
    else:
        ensure_docker_image(tag, TEST_IMAGE_DOCKERFILE)
    return tag


def ensure_shipped_sandbox_image(lang: str) -> str:
    """The shipped reference image for ``lang``, ready in the daemon: the tag
    :func:`shipped_sandbox_env` names when set (must be present; never built here), else
    ``crb-sandbox-<lang>:local`` built once per session from its Dockerfile. Returns the tag."""
    if lang not in SHIPPED_SANDBOX_LANGS:
        raise ValueError(f"no shipped sandbox image for {lang!r}")
    var = shipped_sandbox_env(lang)
    tag = os.environ.get(var)
    if tag:
        require_docker_image(tag, f"{var}={tag}")
        return tag
    tag = f"crb-sandbox-{lang}:local"
    ensure_docker_image(tag, shipped_sandbox_dockerfile(lang), context=SANDBOX_DIR)
    return tag


def require_docker_image(tag: str, named_by: str) -> None:
    """Skip (fail under strict warm-up) unless ``tag`` is present in the daemon's store —
    ``named_by`` says which setting named it, so the reason is actionable."""
    if tag in _IMAGES:
        if _IMAGES[tag]:
            warmup_unavailable(_IMAGES[tag])
        return
    reason = docker_unavailable_reason()
    if reason:
        _IMAGES[tag] = reason
        pytest.skip(reason)
    if not _image_present(tag):
        _IMAGES[tag] = reason = (
            f"docker image {tag!r} ({named_by}) is not present; build or load it"
        )
        warmup_unavailable(reason)
    _IMAGES[tag] = ""


def _image_present(tag: str) -> bool:
    """``docker image inspect`` says ``tag`` is in the daemon's store. A daemon that stops
    answering after the initial probe (``TimeoutExpired``, a broken pipe, an ``OSError``
    from the client) goes through the warm-up policy like any other unavailable warm-up —
    recorded against the tag, a skip locally, a failure under strict warm-up — never an
    uncontrolled test error."""
    docker = shutil.which("docker") or "docker"
    try:
        have = subprocess.run(
            [docker, "image", "inspect", tag],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _IMAGES[tag] = reason = f"docker image inspection of {tag!r} failed: {exc}"
        warmup_unavailable(reason)
    return have.returncode == 0


def ensure_docker_image(tag: str, dockerfile: str | Path, *, context: Path | None = None) -> None:
    """Build ``tag`` once per session (reused if present): from an inline Dockerfile
    string (stdin, no context), or — with ``context`` — from the Dockerfile at ``dockerfile``
    with that build context, exactly as an operator builds it."""
    if tag in _IMAGES:
        if _IMAGES[tag]:
            warmup_unavailable(_IMAGES[tag])
        return
    reason = docker_unavailable_reason()
    if reason:  # no daemon is environmental — a plain skip, never a failure
        _IMAGES[tag] = reason
        pytest.skip(reason)
    docker = shutil.which("docker") or "docker"
    if not _image_present(tag):
        if context is None:
            argv = [docker, "build", "-t", tag, "-"]
            stdin: str | None = str(dockerfile)
        else:
            argv = [docker, "build", "-f", str(dockerfile), "-t", tag, str(context)]
            stdin = None
        try:
            p = subprocess.run(
                argv,
                input=stdin,
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
            warmup_unavailable(reason)
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
