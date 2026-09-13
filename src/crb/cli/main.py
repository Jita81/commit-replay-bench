"""``crb`` entry point: build the parser, dispatch, map every failure to an exit code.

``main(argv)`` is importable and side-effect free apart from stdout/stderr, so
tests drive it in-process. It never lets a harness exception escape as a
traceback: an unexpected error prints one line and exits ``2`` (set
``CRB_DEBUG=1`` to re-raise while developing).
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
    grade,
    ledger,
    mine,
    repo,
    route,
    service,
)
from crb.core.execution import SandboxUnavailable
from crb.core.git import GitError
from crb.core.grade import FalseQ1Violation
from crb.core.ledger import LedgerIntegrityError
from crb.core.legacy import LegacyImportError
from crb.core.version import __version__

PROG = "crb"


def build_parser() -> argparse.ArgumentParser:
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
    config.register(sub)
    service.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
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
    sys.stderr.write(f"{PROG}: error: {message}\n")
    sys.stderr.flush()
    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
