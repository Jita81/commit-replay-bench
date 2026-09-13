"""JavaScript / TypeScript runners: ``node --test``, vitest, jest, mocha.

All four resolve tools from the repo's ``node_modules/.bin`` (or the image's
PATH under docker). The worktree needs a resolvable ``node_modules``; the
workspace layer symlinks the main clone's (local) or the image ships it (docker).

Setup therefore installs into the *clone* (``npm ci`` when a lockfile is
committed, ``npm install`` otherwise) and every worktree inherits it through
that symlink. ``env_dir`` is unused: ``node_modules`` has to sit next to
``package.json`` for Node's resolver to find it.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import (
    BARE,
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    TestRun,
    tail_of,
)

_NPM_FLAGS: tuple[str, ...] = ("--no-audit", "--no-fund", "--loglevel=error")


def declares_dependencies(root: Path) -> bool:
    """Whether ``package.json`` names anything to install."""
    try:
        data = json.loads((Path(root) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return any(
        isinstance(data.get(k), dict) and data[k]
        for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
    )


def _json_after_first_brace(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _list(d: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    v = d.get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


class _NodeBase(BaseRunner):
    default_timeout = 420

    # --- environment -------------------------------------------------------------
    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        """``node_modules/.bin`` exists — or ``package.json`` declares nothing to
        install (a dependency-free ``node --test`` repo is ready as it stands)."""
        nm = Path(root) / "node_modules"
        if (nm / ".bin").is_dir():
            return True
        return (Path(root) / "package.json").is_file() and not declares_dependencies(root)

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
        if not (root / "package.json").is_file():
            return session.result(False, "no package.json: nothing npm could install")
        npm = executor.tool("npm", self.opts.get("npm"))
        verb = "ci" if (root / "package-lock.json").is_file() else "install"
        session.run(
            Command(
                (npm, verb, *_NPM_FLAGS),
                root,
                env={"NODE_ENV": "development", "npm_config_update_notifier": "false"},
                timeout=self.setup_timeout(timeout),
                writable_paths=("node_modules",),
                network=True,
            )
        )
        return self.finish_setup(session, root, Path(env_dir))

    def _bin(self, root: Path, executor: Executor, tool: str) -> str:
        if executor.name == "docker":
            return tool
        local = root / "node_modules" / ".bin" / tool
        return str(local) if local.exists() else executor.tool(tool)

    def _extra(self) -> list[str]:
        """``runner_opts.extra_args`` — e.g. jest ``--selectProjects`` to exclude a
        browser-driven project from the belt."""
        return [str(a) for a in (self.opts.get("extra_args") or [])]

    def _env(self, root: Path, executor: Executor) -> dict[str, str]:
        nm = "/work/node_modules" if executor.name == "docker" else str(root / "node_modules")
        env = {"NODE_PATH": nm, "NODE_ENV": "test"}
        for k, v in dict(self.opts.get("env", {})).items():
            env[str(k)] = str(v)
        return env


class NodeTestRunner(_NodeBase):
    """``node --test`` with the JUnit reporter."""

    name = "node"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        node = executor.tool("node", self.opts.get("node"))
        paths = [] if tuple(scope) == BARE else list(scope)
        argv = [
            node,
            "--test",
            "--test-reporter=junit",
            "--test-reporter-destination=stdout",
            *paths,
        ]
        return Command(tuple(argv), root, env=self._env(root, executor), timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        failing: set[str] = set()
        try:
            xml_root = ET.fromstring(result.stdout or "<testsuites/>")  # noqa: S314 — our own reporter output
        except ET.ParseError:
            return TestRun(
                result.returncode or 1,
                frozenset(),
                tail_of(result.combined),
                duration_s=result.duration_s,
                parse_error="junit parse error",
            )
        for tc in xml_root.iter("testcase"):
            if any(ch.tag in ("failure", "error") for ch in tc):
                failing.add(tc.get("name") or "")
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )


class VitestRunner(_NodeBase):
    name = "vitest"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        vitest = self._bin(root, executor, "vitest")
        argv = [
            vitest,
            "run",
            "--reporter=json",
            "--coverage.enabled=false",
            *self._extra(),
            *scope,
        ]
        return Command(tuple(argv), root, env=self._env(root, executor), timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        data = _json_after_first_brace(result.stdout)
        if data is None:
            return TestRun(
                result.returncode or 1,
                frozenset(),
                tail_of(result.combined),
                duration_s=result.duration_s,
                parse_error="vitest json missing",
            )
        failing: set[str] = set()
        for tr in _list(data, "testResults"):
            for a in _list(tr, "assertionResults"):
                if a.get("status") == "failed":
                    failing.add(str(a.get("fullName") or a.get("title") or ""))
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )


class JestRunner(_NodeBase):
    name = "jest"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        jest = self._bin(root, executor, "jest")
        argv = [jest, "--json", "--silent", "--ci", *self._extra(), *scope]
        return Command(tuple(argv), root, env=self._env(root, executor), timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        data = _json_after_first_brace(result.stdout)
        if data is None:
            return TestRun(
                result.returncode or 1,
                frozenset(),
                tail_of(result.combined),
                duration_s=result.duration_s,
                parse_error="jest json missing",
            )
        failing: set[str] = set()
        for tr in _list(data, "testResults"):
            for a in _list(tr, "testResults") or _list(tr, "assertionResults"):
                if a.get("status") == "failed":
                    failing.add(str(a.get("fullName") or a.get("title") or ""))
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )


class MochaRunner(_NodeBase):
    name = "mocha"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        mocha = self._bin(root, executor, "mocha")
        argv = [mocha]
        req = self.opts.get("mocha_require")
        if req:
            argv += ["--require", str(req)]
        argv += ["--reporter", "json", "--check-leaks", *self._extra(), *scope]
        return Command(tuple(argv), root, env=self._env(root, executor), timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        data = _json_after_first_brace(result.stdout)
        if data is None:
            return TestRun(
                result.returncode or 1,
                frozenset(),
                tail_of(result.combined),
                duration_s=result.duration_s,
                parse_error="mocha json missing",
            )
        failing = {
            str(f.get("fullTitle") or f.get("title") or "").strip() for f in _list(data, "failures")
        }
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )
