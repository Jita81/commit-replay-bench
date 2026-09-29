"""crb.core.quality_model — the quality baseline, named and never claimed (ADR-0026 item 11).

Navigation
----------
What it is:   Unit tests for the ISO/IEC 25010:2023 characteristic-to-check table.
What it does: Pins that every one of the standard's nine characteristics appears exactly
              once; that belt 3 counts under functional correctness only (never under
              reliability); that belt 6 ``api_stable`` counts as modifiability and is only
              an argued secondary of compatibility, which is not counted; that the belts
              evidence exactly two characteristics; that every counted check says when it
              runs; and that the table in docs/EVIDENCE-AND-CLAIMS.md §9 is the one the data
              renders, so the guide cannot drift from the product.
How:          Reads ``QUALITY_MODEL`` directly and compares ``render_table()`` with the
              table under the guide's §9 heading.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 11)
Works with:   src/crb/core/quality_model.py (the code under test),
              docs/EVIDENCE-AND-CLAIMS.md §9 (the guide's copy of the table),
              scripts/claims_check.py (refuses a conformity claim; tests/test_claims_check.py)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a check starts or stops evidencing a characteristic —
              change the data, the guide and ADR-0026's table together.
"""

from __future__ import annotations

import re
from pathlib import Path

from crb.core import quality_model as qm

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "EVIDENCE-AND-CLAIMS.md"

#: ISO/IEC 25010:2023's product quality characteristics, in the standard's order.
ISO_25010_2023 = (
    "Functional suitability",
    "Performance efficiency",
    "Compatibility",
    "Interaction capability",
    "Reliability",
    "Security",
    "Maintainability",
    "Flexibility",
    "Safety",
)


def _by_name() -> dict[str, qm.Characteristic]:
    return {c.name: c for c in qm.QUALITY_MODEL}


def test_every_iso_25010_characteristic_appears_once() -> None:
    names = [c.name for c in qm.QUALITY_MODEL]
    assert names == list(ISO_25010_2023)
    assert len(set(names)) == len(names)
    assert qm.STANDARD == "ISO/IEC 25010:2023"


def test_belt_3_is_counted_under_functional_correctness_only() -> None:
    holders = [c for c in qm.QUALITY_MODEL if "no_new_failures" in {k.check for k in c.counted}]
    assert [c.name for c in holders] == ["Functional suitability"]
    belt3 = next(k for k in holders[0].counted if k.check == "no_new_failures")
    assert belt3.sub == "functional correctness"
    reliability = _by_name()["Reliability"]
    assert reliability.counted == ()
    assert not reliability.evidenced
    assert "no_new_failures" not in {k.check for k in reliability.secondary}


def test_api_stable_is_modifiability_and_compatibility_is_an_argued_secondary() -> None:
    maintainability = _by_name()["Maintainability"]
    api = [k for k in maintainability.counted if k.check == "api_stable"]
    assert len(api) == 1 and api[0].sub == "modifiability"
    assert "switched on" in api[0].runs
    compatibility = _by_name()["Compatibility"]
    assert compatibility.counted == ()
    assert not compatibility.evidenced
    assert [k.check for k in compatibility.secondary] == ["api_stable"]
    assert "not counted" in compatibility.note
    # nowhere else does api_stable count
    counted_api = [c.name for c in qm.QUALITY_MODEL if "api_stable" in {k.check for k in c.counted}]
    assert counted_api == ["Maintainability"]


def test_the_belts_evidence_two_characteristics() -> None:
    assert qm.evidenced() == ("Functional suitability", "Maintainability")
    functional = _by_name()["Functional suitability"]
    assert {k.check for k in functional.counted} >= {"target_green", "no_new_failures"}
    maintainability = _by_name()["Maintainability"]
    assert {k.check for k in maintainability.counted} >= {"repo_lint_clean", "format_step"}
    lint = next(k for k in maintainability.counted if k.check == "repo_lint_clean")
    assert "configures a linter" in lint.runs
    # the instrument's own integrity checks are not a product quality
    counted = {k.check for c in qm.QUALITY_MODEL for k in c.counted}
    assert not counted & {"tests_unmodified", "source_changed", "controls", "mutation"}
    for c in qm.QUALITY_MODEL:
        if c.name not in qm.evidenced():
            assert c.counted == () and c.evidenced is False
        for k in c.counted:
            assert k.runs, f"{k.check} under {c.name} does not say when it runs"
    assert "not evidenced" in qm.ISO_5055


def _guide_table() -> list[str]:
    text = GUIDE.read_text(encoding="utf-8")
    m = re.search(r"^## 9\. .*$", text, re.M)
    assert m, "docs/EVIDENCE-AND-CLAIMS.md has no §9"
    section = text[m.end() :]
    nxt = re.search(r"^## ", section, re.M)
    section = section[: nxt.start()] if nxt else section
    return [ln for ln in section.splitlines() if ln.startswith("|")]


def test_the_guide_table_matches_the_data() -> None:
    rendered = qm.render_table().splitlines()
    assert rendered[0].startswith("| ISO/IEC 25010:2023 characteristic")
    assert _guide_table() == rendered
