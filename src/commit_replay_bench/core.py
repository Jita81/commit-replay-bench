"""Commit-replay benchmark — attach to a repo, replay its real commits, and grade
each AI-can-do / needs-human / fails against the repo's OWN tests.

The core measurement: a repo's test suite is the held-out oracle and its
commits are ground truth, so "can we manufacture on this repo?" is measurable.
Per commit: check out the parent, overlay the commit's tests (which now FAIL =
RED on base — a valid oracle), have the model regenerate the source change, and
require the tests to pass (GREEN) without breaking the rest of the suite.

Grading (matches three buckets):
  * ``ai_can``      — edit applied, target tests GREEN on the first attempt, no
                      regressions. The factory reproduces the change unaided.
  * ``needs_human`` — GREEN only after a remediation retry, OR GREEN but it broke
                      other tests (a reviewer must reconcile).
  * ``fails``       — tests still RED after all attempts (or no usable edit).

The pure pieces (parse / apply / grade) are the hard-won robustness — a tolerant
SEARCH/REPLACE parser (the model varies marker whitespace/count/CRLF) and a fuzzy
applier (indentation drift) — and are unit-tested. The git/test/model IO sits
behind the :class:`RepoHarness` protocol + a ``generate`` callable, both injectable,
so the orchestration is hermetic.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

AI_CAN = "ai_can"
NEEDS_HUMAN = "needs_human"
FAILS = "fails"
SKIP = "skip"  # not a valid oracle (the commit's tests already pass on the parent)


# --- pure: tolerant SEARCH/REPLACE parsing --------------------------------------
def parse_edit_blocks(text: str) -> list[tuple[str, str]]:
    """Parse SEARCH/REPLACE blocks, tolerant of the markers the model actually
    emits — any run of >=5 of the marker char, surrounding whitespace, a bare
    ``====`` divider line, and CRLF. (A strict regex silently dropped valid edits.)"""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if re.match(r"\s*<{5,}\s*SEARCH", lines[i]):
            i += 1
            search: list[str] = []
            while i < len(lines) and not re.match(r"\s*={5,}\s*$", lines[i]):
                search.append(lines[i])
                i += 1
            i += 1  # skip the ==== divider
            repl: list[str] = []
            while i < len(lines) and not re.match(r"\s*>{5,}\s*REPLACE", lines[i]):
                repl.append(lines[i])
                i += 1
            i += 1  # skip the >>>> end marker
            blocks.append(("\n".join(search), "\n".join(repl)))
        else:
            i += 1
    return blocks


# --- pure: fuzzy apply ----------------------------------------------------------
def _find_window(lines: list[str], search: list[str], key: Callable[[str], str]) -> int:
    for i in range(len(lines) - len(search) + 1):
        if all(key(lines[i + j]) == key(search[j]) for j in range(len(search))):
            return i
    return -1


def apply_edit_blocks(src: str, blocks: list[tuple[str, str]]) -> tuple[str, int]:
    """Apply each block by locating its SEARCH lines and substituting REPLACE.
    Tries an exact match (trailing-ws-insensitive) then a fuzzy match (ignoring
    leading indentation, since the model sometimes re-indents). Returns the new
    source and how many blocks applied."""
    lines = src.split("\n")
    applied = 0
    for search, repl in blocks:
        sl = search.split("\n")
        while sl and sl[-1].strip() == "":
            sl.pop()
        if not sl:
            continue
        i = _find_window(lines, sl, lambda x: x.rstrip())
        if i < 0:
            i = _find_window(lines, sl, lambda x: x.strip())
        if i >= 0:
            lines[i : i + len(sl)] = repl.split("\n")
            applied += 1
    return "\n".join(lines), applied


# --- pure: grading --------------------------------------------------------------
def grade(*, target_passed: bool, regressed: bool, succeeded_attempt: int | None) -> str:
    """The three-way verdict. ``succeeded_attempt`` is the 1-based attempt that
    turned the target tests GREEN (None if they never passed)."""
    if not target_passed:
        return FAILS
    if regressed:
        return NEEDS_HUMAN  # passes the target but broke other tests
    if succeeded_attempt and succeeded_attempt > 1:
        return NEEDS_HUMAN  # only after a remediation retry
    return AI_CAN


@dataclass(frozen=True)
class TestRun:
    rc: int
    failed_ids: set[str]
    tail: str = ""


@dataclass(frozen=True)
class CommitSpec:
    commit: str
    subject: str
    src_path: str
    test_paths: list[str]
    complexity: str | None = None


@dataclass(frozen=True)
class ReplayResult:
    commit: str
    complexity: str | None
    verdict: str
    attempts: int
    blocks: int
    applied: int
    target_passed: bool
    regressed: bool
    note: str = ""


class RepoHarness(Protocol):
    """The live, injectable side: git + the repo's test runner."""

    def reset(self) -> None: ...
    def checkout_parent(self, commit: str) -> None: ...
    def overlay_tests(self, commit: str, test_paths: list[str]) -> None: ...
    def read(self, path: str) -> str: ...
    def write(self, path: str, content: str) -> None: ...
    def restore_parent(self, commit: str, path: str) -> None: ...
    def run_tests(self, paths: list[str]) -> TestRun: ...


#: generate(subject, src_path, src, tests, prior_failure) -> SEARCH/REPLACE blocks
GenerateFn = Callable[..., list[tuple[str, str]]]


def valid_python(src: str, path: str) -> tuple[bool, str]:
    """A ``.py`` edit must compile. The tolerant/fuzzy apply can mis-splice an edit
    into syntactically-broken code; running it would error the WHOLE test suite (a
    collection failure), masking a mere attempt failure as a catastrophe. Gate on
    compile so an invalid edit is a retryable attempt, not a crash. Non-py → ok."""
    if not path.endswith(".py"):
        return True, ""
    try:
        compile(src, path, "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"{e.msg} at line {e.lineno}"


def replay_commit(
    harness: RepoHarness,
    spec: CommitSpec,
    generate: GenerateFn,
    *,
    max_attempts: int = 3,
    full_test_target: str = "tests",
) -> ReplayResult:
    """Replay one commit and grade it. ``generate`` receives ``prior_failure`` on
    retries (the actual test output) — feeding that back is the Q1-fix-loop lever."""
    harness.reset()
    harness.checkout_parent(spec.commit)
    harness.overlay_tests(spec.commit, spec.test_paths)
    if harness.run_tests(spec.test_paths).rc == 0:
        harness.reset()
        return ReplayResult(spec.commit, spec.complexity, SKIP, 0, 0, 0, False, False, "no RED oracle")
    base_fail = harness.run_tests([full_test_target]).failed_ids
    src0 = harness.read(spec.src_path)
    tests_text = "\n\n".join(harness.read(t) for t in spec.test_paths)

    last_blocks = last_applied = 0
    prior: str | None = None
    for attempt in range(1, max_attempts + 1):
        blocks = generate(
            subject=spec.subject, src_path=spec.src_path, src=src0,
            tests=tests_text, prior_failure=prior,
        )
        new_src, applied = apply_edit_blocks(src0, blocks)
        last_blocks, last_applied = len(blocks), applied
        if applied == 0:
            prior = "Your previous edit did not apply — copy the SEARCH lines verbatim from the file."
            continue
        ok, syntax_err = valid_python(new_src, spec.src_path)
        if not ok:
            # a mis-spliced edit that breaks syntax would else error the WHOLE suite
            # (an attempt-failure masquerading as catastrophe) — retry instead.
            prior = f"Your edit produced INVALID PYTHON ({syntax_err}) — fix the syntax; copy SEARCH lines exactly."
            last_applied = 0
            continue
        harness.write(spec.src_path, new_src)
        tgt = harness.run_tests(spec.test_paths)
        after = harness.run_tests([full_test_target])
        regressed = bool(after.failed_ids - base_fail)
        if tgt.rc == 0:
            verdict = grade(target_passed=True, regressed=regressed, succeeded_attempt=attempt)
            harness.reset()
            return ReplayResult(spec.commit, spec.complexity, verdict, attempt,
                                last_blocks, last_applied, True, regressed)
        prior = tgt.tail or "Tests still failing."
        harness.restore_parent(spec.commit, spec.src_path)  # revert for the next attempt

    harness.reset()
    return ReplayResult(spec.commit, spec.complexity, FAILS, max_attempts,
                        last_blocks, last_applied, False, False)


def aggregate(results: list[ReplayResult]) -> dict:
    """Roll replay results up into the three-bucket summary + per-complexity."""
    graded = [r for r in results if r.verdict != SKIP]
    by_complexity: dict[str, dict[str, int]] = {}
    counts = {AI_CAN: 0, NEEDS_HUMAN: 0, FAILS: 0}
    for r in graded:
        counts[r.verdict] += 1
        cell = by_complexity.setdefault(r.complexity or "?", {AI_CAN: 0, NEEDS_HUMAN: 0, FAILS: 0})
        cell[r.verdict] += 1
    return {"n": len(graded), "skipped": len(results) - len(graded),
            "counts": counts, "by_complexity": by_complexity}


# --- live harness (git + a venv pytest) -----------------------------------------
class LiveGitHarness:
    """RepoHarness over a real git checkout + an isolated python for the tests."""

    def __init__(self, repo_path: str, python: str, base_ref: str = "main", test_timeout: int = 90):
        self.repo = repo_path
        self.python = python
        self.base_ref = base_ref
        self.test_timeout = test_timeout  # a generated edit can make a test BLOCK (tty/stdin)

    def _git(self, *a):
        return subprocess.run(["git", "-C", self.repo, *a], capture_output=True, text=True)

    def reset(self) -> None:
        self._git("checkout", "-f", self.base_ref)
        self._git("clean", "-fdq")

    def checkout_parent(self, commit: str) -> None:
        self._git("checkout", "-f", f"{commit}~1")

    def overlay_tests(self, commit: str, test_paths: list[str]) -> None:
        self._git("checkout", commit, "--", *test_paths)

    def read(self, path: str) -> str:
        fp = os.path.join(self.repo, path)
        return open(fp).read() if os.path.exists(fp) else ""

    def write(self, path: str, content: str) -> None:
        open(os.path.join(self.repo, path), "w").write(content)

    def restore_parent(self, commit: str, path: str) -> None:
        self._git("checkout", f"{commit}~1", "--", path)

    def run_tests(self, paths: list[str]) -> TestRun:
        try:
            r = subprocess.run(
                [self.python, "-m", "pytest", "--tb=no", "-q", "-rfE", "-p", "no:cacheprovider", *paths],
                cwd=self.repo, capture_output=True, text=True,
                timeout=self.test_timeout, start_new_session=True,
            )
        except subprocess.TimeoutExpired:
            # the edit made a test hang (e.g. blocking on a tty/stdin) — that's a
            # failed attempt, never an infinite wait.
            return TestRun(1, set(), "TIMEOUT — a test hung (likely blocking on input)")
        out = r.stdout + r.stderr
        failed = set(re.findall(r"^(?:FAILED|ERROR)\s+(\S+)", out, re.M))
        tail = "\n".join(out.strip().splitlines()[-15:])
        return TestRun(r.returncode, failed, tail)
