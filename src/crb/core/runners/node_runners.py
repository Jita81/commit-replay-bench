"""JavaScript / TypeScript runners: ``node --test``, vitest, jest, mocha.

All four resolve tools from the repo's ``node_modules/.bin`` (or the image's
PATH under docker). The worktree needs a resolvable ``node_modules``; the
workspace layer symlinks the main clone's (local) or the image ships it (docker).

Setup therefore installs into the *clone* (``npm ci`` when a lockfile is
committed, ``npm install`` otherwise) and every worktree inherits it through
that symlink — **while its lockfile matches the clone's**. A task commit whose
``package-lock.json`` differs (nhsuk-react-components: the commit's eslint config
needs ``@eslint/compat``, absent from HEAD's tree — belt 5 ``rc=2``, 2026-09-15)
gets a **dependency era**: ``<env_dir>/node_eras/<lock hash>/node_modules``,
installed once from that commit's manifest and re-pointed for every worktree
sharing the lockfile. A failed era install is a harness error (the row is
``harness``, outside ``n``), never a silent fall-back to HEAD's tree.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from crb.core.execution import Command, ExecResult, Executor
from crb.core.lint import LintPlan, js_plan
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


def snapshot_to_test(path: str) -> str:
    """``a/__tests__/__snapshots__/X.test.tsx.snap`` → ``a/__tests__/X.test.tsx``.

    A commit that only updates a snapshot still has an executable oracle — the
    test that owns the snapshot — so the target scope names the test, not the
    ``.snap`` (which jest/vitest would not match as a test path)."""
    if path.endswith(".snap") and "__snapshots__/" in path:
        head, _, tail = path.rpartition("__snapshots__/")
        return head + tail[: -len(".snap")]
    return path


_LOCKFILES: tuple[str, ...] = ("package-lock.json", "npm-shrinkwrap.json", "package.json")


def lock_key(root: Path) -> str | None:
    """Identity of a tree's dependency manifest: the hash of its lockfile (else
    ``package.json``) — two trees with the same key resolve the same ``node_modules``."""
    for name in _LOCKFILES:
        p = Path(root) / name
        if p.is_file():
            return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return None


class NodeEraError(RuntimeError):
    """A dependency era could not be installed: a harness error, never a verdict."""


class _NodeBase(BaseRunner):
    default_timeout = 420

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted({snapshot_to_test(f) for f in test_files}))

    # --- dependency eras -----------------------------------------------------------
    def ensure_era(self, root: Path, executor: Executor) -> Path | None:
        """Point the worktree's ``node_modules`` at a tree that matches ITS lockfile.

        The workspace links every worktree to the clone's ``node_modules``. When the
        worktree's lockfile hashes differently, the era ``<env_dir>/node_eras/<key>``
        is installed once (``npm ci`` from that manifest, network on, like setup) and
        the link is re-pointed. Returns the era root used, ``None`` when the clone's
        tree already matches (or under docker, where the image ships the tree).
        """
        if executor.name == "docker" or self.env_dir is None:
            return None
        root = Path(root)
        link = root / "node_modules"
        if not link.is_symlink():
            return None  # the worktree owns a real tree (or has none to re-point)
        clone_nm = link.resolve()
        key, clone_key = lock_key(root), lock_key(clone_nm.parent)
        if key is None or key == clone_key:
            return None
        era = self.env_dir / "node_eras" / key
        era_nm = era / "node_modules"
        if not (era_nm / ".bin").is_dir():
            self._install_era(root, era, executor)
        if link.resolve() != era_nm.resolve():
            link.unlink()
            link.symlink_to(era_nm)
        return era

    def _install_era(self, root: Path, era: Path, executor: Executor) -> None:
        era.mkdir(parents=True, exist_ok=True)
        for name in (*_LOCKFILES, ".npmrc"):
            src = root / name
            if src.is_file():
                shutil.copyfile(src, era / name)
        npm = executor.tool("npm", self.opts.get("npm"))
        verb = "ci" if (era / "package-lock.json").is_file() else "install"
        env = {"NODE_ENV": "development", "npm_config_update_notifier": "false"}
        env.update({str(k): str(v) for k, v in dict(self.opts.get("env", {})).items()})
        # scripts off: an era is a dependency tree, not a build (husky/prepare hooks
        # expect the repository checkout around them)
        cmd = Command(
            (npm, verb, *_NPM_FLAGS, "--ignore-scripts"),
            era,
            env=env,
            timeout=self.setup_timeout(0),
            writable_paths=("node_modules",),
            network=True,
        )
        try:
            res = executor.run(cmd)
        except OSError as exc:
            raise NodeEraError(f"node era {era.name}: {type(exc).__name__}: {exc}") from exc
        if res.returncode != 0 or not (era / "node_modules" / ".bin").is_dir():
            shutil.rmtree(era / "node_modules", ignore_errors=True)
            raise NodeEraError(
                f"node era {era.name}: npm {verb} rc={res.returncode}: {tail_of(res.combined)[-400:]}"
            )

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int = 0
    ) -> TestRun:
        self.ensure_era(root, executor)
        return super().run(executor, root, scope, timeout=timeout)

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
        # runner_opts.env (e.g. a PATH that puts the repo's required node@24 first) applies to
        # setup too — `npm` is a node script, so an engine-strict repo fails otherwise.
        env = {"NODE_ENV": "development", "npm_config_update_notifier": "false"}
        env.update({str(k): str(v) for k, v in dict(self.opts.get("env", {})).items()})
        session.run(
            Command(
                (npm, verb, *_NPM_FLAGS),
                root,
                env=env,
                timeout=self.setup_timeout(timeout),
                writable_paths=("node_modules",),
                network=True,
            )
        )
        return self.finish_setup(session, root, Path(env_dir))

    # --- belt 5 -------------------------------------------------------------------
    def detect_lint(self, root: Path, executor: Executor) -> LintPlan | None:
        """``eslint`` then ``prettier --check`` when configured, else ``standard``
        when ``scripts.lint`` names it (koa: ``"lint": "standard"``, CI ``npm run
        lint``); then ``tsc`` when the repository gates on the type checker
        (``tsconfig.json`` + ``scripts["lint:types"]`` / a ``tsc`` script / CI —
        nhsuk-frontend, nhsuk-react-components; ADR-0011 amendment 2026-09-14), whole-
        project with the rejection attributed to the changed files. Tools resolve from
        ``node_modules/.bin`` (the image's PATH under docker); a binary without its
        config is not evidence."""
        self.ensure_era(root, executor)
        bin_dir = None if executor.name == "docker" else Path(root) / "node_modules" / ".bin"
        return js_plan(root, bin_dir)

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
            had_assertion_failure = False
            for a in _list(tr, "assertionResults"):
                if a.get("status") == "failed":
                    had_assertion_failure = True
                    failing.add(str(a.get("fullName") or a.get("title") or ""))
            if tr.get("status") == "failed" and not had_assertion_failure:
                failing.add(f"suite:{tr.get('name', '')}")
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
        # `--` ends option parsing: without it a variadic option in extra_args
        # (jest --selectProjects A B) swallows the path patterns and EVERY suite runs.
        argv = [jest, "--json", "--silent", "--ci", *self._extra()]
        if scope:
            argv += ["--", *scope]
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
            had_assertion_failure = False
            for a in _list(tr, "testResults") or _list(tr, "assertionResults"):
                if a.get("status") == "failed":
                    had_assertion_failure = True
                    failing.add(str(a.get("fullName") or a.get("title") or ""))
            if tr.get("status") == "failed" and not had_assertion_failure:
                # a suite that failed to LOAD (import/syntax error) is a failure attributable
                # to the file — never an "unattributed" rc≠0 (measured on nhsuk-frontend)
                failing.add(f"suite:{tr.get('name', '')}")
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
