"""crb.core.economics — cost and latency with their denominators, intervals and apparatus (F35).

Navigation
----------
What it is:   The economics fold's test suite — the arithmetic on hand-built rows.
What it does: Pins that a known $0 is $0 and enters the mean, that an unknown cost is never
              read as $0, that all-unknown serves no value, one known row serves a value and
              no interval (with the reason), that the t interval and the delta-method ratio
              interval match hand-computed values, that a lower bound is floored at 0, that
              rows from more than one apparatus version, posture class (ADR-0019) or checks
              arm (ADR-0024) are refused, and that a measured cell and the served
              ``cost_usd_mean`` agree with the fold. Then P-131 across its class: the
              abstract export, the re-measure price and the forecast keep a known $0, and a
              ratchet fails when any reader in ``src/crb`` or ``ui/src`` decides a cost is
              unknown by comparing it with zero.
How:          Hand-built ``GradeRow`` lists (``posture_row``: a current-apparatus row carries
              its posture labels); expected numbers computed by hand in the test
              (textbook t values), never by calling the module's own helpers.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/economics.py (under test), src/crb/core/ledger.py (``GradeRow``,
              ``cost_known``, ``CellStats.n_cost_known``), src/crb/core/capability.py
              (``measure_cell`` attaches the fold), src/crb/core/stats.py (``t_975``),
              src/crb/core/federated.py (the abstract export keeps a known $0),
              src/crb/core/learn.py (the re-measure price keeps it),
              src/crb/core/forecast.py (the forecast prices it)
Tested by:    tests/test_economics.py
Touch when:   never for a new repository; the interval method changes (pin the new method's textbook
              value here first), or a new reader of a cost needs a place in ``_COST_ZERO_ALLOWED``
              (say why there).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from crb.core import capability as cap
from crb.core import economics as ec
from crb.core.checks import LABEL_CHECKS
from crb.core.ledger import LABEL_COST_KNOWN, GradeRow
from crb.core.version import APPARATUS_VERSION
from fixtures.posture import TEST_POSTURE_CLASS, posture_row

PACK = "a" * 64


def row(*, clean: bool = True, cost: float = 0.0, latency: float = 0.0, **kw: Any) -> GradeRow:
    base: dict[str, Any] = {
        "repo": "r",
        "task_id": "f" * 40,
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean,
        "no_new_failures": True,
        "source_changed": True,
        "capability_class": "bug.fix",
        "size": "S",
        "builder": "editblock",
        "model": "m",
        "provider": "p",
        "cost_usd": cost,
        "latency_s": latency,
        "evidence_pack_hash": PACK if clean else "",
        "gold_clean": True,
    }
    base.update(kw)
    return posture_row(**base)


def unknown_cost(**kw: Any) -> GradeRow:
    """A row whose cost nobody measured: imported, it names a builder but never reported."""
    return row(provenance="imported:census", **kw)


def test_a_known_zero_is_zero_and_enters_the_mean() -> None:
    e = ec.fold_economics([row(cost=0.0), row(cost=0.0), row(cost=0.30)])
    assert e.cost_known == 3 and e.cost_known_clean == 3
    assert e.cost_per_attempt.value == pytest.approx(0.10)
    assert e.cost_per_attempt.n == 3
    # sd of (0, 0, 0.3) = 0.17320508; t(2) = 4.302652730
    half = 4.302652730 * 0.17320508 / math.sqrt(3)
    assert e.cost_per_attempt.ci_high == pytest.approx(0.10 + half, abs=1e-6)
    assert e.cost_per_attempt.ci_low == 0.0  # 0.1 - 0.43 floored: a cost is never negative
    assert e.cost_per_attempt.reason == ""
    assert "floored at 0" in e.cost_per_attempt.method


def test_all_zero_known_cost_is_a_known_zero_with_a_zero_width_interval() -> None:
    e = ec.fold_economics([row(cost=0.0) for _ in range(4)])
    est = e.cost_per_attempt
    assert (est.n, est.value, est.ci_low, est.ci_high, est.reason) == (4, 0.0, 0.0, 0.0, "")


def test_all_unknown_serves_no_value_and_says_why() -> None:
    e = ec.fold_economics([unknown_cost(), unknown_cost(clean=False)])
    assert e.n_attempts == 2 and e.cost_known == 0 and e.cost_known_clean == 0
    for est in (e.cost_per_attempt, e.cost_per_clean):
        assert est.n == 0 and est.value is None and est.ci_low is None and est.ci_high is None
        assert est.reason == "no attempt recorded a known cost"
    lat = e.latency_per_attempt
    assert lat.value is None and lat.reason == "no attempt recorded a known latency"


def test_an_unknown_cost_is_left_out_never_read_as_zero() -> None:
    rs = [
        row(cost=0.20),
        row(cost=0.40),
        unknown_cost(),
        row(cost=9.0, labels={LABEL_COST_KNOWN: "false"}),
    ]
    e = ec.fold_economics(rs)
    assert e.n_attempts == 4 and e.cost_known == 2
    assert e.cost_per_attempt.value == pytest.approx(0.30)  # not 0.15, not 2.4


def test_one_known_row_serves_the_value_and_no_interval() -> None:
    e = ec.fold_economics([row(cost=0.25, latency=12.0), unknown_cost(clean=False)])
    est = e.cost_per_attempt
    assert est.n == 1 and est.value == pytest.approx(0.25)
    assert est.ci_low is None and est.ci_high is None
    assert est.reason == "one attempt with a known cost — an interval needs at least two"
    assert e.cost_per_clean.value == pytest.approx(0.25) and e.cost_per_clean.ci_low is None
    lat = e.latency_per_attempt
    assert lat.n == 1 and lat.value == 12.0 and lat.ci_low is None
    assert lat.reason == "one attempt with a known latency — an interval needs at least two"


def test_latency_t_interval_by_hand() -> None:
    # 10, 20, 30, 40 s: mean 25, sd 12.9099445, t(3) = 3.182446305
    e = ec.fold_economics([row(latency=x) for x in (10.0, 20.0, 30.0, 40.0)] + [row(latency=0.0)])
    lat = e.latency_per_attempt
    half = 3.182446305 * 12.9099445 / 2.0
    assert lat.n == 4 and e.latency_known == 4 and e.latency_known_clean == 4
    assert lat.value == pytest.approx(25.0)
    assert lat.ci_low == pytest.approx(25.0 - half, abs=1e-5)
    assert lat.ci_high == pytest.approx(25.0 + half, abs=1e-5)
    assert lat.method == ec.METHOD_T_MEAN


def test_cost_per_clean_is_total_known_cost_over_known_clean_with_a_delta_interval() -> None:
    # 4 known rows, 2 clean: y = (0.1, 0.1, 0.2, 0.2), x = (1, 1, 0, 0) → R = 0.6 / 2 = 0.3
    rs = [row(cost=0.1), row(cost=0.1), row(cost=0.2, clean=False), row(cost=0.2, clean=False)]
    e = ec.fold_economics(rs)
    est = e.cost_per_clean
    assert est.n == 2 and est.value == pytest.approx(0.30)
    # residuals d = y - R x = (-0.2, -0.2, 0.2, 0.2): sd = 0.23094011; x̄ = 0.5; t(3)
    half = 3.182446305 * 0.23094011 / (0.5 * 2.0)
    assert est.ci_high == pytest.approx(0.30 + half, abs=1e-6)
    assert est.ci_low == 0.0  # 0.3 - 0.735 floored
    assert est.method == ec.METHOD_T_RATIO


def test_no_clean_attempt_with_a_known_cost_serves_no_cost_per_clean() -> None:
    e = ec.fold_economics(
        [
            row(cost=0.1, clean=False),
            row(cost=0.2, clean=False),
            row(clean=True, provenance="imported:x"),
        ]
    )
    assert e.n_clean == 1 and e.cost_known_clean == 0
    assert (
        e.cost_per_clean.value is None
        and e.cost_per_clean.reason == "no clean attempt with a known cost"
    )
    assert e.cost_per_attempt.value == pytest.approx(0.15)


def test_mixed_apparatus_is_refused_never_pooled() -> None:
    rs = [
        row(cost=0.1, latency=5.0),
        row(cost=0.3, latency=7.0, apparatus_version="2.1", belt_set="v4"),
    ]
    e = ec.fold_economics(rs)
    assert e.pooled is True and e.apparatus_versions == ("2.1", APPARATUS_VERSION)
    # the counts stay (they are counts), every estimate is withheld with the versions named
    assert e.cost_known == 2 and e.latency_known == 2
    for est in (e.cost_per_attempt, e.cost_per_clean, e.latency_per_attempt):
        assert est.value is None and est.ci_low is None and est.ci_high is None
        assert "2 apparatus versions (2.1, " in est.reason and "never pooled" in est.reason


def test_mixed_posture_classes_are_refused_never_pooled() -> None:
    # ADR-0019 §8: a host-measured attempt and a sealed one are different measurements;
    # the map's posture=all pools their RATES only over invariant tasks, and a cost or a
    # wall clock is never invariant across postures — so economics refuse the blend
    sealed = "docker/copy/sealed"
    rs = [
        row(cost=0.1, latency=5.0),
        row(cost=0.3, latency=90.0, labels={"posture_class": sealed}),
    ]
    e = ec.fold_economics(rs)
    assert e.pooled is True and e.posture_classes == (sealed, TEST_POSTURE_CLASS)
    assert e.cost_known == 2 and e.latency_known == 2
    for est in (e.cost_per_attempt, e.cost_per_clean, e.latency_per_attempt):
        assert est.value is None and est.ci_low is None and est.ci_high is None
        assert f"2 posture classes ({sealed}, {TEST_POSTURE_CLASS})" in est.reason
        assert "never pooled" in est.reason
    assert e.pooled_reason == e.cost_per_attempt.reason
    # one class alone is not pooled: the same rows split by class each serve a value
    one = ec.fold_economics([r for r in rs if r.posture_class == sealed] * 2)
    assert one.pooled is False and one.cost_per_attempt.value == pytest.approx(0.3)


def test_mixed_checks_arms_are_refused_never_pooled() -> None:
    # ADR-0024: a row graded with the format step on is a different measurement (the step
    # itself costs time) from one graded without
    rs = [row(latency=5.0), row(latency=8.0, labels={LABEL_CHECKS: "fmt=1"})]
    assert {r.checks_arm for r in rs} == {"off", "fmt"}
    e = ec.fold_economics(rs)
    assert e.pooled is True and e.checks_arms == ("off", "fmt")
    assert e.latency_per_attempt.value is None
    assert "2 checks arms (off, fmt)" in e.latency_per_attempt.reason


def test_an_unpooled_fold_names_its_one_class_and_arm() -> None:
    e = ec.fold_economics([row(cost=0.1), row(cost=0.2)])
    assert e.pooled is False and e.pooled_reason == ""
    assert e.posture_classes == (TEST_POSTURE_CLASS,) and e.checks_arms == ("off",)
    d = e.to_dict()
    assert d["posture_classes"] == [TEST_POSTURE_CLASS] and d["checks_arms"] == ["off"]
    assert d["pooled_reason"] == ""


def test_disqualified_rows_are_outside_every_denominator() -> None:
    rs = [
        row(cost=0.1),
        row(cost=0.1),
        row(cost=5.0, clean=False, disqualified=True, dq_reason="tamper"),
    ]
    e = ec.fold_economics(rs)
    assert (
        e.n_attempts == 2 and e.cost_known == 2 and e.cost_per_attempt.value == pytest.approx(0.1)
    )


def test_to_dict_rounds_and_keeps_nulls() -> None:
    d = ec.fold_economics([unknown_cost()]).to_dict()
    assert d["pooled"] is False and d["apparatus_versions"] == [APPARATUS_VERSION]
    assert d["cost_per_attempt"] == {
        "n": 0,
        "value": None,
        "ci_low": None,
        "ci_high": None,
        "method": ec.METHOD_T_MEAN,
        "reason": "no attempt recorded a known cost",
    }


def test_a_measured_cell_carries_the_fold_and_agrees_with_its_mean() -> None:
    rs = [row(cost=0.0, latency=3.0), row(cost=0.2, latency=5.0), unknown_cost(latency=4.0)]
    c = cap.measure_cell(rs, cap.PROJECTION_CLASS_SIZE)
    assert c.economics is not None and c.economics == ec.fold_economics(rs)
    # the flat mean the API has always served agrees with the fold: a known $0 counts
    assert c.stats is not None and c.stats.cost_usd_mean == pytest.approx(0.1)
    assert c.economics.cost_per_attempt.value == pytest.approx(c.stats.cost_usd_mean)
    assert c.cost_known is True and c.latency_known is True
    assert c.to_dict()["economics"]["cost_known"] == 2
    assert cap.empty_cell(c.key, cap.PROJECTION_CLASS_SIZE).economics is None


# --- every other reader of the same rows keeps a known $0 (P-131: the class, not one fold) ---


def test_the_abstract_export_keeps_a_known_zero_cost() -> None:
    from crb.core.federated import to_abstract_cell
    from crb.core.ledger import cell_stats

    rs = [row(cost=0.0, latency=3.0), row(cost=0.0, latency=4.0)]
    assert all(r.cost_known for r in rs)
    cell = to_abstract_cell(cell_stats(rs))
    # a cell whose known costs are all $0 leaves the tenant as $0, never as "unknown"
    assert cell.cost_usd_mean == 0.0
    assert to_abstract_cell(cell_stats([unknown_cost(latency=3.0)])).cost_usd_mean is None


def test_the_remeasure_price_keeps_a_known_zero_cost() -> None:
    from crb.core import learn

    stale = [
        row(cost=0.0, latency=6.0, task_id=f"{i:040x}", apparatus_version="2.2") for i in range(4)
    ]
    plan = learn.remeasure_plan(stale, current_apparatus=APPARATUS_VERSION)
    assert len(plan.cells) == 1
    c = plan.cells[0]
    # the price of re-measuring is a known $0, never "?"
    assert c.cost_known is True and c.cost_usd_mean == 0.0 and c.est_cost_usd == 0.0


def test_the_forecast_prices_a_known_zero_cost() -> None:
    from crb.core.forecast import forecast_build

    rs = [row(cost=0.0, latency=6.0, task_id=f"{i:040x}") for i in range(3)]
    f = forecast_build({"bug.fix/S": 2}, rs)
    assert f.costed_components == 2
    assert f.per_component[0].unit_cost_usd == 0.0


#: The only places a cost may be compared with zero: each is a rule about known-ness or a
#: running total, never a filter that decides which costs a mean reads.
_COST_ZERO_ALLOWED = {
    # derive_cost_known: the rule that DECIDES known-ness (a positive cost is known)
    ("src/crb/core/ledger.py", "if cost_usd > 0 or tokens_in > 0 or tokens_out > 0:"),
    # the Factory's run banner: a run's running total, shown only once it has spent
    (
        "ui/src/screens/Factory/FactoryPage.tsx",
        "{run.cost_usd > 0 ? ` ${usd(run.cost_usd)} so far.` : ''}",
    ),
}


def test_no_reader_decides_a_cost_is_unknown_by_comparing_it_with_zero() -> None:
    """P-131 as a gate: known-ness is ``GradeRow.cost_known`` (or the served fold's counts).
    A ``cost_usd > 0`` / ``cost_usd_mean > 0`` filter drops a known $0 as if unknown — the
    class found in the map, the abstract export, the re-measure price, the forecast and
    the Measure and Factory estimates. A new one fails here."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"\bcost_usd(?:_mean)?\s*(?:>|!=)\s*0\b")
    found: set[tuple[str, str]] = set()
    files = [*root.joinpath("src", "crb").rglob("*.py")]
    ui = root.joinpath("ui", "src")
    if ui.is_dir():
        files += [p for p in ui.rglob("*.ts*") if ".test." not in p.name]
    for p in files:
        for line in p.read_text(encoding="utf-8").splitlines():
            if pattern.search(line):
                found.add((p.relative_to(root).as_posix(), line.strip()))
    assert found - _COST_ZERO_ALLOWED == set()
