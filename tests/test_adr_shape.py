"""Every recent ADR keeps the house shape: a decision-log row, the same headings, 100 columns.

ADR-0020 (the value wave) left 120 paragraphs unwrapped, cited no decision-log row in its
status, and its sibling ADR-0021 named its last section "Alternatives rejected" with no row in
the decision log at all; nothing checked any of it (docs/PREVENTION.md P-036).

Navigation
----------
What it is:   The shape ratchet over the ADRs written since the decision log began naming them
              (ADR-0015 on).
What it does: Pins that each such ADR's status cites a ``DL-NNN`` row that exists in
              docs/DECISION-LOG.md; that it has the house sections (Context, Decision,
              Consequences, Alternatives considered); and — for ADR-0020 on — that the row
              names the ADR back, is final (not "may be renumbered"), and that no prose line is
              wider than 100 columns (headings and tables aside).
How:          Reads the Markdown files; no parser beyond line and regex checks.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/README.md (the index and the house shape)
Works with:   docs/adr/0015-signoffs-expire-with-the-apparatus.md (the shape it follows),
              docs/DECISION-LOG.md (the rows the status lines cite), docs/PREVENTION.md (P-036,
              the class it stops), tests/test_header_width.py (the same width rule for code)
Tested by:    tests/test_adr_shape.py
Touch when:   an ADR is added (it is picked up by number) or the house shape changes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ADRS = ROOT / "docs" / "adr"
LOG = (ROOT / "docs" / "DECISION-LOG.md").read_text(encoding="utf-8")
FIRST_WITH_A_ROW = 15
FIRST_WRAPPED = 20
SECTIONS = ("## Context", "## Decision", "## Consequences", "## Alternatives considered")


def _recent() -> list[Path]:
    out = []
    for p in sorted(ADRS.glob("[0-9][0-9][0-9][0-9]-*.md")):
        if int(p.name[:4]) >= FIRST_WITH_A_ROW:
            out.append(p)
    return out


@pytest.mark.parametrize("adr", _recent(), ids=lambda p: p.name[:4])
def test_an_adr_cites_its_decision_log_row_and_keeps_the_house_sections(adr: Path) -> None:
    text = adr.read_text(encoding="utf-8")
    status = next((ln for ln in text.splitlines() if ln.startswith("**Status:**")), "")
    m = re.search(r"\bDL-(\d{3})\b", status)
    assert m, f"{adr.name}: the status cites no decision-log row: {status!r}"
    row = next((ln for ln in LOG.splitlines() if ln.startswith(f"| DL-{m.group(1)} |")), "")
    assert row, f"{adr.name}: DL-{m.group(1)} is not in docs/DECISION-LOG.md"
    if int(adr.name[:4]) >= FIRST_WRAPPED:
        assert f"ADR-{adr.name[:4]}" in row, f"DL-{m.group(1)} does not name ADR-{adr.name[:4]}"
        assert "may be renumbered" not in row
    for heading in SECTIONS:
        assert any(ln.startswith(heading) for ln in text.splitlines()), (
            f"{adr.name}: no '{heading}' section"
        )
    if int(adr.name[:4]) >= FIRST_WRAPPED:
        wide = [
            i
            for i, ln in enumerate(text.splitlines(), start=1)
            if len(ln) > 100 and not ln.lstrip().startswith(("|", "#"))
        ]
        assert not wide, f"{adr.name}: prose lines wider than 100 columns at {wide}"
