"""A tiny Python repository built with ``git init`` in a temp dir, in well under a second.

History (newest first)::

    docs_sha     docs: describe the calculator     — README.md only (NOT a candidate)
    feat_sha     feat: add subtract                — src/calc/__init__.py + tests/test_subtract.py
    initial_sha  chore: scaffold calc              — pytest.ini + src/calc/__init__.py + tests/test_calc.py

At ``feat_sha``'s parent with only ``tests/test_subtract.py`` overlaid the target is
RED (``from calc import subtract`` fails at collection); overlaying the commit's own
source turns it GREEN with the belt (``tests/``) clean. That is exactly the shape
:mod:`crb.core.mine` looks for and :mod:`crb.core.grade` judges.

The ``apply_*`` helpers write builder edits into a trial :class:`Workspace` so the
grader's belts can be exercised one at a time:

* :func:`apply_gold`        — the human's own patch (all four belts hold);
* :func:`apply_noop`        — nothing (target stays RED);
* :func:`apply_tamper`      — edits the target test file (belt 1 → disqualified);
* :func:`apply_regression`  — implements ``subtract`` but breaks ``add`` (belt 3);
* :func:`apply_hardcoded`   — special-cases the oracle's inputs (passes every belt —
  the reason oracle adequacy exists);
* :func:`apply_test_only`   — touches only a non-target test file (belt 4 / blind belt 0).

Two opt-in extra commits exist for the miner's negative paths:

* :meth:`PyRepo.add_green_commit`    — src + test coupled, but the test already
  passes at the parent (must be skipped: "not RED");
* :meth:`PyRepo.add_bad_gold_commit` — RED at the parent, gold turns the target
  GREEN but breaks ``add`` (``gold_clean=False``).

One opt-in commit exists for the environment-setup tests:

* :meth:`PyRepo.add_pyproject_commit` — a minimal ``pyproject.toml`` (hatchling,
  ``src/calc`` layout, a ``[test]`` extra) so ``pip install -e .`` has something to
  build. It is NOT part of the default history: the core suite pins the initial
  commit's file list.

Navigation
----------
What it is:   THE core fixture: a three-commit Python repository built with ``git init`` in well
              under a second, plus the builder-edit helpers that exercise each belt.
What it does: Reproduces exactly the shape the miner looks for and the grader judges — a feat
              commit RED at its parent with only its test overlaid, GREEN with its source — and
              supplies ``apply_gold`` / ``apply_noop`` / ``apply_tamper`` / ``apply_regression`` /
              ``apply_hardcoded`` / ``apply_test_only`` so a test can make one belt fail at a
              time. Opt-in commits add a green-at-parent task, a bad-gold task and a
              ``pyproject.toml`` for the setup and test-infrastructure cases.
How:          Fixed identity and dates through ``git``; ``build(root)`` returns a ``PyRepo`` whose
              ``feat_task`` mirrors what ``crb mine`` records and whose ``trial(dest)`` opens a
              sighted ``Workspace`` at the parent.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   tests/conftest.py (turns it into fixtures), src/crb/core/grade.py (the belts the
              ``apply_*`` helpers target), src/crb/core/mine.py (the candidate rule the history
              satisfies), src/crb/core/workspace.py (``trial``), tests/test_grade.py and
              tests/test_mine.py (the heaviest consumers), scripts/walkthrough.sh (pads it into
              the walkthrough's "public" repository)
Tested by:    tests/test_grade.py, tests/test_mine.py, tests/test_workspace.py, tests/test_git.py,
              tests/test_worker.py
Touch when:   a belt or miner rule needs a shape the history cannot show — add an OPT-IN commit
              method (never change the three base commits: ``feat_task`` and the walkthrough
              depend on them) and an ``apply_*`` helper named for the belt it defeats.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from crb.core.git import GitRepo
from crb.core.spec import BELT_AFFECTED_DIRS, Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace

REPO_NAME = "pyrepo"
SRC = "src/calc/__init__.py"
TEST_CALC = "tests/test_calc.py"
TEST_SUBTRACT = "tests/test_subtract.py"
TEST_MULTIPLY = "tests/test_multiply.py"
README = "README.md"

GIT_IDENTITY = ("-c", "user.name=Fixture Bot", "-c", "user.email=fixture@example.invalid")

PYTEST_INI = "[pytest]\ntestpaths = tests\n"

SRC_INITIAL = '''"""A tiny calculator."""


def add(a: int, b: int) -> int:
    return a + b
'''

SRC_FEAT = (
    SRC_INITIAL
    + """

def subtract(a: int, b: int) -> int:
    return a - b
"""
)

#: The regression patch: ``subtract`` is right, ``add`` is now wrong.
SRC_REGRESSION = '''"""A tiny calculator."""


def add(a: int, b: int) -> int:
    return a + b + 1


def subtract(a: int, b: int) -> int:
    return a - b
'''

#: The hard-coded patch: satisfies the oracle's literal inputs and nothing else.
SRC_HARDCODED = (
    SRC_INITIAL
    + """

def subtract(a: int, b: int) -> int:
    if (a, b) == (5, 3):
        return 2
    if (a, b) == (0, 4):
        return -4
    return 0
"""
)

TEST_CALC_SRC = """from calc import add


def test_add():
    assert add(2, 3) == 5


def test_add_negative():
    assert add(-1, 1) == 0
"""

TEST_SUBTRACT_SRC = """from calc import subtract


def test_subtract():
    assert subtract(5, 3) == 2


def test_subtract_negative():
    assert subtract(0, 4) == -4
"""

TEST_MULTIPLY_SRC = """from calc import multiply


def test_multiply():
    assert multiply(3, 4) == 12
"""

README_SRC = "# calc\n\nA tiny calculator used as a test fixture.\n"

PYPROJECT = "pyproject.toml"
DIST_NAME = "calc"
PYPROJECT_SRC = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "calc"
version = "0.1.0"
description = "fixture distribution for the environment-setup tests"
requires-python = ">=3.10"

[project.optional-dependencies]
test = ["pytest"]

[tool.hatch.build.targets.wheel]
packages = ["src/calc"]
"""

#: The ``add`` test ids as the pytest runner reports them (what a regression breaks).
TEST_CALC_IDS = (f"{TEST_CALC}::test_add", f"{TEST_CALC}::test_add_negative")

#: Lines the feat commit adds to the source file (its churn).
FEAT_SRC_CHURN = 4


def git(path: Path, *args: str) -> str:
    """Run one git command in ``path`` with a fixed identity; raise on failure."""
    argv = ["git", "-C", str(path), *GIT_IDENTITY, *args]
    p = subprocess.run(argv, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed rc={p.returncode}: {p.stderr}")
    return p.stdout.strip()


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _commit(root: Path, subject: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", subject)
    return git(root, "rev-parse", "HEAD")


def default_config(**overrides: object) -> RepoConfig:
    """The :class:`RepoConfig` that describes the fixture layout.

    ``python`` is pinned to the running interpreter (it has pytest installed) and
    ``pythonpath_suffix`` puts ``src/`` on the path — both go through the real
    ``runner_opts`` plumbing.
    """
    base: dict[str, object] = {
        "name": REPO_NAME,
        "language": Language.PYTHON,
        "runner": "pytest",
        "src_prefix": "src/",
        "test_prefix": "tests/",
        "ext": ".py",
        "belt_scope": BELT_AFFECTED_DIRS,
        "runner_opts": {"python": sys.executable, "pythonpath_suffix": "/src"},
    }
    base.update(overrides)
    return RepoConfig(**base)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PyRepo:
    """The built repository: its path, the three base shas and the
    ``RepoConfig`` that describes it.
    """

    path: Path
    initial_sha: str
    feat_sha: str
    docs_sha: str
    config: RepoConfig

    @property
    def repo(self) -> GitRepo:
        """The core's ``GitRepo`` wrapper over the fixture path."""
        return GitRepo(self.path)

    # --- tasks -------------------------------------------------------------------
    def feat_task(self, **changes: object) -> TaskSpec:
        """The feat commit as the miner records it (test_mine proves the baseline)."""
        base = TaskSpec(
            task_id=self.feat_sha,
            repo=REPO_NAME,
            subject="feat: add subtract",
            authored=self.repo.author_date(self.feat_sha),
            test_files=(TEST_SUBTRACT,),
            src_files=(SRC,),
            target_tests=(TEST_SUBTRACT,),
            belt_scope=("tests/",),
            src_churn=FEAT_SRC_CHURN,
            size="XS",
            capability_class="bug.fix",
            language="python",
            baseline_failing=(TEST_SUBTRACT,),
            red_checked=True,
            gold_clean=True,
        )
        return base.with_(**changes) if changes else base

    def green_task(self) -> TaskSpec:
        """A task whose target (``tests/test_calc.py``) is ALREADY green at the parent.

        ``tests/test_calc.py`` is byte-identical between the parent and ``feat_sha`` so
        belt 1 holds; the target passes without any source change, which is exactly
        the situation belt 4 (``source_changed``) exists to refuse.
        """
        return self.feat_task(test_files=[TEST_CALC], target_tests=[TEST_CALC], baseline_failing=[])

    # --- worktrees -----------------------------------------------------------------
    def trial(self, dest: Path, *, sha: str = "", overlay_tests: bool = True) -> Workspace:
        """A fresh trial worktree at the commit's parent, tests overlaid (sighted mode)."""
        ws = Workspace.create(self.repo, sha or self.feat_sha, dest, config=self.config)
        if overlay_tests:
            ws.overlay_tests([TEST_SUBTRACT])
        return ws

    # --- extra commits (mutate the repo; use on a function-scoped fixture) -----------
    def add_green_commit(self) -> str:
        """src + test coupled, but the new test passes at the parent → miner must skip."""
        _write(self.path, SRC, SRC_FEAT.replace("A tiny calculator.", "A tiny calculator!"))
        _write(
            self.path,
            TEST_CALC,
            TEST_CALC_SRC + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
        )
        return _commit(self.path, "refactor: docstring + extra add test (green at parent)")

    def add_bad_gold_commit(self) -> str:
        """RED at the parent, gold makes the target GREEN but breaks the belt."""
        _write(
            self.path,
            SRC,
            SRC_REGRESSION + "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
        )
        _write(self.path, TEST_MULTIPLY, TEST_MULTIPLY_SRC)
        return _commit(self.path, "feat: add multiply (breaks add)")

    def add_pyproject_commit(self) -> str:
        """A minimal packaging file so ``pip install -e .`` (the setup phase) works."""
        _write(self.path, PYPROJECT, PYPROJECT_SRC)
        return _commit(self.path, "build: add pyproject.toml")


def build(root: Path) -> PyRepo:
    """``git init`` the fixture under ``root`` (created if missing). Fast: three commits."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "commit.gpgsign", "false")
    _write(root, "pytest.ini", PYTEST_INI)
    _write(root, SRC, SRC_INITIAL)
    _write(root, TEST_CALC, TEST_CALC_SRC)
    initial = _commit(root, "chore: scaffold calc")
    _write(root, SRC, SRC_FEAT)
    _write(root, TEST_SUBTRACT, TEST_SUBTRACT_SRC)
    feat = _commit(root, "feat: add subtract")
    _write(root, README, README_SRC)
    docs = _commit(root, "docs: describe the calculator")
    return PyRepo(root, initial, feat, docs, default_config())


# ---------------------------------------------------------------------------
# Builder edits applied to a trial workspace
# ---------------------------------------------------------------------------


def apply_gold(ws: Workspace) -> None:
    """The commit's own source: every belt holds."""
    ws.overlay_sources([SRC])


def apply_noop(ws: Workspace) -> None:
    """The builder did nothing: target stays RED."""


def apply_tamper(ws: Workspace) -> None:
    """Edit the target test so it passes without ``subtract`` — belt 1 disqualifies."""
    (ws.root / TEST_SUBTRACT).write_text(
        "def test_subtract():\n    assert True\n\n\ndef test_subtract_negative():\n    assert True\n",
        encoding="utf-8",
    )


def apply_regression(ws: Workspace) -> None:
    """Target goes green, ``add`` breaks — belt 3 reports the new failures."""
    (ws.root / SRC).write_text(SRC_REGRESSION, encoding="utf-8")


def apply_hardcoded(ws: Workspace) -> None:
    """Special-case the oracle's inputs. Passes all four belts: only a stronger
    oracle (mutation strength / adequacy) can catch this, not the belts."""
    (ws.root / SRC).write_text(SRC_HARDCODED, encoding="utf-8")


def apply_test_only(ws: Workspace, rel: str = "tests/test_extra.py") -> None:
    """Touch a non-target test file and nothing else (no source change)."""
    _write(ws.root, rel, "def test_extra():\n    assert 1 + 1 == 2\n")


def write_files(ws: Workspace, files: Sequence[tuple[str, str]]) -> None:
    """Write ``(relative_path, content)`` pairs into the trial worktree — a builder edit by hand."""
    for rel, content in files:
        _write(ws.root, rel, content)
