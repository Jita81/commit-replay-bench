"""crb.core.routing — every branch of the ONE published routing rule.

Navigation
----------
What it is:   The routing rule's test suite — every clause of the ONE published rule, and the
              controls-verdict amendment.
What it does: Pins the clause order — do-not-ship on any false-Q1, granularize XL, calibrate
              below ``min_n``, human when the oracle is weak even if green, calibrate below the
              point bar or with a wide interval (the essay's 10/10 example), deliver at 48/50 and
              on the boundary values — the policy override, the reason codes, and the controls
              clauses (a failed gate routes human even when green — the click case; thin or
              unmeasured controls calibrate; an escape routes human; ``controls=None`` means the
              caller evaluated none).
How:          ``CellStats`` built directly from counts; every case is ``route(stats, policy)``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/routing.py (under test), src/crb/core/ledger.py (``CellStats`` /
              ``CellKey``), src/crb/core/stats.py (the interval), tests/test_capability.py (the
              rule applied over a map), tests/test_signoff.py (the rule inside the sign-off policy)
Tested by:    tests/test_routing.py
Touch when:   never to make a threshold LESS strict without an ADR (docs/CONTRIBUTING.md); a
              clause or reason code is added (a case per branch here and a reason-code coverage
              update).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core import routing as rt
from crb.core.ledger import CellKey, CellStats
from crb.core.stats import wilson_interval


def stats(
    clean: int,
    n: int,
    *,
    size: str = "XS",
    false_q1: int = 0,
    strength: float | None = None,
    **kw: Any,
) -> CellStats:
    """A ``CellStats`` from counts alone (``clean`` of ``n``; size, false-Q1 and oracle strength
    as named overrides) — the routing rule's only input.
    """
    base: dict[str, Any] = {
        "cell": CellKey("replay", "bug.fix", size, "python", "agentic", "m", "p"),
        "n": n,
        "clean": clean,
        "disqualified": 0,
        "errors": 0,
        "false_q1": false_q1,
        "point": clean / n if n else 0.0,
        "ci": wilson_interval(clean, n),
        "cost_usd_mean": 0.01,
        "latency_s_mean": 5.0,
        "oracle_strength_mean": strength,
        "apparatus_versions": ("2.0",),
    }
    base.update(kw)
    return CellStats(**base)


def test_do_not_ship_on_any_false_q1() -> None:
    d = rt.route(stats(50, 50, false_q1=1))
    assert d.route == rt.ROUTE_DO_NOT_SHIP
    assert "false-Q1" in d.reason and d.false_q1 == 1


def test_granularize_xl_before_anything_else() -> None:
    d = rt.route(stats(50, 50, size="XL"))
    assert d.route == rt.ROUTE_GRANULARIZE
    assert d.reason == "size XL is split before attempting"
    # false-Q1 still wins over size
    assert rt.route(stats(50, 50, size="XL", false_q1=2)).route == rt.ROUTE_DO_NOT_SHIP


def test_calibrate_when_n_below_minimum() -> None:
    d = rt.route(stats(9, 9))
    assert d.route == rt.ROUTE_CALIBRATE and d.reason == "n=9 < 10"
    assert rt.route(stats(0, 0)).route == rt.ROUTE_CALIBRATE


def test_human_when_the_oracle_is_too_weak_even_if_green() -> None:
    d = rt.route(stats(48, 50, strength=0.5))
    assert d.route == rt.ROUTE_HUMAN
    assert "oracle strength 0.50" in d.reason
    assert d.oracle_strength == 0.5
    # the explicit argument overrides the cell's mean
    assert rt.route(stats(48, 50, strength=0.95), oracle_strength=0.79).route == rt.ROUTE_HUMAN
    assert rt.route(stats(48, 50, strength=0.5), oracle_strength=0.9).route == rt.ROUTE_DELIVER


def test_calibrate_when_point_below_bar() -> None:
    d = rt.route(stats(44, 50))  # 0.88
    assert d.route == rt.ROUTE_CALIBRATE and d.reason == "point 0.880 < 0.90"


def test_calibrate_when_interval_too_wide_the_essays_example() -> None:
    """10/10 is a perfect point but the Wilson lower bound is ≈0.72 — not enough evidence."""
    d = rt.route(stats(10, 10))
    assert d.route == rt.ROUTE_CALIBRATE
    assert d.point == 1.0
    assert d.ci_low == pytest.approx(0.722, abs=0.001)
    assert "Wilson lower 0.722 < 0.80" in d.reason and "interval too wide" in d.reason


def test_deliver_48_of_50() -> None:
    d = rt.route(stats(48, 50))
    assert d.route == rt.ROUTE_DELIVER
    assert d.n == 50 and d.point == 0.96 and d.ci_low >= 0.80 and d.false_q1 == 0
    assert d.reason == "n=50 point=0.960 ci_low=0.865 false_q1=0"
    assert d.oracle_strength is None
    assert d.policy_version == rt.POLICY_VERSION
    with_oracle = rt.route(stats(48, 50, strength=0.91))
    assert with_oracle.route == rt.ROUTE_DELIVER and with_oracle.reason.endswith("oracle=0.91")


def test_deliver_boundary_values() -> None:
    # exactly n=10 and point=0.9 is allowed by n and point, but the interval is too wide
    assert rt.route(stats(9, 10)).route == rt.ROUTE_CALIBRATE
    # exactly 0.80 oracle strength is NOT too weak
    assert rt.route(stats(48, 50, strength=0.80)).route == rt.ROUTE_DELIVER
    # a cell that just clears every bar
    d = rt.route(stats(30, 30))
    assert d.route == rt.ROUTE_DELIVER and d.ci_low > 0.80


def test_policy_override() -> None:
    lenient = rt.RoutingPolicy(
        min_n=5,
        min_point=0.8,
        min_ci_low=0.5,
        min_oracle_strength=0.3,
        granularize_sizes=(),
        version="routing.test",
    )
    d = rt.route(stats(5, 5, size="XL", strength=0.4), policy=lenient)
    assert d.route == rt.ROUTE_DELIVER and d.policy_version == "routing.test"
    # the bar it cleared travels with it as numbers, not just a name
    assert (
        d.policy_thresholds["min_n"] == 5 and d.to_dict()["policy_thresholds"]["min_ci_low"] == 0.5
    )
    assert rt.route(stats(*GREEN)).to_dict()["policy_thresholds"] == rt.DEFAULT_POLICY.thresholds()
    strict = rt.RoutingPolicy(granularize_sizes=("L", "XL"))
    assert rt.route(stats(50, 50, size="L"), policy=strict).route == rt.ROUTE_GRANULARIZE
    assert lenient.to_dict() == {
        "min_n": 5,
        "min_point": 0.8,
        "min_ci_low": 0.5,
        "min_oracle_strength": 0.3,
        "granularize_sizes": [],
        "version": "routing.test",
        "min_controls_share": 0.5,
        "max_controls_escapes": 0,
        "controls_version": "controls-gate.v1",
    }
    assert rt.RoutingPolicy() == rt.DEFAULT_POLICY


def test_route_decision_to_dict_carries_n_and_method() -> None:
    d = rt.route(stats(48, 50, strength=0.9)).to_dict()
    assert d["route"] == "deliver"
    assert d["cell"] == {
        "process_step": "replay",
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "python",
        "builder": "agentic",
        "model": "m",
        "provider": "p",
    }
    assert d["n"] == 50 and d["point"] == 0.96 and d["ci_low"] == 0.8654
    assert (
        d["false_q1"] == 0 and d["oracle_strength"] == 0.9 and d["policy_version"] == "routing.v1"
    )
    assert rt.route(stats(1, 1)).to_dict()["oracle_strength"] is None


def test_routes_constant_lists_every_route() -> None:
    assert set(rt.ROUTES) == {"deliver", "calibrate", "granularize", "human", "do_not_ship"}


# ---------------------------------------------------------------------------
# the controls gate (ADR-0003 amendment, controls-gate.v1)
# ---------------------------------------------------------------------------


def verdict(
    *,
    passed: bool = True,
    constructible: int = 56,
    total: int = 56,
    escapes: int = 0,
    run_id: str = "0" * 32,
    **kw: Any,
) -> rt.ControlsVerdict:
    """A ``ControlsVerdict`` that PASSES with every control constructible and no escape unless
    overridden — the controls-clause input the numeric clauses are combined with.
    """
    return rt.ControlsVerdict(
        passed=passed,
        constructible=constructible,
        total=total,
        escapes=escapes,
        run_id=run_id,
        created="2026-09-13T00:00:00+00:00",
        **kw,
    )


GREEN = (48, 50)  # a cell that delivers on the numbers alone


def test_numbers_alone_still_deliver_when_no_verdict_is_evaluated() -> None:
    """``controls=None`` = the caller evaluated none: the decision says so and the
    numeric rule (routing.v1) is unchanged."""
    d = rt.route(stats(*GREEN))
    assert d.route == rt.ROUTE_DELIVER and d.reason_code == rt.REASON_DELIVER
    assert d.controls is None and d.controls_policy == "" and d.policy_version == "routing.v1"
    assert d.to_dict()["controls"] is None and d.to_dict()["controls_policy"] == ""


def test_deliver_only_with_passed_majority_constructible_and_zero_escapes() -> None:
    d = rt.route(stats(*GREEN), controls=verdict())
    assert d.route == rt.ROUTE_DELIVER and d.reason_code == rt.REASON_DELIVER
    assert d.reason.endswith("controls=passed 56/56 escapes=0")
    assert d.controls_policy == "controls-gate.v1" and d.policy_version == "routing.v1"
    assert d.controls is not None and d.controls.run_id == "0" * 32
    assert d.to_dict()["controls"]["passed"] is True
    # exactly half constructible is a majority by the published bar (≥ 0.5)
    assert rt.route(stats(*GREEN), controls=verdict(constructible=28)).route == rt.ROUTE_DELIVER


def test_failed_gate_routes_human_even_when_green() -> None:
    """The click case: regression 7/7 violations under TARGET_ONLY — belt 3 blind."""
    d = rt.route(stats(*GREEN), controls=verdict(passed=False))
    assert d.route == rt.ROUTE_HUMAN and d.reason_code == rt.REASON_CONTROLS_FAILED
    assert d.reason.startswith("controls_failed:") and "instrument defect" in d.reason
    assert "(controls run 00000000)" in d.reason
    # a failed gate outranks n: every cell of the repo says so, not only the green ones
    thin = rt.route(stats(3, 4), controls=verdict(passed=False))
    assert thin.route == rt.ROUTE_HUMAN and thin.reason_code == rt.REASON_CONTROLS_FAILED
    # but never false-Q1 or XL
    assert (
        rt.route(stats(*GREEN, false_q1=1), controls=verdict(passed=False)).route
        == rt.ROUTE_DO_NOT_SHIP
    )
    assert (
        rt.route(stats(*GREEN, size="XL"), controls=verdict(passed=False)).route
        == rt.ROUTE_GRANULARIZE
    )


def test_thin_controls_route_calibrate() -> None:
    """cobra / koa: only gold, noop, test_tamper constructible — 3 of 7."""
    d = rt.route(stats(*GREEN), controls=verdict(constructible=24, total=56))
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_CONTROLS_THIN
    assert "only 24 of 56 control rows were constructible (43% < 50%)" in d.reason
    assert "the load-bearing ones never ran" in d.reason
    # thin is decided after the numbers: a thin cell still says n first
    assert rt.route(stats(3, 4), controls=verdict(constructible=24, total=56)).reason == "n=4 < 10"
    # nothing constructible at all is thin too (share 0.0), never a division error
    assert (
        rt.route(stats(*GREEN), controls=verdict(constructible=0, total=0)).route
        == rt.ROUTE_CALIBRATE
    )


def test_unmeasured_controls_route_calibrate() -> None:
    d = rt.route(stats(*GREEN), controls=rt.ControlsVerdict.unmeasured())
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_CONTROLS_UNMEASURED
    assert d.reason.startswith("controls_unmeasured:") and "run a 'controls' run" in d.reason
    assert d.controls is not None and not d.controls.measured
    assert d.controls_policy == "controls-gate.v1"
    assert d.to_dict()["controls"]["measured"] is False
    # an unmeasured verdict never FAILS a cell (it is absence, not a violation)
    assert rt.route(stats(3, 4), controls=rt.ControlsVerdict.unmeasured()).reason == "n=4 < 10"


def test_escapes_route_human_conservatively() -> None:
    """A measurement control graded clean: the oracle is demonstrably gameable on
    this repo — green cannot license auto-delivery until it is re-measured."""
    d = rt.route(stats(*GREEN), controls=verdict(escapes=3))
    assert d.route == rt.ROUTE_HUMAN and d.reason_code == rt.REASON_CONTROLS_ESCAPES
    assert "3 measurement control(s) graded clean" in d.reason
    # escapes come after n (like oracle strength): a thin cell still calibrates on n
    assert rt.route(stats(3, 4), controls=verdict(escapes=3)).route == rt.ROUTE_CALIBRATE
    # a laxer bar is a policy choice that must NAME itself: under the published version
    # string it is refused, so no decision can read `routing.v1` while clearing a lower
    # bar (external review 2026-09-16, point 9); the thresholds travel on every decision
    with pytest.raises(ValueError, match=r"cannot use version 'routing.v1'.*max_controls_escapes"):
        rt.RoutingPolicy(max_controls_escapes=3)
    lax = rt.RoutingPolicy(max_controls_escapes=3, version="routing.v1-lax")
    assert lax.relaxed_clauses() == ("max_controls_escapes",)
    assert rt.RoutingPolicy(min_n=20).relaxed_clauses() == ()  # tightening keeps the name
    lax_d = rt.route(stats(*GREEN), controls=verdict(escapes=3), policy=lax)
    assert lax_d.route == rt.ROUTE_DELIVER
    assert lax_d.reason.endswith("escapes=3")  # the measured count, never a flattering zero
    assert rt.route(stats(*GREEN), controls=verdict(escapes=4), policy=lax).route == rt.ROUTE_HUMAN


def test_controls_clause_order_against_the_numeric_clauses() -> None:
    v = verdict()
    # weak oracle still wins over a passed gate; below-bar numbers still calibrate
    assert rt.route(stats(*GREEN, strength=0.5), controls=v).reason_code == rt.REASON_ORACLE_WEAK
    assert rt.route(stats(44, 50), controls=v).reason_code == rt.REASON_POINT_BELOW_BAR
    assert rt.route(stats(10, 10), controls=v).reason_code == rt.REASON_CI_LOW_BELOW_BAR
    assert rt.route(stats(9, 9), controls=v).reason_code == rt.REASON_N_BELOW_MIN
    # thin / unmeasured bind only when the numbers would otherwise deliver
    assert (
        rt.route(stats(44, 50), controls=verdict(constructible=1)).reason_code
        == rt.REASON_POINT_BELOW_BAR
    )
    assert (
        rt.route(stats(44, 50), controls=rt.ControlsVerdict.unmeasured()).reason_code
        == rt.REASON_POINT_BELOW_BAR
    )


def test_controls_verdict_from_counts_both_shapes() -> None:
    # the worker's counts_json
    counts = {
        "tasks": 8,
        "total": 8,
        "rows": 56,
        "violations": 0,
        "escapes": 1,
        "not_constructible": 32,
        "skipped": 0,
        "passed": True,
        "complete": True,
    }
    v = rt.ControlsVerdict.from_counts(counts, run_id="r" * 32, created="t")
    assert (v.passed, v.constructible, v.total, v.escapes) == (True, 24, 56, 1)
    assert v.run_id == "r" * 32 and v.created == "t" and v.complete and v.measured
    assert v.share == pytest.approx(24 / 56) and v.thin(0.5) and not v.thin(0.4)
    # the controls.report event payload (ControlsReport.to_dict + run_id/reported_at)
    report = {
        "n_tasks": 2,
        "n_rows": 14,
        "violations": 2,
        "escapes": 0,
        "not_constructible": 2,
        "skipped": 7,
        "passed": False,
        "apparatus": {"complete": False},
        "run_id": "e" * 32,
        "reported_at": "2026-09-13T01:00:00+00:00",
    }
    w = rt.ControlsVerdict.from_counts(report)
    assert (w.passed, w.constructible, w.total, w.escapes) == (False, 5, 7, 0)
    assert w.run_id == "e" * 32 and w.created == "2026-09-13T01:00:00+00:00" and not w.complete
    # an empty mapping is a measured-nothing (0/0), not a crash
    z = rt.ControlsVerdict.from_counts({})
    assert z.total == 0 and z.constructible == 0 and not z.passed and z.share == 0.0
    with pytest.raises(ValueError, match="cannot exceed"):
        rt.ControlsVerdict(passed=True, constructible=5, total=4, escapes=0)
    with pytest.raises(ValueError, match="negative"):
        rt.ControlsVerdict(passed=True, constructible=0, total=0, escapes=-1)


def test_controls_verdict_state_and_to_dict() -> None:
    kw = {"min_share": 0.5, "max_escapes": 0}
    assert rt.ControlsVerdict.unmeasured().state(**kw) == rt.CONTROLS_UNMEASURED
    assert verdict(passed=False).state(**kw) == rt.CONTROLS_FAILED
    assert verdict(escapes=1).state(**kw) == rt.CONTROLS_ESCAPED
    assert verdict(constructible=3, total=7).state(**kw) == rt.CONTROLS_THIN
    assert verdict().state(**kw) == rt.CONTROLS_PASSED
    # failed outranks escaped outranks thin — the order the router applies
    assert verdict(passed=False, escapes=2, constructible=1).state(**kw) == rt.CONTROLS_FAILED
    assert verdict(escapes=2, constructible=1).state(**kw) == rt.CONTROLS_ESCAPED
    assert set(rt.CONTROLS_STATES) == {"unmeasured", "failed", "thin", "escaped", "passed"}
    d = verdict(constructible=3, total=7, escapes=1).to_dict()
    assert d == {
        "measured": True,
        "passed": True,
        "complete": True,
        "constructible": 3,
        "total": 7,
        "share": round(3 / 7, 4),
        "escapes": 1,
        "run_id": "0" * 32,
        "created": "2026-09-13T00:00:00+00:00",
    }


def test_reason_codes_cover_every_clause_and_decision_refuses_unknown() -> None:
    assert set(rt.REASON_CODES) == {
        "false_q1",
        "granularize",
        "controls_failed",
        "n_below_min",
        "oracle_weak",
        "controls_escapes",
        "point_below_bar",
        "ci_low_below_bar",
        "controls_unmeasured",
        "controls_thin",
        "deliver",
    }
    assert rt.route(stats(50, 50, false_q1=1)).reason_code == "false_q1"
    assert rt.route(stats(50, 50, size="XL")).reason_code == "granularize"
    with pytest.raises(ValueError, match="reason_code"):
        rt.RouteDecision(
            "deliver", "r", {}, 1, 1.0, 1.0, 0, None, "routing.v1", 1.0, reason_code="vibes"
        )


def test_a_decision_cannot_be_built_without_the_upper_end_of_its_interval() -> None:
    """``ci_high`` had a ``1.0`` default, so a caller who measured ``ci_low`` and omitted it
    serialised a made-up upper bound beside a measured lower one — and every reader quotes
    the pair as a range. Mistake-proofed: the constructor asks for both ends."""
    with pytest.raises(TypeError, match="ci_high"):
        rt.RouteDecision("deliver", "r", {}, 10, 0.9, 0.67, 0, None, "routing.v1")  # type: ignore[call-arg]
    made = rt.RouteDecision("deliver", "r", {}, 10, 0.9, 0.67, 0, None, "routing.v1", 0.98)
    assert made.to_dict()["ci_high"] == 0.98


def test_default_policy_carries_the_controls_thresholds() -> None:
    p = rt.DEFAULT_POLICY
    assert p.min_controls_share == 0.5 and p.max_controls_escapes == 0
    assert p.controls_version == rt.CONTROLS_POLICY_VERSION == "controls-gate.v1"
    assert p.version == rt.POLICY_VERSION == "routing.v1"
    d = p.to_dict()
    assert d["min_controls_share"] == 0.5 and d["max_controls_escapes"] == 0
    assert d["controls_version"] == "controls-gate.v1" and d["version"] == "routing.v1"
