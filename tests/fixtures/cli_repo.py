"""A tiny, real git repository with replayable commits, for driving ``crb`` in-process.

History (oldest → newest)::

    c0  init         pkg/__init__.py, README.md            (no tests → not a candidate)
    c1  feat: add    pkg/calc.py (add), tests/test_calc.py  (coupled src+test → task)
    c2  feat: sub    pkg/calc.py (+sub), tests/test_sub.py  (coupled src+test → task)
    c3  docs         README.md                             (docs only → not a candidate)

Every commit is authored with a fixed identity and date so shas are stable
within a test run. Nothing here imports crb; it is plain git + files.

Navigation
----------
What it is:   A four-commit Python git repository for driving the ``crb`` CLI in-process.
What it does: Provides two replayable commits (``add``, ``sub``: coupled source + test) between a
              test-less scaffold and a docs-only commit, so ``crb mine`` must admit exactly two
              candidates; ``apply_gold`` plays the builder by writing the commit's own source into
              a trial worktree. Imports nothing from ``crb``: plain git and files.
How:          Fixed author identity and dates so shas are stable within a run; ``make_repo``
              returns the four shas and per-task ids on a ``CliRepo``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/test_cli.py (the consumer), src/crb/cli/main.py (what is driven),
              src/crb/core/mine.py (the candidate rule this history is shaped for)
Tested by:    tests/test_cli.py
Touch when:   a CLI test needs another commit shape (a non-candidate, a second language) — keep
              the candidate count the miner tests assert.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

CALC_V1 = "def add(a, b):\n    return a + b\n"
CALC_V2 = CALC_V1 + "\n\ndef sub(a, b):\n    return a - b\n"
TEST_CALC = "from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
TEST_SUB = "from pkg.calc import sub\n\n\ndef test_sub():\n    assert sub(5, 3) == 2\n"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "crb-test",
    "GIT_AUTHOR_EMAIL": "crb-test@example.invalid",
    "GIT_COMMITTER_NAME": "crb-test",
    "GIT_COMMITTER_EMAIL": "crb-test@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


@dataclass(frozen=True)
class CliRepo:
    """The built repository and its four shas, oldest first (``c0`` … ``c3``)."""

    path: Path
    shas: tuple[str, ...]  # (c0, c1, c2, c3)

    @property
    def add_task(self) -> str:
        """The sha of ``c1`` (``feat: add``) — the first replayable task."""
        return self.shas[1]

    @property
    def sub_task(self) -> str:
        """The sha of ``c2`` (``feat: sub``) — the second replayable task."""
        return self.shas[2]


def _git(path: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    r = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, env=env, check=True
    )
    return r.stdout.strip()


def _write(path: Path, rel: str, text: str) -> None:
    p = path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(path: Path, message: str) -> str:
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def make_repo(root: Path) -> CliRepo:
    """Build the fixture repository under ``root`` and return its commit shas."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "crb-test")
    _git(root, "config", "user.email", "crb-test@example.invalid")
    _write(root, "pkg/__init__.py", "")
    _write(root, "README.md", "# demo\n")
    c0 = _commit(root, "init")
    _write(root, "pkg/calc.py", CALC_V1)
    _write(root, "tests/test_calc.py", TEST_CALC)
    c1 = _commit(root, "feat: add")
    _write(root, "pkg/calc.py", CALC_V2)
    _write(root, "tests/test_sub.py", TEST_SUB)
    c2 = _commit(root, "feat: sub")
    _write(root, "README.md", "# demo\n\ndocs only\n")
    c3 = _commit(root, "docs: note")
    return CliRepo(root, (c0, c1, c2, c3))


def apply_gold(worktree: Path, task_sha: str, repo: CliRepo) -> None:
    """Play the builder: write the commit's own source into the trial worktree."""
    if task_sha == repo.add_task:
        _write(worktree, "pkg/calc.py", CALC_V1)
    elif task_sha == repo.sub_task:
        _write(worktree, "pkg/calc.py", CALC_V2)
    else:
        raise ValueError(f"unknown task {task_sha}")


__all__ = ["CALC_V1", "CALC_V2", "TEST_CALC", "TEST_SUB", "CliRepo", "apply_gold", "make_repo"]
