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
              host's, parses the event stream into ``<package>::<Test>`` ids (a package that
              fails naming no test, a test that started and never finished, a package that
              passed without its binary's ``PASS`` are unattributed, never dropped), builds
              the whole module after a narrower belt (the module build gate), declares the
              tools a test may run on the host with ``GOENV=off`` (ADR-0048), warms the module
              cache in setup and detects ``gofmt`` for belt 5.
How:          ``target_scope``: directory of each test file → ``./pkg``. ``command``: env
              (``-count=1``, ``GOTOOLCHAIN=local``, ``CGO_ENABLED``; the caches under ``/tmp``
              and ``Command.exec_tmp`` under docker, because ``go test`` execs the binaries it
              builds there) → ``go test -json``. ``parse``: one JSON event per line;
              ``Action == "fail"`` with a ``Test`` name; a package's own ``fail`` beside named
              ones, a ``run`` with no terminal event and a package ``pass`` with no ``PASS``
              line are a ``parse_error``. ``gate_run``: ``-run ^$ -vet=off ./...``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md, docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0048-the-host-posture-declares-its-environment.md
Works with:   src/crb/core/runners/base.py (the contract), src/crb/core/lint.py (``go_plan``),
              src/crb/core/execution.py (``Executor.tool``; ``exec_tmp`` on the sandbox's
              tmpfs), src/crb/core/spec.py (``BELT_AFFECTED_DIRS`` is reinterpreted here),
              src/crb/core/runners/__init__.py, deploy/sandbox/Dockerfile.go (the reference
              image this command runs in)
Tested by:    tests/test_runners_go.py, tests/test_runners_parsers.py, tests/test_runners_setup.py,
              tests/test_sandbox_images_docker.py, tests/test_runners_go_baseline.py,
              tests/test_runners_toolenv.py, tests/test_runners_early_exit.py
Touch when:   a Go repository needs cgo, a pinned ``go`` binary, a module cache path or a host
              tool its tests run — set ``runner_opts`` (``cgo``, ``go``, ``gofmt``,
              ``gomodcache``, ``tools``; docs/OPERATOR.md);
              a change to how packages are addressed needs a parser/scope test.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from crb.core.deps import DepsBinding
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
from crb.core.runners.toolenv import POSIX_BASICS, ToolSpec
from crb.core.spec import BELT_AFFECTED_DIRS

#: What cgo needs on top when ``runner_opts.cgo`` is on (the C toolchain the build calls).
_CGO_TOOLS: tuple[str, ...] = ("cc", "gcc", "clang", "ld", "ar", "pkg-config")

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

    def declared_tools(self, executor: Executor, root: Path | None = None) -> tuple[ToolSpec, ...]:
        """What a Go test may run by name on the host (ADR-0048): the ``go`` the command
        runs, ``gofmt``, ``git`` and the POSIX basics the sealed image carries — plus the C
        toolchain when cgo is on. A tool that is merely installed (``shellcheck``) is not
        on the list, so it can never change a verdict."""
        go = self._go(executor)
        gofmt = self.opts.get("gofmt")
        tools = [
            ToolSpec("go", go if os.path.isabs(go) else None, ("version",)),
            ToolSpec("gofmt", str(gofmt) if gofmt else None),
            ToolSpec("git", None, ("--version",)),
            *(ToolSpec(name) for name in POSIX_BASICS),
        ]
        if str(self.opts.get("cgo", "0")) == "1":
            tools += [ToolSpec(name) for name in _CGO_TOOLS]
        return tuple(tools)

    def declared_fixed_env(self) -> dict[str, str]:
        """``GOENV=off``: no go env file (``go env -w``, under ``$HOME``) is read, so a host's
        ``GOARCH`` or ``GOEXPERIMENT`` there never changes a result; the settings a
        deployment needs arrive as passthrough names, hashed by value."""
        return {"GOENV": "off"}

    def env_passthrough(self) -> tuple[str, ...]:
        """The module and build caches (and ``GOPATH``) the host environment points at, and
        how modules resolve there (``GOPROXY=off`` makes a warm cache the only source);
        the resolution settings' values are part of the digest."""
        return (
            "GOPATH",
            "GOCACHE",
            "GOMODCACHE",
            "GOPROXY",
            "GOSUMDB",
            "GONOSUMDB",
            "GOPRIVATE",
            "GONOPROXY",
            "GOINSECURE",
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

    #: True while :meth:`gate_run` builds the command: compile every package, run no test.
    _compile_only: bool = False

    def module_gate_scope(self, scope: Sequence[str]) -> tuple[str, ...] | None:
        """``./...`` unless the belt scope already is the whole module (empty or ``./...``):
        a target-only belt (the pilot's cobra shape) otherwise never sees a package that a
        patch stopped compiling outside it — ``./doc`` imports cobra's root package."""
        if not scope or "./..." in scope:
            return None
        return ("./...",)

    def gate_run(
        self,
        executor: Executor,
        root: Path,
        scope: Sequence[str],
        *,
        timeout: int = 0,
        authored: str | None,
        deps: DepsBinding | None = None,
    ) -> TestRun:
        """``go test -json -run ^$ -vet=off <scope>``: every package and its tests compiled
        and linked, offline as the belt run is, and no test run. A package that fails to
        build (or whose binary fails with no test run) makes the run unattributed."""
        self._compile_only = True
        try:
            return self.run_for(
                executor, root, scope, timeout=timeout, authored=authored, deps=deps
            )
        finally:
            self._compile_only = False

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``go test -json <packages>``; an empty scope is ``./...`` (bare discovery). With a
        sealed set bound (ADR-0019) the module cache is that set, read-only and offline
        (``GOPROXY=off``); without one the command is exactly what it always was. Under
        :meth:`gate_run`, ``-run ^$ -vet=off``: build only."""
        go = self._go(executor)
        pkgs = list(scope) or ["./..."]
        env = self._env(executor)
        gate = ("-run", "^$", "-vet=off") if self._compile_only else ()
        # go test compiles each package's test binary into its temp dir and execs it:
        # under the sandbox that is the tmpfs /tmp, which must therefore be exec-mountable.
        cmd = Command(
            (go, "test", "-json", *gate, *pkgs),
            root,
            env=env,
            timeout=timeout,
            writable_paths=(),
            exec_tmp=True,
        )
        return self.bind_deps(cmd, executor)

    def _env(self, executor: Executor) -> dict[str, str]:
        env = {
            # -count=1: never a cached "(cached) ok" — a green must come from this tree.
            "GOFLAGS": "-count=1 -mod=mod",
            "GOTOOLCHAIN": "local",
            "CGO_ENABLED": str(self.opts.get("cgo", "0")),
        }
        if executor.name == "docker":
            # The sandbox filesystem is read-only outside /tmp and the writable paths.
            env["GOCACHE"] = "/tmp/gocache"
            if self.deps is None or not self.deps.sealed:
                env["GOMODCACHE"] = str(self.opts.get("gomodcache", "/tmp/gomod"))
        return env

    def env_probe_command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command | None:
        """``go list -deps -test <packages>`` offline (``GOPROXY=off``; an empty scope is
        ``./...``): loads every package the tests import, the module graph included, from
        the bound set (ADR-0019) without compiling anything — so a RED that is a build
        failure can be told apart from "this posture cannot load the modules"
        (``QUAL_ENV_UNLOADABLE``; the 2026-09-25 finding D1)."""
        env = {**self._env(executor), "GOPROXY": "off"}
        pkgs = list(scope) or ["./..."]
        cmd = Command(
            (self._go(executor), "list", "-deps", "-test", *pkgs),
            Path(root),
            env=env,
            timeout=timeout,
            exec_tmp=True,
        )
        return self.bind_deps(cmd, executor)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """``<Package>::<Test>`` for every ``fail`` event that names a test. Three shapes are
        UNATTRIBUTED (a ``parse_error``), so none can hide behind ids the baseline subtracts
        or read as green (pilot finding D6, stream Q2's verifiers; ADR-0048):

        * a package whose ``fail`` names no test of its own (a build or vet failure, a crash
          outside a test) beside named failures — with nothing named, the base's fail-closed
          rule applies;
        * a test with a ``run`` event and no ``pass``, ``fail`` or ``skip``: its binary died
          during it (``os.Exit``, a background goroutine's panic) and the tests after it never
          ran — the test is named failing too;
        * a package with named failures whose binary never printed its own ``FAIL`` line: it
          died after a failure it reported (a test that panics), so later tests never ran;
        * a package that ``pass``-ed without its binary's own ``PASS`` line: the binary ended
          before its tests reported (an ``init`` that calls ``os.Exit(0)``)."""
        failing: set[str] = set()
        failed_pkgs: set[str] = set()
        named_pkgs: set[str] = set()
        started: dict[tuple[str, str], None] = {}
        summarized: set[str] = set()
        passed_pkgs: list[str] = []
        for line in result.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            action = ev.get("Action")
            pkg = str(ev.get("Package", ""))
            test = ev.get("Test")
            if test:
                if action == "run":
                    started[(pkg, str(test))] = None
                elif action in ("pass", "fail", "skip"):
                    started.pop((pkg, str(test)), None)
                if action == "fail":
                    failing.add(f"{pkg}::{test}")
                    named_pkgs.add(pkg)
                continue
            if action == "output" and ev.get("Output") in ("PASS\n", "FAIL\n"):
                summarized.add(pkg)
            elif action == "fail" and pkg:
                failed_pkgs.add(pkg)
            elif action == "pass" and pkg:
                passed_pkgs.append(pkg)
        problems: list[str] = []
        unnamed = sorted(failed_pkgs - named_pkgs)
        if failing and unnamed:
            shown = ", ".join(unnamed[:5]) + (
                f" and {len(unnamed) - 5} more" if len(unnamed) > 5 else ""
            )
            problems.append(
                f"package{'s' if len(unnamed) > 1 else ''} {shown} failed without naming a test"
            )
        died_in: set[str] = set()
        for pkg, test in started:
            failing.add(f"{pkg}::{test}")
            died_in.add(pkg)
            problems.append(f"package {pkg} exited during {test}; later tests never ran")
        for pkg in sorted(named_pkgs - summarized - died_in):
            problems.append(
                f"package {pkg}'s test binary ended without its own summary (a panic or an "
                "exit after a failure): later tests never ran"
            )
        for pkg in sorted(set(passed_pkgs) - summarized):
            problems.append(
                f"package {pkg} passed without its test binary reporting PASS: it exited "
                "before its tests ran"
            )
        parse_error = ""
        if problems:
            shown_problems = "; ".join(problems[:5]) + (
                f"; and {len(problems) - 5} more" if len(problems) > 5 else ""
            )
            parse_error = f"unattributed failure ({shown_problems})"
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
            parse_error=parse_error,
        )
