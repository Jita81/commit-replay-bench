"""The value scorecard — working changes per pound, blind, and whether the loop is learning.

Navigation
----------
What it is:   The test suite for ``crb.core.value`` — the north-star number, clean → working
              precision, the process-loss share, the learning curve, the register seam and the
              prospective routing precision.
What it does: Pins that the valid denominator excludes outage, harness, disqualified and
              known-bad-oracle rows; that precision reads reviews when there are enough and a
              labelled proxy otherwise (a patch with no lint verdict is unknown, not working;
              a broken public API is never working); that the north star is blind clean rate ×
              precision over every pound spent on blind attempts, with the product of the two
              Wilson bounds as its interval; that the learning curve and the routing precision
              use only prior data (a later row can never change an earlier window or decision);
              that the register seam's statuses become the closed and process shares; that the
              default is the current apparatus and pooling is flagged; and that an unmeasured
              figure is null, never zero.
How:          Rows built directly as ``ValueRow`` (no store); one ``GradeRow`` for the adapter;
              known Wilson values from ``crb.core.stats``; prefix-invariance checks for the two
              time-ordered measures.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/value.py (under test), src/crb/core/stats.py (the interval),
              src/crb/core/routing.py (the rule the prospective decisions replay),
              src/crb/core/ledger.py (the failure kinds and the row the adapter reads)
Tested by:    tests/test_value.py
Touch when:   a measure is added to the scorecard, the valid denominator changes, or stream L's
              register replaces the stub behind ``default_register`` (pin its statuses here).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from crb.core.ledger import (
    FAILURE_BUDGET,
    FAILURE_BUILDER_RED,
    FAILURE_CLEAN,
    FAILURE_DISQUALIFIED,
    FAILURE_HARNESS,
    FAILURE_LINT,
    FAILURE_OUTAGE,
    FAILURE_PROTOCOL,
    GradeRow,
)
from crb.core.review import ReviewRecord
from crb.core.routing import ROUTE_CALIBRATE, ROUTE_DELIVER
from crb.core.stats import wilson_interval
from crb.core.value import (
    BASIS_PROXY,
    BASIS_REVIEW,
    BASIS_REVIEW_POOLED,
    MIN_REVIEWS_FOR_REVIEW_BASIS,
    ClassStatus,
    KindRegister,
    ReviewVerdict,
    ValueRow,
    default_register,
    learning_curve,
    process_loss,
    prospective_routing,
    proxy_working,
    select_rows,
    stub_signature,
    value_report,
    value_row_from_grade,
    verdicts_from_reviews,
)

T0 = datetime(2026, 9, 14, tzinfo=UTC)


def vr(
    i: int,
    *,
    mode: str = "blind",
    kind: str = FAILURE_BUILDER_RED,
    cost: float = 1.0,
    repo: str = "alpha",
    cls: str = "bug.fix",
    size: str = "XS",
    lint: bool | None = True,
    api: bool | None = None,
    app: str = "2.2",
    gold: bool | None = True,
    detail: str = "",
    row_hash: str = "",
) -> ValueRow:
    return ValueRow(
        row_hash=row_hash or f"{i:064x}",
        repo=repo,
        task_id=f"t{i}",
        created=(T0 + timedelta(minutes=i)).isoformat(),
        capability_class=cls,
        size=size,
        mode=mode,
        clean=kind == FAILURE_CLEAN,
        failure_kind=kind,
        cost_usd=cost,
        apparatus_version=app,
        gold_clean=gold,
        repo_lint_clean=lint if kind == FAILURE_CLEAN else None,
        api_stable=api,
        detail=detail,
    )


def verdict(
    i: int, *, mergeable: bool | None, repo: str = "alpha", row_hash: str = ""
) -> ReviewVerdict:
    return ReviewVerdict(
        grade_row_hash=row_hash,
        repo=repo,
        task_id=f"t{i}",
        grade_clean=True,
        mergeable=mergeable,
        verdict="ok" if mergeable else "style",
    )


# --- the row -----------------------------------------------------------------------


def test_a_row_whose_kind_contradicts_clean_is_refused() -> None:
    with pytest.raises(ValueError, match="contradicts"):
        dataclasses.replace(vr(1, kind=FAILURE_CLEAN), failure_kind=FAILURE_LINT)
    with pytest.raises(ValueError, match="not a failure kind"):
        vr(1, kind="bogus")


def test_valid_excludes_outage_harness_disqualified_and_a_bad_oracle() -> None:
    assert vr(1, kind=FAILURE_CLEAN).valid
    assert vr(2, kind=FAILURE_BUDGET).valid and vr(3, kind=FAILURE_PROTOCOL).valid
    assert vr(4, kind=FAILURE_LINT).valid
    for k in (FAILURE_OUTAGE, FAILURE_HARNESS, FAILURE_DISQUALIFIED):
        assert not vr(5, kind=k).valid, k
    assert not vr(6, kind=FAILURE_BUILDER_RED, gold=False).valid
    # the curve's attempts are every row the provider did not refuse: harness bugs are
    # process bugs the loop must see
    assert vr(7, kind=FAILURE_HARNESS).attempted and not vr(8, kind=FAILURE_OUTAGE).attempted


def test_the_adapter_reads_a_grade_row_and_its_optional_api_belt() -> None:
    row = GradeRow(
        repo="alpha",
        task_id="a" * 40,
        clean=True,
        tests_unmodified=True,
        target_green=True,
        no_new_failures=True,
        source_changed=True,
        repo_lint_clean=True,
        capability_class="bug.fix",
        size="S",
        mode="blind",
        cost_usd=0.5,
        evidence_pack_hash="p" * 64,
        labels={"api_stable": "false"},
    ).chained("0" * 64)
    v = value_row_from_grade(row)
    assert v.row_hash == row.row_hash and v.clean and v.failure_kind == FAILURE_CLEAN
    assert v.repo_lint_clean is True and v.api_stable is False and v.mode == "blind"
    assert proxy_working(v) is False  # a public-API break is never working
    assert v.grade is row  # stream L's register reads the full row behind the seam


def test_the_adapter_names_the_protocol_guard_and_the_budget_stop() -> None:
    base = {
        "repo": "alpha",
        "task_id": "b" * 40,
        "clean": False,
        "tests_unmodified": True,
        "target_green": False,
        "no_new_failures": None,
        "source_changed": None,
    }
    prot = GradeRow(**base, error="protocol violation: network: 'pip' is not allowed")
    assert value_row_from_grade(prot).detail == "network"
    budget = GradeRow(**base, labels={"stop_reason": "max_turns"})
    v = value_row_from_grade(budget)
    assert v.failure_kind == FAILURE_BUDGET and v.detail == "max_turns"
    assert stub_signature(v) == "budget:max_turns"
    assert stub_signature(vr(1, kind=FAILURE_CLEAN)) is None


# --- precision ------------------------------------------------------------------------


def test_the_proxy_calls_an_unlinted_patch_unknown_and_a_lint_clean_one_working() -> None:
    assert proxy_working(vr(1, kind=FAILURE_CLEAN, lint=True)) is True
    assert proxy_working(vr(2, kind=FAILURE_CLEAN, lint=None)) is None
    assert proxy_working(vr(3, kind=FAILURE_CLEAN, lint=True, api=False)) is False
    assert proxy_working(vr(4, kind=FAILURE_BUILDER_RED)) is False


def test_precision_reads_reviews_when_there_are_enough_and_says_so() -> None:
    rows = [vr(i, kind=FAILURE_CLEAN) for i in range(10)]
    few = [verdict(i, mergeable=i == 0) for i in range(MIN_REVIEWS_FOR_REVIEW_BASIS - 1)]
    rep = value_report(rows, few, apparatus="all").to_dict()
    assert rep["precision"]["basis"] == BASIS_PROXY
    assert rep["precision"]["proxy"]["k"] == 10 and rep["precision"]["proxy"]["n"] == 10
    enough = [verdict(i, mergeable=i < 2) for i in range(MIN_REVIEWS_FOR_REVIEW_BASIS)]
    rep = value_report(rows, enough, apparatus="all").to_dict()
    assert rep["precision"]["basis"] == BASIS_REVIEW
    rv = rep["precision"]["review"]
    ci = wilson_interval(2, MIN_REVIEWS_FOR_REVIEW_BASIS)
    assert (rv["k"], rv["n"]) == (2, MIN_REVIEWS_FOR_REVIEW_BASIS)
    assert rv["ci_low"] == pytest.approx(ci.low, abs=1e-4)


def test_too_few_reviews_in_a_repository_borrow_every_repositorys_before_the_proxy() -> None:
    rows = [vr(i, kind=FAILURE_CLEAN) for i in range(4)]
    rows += [vr(10 + i, kind=FAILURE_CLEAN, repo="beta") for i in range(4)]
    vs = [verdict(i, mergeable=i == 0, repo="beta") for i in range(MIN_REVIEWS_FOR_REVIEW_BASIS)]
    rep = value_report(rows, vs, repo="alpha", apparatus="all").to_dict()
    assert rep["precision"]["basis"] == BASIS_REVIEW_POOLED
    assert rep["north_star"]["precision"]["n"] == MIN_REVIEWS_FOR_REVIEW_BASIS
    alpha = next(
        r
        for r in value_report(rows, vs, apparatus="all").to_dict()["repos"]
        if r["repo"] == "alpha"
    )
    assert alpha["north_star"]["precision_basis"] == BASIS_REVIEW_POOLED
    beta = value_report(rows, vs, repo="beta", apparatus="all").to_dict()
    assert beta["precision"]["basis"] == BASIS_REVIEW


def test_a_review_that_did_not_answer_mergeable_is_not_counted() -> None:
    rows = [vr(1, kind=FAILURE_CLEAN)]
    vs = [verdict(i, mergeable=None) for i in range(MIN_REVIEWS_FOR_REVIEW_BASIS)]
    rep = value_report(rows, vs, apparatus="all").to_dict()
    assert rep["precision"]["review"]["n"] == 0 and rep["precision"]["basis"] == BASIS_PROXY


def test_a_joined_review_is_scoped_by_its_row_and_proxy_agreement_is_counted() -> None:
    rows = [vr(i, kind=FAILURE_CLEAN, row_hash=f"{i:064x}") for i in range(3)]
    other = vr(9, kind=FAILURE_CLEAN, app="2.1", row_hash="9" * 64)
    vs = [
        verdict(0, mergeable=False, row_hash=f"{0:064x}"),
        verdict(1, mergeable=True, row_hash=f"{1:064x}"),
        verdict(9, mergeable=True, row_hash="9" * 64),  # its row is outside apparatus 2.2
    ]
    rep = value_report([*rows, other], vs).to_dict()
    assert rep["precision"]["review"]["n"] == 2
    agree = rep["precision"]["agreement"]
    # the proxy called both reviewed patches working; the reviewer merged one
    assert agree == {"n": 2, "both_working": 1, "proxy_only": 1, "review_only": 0, "neither": 0}


def test_verdicts_from_reviews_keep_the_latest_per_row() -> None:
    row = vr(1, kind=FAILURE_CLEAN, row_hash="a" * 64)
    older = ReviewRecord(
        grade_row_hash="a" * 64,
        repo="alpha",
        task_id="t1",
        reviewer="u1",
        statement="Looked, not answered.",
        mergeable=None,
        patch_sha256_reviewed="d" * 64,
    )
    newer = dataclasses.replace(older, statement="Mergeable as-is.", mergeable=True, review_id="")
    orphan = dataclasses.replace(older, grade_row_hash="e" * 64, review_id="")
    out = verdicts_from_reviews([older, newer, orphan], {row.row_hash: row})
    # the latest record per row stands; a review of a row not in the ledger is dropped
    assert len(out) == 1 and out[0].mergeable is True and out[0].grade_clean is True


# --- the north star ---------------------------------------------------------------------


def test_the_north_star_is_blind_clean_rate_times_precision_per_pound() -> None:
    # 10 blind valid attempts, 4 clean; 2 outage rows that still cost money; sighted ignored
    rows = [
        vr(i, kind=FAILURE_CLEAN if i < 4 else FAILURE_BUILDER_RED, cost=2.0) for i in range(10)
    ]
    rows += [vr(20 + i, kind=FAILURE_OUTAGE, cost=1.0) for i in range(2)]
    rows += [vr(40 + i, mode="sighted", kind=FAILURE_CLEAN, cost=5.0) for i in range(5)]
    vs = [verdict(i, mergeable=i < 3) for i in range(6)]  # precision 3/6
    ns = value_report(rows, vs, apparatus="all", usd_per_gbp=2.0).to_dict()["north_star"]
    assert ns["n_attempts"] == 12 and ns["n_valid"] == 10 and ns["clean"] == 4
    assert ns["spend_usd"] == pytest.approx(22.0) and ns["spend_gbp"] == pytest.approx(11.0)
    assert ns["working_rate"] == pytest.approx(0.4 * 0.5)
    assert ns["working_estimate"] == pytest.approx(2.0)
    assert ns["per_pound"] == pytest.approx(2.0 / 11.0, abs=1e-4)
    lo = wilson_interval(4, 10).low * wilson_interval(3, 6).low
    hi = wilson_interval(4, 10).high * wilson_interval(3, 6).high
    assert ns["working_rate_low"] == pytest.approx(lo, abs=1e-4)
    assert ns["working_rate_high"] == pytest.approx(hi, abs=1e-4)
    assert ns["per_pound_low"] == pytest.approx(lo * 10 / 11.0, abs=1e-4)
    assert ns["pounds_per_working"] == pytest.approx(11.0 / 2.0, abs=0.01)
    assert ns["precision_basis"] == BASIS_REVIEW and "Wilson" in ns["method"]


def test_an_unmeasured_north_star_is_null_never_zero() -> None:
    ns = value_report([vr(1, mode="sighted", kind=FAILURE_CLEAN)], []).to_dict()["north_star"]
    assert ns["n_valid"] == 0 and ns["per_pound"] is None and ns["working_rate"] is None
    assert ns["clean_rate"]["point"] is None and ns["clean_rate"]["ci_low"] is None


def test_the_default_scope_is_the_current_apparatus_and_pooling_is_flagged() -> None:
    rows = [vr(1, kind=FAILURE_CLEAN, app="2.2"), vr(2, kind=FAILURE_CLEAN, app="2.1")]
    cur = value_report(rows, []).to_dict()
    assert cur["apparatus"] == "2.2" and cur["rows"] == 1 and cur["pooled"] is False
    pooled = value_report(rows, [], apparatus="all").to_dict()
    assert pooled["rows"] == 2 and pooled["pooled"] is True
    assert pooled["apparatus_versions"] == ["2.1", "2.2"]
    assert len(select_rows(rows, repo="beta", apparatus="all")) == 0


# --- process loss -----------------------------------------------------------------------


def test_process_loss_counts_rows_and_pounds_per_kind() -> None:
    rows = [
        vr(1, kind=FAILURE_BUDGET, cost=3.0),
        vr(2, kind=FAILURE_PROTOCOL, cost=1.0),
        vr(3, kind=FAILURE_HARNESS, cost=0.5),
        vr(4, kind=FAILURE_OUTAGE, cost=0.0),
        vr(5, kind=FAILURE_CLEAN, cost=4.0),
        vr(6, kind=FAILURE_BUILDER_RED, cost=1.5),
    ]
    pl = process_loss(rows, usd_per_gbp=1.0).to_dict()
    assert pl["kinds"]["budget"] == {"rows": 1, "usd": 3.0, "gbp": 3.0}
    assert pl["rows"] == 4 and pl["rows_share"] == pytest.approx(4 / 6, abs=1e-4)
    assert pl["usd"] == pytest.approx(4.5) and pl["usd_share"] == pytest.approx(
        4.5 / 10.0, abs=1e-4
    )
    # budget + protocol against the valid non-clean rows (budget, protocol, builder_red)
    assert pl["budget_protocol_share_of_valid_failures"] == pytest.approx(2 / 3, abs=1e-4)


# --- the learning curve -----------------------------------------------------------------


def _curve_rows() -> list[ValueRow]:
    kinds = [FAILURE_PROTOCOL, FAILURE_CLEAN, FAILURE_PROTOCOL, FAILURE_BUDGET] * 3
    return [
        vr(i, kind=k, detail="network" if k == FAILURE_PROTOCOL else "")
        for i, k in enumerate(kinds)
    ]


def test_a_first_sighting_is_new_and_only_a_later_one_recurs() -> None:
    lc = learning_curve(_curve_rows(), window=4, register=KindRegister()).to_dict()
    w0 = lc["windows"][0]
    # window 0: protocol (new), clean, protocol (recurs — seen at attempt 1), budget (new)
    assert (w0["n"], w0["new"], w0["recurrences"]) == (4, 2, 1)
    assert lc["windows"][1]["recurrences"] == 3 and lc["windows"][1]["classes_known"] == 2
    prot = next(c for c in lc["classes"] if c["signature"] == "protocol:network")
    assert prot["first_seen"] == 1 and prot["occurrences"] == 6 and prot["counts"][0] == 1


def test_a_class_is_per_repository() -> None:
    rows = [vr(1, kind=FAILURE_BUDGET), vr(2, kind=FAILURE_BUDGET, repo="beta")]
    lc = learning_curve(rows, window=4, register=KindRegister()).to_dict()
    # the same kind in a second repository is a new class there, not a recurrence
    assert lc["windows"][0]["new"] == 2 and lc["windows"][0]["recurrences"] == 0
    assert [(c["repo"], c["signature"]) for c in lc["classes"]] == [
        ("alpha", "budget"),
        ("beta", "budget"),
    ]


def test_the_curve_never_looks_ahead() -> None:
    rows = _curve_rows()
    full = learning_curve(rows, window=4, register=KindRegister()).to_dict()
    head = learning_curve(rows[:8], window=4, register=KindRegister()).to_dict()
    assert full["windows"][:2] == head["windows"][:2]


def test_the_curve_skips_outage_rows_and_orders_by_time() -> None:
    rows = [*_curve_rows(), vr(100, kind=FAILURE_OUTAGE)]
    shuffled = list(reversed(rows))
    lc = learning_curve(shuffled, window=4, register=KindRegister()).to_dict()
    assert lc["attempts"] == 12
    assert (
        lc["windows"]
        == learning_curve(rows, window=4, register=KindRegister()).to_dict()["windows"]
    )


class _Register:
    """A stand-in for stream L's register: two classes closed, one by process."""

    source = "test"

    def class_of(self, row: ValueRow) -> str | None:
        return stub_signature(row)

    def statuses(self, rows: Sequence[ValueRow]) -> Sequence[ClassStatus]:
        del rows
        return (
            ClassStatus("protocol:network", "alpha", "closed", "process"),
            ClassStatus("budget", "alpha", "closed", "context"),
            ClassStatus("lint", "alpha", "applied", "context"),
            ClassStatus("builder_red", "alpha", "open", ""),
        )


def test_the_register_seam_gives_the_closed_and_process_shares() -> None:
    reg = learning_curve(_curve_rows(), window=4, register=_Register()).to_dict()["register"]
    assert reg["source"] == "test" and reg["n_classes"] == 4
    assert (reg["closed"], reg["closed_share"]) == (2, 0.5)
    assert (reg["removed_by_process"], reg["removed_by_process_share"]) == (1, 0.5)


def test_the_stub_register_says_it_is_a_stub_and_closes_nothing() -> None:
    reg = learning_curve(_curve_rows(), window=4, register=default_register()).to_dict()["register"]
    assert reg["source"].startswith("stub")
    assert reg["closed"] == 0 and reg["removed_by_process_share"] is None
    with pytest.raises(ValueError, match="status"):
        ClassStatus("x", "alpha", "fixed", "")
    with pytest.raises(ValueError, match="lever"):
        ClassStatus("x", "alpha", "closed", "hope")


# --- prospective routing ----------------------------------------------------------------


def test_a_deliver_decision_is_made_from_prior_rows_only() -> None:
    # 16 clean rows lift the Wilson lower bound over 0.80 (16/16 → 0.806); the rows after
    # that are let in under deliver, and a failure among them is scored against it
    rows = [vr(i, mode="sighted", kind=FAILURE_CLEAN) for i in range(30)]
    rows.append(vr(30, mode="sighted", kind=FAILURE_BUILDER_RED))
    rows.append(vr(31, mode="sighted", kind=FAILURE_CLEAN))
    rp = prospective_routing(rows).to_dict()
    assert rp["rows_scored"] == 32
    assert rp["decisions"][ROUTE_CALIBRATE] == 16 and rp["decisions"][ROUTE_DELIVER] == 16
    assert (rp["deliver"]["k"], rp["deliver"]["n"]) == (15, 16)
    # a later row cannot change an earlier decision
    head = prospective_routing(rows[:31]).to_dict()
    assert (head["deliver"]["k"], head["deliver"]["n"]) == (14, 15)
    assert rp["controls"] == "not evaluated"


def test_routing_never_pools_modes_or_repositories() -> None:
    rows = [vr(i, mode="sighted", kind=FAILURE_CLEAN) for i in range(16)]
    rows.append(vr(16, mode="blind", kind=FAILURE_CLEAN))
    rows.append(vr(17, mode="sighted", kind=FAILURE_CLEAN, repo="beta"))
    assert prospective_routing(rows).to_dict()["deliver"]["n"] == 0


def test_no_deliver_decision_is_a_null_precision() -> None:
    rp = prospective_routing([vr(1, kind=FAILURE_CLEAN)]).to_dict()
    assert rp["deliver"]["n"] == 0 and rp["deliver"]["point"] is None


# --- the report -------------------------------------------------------------------------


def test_the_report_carries_cells_and_repositories() -> None:
    rows = [vr(i, kind=FAILURE_CLEAN if i % 2 else FAILURE_BUDGET, size="S") for i in range(6)]
    rows += [vr(10 + i, kind=FAILURE_CLEAN, repo="beta") for i in range(3)]
    rep = value_report(rows, [], apparatus="all").to_dict()
    assert rep["schema"] == "crb.value.v1" and rep["repo"] is None
    assert {r["repo"] for r in rep["repos"]} == {"alpha", "beta"}
    cell = next(c for c in rep["cells"] if c["size"] == "S")
    assert cell["n_valid"] == 6 and cell["clean"]["k"] == 3 and cell["mode"] == "blind"
    one = value_report(rows, [], repo="beta", apparatus="all").to_dict()
    assert one["repo"] == "beta" and one["rows"] == 3 and one["repos"] == []
