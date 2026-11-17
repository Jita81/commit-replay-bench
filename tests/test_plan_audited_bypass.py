"""The audited-bypass plan arm: an attested blind plan skips only the lookalike checks (ADR-0055).

Navigation
----------
What it is:   Tests for ``compose`` on a ``ctx.plan-audited*`` arm and for the split of the
              plan guard's reasons into structural and lookalike ones.
What it does: Pins that a guarded ``ctx.plan`` arm is unchanged (a lookalike plan is still
              withheld whole); that on an audited arm a plan tripping only lookalike reasons
              is delivered, stamped ``ctx_plan_guard`` = ``audited_bypass`` and
              ``ctx_plan_would_refuse`` with the reasons, never ``ctx_plan_refused``; that a
              structural reason (a text that is not the rendering, no gold view, a broken
              limit) still withholds it; that the blind brief still carries no test files,
              target tests or test command; and the reason partition itself.
How:          Hand-built ``GoldView`` values and plans; pure ``compose`` calls; no git, no
              model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0055-audited-bypass-plan-arm.md, docs/adr/0054-accepted-plan-context-arm.md
Works with:   src/crb/builders/brief.py (``compose``, ``plan_guard``), src/crb/core/plan.py
              (``STRUCTURAL_REASONS``, ``LOOKALIKE_REASONS``), src/crb/core/context_arm.py
              (``audited_plan_arm``), tests/test_brief_plan_guard.py (the guard it splits)
Tested by:    this file
Touch when:   never for a new repository; the reason partition or the audited stamps change
              (an ADR first).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.builders.brief import (
    LABEL_CTX_DELIVERED,
    LABEL_CTX_PLAN_GUARD,
    LABEL_CTX_PLAN_REFUSED,
    LABEL_CTX_PLAN_WOULD_REFUSE,
    LABEL_CTX_REFUSED,
    ContextEntry,
    GoldView,
    Ticket,
    compose,
    plan_guard,
)
from crb.core import context_arm as arms
from crb.core import plan as p
from crb.core.plan import PlanBody

AUDITED_ARM = "A0+library@ctx.plan-audited.0123456789ab"
GUARDED_ARM = "A0+library@ctx.plan.0123456789ab"
PARENT = "a" * 40
TICKET = Ticket("feat: refuse empty names", "feat: refuse empty names")

SRC_AFTER = (
    "def validate(name):\n"
    "    if not name:\n"
    '        raise ValueError("name required")\n'
    "    return name.strip().lower()\n"
)
TEST_AFTER = (
    "def test_validate_refuses_empty_name_quickly():\n"
    "    with pytest.raises(ValueError, match='name required'):\n"
    "        validate('')\n"
)


def gold() -> GoldView:
    return GoldView(
        novel=frozenset({"name required"}),
        parent_has=lambda tok: tok in {"validate"},
        src_after=SRC_AFTER,
        test_after=TEST_AFTER,
        src_added=tuple(SRC_AFTER.splitlines()[1:]),
        test_added=tuple(TEST_AFTER.splitlines()),
        test_paths=("tests/test_validate_names.py",),
    )


def plan(*steps: str) -> PlanBody:
    return PlanBody(summary=("Refuse an empty name",), steps=steps)


#: A plan a blind drafter could write that reads like the held-out test and the change.
LOOKALIKE = plan(
    "Cover test_validate_refuses_empty_name_quickly",
    "raise ValueError name required then return name strip lower",
)
CLEAN = plan("Check the name before it is used", "Raise an error for an empty name")


def entry(body: PlanBody, text: str | None = None) -> ContextEntry:
    return ContextEntry(
        "plan/1",
        p.render(body) if text is None else text,
        "1",
        "2026-11-01T00:00:00Z",
        source_rev=PARENT,
        plan=body,
    )


#: A stored text that is not the plan's rendering (``plan_render``).
NOT_RENDERED = "Implementation plan for this change:\nDo what the tests want."


def _compose(arm: str, *library: ContextEntry, **kw: Any) -> Any:
    kw.setdefault("gold", gold())
    return compose(
        arm,
        TICKET,
        repo="pyrepo",
        language="python",
        mode="blind",
        novel=gold().novel,
        parent_rev=PARENT,
        library=library,
        test_files=("tests/test_validate_names.py",),
        target_tests=("tests/test_validate_names.py::test_validate_refuses_empty_name_quickly",),
        test_command="pytest -q",
        **kw,
    )


def test_the_reasons_split_into_structural_and_lookalike_with_nothing_left_over() -> None:
    assert p.STRUCTURAL_REASONS == (
        p.REASON_RENDER,
        p.REASON_LENGTH,
        p.REASON_CODE_BLOCK,
        p.REASON_NO_GOLD,
    )
    assert p.LOOKALIKE_REASONS == (
        p.REASON_TEST_NAME,
        p.REASON_TEST_PATH,
        p.REASON_TEST_SPAN,
        p.REASON_GOLD_SPAN,
        p.REASON_GOLD_LINE,
        p.REASON_ASSERTED_LITERAL,
    )
    assert set(p.STRUCTURAL_REASONS).isdisjoint(p.LOOKALIKE_REASONS)
    assert set(p.STRUCTURAL_REASONS) | set(p.LOOKALIKE_REASONS) == set(p.PLAN_REASONS)


def test_only_the_plan_audited_source_is_an_audited_arm() -> None:
    assert arms.audited_plan_arm(AUDITED_ARM) and arms.plan_arm(AUDITED_ARM)
    assert not arms.audited_plan_arm(GUARDED_ARM)
    assert not arms.audited_plan_arm("A0")
    assert not arms.audited_plan_arm("A0+library@ctx.req.0123456789ab")
    assert arms.CTX_SOURCE_KIND["plan-audited"] == arms.CTX_KIND_PLANNED


def test_the_lookalike_plan_trips_only_lookalike_reasons() -> None:
    why = plan_guard(LOOKALIKE, gold())
    assert why == (p.REASON_GOLD_SPAN, p.REASON_TEST_NAME)


def test_off_a_guarded_arm_still_withholds_the_lookalike_plan_whole() -> None:
    e = entry(LOOKALIKE)
    composed = _compose(GUARDED_ARM, e)
    assert composed.brief.plan == ""
    assert composed.labels[LABEL_CTX_PLAN_REFUSED] == "plan_gold_span,plan_test_name"
    assert composed.labels[LABEL_CTX_DELIVERED] == "0"
    assert composed.refused == (e.text,)
    assert LABEL_CTX_PLAN_GUARD not in composed.labels
    assert LABEL_CTX_PLAN_WOULD_REFUSE not in composed.labels


def test_on_an_audited_arm_the_lookalike_plan_is_delivered_and_stamped() -> None:
    e = entry(LOOKALIKE)
    composed = _compose(AUDITED_ARM, e)
    assert composed.brief.plan == e.text
    assert e.text in composed.brief.task_text()
    assert composed.labels[LABEL_CTX_DELIVERED] == "1"
    assert composed.labels[LABEL_CTX_REFUSED] == "0"
    assert composed.labels[LABEL_CTX_PLAN_GUARD] == "audited_bypass"
    assert composed.labels[LABEL_CTX_PLAN_WOULD_REFUSE] == "plan_gold_span,plan_test_name"
    assert LABEL_CTX_PLAN_REFUSED not in composed.labels
    assert composed.refused == ()


def test_a_clean_plan_on_an_audited_arm_claims_no_bypass() -> None:
    composed = _compose(AUDITED_ARM, entry(CLEAN))
    assert composed.brief.plan == entry(CLEAN).text
    assert composed.labels[LABEL_CTX_PLAN_GUARD] == "audited_bypass"
    assert LABEL_CTX_PLAN_WOULD_REFUSE not in composed.labels
    assert LABEL_CTX_PLAN_REFUSED not in composed.labels


@pytest.mark.parametrize(
    ("e", "kw", "reason"),
    [
        (entry(CLEAN, NOT_RENDERED), {}, p.REASON_RENDER),
        (entry(CLEAN), {"gold": None}, p.REASON_NO_GOLD),
        (entry(plan(*(f"step {i}" for i in range(p.MAX_LINES + 1)))), {}, p.REASON_LENGTH),
    ],
)
def test_a_structural_reason_still_withholds_the_plan_on_an_audited_arm(
    e: ContextEntry, kw: dict[str, Any], reason: str
) -> None:
    composed = _compose(AUDITED_ARM, e, **kw)
    assert composed.brief.plan == ""
    assert composed.labels[LABEL_CTX_DELIVERED] == "0"
    assert reason in composed.labels[LABEL_CTX_PLAN_REFUSED].split(",")
    assert set(composed.labels[LABEL_CTX_PLAN_REFUSED].split(",")) <= set(p.STRUCTURAL_REASONS)
    assert composed.refused == (e.text,)
    assert composed.labels[LABEL_CTX_PLAN_GUARD] == "audited_bypass"
    assert LABEL_CTX_PLAN_WOULD_REFUSE not in composed.labels


def test_a_code_block_cannot_reach_the_guard_through_a_well_shaped_plan() -> None:
    """``plan_code_block`` is structural, but a fenced line breaks the plan's shape first
    (``plan_render``) and the renderer adds no indentation, so no rendered plan carries it."""
    with pytest.raises(ValueError, match="code fence"):
        p.render(plan("Check the name", "```x = 1```"))
    assert plan_guard(plan("Check the name", "```x = 1```"), gold()) == (p.REASON_RENDER,)


def test_a_structural_and_lookalike_plan_is_withheld_for_the_structural_reason_only() -> None:
    why = plan_guard(LOOKALIKE, gold(), text=NOT_RENDERED)
    assert p.REASON_RENDER in why and p.REASON_TEST_NAME in why
    composed = _compose(AUDITED_ARM, entry(LOOKALIKE, NOT_RENDERED))
    assert composed.brief.plan == ""
    assert composed.labels[LABEL_CTX_PLAN_REFUSED] == p.REASON_RENDER
    assert LABEL_CTX_PLAN_WOULD_REFUSE not in composed.labels


@pytest.mark.parametrize("arm", [AUDITED_ARM, GUARDED_ARM])
def test_the_blind_brief_still_withholds_the_test_files_targets_and_command(arm: str) -> None:
    composed = _compose(arm, entry(LOOKALIKE))
    brief = composed.brief
    assert brief.test_files == () and brief.target_tests == () and brief.test_command == ""
    text = brief.task_text()
    assert "tests/test_validate_names.py::" not in text
    assert "pytest -q" not in text
