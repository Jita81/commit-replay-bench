"""Minimal Python fixture for the sandbox (docker) tests.

Kept separate from ``tests/fixtures/pyrepo.py`` (owned by the core test suite):
this one needs nothing but the interpreter + pytest inside the image.

    pkg/__init__.py, pkg/calc.py   add            \\  commit 1
    tests/test_calc.py             test_add       /
    pkg/sub.py                     sub            \\  commit 2 (the feat)
    tests/test_sub.py              test_sub       /

Pytest ids are ``tests/test_sub.py::test_sub`` etc. The runner's declared
writable path (``.pytest_scratch``) is git-ignored so a sandboxed run leaves
``git status`` clean.

Navigation
----------
What it is:   The minimal Python fixture for the docker sandbox tests.
What it does: Builds the two-commit shape with nothing but the interpreter and pytest required
              inside the image, with the runner's writable scratch path git-ignored so a
              sandboxed run leaves the worktree clean. Kept apart from ``fixtures/pyrepo.py``,
              which belongs to the core suite and carries opt-in commits the sandbox never needs.
How:          ``two_commit_repo`` over ``pkg/`` sources and ``tests/`` files; ``config`` returns a
              ``RepoConfig`` for the pytest runner with the requested belt scope.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   tests/test_sandbox_docker.py and tests/test_builders_container_docker.py (the
              consumers), tests/fixtures/langs/__init__.py (the shape),
              src/crb/core/execution.py (``DockerExecutor`` runs it), tests/conftest_langs.py
              (``ensure_docker_image``)
Tested by:    tests/test_sandbox_docker.py, tests/test_builders_container_docker.py
Touch when:   the sandbox image changes what it carries (the fixture must still need nothing but
              pytest); never for a new repository.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from crb.core.spec import BELT_BARE, Language, RepoConfig

from . import two_commit_repo

SRC_CALC = "pkg/calc.py"
SRC_SUB = "pkg/sub.py"
TEST_CALC = "tests/test_calc.py"
TEST_SUB = "tests/test_sub.py"

ADD_TEST_ID = "tests/test_calc.py::test_add"
SUB_TEST_ID = "tests/test_sub.py::test_sub"

#: Extra oracles the sandbox tests drop into a worktree to probe the walls.
NET_TEST = "tests/test_net.py"
NET_TEST_ID = "tests/test_net.py::test_network_reachable"
NET_TEST_SRC = (
    "import urllib.request\n\n\n"
    "def test_network_reachable():\n"
    '    with urllib.request.urlopen("https://example.com", timeout=5) as r:\n'
    "        assert r.status == 200\n"
)
WRITE_TEST = "tests/test_write.py"
WRITE_TEST_ID = "tests/test_write.py::test_can_write_worktree"
WRITE_TEST_SRC = (
    "import pathlib\n\n\n"
    "def test_can_write_worktree():\n"
    '    pathlib.Path("/work/hacked.txt").write_text("owned", encoding="utf-8")\n'
)

_INITIAL = {
    ".gitignore": ".pytest_scratch\n__pycache__\n.pytest_cache\n",
    "pkg/__init__.py": "",
    SRC_CALC: "def add(a: int, b: int) -> int:\n    return a + b\n",
    TEST_CALC: "from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}

_FEAT = {
    SRC_SUB: "def sub(a: int, b: int) -> int:\n    return a - b\n",
    TEST_SUB: "from pkg.sub import sub\n\n\ndef test_sub():\n    assert sub(3, 2) == 1\n",
}


def build(tmp_path: Path, *, extra: Mapping[str, str] | None = None) -> tuple[Path, str]:
    """``extra`` = more files in the initial commit (a lint config the parent carries)."""
    return two_commit_repo(Path(tmp_path) / "pyrepo-min", {**_INITIAL, **(extra or {})}, _FEAT)


def config(
    belt_scope: str | tuple[str, ...] = BELT_BARE, *, runner_opts: Mapping[str, Any] | None = None
) -> RepoConfig:
    """The ``RepoConfig`` for the fixture: the ``pytest`` runner over ``pkg/`` + ``tests/``;
    ``runner_opts`` is passed through untouched (the default is empty: the image's own pytest).
    """
    return RepoConfig(
        name="pyfix-min",
        language=Language.PYTHON,
        runner="pytest",
        src_prefix="pkg/",
        test_prefix="tests/",
        ext=".py",
        belt_scope=belt_scope,
        runner_opts=dict(runner_opts or {}),
    )
