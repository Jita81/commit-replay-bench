"""crb.core.forecast — ex-ante build forecast + the readiness punch-list.

Ports the upstream test_benchmark_forecast cases onto crb types. The forecast
routes every component through the ONE rule; the readiness gate never relaxes
false-Q1 = 0 and reports the specific gaps, not a vibe.

Navigation
----------
What it is:   The forecast's test suite — the ex-ante build forecast and the readiness punch-list.
What it does: Pins component-key parsing, that cost, variance and route come through the ONE rule
              per component, the cheapest-passing config choice, class-only keys, uncosted cells
              reported rather than priced, the single-rep band, the special routes, that the
              thresholds are frozen and never relax false-Q1, and that readiness lists the
              specific gaps, passes only when the bar is met (or relaxed with a sign-off) and
              treats false-Q1 as cardinal.
How:          Rows built per cell with alternating costs so σ is known; ``forecast_build`` /
              ``assess_readiness`` over a capability map, with ``crb.core.signoff`` for the
              sign-off overlay.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/forecast.py (under test), src/crb/core/capability.py (the map it
              reads), src/crb/core/signoff.py (the overlay), src/crb/core/routing.py (the
              routes), tests/test_server_routes_forecast.py (the same numbers served)
Tested by:    tests/test_forecast.py
Touch when:   a readiness gap kind is added (a punch-list case); the forecast's cost model
              changes (re-derive the known σ values).
"""

from __future__ import annotations

import math

import pytest

from crb.core import capability as cap
from crb.core import forecast as fc
from crb.core import signoff as so
from crb.core.ledger import GradeRow
from crb.core.routing import ROUTE_CALIBRATE, ROUTE_DELIVER, ROUTE_GRANULARIZE, ROUTE_HUMAN
from fixtures.posture import posture_row

PACK = "c" * 64


def _row(
    *,
    clean: bool = True,
    cls: str = "bug.fix",
    size: str = "S",
    model: str = "gpt-oss-120b",
    cost: float = 0.0,
    latency: float = 0.0,
    oracle_strength: float | None = None,
    task_id: str = "0123456789abcdef",
) -> GradeRow:
    return posture_row(
        repo="todo",
        task_id=task_id,
        clean=clean,
        tests_unmodified=True,
        target_green=clean,
        no_new_failures=True,
        source_changed=True,
        capability_class=cls,
        size=size,
        language="python",
        builder="agentic",
        model=model,
        provider="cerebras",
        cost_usd=cost,
        latency_s=latency,
        oracle_strength=oracle_strength,
        evidence_pack_hash=PACK if clean else "",
    )


def _cell_rows(
    cls: str,
    size: str,
    *,
    n: int = 40,
    clean: int = 38,
    cost: float = 0.5,
    cost_sd: float = 0.0,
    latency: float = 600.0,
    model: str = "gpt-oss-120b",
    **kw: object,
) -> list[GradeRow]:
    """``n`` rows whose costs alternate ``cost ± cost_sd`` (sample σ ≈ cost_sd for even n)."""
    rows = []
    for i in range(n):
        c = cost + (cost_sd if i % 2 else -cost_sd)
        rows.append(
            _row(
                clean=i < clean,
                cls=cls,
                size=size,
                cost=c,
                latency=latency,
                model=model,
                task_id=f"{i:016x}",
                **kw,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# component keys
# ---------------------------------------------------------------------------


def test_parse_component_key_forms() -> None:
    assert fc.parse_component_key("bug.fix/S") == ("bug.fix", "S")
    assert fc.parse_component_key(("bug.fix", "M")) == ("bug.fix", "M")
    assert fc.parse_component_key("docs.update") == ("docs.update", "")
    assert fc.component_label("bug.fix", "S") == "bug.fix/S"
    assert fc.component_label("bug.fix", "") == "bug.fix"
    with pytest.raises(ValueError, match="not in"):
        fc.parse_component_key("bug.fix/small")  # an input mistake, refused
    with pytest.raises(ValueError, match="no capability class"):
        fc.parse_component_key("/S")


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------


def test_forecast_cost_variance_routing_and_unmeasured() -> None:
    rows = (
        _cell_rows("bug.fix", "S", cost=0.5, cost_sd=0.1)  # deliver
        + _cell_rows("backend.route.add", "M", cost=0.6, clean=40)  # deliver
        + _cell_rows("frontend.component.add", "M", cost=0.7, clean=16)  # 40% → calibrate
    )
    mix = {
        "bug.fix/S": 2,
        "backend.route.add/M": 1,
        "frontend.component.add/M": 1,
        "docs.update/S": 3,
    }
    f = fc.forecast_build(mix, rows)

    assert f.components == 7 and f.measured_components == 4
    assert f.coverage == pytest.approx(4 / 7)
    assert f.costed_components == 4 and f.timed_components == 4
    # cost: 2×0.5 + 0.6 + 0.7 = 2.30 (docs.update unmeasured → not costed)
    assert f.total_cost_mean == pytest.approx(2.30)
    # variance: only bug.fix has σ (≈0.1 sample σ over ±0.1 alternation) over 2 units
    sigma = _sigma_of([0.4, 0.6] * 20)
    assert f.total_cost_stddev == pytest.approx(math.sqrt(2 * sigma**2), rel=1e-6)
    # routing: 3 units deliver, 1 calibrate, 3 not yet measured
    assert f.deliver == 3 and f.calibrate == 1 and f.human == 0
    assert f.units_by_route[cap.NOT_YET_MEASURED] == 3
    assert f.unmeasured == ("docs.update/S",)
    # build time: 4 measured units × 600 s = 40 min
    assert f.total_build_minutes == pytest.approx(40.0)
    # expected clean: 2×0.95 + 1×1.0 + 1×0.4 = 3.3 of 4 measured
    assert f.expected_clean_units == pytest.approx(3.3)
    assert f.p_clean_mean == pytest.approx(3.3 / 4)
    assert f.p_clean_stddev > 0.0 and not f.single_rep_band
    per = {c.label: c for c in f.per_component}
    assert per["bug.fix/S"].config == "agentic/gpt-oss-120b@cerebras"
    assert (
        per["frontend.component.add/M"].config == ""
        and per["frontend.component.add/M"].route == ROUTE_CALIBRATE
    )
    assert per["docs.update/S"].route == cap.NOT_YET_MEASURED and per["docs.update/S"].n == 0
    assert per["bug.fix/S"].n == 40 and per["bug.fix/S"].ci_low is not None
    assert f.policy_version == "routing.v1"
    assert f.to_dict()["unmeasured"] == ["docs.update/S"]


def _sigma_of(xs: list[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def test_forecast_routes_to_cheapest_passing_config() -> None:
    # bug.fix/S is weak on the cheap model but passes on the dear one → priced at the dear one;
    # docs.update passes on both → priced at the cheap one.
    rows = (
        _cell_rows("bug.fix", "S", model="cheap", cost=0.5, clean=2)
        + _cell_rows("bug.fix", "S", model="dear", cost=2.7, clean=40)
        + _cell_rows("docs.update", "S", model="cheap", cost=0.5, clean=40)
        + _cell_rows("docs.update", "S", model="dear", cost=2.7, clean=40)
    )
    f = fc.forecast_build({"bug.fix/S": 1, "docs.update/S": 1}, rows)
    per = {c.label: c for c in f.per_component}
    # the (class × size) cell for bug.fix pools both models: 42/80 → calibrate, so the
    # forecast is honest that the CELL is not deliverable even though one config passes.
    assert per["bug.fix/S"].route == ROUTE_CALIBRATE and per["bug.fix/S"].config == ""
    assert per["docs.update/S"].route == ROUTE_DELIVER and "cheap" in per["docs.update/S"].config
    assert per["docs.update/S"].unit_cost_usd == pytest.approx(0.5)
    # a model-projected forecast is the caller's tool for "escalate to the dear model":
    m = cap.build_capability_map(rows, projection=cap.PROJECTION_CLASS_SIZE_MODEL)
    assert m.get(capability_class="bug.fix", size="S", model="dear").route == ROUTE_DELIVER


def test_forecast_class_only_key_uses_class_projection() -> None:
    rows = _cell_rows("bug.fix", "S", clean=40) + _cell_rows("bug.fix", "M", clean=40)
    f = fc.forecast_build({"bug.fix": 3}, rows)
    c = f.per_component[0]
    assert c.size == "" and c.route == ROUTE_DELIVER and c.n == 80  # the pick pools both sizes
    assert f.deliver == 3


def test_forecast_uncosted_cells_are_reported_not_priced() -> None:
    f = fc.forecast_build({"bug.fix/S": 2}, _cell_rows("bug.fix", "S", cost=0.0, latency=0.0))
    assert f.measured_components == 2 and f.costed_components == 0 and f.timed_components == 0
    assert f.total_cost_mean == 0.0 and f.total_build_minutes == 0.0
    assert f.per_component[0].unit_cost_usd is None and f.per_component[0].unit_minutes is None
    assert "0/2 costed" in fc.render_forecast(f)


def test_single_rep_band_is_surfaced() -> None:
    f = fc.forecast_build(
        {"bug.fix/S": 2, "novel.thing/S": 3}, _cell_rows("bug.fix", "S", clean=40)
    )
    assert f.p_clean_mean == 1.0 and f.p_clean_stddev == 0.0 and f.single_rep_band
    assert "absence of spread" in fc.render_forecast(f)


def test_forecast_special_routes() -> None:
    rows = _cell_rows("bug.fix", "XL", clean=40) + _cell_rows(
        "bug.fix", "S", clean=40, oracle_strength=0.5
    )
    f = fc.forecast_build({"bug.fix/XL": 2, "bug.fix/S": 1}, rows)
    assert f.units_by_route[ROUTE_GRANULARIZE] == 2 and f.units_by_route[ROUTE_HUMAN] == 1
    assert f.deliver == 0


def test_forecast_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="negative"):
        fc.forecast_build({"bug.fix/S": -1}, [])


def test_render_forecast_smoke() -> None:
    f = fc.forecast_build({"bug.fix/S": 1, "missing.x/S": 1}, _cell_rows("bug.fix", "S"))
    txt = fc.render_forecast(f)
    assert "Build forecast" in txt and "missing.x/S" in txt and "Unmeasured" in txt
    assert "| `bug.fix/S` | 1 | **deliver** | 40 |" in txt


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------


def test_thresholds_are_frozen_and_never_relax_false_q1() -> None:
    t = fc.ReadinessThresholds()
    assert (t.min_coverage, t.min_reps, t.require_earned_tier, t.max_false_q1, t.min_buildable) == (
        0.90,
        5,
        True,
        0,
        0.80,
    )
    with pytest.raises(ValueError, match="always 0"):
        fc.ReadinessThresholds(max_false_q1=1)
    with pytest.raises(ValueError, match="within"):
        fc.ReadinessThresholds(min_coverage=1.5)
    with pytest.raises(AttributeError):
        t.min_reps = 1  # type: ignore[misc]
    assert t.to_dict()["version"] == "readiness.v1"


def test_readiness_reports_the_punch_list() -> None:
    # default bar on automated-pass data + an unmeasured class + a thin cell ⇒ NOT ready
    rows = _cell_rows("bug.fix", "S", clean=40) + _cell_rows("test.add", "S", n=3, clean=3)
    r = fc.assess_readiness({"bug.fix/S": 2, "test.add/S": 1, "novel.x/S": 3}, rows)
    assert not r.ok
    assert r.coverage == pytest.approx(3 / 6)
    assert r.measured == 3 and r.total == 6
    assert r.min_reps_seen == 3
    assert r.earned_units == 0 and r.buildable_units == 2
    assert r.false_q1_total == 0
    blob = " ".join(r.gaps)
    assert "coverage 50% < 90%" in blob and "novel.x/S" in blob
    assert "under 5 trials" in blob and "test.add/S (n=3)" in blob
    assert "not earned-trusted" in blob
    assert "buildable 67% < 80%" in blob and "1 calibrate" in blob
    assert "NOT READY" in fc.render_readiness(r)
    assert r.to_dict()["gaps"] == list(r.gaps)


def test_readiness_passes_when_bar_relaxed_and_go_with_signoff() -> None:
    rows = _cell_rows("bug.fix", "S", clean=40)
    t = fc.ReadinessThresholds(
        min_coverage=0.0, min_reps=1, require_earned_tier=False, min_buildable=0.80
    )
    r = fc.assess_readiness({"bug.fix/S": 3}, rows, thresholds=t)
    assert r.ok and not r.gaps
    assert r.coverage == 1.0 and r.buildable_frac == 1.0
    assert "GO" in fc.render_readiness(r)
    # the DEFAULT bar is met once a human signs the cell off
    strict = fc.assess_readiness({"bug.fix/S": 3}, rows)
    assert not strict.ok and any("earned" in g for g in strict.gaps)
    signed = fc.assess_readiness(
        {"bug.fix/S": 3},
        rows,
        signoffs=[so.SignoffRecord(repo="todo", capability_class="bug.fix", verifier="alice")],
        repo="todo",
    )
    assert signed.ok, signed.gaps
    assert signed.earned_units == 3


def test_readiness_false_q1_is_cardinal() -> None:
    bad = _row(cls="bug.fix", size="S")
    object.__setattr__(bad, "target_green", False)
    rows = [*_cell_rows("bug.fix", "S", clean=40), bad]
    r = fc.assess_readiness(
        {"bug.fix/S": 3},
        rows,
        thresholds=fc.ReadinessThresholds(
            min_coverage=0.0, min_reps=1, require_earned_tier=False, min_buildable=0.0
        ),
    )
    assert not r.ok
    assert r.false_q1_total == 1
    assert any("CARDINAL" in g and "false_q1=1" in g for g in r.gaps)
    # a sign-off cannot rescue it either
    r2 = fc.assess_readiness(
        {"bug.fix/S": 3},
        rows,
        signoffs=[so.SignoffRecord(repo="todo", capability_class="bug.fix", verifier="alice")],
        repo="todo",
    )
    assert not r2.ok and r2.earned_units == 0


def test_readiness_empty_mix_is_not_ready() -> None:
    r = fc.assess_readiness({}, [])
    assert not r.ok and r.total == 0 and r.coverage == 0.0
    assert any("coverage 0%" in g for g in r.gaps)
