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

Navigation
----------
What it is:   The four JavaScript/TypeScript runners (``node``, ``vitest``, ``jest``, ``mocha``)
              on one base, ``_NodeBase``, that owns ``node_modules`` and dependency eras.
What it does: Builds each tool's machine-readable command (JUnit XML for ``node --test``, JSON
              for the rest), parses failing ids — a suite that failed to load is attributed to
              its file, never "unattributed"; maps a snapshot to the test that owns it;
              installs the clone's ``node_modules`` in setup and a per-lockfile era when a
              task commit's manifest differs; detects eslint/prettier/standard/tsc for belt 5.
How:          ``run``: ``ensure_era`` (hash the worktree's lockfile → install/re-point the
              symlink) → base ``run``. ``parse``: locate the JSON/XML in stdout → walk the
              reporter's result tree → ids. ``setup``: ``npm ci``/``install`` in the clone.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/runners/base.py (the contract), src/crb/core/workspace.py (symlinks
              each worktree's ``node_modules`` to the clone's — what an era re-points),
              src/crb/core/lint.py (``js_plan``), src/crb/core/execution.py (``Executor.tool``),
              src/crb/core/runners/__init__.py (the four registry names)
Tested by:    tests/test_runners_node.py, tests/test_node_eras.py, tests/test_runners_parsers.py,
              tests/test_runners_setup.py
Touch when:   a JavaScript repository needs a different invocation — prefer ``runner_opts``
              (``extra_args``, ``env``, ``npm``/``node``, ``mocha_require``, ``era_keep``,
              ``era_min_free_mb``; docs/OPERATOR.md) over editing; a new reporter shape or a
              fifth test tool means a new subclass, a parser test on canned output and a
              registry entry.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from crb.core.execution import Command, ExecResult, Executor
from crb.core.lint import LintPlan, js_plan
from crb.core.runners.base import (
    BARE,
    READY_CHECK_TIMEOUT_S,
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
    """The first JSON object in ``text`` — reporters print banners and warnings before it."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _list(d: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """``d[key]`` as a list of dicts, tolerating a missing or malformed reporter field."""
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


#: Manifest files in identity order: the first present names the era. npm honours
#: ``yarn.lock`` as a resolution hint, so a yarn repository's era is still keyed and
#: installed from the lockfile the maintainers committed.
_LOCKFILES: tuple[str, ...] = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "package.json",
)


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


#: An era install is refused below this much free space on the env volume: a tree
#: that fills the disk takes the worker, the API and the ledger down with it
#: (2026-09-15). ``runner_opts.era_min_free_mb`` overrides.
ERA_MIN_FREE_MB = 2048
#: Eras kept per repository; the least recently used beyond this are evicted before a
#: new one is installed. ``runner_opts.era_keep`` overrides.
ERA_KEEP = 8


class _NodeBase(BaseRunner):
    """What the four tools share: ``node_modules`` resolution, dependency eras, npm setup,
    the belt 5 plan and the test-time environment. Subclasses add ``command``/``parse``."""

    default_timeout = 420

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        """Test files as the tool addresses them; a ``.snap`` maps to the test that owns it."""
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
        if executor.name == "docker" or self.env_dir is None or self._sealed_nm() is not None:
            return None  # a sealed set (ADR-0019) is the tree: no era is ever installed
        root = Path(root)
        link = root / "node_modules"
        if not link.is_symlink():
            return None  # the worktree owns a real tree (or has none to re-point)
        clone_nm = link.resolve()
        # The link's target sits next to the manifest its tree was installed from (the clone
        # or an earlier era), so hashing that manifest says whether the tree matches.
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
        with contextlib.suppress(OSError):
            os.utime(era)  # most recently used: eviction is LRU
        return era

    def _install_era(self, root: Path, era: Path, executor: Executor) -> None:
        """``npm ci``/``install`` of the worktree's manifest into ``era`` (network on, scripts
        off). Refuses below the free-space floor; a failed install removes the partial tree
        and raises :class:`NodeEraError` so the row reads ``harness``."""
        self._evict_eras(era)
        min_free = int(self.opts.get("era_min_free_mb", ERA_MIN_FREE_MB)) * 1024 * 1024
        era.parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(era.parent).free
        if free < min_free:
            raise NodeEraError(
                f"node era {era.name}: {free // 2**20} MB free on the env volume < "
                f"{min_free // 2**20} MB (era_min_free_mb) — refusing to install"
            )
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
            # A partial tree would read as "installed" next time; remove it so the retry is real.
            shutil.rmtree(era / "node_modules", ignore_errors=True)
            raise NodeEraError(
                f"node era {era.name}: npm {verb} rc={res.returncode}: {tail_of(res.combined)[-400:]}"
            )

    def _evict_eras(self, keep_for: Path) -> None:
        """Drop the least recently used eras beyond ``era_keep`` (never ``keep_for``)."""
        keep = int(self.opts.get("era_keep", ERA_KEEP))
        eras_dir = keep_for.parent
        if not eras_dir.is_dir():
            return
        others = [d for d in eras_dir.iterdir() if d.is_dir() and d != keep_for]
        others.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        for stale in others[max(0, keep - 1) :]:
            shutil.rmtree(stale, ignore_errors=True)

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int = 0
    ) -> TestRun:
        """Base ``run`` once the worktree's ``node_modules`` matches its own lockfile."""
        self.ensure_era(root, executor)
        return super().run(executor, root, scope, timeout=timeout)

    # --- a sealed dependency set (ADR-0019) -------------------------------------
    def _sealed_nm(self) -> Path | None:
        """The bound sealed ``node_modules`` on the host, or ``None``."""
        b = self.deps
        if b is None or not b.sealed:
            return None
        mount = next((m for m in b.mounts if m.container_path == "/work/node_modules"), None)
        return Path(mount.host_path) if mount is not None else None

    def env_probe_command(self, root: Path, executor: Executor) -> Command | None:
        """``npm ls --all --offline``: the tree the lock names is whole in the bound set — or
        the posture cannot run this parent."""
        if self._sealed_nm() is None:
            return None
        npm = executor.tool("npm", self.opts.get("npm"))
        return Command(
            (npm, "ls", "--all", "--offline"),
            Path(root),
            env={**self._env(Path(root), executor), "npm_config_userconfig": "/dev/null"},
            timeout=READY_CHECK_TIMEOUT_S,
        )

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
        """One ``npm ci`` (lockfile committed) or ``npm install`` in the clone; every worktree
        inherits the tree through the workspace's symlink."""
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
        sealed = self._sealed_nm()
        if executor.name == "docker":
            bin_dir = None
        elif sealed is not None:
            bin_dir = sealed / ".bin"
        else:
            bin_dir = Path(root) / "node_modules" / ".bin"
        return js_plan(root, bin_dir)

    def _bin(self, root: Path, executor: Executor, tool: str) -> str:
        """The repo's own ``node_modules/.bin/<tool>`` when present, else the executor's."""
        if executor.name == "docker":
            return tool
        sealed = self._sealed_nm()
        local = (sealed if sealed is not None else root / "node_modules") / ".bin" / tool
        return str(local) if local.exists() else executor.tool(tool)

    def _extra(self) -> list[str]:
        """``runner_opts.extra_args`` — e.g. jest ``--selectProjects`` to exclude a
        browser-driven project from the belt."""
        return [str(a) for a in (self.opts.get("extra_args") or [])]

    def _env(self, root: Path, executor: Executor) -> dict[str, str]:
        """The test command's environment: ``NODE_PATH`` at the resolved tree, ``NODE_ENV=test``,
        then ``runner_opts.env`` on top."""
        sealed = self._sealed_nm()
        if executor.name == "docker":
            nm = "/work/node_modules"
        else:
            nm = str(sealed) if sealed is not None else str(root / "node_modules")
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
        """``node --test`` with the JUnit reporter on stdout (the machine-readable reporter
        every supported node version ships)."""
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
        """Every ``<testcase>`` carrying a ``<failure>`` or ``<error>`` child is a failing id."""
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
    """``vitest run --reporter=json``; coverage off so the JSON is the whole of stdout."""

    name = "vitest"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``vitest run --reporter=json --coverage.enabled=false <extra_args> <scope>``."""
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
        """Failed assertions by ``fullName``; a file whose suite failed with no assertion
        recorded (it did not load) is attributed as ``suite:<file>``."""
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
                # load failure (import/syntax): attributable to the file, same rule as jest
                failing.add(f"suite:{tr.get('name', '')}")
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )


class JestRunner(_NodeBase):
    """``jest --json --ci``; the JSON shape is the one vitest's reporter reproduces."""

    name = "jest"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``jest --json --silent --ci <extra_args> -- <scope>``."""
        jest = self._bin(root, executor, "jest")
        # `--` ends option parsing: without it a variadic option in extra_args
        # (jest --selectProjects A B) swallows the path patterns and EVERY suite runs.
        argv = [jest, "--json", "--silent", "--ci", *self._extra()]
        if scope:
            argv += ["--", *scope]
        return Command(tuple(argv), root, env=self._env(root, executor), timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """Failed assertions by ``fullName`` (jest names the per-file list ``testResults``
        or ``assertionResults`` depending on version); a suite that failed to load is
        attributed as ``suite:<file>``."""
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
    """``mocha --reporter json``; ``runner_opts.mocha_require`` preloads the register hook
    (``ts-node/register``, a babel register) the repository's own test script would."""

    name = "mocha"

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``mocha [--require X] --reporter json --check-leaks <extra_args> <scope>``."""
        mocha = self._bin(root, executor, "mocha")
        argv = [mocha]
        req = self.opts.get("mocha_require")
        if req:
            argv += ["--require", str(req)]
        argv += ["--reporter", "json", "--check-leaks", *self._extra(), *scope]
        return Command(tuple(argv), root, env=self._env(root, executor), timeout=timeout)

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """Every entry of the reporter's ``failures`` list, by ``fullTitle``."""
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
