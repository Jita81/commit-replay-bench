"""No public page says the same thing twice: a paragraph repeated back to back, or an API
route row written twice, is an edit applied twice — the mark a resumed build leaves (P-650).

The definition-of-done checker and the claims gate read a duplicated paragraph as fine (every
claim still resolves), so nothing else in the suite sees it. This one does.

Navigation
----------
What it is:   The duplicate-text ratchet for the public documentation.
What it does: Fails when any Markdown page under docs/, the changelog or the README carries
              the same paragraph twice in a row (a paragraph is a block between blank lines,
              compared whole once whitespace is folded; short blocks — a heading, a rule — are
              ignored), and when docs/API.md's route table carries the same route row twice
              anywhere. Generated tables (docs/dod/GAP-ANALYSIS.md) are the checker's own and
              are not paragraphs a person wrote, so they are skipped; a dated report under
              docs/reviews/ repeats its tables on purpose and is skipped too.
How:          ``re.split`` on blank lines; a route row is a table line whose first cell is an
              HTTP method.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   docs/ONBOARDING-A-REPO.md and docs/API.md (where the first duplicates were found),
              scripts/dod_check.py (which does not see a duplicate), tests/test_public_docs.py
              (the other drift tests on the same pages), docs/PREVENTION.md (P-650)
Tested by:    tests/test_doc_duplicates.py
Touch when:   never for a new repository; a page repeats a block on purpose (say why here and
              exempt the path), or a second generated page is added (skip it as GAP-ANALYSIS is).
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
#: Pages whose repeated blocks are generated or deliberate, never a slip.
SKIPPED = ("docs/dod/GAP-ANALYSIS.md", "docs/reviews/")
#: Blocks shorter than this (a heading, a rule, a one-word cell) are not paragraphs.
MIN_CHARS = 40
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def pages() -> list[Path]:
    out = [
        p for p in sorted(DOCS.rglob("*.md")) if not str(p.relative_to(ROOT)).startswith(SKIPPED)
    ]
    return [ROOT / "README.md", ROOT / "CHANGELOG.md", *out]


def repeated_paragraphs(text: str) -> list[str]:
    """Every paragraph that is followed immediately by itself (whitespace folded)."""
    blocks = [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*\n", text)]
    blocks = [b for b in blocks if b]
    return [a for a, b in pairwise(blocks) if a == b and len(a) >= MIN_CHARS]


def repeated_route_rows(text: str) -> list[str]:
    """Every route row (``| GET | `/path` | …``) that appears more than once."""
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3 or cells[1] not in METHODS:
            continue
        if line in seen and line not in out:
            out.append(line)
        seen.add(line)
    return out


def test_no_public_page_repeats_a_paragraph_back_to_back() -> None:
    found = {
        str(p.relative_to(ROOT)): [
            d[:80] for d in repeated_paragraphs(p.read_text(encoding="utf-8"))
        ]
        for p in pages()
    }
    found = {k: v for k, v in found.items() if v}
    assert not found, "a paragraph written twice in a row (an edit applied twice?):\n" + "\n".join(
        f"{k}: {v}" for k, v in sorted(found.items())
    )


def test_no_api_route_row_appears_twice() -> None:
    rows = repeated_route_rows((DOCS / "API.md").read_text(encoding="utf-8"))
    assert not rows, "route rows written twice in docs/API.md:\n" + "\n".join(r[:100] for r in rows)


def test_the_detector_sees_a_repeated_paragraph_and_a_repeated_row() -> None:
    para = "The notes become proposals, not edits, and the same words twice are the mark of a resumed edit."
    assert repeated_paragraphs(f"# Title\n\n{para}\n\n{para}\n\nNext paragraph, different.\n") == [
        para
    ]
    # folded whitespace: a re-wrapped copy is still the same paragraph
    assert repeated_paragraphs(f"{para}\n\n{para.replace(' edits,', ' edits,\n')}") == [para]
    # a short block (a heading) repeated is not a paragraph
    assert repeated_paragraphs("## Gaps\n\n## Gaps\n") == []
    row = "| GET | `/repos/{name}/config-candidates` | viewer | the candidates |"
    assert repeated_route_rows(f"| a | b |\n{row}\n| POST | `/x` | operator | y |\n{row}\n") == [
        row
    ]
    assert repeated_route_rows(f"{row}\n") == []
