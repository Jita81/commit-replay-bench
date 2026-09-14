"""``go test -json`` runner.

Setup is ``go mod download`` (the module cache under ``$GOMODCACHE``; the
host's, since the cache is keyed by module path + version and shared safely).
Ready means ``go list ./...`` resolves with ``GOPROXY=off`` — the exact question
"can the test command build without the network".
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.lint import LintPlan, go_plan
from crb.core.runners.base import (
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    TestRun,
    host_check,
    tail_of,
)
from crb.core.spec import BELT_AFFECTED_DIRS

_GO_BASE_ENV: dict[str, str] = {"GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"}


class GoRunner(BaseRunner):
    name = "go"
    default_timeout = 600

    # --- environment -------------------------------------------------------------
    def _go(self, executor: Executor) -> str:
        return executor.tool("go", self.opts.get("go"))

    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        go = str(self.opts.get("go") or "go")
        return host_check([go, "list", "./..."], Path(root), env={**_GO_BASE_ENV, "GOPROXY": "off"})

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
        if not (root / "go.mod").is_file():
            return session.result(False, "no go.mod: not a Go module")
        session.run(
            Command(
                (self._go(executor), "mod", "download"),
                root,
                env=dict(_GO_BASE_ENV),
                timeout=self.setup_timeout(timeout),
                network=True,
            )
        )
        return self.finish_setup(session, root, Path(env_dir))

    # --- belt 5 -------------------------------------------------------------------
    def detect_lint(self, root: Path, executor: Executor) -> LintPlan | None:
        """``gofmt -l`` — shipped with every Go toolchain and enabled by cobra's
        ``.golangci.yml`` (``formatters: gofmt``) and ``Makefile fmt``."""
        return go_plan(root, executor.tool("gofmt", self.opts.get("gofmt")))

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        pkgs = set()
        for f in test_files:
            d = os.path.dirname(f)
            pkgs.add("./" + d if d else "./")
        return tuple(sorted(pkgs))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
        # A bare directory ("calc/") is read by `go test` as an import path, not a
        # package pattern; AFFECTED_DIRS therefore means the target packages themselves.
        if self.config.belt_scope == BELT_AFFECTED_DIRS:
            return self.target_scope(test_files)
        return super().belt_scope(target_tests, test_files)

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        go = self._go(executor)
        pkgs = list(scope) or ["./..."]
        env = {
            "GOFLAGS": "-count=1 -mod=mod",
            "GOTOOLCHAIN": "local",
            "CGO_ENABLED": str(self.opts.get("cgo", "0")),
        }
        writable: tuple[str, ...] = ()
        if executor.name == "docker":
            env["GOCACHE"] = "/tmp/gocache"
            env["GOMODCACHE"] = str(self.opts.get("gomodcache", "/tmp/gomod"))
            env["GOFLAGS"] = "-count=1 -mod=mod"
        return Command(
            (go, "test", "-json", *pkgs), root, env=env, timeout=timeout, writable_paths=writable
        )

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        failing = set()
        for line in result.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("Action") == "fail" and ev.get("Test"):
                failing.add(f"{ev.get('Package', '')}::{ev['Test']}")
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )
