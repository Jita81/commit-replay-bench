"""A fixture repository where two commits carry one change: cherry-picks and a revert.

The commit census of 2026-09-27 found both shapes in real cells: in click's ``bug.fix`` S
cell two commits with one ``git patch-id`` (a fix landed on ``main`` and cherry-picked to
``stable``), and a revert sitting in the same cell as the commit it reverts. This builds the
same shapes on top of ``pyrepo`` with dates a day apart, so the walk order is deterministic:

* ``pick_old`` — on a ``stable`` branch, ``fix: add multiply`` (src + a new test);
* ``pick_new`` — the same change cherry-picked onto ``main`` a day later (same patch-id);
* a merge of ``stable`` into ``main`` (so ``git log --no-merges`` walks both);
* ``original`` — ``feat: add power`` (src + a new test);
* ``revert`` — ``git revert`` of ``original`` (its message names it).

Navigation
----------
What it is:   The fixture for ADR-less stream G work (DL-093): a distinct commit is a distinct
              change.
What it does: Builds the pyrepo history plus a cherry-pick pair across a merge and a revert
              pair, each commit at a fixed author and committer date.
How:          ``pyrepo.build`` then plain ``git`` with ``GIT_AUTHOR_DATE`` / ``GIT_COMMITTER_DATE``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md (the miner it feeds); DL-093
Works with:   tests/fixtures/pyrepo.py (the base history), src/crb/core/mine.py (the walk it
              exercises), tests/test_mine_distinct_change.py (its consumer)
Tested by:    tests/test_mine_distinct_change.py
Touch when:   the census finds another shape of one change in two commits.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from crb.core.git import GitRepo
from crb.core.spec import RepoConfig
from fixtures import pyrepo as pr

TEST_POWER = "tests/test_power.py"
TEST_POWER_SRC = "from calc import power\n\n\ndef test_power():\n    assert power(2, 3) == 8\n"
MULTIPLY = "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n"
POWER = "\n\ndef power(a: int, b: int) -> int:\n    return a**b\n"


#: Every commit here is dated after pyrepo's own (which are made now), a day apart.
_T0 = int(time.time()) + 3600


def _git(root: Path, day: int, *args: str) -> str:
    date = f"@{_T0 + day * 86400} +0000"
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    argv = ["git", "-C", str(root), *pr.GIT_IDENTITY, *args]
    p = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed rc={p.returncode}: {p.stderr}")
    return p.stdout.strip()


def _commit(root: Path, day: int, subject: str) -> str:
    _git(root, day, "add", "-A")
    _git(root, day, "commit", "-q", "-m", subject)
    return _git(root, day, "rev-parse", "HEAD")


@dataclass(frozen=True)
class DistinctRepo:
    """The built repository and the shas of its two same-change pairs."""

    path: Path
    feat_sha: str
    pick_old: str
    pick_new: str
    original: str
    revert: str
    config: RepoConfig

    @property
    def repo(self) -> GitRepo:
        return GitRepo(self.path)


def build(root: Path) -> DistinctRepo:
    base = pr.build(root)
    src = root / pr.SRC
    _git(root, 2, "checkout", "-q", "-b", "stable")
    src.write_text(pr.SRC_FEAT + MULTIPLY, encoding="utf-8")
    (root / pr.TEST_MULTIPLY).write_text(pr.TEST_MULTIPLY_SRC, encoding="utf-8")
    pick_old = _commit(root, 2, "fix: add multiply")
    _git(root, 3, "checkout", "-q", "main")
    _git(root, 3, "cherry-pick", "-x", pick_old)
    pick_new = _git(root, 3, "rev-parse", "HEAD")
    _git(root, 4, "merge", "--no-ff", "-q", "-m", "merge stable", "stable")
    src.write_text(pr.SRC_FEAT + MULTIPLY + POWER, encoding="utf-8")
    (root / TEST_POWER).write_text(TEST_POWER_SRC, encoding="utf-8")
    original = _commit(root, 5, "feat: add power")
    _git(root, 6, "revert", "--no-edit", original)
    revert = _git(root, 6, "rev-parse", "HEAD")
    return DistinctRepo(root, base.feat_sha, pick_old, pick_new, original, revert, base.config)
