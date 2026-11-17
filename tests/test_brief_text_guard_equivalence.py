"""The shared text guard gives ``req_guard`` exactly the reasons its inline checks gave (ADR-0054).

Navigation
----------
What it is:   An equivalence pin for ``crb.builders.brief._text_guard``, the code-block,
              held-out test name and test path checks ``req_guard`` and ``plan_guard`` share.
What it does: Runs a fixed corpus of texts through the shared guard (prefix ``req``) and
              through a frozen copy of the checks as ``req_guard`` held them inline before
              ADR-0054, and asserts the same reasons for every text; pins that the ``req_``
              names are the stated reasons' own; and that ``req_guard`` still stamps each.
How:          A hand-built ``GoldView``; pure function calls; no git, no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0052-stated-requirement-arms.md
Works with:   src/crb/builders/brief.py (``_text_guard``, ``req_guard``), src/crb/core/stated.py
              (the ``req_`` reason names), tests/test_brief_req_guard.py (the req guard's own
              reason-by-reason tests)
Tested by:    this file
Touch when:   never for a new repository; a shared text check changes (an ADR first, and
              this frozen copy with it).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.builders.brief import (
    GoldView,
    _holds,
    _names_ci,
    _names_test_path,
    _test_def_tokens,
    _text_guard,
    req_guard,
)
from crb.core import stated
from crb.core.stated import StatedItem

PARENT_TREE = frozenset({"validate", "Config", "load", "helper_in_parent"})
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
    "def helper_in_parent():\n"
    "    pass\n"
    "def make_widget_fixture():\n"
    "    return 1\n"
)


def gold(**kw: Any) -> GoldView:
    base: dict[str, Any] = {
        "novel": frozenset({"name required"}),
        "parent_has": lambda tok: tok in PARENT_TREE,
        "src_after": SRC_AFTER,
        "test_after": TEST_AFTER,
        "src_added": tuple(SRC_AFTER.splitlines()[1:]),
        "test_added": tuple(TEST_AFTER.splitlines()),
        "test_paths": ("tests/test_validate_names.py",),
    }
    base.update(kw)
    return GoldView(**base)


def _frozen_inline_checks(text: str, view: GoldView) -> set[str]:
    """The three checks exactly as ``req_guard`` held them inline before ADR-0054."""
    reasons: set[str] = set()
    if (
        "```" in text
        or "~~~" in text
        or any(ln.startswith(("    ", "\t")) for ln in text.splitlines())
    ):
        reasons.add(stated.REASON_CODE_BLOCK)
    for tok in _test_def_tokens(view):
        if _names_ci(text, tok) and not _holds(view.src_after, tok) and not view.parent_has(tok):
            reasons.add(stated.REASON_TEST_NAME)
    if _names_test_path(text, view):
        reasons.add(stated.REASON_TEST_PATH)
    return reasons


CORPUS: tuple[str, ...] = (
    "",
    "Existing callers of validate keep working",
    "Use ```x = 1``` here",
    "Use ~~~x~~~ here",
    "first line\n    indented code",
    "first line\n\ttabbed code",
    "Cover test_validate_refuses_empty_name_quickly",
    "COVER TEST_VALIDATE_REFUSES_EMPTY_NAME_QUICKLY",
    "Reuse helper_in_parent as before",
    "Build it with make_widget_fixture",
    "See tests/test_validate_names.py",
    "As test_validate_names checks",
    "test_validate_names.py and ```x``` and test_validate_refuses_empty_name_quickly",
    "validate stays; name required is the message",
    "- a bullet\n1. a numbered step",
)


@pytest.mark.parametrize("text", CORPUS)
def test_the_shared_guard_equals_the_frozen_inline_checks(text: str) -> None:
    for view in (gold(), gold(test_paths=("tests/test.py",)), gold(src_after=TEST_AFTER)):
        assert _text_guard(text, view, prefix="req") == _frozen_inline_checks(text, view), text


def test_the_req_prefix_names_the_stated_reasons() -> None:
    assert stated.REASON_CODE_BLOCK == "req_code_block"
    assert stated.REASON_TEST_NAME == "req_test_name"
    assert stated.REASON_TEST_PATH == "req_test_path"


def test_the_plan_prefix_gives_the_same_checks_under_plan_names() -> None:
    text = CORPUS[-3]
    req = _text_guard(text, gold(), prefix="req")
    plan = _text_guard(text, gold(), prefix="plan")
    assert {r.removeprefix("req_") for r in req} == {r.removeprefix("plan_") for r in plan}
    assert plan == {"plan_code_block", "plan_test_name", "plan_test_path"}


def test_req_guard_still_stamps_each_shared_reason() -> None:
    def guard(statement: str) -> list[str]:
        item = StatedItem("i01", "rule", statement, "nowhere")
        return req_guard(stated.render("prose", (item,)), (item,), "prose", gold())

    assert stated.REASON_CODE_BLOCK in guard("Use ```x = 1```")
    assert stated.REASON_TEST_PATH in guard("See tests/test_validate_names.py")
    assert stated.REASON_TEST_NAME in guard("Build it with make_widget_fixture")
    assert guard("Existing callers of validate keep working") == []
