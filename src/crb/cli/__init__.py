"""``crb`` — the command-line front door to :mod:`crb.core`.

The CLI is deliberately thin: parse → call core → print. It carries no verdict
logic of its own; every number it prints was computed by the core and carries
its ``n``, its interval and its apparatus stamp.

Exit codes (stable, scriptable):

* ``0`` — the command succeeded and, where it had a verdict, the verdict was positive;
* ``1`` — the verdict was negative (not clean, chain broken, a cell routed
  ``do_not_ship``…);
* ``2`` — usage error, or a harness / sandbox / git error. A harness error is
  never a pass.

Navigation
----------
What it is:   The ``crb`` command-line package — the front door and its exit-code contract.
What it does: Re-exports ``main`` for the ``crb`` console script; the docstring above is the
              contract every subcommand honours (thin: parse → core → print; three exit
              codes; a harness error is never a pass).
How:          Plain re-export; ``crb.cli.main`` builds the parser and dispatches.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/cli/main.py (parser + dispatch + exit-code mapping),
              src/crb/cli/commands/__init__.py (the shared plumbing every verb uses),
              src/crb/cli/commands/repo.py (the first verb an operator runs), docs/OPERATOR.md
              (the verbs in pipeline order)
Tested by:    tests/test_cli.py
Touch when:   never for a new repository; only when a new console entry point is added.
"""

from crb.cli.main import main

__all__ = ["main"]
