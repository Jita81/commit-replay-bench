"""Shared fixtures for the hermetic core suite. Nothing here needs docker or a network —
and a test that does need the network is skipped, with the reason, when it is not there.

Navigation
----------
What it is:   The pytest conftest of the hermetic core suite — five function-scoped fixtures
              over the Python fixture repository, the setup gate for network tests, and the
              session finaliser that keeps the base temporary directory deletable.
What it does: Builds a fresh ``pyrepo`` (three commits) per test and derives from it the
              ``runner`` (a real ``PytestRunner``), a ``LocalExecutor``, the mined
              ``feat_task`` and a sighted ``trial`` worktree that is removed afterwards. Nothing
              here needs docker, a network or a model; nothing here decides a verdict. Before
              every ``@pytest.mark.network`` test it asks whether the hosts the marker names
              answer, and skips the test with the host and the reason when they do not (a
              failure under ``CRB_TEST_STRICT_WARMUP=1``, as in CI). When the session ends it
              gives every directory under the base temporary directory back to its owner, so
              the read-only sealed sets some tests leave never stop pytest deleting it (P-101).
How:          ``pyrepo`` calls ``fixtures.pyrepo.build`` under ``tmp_path``; ``trial`` yields
              ``PyRepo.trial`` inside try/finally so a failing test never leaks a worktree;
              ``pytest_runtest_setup`` hands the ``network`` marker's hosts to
              ``conftest_langs.require_network``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/pyrepo.py (the repository every fixture derives from),
              src/crb/core/runners/pytest_runner.py (``runner``), src/crb/core/execution.py
              (``executor``), src/crb/core/workspace.py (``trial``), tests/conftest_langs.py
              and tests/conftest_store.py (the deliberately separate helper modules),
              tests/fixtures/tmptree.py (``restore_removable``, the finaliser's walk)
Tested by:    tests/test_grade.py, tests/test_mine.py, tests/test_workspace.py (every consumer),
              tests/test_conftest_langs.py (the network gate), tests/test_tmp_tree_hygiene.py
              (the finaliser)
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
from fixtures.tmptree import restore_removable

try:  # the same module object the test modules import (tests/ may or may not be a package)
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs


def pytest_runtest_setup(item: pytest.Item) -> None:
    """A ``@pytest.mark.network`` test runs only when the hosts it names answer.

    Offline, or behind a proxy that refuses, it is skipped with the host and the reason
    instead of failing on an install the host could never complete; under strict warm-up
    (CI, where the network is there) it fails. The marker's arguments are the hosts; none
    means the Python package index.
    """
    marker = item.get_closest_marker("network")
    if marker is not None:
        langs.require_network(tuple(str(h) for h in marker.args))


@pytest.fixture(scope="session", autouse=True)
def _basetemp_stays_removable(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Hand every directory under this session's base temporary directory back to its
    owner when the session ends (P-101). A sealed dependency set is read-only by design
    (``crb.provision.store``); left that way, pytest cannot delete an old base directory,
    renames it ``garbage-<uuid>`` and keeps it — about 0.4 GB per full run. Links are never
    followed. Guarded by ``tests/test_tmp_tree_hygiene.py``."""
    yield
    restore_removable(tmp_path_factory.getbasetemp())


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
