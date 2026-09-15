"""Sandbox: the instrument inside :class:`DockerExecutor` — and the walls hold.

With a reachable daemon, builds ``crb-test-py:local`` (``python:3.12-slim`` +
pytest) once per session and, on :mod:`tests.fixtures.langs.pyrepo_min`:

* ``qualify`` + ``grade`` run and parse under ``--network=none`` (gold → clean);
* a test that opens ``https://example.com`` FAILS (the network is truly off);
* a test that writes ``/work/hacked.txt`` FAILS (the worktree is read-only);
* the worktree on the host is byte-identical after a sandboxed run.

Skipped — with the probe's reason — when no daemon answers ``docker info`` or
the image cannot be built (no network). Never falls back to running in-process:
that is :class:`~crb.core.execution.SandboxUnavailable`'s job.

Worktrees live under ``tests/.cache/sandbox`` rather than pytest's ``tmp_path``:
on macOS the VM behind docker (colima / Docker Desktop) shares ``/Users`` but
not ``/private/var/folders``, so a bind mount from there would be empty.

Navigation
----------
What it is:   The sandbox suite — the instrument inside ``DockerExecutor`` against a real daemon,
              and proof that the walls hold.
What it does: Pins that the executor is hardened, that ``qualify`` and ``grade`` run and parse
              under ``--network=none`` (gold → clean), that a test opening ``https://example.com``
              FAILS, that a test writing ``/work/hacked.txt`` FAILS (read-only worktree), and that
              the host worktree is byte-identical after a sandboxed run. Never falls back to
              in-process execution — that is ``SandboxUnavailable``'s job.
How:          ``crb-test-py:local`` built once per session from an inline Dockerfile
              (``python:3.12-slim`` + pytest); worktrees under the tests cache because the VM
              behind colima / Docker Desktop cannot bind-mount pytest's ``tmp_path``; skipped
              with the probe's reason when no daemon answers.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/execution.py (``DockerExecutor`` under test),
              tests/fixtures/langs/pyrepo_min.py (the fixture), tests/conftest_langs.py
              (``ensure_docker_image`` and the probes), tests/test_execution.py (the same
              executor without a daemon), docs/SECURITY.md (sandboxed test execution, §3.1)
Tested by:    tests/test_sandbox_docker.py
Touch when:   a hardening flag is added (a wall test that proves it holds from INSIDE the
              container, not only that the flag is on argv); the sandbox image changes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.execution import DockerExecutor, DockerSettings
from crb.core.git import GitRepo
from crb.core.grade import grade
from crb.core.mine import Candidate, qualify
from crb.core.runners import get_runner
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

pyrepo_min = langs.fixture_module("pyrepo_min")

pytestmark = [pytest.mark.docker, pytest.mark.slow]

IMAGE = "crb-test-py:local"
DOCKERFILE = "FROM python:3.12-slim\nRUN pip install --no-cache-dir 'pytest>=8.3,<9'\n"

#: Host-side artefacts a sandboxed run is allowed to leave: the runner's declared
#: writable path (bind-mounted rw) and git's own bookkeeping.
_ALLOWED_HOST_WRITES = frozenset({".pytest_scratch", ".git"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _sandbox_ready() -> None:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.ensure_docker_image(IMAGE, DOCKERFILE)


@pytest.fixture(scope="module")
def sandbox_root() -> Iterator[Path]:
    """A bind-mountable scratch root under the tests cache (the VM cannot mount ``tmp_path``);
    removed after the module.
    """
    root = langs.CACHE_DIR / "sandbox" / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def built(sandbox_root: Path) -> tuple[GitRepo, str]:
    root, feat_sha = pyrepo_min.build(sandbox_root)
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config() -> RepoConfig:
    return pyrepo_min.config()


@pytest.fixture(scope="module")
def runner(config: RepoConfig) -> BaseRunner:
    return get_runner(config)


@pytest.fixture(scope="module")
def executor() -> DockerExecutor:
    """The hardened ``DockerExecutor`` on the session-built test image."""
    return DockerExecutor(DockerSettings(image=IMAGE))


@pytest.fixture(scope="module")
def candidate(built: tuple[GitRepo, str], config: RepoConfig) -> Candidate:
    repo, feat_sha = built
    return langs.feat_candidate(repo, config, feat_sha)


@pytest.fixture(scope="module")
def task(
    built: tuple[GitRepo, str],
    config: RepoConfig,
    runner: BaseRunner,
    executor: DockerExecutor,
    candidate: Candidate,
    sandbox_root: Path,
) -> TaskSpec:
    """The feat task qualified once INSIDE the sandbox; a skip reason here is a fixture failure."""
    repo, _ = built
    outcome = qualify(
        repo, config, candidate, runner=runner, executor=executor, scratch=sandbox_root / "mine"
    )
    assert outcome.task is not None, outcome.skipped_reason
    return outcome.task


@pytest.fixture
def trial(
    built: tuple[GitRepo, str], config: RepoConfig, candidate: Candidate, sandbox_root: Path
) -> Iterator[Workspace]:
    """A fresh worktree per test under ``sandbox_root`` with the feat tests overlaid, removed afterwards."""
    repo, _ = built
    ws = langs.trial_worktree(
        repo, candidate, sandbox_root / f"trial-{uuid.uuid4().hex[:8]}", config
    )
    yield ws
    ws.remove()


def _snapshot(root: Path) -> dict[str, str]:
    """``{relative_path: sha256}`` of every regular file except the allowed writes."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        top = rel_dir.split(os.sep, 1)[0] if rel_dir != "." else ""
        if top in _ALLOWED_HOST_WRITES:
            dirnames[:] = []
            continue
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            out[os.path.relpath(p, root)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# The instrument runs under the sandbox
# ---------------------------------------------------------------------------


def test_executor_is_hardened(executor: DockerExecutor):
    d = executor.describe()
    assert d["executor"] == "docker" and d["image"] == IMAGE and d["network"] == "none"
    assert d["user"] == "65534:65534"


def test_qualify_runs_and_parses_in_sandbox(task: TaskSpec):
    assert task.red_checked is True
    assert task.gold_clean is True, task.gold_note
    assert task.target_tests == (pyrepo_min.TEST_SUB,)
    # pytest attributes the ImportError at the parent to the file (collection error)
    assert task.baseline_failing == (pyrepo_min.TEST_SUB,)


def test_gold_grades_clean_in_sandbox(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    res = grade(trial, task, config=config, runner=runner, executor=executor)
    assert res.clean is True, res.to_dict()
    assert res.belts.all_true
    assert res.changed_files == (pyrepo_min.SRC_SUB,)


# ---------------------------------------------------------------------------
# The walls
# ---------------------------------------------------------------------------


def test_network_is_off(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    (trial.root / pyrepo_min.NET_TEST).write_text(pyrepo_min.NET_TEST_SRC, encoding="utf-8")
    run = runner.run(executor, trial.root, (pyrepo_min.NET_TEST,))
    assert run.red and not run.timed_out
    assert run.failing == frozenset({pyrepo_min.NET_TEST_ID})
    assert "URLError" in run.tail, run.tail


def test_worktree_is_read_only(trial, task, runner, executor):
    trial.overlay_sources(task.src_files)
    (trial.root / pyrepo_min.WRITE_TEST).write_text(pyrepo_min.WRITE_TEST_SRC, encoding="utf-8")
    run = runner.run(executor, trial.root, (pyrepo_min.WRITE_TEST,))
    assert run.red and not run.timed_out
    assert run.failing == frozenset({pyrepo_min.WRITE_TEST_ID})
    assert "Read-only file system" in run.tail, run.tail
    assert not (trial.root / "hacked.txt").exists()


def test_host_worktree_unchanged_after_sandboxed_run(trial, task, config, runner, executor):
    trial.overlay_sources(task.src_files)
    before = _snapshot(trial.root)
    top_before = {p.name for p in trial.root.iterdir()}
    res = grade(trial, task, config=config, runner=runner, executor=executor)
    assert res.clean is True
    assert _snapshot(trial.root) == before
    assert trial.touched_files() == sorted({*task.src_files, *task.test_files})
    stray = {p.name for p in trial.root.iterdir()} - top_before - _ALLOWED_HOST_WRITES
    assert not stray, f"sandboxed run left {sorted(stray)} on the host"
