"""pytest runner (Python)."""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import BaseRunner, TestRun, parse_pytest_failures, tail_of

# A real pytest oracle defines test functions/classes. A source module that merely
# happens to be named test_*.py does NOT — using it as an oracle lets source edits
# read as tamper and runs a non-test file as the target (malformed-oracle class).
_PYTEST_DEF_RE = re.compile(r"(?m)^\s*(?:async\s+)?def\s+test|^\s*class\s+Test")


class PytestRunner(BaseRunner):
    name = "pytest"
    default_timeout = 900

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        host_default = self.opts.get("python") or (
            sys.executable if executor.name != "docker" else None
        )
        python = executor.tool("python", host_default)
        argv = [
            python,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-rfE",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-o",
            "addopts=",
            "--continue-on-collection-errors",
            *scope,
        ]
        env = {
            "PYTHONPATH": str(root) + str(self.opts.get("pythonpath_suffix", "")),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
        if executor.name == "docker":
            env["PYTHONPATH"] = "/work" + str(self.opts.get("pythonpath_suffix", "")).replace(
                str(root), "/work"
            )
        for k, v in dict(self.opts.get("env", {})).items():
            env[str(k)] = str(v)
        return Command(
            tuple(argv), root, env=env, timeout=timeout, writable_paths=(".pytest_scratch",)
        )

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        failing = parse_pytest_failures(result.combined)
        return TestRun(
            result.returncode, failing, tail_of(result.combined), duration_s=result.duration_s
        )

    def is_valid_oracle(self, root: Path, test_file: str) -> bool:
        p = root / test_file
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return _PYTEST_DEF_RE.search(text) is not None
