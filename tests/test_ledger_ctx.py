"""A row's context-set stamps agree with its arm, at write and on read (ADR-0050 item 5).

A row of a context-set arm (``A0+library@ctx.<source>.<hex>``) carries the full set digest,
its source, the gap anchor and the composer's counts; a control row is plain ``A0`` with
``ctx_source`` = ``control`` and none of the arm's own stamps; any other row carries no ctx
stamp at all. ``ctx_label_violation`` is the one rule, and ``GradeRow`` refuses a row it names.

Navigation
----------
What it is:   The tests of ``crb.core.ledger.ctx_label_violation`` and its ``GradeRow`` refusal.
What it does: Pins each refusal of a context-set row and of a control row, that a row with no
              ctx stamp is untouched, and that the ledger refuses a row the rule names.
How:          Label dicts built from ``crb.core.ctxset.run_stamps`` (the labels a run writes)
              and hand-edited; rows reduced through the classification tests' ``_replay``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md, docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/ledger.py (under test), src/crb/core/ctxset.py (``run_stamps``),
              tests/test_ledger_classification.py (the row helpers)
Tested by:    tests/test_ledger_ctx.py
Touch when:   never for a new repository; a ctx stamp joins or leaves a row, or a refusal changes.
"""

from __future__ import annotations

import pytest

from crb.core import context_arm as ca
from crb.core import ledger as lg
from crb.core import lint as lint_mod
from test_ledger_classification import _replay, _result, _task

DIGEST = "ab" * 32
GAP_RULE = "anchor.v1"


def _name(source: str) -> str:
    return f"ctx.{source}.{DIGEST[:12]}"


def _arm(source: str) -> str:
    return f"A0+library@{_name(source)}"


def _entries(source: str) -> dict[str, str]:
    labels = {
        ca.LABEL_CTX_SET: DIGEST,
        ca.LABEL_CTX_SOURCE: source,
        ca.LABEL_CTX_GAP: "0",
        ca.LABEL_CTX_GAP_RULE: GAP_RULE,
        ca.LABEL_CTX_DELIVERED: "2",
        ca.LABEL_CTX_CHARS: "140",
    }
    if source.startswith("mech"):
        labels[ca.LABEL_CTX_DRAFTER] = "drafter.v1"
    else:
        labels[ca.LABEL_CTX_CEILING] = "1"
    return labels


def _control() -> dict[str, str]:
    return {
        ca.LABEL_CTX_SET: DIGEST,
        ca.LABEL_CTX_SOURCE: ca.CTX_SOURCE_CONTROL,
        ca.LABEL_CTX_GAP: "1",
        ca.LABEL_CTX_GAP_RULE: GAP_RULE,
    }


SOURCES = ("oracle", "oracle-placebo", "mech", "mech-placebo")


@pytest.mark.parametrize("source", SOURCES)
def test_a_well_stamped_context_set_row_passes(source: str) -> None:
    assert lg.ctx_label_violation(_arm(source), _entries(source)) == ""


def test_a_well_stamped_control_row_passes_and_a_plain_row_is_untouched() -> None:
    assert lg.ctx_label_violation(ca.BASE_A0, _control()) == ""
    assert lg.ctx_label_violation(ca.BASE_A0, {}) == ""
    assert lg.ctx_label_violation("A0+facts", {"other": "x"}) == ""


def test_every_stamp_a_run_writes_is_one_the_rule_reads() -> None:
    assert set(_entries("mech")) | set(_entries("oracle")) <= set(lg.CTX_RUN_LABELS) | set(
        lg.CTX_ARM_LABELS
    )
    assert set(_control()) <= set(lg.CTX_RUN_LABELS)
    assert not set(lg.CTX_RUN_LABELS) & set(lg.CTX_ARM_LABELS)


@pytest.mark.parametrize(
    ("arm", "edit", "match"),
    [
        # an arm naming a set with no stamps at all
        (_arm("mech"), {ca.LABEL_CTX_SET: None}, "full ctx_set digest"),
        (_arm("mech"), {ca.LABEL_CTX_SET: DIGEST[:12]}, "full ctx_set digest"),
        (_arm("mech"), {ca.LABEL_CTX_GAP: "2"}, "ctx_gap"),
        (_arm("mech"), {ca.LABEL_CTX_GAP_RULE: None}, "ctx_gap_rule"),
        (_arm("mech"), {ca.LABEL_CTX_SET: "cd" * 32}, "is not the set"),
        (_arm("mech"), {ca.LABEL_CTX_SOURCE: "oracle"}, "is not the arm's source"),
        (_arm("mech"), {ca.LABEL_CTX_DELIVERED: None}, "ctx_delivered"),
        (_arm("mech"), {ca.LABEL_CTX_CHARS: "-1"}, "ctx_chars"),
        (_arm("mech"), {ca.LABEL_CTX_CEILING: "1"}, "ctx_ceiling"),
        (_arm("mech"), {ca.LABEL_CTX_DRAFTER: None}, "ctx_drafter"),
        (_arm("oracle"), {ca.LABEL_CTX_CEILING: None}, "ctx_ceiling"),
        (_arm("oracle"), {ca.LABEL_CTX_CEILING: "0"}, "ctx_ceiling"),
        (_arm("oracle"), {ca.LABEL_CTX_DRAFTER: "d"}, "ctx_drafter"),
        (_arm("oracle"), {ca.LABEL_CTX_DRAFTER: ""}, "ctx_drafter"),
    ],
)
def test_a_context_set_row_whose_stamps_disagree_with_its_arm_is_refused(
    arm: str, edit: dict[str, str | None], match: str
) -> None:
    source = arm.rsplit("@", 1)[1].split(".")[1]
    labels = _entries(source)
    for k, v in edit.items():
        if v is None:
            labels.pop(k, None)
        else:
            labels[k] = v
    assert match in lg.ctx_label_violation(arm, labels)


@pytest.mark.parametrize("base", ["A0+library@{}+L", "S1@x+library@{}"])
def test_a_context_set_arm_on_another_base_or_with_a_loop_is_refused(base: str) -> None:
    arm = base.format(_name("mech"))
    assert ca.is_arm(arm)
    assert "is not base A0" in lg.ctx_label_violation(arm, _entries("mech"))


@pytest.mark.parametrize(
    ("arm", "edit", "match"),
    [
        ("A0+facts", {}, "a context-set control row is plain A0"),
        (ca.BASE_A0, {ca.LABEL_CTX_SOURCE: "mech"}, "control row's ctx_source"),
        (ca.BASE_A0, {ca.LABEL_CTX_DELIVERED: "0"}, "arm's own stamps"),
        (ca.BASE_A0, {ca.LABEL_CTX_DRAFTER: "d"}, "arm's own stamps"),
        (ca.BASE_A0, {ca.LABEL_CTX_GAP: ""}, "ctx_gap"),
    ],
)
def test_a_control_row_that_is_not_plain_a0_control_is_refused(
    arm: str, edit: dict[str, str], match: str
) -> None:
    assert match in lg.ctx_label_violation(arm, {**_control(), **edit})


def test_a_stray_ctx_stamp_on_a_plain_row_is_refused() -> None:
    assert "full ctx_set digest" in lg.ctx_label_violation(
        ca.BASE_A0, {ca.LABEL_CTX_GAP: "0", ca.LABEL_CTX_GAP_RULE: GAP_RULE}
    )


def test_the_ledger_writes_a_well_stamped_row_and_refuses_one_the_rule_names() -> None:
    res = _result(lint_status=lint_mod.LINT_NONE_DETECTED)
    row = _replay(res, _task(), context_arm=_arm("mech"), labels=_entries("mech"))
    assert row.labels[ca.LABEL_CTX_SET] == DIGEST
    control = _replay(res, _task(), context_arm=ca.BASE_A0, labels=_control())
    assert control.labels[ca.LABEL_CTX_SOURCE] == ca.CTX_SOURCE_CONTROL
    bad = row.fields()
    bad["labels"] = {**row.labels, ca.LABEL_CTX_SOURCE: "oracle"}
    with pytest.raises(lg.LedgerIntegrityError, match="is not the arm's source"):
        lg.GradeRow(**bad)
    stray = control.fields()
    stray["labels"] = {**control.labels, ca.LABEL_CTX_CHARS: "3"}
    with pytest.raises(lg.LedgerIntegrityError, match="arm's own stamps"):
        lg.GradeRow(**stray)
