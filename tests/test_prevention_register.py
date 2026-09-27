"""Every row of the prevention register tags the finding it states (P-109).

Navigation
----------
What it is:   The claim-tag rule applied to the rows of ``docs/PREVENTION.md``, which the
              claims gate cannot see because it skips tables.
What it does: Reads each register row and fails when its bug and first-seen cells carry no
              permitted tag (``[measured]``, ``[hypothesis]``, ``[aspiration]``, ``[gap]``),
              or carry a ``[measured]`` tag without its n, its method and its apparatus
              version.
How:          The register's ``| P-nnn |`` rows split into cells; the tag check is
              ``scripts/claims_check.py``'s own ``tag_defects``, loaded from the script, so
              the two can never disagree on what a complete tag is.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/PREVENTION.md (the register it reads), scripts/claims_check.py
              (``tag_defects``), docs/EVIDENCE-AND-CLAIMS.md (the claim-tag rule)
Tested by:    tests/test_prevention_register.py
Touch when:   the register gains a column, or the claims gate's tag rule changes.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "PREVENTION.md"


def _claims_check() -> ModuleType:
    if "claims_check" in sys.modules:  # tests/test_claims_check.py loads it the same way
        return sys.modules["claims_check"]
    spec = importlib.util.spec_from_file_location(
        "claims_check", ROOT / "scripts" / "claims_check.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["claims_check"] = mod  # its dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


def _rows() -> list[list[str]]:
    lines = REGISTER.read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line.startswith("| P-")]
    return [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]


def row_defects(cells: list[str], tag_defects: Callable[[str], list[str] | None]) -> list[str]:
    """What a register row still owes: a tag on its finding, and a complete ``[measured]``."""
    pid, bug, _cls, seen = cells[:4]
    owed = tag_defects(f"{bug} {seen}")
    if owed is None:
        return [f"{pid}: its finding carries no [measured]/[hypothesis]/[aspiration]/[gap] tag"]
    return [f"{pid}: {d}" for d in owed]


def test_the_register_has_rows() -> None:
    assert len(_rows()) >= 1


def test_every_register_row_tags_the_finding_it_states() -> None:
    """PR #61 review: P-103 to P-106 stated findings — "found two flows" among them — with
    no tag, no n, no method and no apparatus."""
    tag_defects = _claims_check().tag_defects
    owed = [d for cells in _rows() for d in row_defects(cells, tag_defects)]
    assert owed == [], owed


def test_the_row_check_refuses_an_untagged_and_an_incomplete_measured_row() -> None:
    tag_defects = _claims_check().tag_defects
    untagged = ["P-900", "a bug", "a-class", "a review, 2026-09-27"]
    thin = ["P-901", "a bug", "a-class", "2026-09-27 [measured — n = 2]"]
    whole = [
        "P-902",
        "a bug",
        "a-class",
        "2026-09-27 [measured — n = 2 runs; method: the guard run on the old tree; apparatus 2.3]",
    ]
    assert row_defects(untagged, tag_defects) != []
    assert row_defects(thin, tag_defects) != []
    assert row_defects(whole, tag_defects) == []
