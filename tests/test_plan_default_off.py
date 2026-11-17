"""The accepted-plan arm is off by default: existing arms, briefs and sets are unchanged (ADR-0054).

Navigation
----------
What it is:   Golden pins that adding the ``plan`` source moved nothing an existing arm writes.
What it does: Pins the ``ctx_brief`` hash and the other labels ``compose`` stamps for a plain
              ``A0`` brief (blind and sighted) and for a mechanical, a hindsight and a
              stated arm, each value taken from the code before ADR-0054; that none of those
              briefs carries a plan block or a ``plan`` key; that no ``ctx_plan_*`` stamp
              reaches a row of a v1 or v2 set; and the v1 and v2 set digests, unchanged.
How:          Fixed inputs to ``compose`` and ``ctxset.parse``; no git, no model, no docker.
              ``ctx_rules`` and the full task text are not pinned: they move with the rules
              text, which ADR-0054 does not touch and other changes may.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/builders/brief.py (``compose``), src/crb/builders/base.py (the plan
              block), src/crb/core/ctxset.py (the digests and run stamps),
              tests/fixtures/ctx_rows.py (the v1 and v2 fixture documents)
Tested by:    this file
Touch when:   never for a new repository; a change that is MEANT to move an existing arm's
              brief or a set's digest (an ADR first, and these pins with it).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.builders.brief import ContextEntry, GoldView, Ticket, compose
from crb.core import ctxset, stated
from crb.core.stated import StatedItem
from fixtures.ctx_rows import ctx_doc, req_doc

PARENT = "a" * 40
TICKET = Ticket("feat: refuse empty names", "Refuse an empty name in validate.")
GOLD = GoldView(
    novel=frozenset({"name required"}),
    parent_has=lambda _tok: False,
    src_after="def validate(name):\n    return name\n",
    test_after="def test_x():\n    pass\n",
    src_added=("    return name",),
    test_added=("def test_x():",),
    test_paths=("tests/test_x.py",),
)
MECH = ContextEntry(
    "m/1",
    "The handler in cmd/root.go reads the flag first.",
    "1",
    "2026-11-01T00:00:00Z",
    mechanical=True,
    source_rev=PARENT,
)
ITEM = StatedItem("i01", "rule", "Existing callers of validate keep working", "nowhere")
REQ = ContextEntry(
    "r/1", stated.render("prose", (ITEM,)), "1", "", items=(ITEM,), structure="prose"
)

#: (arm, mode, compose keywords, the labels before ADR-0054 except ``ctx_rules``)
GOLDEN: tuple[tuple[str, str, dict[str, Any], dict[str, str]], ...] = (
    (
        "A0",
        "blind",
        {"facts": ("Validate lives in app/names.py",), "learned": ("Run the suite first",)},
        {
            "ctx_brief": "79ea64aadb011bc34bf1b3500db8590f0601fb77892ccdd42a6a66e03b62e0c6",
            "ctx_refused": "0",
            "ctx_ticket": "message",
        },
    ),
    (
        "A0",
        "sighted",
        {},
        {
            "ctx_brief": "2df8fee5271e7d7ceee5a5e368cac197b9af245f2199fff5f46edddb59e400c7",
            "ctx_refused": "0",
            "ctx_ticket": "message",
        },
    ),
    (
        "A0+library@ctx.mech.0123456789ab",
        "blind",
        {"library": (MECH,)},
        {
            "ctx_brief": "1db2b9103858efb02742eed79ce63210c2cc1de7d8e55507d25b6dc292730c4f",
            "ctx_chars": "48",
            "ctx_delivered": "1",
            "ctx_library": "2e059a090fb11d8d",
            "ctx_refused": "0",
            "ctx_ticket": "message",
        },
    ),
    (
        "A0+library@ctx.oracle.0123456789ab",
        "blind",
        {"library": (MECH,)},
        {
            "ctx_brief": "1db2b9103858efb02742eed79ce63210c2cc1de7d8e55507d25b6dc292730c4f",
            "ctx_chars": "48",
            "ctx_delivered": "1",
            "ctx_library": "2e059a090fb11d8d",
            "ctx_refused": "0",
            "ctx_ticket": "message",
        },
    ),
    (
        "A0+library@ctx.req.0123456789ab",
        "blind",
        {"library": (REQ,)},
        {
            "ctx_brief": "b19bc7d4944e78f93d6e09735407ee002315da9d38922103821ec2527a3651b5",
            "ctx_chars": "79",
            "ctx_delivered": "1",
            "ctx_library": "dcd4840b00ad8de2",
            "ctx_refused": "0",
            "ctx_ticket": "message",
        },
    ),
)


@pytest.mark.parametrize(("arm", "mode", "kw", "expected"), GOLDEN)
def test_an_existing_arms_brief_is_unchanged(
    arm: str, mode: str, kw: dict[str, Any], expected: dict[str, str]
) -> None:
    composed = compose(
        arm,
        TICKET,
        repo="pyrepo",
        language="python",
        mode=mode,
        novel=GOLD.novel,
        gold=GOLD,
        parent_rev=PARENT,
        test_files=("tests/test_x.py",),
        target_tests=("tests/test_x.py::test_x",),
        test_command="pytest -q",
        **kw,
    )
    labels = {k: v for k, v in composed.labels.items() if k != "ctx_rules"}
    assert labels == {"context_arm": arm, **expected}
    assert composed.brief.plan == ""
    assert "plan" not in composed.brief.to_dict()
    assert "Accepted implementation plan" not in composed.brief.task_text()


def test_the_v1_and_v2_digests_are_unchanged() -> None:
    assert ctxset.parse(ctx_doc()).digest == (
        "a7dd1d67d33a6505872d1136493cf8ad608442be5de94457b32afcf399ef8efd"
    )
    assert ctxset.parse(req_doc()).digest == (
        "d0039d368668b7363cbec36b0ad0069e64ec6bf996cd89bd01d0071cb822dd4b"
    )
    assert ctxset.parse(req_doc(structure="checklist")).digest == (
        "630e257b642e8855a1ae9454ee87d95f0fd7e386e75db050219b293bca84fd5d"
    )


@pytest.mark.parametrize("doc", [ctx_doc(), req_doc(), req_doc(structure="checklist")])
def test_no_plan_stamp_reaches_a_v1_or_v2_row(doc: dict[str, Any]) -> None:
    cset = ctxset.parse(doc)
    assert not cset.planned
    assert cset.accepted_by == ""
    for role in ctxset.ROLES:
        stamps = ctxset.run_stamps(cset, role, dict.fromkeys(cset.task_ids, "1"))
        for row in stamps.values():
            assert not any(k.startswith("ctx_plan_") for k in row), row
