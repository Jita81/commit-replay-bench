"""The one runner contract every language honours.

A runner turns a *scope* (test files, packages, classes, or test binaries —
whatever the toolchain addresses) into a :class:`~crb.core.execution.Command`,
hands it to an executor, and parses the output into a :class:`TestRun`:

    (returncode, failing_test_ids, tail, timed_out)

Two scopes matter to the grader:

* the **target scope** — the commit's own test files, mapped to what the
  toolchain can address (belt 2: target green);
* the **belt scope** — the regression surface (belt 3: no new failures),
  resolved from the repo's ``belt_scope`` policy.

Runners never decide verdicts. They report what the toolchain said.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from crb.core.execution import Command, ExecResult, Executor
from crb.core.spec import BELT_AFFECTED_DIRS, BELT_BARE, BELT_TARGET_ONLY, RepoConfig

#: Sentinel: "run the toolchain's default discovery" (the census ``BARE`` scope).
BARE: tuple[str, ...] = ()

#: Cap on the raw output tail we keep (evidence packs are redacted + capped).
TAIL_LINES = 40


@dataclass(frozen=True)
class TestRun:
    returncode: int
    failing: frozenset[str]
    tail: str = ""
    timed_out: bool = False
    duration_s: float = 0.0
    parse_error: str = ""

    @property
    def green(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.parse_error

    @property
    def red(self) -> bool:
        return not self.green

    def to_dict(self) -> dict[str, Any]:
        return {
            "returncode": self.returncode,
            "failing": sorted(self.failing),
            "tail": self.tail,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 3),
            "parse_error": self.parse_error,
        }


def tail_of(text: str, n: int = TAIL_LINES) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


class TestRunner(Protocol):
    name: str
    config: RepoConfig

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]: ...

    def belt_scope(
        self, target_tests: Sequence[str], test_files: Sequence[str]
    ) -> tuple[str, ...]: ...

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command: ...

    def parse(self, result: ExecResult, root: Path) -> TestRun: ...

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int
    ) -> TestRun: ...

    def is_valid_oracle(self, root: Path, test_file: str) -> bool: ...


class BaseRunner:
    """Shared plumbing. Subclasses implement ``target_scope``, ``command``, ``parse``."""

    name = "base"
    default_timeout = 900

    def __init__(self, config: RepoConfig) -> None:
        self.config = config
        self.opts: dict[str, Any] = dict(config.runner_opts)

    # --- scopes ------------------------------------------------------------------
    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted(set(test_files)))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
        policy = self.config.belt_scope
        if isinstance(policy, tuple):
            return BARE if policy in {("BARE",), ()} else policy
        if policy == BELT_TARGET_ONLY:
            return tuple(target_tests)
        if policy == BELT_AFFECTED_DIRS:
            dirs = sorted({os.path.dirname(tf) + "/" for tf in test_files if os.path.dirname(tf)})
            return tuple(dirs) or ((self.config.test_prefix,) if self.config.test_prefix else BARE)
        if policy == BELT_BARE:
            return BARE
        raise ValueError(f"unknown belt_scope policy {policy!r}")  # pragma: no cover

    # --- execution ---------------------------------------------------------------
    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        raise NotImplementedError

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        raise NotImplementedError

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int = 0
    ) -> TestRun:
        t = timeout or int(self.opts.get("timeout", self.default_timeout))
        cmd = self.command(root, scope, executor=executor, timeout=t)
        result = executor.run(cmd)
        if result.timed_out:
            return TestRun(124, frozenset(), tail_of(result.combined), True, result.duration_s)
        run = self.parse(result, root)
        parse_error = run.parse_error
        # FAIL CLOSED on unattributed failure: a non-zero exit with no parsed failing
        # test ids (compile error, crash, reporter mismatch) must never read as "no
        # new failures". The grader treats parse_error as a failed belt.
        if run.returncode != 0 and not run.failing and not parse_error:
            parse_error = f"unattributed failure (rc={run.returncode}, no failing ids parsed)"
        return TestRun(
            run.returncode,
            run.failing,
            run.tail or tail_of(result.combined),
            False,
            result.duration_s,
            parse_error,
        )

    # --- oracle validity ---------------------------------------------------------
    def is_valid_oracle(self, root: Path, test_file: str) -> bool:
        """A target test file must exist and be non-trivial. Languages with a cheap
        static signal (pytest's ``def test`` / ``class Test``) tighten this."""
        p = root / test_file
        try:
            return p.is_file() and p.stat().st_size > 0
        except OSError:
            return False

    def describe(self) -> dict[str, Any]:
        return {"runner": self.name}


_FAIL_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)


def parse_pytest_failures(text: str) -> frozenset[str]:
    """The pytest ``-rfE`` short-summary parser. Shared so every pytest path is identical."""
    return frozenset(m.split(" ")[0] for m in _FAIL_LINE.findall(text))
