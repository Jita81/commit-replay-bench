"""Mine a git repo for feasible replay commits.

A feasible commit pairs a *source* change with a *test* change, small enough to
be a clean single-file regeneration. Whether the test is a genuine RED oracle on
the parent (it must FAIL before the fix) is decided at replay time —
:func:`commit_replay_bench.core.replay_commit` returns ``SKIP`` if it isn't — so
mining stays fast (git metadata only, no test runs).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

_TEST_RE = re.compile(r"(^|/)tests?/")
_TEST_SUFFIXES = ("_test.py", "_test.js", "_test.ts", ".test.ts", ".test.js", ".spec.ts", ".spec.js")


@dataclass
class Candidate:
    """A mineable commit: one source file + its test(s), bounded churn."""

    commit: str
    subject: str
    src_path: str
    test_paths: list[str] = field(default_factory=list)
    churn: int = 0


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout


def _is_test(path: str) -> bool:
    p = path.lower()
    return bool(_TEST_RE.search(p)) or "test_" in p or p.endswith(_TEST_SUFFIXES)


def _is_src(path: str, exts: tuple[str, ...]) -> bool:
    return path.endswith(exts) and not _is_test(path) and "__init__" not in path


def mine_feasible_commits(
    repo: str,
    *,
    limit: int = 400,
    src_exts: tuple[str, ...] = (".py",),
    max_src_files: int = 1,
    min_churn: int = 3,
    max_churn: int = 400,
    max_src_lines: int = 1200,
) -> list[Candidate]:
    """Scan the last ``limit`` non-merge commits and return the feasible ones.

    A commit is feasible when it touches between 1 and ``max_src_files`` source
    files (matching ``src_exts``, excluding tests and ``__init__``) AND at least
    one test file, with total source churn in ``[min_churn, max_churn]``, and the
    single source file is at most ``max_src_lines`` on the parent (keeps the
    regeneration prompt bounded). Newest first.
    """
    raw = _git(repo, "log", "--no-merges", f"-{limit}", "--numstat", "--pretty=format:@@@%H|%s")
    commits: list[dict] = []
    cur: dict | None = None
    for ln in raw.splitlines():
        if ln.startswith("@@@"):
            if cur:
                commits.append(cur)
            h, _, s = ln[3:].partition("|")
            cur = {"h": h, "s": s, "src": [], "tst": [], "churn": 0}
        elif ln.strip() and cur and "\t" in ln:
            added, deleted, path = (ln.split("\t") + ["", "", ""])[:3]
            churn = (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)
            if _is_src(path, src_exts):
                cur["src"].append(path)
                cur["churn"] += churn
            elif _is_test(path):
                cur["tst"].append(path)
    if cur:
        commits.append(cur)

    out: list[Candidate] = []
    for c in commits:
        if not (1 <= len(c["src"]) <= max_src_files and c["tst"]):
            continue
        if not (min_churn <= c["churn"] <= max_churn):
            continue
        src = c["src"][0]
        parent_src = _git(repo, "show", f"{c['h']}~1:{src}")
        n_lines = len(parent_src.splitlines())
        if 0 < n_lines <= max_src_lines:
            out.append(Candidate(c["h"], c["s"], src, list(dict.fromkeys(c["tst"])), c["churn"]))
    return out
