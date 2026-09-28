"""The words about the sign-off clause say no more than the clause does (P-156).

ADR-0018's sign-off clause stops an item before any spend only when its cell routes
``deliver`` and nobody has signed that cell: :func:`crb.factory.loop.unsigned_cell_reason`
returns nothing for any other route. Only a deliver cell can be signed, so every cell that
routes calibrate, human or nothing is also a cell "nobody has signed" — and an item there IS
built, with its delivery withheld. Stream S's copy on the Posture and Factory screens and in
three hints said "an item in a cell nobody has signed off is not built at all": a rule wider
than the code, which a reader would act on. This file holds the words to the code's scope:
every clause in the product's copy that pairs signing with "not built" names the deliver
route in the same clause.

Navigation
----------
What it is:   The copy gate for the sign-off clause's scope, and the anchor that ties it to
              the rule it describes.
What it does: Splits the UI's copy (every non-test ``.ts``/``.tsx`` under ``ui/src``), the
              docs and the README into clauses at ``. ; : ! ?`` and line ends, and fails on a
              clause that speaks of signing (sign, unsigned, attest) and says an item is not
              built without naming ``deliver``; proves the rule catches the five sentences
              it was written for; and pins that the clause itself is scoped to deliver cells.
How:          ``re`` over the files; ``unsigned_cell_reason`` called directly.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0018-a-signed-cell-licenses-delivery.md
Works with:   src/crb/factory/loop.py (``unsigned_cell_reason`` — the rule the words
              describe), ui/src/screens/Posture/PosturePage.tsx and
              ui/src/screens/Factory/FactoryPage.tsx (the rows and sentences that said too
              much), ui/src/help/hints.ts and ui/src/help/help.ts (the hints), docs/PREVENTION.md
              (P-156)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the sign-off clause changes scope (change the
              anchor with the rule, and the words with both).
"""

from __future__ import annotations

import re
from pathlib import Path

from crb.factory.loop import unsigned_cell_reason

ROOT = Path(__file__).resolve().parent.parent
_NOT_BUILT = re.compile(
    r"\b(?:is|are) not built\b|\bdoes not build\b|\bnot be built\b|\bis never built\b"
)
_SIGNING = re.compile(r"\bsign|\bunsigned\b|\battest", re.IGNORECASE)
_BREAK = re.compile(r"[.;:!?\n]")


def overclaims(text: str) -> list[str]:
    """Every clause of ``text`` that pairs signing with "not built" and does not name the
    deliver route."""
    out: list[str] = []
    for m in _NOT_BUILT.finditer(text):
        start = max((b.end() for b in _BREAK.finditer(text, 0, m.start())), default=0)
        after = _BREAK.search(text, m.end())
        clause = text[start : after.start() if after else len(text)]
        if _SIGNING.search(clause) and "deliver" not in clause.lower():
            out.append(clause.strip())
    return out


def _copy_files() -> list[Path]:
    ui = [
        p
        for p in (ROOT / "ui" / "src").rglob("*")
        if p.suffix in {".ts", ".tsx"} and ".test." not in p.name and "node_modules" not in p.parts
    ]
    return [*ui, *(ROOT / "docs").rglob("*.md"), ROOT / "README.md"]


def test_no_copy_says_an_unsigned_cell_is_not_built_without_naming_the_deliver_route() -> None:
    found = {
        str(p.relative_to(ROOT)): hits
        for p in _copy_files()
        if (hits := overclaims(p.read_text(encoding="utf-8", errors="replace")))
    }
    assert found == {}, (
        "the sign-off clause stops an item only in a cell that routes deliver; say so in the "
        f"same clause: {found}"
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
    fixed = "an item in a deliver cell nobody has signed off is not built at all"
    assert overclaims(fixed) == []
    # a "not built" that is not about signing is somebody else's sentence
    assert overclaims("a task that is not proven there is never built") == []


def test_the_clause_the_words_describe_bites_only_on_a_deliver_route() -> None:
    for route in ("calibrate", "human", "do_not_ship"):
        assert unsigned_cell_reason({"route": route}, require_signed_cell=True) == ""
    assert unsigned_cell_reason(
        {"route": "deliver", "verification_tier": "automated-pass"}, require_signed_cell=True
    )
