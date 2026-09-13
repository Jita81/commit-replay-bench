"""Package + apparatus versioning.

``APPARATUS_VERSION`` is the version of the *measuring instrument* — the
grader semantics, belt definitions, size table and routing rule. It is stamped
onto every grade row and every evidence pack so a number can always be traced
to the exact apparatus that produced it ("evidence expires" — see
``docs/EVIDENCE-AND-CLAIMS.md``). Bump it whenever the meaning of a verdict
could change; bump ``__version__`` for anything else.
"""

from __future__ import annotations

__version__ = "2.0.0a0"

#: Semantic version of the grading apparatus. Changing belt semantics, the
#: size-tier table, the change-class taxonomy or the routing rule MUST bump
#: this and be recorded in an ADR.
APPARATUS_VERSION = "2.0"
