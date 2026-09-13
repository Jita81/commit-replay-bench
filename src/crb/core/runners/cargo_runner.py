"""``cargo test`` runner (Rust).

Setup is ``cargo fetch`` (the registry cache under ``$CARGO_HOME``); ready is
``cargo metadata --offline`` resolving the full dependency graph without the
network — the same resolution ``cargo test --offline`` performs first.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import (
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    TestRun,
    host_check,
    tail_of,
)

_FAILED = re.compile(r"^(?:test )?(\S+) (?:\.\.\.|---) FAILED$", re.M)


class CargoRunner(BaseRunner):
    name = "cargo"
    default_timeout = 1200

    # --- environment -------------------------------------------------------------
    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        cargo = str(self.opts.get("cargo") or "cargo")
        return host_check(
            [cargo, "metadata", "--offline", "--format-version", "1"],
            Path(root),
            env={"CARGO_TERM_COLOR": "never"},
        )

    def setup(
        self,
        executor: Executor,
        root: Path,
        *,
        env_dir: Path,
        timeout: int,
        on_step: Callable[[SetupStep], None] | None = None,
    ) -> SetupResult:
        refusal = self.sandbox_refusal(executor)
        if refusal is not None:
            return refusal
        root = Path(root)
        session = SetupSession(executor, on_step=on_step)
        if not (root / "Cargo.toml").is_file():
            return session.result(False, "no Cargo.toml: not a cargo package")
        cargo = executor.tool("cargo", self.opts.get("cargo"))
        session.run(
            Command(
                (cargo, "fetch"),
                root,
                env={"CARGO_TERM_COLOR": "never"},
                timeout=self.setup_timeout(timeout),
                network=True,
            )
        )
        return self.finish_setup(session, root, Path(env_dir))

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
