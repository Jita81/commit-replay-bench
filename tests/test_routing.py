"""crb.core.routing — every branch of the ONE published routing rule, routing.v2.

Navigation
----------
What it is:   The routing rule's test suite — every clause of routing.v2 (ADR-0025 as ADR-0026
              amends it), and the controls verdict read at the cell's apparatus.
What it does: Pins the clause order — do-not-ship on any false-Q1, granularize XL, a failed
              controls gate routing human even when the reading delivers (the click case), the
              sealed posture, belt 5 switched off, the reading (unregistered, descriptive, look
              pending), the oracle (unmeasured, thin, weak), escaped controls, the reading
              decided against (insufficient, undecided), the standard (a ceiling, a leaner
              standard), unmeasured and thin controls, deliver — the policy's refusals of any
              relaxation, the reason codes, and every failing clause listed as a shortfall.
How:          ``CellStats`` and an ``ArmVerdict`` built directly; every case is
              ``route(stats, oracle=…, controls=…, reading=…)``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md,
              docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/routing.py (under test), src/crb/core/reading.py (``ArmVerdict``),
              src/crb/core/ledger.py (``CellStats`` / ``CellKey``), tests/test_routing_v2.py
              (the same rule driven through readings and the map)
Tested by:    tests/test_routing.py
Touch when:   never for a new repository; never to make a threshold LESS strict without an ADR
              (docs/CONTRIBUTING.md); a clause or reason code is added (a case per branch here and a
              reason-code coverage update).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core import routing as rt
from crb.core.ledger import CellKey, CellStats
from crb.core.reading import (
    VERDICT_CEILING,
    VERDICT_DELIVER,
    VERDICT_DESCRIPTIVE,
    VERDICT_INSUFFICIENT,
    VERDICT_LEANER,
    VERDICT_LOOK_PENDING,
    VERDICT_UNDECIDED,
    ArmVerdict,
)
from crb.core.stats import wilson_interval

ARM = "S1@claude-opus-5"


def stats(
    clean: int = 20,
    n: int = 20,
    *,
    size: str = "XS",
    false_q1: int = 0,
    arm: str = ARM,
    **kw: Any,
) -> CellStats:
    """A ``CellStats`` of apparatus 2.4 from counts alone, every row in the sealed posture."""
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
        "oracle_strength_mean": None,
        "apparatus_versions": ("2.4",),
        "apparatus_version": "2.4",
        "context_arm": arm,
        "taxonomy": "global/classes@v1",
        "n_tasks": n,
        "task_clean": clean,
        "task_ci": wilson_interval(clean, n),
    }
    base.update(kw)
    return CellStats(**base)


def reading(state: str = VERDICT_DELIVER, **kw: Any) -> ArmVerdict:
    """What the cell's registered reading says about the arm (delivering by default)."""
    base: dict[str, Any] = {
        "arm": ARM,
        "state": state,
        "reading_id": "rdg_" + "a" * 24,
        "rule": "look.v1",
        "counted": 20,
        "clean": 20,
        "standard": ARM,
        "counted_commits": tuple(f"c{i}" for i in range(20)),
    }
    base.update(kw)
    return ArmVerdict(**base)


def oracle(strength: float | None = 0.9, scored: int = 20, n: int = 20) -> rt.OracleEvidence:
    return rt.OracleEvidence(strength=strength, scored_tasks=scored, n_tasks=n)


def verdict(
    *,
    passed: bool = True,
    constructible: int = 56,
    total: int = 56,
    escapes: int = 0,
    run_id: str = "0" * 32,
    **kw: Any,
) -> rt.ControlsVerdict:
    """A ``ControlsVerdict`` at 2.4 that PASSES with every control constructible and no escape
    unless overridden."""
    return rt.ControlsVerdict(
        passed=passed,
        constructible=constructible,
        total=total,
        escapes=escapes,
        run_id=run_id,
        created="2026-09-27T00:00:00+00:00",
        apparatus_version=kw.pop("apparatus_version", "2.4"),
        **kw,
    )


def go(
    s: CellStats | None = None,
    *,
    r: ArmVerdict | None = None,
    o: rt.OracleEvidence | None = None,
    c: rt.ControlsVerdict | None = None,
    **kw: Any,
) -> rt.RouteDecision:
    """``route`` with everything measured and delivering unless a keyword says otherwise."""
    return rt.route(
        s if s is not None else stats(),
        reading=r if r is not None else reading(),
        oracle=o if o is not None else oracle(),
        controls=c if c is not None else verdict(),
        **kw,
    )


def test_deliver_only_when_every_clause_holds() -> None:
    d = go()
    assert d.route == rt.ROUTE_DELIVER and d.reason_code == rt.REASON_DELIVER
    assert d.shortfalls == ()
    assert d.policy_version == "routing.v2" and d.controls_policy == "controls-gate.v2"
    assert d.standard == ARM and d.look_state == VERDICT_DELIVER and d.counted == 20
    assert "is the cell's standard: 20 of 20 clean" in d.reason
    assert d.reason.endswith("escapes=0 · false_q1=0")


def test_do_not_ship_on_any_false_q1() -> None:
    d = go(stats(false_q1=1))
    assert d.route == rt.ROUTE_DO_NOT_SHIP
    assert "false-Q1" in d.reason and d.false_q1 == 1


def test_granularize_xl_before_anything_else() -> None:
    d = go(stats(size="XL"))
    assert d.route == rt.ROUTE_GRANULARIZE
    assert d.reason == "size XL is split before attempting"
    assert go(stats(size="XL", false_q1=2)).route == rt.ROUTE_DO_NOT_SHIP


def test_failed_gate_routes_human_even_when_the_reading_delivers() -> None:
    """The click case: regression 7/7 violations under TARGET_ONLY — belt 3 blind."""
    d = go(c=verdict(passed=False))
    assert d.route == rt.ROUTE_HUMAN and d.reason_code == rt.REASON_CONTROLS_FAILED
    assert d.reason.startswith("controls_failed:") and "instrument defect" in d.reason
    assert "(controls run 00000000)" in d.reason
    # a failed gate outranks the reading: every cell of the repo says so
    thin = go(r=reading(VERDICT_LOOK_PENDING, needed=5, next_look=20), c=verdict(passed=False))
    assert thin.route == rt.ROUTE_HUMAN and thin.reason_code == rt.REASON_CONTROLS_FAILED
    assert go(stats(false_q1=1), c=verdict(passed=False)).route == rt.ROUTE_DO_NOT_SHIP
    assert go(stats(size="XL"), c=verdict(passed=False)).route == rt.ROUTE_GRANULARIZE


def test_rows_outside_the_sealed_posture_route_calibrate() -> None:
    d = go(stats(n_unsealed=3))
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_POSTURE_UNSEALED
    assert d.shortfalls[0].next == "seal" and not d.shortfalls[0].model_money
    # S2 is graded on held-out acceptance tests instead: the clause does not apply to it
    s2 = go(stats(arm="S2", n_unsealed=3), r=reading(arm="S2", standard="S2"))
    assert s2.route == rt.ROUTE_DELIVER


def test_belt_5_switched_off_never_helps_a_cell() -> None:
    d = go(stats(n_tasks_lint_disabled=2), r=reading(VERDICT_LOOK_PENDING, needed=3, next_look=20))
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_LINT_DISABLED
    assert d.shortfalls[0].next == "config"


def test_a_cell_without_a_registered_reading_routes_calibrate() -> None:
    d = rt.route(stats(), oracle=oracle(), controls=verdict())
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_READING_UNREGISTERED
    assert d.shortfalls[0].next == "register"
    desc = go(stats(arm="A0"), r=reading(VERDICT_DESCRIPTIVE, arm="A0"))
    assert desc.reason_code == rt.REASON_DESCRIPTIVE and desc.route == rt.ROUTE_CALIBRATE


def test_a_pending_look_routes_calibrate_and_names_the_commits_still_needed() -> None:
    d = go(r=reading(VERDICT_LOOK_PENDING, counted=20, clean=19, needed=10, next_look=30))
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_LOOK_PENDING
    first = d.shortfalls[0]
    assert (first.next, first.count, first.model_money) == ("replay", 10, True)
    assert "look at 30" in d.reason and d.needed == 10


def test_an_unmeasured_or_thin_oracle_routes_calibrate() -> None:
    assert go(o=oracle(None, 0)).reason_code == rt.REASON_ORACLE_UNMEASURED
    d = rt.route(stats(), reading=reading(), controls=verdict())
    assert d.reason_code == rt.REASON_ORACLE_UNMEASURED and d.oracle_strength is None
    thin = go(o=oracle(0.95, scored=9, n=20))
    assert thin.route == rt.ROUTE_CALIBRATE and thin.reason_code == rt.REASON_ORACLE_THIN
    assert thin.shortfalls[0].count == 11
    # exactly half scored is enough (the majority rule the controls gate applies)
    assert go(o=oracle(0.95, scored=10, n=20)).route == rt.ROUTE_DELIVER


def test_human_when_the_oracle_is_too_weak_even_if_green() -> None:
    d = go(o=oracle(0.5))
    assert d.route == rt.ROUTE_HUMAN and d.reason_code == rt.REASON_ORACLE_WEAK
    assert "oracle strength 0.50" in d.reason and d.oracle_strength == 0.5
    # exactly 0.80 is NOT too weak
    assert go(o=oracle(0.80)).route == rt.ROUTE_DELIVER


def test_escapes_route_human_and_a_laxer_bar_must_name_itself() -> None:
    d = go(c=verdict(escapes=3))
    assert d.route == rt.ROUTE_HUMAN and d.reason_code == rt.REASON_CONTROLS_ESCAPES
    assert "3 measurement control(s) graded clean" in d.reason
    with pytest.raises(ValueError, match=r"cannot use version 'routing.v2'.*max_controls_escapes"):
        rt.RoutingPolicy(max_controls_escapes=3)
    lax = rt.RoutingPolicy(max_controls_escapes=3, version="routing.v2-lax")
    assert lax.relaxed_clauses() == ("max_controls_escapes",)
    lax_d = go(c=verdict(escapes=3), policy=lax)
    assert lax_d.route == rt.ROUTE_DELIVER and "escapes=3" in lax_d.reason
    assert go(c=verdict(escapes=4), policy=lax).route == rt.ROUTE_HUMAN


def test_the_reading_decided_against_routes_human_or_calibrate() -> None:
    ins = go(r=reading(VERDICT_INSUFFICIENT, counted=5, clean=2))
    assert ins.route == rt.ROUTE_HUMAN and ins.reason_code == rt.REASON_INSUFFICIENT
    assert "never read again" in ins.reason and ins.shortfalls[0].next == "new_reading"
    und = go(r=reading(VERDICT_UNDECIDED, counted=15, clean=15, next_look=20, needed=5))
    assert und.route == rt.ROUTE_CALIBRATE and und.reason_code == rt.REASON_UNDECIDED
    assert und.shortfalls[0].next == "mine"


def test_only_the_standard_arm_delivers() -> None:
    ceiling = go(stats(arm="S3"), r=reading(VERDICT_CEILING, arm="S3", standard=""))
    assert ceiling.route == rt.ROUTE_CALIBRATE and ceiling.reason_code == rt.REASON_CEILING
    assert ceiling.shortfalls[0].next == "calibration_builds"
    assert ceiling.shortfalls[0].model_money
    richer = f"{ARM}+facts@gpt-oss-120b"
    leaner = go(stats(arm=richer), r=reading(VERDICT_LEANER, arm=richer))
    assert leaner.route == rt.ROUTE_CALIBRATE and leaner.reason_code == rt.REASON_LEANER_STANDARD


def test_unmeasured_controls_route_calibrate() -> None:
    d = go(c=rt.ControlsVerdict.unmeasured())
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_CONTROLS_UNMEASURED
    assert d.reason.startswith("controls_unmeasured:") and "run a 'controls' run" in d.reason
    assert d.controls is not None and not d.controls.measured
    assert d.to_dict()["controls"]["measured"] is False
    # nothing evaluated reads as unmeasured, never as a pass
    none = rt.route(stats(), reading=reading(), oracle=oracle())
    assert none.reason_code == rt.REASON_CONTROLS_UNMEASURED
    # a report of another apparatus is history; an incomplete run that found nothing cannot pass
    assert go(c=verdict(apparatus_version="2.3")).reason_code == rt.REASON_CONTROLS_UNMEASURED
    assert go(c=verdict(complete=False)).reason_code == rt.REASON_CONTROLS_UNMEASURED
    # an incomplete run that FOUND a violation fails: a violation found is a violation
    assert go(c=verdict(complete=False, passed=False)).route == rt.ROUTE_HUMAN


def test_thin_controls_route_calibrate() -> None:
    d = go(c=verdict(constructible=24, total=56))
    assert d.route == rt.ROUTE_CALIBRATE and d.reason_code == rt.REASON_CONTROLS_THIN
    assert "only 24 of 56 control rows were constructible (43% < 50%)" in d.reason
    assert go(c=verdict(constructible=28)).route == rt.ROUTE_DELIVER
    assert go(c=verdict(constructible=0, total=0)).route == rt.ROUTE_CALIBRATE


def test_every_failing_clause_is_listed_in_order() -> None:
    d = rt.route(stats(n_unsealed=1), reading=reading(VERDICT_CEILING, arm=ARM))
    codes = [s.code for s in d.shortfalls]
    assert codes == [
        rt.REASON_POSTURE_UNSEALED,
        rt.REASON_ORACLE_UNMEASURED,
        rt.REASON_CEILING,
        rt.REASON_CONTROLS_UNMEASURED,
    ]
    assert d.reason_code == codes[0]
    assert all(s.to_dict()["code"] == c for s, c in zip(d.shortfalls, codes, strict=True))


def test_route_decision_to_dict_carries_the_reading_and_the_counts() -> None:
    d = go().to_dict()
    assert d["route"] == "deliver" and d["basis"] == "first_observed_attempt"
    assert d["cell"]["builder"] == "agentic" and d["context_arm"] == ARM
    assert d["taxonomy"] == "global/classes@v1" and d["apparatus_version"] == "2.4"
    assert (d["n_tasks"], d["task_clean"], d["counted"], d["counted_clean"]) == (20, 20, 20, 20)
    assert d["oracle_scored_tasks"] == 20 and d["oracle_share"] == 1.0
    assert d["policy_thresholds"] == rt.DEFAULT_POLICY.thresholds()
    assert d["shortfalls"] == []


def test_the_published_policy_refuses_every_relaxation() -> None:
    p = rt.DEFAULT_POLICY
    assert p.rule == "look.v1" and p.min_oracle_share == 0.5 and p.cell_error_budget == 0.05
    assert p.controls_version == rt.CONTROLS_POLICY_VERSION == "controls-gate.v2"
    assert p.version == rt.POLICY_VERSION == "routing.v2"
    with pytest.raises(ValueError, match="retired"):
        rt.RoutingPolicy(version="routing.v1")
    with pytest.raises(ValueError, match="under any name"):
        rt.RoutingPolicy(min_oracle_share=0.2, version="routing.v2-lax")
    with pytest.raises(ValueError, match="looser"):
        rt.RoutingPolicy(cell_error_budget=0.1)
    tighter = rt.RoutingPolicy(rule="look.v1-late", min_oracle_strength=0.9)
    assert tighter.relaxed_clauses() == ()
    assert go(o=oracle(0.85), policy=tighter).route == rt.ROUTE_HUMAN
    strict = rt.RoutingPolicy(granularize_sizes=("L", "XL"))
    assert go(stats(size="L"), policy=strict).route == rt.ROUTE_GRANULARIZE
    assert p.to_dict()["description"] == p.describe()


def test_controls_verdict_from_counts_both_shapes() -> None:
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
    report = {
        "n_tasks": 2,
        "n_rows": 14,
        "violations": 2,
        "escapes": 0,
        "not_constructible": 2,
        "skipped": 7,
        "passed": False,
        "apparatus": {"complete": False, "apparatus_version": "2.4"},
        "run_id": "e" * 32,
        "reported_at": "2026-09-13T01:00:00+00:00",
    }
    w = rt.ControlsVerdict.from_counts(report)
    assert (w.passed, w.constructible, w.total, w.escapes) == (False, 5, 7, 0)
    assert w.run_id == "e" * 32 and not w.complete and w.apparatus_version == "2.4"
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
    assert verdict(complete=False).state(**kw) == rt.CONTROLS_UNMEASURED
    assert verdict().state(**kw) == rt.CONTROLS_PASSED
    assert verdict(passed=False, escapes=2, constructible=1).state(**kw) == rt.CONTROLS_FAILED
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
        "created": "2026-09-27T00:00:00+00:00",
        "apparatus_version": "2.4",
        "detail": "",
    }


def test_reason_codes_cover_every_clause_and_decision_refuses_unknown() -> None:
    assert rt.REASON_CODES_V2 == (
        "false_q1",
        "granularize",
        "controls_failed",
        "posture_unsealed",
        "lint_disabled",
        "reading_unregistered",
        "descriptive",
        "look_pending",
        "oracle_unmeasured",
        "oracle_thin",
        "oracle_weak",
        "controls_escapes",
        "insufficient",
        "undecided",
        "ceiling",
        "leaner_standard",
        "controls_unmeasured",
        "controls_thin",
        "deliver",
    )
    # routing.v1's retired codes still validate on a stored decision
    assert set(rt.REASON_CODES_V1) <= set(rt.REASON_CODES)
    with pytest.raises(ValueError, match="reason_code"):
        rt.RouteDecision(
            "deliver", "r", {}, 1, 1.0, 1.0, 0, None, "routing.v2", 1.0, reason_code="vibes"
        )
    with pytest.raises(ValueError, match="shortfall code"):
        rt.Shortfall("n_below_min", "calibrate", 1, 10, "replay")


def test_a_decision_cannot_be_built_without_the_upper_end_of_its_interval() -> None:
    """``ci_high`` had a ``1.0`` default, so a caller who measured ``ci_low`` and omitted it
    serialised a made-up upper bound beside a measured lower one. Mistake-proofed."""
    with pytest.raises(TypeError, match="ci_high"):
        rt.RouteDecision("deliver", "r", {}, 10, 0.9, 0.67, 0, None, "routing.v2")  # type: ignore[call-arg]
    made = rt.RouteDecision("deliver", "r", {}, 10, 0.9, 0.67, 0, None, "routing.v2", 0.98)
    assert made.to_dict()["ci_high"] == 0.98


def test_routes_constant_lists_every_route() -> None:
    assert set(rt.ROUTES) == {"deliver", "calibrate", "granularize", "human", "do_not_ship"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_oracle_strength", 0.9),
        ("min_oracle_share", 0.75),
        ("min_controls_share", 0.6),
        ("max_controls_escapes", 1),
        ("cell_error_budget", 0.01),
    ],
)
def test_the_published_bar_moves_with_every_threshold_it_names(field: str, value: Any) -> None:
    """P-347: ``describe()`` typed "at least half", "at least half its controls" and "let no
    measurement control escape" instead of reading the policy, so a tightened policy kept
    publishing the old bar and the claims gate, which compares README with ``describe()``,
    stayed green. Every threshold the sentence names is rendered from its field."""
    from dataclasses import replace

    from crb.core.routing import DEFAULT_POLICY

    # a looser threshold must carry its own version string (it is not the published bar)
    extra = {"version": "routing.v2-local"} if field == "max_controls_escapes" else {}
    moved = replace(DEFAULT_POLICY, **{field: value}, **extra)
    assert moved.describe() != DEFAULT_POLICY.describe(), field
    if extra:  # the version string alone must not be what moved
        assert "let at most 1 measurement control escape" in moved.describe()
    else:
        assert f"{value:.0%}" in moved.describe() or f"{value:.2f}" in moved.describe()
