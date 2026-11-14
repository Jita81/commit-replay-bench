"""The runner-tool pre-check: refuse an attempt before any builder call when the grader's own
test command cannot start.

A replay on nhsuk-react-components paid the builder six times and then graded each attempt
``harness`` because ``jest`` was not in the repository's environment (docs/PREVENTION.md
P-004). The grader's first word was never going to resolve, so the outcome was decided before
the builder was called. This check asks the question the grader would ask, first: does the
runner's test command start with something this host can execute?

It is a **gate**, not advice: the attempt is refused with ``runner tool missing: <tool>`` (a
``harness`` row by the product's failure rule — an instrument fault, never the model's) and
the builder is neither instantiated nor called, so nothing is spent. It changes nothing the
builder sees. Under a sandbox executor the image is its own environment and the host cannot
answer for it, so the check does not run there (the sealed posture's own qualification owns
that case — ``feat/posture``).

The **builder-side tool check** asks the same question where the BUILDER runs: the test
command the builder is handed (the brief's harness command) is the grader's command rendered
for the builder's environment, and a builder image without the test tool (``pytest``
missing from a slim Python image) leaves the builder with a command it cannot run — on a
repository whose sealed set is empty, nothing else puts the tool there. Before any model
call the adapter derives the runner's check from that very command (``dataclasses.replace``
of its argv only: never a command rebuilt field by field, P-820) and runs it in the
builder's own environment — the builder image with the session's dependency mounts and env
when the builder is sealed, the host otherwise — under a short wall clock. A non-zero exit,
a timeout, a cancellation, an environment error or a check that could not run refuses the
attempt with the same ``runner tool missing: <tool>`` prefix: an instrument row, nothing
spent.

Navigation
----------
What it is:   ``runner_tool_missing`` — the question "can the grader's test command start on
              this host?", asked before the builder is paid; ``tool_check_command`` and
              ``builder_tool_refusal`` — "does the command handed to the builder start in
              the builder's own environment?", asked before any model call.
What it does: Builds the runner's test command for the task's target tests (never shown to
              the builder), takes its first word, and resolves it: a path must exist and be
              executable (a repository-relative one from the command's working directory), a
              bare name must be on the command's PATH. Returns ``""`` when it resolves (or
              when the question cannot be asked — a runner that cannot build its command, a
              sandbox executor), else the refusal sentence with the fix.
How:          ``runner.command(...)`` → ``argv[0]`` → ``os.access`` / ``shutil.which`` with the
              PATH the local executor would give the child. The builder-side check:
              ``runner.tool_check(argv)`` → ``replace(handed, argv=…)`` → ``executor.run``
              bounded by ``TOOL_CHECK_TIMEOUT_S``; anything but a finished exit 0 refuses.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/builders/adapter.py (calls both in ``build`` before the builder),
              src/crb/builders/container.py (``builder_executor`` — the builder's image),
              src/crb/core/runners/base.py (``command`` — the grader's own command),
              src/crb/core/execution.py (``LocalExecutor`` and the PATH it passes),
              src/crb/core/ledger.py (``derive_failure_kind`` — the refusal is ``harness``),
              docs/PREVENTION.md (P-004 — the bug this closes)
Tested by:    tests/test_builders_toolcheck.py, tests/test_builders_tool_check.py,
              tests/test_builders_container_docker.py (the builder image without pytest)
Touch when:   never for a new repository; a runner whose command does not start with its tool is
              added (teach this where the tool is).
"""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from crb.core.execution import SandboxUnavailable

if TYPE_CHECKING:
    from crb.core.execution import Command, ExecResult, Executor
    from crb.core.runners.base import BaseRunner

#: The error prefix of a refused attempt — the class signature the learning loop reads.
RUNNER_TOOL_MISSING = "runner tool missing: "
#: The executor the host can answer for; a sandbox image is its own environment.
_LOCAL = "local"
#: The builder-side tool check's wall clock: it starts a tool and prints its version.
TOOL_CHECK_TIMEOUT_S = 60
#: How much of the check's output a refusal quotes.
_TAIL = 300


def _resolves(argv0: str, cwd: Path, path_env: str) -> bool:
    if os.sep in argv0 or "/" in argv0:
        p = Path(argv0)
        p = p if p.is_absolute() else cwd / p
        return p.is_file() and os.access(p, os.X_OK)
    return shutil.which(argv0, path=path_env) is not None


def runner_tool_missing(
    runner: BaseRunner, executor: Executor, root: Path, target_tests: Sequence[str] = ()
) -> str:
    """``""`` when the runner's test command can start on this host; else the refusal:
    ``runner tool missing: <tool> — …`` naming the command's first word and the fix."""
    if getattr(executor, "name", "") != _LOCAL:
        return ""
    try:
        timeout = int(runner.opts.get("timeout", runner.default_timeout))
        cmd = runner.command(Path(root), tuple(target_tests), executor=executor, timeout=timeout)
    except Exception:  # the question cannot be asked: never refuse on a guess
        return ""
    argv0 = cmd.argv[0]
    path_env = str(cmd.env.get("PATH") or os.environ.get("PATH", ""))
    if _resolves(argv0, cmd.root / cmd.cwd_rel, path_env):
        return ""
    tool = Path(argv0).name
    return (
        f"{RUNNER_TOOL_MISSING}{tool} — the {runner.name} runner's test command starts with "
        f"{argv0!r}, which does not resolve on this host, so no attempt could be graded; "
        "refused before any builder call (nothing spent). Prepare the repository's "
        f"environment (`crb repo setup {runner.config.name}`) or install {tool}, then re-run"
    )


def tool_check_command(runner: BaseRunner, handed: Command) -> tuple[str, Command] | None:
    """``(tool, check)``: the runner's tool check derived from ``handed`` — the test command
    the builder is handed, as a :class:`~crb.core.execution.Command` — with ONLY its argv
    replaced (env, mounts, tree, root, working directory, timeout all stay the handed
    command's). ``None`` when the runner declares no check."""
    declared = runner.tool_check(handed.argv)
    if declared is None:
        return None
    tool, argv = declared
    return tool, replace(handed, argv=tuple(argv))


def _outcome(res: ExecResult) -> str:
    """Why a finished-or-not check did not prove the tool, or ``""`` when it did."""
    tail = " ".join((res.stderr or res.stdout or "").split())[-_TAIL:]
    if res.env_error:
        return f"environment error ({res.env_error}): {tail}".rstrip(": ")
    if res.cancelled:
        return "cancelled before it finished"
    if res.timed_out:
        return "timed out"
    if res.returncode != 0:
        return f"exit {res.returncode}: {tail}".rstrip(": ")
    return ""


def builder_tool_refusal(
    runner: BaseRunner, executor: Executor, tool: str, check: Command, *, where: str
) -> tuple[str, str]:
    """Run ``check`` on ``executor`` (the builder's own environment, named ``where``) under
    :data:`TOOL_CHECK_TIMEOUT_S`. Returns ``(outcome, refusal)``: ``("ok", "")`` when the
    tool started; otherwise the outcome and the refusal, ``runner tool missing: <tool> —
    …``. Fails closed: a non-zero exit, a timeout, a cancellation, an environment error or
    a check that raised refuses. :class:`SandboxUnavailable` propagates — the sandbox
    itself is missing (an absent builder image), and the run stops as the session would."""
    bounded = replace(check, timeout=min(check.timeout, TOOL_CHECK_TIMEOUT_S))
    try:
        res = executor.run(bounded)
    except SandboxUnavailable:
        raise
    except Exception as exc:  # the check could not run: never read as "the tool is there"
        outcome = f"the check could not run: {type(exc).__name__}: {str(exc)[:_TAIL]}"
    else:
        outcome = _outcome(res)
        if not outcome:
            return "ok", ""
    shown = " ".join(shlex.quote(a) for a in check.argv)
    return outcome, (
        f"{RUNNER_TOOL_MISSING}{tool} — the {runner.name} runner's test command handed to the "
        f"builder does not start in the builder's own environment ({where}): `{shown}` "
        f"{outcome}; refused before any builder call (nothing spent). The builder's "
        f"environment must carry {tool} (the builder image recipes: deploy/README.md 9.2)"
    )


__all__ = [
    "RUNNER_TOOL_MISSING",
    "TOOL_CHECK_TIMEOUT_S",
    "builder_tool_refusal",
    "runner_tool_missing",
    "tool_check_command",
]
