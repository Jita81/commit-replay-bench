"""The one runner contract every language honours.

A runner turns a *scope* (test files, packages, classes, or test binaries —
whatever the toolchain addresses) into a :class:`~crb.core.execution.Command`,
hands it to an executor, and parses the output into a :class:`TestRun`:

    (returncode, failing_test_ids, tail, timed_out)

Two scopes matter to the grader:

* the **target scope** — the commit's own test files, mapped to what the
  toolchain can address (belt 2: target green);
* the **belt scope** — the regression surface (belt 3: no new failures),
  resolved from the repo's ``belt_scope`` policy.

Runners never decide verdicts. They report what the toolchain said.

Environment setup
-----------------
Before a repository can be probed its test dependencies must exist somewhere the
runner can reach: a virtualenv, ``node_modules``, a warm module cache. That is
the **one network-permitted phase** of the whole instrument, and it is explicit:
:meth:`BaseRunner.setup` runs it (every command is ``Command(..., network=True)``
so a sandboxing executor can tell it apart), records every step as a
:class:`SetupStep` with a redacted tail, and :meth:`BaseRunner.environment_ready`
answers — without network — whether the environment is usable now. Setup is a
*host* phase: a sandbox image must ship its own toolchain and dependencies, so
under a docker executor ``setup`` refuses rather than pretending.

Services the oracle needs
-------------------------
Some suites are only an oracle next to a running service (mesh-client's MESH
sandbox on ``localhost:8701``). ``runner_opts.services`` declares them
(:mod:`crb.core.services`); the runner owns one :class:`~crb.core.services.ServiceSession`
per repository: :meth:`BaseRunner.setup` stages every era's fixtures and starts
the services once (recorded in the :class:`SetupResult`), :meth:`BaseRunner.run`
makes sure the variant the task's authored date selects is healthy — reusing the
running one — merges the session's exported environment into the test command,
and stamps the :class:`TestRun` with which service version answered. A service
that cannot be provided is :class:`~crb.core.services.ServiceUnavailable`: the
run stops, nothing is graded against a missing oracle.

Navigation
----------
What it is:   The runner contract (``TestRunner`` protocol, ``BaseRunner`` plumbing) and the
              records every language runner returns: ``TestRun``, ``SetupStep``, ``SetupResult``.
What it does: Resolves target and belt scopes from the repo config; runs one scope through an
              executor and fails closed when a non-zero exit carries no attributable test id;
              runs the one network-permitted setup phase on the host (refused under docker) and
              keeps its redacted record; starts and stamps the oracle's services. It never
              decides a verdict — it reports what the toolchain said.
How:          ``run``: services for the task's era → ``command`` → execute → ``parse`` →
              ``parse_error`` when rc≠0 and nothing parsed. ``setup``: a ``SetupSession``
              records each ``network=True`` step → ``finish_setup`` checks the last step,
              ``environment_ready`` and the services.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/runners/pytest_runner.py (the reference subclass),
              src/crb/core/execution.py (the ``Command``/``Executor`` it drives),
              src/crb/core/services.py (the oracle's services and era selection),
              src/crb/core/grade.py (consumes ``TestRun`` for belts 2 and 3),
              src/crb/core/lint.py (belt 5 plans), src/crb/core/spec.py (``RepoConfig.belt_scope``
              and ``runner_opts``), src/crb/core/runners/__init__.py (the registry)
Tested by:    tests/test_runners_parsers.py, tests/test_runners_setup.py, tests/test_services.py
Touch when:   never for a new repository — set ``runner``, ``belt_scope``, ``runner_opts`` and
              ``lint`` in the repo config instead (docs/OPERATOR.md); adding a language means a
              new subclass registered in src/crb/core/runners/__init__.py; changing ``TestRun``
              or the fail-closed rule needs an ADR and an apparatus bump
              (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from crb.core.deps import DepsBinding
from crb.core.execution import Command, ExecResult, Executor, LocalExecutor
from crb.core.lint import LintPlan, lint_disabled, plan_from_config
from crb.core.redact import redact_and_cap
from crb.core.services import (
    SERVICES_SANDBOX_REFUSED,
    ServiceRecord,
    ServiceSession,
    ServiceSpec,
    ServiceUnavailable,
    authored_of,
    clone_root_of,
    parse_services,
)
from crb.core.spec import BELT_AFFECTED_DIRS, BELT_BARE, BELT_TARGET_ONLY, RepoConfig

#: Sentinel: "run the toolchain's default discovery" (the census ``BARE`` scope).
BARE: tuple[str, ...] = ()

#: Cap on the raw output tail we keep (evidence packs are redacted + capped).
TAIL_LINES = 40

#: Per-step wall clock for dependency installation when the caller passes none.
DEFAULT_SETUP_TIMEOUT_S = 1800

#: Wall clock for the cheap, offline "is the environment ready?" probes.
READY_CHECK_TIMEOUT_S = 300

#: Cap on the redacted tail one setup step keeps.
SETUP_TAIL_CHARS = 4000

SETUP_NOTHING = "nothing to set up"
SETUP_SANDBOX_REFUSED = (
    "setup runs on the host; a sandbox image must ship the toolchain and dependencies"
)


@dataclass(frozen=True)
class TestRun:
    """What the toolchain said. ``services`` names the service instances (image
    digest, variant, when they read healthy) the tests ran against — part of the
    apparatus, so a verdict carries which oracle service answered."""

    returncode: int
    failing: frozenset[str]
    tail: str = ""
    timed_out: bool = False
    duration_s: float = 0.0
    parse_error: str = ""
    services: tuple[ServiceRecord, ...] = ()
    #: The instrument failed around the tests (ADR-0019: ``tree_copy_failed`` — the
    #: throwaway copy of the worktree could not be made). Such a run is red but it is NOT a
    #: verdict about the code: no failing id is attributed, the grader records an
    #: environment failure and the qualifier refuses ``QUAL_TREE_COPY_FAILED``.
    env_error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "services", tuple(self.services))

    @property
    def green(self) -> bool:
        """Exit 0, within the clock, and parseable — all three, or it is not green."""
        return self.returncode == 0 and not self.timed_out and not self.parse_error

    @property
    def red(self) -> bool:
        """Anything that is not :attr:`green` (a timeout or parse error is red, not unknown)."""
        return not self.green

    def to_dict(self) -> dict[str, Any]:
        """The evidence-pack shape (sorted ids, rounded duration — stable for hashing)."""
        d: dict[str, Any] = {
            "returncode": self.returncode,
            "failing": sorted(self.failing),
            "tail": self.tail,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 3),
            "parse_error": self.parse_error,
        }
        # Present iff the oracle ran against a service: packs of repos without one
        # stay byte-identical (content-addressed hashes are part of the evidence).
        if self.services:
            d["services"] = [s.to_dict() for s in self.services]
        # Present iff set, for the same reason: existing packs stay byte-identical.
        if self.env_error:
            d["env_error"] = self.env_error
        return d


def tail_of(text: str, n: int = TAIL_LINES) -> str:
    """The last ``n`` lines of toolchain output — what an operator reads on a failure."""
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


# ---------------------------------------------------------------------------
# Environment setup records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetupStep:
    """One command of the setup phase, as it ran. ``tail`` is redacted and capped
    at construction so a step can never carry a secret into an event or a run."""

    argv: tuple[str, ...]
    rc: int
    tail: str = ""
    duration_s: float = 0.0
    timed_out: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))
        object.__setattr__(self, "tail", redact_and_cap(self.tail, max_chars=SETUP_TAIL_CHARS))

    @property
    def ok(self) -> bool:
        """Exited 0 within the clock."""
        return self.rc == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        """The shape a ``setup.step`` event and a stored ``SetupResult`` carry."""
        return {
            "argv": list(self.argv),
            "rc": self.rc,
            "tail": self.tail,
            "duration_s": round(self.duration_s, 3),
            "timed_out": self.timed_out,
        }


@dataclass(frozen=True)
class SetupResult:
    """What the setup phase did and whether the environment is usable afterwards.

    ``ok`` means *ready now*: the step that closed the phase exited 0 and the
    runner's own readiness probe passed. Every step that ran is kept — a failed
    primary install followed by a successful fallback is ``ok`` with both on
    record. A step that failed leaves its redacted tail in ``steps`` and ``note``
    says which; nothing here is a verdict about any commit.
    """

    ok: bool
    steps: tuple[SetupStep, ...] = ()
    note: str = ""
    duration_s: float = 0.0
    #: The oracle's services setup started (or adopted), with their image digests.
    services: tuple[ServiceRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "services", tuple(self.services))

    @property
    def last_tail(self) -> str:
        """The tail of the last step that ran (what an operator reads on failure)."""
        return self.steps[-1].tail if self.steps else ""

    def to_dict(self) -> dict[str, Any]:
        """The shape the worker stores and the API returns for a setup phase."""
        d: dict[str, Any] = {
            "ok": self.ok,
            "steps": [s.to_dict() for s in self.steps],
            "note": self.note,
            "duration_s": round(self.duration_s, 3),
        }
        if self.services:
            d["services"] = [s.to_dict() for s in self.services]
        return d


class SetupSession:
    """Runs setup commands through an executor and keeps the record.

    ``run`` executes one :class:`~crb.core.execution.Command` (forced
    ``network=True`` — this is the network phase by definition) and appends its
    :class:`SetupStep`; ``result`` closes the session. ``on_step`` lets a caller
    stream steps as they finish (the worker turns them into ``setup.step`` events).
    """

    def __init__(
        self, executor: Executor, *, on_step: Callable[[SetupStep], None] | None = None
    ) -> None:
        self._executor = executor
        self._on_step = on_step
        self.steps: list[SetupStep] = []
        self._started = time.monotonic()

    @property
    def executor(self) -> Executor:
        """The executor the steps run through (``finish_setup`` reuses it for services)."""
        return self._executor

    def run(self, cmd: Command) -> SetupStep:
        """Execute one setup command and record it; a missing binary is a step, not a crash."""
        # Every setup command is the network phase by definition, whatever the caller marked.
        net = cmd if cmd.network else _with_network(cmd)
        started = time.monotonic()
        try:
            res = self._executor.run(net)
        except OSError as exc:
            # a missing toolchain binary is a failed step, not a crash: rc 127 as a shell would
            res = ExecResult(
                127, "", f"{type(exc).__name__}: {exc}", False, time.monotonic() - started
            )
        return self.record(net, res)

    def record(self, cmd: Command, res: ExecResult) -> SetupStep:
        """Append a step for a command that ran elsewhere (a service start) and
        stream it like any other."""
        step = SetupStep(
            cmd.argv, res.returncode, tail_of(res.combined), res.duration_s, res.timed_out
        )
        self.steps.append(step)
        if self._on_step is not None:
            self._on_step(step)
        return step

    @property
    def all_ok(self) -> bool:
        """Every step passed (a recovered failure makes this ``False`` while ``ok`` can be ``True``)."""
        return all(s.ok for s in self.steps)

    def result(self, ok: bool, note: str, services: Sequence[ServiceRecord] = ()) -> SetupResult:
        """Close the session into a :class:`SetupResult` with the wall clock since it opened."""
        return SetupResult(
            ok, tuple(self.steps), note, time.monotonic() - self._started, tuple(services)
        )


def _with_network(cmd: Command) -> Command:
    # Command is frozen; rebuild it with the network flag set so a sandbox executor can see it.
    return dataclasses.replace(cmd, network=True)


def _with_env(cmd: Command, base: dict[str, str]) -> Command:
    """``base`` under the command's own environment: what a service exports reaches
    the tests, but the runner's (and ``runner_opts.env``'s) explicit values win."""
    return dataclasses.replace(cmd, env={**base, **cmd.env})


def with_deps(cmd: Command, binding: DepsBinding | None, executor_name: str) -> Command:
    """``cmd`` with a dependency binding applied (ADR-0019 §6): the binding's environment
    for this executor (``env`` in a container, ``local_env`` on the host) OVER the
    runner's own — the binding is what points the toolchain at the sealed set
    (``GOMODCACHE``, ``GOPROXY=off``) — and, under docker only, its sets as read-only
    mounts. Idempotent (a mount already on the command is not added twice); ``None`` or an
    empty binding leaves the command exactly as the runner built it."""
    if binding is None or (not binding.env and not binding.local_env and not binding.mounts):
        return cmd
    env = {**cmd.env, **binding.env_for(executor_name)}
    mounts = cmd.ro_mounts
    if executor_name == "docker":
        mounts = tuple(dict.fromkeys((*cmd.ro_mounts, *binding.mounts)))
    return dataclasses.replace(cmd, env=env, ro_mounts=mounts)


def host_check(argv: Sequence[str], root: Path, *, env: dict[str, str] | None = None) -> bool:
    """Run an offline readiness probe on the host; ``True`` iff it exits 0.

    A missing binary, a launch error or a timeout reads as *not ready* — never as
    ready. The probe must be one the test command itself would perform (resolve
    the build offline), so "ready" means exactly "the tests can run now".
    """
    try:
        res = LocalExecutor().run(
            Command(tuple(argv), root, env=env or {}, timeout=READY_CHECK_TIMEOUT_S)
        )
    except (OSError, ValueError):
        return False
    return res.ok


def failed_step_note(steps: Sequence[SetupStep]) -> str:
    """``"step N failed (rc=…): <argv>"`` for the step that stopped the phase — the
    LAST one — or ``""`` when it passed. An earlier failure followed by more steps
    was recovered (a ``pip_fallback`` after a failed primary) and is not the stop."""
    if not steps or steps[-1].ok:
        return ""
    last = steps[-1]
    how = "timed out" if last.timed_out else f"rc={last.rc}"
    return f"step {len(steps)} failed ({how}): {' '.join(last.argv)}"


class TestRunner(Protocol):
    """The structural contract the grader, miner and worker programme against.

    :class:`BaseRunner` satisfies it; the protocol exists so a test double (or a
    future runner that does not inherit) can be substituted without the core
    importing it.
    """

    name: str
    config: RepoConfig

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]: ...

    def belt_scope(
        self, target_tests: Sequence[str], test_files: Sequence[str]
    ) -> tuple[str, ...]: ...

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command: ...

    def parse(self, result: ExecResult, root: Path) -> TestRun: ...

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int
    ) -> TestRun: ...

    def is_valid_oracle(self, root: Path, test_file: str) -> bool: ...

    def setup(
        self,
        executor: Executor,
        root: Path,
        *,
        env_dir: Path,
        timeout: int,
        on_step: Callable[[SetupStep], None] | None = None,
    ) -> SetupResult: ...

    def environment_ready(self, root: Path, env_dir: Path) -> bool: ...

    def lint_plan(self, root: Path, executor: Executor) -> LintPlan | None: ...


class BaseRunner:
    """Shared plumbing. Subclasses implement ``target_scope``, ``command``, ``parse``.

    ``env_dir`` is where a runner keeps state that must not live in the clone (the
    Python virtualenv). The worker and the CLI bind it after construction; a
    runner without one behaves exactly as before (``runner_opts`` / host tools).
    """

    name = "base"
    default_timeout = 900

    def __init__(self, config: RepoConfig, *, env_dir: Path | None = None) -> None:
        self.config = config
        self.opts: dict[str, Any] = dict(config.runner_opts)
        self.env_dir: Path | None = Path(env_dir) if env_dir is not None else None
        #: The current task's author date (``TaskSpec.authored``), bound by the
        #: caller like ``env_dir`` — it selects the era variant of a declared
        #: service. ``None`` → the worktree HEAD's date is the fallback (see :meth:`run`).
        self.authored: str | None = None
        #: The oracle's services, once started (see :meth:`ensure_services`).
        self._services: ServiceSession | None = None
        #: The sealed dependency set the next command runs with (ADR-0019), bound by
        #: :meth:`run_for` (like ``authored``) or :meth:`deps_bound` — the qualifier and the
        #: grader bind the role's (or the trial's selected) set; ``None`` keeps today's
        #: command exactly.
        self.deps: DepsBinding | None = None

    # --- dependencies (ADR-0019) ---------------------------------------------------
    def bind_deps(self, cmd: Command, executor: Executor) -> Command:
        """``cmd`` with :attr:`deps` applied (:func:`with_deps`)."""
        return with_deps(cmd, self.deps, executor.name)

    @contextlib.contextmanager
    def deps_bound(self, binding: DepsBinding | None) -> Iterator[None]:
        """Bind ``binding`` for the block, restoring the previous one after."""
        previous = self.deps
        self.deps = binding
        try:
            yield
        finally:
            self.deps = previous

    def probe_environment(
        self, executor: Executor, root: Path, *, timeout: int = READY_CHECK_TIMEOUT_S
    ) -> ExecResult | None:
        """Run :meth:`env_probe_command` over the whole tree with :attr:`deps` bound;
        ``None`` when this runner has none. The caller reads ``ok`` (a probe failure is the
        posture's, never a verdict)."""
        cmd = self.env_probe_command(Path(root), (), executor=executor, timeout=timeout)
        if cmd is None:
            return None
        return executor.run(self.bind_deps(cmd, executor))

    # --- scopes ------------------------------------------------------------------
    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        """The commit's test files as the toolchain addresses them (belt 2). Default:
        the files themselves, de-duplicated and sorted so the command is stable."""
        return tuple(sorted(set(test_files)))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
        """The regression surface belt 3 runs, from ``RepoConfig.belt_scope``: an explicit
        tuple of paths, ``target_only``, ``affected_dirs`` (the directories of the target
        tests, else ``test_prefix``) or ``bare`` (the toolchain's default discovery)."""
        policy = self.config.belt_scope
        if isinstance(policy, tuple):
            # ("BARE",) is the census-era spelling of the empty scope; both mean default discovery.
            return BARE if policy in {("BARE",), ()} else policy
        if policy == BELT_TARGET_ONLY:
            return tuple(target_tests)
        if policy == BELT_AFFECTED_DIRS:
            dirs = sorted({os.path.dirname(tf) + "/" for tf in test_files if os.path.dirname(tf)})
            return tuple(dirs) or ((self.config.test_prefix,) if self.config.test_prefix else BARE)
        if policy == BELT_BARE:
            return BARE
        raise ValueError(f"unknown belt_scope policy {policy!r}")  # pragma: no cover

    # --- execution ---------------------------------------------------------------
    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """The argv that runs ``scope`` in ``root``; ``executor`` lets a runner pick the
        sandbox-side interpreter over the host one. Subclasses must implement."""
        raise NotImplementedError

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """Turn raw toolchain output into failing test ids. Subclasses must implement;
        set ``parse_error`` when the reporter's shape was not recognised."""
        raise NotImplementedError

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int = 0
    ) -> TestRun:
        """Run ``scope`` in ``root`` and report what the toolchain said.

        With services declared, the variant :attr:`authored` selects is made
        healthy first (:meth:`run_for` binds it for one call). A caller that binds
        nothing gets the worktree HEAD's date — the commit's *parent* — as the
        fallback: exact except for a commit sitting on an era boundary, so grading
        callers should bind the task's own date.
        """
        t = timeout or int(self.opts.get("timeout", self.default_timeout))
        records: tuple[ServiceRecord, ...] = ()
        service_env: dict[str, str] = {}
        if self.has_services():
            records = self.ensure_services(executor, root, authored=self.authored)
            service_env = self.service_env()
        cmd = self.bind_deps(self.command(root, scope, executor=executor, timeout=t), executor)
        if service_env:
            cmd = _with_env(cmd, service_env)
        result = executor.run(cmd)
        if result.env_error:
            # the instrument failed (the tree could not be copied): red, never attributed
            return TestRun(
                result.returncode or 1,
                frozenset(),
                tail_of(result.combined),
                False,
                result.duration_s,
                parse_error=f"environment: {result.env_error}",
                services=records,
                env_error=result.env_error,
            )
        if result.timed_out:
            # 124 is coreutils `timeout`'s exit code; the grader reads timed_out, not the rc.
            return TestRun(
                124,
                frozenset(),
                tail_of(result.combined),
                True,
                result.duration_s,
                services=records,
            )
        run = self.parse(result, root)
        parse_error = run.parse_error
        # FAIL CLOSED on unattributed failure: a non-zero exit with no parsed failing
        # test ids (compile error, crash, reporter mismatch) must never read as "no
        # new failures". The grader treats parse_error as a failed belt.
        if run.returncode != 0 and not run.failing and not parse_error:
            parse_error = f"unattributed failure (rc={run.returncode}, no failing ids parsed)"
        return TestRun(
            run.returncode,
            run.failing,
            run.tail or tail_of(result.combined),
            False,
            result.duration_s,
            parse_error,
            records,
        )

    def run_for(
        self,
        executor: Executor,
        root: Path,
        scope: Sequence[str],
        *,
        timeout: int = 0,
        authored: str | None,
        deps: DepsBinding | None = None,
    ) -> TestRun:
        """:meth:`run` with the task's author date (era selection of a declared service)
        and its dependency binding (ADR-0019) bound for the call, the previous bindings
        restored after. Additive: every language runner's ``run`` override keeps its
        signature."""
        previous, previous_deps = self.authored, self.deps
        self.authored = authored
        if deps is not None:
            self.deps = deps
        try:
            return self.run(executor, root, scope, timeout=timeout)
        finally:
            self.authored, self.deps = previous, previous_deps

    # --- the posture (ADR-0019) ----------------------------------------------------
    def toolchain_argv(self, executor: Executor) -> tuple[str, ...]:
        """The command that prints the toolchain's exact version inside ``executor`` — part
        of the posture (a Go 1.26.4 host and a Go 1.26.8 sandbox are two postures). The
        base runner names none."""
        return ()

    def env_probe_command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command | None:
        """An offline command that proves the posture can LOAD the dependencies the tests
        at ``root`` need (Go: ``go list -deps -test ./...`` with ``GOPROXY=off``), so a
        build-failure RED is never "nothing builds here". ``None`` — this runner has no
        such probe; the qualifier then refuses a build-failure RED in a sealed posture."""
        return None

    def _services_state_dir(self) -> Path | None:
        """Where service fixtures are staged for bind-mounting. ``CRB_SERVICES_DIR``
        overrides ``<env_dir>/services`` for hosts whose container runtime cannot see
        ``CRB_HOME`` (colima / Docker Desktop mount tables exclude ``/private/tmp`` —
        the dev stack lives there); production keeps ``CRB_HOME`` on a shared path."""
        override = os.environ.get("CRB_SERVICES_DIR", "").strip()
        if override:
            return Path(override).expanduser() / self.config.name
        return (self.env_dir / "services") if self.env_dir is not None else None

    # --- services the oracle needs (runner_opts.services) --------------------------
    def has_services(self) -> bool:
        """``True`` iff the repo config declares ``runner_opts.services``."""
        return bool(self.opts.get("services"))

    def service_specs(self) -> tuple[ServiceSpec, ...]:
        """The declared services, validated. A malformed declaration is a harness
        error (:class:`ServiceUnavailable`), never a verdict."""
        try:
            return parse_services(self.opts)
        except ValueError as exc:
            raise ServiceUnavailable(f"runner_opts.services: {exc}") from exc

    def ensure_services(
        self,
        executor: Executor,
        root: Path,
        *,
        authored: str | None = None,
        on_command: Callable[[Command, ExecResult], object] | None = None,
        warm: bool = False,
    ) -> tuple[ServiceRecord, ...]:
        """Every declared service healthy for the variant the task needs; ``()``
        when none is declared.

        One :class:`~crb.core.services.ServiceSession` per runner, keyed to the
        repository *clone* (``root`` may be a trial worktree; fixtures and
        ``generate`` come from the clone every worktree shares). Fixtures stage
        under ``<env_dir>/services``. ``warm`` is the setup phase: stage every
        variant and start the latest era so the record names what will answer.
        Under a sandbox executor this refuses (the tests could not reach the
        service through ``--network=none``); the caller stops, nothing is graded.
        """
        specs = self.service_specs()
        if not specs:
            return ()
        if executor.name == "docker":
            raise ServiceUnavailable(SERVICES_SANDBOX_REFUSED)
        clone = clone_root_of(Path(root))
        session = self._services
        # One session per clone: a runner re-bound to another repository's clone starts afresh.
        if session is None or session.clone != clone:
            if session is not None:
                session.close()
            session = ServiceSession(
                specs,
                executor,
                clone=clone,
                repo=self.config.name,
                state_dir=self._services_state_dir(),
            )
            self._services = session
        session.executor = executor
        session.on_command = on_command
        try:
            if warm:
                session.prepare()
                return session.ensure(None, latest=True)
            if authored is None and any(s.needs_era for s in specs):
                authored = authored_of(Path(root))
            return session.ensure(authored)
        finally:
            session.on_command = None

    def service_env(self) -> dict[str, str]:
        """The environment the active services export to the test command."""
        return dict(self._services.env) if self._services is not None else {}

    def service_records(self) -> tuple[ServiceRecord, ...]:
        """The service instances currently answering (what a ``TestRun`` is stamped with)."""
        return self._services.records if self._services is not None else ()

    def service_logs(self) -> dict[str, str]:
        """Redacted, capped log tails of services that stopped or failed health."""
        return dict(self._services.logs) if self._services is not None else {}

    def close_services(self) -> None:
        """Stop the services this runner started (``keep: true`` ones stay up)."""
        if self._services is not None:
            self._services.close()

    # --- oracle validity ---------------------------------------------------------
    def is_valid_oracle(self, root: Path, test_file: str) -> bool:
        """A target test file must exist and be non-trivial. Languages with a cheap
        static signal (pytest's ``def test`` / ``class Test``) tighten this."""
        p = root / test_file
        try:
            return p.is_file() and p.stat().st_size > 0
        except OSError:
            return False

    def describe(self) -> dict[str, Any]:
        """Apparatus description: the runner and the service instances it is using."""
        out: dict[str, Any] = {"runner": self.name}
        records = self.service_records()
        if records:
            out["services"] = [r.to_dict() for r in records]
        return out

    # --- belt 5: the repository's own formatter / linter (ADR-0011) ------------
    def lint_plan(self, root: Path, executor: Executor) -> LintPlan | None:
        """What belt 5 runs on the changed files: the declared ``RepoConfig.lint``
        when present, else this language's default (:meth:`detect_lint`), else
        ``None`` — the belt is then *not evaluated* (never a pass, never a fail).
        ``{"disabled": true}`` in the config is an explicit ``None``."""
        if lint_disabled(self.config.lint):
            return None
        declared = plan_from_config(self.config.lint)
        if declared is not None:
            return declared
        return self.detect_lint(Path(root), executor)

    def detect_lint(self, root: Path, executor: Executor) -> LintPlan | None:
        """The language default, from the repository's OWN configuration only
        (``.golangci.yml``, ``[tool.ruff]``, an ESLint config, a pom plugin…). The
        base runner detects nothing; each language runner cites its evidence."""
        return None

    # --- environment setup (the one network phase) ----------------------------
    def setup(
        self,
        executor: Executor,
        root: Path,
        *,
        env_dir: Path,
        timeout: int,
        on_step: Callable[[SetupStep], None] | None = None,
    ) -> SetupResult:
        """Install the repository's test dependencies so :meth:`run` can work offline.

        Default: nothing to do (``ok=True``). Language runners override this and
        record every command they ran; ``timeout`` is the per-step wall clock
        (``0`` → ``runner_opts.setup_timeout`` or :data:`DEFAULT_SETUP_TIMEOUT_S`);
        ``on_step`` sees each :class:`SetupStep` as it finishes.
        """
        return SetupResult(True, (), SETUP_NOTHING, 0.0)

    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        """``True`` iff the test command could run now without the network.

        Answered on the host with the toolchain's own offline resolution (cheap next
        to a test run; never a download). Runners with no environment to prepare
        are always ready.
        """
        return True

    def setup_timeout(self, timeout: int) -> int:
        """Per-step wall clock: the caller's, else ``runner_opts.setup_timeout``, else the default."""
        return int(timeout or self.opts.get("setup_timeout", DEFAULT_SETUP_TIMEOUT_S))

    @staticmethod
    def sandbox_refusal(executor: Executor) -> SetupResult | None:
        """Setup is a host phase: under a sandbox it fails closed with the reason."""
        if executor.name == "docker":
            return SetupResult(False, (), SETUP_SANDBOX_REFUSED, 0.0)
        return None

    def finish_setup(self, session: SetupSession, root: Path, env_dir: Path) -> SetupResult:
        """Close a session: ok iff the step that stopped the phase passed AND the
        environment reads ready AND the oracle's services (if declared) are up.
        Runners stop at the first unrecovered failure, so the last step is decisive;
        an earlier failure means a fallback recovered it. The service commands are
        recorded as steps too; a service that cannot be provided fails the phase
        with its reason (and the bit-rot hint when a pinned build is what broke)."""
        steps = session.steps
        if steps and not steps[-1].ok:
            return session.result(False, failed_step_note(steps))
        if not self.environment_ready(root, env_dir):
            return session.result(False, "steps succeeded but the environment is not ready")
        recovered = [i for i, s in enumerate(steps, 1) if not s.ok]
        note = (
            "ready"
            if not recovered
            else ("ready (step " + ", ".join(map(str, recovered)) + " failed; fallback succeeded)")
        )
        if not self.has_services():
            return session.result(True, note)
        if self.env_dir is None:
            self.env_dir = Path(env_dir)
        try:
            records = self.ensure_services(
                session.executor, root, on_command=session.record, warm=True
            )
        except ServiceUnavailable as exc:
            return session.result(False, f"services: {exc}")
        named = ", ".join(f"{r.name}@{r.variant}" for r in records)
        return session.result(True, f"{note}; services: {named}", records)


#: One ``-rfE`` short-summary line: ``FAILED tests/x.py::test_a - AssertionError``. ERROR
#: (a fixture or collection error) counts as a failing id too — it is not a pass.
_FAIL_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)


def parse_pytest_failures(text: str) -> frozenset[str]:
    """The pytest ``-rfE`` short-summary parser. Shared so every pytest path is identical."""
    return frozenset(m.split(" ")[0] for m in _FAIL_LINE.findall(text))
