"""Dependency-free statistics: Wilson intervals and friends.

Navigation
----------
What it is:   The statistics every number in the product is reported with — the Wilson
              95% interval, mean, sample standard deviation and a two-proportion z-test.
What it does: Gives each rate the interval the routing rule keys on (``ci_low``) without a
              third-party dependency; an empty sample yields ``[0, 1]``, never a point.
How:          Closed-form Wilson score with ``Z_95``; ``stddev`` is the n-1 sample form;
              ``two_proportion_z`` pools the proportions and uses ``erf`` for the p-value.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/ledger.py (``CellStats.ci`` and the failure split's intervals),
              src/crb/core/routing.py (``min_ci_low`` is the Wilson lower bound),
              src/crb/core/learn.py (``rows_to_clear_bar`` searches the interval),
              src/crb/core/federated.py (the interval recomputed on pooled counts),
              src/crb/core/capability.py (σ of the clean indicator, advisory)
Tested by:    tests/test_stats.py, tests/test_ledger.py
Touch when:   never for a new repository; changing the interval method or ``Z_95`` changes
              every ``ci_low`` and therefore every route — an ADR and an apparatus bump
              (src/crb/core/version.py), and docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method
              must name the new method.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Z_95 = 1.959963984540054  # inverse standard normal at 0.975


@dataclass(frozen=True)
class Interval:
    """A closed ``[low, high]`` confidence interval on a proportion."""

    low: float
    high: float

    @property
    def width(self) -> float:
        return self.high - self.low


def wilson_interval(successes: int, n: int, z: float = Z_95) -> Interval:
    """Wilson score interval for a binomial proportion. ``n<=0`` → [0, 1]."""
    if n <= 0:
        return Interval(0.0, 1.0)
    if successes < 0 or successes > n:
        raise ValueError("successes must be within [0, n]")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return Interval(max(0.0, centre - margin), min(1.0, centre + margin))


def mean(xs: Sequence[float]) -> float:
    """Arithmetic mean; ``0.0`` for an empty sample (callers report the n beside it)."""
    return sum(xs) / len(xs) if xs else 0.0


def stddev(xs: Sequence[float]) -> float:
    """Sample standard deviation (n-1); 0 for n<2."""
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def two_proportion_z(k_a: int, n_a: int, k_b: int, n_b: int) -> tuple[float, float]:
    """One-sided (H1: p_b > p_a) two-proportion z-test → (z, p)."""
    if n_a <= 0 or n_b <= 0:
        return 0.0, 1.0
    p_a, p_b = k_a / n_a, k_b / n_b
    pooled = (k_a + k_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if se == 0:
        return 0.0, 1.0
    z = (p_b - p_a) / se
    return z, 1.0 - _phi(z)


def _phi(x: float) -> float:
    """The standard normal CDF, via ``erf`` (no scipy in the core)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
