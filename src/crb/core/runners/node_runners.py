"""JavaScript / TypeScript runners: ``node --test``, vitest, jest, mocha.

All four resolve tools from the repo's ``node_modules/.bin`` (or the image's
PATH under docker). The worktree needs a resolvable ``node_modules``; the
workspace layer symlinks the main clone's (local) or the image ships it (docker).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import BARE, BaseRunner, TestRun, tail_of


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

    def _bin(self, root: Path, executor: Executor, tool: str) -> str:
        if executor.name == "docker":
            return tool
        local = root / "node_modules" / ".bin" / tool
        return str(local) if local.exists() else executor.tool(tool)

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
        argv = [vitest, "run", "--reporter=json", "--coverage.enabled=false", *scope]
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
        argv = [jest, "--json", "--silent", "--ci", *scope]
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
        argv += ["--reporter", "json", "--check-leaks", *scope]
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
