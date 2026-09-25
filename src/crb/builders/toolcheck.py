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

Navigation
----------
What it is:   ``runner_tool_missing`` — the question "can the grader's test command start on
              this host?", asked before the builder is paid.
What it does: Builds the runner's test command for the task's target tests (never shown to
              the builder), takes its first word, and resolves it: a path must exist and be
              executable (a repository-relative one from the command's working directory), a
              bare name must be on the command's PATH. Returns ``""`` when it resolves (or
              when the question cannot be asked — a runner that cannot build its command, a
              sandbox executor), else the refusal sentence with the fix.
How:          ``runner.command(...)`` → ``argv[0]`` → ``os.access`` / ``shutil.which`` with the
              PATH the local executor would give the child.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/builders/adapter.py (calls it in ``build`` before the builder),
              src/crb/core/runners/base.py (``command`` — the grader's own command),
              src/crb/core/execution.py (``LocalExecutor`` and the PATH it passes),
              src/crb/core/ledger.py (``derive_failure_kind`` — the refusal is ``harness``),
              docs/PREVENTION.md (P-004 — the bug this closes)
Tested by:    tests/test_builders_toolcheck.py
Touch when:   a runner whose command does not start with its tool is added (teach this where
              the tool is); never for a new repository.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crb.core.execution import Executor
    from crb.core.runners.base import BaseRunner

#: The error prefix of a refused attempt — the class signature the learning loop reads.
RUNNER_TOOL_MISSING = "runner tool missing: "
#: The executor the host can answer for; a sandbox image is its own environment.
_LOCAL = "local"


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


__all__ = ["RUNNER_TOOL_MISSING", "runner_tool_missing"]
