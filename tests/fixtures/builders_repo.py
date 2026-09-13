"""A tiny git repository for builder tests, built inline (no network, no fixtures on disk).

History:

* commit 1 (the PARENT): ``pkg/calc.py`` with a buggy ``add`` (``a - b``), an
  unrelated ``pkg/util.py``, and an existing green test ``tests/test_util.py``.
* commit 2 (the TASK): fixes ``add`` and adds ``tests/test_calc.py`` — the oracle.

At the parent with ``tests/test_calc.py`` overlaid the target is RED; with the
commit's ``pkg/calc.py`` overlaid it is GREEN. ``make_task`` records exactly that
(``red_checked=True``, empty baseline), so :func:`crb.core.grade.grade` can be
run against a builder's edit in the tests.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from crb.core.git import GitRepo
from crb.core.spec import BELT_TARGET_ONLY, Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace

BUGGY_CALC = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
FIXED_CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
UTIL = "def shout(s):\n    return s.upper()\n"
TEST_UTIL = "from pkg.util import shout\n\n\ndef test_shout():\n    assert shout('a') == 'A'\n"
TEST_CALC = (
    "from pkg.calc import add, mul\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n\n"
    "def test_mul():\n    assert mul(2, 3) == 6\n"
)

SUBJECT = "fix: add() must add, not subtract"


def _git(repo: Path, *args: str) -> str:
    argv = [
        "git",
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.com",
        "-c",
        "commit.gpgsign=false",
        "-C",
        str(repo),
        *args,
    ]
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout.strip()


@dataclass(frozen=True)
class Fixture:
    repo: GitRepo
    config: RepoConfig
    task: TaskSpec
    root: Path

    def workspace(self, dest: Path, *, mode: str = "sighted") -> Workspace:
        """A fresh worktree at the parent; tests overlaid only in sighted mode."""
        ws = Workspace.create(self.repo, self.task.task_id, dest, config=self.config)
        if mode == "sighted":
            ws.overlay_tests(self.task.test_files)
        return ws


def make_fixture(base: Path) -> Fixture:
    root = base / "fixture-repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "calc.py").write_text(BUGGY_CALC, encoding="utf-8")
    (root / "pkg" / "util.py").write_text(UTIL, encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_util.py").write_text(TEST_UTIL, encoding="utf-8")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial: buggy add")
    (root / "pkg" / "calc.py").write_text(FIXED_CALC, encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", SUBJECT)
    sha = _git(root, "rev-parse", "HEAD")

    config = RepoConfig(
        name="fixture",
        language=Language.PYTHON,
        src_prefix="pkg/",
        test_prefix="tests/",
        belt_scope=BELT_TARGET_ONLY,
        runner_opts={"python": sys.executable},
    )
    task = TaskSpec(
        task_id=sha,
        repo="fixture",
        subject=SUBJECT,
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_calc.py",),
        src_files=("pkg/calc.py",),
        target_tests=("tests/test_calc.py",),
        belt_scope=("tests/test_calc.py", "tests/test_util.py"),
        src_churn=2,
        size="XS",
        capability_class="bug.fix",
        language="python",
        # at the parent with the oracle overlaid, test_add is RED (the baseline records it)
        baseline_failing=("tests/test_calc.py::test_add",),
        red_checked=True,
        gold_clean=True,
    )
    return Fixture(repo=GitRepo(root), config=config, task=task, root=root)
