"""Every row of the prevention register tags the finding it states (P-109).

Navigation
----------
What it is:   The claim-tag rule applied to the rows of ``docs/PREVENTION.md``, which the
              claims gate cannot see because it skips tables.
What it does: Reads each register row and fails when its bug and first-seen cells carry no
              permitted tag (``[measured]``, ``[hypothesis]``, ``[aspiration]``, ``[gap]``),
              or carry a ``[measured]`` tag without its n, its method and its apparatus
              version.
How:          The register's ``P-nnn`` table rows, read by the claims gate's own CommonMark
              parser so a row is read however it is indented or spaced; the tag check is
              ``scripts/claims_check.py``'s own ``tag_defects``, loaded from the script, so
              the two can never disagree on what a complete tag is.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/PREVENTION.md (the register it reads), scripts/claims_check.py
              (``tag_defects``), docs/EVIDENCE-AND-CLAIMS.md (the claim-tag rule)
Tested by:    tests/test_prevention_register.py
Touch when:   never for a new repository (the register records the product's own bugs,
              not a client's); the register gains a column, or the claims gate's tag rule
              changes.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "PREVENTION.md"
_ID_RE = re.compile(r"P-\d+")


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


def register_rows(text: str) -> list[list[str]]:
    """The cells of every table row whose first cell is a ``P-nnn`` id, read by the claims
    gate's own CommonMark parser (tables on, as GitHub renders them): a row is a row however
    it is indented or spaced, and an example inside a fence is not one (P-113)."""
    rows: list[list[str]] = []
    cells: list[str] | None = None
    for token in _claims_check()._MARKDOWN.parse(text):
        if token.type == "tr_open":
            cells = []
        elif token.type == "inline" and cells is not None:
            cells.append(token.content.strip())
        elif token.type == "tr_close" and cells is not None:
            if cells and _ID_RE.fullmatch(cells[0]):
                rows.append(cells)
            cells = None
    return rows


def _rows() -> list[list[str]]:
    return register_rows(REGISTER.read_text(encoding="utf-8"))


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


def test_the_row_reader_sees_every_row_markdown_renders() -> None:
    """Every row Markdown renders as a register row is read — indented, with no space after
    the pipe or with no leading pipe — and an example inside a fence is not a row (P-113)."""
    page = (
        "| id | bug | class | first seen |\n"
        "|---|---|---|---|\n"
        "| P-900 | a bug | a-class | 2026-09-27 [hypothesis] |\n"
        "  | P-901 | a bug | a-class | a review, 2026-09-27 |\n"
        "|P-902| a bug | a-class | a review, 2026-09-27 |\n"
        "P-903 | a bug | a-class | a review, 2026-09-27 |\n"
        "\n"
        "```\n| P-904 | an example in a fence is not a row | x | y |\n```\n"
    )
    assert [r[0] for r in register_rows(page)] == ["P-900", "P-901", "P-902", "P-903"]
    tag_defects = _claims_check().tag_defects
    owed = [d for cells in register_rows(page) for d in row_defects(cells, tag_defects)]
    assert [d.split(":", 1)[0] for d in owed] == ["P-901", "P-902", "P-903"]
