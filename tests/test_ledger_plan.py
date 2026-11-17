"""An accepted-plan row's stamps agree with its arm (ADR-0054), at write and on read.

Navigation
----------
What it is:   The tests of ``crb.core.ledger.ctx_label_violation``'s accepted-plan rules.
What it does: Pins that a ``ctx.plan*`` entries row carries every plan stamp and neither the
              mechanical drafter nor the hindsight ceiling; that no other row (a control row,
              an oracle, mech or req arm, a plain row) carries a plan stamp; that the optional
              refusal, novel-token and open-gap stamps are checked when present; that an
              audited-bypass row (ADR-0055) carries its guard, audit and auditor stamps, its
              would-refuse reasons lookalike ones only and its refused reasons structural ones
              only, and that no other row carries them; and that the ledger refuses a row the
              rule names.
How:          Labels from ``crb.core.ctxset.run_stamps`` on a parsed v3 set (the labels a run
              writes), hand-edited; rows written through the classification tests' ``_replay``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0050-context-set-arms.md,
              docs/adr/0055-audited-bypass-plan-arm.md
Works with:   src/crb/core/ledger.py (under test), src/crb/core/ctxset.py (``run_stamps``),
              tests/fixtures/ctx_rows.py (``plan_set``), tests/test_ledger_stated.py (the v2
              stamps)
Tested by:    tests/test_ledger_plan.py
Touch when:   never for a new repository; a plan stamp joins or leaves a row.
"""

from __future__ import annotations

import pytest

from crb.core import context_arm as ca
from crb.core import ctxset
from crb.core import ledger as lg
from crb.core import lint as lint_mod
from fixtures.ctx_rows import TASKS, ctx_row, ctx_set, plan_set, req_set
from test_ledger_classification import _replay, _result, _task


def _stamps(cset: ctxset.CtxSet, role: str = ctxset.ROLE_ENTRIES) -> dict[str, str]:
    labels = dict(ctxset.run_stamps(cset, role, dict.fromkeys(cset.task_ids, "1"))[TASKS[0]])
    if role == ctxset.ROLE_ENTRIES:
        labels.update({ca.LABEL_CTX_DELIVERED: "1", ca.LABEL_CTX_CHARS: "120"})
    return labels


PLAN = plan_set()
ORACLE = ctx_set()
REQ = req_set()
PLAN_OWN = (*lg.CTX_PLAN_LABELS, ca.LABEL_CTX_PLAN_REFUSED, ca.LABEL_CTX_PLAN_NOVEL)


def _mech() -> tuple[str, dict[str, str]]:
    """A mechanical arm's row, built by hand: a v1 mech set needs its pinned drafter."""
    labels = {
        **_stamps(ORACLE),
        ca.LABEL_CTX_SOURCE: ctxset.SOURCE_MECH,
        ca.LABEL_CTX_DRAFTER: "drafter.v1",
    }
    labels.pop(ca.LABEL_CTX_CEILING)
    return f"A0+library@ctx.{ctxset.SOURCE_MECH}.{ORACLE.digest[:12]}", labels


def test_a_run_stamped_plan_row_and_its_control_pass() -> None:
    labels = _stamps(PLAN)
    assert set(lg.CTX_PLAN_LABELS) <= set(labels)
    assert ca.LABEL_CTX_DRAFTER not in labels
    assert ca.LABEL_CTX_CEILING not in labels
    assert lg.ctx_label_violation(PLAN.arm, labels) == ""
    control = _stamps(PLAN, ctxset.ROLE_CONTROL)
    assert not set(PLAN_OWN) & set(control)
    assert lg.ctx_label_violation(ca.BASE_A0, control) == ""


def test_an_unaccepted_plan_and_a_plan_that_saw_only_the_ticket_pass() -> None:
    for cset in (plan_set(accepted_by="none"), plan_set(saw=("ticket",))):
        assert lg.ctx_label_violation(cset.arm, _stamps(cset)) == ""


def test_the_optional_plan_stamps_pass_when_well_formed() -> None:
    labels = {
        **_stamps(PLAN),
        ca.LABEL_CTX_PLAN_NOVEL: "3",
        ca.LABEL_CTX_PLAN_REFUSED: "plan_test_name,plan_test_span",
        ca.LABEL_CTX_OPEN_GAPS: "2",
    }
    assert lg.ctx_label_violation(PLAN.arm, labels) == ""


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        ({ca.LABEL_CTX_PLAN_DRAFTER: None}, "lacks"),
        ({ca.LABEL_CTX_PLAN_SAW: ""}, "lacks"),
        ({ca.LABEL_CTX_PLAN_ACCEPTED: None}, "lacks"),
        ({ca.LABEL_CTX_PLAN_DRAFTER: "a planner"}, "ctx_plan_drafter"),
        ({ca.LABEL_CTX_PLAN_SAW: "tree,ticket"}, "ctx_plan_saw"),
        ({ca.LABEL_CTX_PLAN_SAW: "tree"}, "ctx_plan_saw"),
        ({ca.LABEL_CTX_PLAN_SAW: "diff,ticket"}, "ctx_plan_saw"),
        ({ca.LABEL_CTX_PLAN_SAW: "ticket,ticket"}, "ctx_plan_saw"),
        ({ca.LABEL_CTX_PLAN_ACCEPTED: "model:x@" + "a" * 64}, "ctx_plan_accepted"),
        ({ca.LABEL_CTX_PLAN_ACCEPTED: "None"}, "ctx_plan_accepted"),
        ({ca.LABEL_CTX_OPEN_GAPS: "0"}, "ctx_open_gaps"),
        ({ca.LABEL_CTX_PLAN_NOVEL: "-1"}, "ctx_plan_novel"),
        ({ca.LABEL_CTX_PLAN_NOVEL: "two"}, "ctx_plan_novel"),
        ({ca.LABEL_CTX_DRAFTER: "drafter.v1"}, "ctx_drafter"),
        ({ca.LABEL_CTX_CEILING: "1"}, "ctx_ceiling"),
    ],
)
def test_a_plan_row_whose_plan_stamps_disagree_is_refused(
    edit: dict[str, str | None], match: str
) -> None:
    labels = _stamps(PLAN)
    for k, v in edit.items():
        if v is None:
            labels.pop(k, None)
        else:
            labels[k] = v
    assert match in lg.ctx_label_violation(PLAN.arm, labels)


@pytest.mark.parametrize(
    "refused",
    ["plan_bogus", "req_length", "plan_test_span,plan_length", "plan_length,plan_length", ""],
)
def test_a_plan_row_whose_refusal_reasons_are_not_guard_reasons_is_refused(refused: str) -> None:
    labels = {**_stamps(PLAN), ca.LABEL_CTX_PLAN_REFUSED: refused}
    assert "ctx_plan_refused" in lg.ctx_label_violation(PLAN.arm, labels)


@pytest.mark.parametrize("key", PLAN_OWN)
def test_no_other_row_carries_a_plan_stamp(key: str) -> None:
    value = _stamps(PLAN).get(key, "1")
    mech_arm, mech = _mech()
    assert lg.ctx_label_violation(mech_arm, mech) == ""
    for arm, labels in ((ORACLE.arm, _stamps(ORACLE)), (REQ.arm, _stamps(REQ)), (mech_arm, mech)):
        assert "non-plan arm" in lg.ctx_label_violation(arm, {**labels, key: value}), arm
    control = {**_stamps(PLAN, ctxset.ROLE_CONTROL), key: value}
    assert "arm's own stamps" in lg.ctx_label_violation(ca.BASE_A0, control)
    assert "without a ctx_set" in lg.ctx_label_violation(ca.BASE_A0, {key: value})


def test_a_plan_row_carries_no_stated_stamp_but_may_carry_open_gaps() -> None:
    stated = {**_stamps(PLAN), ca.LABEL_CTX_STATED: "1"}
    assert "non-req arm" in lg.ctx_label_violation(PLAN.arm, stated)
    gaps = {**_stamps(PLAN), ca.LABEL_CTX_OPEN_GAPS: "1"}
    assert lg.ctx_label_violation(PLAN.arm, gaps) == ""


def test_the_ledger_writes_a_plan_row_and_refuses_one_the_rule_names() -> None:
    res = _result(lint_status=lint_mod.LINT_NONE_DETECTED)
    row = _replay(res, _task(), context_arm=PLAN.arm, labels=_stamps(PLAN))
    assert row.labels[ca.LABEL_CTX_PLAN_ACCEPTED] == "human:fixture-01"
    bad = row.fields()
    bad["labels"] = {**row.labels, ca.LABEL_CTX_PLAN_SAW: "tree"}
    with pytest.raises(lg.LedgerIntegrityError, match="ctx_plan_saw"):
        lg.GradeRow(**bad)


def test_a_fixture_plan_row_is_a_valid_grade_row() -> None:
    row = ctx_row(PLAN, TASKS[0], clean=True)
    assert row.labels[ca.LABEL_CTX_SOURCE] == ctxset.SOURCE_PLAN
    assert row.labels[ca.LABEL_CTX_PLAN_SAW] == "ticket,tree"
    stray = row.fields()
    stray["labels"] = {**row.labels, ca.LABEL_CTX_CEILING: "1"}
    with pytest.raises(lg.LedgerIntegrityError, match="ctx_ceiling"):
        lg.GradeRow(**stray)


# --- the audited-bypass stamps (ADR-0055) -----------------------------------------------


AUDITED = plan_set(audited=True)
AUDIT_OWN = (*lg.CTX_PLAN_AUDIT_LABELS, ca.LABEL_CTX_PLAN_WOULD_REFUSE)


def test_a_run_stamped_audited_row_and_its_control_pass() -> None:
    labels = _stamps(AUDITED)
    assert set(lg.CTX_PLAN_AUDIT_LABELS) <= set(labels)
    assert labels[ca.LABEL_CTX_PLAN_GUARD] == ca.PLAN_GUARD_AUDITED_BYPASS
    assert labels[ca.LABEL_CTX_PLAN_AUDIT] == "a" * 64
    assert labels[ca.LABEL_CTX_PLAN_AUDITOR] == "human:fixture-02"
    assert lg.ctx_label_violation(AUDITED.arm, labels) == ""
    bypassed = {**labels, ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_gold_span,plan_test_name"}
    assert lg.ctx_label_violation(AUDITED.arm, bypassed) == ""
    structural = {
        **labels,
        ca.LABEL_CTX_PLAN_REFUSED: "plan_length,plan_render",
        ca.LABEL_CTX_DELIVERED: "0",
    }
    assert lg.ctx_label_violation(AUDITED.arm, structural) == ""
    control = _stamps(AUDITED, ctxset.ROLE_CONTROL)
    assert not set(AUDIT_OWN) & set(control)
    assert lg.ctx_label_violation(ca.BASE_A0, control) == ""


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        ({ca.LABEL_CTX_PLAN_GUARD: None}, "lacks"),
        ({ca.LABEL_CTX_PLAN_AUDIT: None}, "lacks"),
        ({ca.LABEL_CTX_PLAN_AUDITOR: ""}, "lacks"),
        ({ca.LABEL_CTX_PLAN_GUARD: "guarded"}, "ctx_plan_guard"),
        ({ca.LABEL_CTX_PLAN_AUDIT: "a" * 63}, "ctx_plan_audit"),
        ({ca.LABEL_CTX_PLAN_AUDITOR: "an auditor"}, "ctx_plan_auditor"),
        ({ca.LABEL_CTX_PLAN_WOULD_REFUSE: ""}, "ctx_plan_would_refuse"),
        ({ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_test_name,plan_gold_span"}, "would_refuse"),
        ({ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_test_name,plan_test_name"}, "would_refuse"),
        ({ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_length"}, "ctx_plan_would_refuse"),
        ({ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_bogus"}, "ctx_plan_would_refuse"),
        ({ca.LABEL_CTX_PLAN_REFUSED: "plan_test_name"}, "lookalike"),
        ({ca.LABEL_CTX_PLAN_REFUSED: "plan_length,plan_test_span"}, "ctx_plan_refused"),
        # fullmatch: a trailing newline is not a digest or an auditor
        ({ca.LABEL_CTX_PLAN_AUDIT: "a" * 64 + "\n"}, "ctx_plan_audit"),
        ({ca.LABEL_CTX_PLAN_AUDITOR: "human:fixture-02\n"}, "ctx_plan_auditor"),
        # a would-refuse is stamped only for a delivered plan, never beside a withheld one
        (
            {
                ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_test_name",
                ca.LABEL_CTX_PLAN_REFUSED: "plan_render",
            },
            "not delivered",
        ),
        (
            {
                ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_test_name",
                ca.LABEL_CTX_PLAN_REFUSED: "plan_render",
                ca.LABEL_CTX_DELIVERED: "0",
            },
            "not delivered",
        ),
        (
            {ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_test_name", ca.LABEL_CTX_DELIVERED: "0"},
            "not delivered",
        ),
    ],
)
def test_an_audited_row_whose_audit_stamps_disagree_is_refused(
    edit: dict[str, str | None], match: str
) -> None:
    labels = _stamps(AUDITED)
    for k, v in edit.items():
        if v is None:
            labels.pop(k, None)
        else:
            labels[k] = v
    assert match in lg.ctx_label_violation(AUDITED.arm, labels)


@pytest.mark.parametrize("key", AUDIT_OWN)
def test_no_other_row_carries_an_audit_stamp(key: str) -> None:
    value = {**_stamps(AUDITED), ca.LABEL_CTX_PLAN_WOULD_REFUSE: "plan_test_name"}[key]
    assert "audited-bypass" in lg.ctx_label_violation(PLAN.arm, {**_stamps(PLAN), key: value})
    for arm, labels in ((ORACLE.arm, _stamps(ORACLE)), (REQ.arm, _stamps(REQ))):
        assert "non-plan arm" in lg.ctx_label_violation(arm, {**labels, key: value}), arm
    control = {**_stamps(AUDITED, ctxset.ROLE_CONTROL), key: value}
    assert "arm's own stamps" in lg.ctx_label_violation(ca.BASE_A0, control)
    assert "without a ctx_set" in lg.ctx_label_violation(ca.BASE_A0, {key: value})


def test_a_fixture_audited_row_is_a_valid_grade_row_and_the_ledger_refuses_a_bad_one() -> None:
    row = ctx_row(AUDITED, TASKS[0], clean=True)
    assert row.labels[ca.LABEL_CTX_SOURCE] == ctxset.SOURCE_PLAN_AUDITED
    assert row.labels[ca.LABEL_CTX_PLAN_GUARD] == ca.PLAN_GUARD_AUDITED_BYPASS
    bad = row.fields()
    bad["labels"] = {**row.labels, ca.LABEL_CTX_PLAN_REFUSED: "plan_gold_span"}
    with pytest.raises(lg.LedgerIntegrityError, match="lookalike"):
        lg.GradeRow(**bad)
