"""crb.core.stats — Wilson intervals, mean/stddev, two-proportion z (known values).

Navigation
----------
What it is:   The statistics test suite — Wilson intervals, mean / stddev and the two-proportion
              z against known values.
What it does: Pins the essay's example (10/10 licenses only ≈ 0.722 at 95 %), 48/50, the
              degenerate 0/10 and 5/10 cases, that a smaller z narrows the interval, that
              impossible counts are refused, and the interval's properties over random counts.
How:          Known values to three decimals plus a small property loop; no fixtures.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/stats.py (under test), src/crb/core/routing.py (consumes the lower
              bound), docs/EVIDENCE-AND-CLAIMS.md (every number carries its method)
Tested by:    tests/test_stats.py
Touch when:   never for a new repository; an estimator is added (pin a textbook value, not the
              implementation's own output).
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crb.core.stats import Z_95, Interval, mean, stddev, two_proportion_z, wilson_interval


def test_wilson_no_data_is_the_whole_unit_interval() -> None:
    assert wilson_interval(0, 0) == Interval(0.0, 1.0)
    assert wilson_interval(0, -3) == Interval(0.0, 1.0)
    assert Interval(0.0, 1.0).width == 1.0


def test_wilson_10_of_10_lower_bound_is_0_722() -> None:
    """The essay's example: a perfect 10/10 only licenses ≈72% at 95%."""
    ci = wilson_interval(10, 10)
    assert ci.low == pytest.approx(0.7225, abs=0.0005)
    assert ci.high == pytest.approx(1.0)


def test_wilson_48_of_50() -> None:
    ci = wilson_interval(48, 50)
    assert ci.low == pytest.approx(0.8654, abs=0.0005)
    assert ci.high == pytest.approx(0.9890, abs=0.0005)


def test_wilson_0_of_10_and_5_of_10() -> None:
    ci = wilson_interval(0, 10)
    assert ci.low == 0.0 and ci.high == pytest.approx(0.2775, abs=0.0005)
    ci = wilson_interval(5, 10)
    assert ci.low == pytest.approx(0.2366, abs=0.0005)
    assert ci.high == pytest.approx(0.7634, abs=0.0005)
    assert ci.low + ci.high == pytest.approx(1.0)  # symmetric about 0.5


def test_wilson_custom_z_is_narrower_for_smaller_z() -> None:
    assert wilson_interval(8, 10, z=1.0).width < wilson_interval(8, 10).width
    assert pytest.approx(1.959964, abs=1e-6) == Z_95


def test_wilson_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
    with pytest.raises(ValueError):
        wilson_interval(-1, 10)


@settings(max_examples=200, database=None, deadline=None)
@given(st.integers(min_value=1, max_value=500), st.data())
def test_wilson_properties(n: int, data: st.DataObject) -> None:
    k = data.draw(st.integers(min_value=0, max_value=n))
    ci = wilson_interval(k, n)
    eps = 1e-12
    assert -eps <= ci.low <= k / n + eps
    assert k / n - eps <= ci.high <= 1.0 + eps
    if 0 < k < n:
        assert ci.low < k / n < ci.high
    bigger = wilson_interval(k * 2, n * 2)
    assert bigger.width <= ci.width + 1e-12  # more evidence never widens the interval


def test_mean_and_stddev() -> None:
    assert mean([]) == 0.0
    assert mean([2.0, 4.0]) == 3.0
    assert stddev([]) == 0.0 and stddev([5.0]) == 0.0
    assert stddev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.13809, abs=1e-5)


def test_two_proportion_z_known_values() -> None:
    z, p = two_proportion_z(20, 100, 40, 100)  # 20% → 40%
    assert z == pytest.approx(3.0861, abs=1e-3)
    assert p == pytest.approx(0.00101, abs=1e-4)
    z, p = two_proportion_z(40, 100, 20, 100)  # one-sided: the other direction is not "better"
    assert z == pytest.approx(-3.0861, abs=1e-3) and p > 0.99
    assert two_proportion_z(10, 20, 10, 20) == (0.0, 0.5)


def test_two_proportion_z_degenerate() -> None:
    assert two_proportion_z(0, 0, 5, 10) == (0.0, 1.0)
    assert two_proportion_z(5, 10, 0, 0) == (0.0, 1.0)
    assert two_proportion_z(10, 10, 10, 10) == (0.0, 1.0)  # pooled p = 1 → se = 0
    assert two_proportion_z(0, 10, 0, 10) == (0.0, 1.0)


def test_interval_is_frozen() -> None:
    ci = Interval(0.1, 0.2)
    with pytest.raises(AttributeError):
        ci.low = 0.5  # type: ignore[misc]
    assert math.isclose(ci.width, 0.1)
