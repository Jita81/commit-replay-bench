"""Dependency-free statistics: Wilson intervals and friends."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Z_95 = 1.959963984540054  # inverse standard normal at 0.975


@dataclass(frozen=True)
class Interval:
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
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
