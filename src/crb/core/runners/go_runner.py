"""``go test -json`` runner."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import BaseRunner, TestRun, tail_of


class GoRunner(BaseRunner):
    name = "go"
    default_timeout = 600

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        pkgs = set()
        for f in test_files:
            d = os.path.dirname(f)
            pkgs.add("./" + d if d else "./")
        return tuple(sorted(pkgs))

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        go = executor.tool("go", self.opts.get("go"))
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
