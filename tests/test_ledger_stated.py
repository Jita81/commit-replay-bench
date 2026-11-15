"""A stated-requirement row's stamps agree with its arm (ADR-0052 item 2), at write and on read.

Navigation
----------
What it is:   The tests of ``crb.core.ledger.ctx_label_violation``'s stated-requirement rules.
What it does: Pins that a ``ctx.req*`` entries row carries every stated stamp, that no other
              row (a control row, an oracle or mech arm, a plain row) carries any of them,
              that ``ctx_turns`` is an optional count on a context-set run's row only, and that
              the ledger refuses a row the rule names.
How:          Labels from ``crb.core.ctxset.run_stamps`` on a parsed v2 set (the labels a run
              writes), hand-edited; rows written through the classification tests' ``_replay``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0052-stated-requirements-source.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ledger.py (under test), src/crb/core/ctxset.py (``run_stamps``),
              tests/fixtures/ctx_rows.py (``req_set``), tests/test_ledger_ctx.py
Tested by:    tests/test_ledger_stated.py
Touch when:   never for a new repository; a stated stamp joins or leaves a row.
"""

from __future__ import annotations

import pytest

from crb.core import context_arm as ca
from crb.core import ctxset
from crb.core import ledger as lg
from crb.core import lint as lint_mod
from fixtures.ctx_rows import TASKS, ctx_set, req_set
from test_ledger_classification import _replay, _result, _task


def _stamps(cset: ctxset.CtxSet, role: str = ctxset.ROLE_ENTRIES) -> dict[str, str]:
    return dict(ctxset.run_stamps(cset, role, dict.fromkeys(cset.task_ids, "1"))[TASKS[0]])


REQ = req_set()
ORACLE = ctx_set()


def test_a_run_stamped_req_row_and_its_control_pass() -> None:
    labels = _stamps(REQ)
    assert set(lg.CTX_STATED_LABELS) <= set(labels)
    assert labels[ca.LABEL_CTX_CEILING] == "1" and ca.LABEL_CTX_DRAFTER not in labels
    assert lg.ctx_label_violation(REQ.arm, labels) == ""
    assert lg.ctx_label_violation(REQ.arm, {**labels, ca.LABEL_CTX_REQ_REFUSED: "req_length"}) == ""
    control = _stamps(REQ, ctxset.ROLE_CONTROL)
    assert not set(lg.CTX_STATED_LABELS) & set(control)
    assert lg.ctx_label_violation(ca.BASE_A0, control) == ""


def test_the_placebo_and_the_checklist_structure_pass() -> None:
    placebo = req_set(ctxset.SOURCE_REQ_PLACEBO, matched_to=REQ.digest)
    assert lg.ctx_label_violation(placebo.arm, _stamps(placebo)) == ""
    checklist = req_set(structure="checklist")
    assert lg.ctx_label_violation(checklist.arm, _stamps(checklist)) == ""


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        ({ca.LABEL_CTX_STATED: None}, "lacks"),
        ({ca.LABEL_CTX_ITEMS: None}, "lacks"),
        ({ca.LABEL_CTX_PROV: ""}, "lacks"),
        ({ca.LABEL_CTX_STATED: "0"}, "ctx_stated"),
        ({ca.LABEL_CTX_ITEMS: "ab" * 6}, "items digest"),
        ({ca.LABEL_CTX_STRUCTURE: "table"}, "ctx_structure"),
        ({ca.LABEL_CTX_AUTHOR_SAW: "tests,diff"}, "ctx_author_saw"),
        ({ca.LABEL_CTX_AUTHOR_SAW: "diff,gold"}, "ctx_author_saw"),
        ({ca.LABEL_CTX_PROV: "product:1"}, "ctx_prov"),
        ({ca.LABEL_CTX_REQ_DRAFTER: "Jane Doe"}, "ctx_req_drafter"),
        ({ca.LABEL_CTX_CEILING: None}, "ctx_ceiling"),
        ({ca.LABEL_CTX_DRAFTER: "drafter.v1"}, "ctx_drafter"),
        ({ca.LABEL_CTX_TURNS: "many"}, "ctx_turns"),
    ],
)
def test_a_req_row_whose_stated_stamps_disagree_is_refused(
    edit: dict[str, str | None], match: str
) -> None:
    labels = _stamps(REQ)
    for k, v in edit.items():
        if v is None:
            labels.pop(k, None)
        else:
            labels[k] = v
    assert match in lg.ctx_label_violation(REQ.arm, labels)


@pytest.mark.parametrize("key", [*lg.CTX_STATED_LABELS, ca.LABEL_CTX_REQ_REFUSED])
def test_no_other_row_carries_a_stated_stamp(key: str) -> None:
    value = _stamps(REQ).get(key, "req_length")
    oracle = {**_stamps(ORACLE), key: value}
    assert "non-req arm" in lg.ctx_label_violation(ORACLE.arm, oracle)
    control = {**_stamps(REQ, ctxset.ROLE_CONTROL), key: value}
    assert "arm's own stamps" in lg.ctx_label_violation(ca.BASE_A0, control)
    assert "without a ctx_set" in lg.ctx_label_violation(ca.BASE_A0, {key: value})


def test_ctx_turns_is_an_optional_count_on_a_context_set_run_row_only() -> None:
    for arm, labels in (
        (REQ.arm, _stamps(REQ)),
        (ORACLE.arm, _stamps(ORACLE)),
        (ca.BASE_A0, _stamps(REQ, ctxset.ROLE_CONTROL)),
    ):
        assert lg.ctx_label_violation(arm, {**labels, ca.LABEL_CTX_TURNS: "7"}) == ""
        assert "ctx_turns" in lg.ctx_label_violation(arm, {**labels, ca.LABEL_CTX_TURNS: "-1"})
    assert "without a ctx_set" in lg.ctx_label_violation(ca.BASE_A0, {ca.LABEL_CTX_TURNS: "7"})
    assert ca.LABEL_CTX_TURNS not in ca.PROVENANCE_LABELS


def test_the_ledger_writes_a_req_row_and_refuses_one_the_rule_names() -> None:
    res = _result(lint_status=lint_mod.LINT_NONE_DETECTED)
    row = _replay(res, _task(), context_arm=REQ.arm, labels=_stamps(REQ))
    assert row.labels[ca.LABEL_CTX_ITEMS] == REQ.items_digest
    bad = row.fields()
    bad["labels"] = {**row.labels, ca.LABEL_CTX_STRUCTURE: "table"}
    with pytest.raises(lg.LedgerIntegrityError, match="ctx_structure"):
        lg.GradeRow(**bad)
