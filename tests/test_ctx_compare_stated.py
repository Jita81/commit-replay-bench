"""The paired reader on a stated-requirement set (ADR-0052 item 6), and its cost block.

Navigation
----------
What it is:   The tests of ``crb.core.ctx_compare.ctx_pair`` for ``ctx.req*`` treatments, and
              of the cost block, windows and drift flag every pair now carries.
What it does: Pins the stated banner and provenance line, linkage by items digest for a
              structure contrast (head to head), the placebo's link through its matched
              treatment, ``ctx_pair_items_mismatch`` for a stated treatment against any other
              set (and a stated control against a non-stated treatment), the tests-only
              provenance strata, the per-side cost and paired cost difference, and drift.
How:          Rows from tests/fixtures/ctx_rows.py (``req_set``, ``side``), cost and time
              overridden per row.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0052-stated-requirement-arms.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctx_compare.py (under test), tests/test_ctx_compare.py (the v1 pair
              tests), tests/fixtures/ctx_rows.py (the sets and rows paired here)
Tested by:    tests/test_ctx_compare_stated.py
Touch when:   never for a new repository; the stated linkage, banner or cost block change.
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core import ctx_compare as cc
from crb.core import ctxset
from crb.core import stated as st
from crb.core.context_arm import LABEL_CTX_TURNS
from crb.core.ledger import GradeRow
from fixtures.ctx_rows import TASKS, ctx_set, req_set, side

T = TASKS
PROSE = req_set()
CHECKLIST = req_set(structure="checklist")
OTHER = req_set(statement="The command prints its usage when no argument is given")
PLACEBO = req_set(
    ctxset.SOURCE_REQ_PLACEBO,
    statement="Weather over the hills stays calm through the long afternoon",
    matched_to=PROSE.digest,
)
ORACLE = ctx_set()
SETS = {s.digest: s for s in (PROSE, CHECKLIST, OTHER, PLACEBO, ORACLE)}
CONTROL = dict.fromkeys(T, False)
TREAT = {t: i < 4 for i, t in enumerate(T)}


def _pair(control: list[GradeRow], treatment: list[GradeRow], tset: Any = PROSE) -> cc.CtxPair:
    return cc.ctx_pair(control, treatment, task_ids=tset.task_ids, sets=SETS)


def _refused(reason: str, control: list[GradeRow], treatment: list[GradeRow]) -> None:
    with pytest.raises(cc.CtxPairRefused) as exc:
        _pair(control, treatment)
    assert exc.value.reason == reason, exc.value


def test_a_stated_pair_leads_with_the_stated_banner_and_its_provenance() -> None:
    pair = _pair(side(PROSE, CONTROL, role=ctxset.ROLE_CONTROL), side(PROSE, TREAT))
    assert pair.stated and pair.ceiling and not pair.head_to_head
    d = pair.to_dict()
    assert next(iter(d)) == "banner" and d["banner"] == cc.STATED_BANNER
    assert d["provenance"][st.PROV_NOWHERE] == len(T)
    assert d["provenance"][st.PROV_ATTESTED] == len(T)
    text = cc.render(pair)
    assert text.splitlines()[0] == cc.STATED_BANNER
    assert text.splitlines()[1].startswith("provenance ")
    assert "leak-guarded" in cc.STATED_BANNER and "uncontaminated" not in cc.STATED_BANNER


def test_a_non_stated_pair_keeps_its_ceiling_banner_and_no_stated_keys() -> None:
    pair = cc.ctx_pair(
        side(ORACLE, CONTROL, role=ctxset.ROLE_CONTROL),
        side(ORACLE, TREAT),
        task_ids=ORACLE.task_ids,
        sets=SETS,
    )
    d = pair.to_dict()
    assert d["banner"] == cc.CEILING_BANNER
    assert not {"stated", "provenance", "prov_strata", "head_to_head"} & set(d)


def test_a_structure_contrast_links_by_items_digest_head_to_head() -> None:
    assert PROSE.items_digest == CHECKLIST.items_digest and PROSE.digest != CHECKLIST.digest
    pair = _pair(side(PROSE, CONTROL), side(CHECKLIST, TREAT), CHECKLIST)
    assert pair.head_to_head and pair.control_set == PROSE.digest
    assert (pair.b, pair.c) == (4, 0)


def test_the_placebo_links_through_its_matched_treatment() -> None:
    pair = _pair(side(PROSE, CONTROL), side(PLACEBO, TREAT), PLACEBO)
    assert pair.stated and not pair.head_to_head


def test_a_stated_treatment_against_other_items_or_a_non_stated_set_is_refused() -> None:
    _refused(cc.REASON_ITEMS_MISMATCH, side(OTHER, CONTROL), side(PROSE, TREAT))
    _refused(cc.REASON_ITEMS_MISMATCH, side(ORACLE, CONTROL), side(PROSE, TREAT))
    with pytest.raises(cc.CtxPairRefused) as exc:
        cc.ctx_pair(side(PROSE, CONTROL), side(ORACLE, TREAT), task_ids=ORACLE.task_ids, sets=SETS)
    assert exc.value.reason == cc.REASON_ITEMS_MISMATCH


def test_an_unstored_control_set_is_unlinked() -> None:
    with pytest.raises(cc.CtxPairRefused) as exc:
        cc.ctx_pair(
            side(CHECKLIST, CONTROL),
            side(PROSE, TREAT),
            task_ids=PROSE.task_ids,
            sets={PROSE.digest: PROSE},
        )
    assert exc.value.reason == cc.REASON_UNLINKED


def test_tests_only_items_get_their_own_stratum() -> None:
    mixed = req_set(
        provenance=st.PROV_TESTS_ONLY,
        statements={
            t: f"The command keeps flag number {i} working unchanged" for i, t in enumerate(T)
        },
    )
    sets = {mixed.digest: mixed}
    pair = cc.ctx_pair(
        side(mixed, CONTROL, role=ctxset.ROLE_CONTROL),
        side(mixed, TREAT),
        task_ids=mixed.task_ids,
        sets=sets,
    )
    (only,) = pair.prov_strata
    assert only.tests_only is True and only.treatment.n == len(T)
    no = cc.ctx_pair(
        side(PROSE, CONTROL, role=ctxset.ROLE_CONTROL), side(PROSE, TREAT), task_ids=T, sets=SETS
    )
    assert [s.tests_only for s in no.prov_strata] == [False]


def test_the_cost_block_reads_cost_tokens_and_turns_per_side_and_paired() -> None:
    ctl = [
        *side(PROSE, {T[0]: False}, role=ctxset.ROLE_CONTROL, cost_usd=0.10, tokens_in=100),
        *side(PROSE, {T[1]: False}, role=ctxset.ROLE_CONTROL, cost_usd=0.30, tokens_in=300),
    ]
    trt = [
        *side(PROSE, {T[0]: True}, cost_usd=0.20, tokens_out=7, labels={LABEL_CTX_TURNS: "4"}),
        *side(PROSE, {T[1]: True}, cost_usd=0.60, tokens_out=9, labels={LABEL_CTX_TURNS: "6"}),
    ]
    d = _pair(ctl, trt).to_dict()["cost"]
    assert d["control"]["cost_usd_median"] == pytest.approx(0.2)
    assert d["control"]["tokens_in_total"] == 400
    assert d["control"]["turns_missing"] == 2
    assert d["treatment"]["cost_usd_total"] == pytest.approx(0.8)
    assert d["treatment"]["tokens_out_median"] == 8
    assert d["treatment"]["turns_median"] == 5 and d["treatment"]["turns_missing"] == 0
    paired = d["paired_cost_usd_diff"]
    assert paired["n"] == 2 and paired["median"] == pytest.approx(0.2)
    # inclusive quartiles of (0.1, 0.3)
    assert paired["iqr"] == [pytest.approx(0.15), pytest.approx(0.25)]


@pytest.mark.parametrize(
    ("ctl_at", "trt_at", "drift"),
    [
        ("2026-11-01T00:00:00+00:00", "2026-11-03T00:00:00+00:00", False),
        ("2026-11-01T00:00:00+00:00", "2026-11-20T00:00:00+00:00", True),
        ("2026-11-20T00:00:00+00:00", "2026-11-01T00:00:00+00:00", True),
    ],
)
def test_drift_flags_sides_run_more_than_a_week_apart(
    ctl_at: str, trt_at: str, drift: bool
) -> None:
    pair = _pair(
        side(PROSE, CONTROL, role=ctxset.ROLE_CONTROL, created=ctl_at),
        side(PROSE, TREAT, created=trt_at),
    )
    d = pair.to_dict()
    assert d["drift"] is drift and d["windows"]["control"]["first"] == ctl_at
    assert ("drift:" in cc.render(pair)) is drift


def test_the_new_reason_is_a_known_reason() -> None:
    assert cc.REASON_ITEMS_MISMATCH in cc.REASONS
