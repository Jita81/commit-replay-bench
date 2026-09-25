"""Dependency-free statistics: Wilson intervals and friends.

Navigation
----------
What it is:   The statistics every number in the product is reported with — the Wilson
              95% interval, mean, sample standard deviation, a two-proportion z-test and the
              Student-t critical value the economics intervals use.
What it does: Gives each rate the interval the routing rule keys on (``ci_low``) without a
              third-party dependency; an empty sample yields ``[0, 1]``, never a point.
How:          Closed-form Wilson score with ``Z_95``; ``stddev`` is the n-1 sample form;
              ``two_proportion_z`` pools the proportions and uses ``erf`` for the p-value;
              ``t_975`` is a table to 30 df and a Cornish-Fisher expansion above.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/ledger.py (``CellStats.ci`` and the failure split's intervals),
              src/crb/core/routing.py (``min_ci_low`` is the Wilson lower bound),
              src/crb/core/learn.py (``rows_to_clear_bar`` searches the interval),
              src/crb/core/federated.py (the interval recomputed on pooled counts),
              src/crb/core/capability.py (σ of the clean indicator, advisory),
              src/crb/core/economics.py (``t_975`` for the cost and latency intervals)
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


#: Student's t at 0.975 for 1–30 degrees of freedom (to 9 places). Above 30 the
#: Cornish-Fisher expansion in :func:`t_975` is accurate to better than 1e-5.
_T_975: tuple[float, ...] = (
    12.706204736,
    4.302652730,
    3.182446305,
    2.776445105,
    2.570581836,
    2.446911851,
    2.364624252,
    2.306004135,
    2.262157163,
    2.228138852,
    2.200985160,
    2.178812830,
    2.160368656,
    2.144786688,
    2.131449546,
    2.119905299,
    2.109815578,
    2.100922040,
    2.093024054,
    2.085963447,
    2.079613845,
    2.073873068,
    2.068657610,
    2.063898562,
    2.059538553,
    2.055529439,
    2.051830516,
    2.048407142,
    2.045229642,
    2.042272456,
)


def t_975(df: int) -> float:
    """The two-sided 95 % Student-t critical value for ``df`` degrees of freedom.

    A table for ``df`` <= 30; above that the Cornish-Fisher expansion of the t quantile
    about the normal one (three terms). ``df`` < 1 has no t distribution → ``ValueError``.
    """
    if df < 1:
        raise ValueError("a t interval needs at least one degree of freedom (n >= 2)")
    if df <= len(_T_975):
        return _T_975[df - 1]
    z = Z_95
    g1 = (z**3 + z) / 4
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384
    return z + g1 / df + g2 / df**2 + g3 / df**3
