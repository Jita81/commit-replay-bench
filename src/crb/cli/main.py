"""``crb`` entry point: build the parser, dispatch, map every failure to an exit code.

``main(argv)`` is importable and side-effect free apart from stdout/stderr, so
tests drive it in-process. It never lets a harness exception escape as a
traceback: an unexpected error prints one line and exits ``2`` (set
``CRB_DEBUG=1`` to re-raise while developing).

Navigation
----------
What it is:   The ``crb`` entry point — parser assembly, dispatch, and the one place every
              failure becomes an exit code.
What it does: Registers each command module's subparser, runs the chosen ``func``, and maps
              ``CliError`` / sandbox / git / ledger / false-Q1 exceptions to a one-line
              stderr message and exit 2 — never a traceback, never a silent pass
              (``CRB_DEBUG=1`` re-raises for development).
How:          ``build_parser`` → ``argparse`` → ``main`` try/except ladder → ``_fail``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/cli/commands/__init__.py (``CliError``, the exit codes),
              src/crb/cli/commands/repo.py + src/crb/cli/commands/mine.py +
              src/crb/cli/commands/grade.py + src/crb/cli/commands/ledger.py +
              src/crb/cli/commands/route.py (the pipeline verbs, in order),
              src/crb/cli/commands/service.py (``serve`` / ``worker`` / ``migrate`` /
              ``doctor``), src/crb/cli/commands/users.py (the break-glass account verbs),
              src/crb/core/execution.py (``SandboxUnavailable`` → exit 2)
Tested by:    tests/test_cli.py, tests/test_cli_doctor.py, tests/test_cli_tasks.py,
              tests/test_cli_users.py
Touch when:   never for a new repository; adding a verb means a ``register`` in a new
              commands module and one line here; a new core exception class that should
              exit 2 with a clean message needs a clause in the ladder.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from crb.cli.commands import (
    EXIT_ERROR,
    CliError,
    config,
    deps,
    grade,
    learn,
    ledger,
    mine,
    repo,
    route,
    service,
    tasks,
    users,
)
from crb.core.execution import SandboxUnavailable
from crb.core.git import GitError
from crb.core.grade import FalseQ1Violation
from crb.core.ledger import LedgerIntegrityError
from crb.core.legacy import LegacyImportError
from crb.core.version import __version__

PROG = "crb"


def build_parser() -> argparse.ArgumentParser:
    """The top-level parser with every verb registered (order = the help's order)."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Commit Replay Bench — grade an AI builder against a repository's own "
            "held-out tests under four mechanical belts (false-Q1 = 0), ledger every "
            "verdict, route change-classes on measured evidence."
        ),
        epilog="exit codes: 0 ok | 1 verdict negative | 2 usage or harness error",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    repo.register(sub)
    mine.register(sub)
    grade.register(sub)
    ledger.register(sub)
    route.register(sub)
    learn.register(sub)
    tasks.register(sub)
    config.register(sub)
    deps.register(sub)
    users.register(sub)
    service.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, dispatch, and return the exit code (see the package docstring for the codes).
    Every known failure class is caught below and reported in one line."""
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as e:  # argparse: usage error (2) or --help/--version (0)
        code = e.code
        return code if isinstance(code, int) else EXIT_ERROR
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        return int(func(args))
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_ERROR
    except CliError as e:
        return _fail(str(e))
    except SandboxUnavailable as e:
        return _fail(f"sandbox unavailable (failing closed): {e}")
    except GitError as e:
        return _fail(f"git: {e}")
    except (LedgerIntegrityError, FalseQ1Violation, LegacyImportError) as e:
        return _fail(f"{type(e).__name__}: {e}")
    except NotImplementedError as e:
        return _fail(f"not implemented: {e}")
    except KeyboardInterrupt:
        return _fail("interrupted")
    except Exception as e:  # never a traceback, never a pass
        if os.environ.get("CRB_DEBUG"):
            raise
        return _fail(f"{type(e).__name__}: {e}")


def _fail(message: str) -> int:
    """Print one error line on stderr and return the harness-error code."""
    sys.stderr.write(f"{PROG}: error: {message}\n")
    sys.stderr.flush()
    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
