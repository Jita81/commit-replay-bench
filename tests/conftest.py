"""Shared fixtures for the hermetic core suite. Nothing here needs docker or a network."""

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
    return PytestRunner(pyrepo.config)


@pytest.fixture
def executor() -> LocalExecutor:
    return LocalExecutor()


@pytest.fixture
def feat_task(pyrepo: pr.PyRepo) -> TaskSpec:
    return pyrepo.feat_task()


@pytest.fixture
def trial(pyrepo: pr.PyRepo, tmp_path: Path) -> Iterator[Workspace]:
    """A sighted trial worktree: parent + target tests overlaid; removed afterwards."""
    ws = pyrepo.trial(tmp_path / "trial")
    try:
        yield ws
    finally:
        ws.remove()
