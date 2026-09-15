"""Tiny, hermetic python fixture repository for the oracle-programme tests.

Real git + real pytest subprocess — no docker, no network, no model. Everything the
negative controls and the mutation scorer need is a known red→green commit shape:

* ``fix``      — buggy ``add`` fixed + the test that is RED on the parent; ``helper.py``
                 is an adjacent same-dir module covered ONLY by the wider suite (the
                 deterministic regression-poison target).
* ``bad_gold`` — a commit whose shipped test the commit's OWN source cannot satisfy
                 (the GOLD control must surface it as a VIOLATION).
* ``new``      — a new-file commit (parent lacks the source).
* ``green``    — a cosmetic commit whose test already passes on the parent (no RED
                 oracle → controls skip).
* ``sub``      — a fix whose parent HAS a root ``conftest.py`` other suite tests depend
                 on (the env-poison control clobbers it → caught by belt 3).
* ``poly``     — a target test mixing ONE literal assert with a loop assert the
                 hardcode cheat cannot parse (→ caught: target stays red).
* ``alone``    — the source is the only module in its directory (regression control
                 honestly not constructible).
* ``mut``      — the mutation fixture: ``mod2.py``'s ``is_admin`` (STRONG oracle) and
                 ``discount`` (WEAK oracle: the ``total > 100`` branch is never
                 exercised, so mutants there escape).

Tasks are produced through the real miner path (:func:`crb.core.mine.qualify`), so
``baseline_failing`` and ``red_checked`` are measured, never assumed.

Navigation
----------
What it is:   The hermetic Python fixture repository for the oracle programme (negative controls
              and mutation scoring).
What it does: Provides one commit per shape the controls and the scorer must handle — ``fix``,
              ``bad_gold``, ``new``, ``green``, ``sub`` (a root conftest other tests depend on),
              ``poly``, ``alone`` and ``mut`` (a strong ``is_admin`` oracle beside a weak
              ``discount`` one) — and builds ``TaskSpec``s through the REAL miner path so
              ``red_checked`` and ``baseline_failing`` are measured, never assumed.
How:          Real ``git`` + real pytest subprocess via ``PytestRunner`` and ``LocalExecutor``;
              ``build_controls_repo`` commits every shape once (session-scoped by callers),
              ``make_task`` runs ``crb.core.mine.qualify``, ``make_task_unchecked`` skips the RED
              check for commits the miner would refuse.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0010-polyglot-negative-controls.md
Works with:   src/crb/core/oracle/controls.py and src/crb/core/oracle/mutation.py (what runs on
              it), src/crb/core/mine.py (``qualify`` builds the tasks),
              tests/test_oracle_controls.py and tests/test_oracle_mutation.py (the consumers),
              tests/test_oracle_sealed_corpus.py (borrows ``init_repo`` / ``commit`` for the
              authored-date lookup)
Tested by:    tests/test_oracle_controls.py, tests/test_oracle_mutation.py,
              tests/test_oracle_sealed_corpus.py
Touch when:   a new control or mutation operator needs a commit shape not listed in the
              docstring — add the commit and its ``*_LINES`` constants, and pin the expected
              verdict in the consumer; never re-order the existing commits (line numbers are
              asserted).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import Candidate, qualify
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import BELT_AFFECTED_DIRS, Language, RepoConfig, TaskSpec

MUT_SRC = """def is_admin(role):
    return role == "admin"


def discount(total):
    if total > 100:
        return total - 10
    return total
"""

MUT_PARENT_SRC = """def is_admin(role):
    return False


def discount(total):
    return 0
"""

MUT_TEST = """from mod2 import discount, is_admin


def test_is_admin_both_directions():
    # STRONG oracle for is_admin — pins both truth directions
    assert is_admin("admin") is True
    assert is_admin("guest") is False


def test_discount_small_only():
    # WEAK oracle for discount — never exercises the total > 100 branch
    assert discount(50) == 50
"""

#: line spans of MUT_SRC: is_admin = 1-2, discount = 5-8
MUT_IS_ADMIN_LINES = frozenset({2})
MUT_DISCOUNT_LINES = frozenset({6, 7})
MUT_ALL_LINES = MUT_IS_ADMIN_LINES | MUT_DISCOUNT_LINES


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run one git command in ``repo`` (``check=True``: a failing git call is a fixture bug)."""
    full_env = {**os.environ, **(env or {})}
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=full_env,
    )
    return r.stdout


def init_repo(repo: Path) -> None:
    """``git init`` with a fixed local identity and signing off, so shas are reproducible."""
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")


def commit(repo: Path, files: dict[str, str], msg: str, *, author_date: str | None = None) -> str:
    """Write ``files``, stage them and commit; ``author_date`` pins both dates for the sealed-corpus
    tests. Returns the new HEAD sha.
    """
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        git(repo, "add", rel)
    env = (
        {"GIT_AUTHOR_DATE": author_date, "GIT_COMMITTER_DATE": author_date} if author_date else None
    )
    git(repo, "commit", "-q", "-m", msg, env=env)
    return git(repo, "rev-parse", "HEAD").strip()


def fixture_config() -> RepoConfig:
    """AFFECTED_DIRS belt so the wider ``tests/`` suite is the regression belt."""
    return RepoConfig(
        name="oracle-fixture",
        language=Language.PYTHON,
        runner="pytest",
        test_prefix="tests/",
        belt_scope=BELT_AFFECTED_DIRS,
        runner_opts={"python": sys.executable, "timeout": 120},
    )


@dataclass(frozen=True)
class ControlsRepo:
    """The built repository and the sha of every shape the docstring lists."""

    path: Path
    fix: str
    bad_gold: str
    new: str
    green: str
    sub: str
    poly: str
    alone: str
    mut: str

    @property
    def git(self) -> GitRepo:
        """The core's ``GitRepo`` wrapper over the fixture path."""
        return GitRepo(self.path)


def build_controls_repo(base: Path) -> ControlsRepo:
    """Commit every shape once under ``base / "r"``; callers scope it to the session and never
    mutate it (tasks are built from shas, worktrees are opened elsewhere).
    """
    repo = base / "r"
    init_repo(repo)
    # base: buggy impl + a smoke test (so `tests/` is a runnable belt) plus an ADJACENT
    # same-dir module covered ONLY by the wider suite — the regression poison target.
    commit(
        repo,
        {
            "mod.py": "def add(a, b):\n    return a - b\n",
            "helper.py": "def helper_val():\n    return 41\n",
            "tests/test_smoke.py": "def test_smoke():\n    assert True\n",
            "tests/test_helper.py": (
                "import helper\n\n\ndef test_helper():\n    assert helper.helper_val() == 41\n"
            ),
        },
        "base",
    )
    fix = commit(
        repo,
        {
            "mod.py": "def add(a, b):\n    return a + b\n",
            "tests/test_mod.py": "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
        "fix add",
    )
    # NEW-FILE commit: the parent lacks the source file entirely.
    new = commit(
        repo,
        {
            "newmod.py": "def mul(a, b):\n    return a * b\n",
            "tests/test_newmod.py": "from newmod import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
        },
        "add newmod",
    )
    # GREEN-ON-PARENT commit: its test already passes on the parent → no RED oracle.
    green = commit(
        repo,
        {
            "mod.py": "def add(a, b):\n    return a + b\n\n\nX = 1\n",
            "tests/test_mod.py": "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
        "cosmetic",
    )
    # CONFTEST-BELT: a root conftest fixture other suite tests depend on — the
    # env-poison control clobbers it, so later specs get a CAUGHT path.
    commit(
        repo,
        {
            "conftest.py": "import pytest\n\n\n@pytest.fixture\ndef magic():\n    return 7\n",
            "tests/test_conf.py": "def test_magic(magic):\n    assert magic == 7\n",
        },
        "conftest belt",
    )
    commit(repo, {"sub.py": "def sub(a, b):\n    return a + b\n"}, "sub base")
    sub = commit(
        repo,
        {
            "sub.py": "def sub(a, b):\n    return a - b\n",
            "tests/test_sub.py": "from sub import sub\n\n\ndef test_sub():\n    assert sub(5, 2) == 3\n",
        },
        "fix sub",
    )
    # POLY: one extractable literal assert + a loop assert the cheat cannot parse.
    commit(repo, {"poly.py": "def double(x):\n    return x\n"}, "poly base")
    poly = commit(
        repo,
        {
            "poly.py": "def double(x):\n    return 2 * x\n",
            "tests/test_poly.py": (
                "from poly import double\n\n\ndef test_double():\n"
                "    assert double(3) == 6\n"
                "    for x in range(4):\n"
                "        assert double(x) == x + x\n"
            ),
        },
        "fix double",
    )
    # ALONE: the source is the only module in its directory → no poison candidate.
    commit(repo, {"pkg/__init__.py": "", "pkg/alone.py": "def one():\n    return 2\n"}, "pkg base")
    alone = commit(
        repo,
        {
            "pkg/alone.py": "def one():\n    return 1\n",
            "tests/test_alone.py": "from pkg.alone import one\n\n\ndef test_one():\n    assert one() == 1\n",
        },
        "fix one",
    )
    # MUT: the mutation-strength fixture (strong oracle for is_admin, weak for discount).
    commit(repo, {"mod2.py": MUT_PARENT_SRC}, "mod2 base")
    mut = commit(repo, {"mod2.py": MUT_SRC, "tests/test_mod2.py": MUT_TEST}, "fix mod2")
    # BAD-GOLD — LAST, so its permanently-RED test never sits in an earlier commit's
    # belt baseline: the shipped test pins a value the commit's own source cannot
    # produce, so the GOLD control must surface it as a VIOLATION.
    commit(repo, {"bad.py": "def twice(x):\n    return x\n"}, "bad base")
    bad_gold = commit(
        repo,
        {
            "bad.py": "def twice(x):\n    return 2 * x\n",
            "tests/test_bad.py": "from bad import twice\n\n\ndef test_twice():\n    assert twice(2) == 5\n",
        },
        "bad gold",
    )
    return ControlsRepo(repo, fix, bad_gold, new, green, sub, poly, alone, mut)


def make_task(
    fr: ControlsRepo,
    sha: str,
    src_files: tuple[str, ...],
    test_files: tuple[str, ...],
    scratch: Path,
    *,
    gold: bool = False,
) -> TaskSpec:
    """A TaskSpec through the REAL miner path (RED check + measured baseline)."""
    config = fixture_config()
    repo = fr.git
    cand = Candidate(sha, tuple(repo.changed_files(sha)), src_files, test_files)
    outcome = qualify(
        repo,
        config,
        cand,
        runner=PytestRunner(config),
        executor=LocalExecutor(),
        scratch=scratch,
        gold=gold,
    )
    if outcome.task is None:
        raise AssertionError(f"fixture commit {sha[:10]} did not qualify: {outcome.skipped_reason}")
    return outcome.task


def make_task_unchecked(
    fr: ControlsRepo, sha: str, src_files: tuple[str, ...], test_files: tuple[str, ...]
) -> TaskSpec:
    """A TaskSpec WITHOUT the RED check (for commits the miner would refuse)."""
    repo = fr.git
    config = fixture_config()
    runner = PytestRunner(config)
    target = runner.target_scope(test_files)
    return TaskSpec(
        task_id=sha,
        repo=config.name,
        subject=repo.subject(sha),
        authored=repo.author_date(sha),
        test_files=test_files,
        src_files=src_files,
        target_tests=target,
        belt_scope=runner.belt_scope(target, test_files),
        language="python",
    )
