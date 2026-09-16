"""Package + apparatus versioning.

``APPARATUS_VERSION`` is the version of the *measuring instrument* — the
grader semantics, belt definitions, size table and routing rule. It is stamped
onto every grade row and every evidence pack so a number can always be traced
to the exact apparatus that produced it ("evidence expires" — see
``docs/EVIDENCE-AND-CLAIMS.md``). Bump it whenever the meaning of a verdict
could change; bump ``__version__`` for anything else.

Navigation
----------
What it is:   The two version numbers — ``__version__`` (the package) and
              ``APPARATUS_VERSION`` (the measuring instrument), with the history of why
              the latter moved.
What it does: Stamps every grade row and evidence pack so a number is traceable to the
              apparatus that produced it; ``__version__`` is what ``crb --version``,
              ``/version`` and the Helm chart report and must agree with pyproject.toml.
How:          Two module constants; nothing else.
Layer:        core — docs/ARCHITECTURE.md#74-versioning
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/ledger.py (``expected_belt_sets`` reads the apparatus stamp to
              admit a belt set), src/crb/core/evidence.py (the apparatus stamp on packs),
              src/crb/core/learn.py (``remeasure_plan`` compares stamps), pyproject.toml
              (the package version's other home), deploy/helm/crb/Chart.yaml
              (``appVersion``), src/crb/server/app.py (``/version``)
Tested by:    tests/test_version_consistency.py, tests/test_ledger.py
Touch when:   a release (``__version__`` in the three places the test pins), or a change
              to belt semantics, the size table, the taxonomy or the routing rule
              (``APPARATUS_VERSION`` — with an ADR, a line in the history above, and the
              belt-set rule in src/crb/core/ledger.py if a belt was added);
              docs/ARCHITECTURE.md#74-versioning is the reader's page.
"""

from __future__ import annotations

__version__ = "2.0.0a1"

#: Semantic version of the grading apparatus. Changing belt semantics, the
#: size-tier table, the change-class taxonomy or the routing rule MUST bump
#: this and be recorded in an ADR.
#: History: 2.0 (reboot) → 2.1 (2026-09-14, Wave A: belt 1 covers test infrastructure and
#: every non-target test file [ADR-0001 amendment]; routing gated on the negative-controls
#: verdict [ADR-0003 amendment]; intent-resolved change class [ARCHITECTURE §7.5];
#: polyglot controls.v2 [ADR-0010]). Rows stamped 2.0 are never blended with 2.1.
#: 2.1 → 2.2 (2026-09-14, Wave B: belt 5 ``repo_lint_clean`` — the repository's own
#: formatter/linter on the changed files, ``belt_set="v5"``, failure kind ``lint``
#: [ADR-0011]). Rows stamped 2.1 (``v4``) keep their four-belt meaning; belt 5 is
#: unrecorded for them, never re-derived.
APPARATUS_VERSION = "2.2"
