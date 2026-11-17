"""Tests for the accepted-plan body, its renderer and its fixed limits (ADR-0054).

Navigation
----------
What it is:   Tests for ``crb.core.plan``: ``PlanBody``, ``render``, ``shape_violation``,
              ``length_violation`` and ``plan_from_doc``.
What it does: Pins the rendered text byte for byte (the header, the section headings, the
              numbered steps, an empty section left out); that the renderer refuses a plan
              that breaks its shape; each shape and limit rule; and the document round trip.
How:          Pure function calls; no git, no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0054-accepted-plan-context-arm.md
Works with:   src/crb/core/plan.py (the module under test), src/crb/core/ctxset.py (the v3
              parser that reads it), src/crb/builders/brief.py (``plan_guard``, which
              re-renders a plan)
Tested by:    this file
Touch when:   never for a new repository; a section, the renderer or a limit changes (an ADR
              first).
"""

from __future__ import annotations

import pytest

from crb.core import plan as p
from crb.core.plan import PlanBody

FULL = PlanBody(
    summary=("Refuse an empty name",),
    files=("src/app/names.py",),
    steps=("Check the name first", "Raise an error when it is empty"),
    decisions=("Existing callers keep working",),
    tests=("A test that an empty name is refused",),
)


def test_the_rendering_is_fixed_byte_for_byte() -> None:
    assert p.render(FULL) == (
        "Implementation plan for this change:\n"
        "Summary:\n"
        "- Refuse an empty name\n"
        "Files:\n"
        "- src/app/names.py\n"
        "Steps:\n"
        "1. Check the name first\n"
        "2. Raise an error when it is empty\n"
        "Decisions:\n"
        "- Existing callers keep working\n"
        "Tests:\n"
        "- A test that an empty name is refused"
    )


def test_the_header_and_headings_claim_nothing_the_set_may_not_hold() -> None:
    """The frame is the same for every plan set: whether the plan was accepted, and what its
    drafter saw, are row stamps, never words the builder reads (ADR-0054 item 2)."""
    frame = " ".join((p.PLAN_HEADER, *p.SECTION_HEADINGS.values())).lower()
    for claim in ("accepted", "settled", "agreed", "reviewed", "ticket", "tree", "before"):
        assert claim not in frame, claim


def test_an_empty_optional_section_is_left_out() -> None:
    bare = PlanBody(summary=("Do it",), steps=("One step",))
    assert p.render(bare) == f"{p.PLAN_HEADER}\nSummary:\n- Do it\nSteps:\n1. One step"
    assert "Files:" not in p.render(bare)
    assert "Tests:" not in p.render(bare)


def test_lines_and_sections_read_in_render_order() -> None:
    assert FULL.lines() == (*FULL.summary, *FULL.files, *FULL.steps, *FULL.decisions, *FULL.tests)
    with pytest.raises(ValueError):
        FULL.section("notes")


@pytest.mark.parametrize(
    ("plan", "fragment"),
    [
        (PlanBody(summary=(), steps=("x",)), "summary is empty"),
        (PlanBody(summary=("x",)), "steps is empty"),
        (PlanBody(summary=(" x",), steps=("y",)), "trimmed"),
        (PlanBody(summary=("",), steps=("y",)), "trimmed"),
        (PlanBody(summary=("x\ny",), steps=("y",)), "several lines"),
        (PlanBody(summary=("x",), steps=("use ```code```",)), "code fence"),
        (PlanBody(summary=("x",), steps=("use ~~~code~~~",)), "code fence"),
    ],
)
def test_each_shape_rule(plan: PlanBody, fragment: str) -> None:
    assert fragment in p.shape_violation(plan)
    with pytest.raises(ValueError, match="breaks its shape"):
        p.render(plan)


def test_a_well_formed_plan_has_no_shape_or_length_violation() -> None:
    assert p.shape_violation(FULL) == ""
    assert p.length_violation(FULL) == ""


def test_each_fixed_limit() -> None:
    one = ("x",)
    many_lines = PlanBody(summary=one, steps=tuple(f"s{i}" for i in range(p.MAX_LINES)))
    assert "lines" in p.length_violation(many_lines)
    files = PlanBody(summary=one, steps=one, files=tuple(f"f{i}" for i in range(p.MAX_FILES + 1)))
    assert "files" in p.length_violation(files)
    decisions = PlanBody(
        summary=one, steps=one, decisions=tuple(f"d{i}" for i in range(p.MAX_DECISIONS + 1))
    )
    assert "decisions" in p.length_violation(decisions)
    long_line = PlanBody(summary=("x" * (p.MAX_LINE_CHARS + 1),), steps=one)
    assert "characters" in p.length_violation(long_line)
    at_line_limit = PlanBody(summary=("x" * p.MAX_LINE_CHARS,), steps=one)
    assert p.length_violation(at_line_limit) == ""
    wide = PlanBody(summary=one, steps=tuple("y" * 500 for _ in range(17)))
    assert "plan characters" in p.length_violation(wide)
    assert "plan characters" in p.length_violation(FULL, "z" * (p.MAX_PLAN_CHARS + 1))


def test_the_document_round_trips() -> None:
    assert p.plan_from_doc(FULL.to_doc()) == FULL


@pytest.mark.parametrize(
    "doc",
    [
        [],
        {"summary": ["x"], "steps": ["y"]},
        {**FULL.to_doc(), "notes": ["z"]},
        {**FULL.to_doc(), "steps": "one step"},
        {**FULL.to_doc(), "steps": [1]},
    ],
)
def test_a_malformed_document_is_refused(doc: object) -> None:
    with pytest.raises(ValueError):
        p.plan_from_doc(doc)


def test_the_reason_names_and_saw_values_are_fixed() -> None:
    assert p.PLAN_REASONS == (
        "plan_render",
        "plan_length",
        "plan_code_block",
        "plan_test_name",
        "plan_test_path",
        "plan_test_span",
        "plan_gold_span",
        "plan_gold_line",
        "plan_asserted_literal",
        "plan_no_gold",
    )
    assert p.PLAN_SAW_VALUES == ("ticket", "tree")
    for ok in ("human:a", "human:fixture-01", "none"):
        assert p.ACCEPTED_BY_RE.match(ok)
    for bad in ("", "human:", "model:x@y", "None", "human:-x"):
        assert not p.ACCEPTED_BY_RE.match(bad)
