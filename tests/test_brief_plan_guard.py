"""Tests for the accepted-plan guard and its place in the composer (ADR-0054).

Navigation
----------
What it is:   Tests for ``crb.builders.brief.plan_guard``, ``plan_novel``, ``admit_at_parent``
              with ``require_mechanical=False`` and ``compose`` on a ``ctx.plan*`` arm.
What it does: Pins each guard reason on a minimal ``GoldView``; that a seven-token copy of
              the change is not caught and an eight-token copy is; that a token the change
              introduced is counted, never refused; that a guarded plan is withheld WHOLE
              (nothing of it reaches the brief) and its reasons stamped; that a kept plan
              reaches the brief's own plan block, never ``spec_facts``; and that a plan entry
              is admitted at the parent commit without the mechanical stamp.
How:          Hand-built ``GoldView`` values; pure function calls; no git, no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/builders/brief.py (the module under test), src/crb/core/plan.py (the
              body and renderer), tests/test_brief_req_guard.py (the stated guard it shares
              its text checks with)
Tested by:    this file
Touch when:   never for a new repository; a guard rule, a reason or the plan block changes
              (an ADR first).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.builders.brief import (
    LABEL_CTX_DELIVERED,
    LABEL_CTX_PLAN_NOVEL,
    LABEL_CTX_PLAN_REFUSED,
    LABEL_CTX_REFUSED,
    ContextEntry,
    GoldView,
    Ticket,
    admit_at_parent,
    compose,
    plan_guard,
    plan_novel,
)
from crb.core import plan as p
from crb.core.plan import PlanBody

PLAN_ARM = "A0+library@ctx.plan.0123456789ab"
MECH_ARM = "A0+library@ctx.mech.0123456789ab"
PARENT = "a" * 40
TICKET = Ticket("feat: refuse empty names", "feat: refuse empty names")
PARENT_TREE = frozenset({"validate", "Config", "load"})

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
    "    alpha bravo charlie delta echo foxtrot golf hotel india\n"
)


def gold(**kw: Any) -> GoldView:
    base: dict[str, Any] = {
        "novel": frozenset({"name required", "validate_strict"}),
        "parent_has": lambda tok: tok in PARENT_TREE,
        "src_after": SRC_AFTER,
        "test_after": TEST_AFTER,
        "src_added": tuple(SRC_AFTER.splitlines()[1:]),
        "test_added": tuple(TEST_AFTER.splitlines()),
        "test_paths": ("tests/test_validate_names.py",),
    }
    base.update(kw)
    return GoldView(**base)


def plan(*steps: str, **kw: Any) -> PlanBody:
    return PlanBody(
        summary=kw.pop("summary", ("Refuse an empty name",)),
        steps=steps or ("Check the name before it is used",),
        **kw,
    )


CLEAN = plan("Check the name before it is used", "Raise an error for an empty name")


def entry(body: PlanBody, *, source_rev: str = PARENT, text: str | None = None) -> ContextEntry:
    return ContextEntry(
        "plan/1",
        p.render(body) if text is None else text,
        "1",
        "2026-11-01T00:00:00Z",
        source_rev=source_rev,
        plan=body,
    )


def _compose(arm: str, library: tuple[ContextEntry, ...], **kw: Any) -> Any:
    kw.setdefault("novel", gold().novel)
    kw.setdefault("gold", gold())
    kw.setdefault("parent_rev", PARENT)
    return compose(
        arm, TICKET, repo="pyrepo", language="python", mode="blind", library=library, **kw
    )


# -- plan_guard, reason by reason -------------------------------------------------------------


def test_a_clean_plan_passes() -> None:
    assert plan_guard(CLEAN, gold()) == ()
    assert plan_guard(CLEAN, gold(), text=p.render(CLEAN)) == ()


def test_no_gold_view_fails_closed() -> None:
    assert plan_guard(CLEAN, None) == (p.REASON_NO_GOLD,)


def test_a_text_that_is_not_the_rendering_is_refused() -> None:
    assert p.REASON_RENDER in plan_guard(CLEAN, gold(), text="Do what the tests want.")
    assert plan_guard(PlanBody(summary=(), steps=("x",)), gold()) == (p.REASON_RENDER,)


def test_a_plan_over_the_limits_is_refused() -> None:
    long = plan(*(f"step {i}" for i in range(p.MAX_LINES + 1)))
    assert p.REASON_LENGTH in plan_guard(long, gold())


def test_a_held_out_tests_name_is_refused() -> None:
    named = plan("Cover test_validate_refuses_empty_name_quickly")
    assert p.REASON_TEST_NAME in plan_guard(named, gold())


def test_a_held_out_tests_path_or_stem_is_refused() -> None:
    for step in ("Add tests/test_validate_names.py", "Extend test_validate_names"):
        assert p.REASON_TEST_PATH in plan_guard(plan(step), gold()), step


def test_a_seven_token_copy_is_not_caught_and_an_eight_token_copy_is() -> None:
    seven = plan("Use alpha bravo charlie delta echo foxtrot golf")
    eight = plan("Use alpha bravo charlie delta echo foxtrot golf hotel")
    assert p.REASON_TEST_SPAN not in plan_guard(seven, gold())
    assert p.REASON_TEST_SPAN in plan_guard(eight, gold())


def test_a_copy_split_across_plan_lines_is_caught() -> None:
    split = plan("Use alpha bravo charlie delta", "then echo foxtrot golf hotel")
    assert p.REASON_TEST_SPAN in plan_guard(split, gold())


def test_an_eight_token_copy_of_the_changes_source_is_refused() -> None:
    copied = plan("raise ValueError name required then return name strip lower")
    why = plan_guard(copied, gold())
    assert p.REASON_GOLD_SPAN in why
    assert p.REASON_TEST_SPAN not in why


def test_a_plan_repeating_an_asserted_literal_is_refused_unless_the_request_states_it() -> None:
    view = gold(
        novel=frozenset(),
        test_added=(
            'assert.PanicsWithError(t, "echo: response writer does not support flushing", f)',
        ),
        test_paths=("response_test.go",),
    )
    body = plan("Panic with response writer does not support flushing")
    assert p.REASON_ASSERTED_LITERAL in plan_guard(body, view)
    request = "Flush panics: response writer does not support flushing"
    assert p.REASON_ASSERTED_LITERAL not in plan_guard(body, view, request)


def test_a_token_the_change_introduced_is_counted_never_refused() -> None:
    names = plan("Add validate_strict and raise name required for an empty name")
    assert plan_guard(names, gold()) == ()
    text = p.render(names)
    assert plan_novel(text, gold()) == 2
    assert plan_novel(p.render(CLEAN), gold()) == 0
    assert plan_novel(text, None) == 0


def test_the_reasons_are_sorted_and_named_from_the_plan_vocabulary() -> None:
    many = plan(
        "Cover test_validate_refuses_empty_name_quickly in tests/test_validate_names.py",
        "Use alpha bravo charlie delta echo foxtrot golf hotel",
    )
    why = plan_guard(many, gold())
    assert list(why) == sorted(why)
    assert set(why) <= set(p.PLAN_REASONS)
    assert {p.REASON_TEST_NAME, p.REASON_TEST_PATH, p.REASON_TEST_SPAN} <= set(why)


# -- review fixes: the renderer's own words, short copies, split literals ----------------------


FULL_SECTIONS = plan(
    "Check the name before it is used",
    files=("src/app/names.py",),
    decisions=("Existing callers keep working",),
    tests=("A test that an empty name is refused",),
)


def test_the_header_and_headings_never_trip_the_test_name_or_path_checks() -> None:
    """A held-out test whose fixture, class or file stem is a word of the renderer's own
    header or headings (``steps``, ``Tests``, ``plan``, ``summary``) withholds no plan: the
    checks read the plan's own lines, never the frame the renderer adds."""
    view = gold(
        test_after="class Tests:\n    def test_x(steps):\n        assert steps\n",
        test_added=("class Tests:", "    def test_x(steps):", "        assert steps"),
        test_paths=(
            "test/plan.test.js",
            "src/__tests__/summary.test.js",
            "spec/decisions.spec.js",
            "test/change.test.js",
        ),
    )
    assert p.render(FULL_SECTIONS).count(":") >= 5  # the header and every heading are there
    assert plan_guard(FULL_SECTIONS, view) == ()
    # a word the plan's own lines use is still checked
    assert p.REASON_TEST_NAME in plan_guard(plan("Walk the steps in order"), view)
    assert p.REASON_TEST_PATH in plan_guard(plan("Write the summary first"), view)


def test_the_novel_count_reads_the_plans_own_lines_not_the_header() -> None:
    e = entry(FULL_SECTIONS)
    words = frozenset({"Implementation", "Decisions", "Summary"})
    composed = _compose(PLAN_ARM, (e,), novel=frozenset(), gold=gold(novel=words))
    assert composed.brief.plan == e.text
    assert composed.labels[LABEL_CTX_PLAN_NOVEL] == "0"


def _short_fix(**kw: Any) -> GoldView:
    return gold(
        novel=frozenset(),
        src_after="def clamp(x, lo=0, hi=3):\n    return max(lo, min(x, hi))\n",
        src_added=("    return max(lo, min(x, hi))",),
        test_after="def test_clamp_bounds():\n    assert clamp(5) == 3\n",
        test_added=("    assert clamp(5) == 3",),
        test_paths=("tests/test_clamp_bounds.py",),
        **kw,
    )


def test_a_short_change_copied_whole_is_refused_however_few_its_tokens() -> None:
    src = plan("Replace the body with: return max(lo, min(x, hi))")
    test = plan("Make sure clamp(5) == 3 holds")
    spaced = plan("Use MAX( lo ,min( x,hi ) );")
    for body in (src, test, spaced):
        why = plan_guard(body, _short_fix())
        assert p.REASON_GOLD_LINE in why, body
        assert p.REASON_GOLD_SPAN not in why and p.REASON_TEST_SPAN not in why, body
    split = plan("Return max(lo,", "min(x, hi)) from clamp")
    assert p.REASON_GOLD_LINE in plan_guard(split, _short_fix())


def test_a_gold_line_the_request_or_the_parent_holds_or_prose_is_not_a_copy() -> None:
    body = plan("Replace the body with: return max(lo, min(x, hi))")
    request = "fix: clamp should return max(lo, min(x, hi))"
    assert p.REASON_GOLD_LINE not in plan_guard(body, _short_fix(), request)
    held = "    return max(lo, min(x, hi))  # an older copy of the line"
    parent = _short_fix(parent_has=lambda tok: tok in held)
    assert p.REASON_GOLD_LINE not in plan_guard(body, parent)
    # under GOLD_LINE_MIN, or with no code character, a line is the span rules' to judge
    short = gold(novel=frozenset(), src_added=("    x = f(y)",), test_added=())
    assert plan_guard(plan("Set x = f(y) first"), short) == ()
    prose = gold(novel=frozenset(), src_added=("    # Return the clamped value",), test_added=())
    assert plan_guard(plan("Return the clamped value"), prose) == ()
    assert plan_guard(CLEAN, _short_fix()) == ()


def test_an_asserted_literal_split_across_plan_lines_is_refused() -> None:
    view = gold(
        novel=frozenset(),
        test_added=("    with pytest.raises(ValueError, match='duration must be positive here'):",),
    )
    one = plan("Raise ValueError with message: duration must be positive here")
    split = plan("Raise ValueError with message: duration must", "be positive here")
    assert p.REASON_ASSERTED_LITERAL in plan_guard(one, view)
    assert p.REASON_ASSERTED_LITERAL in plan_guard(split, view)
    assert p.REASON_ASSERTED_LITERAL not in plan_guard(
        split, view, "duration must be positive here"
    )


# -- admission at the parent ------------------------------------------------------------------


def test_admit_at_parent_without_the_mechanical_stamp() -> None:
    e = entry(CLEAN)
    assert not e.mechanical
    assert e.planned
    assert admit_at_parent([e], PARENT) == ([], [e.entry_id])
    assert admit_at_parent([e], PARENT, require_mechanical=False) == ([e], [])
    other = entry(CLEAN, source_rev="b" * 40)
    assert admit_at_parent([other], PARENT, require_mechanical=False) == ([], [other.entry_id])
    assert admit_at_parent([e], "", require_mechanical=False) == ([], [e.entry_id])


# -- compose on a plan arm --------------------------------------------------------------------


def test_a_kept_plan_reaches_the_plan_block_not_the_facts() -> None:
    e = entry(CLEAN)
    composed = _compose(PLAN_ARM, (e,))
    assert composed.brief.plan == e.text
    assert composed.brief.spec_facts == ()
    assert e.text in composed.brief.task_text()
    assert composed.labels[LABEL_CTX_DELIVERED] == "1"
    assert composed.labels[LABEL_CTX_REFUSED] == "0"
    assert composed.labels[LABEL_CTX_PLAN_NOVEL] == "0"
    assert LABEL_CTX_PLAN_REFUSED not in composed.labels


def test_a_plan_naming_novel_tokens_is_delivered_and_counted() -> None:
    e = entry(plan("Add validate_strict and raise name required for an empty name"))
    composed = _compose(PLAN_ARM, (e,))
    assert composed.brief.plan == e.text
    assert composed.labels[LABEL_CTX_PLAN_NOVEL] == "2"


def test_a_guarded_plan_is_withheld_whole() -> None:
    e = entry(
        plan(
            "Check the name before it is used",
            "Use alpha bravo charlie delta echo foxtrot golf hotel",
        )
    )
    composed = _compose(PLAN_ARM, (e,))
    assert composed.brief.plan == ""
    assert composed.brief.spec_facts == ()
    assert "Check the name" not in composed.brief.task_text()
    assert composed.labels[LABEL_CTX_DELIVERED] == "0"
    assert composed.labels[LABEL_CTX_REFUSED] == "1"
    assert composed.labels[LABEL_CTX_PLAN_REFUSED] == p.REASON_TEST_SPAN
    assert LABEL_CTX_PLAN_NOVEL not in composed.labels
    assert composed.refused == (e.text,)


def test_a_plan_with_no_gold_view_is_withheld() -> None:
    composed = _compose(PLAN_ARM, (entry(CLEAN),), gold=None)
    assert composed.brief.plan == ""
    assert composed.labels[LABEL_CTX_PLAN_REFUSED] == p.REASON_NO_GOLD


def test_a_plan_entry_off_the_parent_is_not_admitted() -> None:
    composed = _compose(PLAN_ARM, (entry(CLEAN, source_rev="b" * 40),))
    assert composed.brief.plan == ""
    assert composed.labels[LABEL_CTX_DELIVERED] == "0"
    assert composed.labels[LABEL_CTX_REFUSED] == "1"


def test_a_plan_arm_needs_the_parent_commit() -> None:
    with pytest.raises(ValueError, match="parent_rev"):
        _compose(PLAN_ARM, (entry(CLEAN),), parent_rev="")


def test_a_plan_entry_on_a_mechanical_arm_is_not_admitted() -> None:
    composed = _compose(MECH_ARM, (entry(CLEAN),))
    assert composed.brief.plan == ""
    assert composed.labels[LABEL_CTX_DELIVERED] == "0"


def test_a_plan_less_entry_on_a_plan_arm_still_meets_refuse_novel() -> None:
    bare = ContextEntry("plan/2", "Raise name required", "1", "", source_rev=PARENT)
    composed = _compose(PLAN_ARM, (bare,))
    assert composed.brief.spec_facts == ()
    assert composed.labels[LABEL_CTX_REFUSED] == "1"


def test_the_brief_hash_moves_only_when_a_plan_is_delivered() -> None:
    kept = _compose(PLAN_ARM, (entry(CLEAN),))
    withheld = _compose(PLAN_ARM, (entry(CLEAN),), gold=None)
    empty = _compose(PLAN_ARM, ())
    assert withheld.labels["ctx_brief"] == empty.labels["ctx_brief"]
    assert kept.labels["ctx_brief"] != empty.labels["ctx_brief"]
