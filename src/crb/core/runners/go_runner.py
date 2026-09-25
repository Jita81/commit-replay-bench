"""``go test -json`` runner.

Setup is ``go mod download`` (the module cache under ``$GOMODCACHE``; the
host's, since the cache is keyed by module path + version and shared safely).
Ready means ``go list ./...`` resolves with ``GOPROXY=off`` — the exact question
"can the test command build without the network".

Navigation
----------
What it is:   The Go runner — ``GoRunner`` over ``go test -json``.
What it does: Maps test files to their packages (Go addresses packages, not files), runs
              ``go test -json`` with build caching disabled and the toolchain pinned to the
              host's, parses the event stream into ``<package>::<Test>`` ids, warms the module
              cache in setup and detects ``gofmt`` for belt 5.
How:          ``target_scope``: directory of each test file → ``./pkg``. ``command``: env
              (``-count=1``, ``GOTOOLCHAIN=local``, ``CGO_ENABLED``; the caches under ``/tmp``
              and ``Command.exec_tmp`` under docker, because ``go test`` execs the binaries it
              builds there) → ``go test -json``. ``parse``: one JSON event per line;
              ``Action == "fail"`` with a ``Test`` name.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md, docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/runners/base.py (the contract), src/crb/core/lint.py (``go_plan``),
              src/crb/core/execution.py (``Executor.tool``; ``exec_tmp`` on the sandbox's
              tmpfs), src/crb/core/spec.py (``BELT_AFFECTED_DIRS`` is reinterpreted here),
              src/crb/core/runners/__init__.py, deploy/sandbox/Dockerfile.go (the reference
              image this command runs in)
Tested by:    tests/test_runners_go.py, tests/test_runners_parsers.py, tests/test_runners_setup.py,
              tests/test_sandbox_images_docker.py
Touch when:   a Go repository needs cgo, a pinned ``go`` binary or a module cache path —
              set ``runner_opts`` (``cgo``, ``go``, ``gofmt``, ``gomodcache``; docs/OPERATOR.md);
              a change to how packages are addressed needs a parser/scope test.
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

#: ``-mod=mod`` lets go.mod be updated from the cache; ``GOTOOLCHAIN=local`` refuses the
#: silent toolchain download a newer ``go`` directive would otherwise trigger.
_GO_BASE_ENV: dict[str, str] = {"GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"}


class GoRunner(BaseRunner):
    """``RepoConfig.runner == "go"``. Scopes are package patterns (``./calc``), not files."""

    name = "go"
    default_timeout = 600

    # --- environment -------------------------------------------------------------
    def _go(self, executor: Executor) -> str:
        return executor.tool("go", self.opts.get("go"))

    def toolchain_argv(self, executor: Executor) -> tuple[str, ...]:
        """``go version`` — the exact toolchain (``go1.26.8``), part of the posture."""
        return (self._go(executor), "version")

    def env_probe_command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command | None:
        """``go list -deps -test ./...`` offline (``GOPROXY=off``): loads every package the
        tests import, the module graph included, without compiling anything — so a RED that
        is a build failure can be told apart from "this posture cannot load the modules"
        (ADR-0019 §2; the 2026-09-25 finding D1)."""
        env = {"GOFLAGS": "-mod=mod", "GOPROXY": "off", "GOTOOLCHAIN": "local"}
        if executor.name == "docker":
            env["GOCACHE"] = "/tmp/gocache"
            env["GOMODCACHE"] = str(self.opts.get("gomodcache", "/tmp/gomod"))
        pkgs = list(scope) or ["./..."]
        return Command(
            (self._go(executor), "list", "-deps", "-test", *pkgs), root, env=env, timeout=timeout
        )

    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        """``go list ./...`` with ``GOPROXY=off`` — resolves offline or it is not ready."""
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
        """``go mod download`` into the host's shared module cache."""
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
        """The package of each test file (``a/b/x_test.go`` → ``./a/b``; root → ``./``)."""
        pkgs = set()
        for f in test_files:
            d = os.path.dirname(f)
            pkgs.add("./" + d if d else "./")
        return tuple(sorted(pkgs))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
        """As the base rule, except ``affected_dirs`` becomes the target packages."""
        # A bare directory ("calc/") is read by `go test` as an import path, not a
        # package pattern; AFFECTED_DIRS therefore means the target packages themselves.
        if self.config.belt_scope == BELT_AFFECTED_DIRS:
            return self.target_scope(test_files)
        return super().belt_scope(target_tests, test_files)

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``go test -json <packages>``; an empty scope is ``./...`` (bare discovery)."""
        go = self._go(executor)
        pkgs = list(scope) or ["./..."]
        env = {
            # -count=1: never a cached "(cached) ok" — a green must come from this tree.
            "GOFLAGS": "-count=1 -mod=mod",
            "GOTOOLCHAIN": "local",
            "CGO_ENABLED": str(self.opts.get("cgo", "0")),
        }
        writable: tuple[str, ...] = ()
        if executor.name == "docker":
            # The sandbox filesystem is read-only outside /tmp and the writable paths.
            env["GOCACHE"] = "/tmp/gocache"
            env["GOMODCACHE"] = str(self.opts.get("gomodcache", "/tmp/gomod"))
            env["GOFLAGS"] = "-count=1 -mod=mod"
        # go test compiles each package's test binary into its temp dir and execs it:
        # under the sandbox that is the tmpfs /tmp, which must therefore be exec-mountable.
        return Command(
            (go, "test", "-json", *pkgs),
            root,
            env=env,
            timeout=timeout,
            writable_paths=writable,
            exec_tmp=True,
        )

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """``<Package>::<Test>`` for every ``fail`` event that names a test (a package-level
        ``fail`` without a ``Test`` is a build failure — left to the fail-closed rule)."""
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
