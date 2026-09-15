"""``cargo test`` runner (Rust).

Setup is ``cargo fetch`` (the registry cache under ``$CARGO_HOME``); ready is
``cargo metadata --offline`` resolving the full dependency graph without the
network — the same resolution ``cargo test --offline`` performs first.

Navigation
----------
What it is:   The Rust runner — ``CargoRunner`` over ``cargo test``.
What it does: Maps ``tests/<name>.rs`` (or ``tests/<name>/…``) to the integration-test binary
              ``--test <name>`` (anything else means the whole crate), runs ``cargo test
              --no-fail-fast --offline`` so a failing binary does not truncate belt 3, parses
              both harness output formats for ``FAILED`` lines, fetches the registry in setup
              and detects rustfmt/clippy for belt 5.
How:          ``target_scope``: path → binary stem or ``ALL``. ``command``: ``--test`` per stem
              with the target dir pinned. ``parse``: regex over combined output.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/runners/base.py (the contract), src/crb/core/lint.py (``rust_plan``),
              src/crb/core/execution.py (``Executor.tool``; ``target/`` writable under docker),
              src/crb/core/runners/__init__.py
Tested by:    tests/test_runners_cargo.py, tests/test_runners_parsers.py,
              tests/test_runners_setup.py
Touch when:   a Rust repository needs a pinned ``cargo``, a registry home or online resolution —
              set ``runner_opts`` (``cargo``, ``cargo_home``, ``offline``; docs/OPERATOR.md);
              a workspace with several crates needs a scope-mapping test before changing
              ``target_scope``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.lint import LintPlan, rust_plan
from crb.core.runners.base import (
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    TestRun,
    host_check,
    tail_of,
)

#: Both harness formats: verbose ``test name ... FAILED`` and quiet ``name --- FAILED``.
_FAILED = re.compile(r"^(?:test )?(\S+) (?:\.\.\.|---) FAILED$", re.M)


class CargoRunner(BaseRunner):
    """``RepoConfig.runner == "cargo"``. Scopes are integration-test binary names (or ``ALL``)."""

    name = "cargo"
    default_timeout = 1200

    # --- environment -------------------------------------------------------------
    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        """``cargo metadata --offline`` resolves the whole graph, or it is not ready."""
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
        """``cargo fetch`` into the host's ``$CARGO_HOME`` registry cache."""
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

    # --- belt 5 -------------------------------------------------------------------
    def _lint_env(self, root: Path, executor: Executor) -> dict[str, str]:
        """The same target-dir/registry pinning ``command`` uses, for the belt 5 tools."""
        env = {
            "CARGO_TARGET_DIR": "/work/target"
            if executor.name == "docker"
            else str(Path(root) / "target"),
            "CARGO_TERM_COLOR": "never",
        }
        if executor.name == "docker":
            env["CARGO_HOME"] = str(self.opts.get("cargo_home", "/tmp/cargo"))
        return env

    def detect_lint(self, root: Path, executor: Executor) -> LintPlan | None:
        """``cargo fmt --check`` / ``cargo clippy -- -D warnings`` (crate-wide,
        offline) when the repository configures them — clap: ``.clippy.toml`` and the
        ``rustfmt`` / ``clippy`` jobs of ``ci.yml``."""
        cargo = executor.tool("cargo", self.opts.get("cargo"))
        return rust_plan(root, cargo, self._lint_env(root, executor))

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        """Integration-test binary stems; a unit test inside ``src/`` cannot be addressed
        alone, so it widens the scope to ``ALL`` (the whole crate)."""
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
        """``cargo test --no-fail-fast --offline [--test <stem>…]``; ``ALL`` adds no filter."""
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
        """Every ``FAILED`` line of either harness format, by test path."""
        failing = frozenset(m.strip() for m in _FAILED.findall(result.combined))
        return TestRun(
            result.returncode, failing, tail_of(result.combined), duration_s=result.duration_s
        )
