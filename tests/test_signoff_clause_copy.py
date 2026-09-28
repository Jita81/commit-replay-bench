"""The words about the sign-off clause say no more than the clause does (P-328).

ADR-0018's sign-off clause, as ADR-0026 item 8 amends it, stops an item before any spend only
when its cell has a PROVEN context standard that nobody has signed off: the entry gate
(:func:`crb.factory.standard.decide_entry`) stops a cell with no standard, or only an ``S3``
ceiling, as ``no_proven_standard`` — another stop, with another way forward — never as
``unsigned_cell``. Stream S's copy said "an item in a cell nobody has signed off is not built
at all": a rule wider than the code, which a reader would act on. This file holds the words to
the code's scope: every clause in the product's copy that pairs signing with "not built" names
the standard (or the deliver route the screen predicts from) in the same clause.

Navigation
----------
What it is:   The copy gate for the sign-off clause's scope, and the anchor that ties it to
              the rule it describes.
What it does: Splits the UI's copy (every non-test ``.ts``/``.tsx`` under ``ui/src``), the
              docs and the README into clauses at ``. ; : ! ?`` and line ends, and fails on a
              clause that speaks of signing (sign, unsigned, attest) and says an item is not
              built without naming the standard or ``deliver``; proves the rule catches the
              sentences it was written for; and pins that the clause itself bites only on a
              proven standard.
How:          ``re`` over the files; ``decide_entry`` called directly.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0018-a-signed-cell-licenses-delivery.md,
              docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/factory/standard.py (``decide_entry`` — the rule the words describe),
              ui/src/screens/Posture/PosturePage.tsx and ui/src/screens/Factory/FactoryPage.tsx
              (the rows and sentences that said too much), ui/src/help/hints.ts and
              ui/src/help/help.ts (the hints), docs/PREVENTION.md (P-328)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the sign-off clause changes scope (change the
              anchor with the rule, and the words with both).
"""

from __future__ import annotations

import re
from pathlib import Path

from crb.factory.standard import (
    STOP_NO_PROVEN_STANDARD,
    STOP_UNSIGNED_CELL,
    CellRef,
    Standard,
    decide_entry,
)

ROOT = Path(__file__).resolve().parent.parent
_NOT_BUILT = re.compile(
    r"\b(?:is|are) not built\b|\bdoes not build\b|\bnot be built\b|\bis never built\b"
)
_SIGNING = re.compile(r"\bsign|\bunsigned\b|\battest", re.IGNORECASE)
_BREAK = re.compile(r"[.;:!?\n]")


def overclaims(text: str) -> list[str]:
    """Every clause of ``text`` that pairs signing with "not built" and names neither the
    standard nor the deliver route."""
    out: list[str] = []
    for m in _NOT_BUILT.finditer(text):
        start = max((b.end() for b in _BREAK.finditer(text, 0, m.start())), default=0)
        after = _BREAK.search(text, m.end())
        clause = text[start : after.start() if after else len(text)]
        low = clause.lower()
        if _SIGNING.search(clause) and "deliver" not in low and "standard" not in low:
            out.append(clause.strip())
    return out


def _copy_files() -> list[Path]:
    ui = [
        p
        for p in (ROOT / "ui" / "src").rglob("*")
        if p.suffix in {".ts", ".tsx"} and ".test." not in p.name and "node_modules" not in p.parts
    ]
    return [*ui, *(ROOT / "docs").rglob("*.md"), ROOT / "README.md"]


def test_no_copy_says_an_unsigned_cell_is_not_built_without_naming_the_standard() -> None:
    found = {
        str(p.relative_to(ROOT)): hits
        for p in _copy_files()
        if (hits := overclaims(p.read_text(encoding="utf-8", errors="replace")))
    }
    assert found == {}, (
        "the sign-off clause stops an item only in a cell whose proven standard nobody has "
        f"signed; say so in the same clause: {found}"
    )


def test_the_gate_catches_the_sentences_it_was_written_for() -> None:
    said = [
        "the factory does not build an item in a cell until a person has attested that cell",
        "from today; an item in a cell nobody has signed off is not built at all, and one",
        "nobody has signed this cell off, so an item here is not built at all unless",
        "An item in an unsigned cell is not built at all; one elsewhere is withheld.",
        "Without the sign-off an item is not built at all.",
    ]
    for sentence in said:
        assert overclaims(sentence), sentence
    fixed = "an item whose cell's standard nobody has signed off is not built at all"
    assert overclaims(fixed) == []
    assert overclaims("an item in a deliver cell nobody has signed off is not built at all") == []
    # a "not built" that is not about signing is somebody else's sentence
    assert overclaims("a task that is not proven there is never built") == []


def _entry(standard: Standard | None) -> str:
    return decide_entry(
        capability_class="bug.fix",
        size="S",
        standard_for=lambda _cell: standard,
        agreement_passed=True,
        missing_slots=(),
        person_test=True,
        require_signed_cell=True,
    ).code


def test_the_clause_the_words_describe_bites_only_on_a_proven_standard() -> None:
    # no standard, or only a ceiling: another stop, never the sign-off clause's
    assert _entry(None) == STOP_NO_PROVEN_STANDARD
    assert _entry(Standard("S3", signed=True)) == STOP_NO_PROVEN_STANDARD
    # a proven standard nobody signed: the clause, and only then
    assert _entry(Standard("S2", signed=False)) == STOP_UNSIGNED_CELL
    assert _entry(Standard("S2", signed=True)) == ""
    assert CellRef("bug.fix", "S").size == "S"  # the cell the gate read
