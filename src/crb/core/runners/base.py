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
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from crb.core.execution import Command, ExecResult, Executor, LocalExecutor
from crb.core.lint import LintPlan, lint_disabled, plan_from_config
from crb.core.redact import redact_and_cap
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
    returncode: int
    failing: frozenset[str]
    tail: str = ""
    timed_out: bool = False
    duration_s: float = 0.0
    parse_error: str = ""

    @property
    def green(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.parse_error

    @property
    def red(self) -> bool:
        return not self.green

    def to_dict(self) -> dict[str, Any]:
        return {
            "returncode": self.returncode,
            "failing": sorted(self.failing),
            "tail": self.tail,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 3),
            "parse_error": self.parse_error,
        }


def tail_of(text: str, n: int = TAIL_LINES) -> str:
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
        return self.rc == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))

    @property
    def last_tail(self) -> str:
        """The tail of the last step that ran (what an operator reads on failure)."""
        return self.steps[-1].tail if self.steps else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "steps": [s.to_dict() for s in self.steps],
            "note": self.note,
            "duration_s": round(self.duration_s, 3),
        }


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

    def run(self, cmd: Command) -> SetupStep:
        net = cmd if cmd.network else _with_network(cmd)
        started = time.monotonic()
        try:
            res = self._executor.run(net)
        except OSError as exc:
            # a missing toolchain binary is a failed step, not a crash: rc 127 as a shell would
            step = SetupStep(
                net.argv, 127, f"{type(exc).__name__}: {exc}", time.monotonic() - started
            )
        else:
            step = SetupStep(
                net.argv, res.returncode, tail_of(res.combined), res.duration_s, res.timed_out
            )
        self.steps.append(step)
        if self._on_step is not None:
            self._on_step(step)
        return step

    @property
    def all_ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def result(self, ok: bool, note: str) -> SetupResult:
        return SetupResult(ok, tuple(self.steps), note, time.monotonic() - self._started)


def _with_network(cmd: Command) -> Command:
    return Command(
        cmd.argv,
        cmd.root,
        cwd_rel=cmd.cwd_rel,
        env=cmd.env,
        timeout=cmd.timeout,
        writable_paths=cmd.writable_paths,
        network=True,
    )


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

    # --- scopes ------------------------------------------------------------------
    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted(set(test_files)))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
        policy = self.config.belt_scope
        if isinstance(policy, tuple):
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
        raise NotImplementedError

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        raise NotImplementedError

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int = 0
    ) -> TestRun:
        t = timeout or int(self.opts.get("timeout", self.default_timeout))
        cmd = self.command(root, scope, executor=executor, timeout=t)
        result = executor.run(cmd)
        if result.timed_out:
            return TestRun(124, frozenset(), tail_of(result.combined), True, result.duration_s)
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
        )

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
        return {"runner": self.name}

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
        return int(timeout or self.opts.get("setup_timeout", DEFAULT_SETUP_TIMEOUT_S))

    @staticmethod
    def sandbox_refusal(executor: Executor) -> SetupResult | None:
        """Setup is a host phase: under a sandbox it fails closed with the reason."""
        if executor.name == "docker":
            return SetupResult(False, (), SETUP_SANDBOX_REFUSED, 0.0)
        return None

    def finish_setup(self, session: SetupSession, root: Path, env_dir: Path) -> SetupResult:
        """Close a session: ok iff the step that stopped the phase passed AND the
        environment reads ready. Runners stop at the first unrecovered failure, so
        the last step is decisive; an earlier failure means a fallback recovered it."""
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
        return session.result(True, note)


_FAIL_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)


def parse_pytest_failures(text: str) -> frozenset[str]:
    """The pytest ``-rfE`` short-summary parser. Shared so every pytest path is identical."""
    return frozenset(m.split(" ")[0] for m in _FAIL_LINE.findall(text))
