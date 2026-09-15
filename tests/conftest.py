"""Shared fixtures for the hermetic core suite. Nothing here needs docker or a network.

Navigation
----------
What it is:   The pytest conftest of the hermetic core suite — five function-scoped fixtures
              over the Python fixture repository.
What it does: Builds a fresh ``pyrepo`` (three commits) per test and derives from it the
              ``runner`` (a real ``PytestRunner``), a ``LocalExecutor``, the mined
              ``feat_task`` and a sighted ``trial`` worktree that is removed afterwards. Nothing
              here needs docker, a network or a model; nothing here decides a verdict.
How:          ``pyrepo`` calls ``fixtures.pyrepo.build`` under ``tmp_path``; ``trial`` yields
              ``PyRepo.trial`` inside try/finally so a failing test never leaks a worktree.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/pyrepo.py (the repository every fixture derives from),
              src/crb/core/runners/pytest_runner.py (``runner``), src/crb/core/execution.py
              (``executor``), src/crb/core/workspace.py (``trial``), tests/conftest_langs.py
              and tests/conftest_store.py (the deliberately separate helper modules)
Tested by:    tests/test_grade.py, tests/test_mine.py, tests/test_workspace.py (every consumer)
Touch when:   never for a new repository; add a fixture here only when three or more core test
              modules need the same object — language, store and server fixtures live in their
              own helper modules so this file stays the core suite's.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr


@pytest.fixture
def pyrepo(tmp_path: Path) -> pr.PyRepo:
    """A fresh three-commit Python fixture repo (function-scoped: tests may add commits)."""
    return pr.build(tmp_path / "pyrepo")


@pytest.fixture
def runner(pyrepo: pr.PyRepo) -> PytestRunner:
    """The real ``PytestRunner`` over the fixture's config — the belts are
    judged by pytest itself.
    """
    return PytestRunner(pyrepo.config)


@pytest.fixture
def executor() -> LocalExecutor:
    """A host executor: the core suite never needs the docker sandbox."""
    return LocalExecutor()


@pytest.fixture
def feat_task(pyrepo: pr.PyRepo) -> TaskSpec:
    """The feat commit's ``TaskSpec`` as ``crb mine`` would record it (RED at the parent)."""
    return pyrepo.feat_task()


@pytest.fixture
def trial(pyrepo: pr.PyRepo, tmp_path: Path) -> Iterator[Workspace]:
    """A sighted trial worktree: parent + target tests overlaid; removed afterwards."""
    ws = pyrepo.trial(tmp_path / "trial")
    try:
        yield ws
    finally:
        ws.remove()
