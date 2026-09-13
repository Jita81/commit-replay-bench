"""``cargo test`` runner (Rust)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import BaseRunner, TestRun, tail_of

_FAILED = re.compile(r"^(?:test )?(\S+) (?:\.\.\.|---) FAILED$", re.M)


class CargoRunner(BaseRunner):
    name = "cargo"
    default_timeout = 1200

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        # tests/foo.rs -> integration test binary "foo"; tests/builder/env.rs -> "builder"
        stems = set()
        for f in test_files:
            parts = f.split("/")
            if len(parts) >= 2 and parts[0] == "tests":
                stems.add(
                    parts[1][:-3] if len(parts) == 2 and parts[1].endswith(".rs") else parts[1]
                )
            else:
                stems.add("ALL")
        return tuple(sorted(stems))

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        cargo = executor.tool("cargo", self.opts.get("cargo"))
        # No --quiet: the quiet harness prints "name --- FAILED", the verbose one
        # "test name ... FAILED"; we parse both but keep the stable verbose format.
        # --no-fail-fast: cargo stops at the first failing test BINARY otherwise, which
        # truncates belt 3's failing set (a false "no new failures").
        argv = [
            cargo,
            "test",
            "--no-fail-fast",
            "--offline" if self.opts.get("offline", True) else "--locked",
        ]
        for t in scope:
            if t != "ALL":
                argv += ["--test", t]
        env = {
            "CARGO_TARGET_DIR": "/work/target"
            if executor.name == "docker"
            else str(root / "target"),
            "CARGO_TERM_COLOR": "never",
        }
        if executor.name == "docker":
            env["CARGO_HOME"] = str(self.opts.get("cargo_home", "/tmp/cargo"))
        return Command(tuple(argv), root, env=env, timeout=timeout, writable_paths=("target",))

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        failing = frozenset(m.strip() for m in _FAILED.findall(result.combined))
        return TestRun(
            result.returncode, failing, tail_of(result.combined), duration_s=result.duration_s
        )
