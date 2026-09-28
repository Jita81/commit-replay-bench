"""The quality baseline — ISO/IEC 25010:2023 named, never claimed (ADR-0026 item 11).

A clean row says the repository's own tests passed and, where configured, its own linter
accepted the change. A reader asking "which qualities does that evidence?" needs a named
model to answer against, and the answer must never grow into a conformity claim. This module
is that answer as data: each of the nine product quality characteristics of ISO/IEC
25010:2023, the product's checks that evidence *part* of it (by name, with when each runs),
and — for every other characteristic — "not evidenced".

The belts evidence parts of two characteristics: functional suitability (functional
correctness — belts 2 and 3, and the review verdicts ``defect`` and ``regression``) and
maintainability (belt 5 where the repository configures a linter, the format step, belt 6
``api_stable`` as modifiability where it is switched on, and the review verdicts ``style``
and ``api_change``). Belt 3 is regression correctness and counts under functional
suitability only. Compatibility is named only as belt 6's argued secondary and is not
counted. Belts 1 and 4, the negative controls and mutation strength evidence the
instrument's integrity, not a product quality, so they appear nowhere here. None of ISO/IEC
5055's measures is computed.

Nothing here certifies that code conforms to any standard: ``scripts/claims_check.py``
refuses a sentence that says so in README, the bundled guides and the factory's pull-request
body template.

Navigation
----------
What it is:   The ISO/IEC 25010:2023 characteristic-to-check table (``QUALITY_MODEL``), the
              characteristics it counts as evidenced (``evidenced``), the ISO/IEC 5055 line
              and the Markdown rendering the guide carries (``render_table``).
What it does: Names, for each characteristic, the checks counted as evidence of part of it
              and when each runs, the checks argued as a secondary but not counted, and a
              note; renders that as the table in docs/EVIDENCE-AND-CLAIMS.md §9.
How:          Frozen dataclasses and a tuple; standard library only (ADR-0008).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 11), docs/adr/0011-repo-lint-belt.md,
              docs/adr/0024-working-by-construction.md
Works with:   src/crb/core/grade.py (the belts named here), src/crb/core/checks.py (the format
              step and belt 6 switches), src/crb/core/review.py (the review verdicts),
              docs/EVIDENCE-AND-CLAIMS.md §9 (the guide's copy of the table),
              scripts/claims_check.py (refuses a conformity claim)
Tested by:    tests/test_quality_model.py
Touch when:   a check starts or stops evidencing a characteristic — change this table, the
              guide (§9, regenerated from ``render_table``) and ADR-0026's table together.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The standard the table names — never one the product claims conformity with.
STANDARD = "ISO/IEC 25010:2023"

#: ISO/IEC 5055's measures: none is computed. One may enter only as the repository's own
#: analyser run as a gate (ADR-0011), never as prose.
ISO_5055 = (
    "ISO/IEC 5055: not evidenced — none of its measures is computed; one may enter only as "
    "the repository's own analyser, run as a gate (ADR-0011)"
)

_EVERY_GRADE = "at every grade: every replay and factory attempt that reaches the grader"
_LINT = "at every grade, only where the repository configures a linter"
_FORMAT = "before the grade, only where `checks.format_step` is switched on"
_API = "at every grade, only where `checks.api_stable` is switched on"
_REVIEW = "when a person reviews an accepted row or a factory pull request"


@dataclass(frozen=True)
class Evidence:
    """One check, the sub-characteristic it evidences part of, and when it runs."""

    check: str
    label: str
    sub: str
    runs: str


@dataclass(frozen=True)
class Characteristic:
    """One ISO/IEC 25010:2023 characteristic and what the product's checks say about it."""

    name: str
    counted: tuple[Evidence, ...]
    secondary: tuple[Evidence, ...]
    note: str

    @property
    def evidenced(self) -> bool:
        """At least one check is counted as evidence of part of this characteristic."""
        return bool(self.counted)


_BELT_2 = Evidence("target_green", "belt 2 `target_green`", "functional correctness", _EVERY_GRADE)
_BELT_3 = Evidence(
    "no_new_failures", "belt 3 `no_new_failures`", "functional correctness", _EVERY_GRADE
)
_DEFECT = Evidence("defect", "review verdict `defect`", "functional correctness", _REVIEW)
_REGRESSION = Evidence(
    "regression", "review verdict `regression`", "functional correctness", _REVIEW
)
_BELT_5 = Evidence("repo_lint_clean", "belt 5 `repo_lint_clean`", "analysability", _LINT)
_FORMAT_STEP = Evidence("format_step", "the format step", "analysability", _FORMAT)
_BELT_6 = Evidence("api_stable", "belt 6 `api_stable`", "modifiability", _API)
_BELT_6_COMPAT = Evidence("api_stable", "belt 6 `api_stable`", "interoperability", _API)
_STYLE = Evidence("style", "review verdict `style`", "analysability", _REVIEW)
_API_CHANGE = Evidence("api_change", "review verdict `api_change`", "modifiability", _REVIEW)

_NOT_EVIDENCED = "not evidenced"

#: The table, in the standard's order. Every characteristic appears exactly once.
QUALITY_MODEL: tuple[Characteristic, ...] = (
    Characteristic(
        "Functional suitability",
        (_BELT_2, _BELT_3, _DEFECT, _REGRESSION),
        (),
        "completeness only as far as the tests assert; mutation strength says how far to "
        "trust them; belt 3 is regression correctness and counts here only",
    ),
    Characteristic("Performance efficiency", (), (), _NOT_EVIDENCED),
    Characteristic(
        "Compatibility",
        (),
        (_BELT_6_COMPAT,),
        "not evidenced; belt 6 is argued as a secondary here and not counted",
    ),
    Characteristic("Interaction capability", (), (), _NOT_EVIDENCED),
    Characteristic(
        "Reliability",
        (),
        (),
        "not evidenced; belt 3 is regression correctness and counts under functional "
        "suitability only",
    ),
    Characteristic(
        "Security",
        (),
        (),
        "not evidenced; F31 proposes the repository's own security scanner as a review probe",
    ),
    Characteristic(
        "Maintainability",
        (_BELT_5, _FORMAT_STEP, _BELT_6, _STYLE, _API_CHANGE),
        (),
        "by the repository's own rules, not ISO/IEC 5055's",
    ),
    Characteristic("Flexibility", (), (), _NOT_EVIDENCED),
    Characteristic("Safety", (), (), _NOT_EVIDENCED),
)


def evidenced() -> tuple[str, ...]:
    """The characteristics at least one check is counted as evidence of part of."""
    return tuple(c.name for c in QUALITY_MODEL if c.evidenced)


def _cell(items: tuple[Evidence, ...]) -> str:
    if not items:
        return "—"
    return "; ".join(f"{e.label} ({e.sub}) — {e.runs}" for e in items)


def render_table() -> str:
    """The table as Markdown — docs/EVIDENCE-AND-CLAIMS.md §9 carries exactly this."""
    rows = [
        f"| {STANDARD} characteristic | counted as evidence of part of it, and when each runs "
        "| argued secondary, not counted | note |",
        "|---|---|---|---|",
    ]
    for c in QUALITY_MODEL:
        rows.append(f"| {c.name} | {_cell(c.counted)} | {_cell(c.secondary)} | {c.note} |")
    return "\n".join(rows)
