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
"""

from crb.cli.main import main

__all__ = ["main"]
