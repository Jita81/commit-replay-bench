"""The economics of a cell — cost and latency with their denominators, intervals and apparatus.

A mean cost with no ``n`` and no interval is a rumour, and one that quietly drops a known
``$0`` (a fixture, a metered subscription) is a wrong rumour. This module folds one group of
ledger rows into :class:`Economics`: for each axis, how many attempts (and how many clean
attempts) carry a KNOWN value, the mean over exactly those rows, and a 95 % interval with
the method named — or no interval, and the reason, when there are fewer than two known rows.

Rules
-----
* **Known is a row fact.** Cost is known when :attr:`crb.core.ledger.GradeRow.cost_known`
  says so — a known ``$0`` counts as ``$0`` and enters the mean; an unknown cost is left out
  of both the mean and its ``n``, never read as ``$0``. Latency is known when the row
  recorded a positive wall clock (``latency_s > 0``): no real attempt takes no time, so a
  ``0`` is "not recorded", never "instant".
* **Two known rows or no interval.** The per-attempt means carry a Student-t 95 % interval
  on the known rows (``n - 1`` degrees of freedom, :func:`crb.core.stats.t_975`). Cost per
  clean attempt is a ratio (total known cost ÷ known clean attempts); its interval is the
  delta-method (linearised ratio-estimator) t interval over the same known rows. A lower
  bound below zero is floored at ``0`` — a cost or a duration cannot be negative — and the
  method string says so. One known row serves its value and no interval; none serves no
  value. Each says why.
* **Never pooled across apparatus.** Rows from more than one ``apparatus_version`` are
  refused: every estimate is withheld with the versions named, as the rest of the map
  refuses to blend apparatus (docs/EVIDENCE-AND-CLAIMS.md §4). Read one apparatus instead.

Navigation
----------
What it is:   The cost and latency fold for one cell (or one repository's rows): known
              counts as denominators, means, t intervals with the method named, apparatus.
What it does: ``fold_economics(rows)`` → :class:`Economics` with ``cost_per_attempt``,
              ``cost_per_clean`` and ``latency_per_attempt`` as :class:`Estimate` (n, value,
              ci_low, ci_high, method, reason); refuses a pooled apparatus; never reads an
              unknown as zero.
How:          Eligible rows only (the cell's ``n``); ``GradeRow.cost_known`` and
              ``latency_s > 0`` pick the known rows; ``t_975`` gives the critical value.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md (economics never route — this is a report)
Works with:   src/crb/core/ledger.py (``GradeRow.cost_known``, ``GradeRow.eligible``),
              src/crb/core/stats.py (``t_975``, ``mean``, ``stddev``),
              src/crb/core/capability.py (attaches an ``Economics`` to every measured cell),
              src/crb/server/routes/capability.py (serves it per cell and for the map),
              src/crb/server/schemas_capability.py (``EconomicsOut``),
              ui/src/lib/economics.ts (turns it into the tiles' value, n, interval, apparatus)
Tested by:    tests/test_economics.py, tests/test_server_routes_capability.py
Touch when:   never for a new repository; changing the interval method changes every
              economics interval the product shows — name the new method in
              docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method in the same change.
Claims:       An economics figure is a mean over the attempts that recorded it, with its
              interval and n; it is never a cost per accepted change
              (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from crb.core.ledger import GradeRow
from crb.core.stats import mean, stddev, t_975

#: The interval on a per-attempt mean.
METHOD_T_MEAN = "Student-t 95% on the known rows (n-1 df), lower bound floored at 0"
#: The interval on cost per clean attempt (a ratio of two means over the same rows).
METHOD_T_RATIO = (
    "delta-method (ratio estimator) Student-t 95% on the known rows (n-1 df), "
    "lower bound floored at 0"
)

REASON_POOLED = (
    "rows from {k} apparatus versions ({versions}) — economics are never pooled across "
    "apparatus versions; read one apparatus"
)
REASON_NONE_KNOWN = "no attempt recorded a known {axis}"
REASON_ONE_KNOWN = "one attempt with a known {axis} — an interval needs at least two"
REASON_NO_CLEAN = "no clean attempt with a known cost"


@dataclass(frozen=True)
class Estimate:
    """One economics figure. ``n`` is its denominator (known attempts, or known clean
    attempts for cost per clean attempt). ``value`` is ``None`` when nothing is known;
    ``ci_low`` / ``ci_high`` are ``None`` whenever no interval is served, and ``reason``
    then says why (it is ``""`` only when the value AND its interval are served)."""

    n: int
    value: float | None
    ci_low: float | None
    ci_high: float | None
    method: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "value": None if self.value is None else round(self.value, 6),
            "ci_low": None if self.ci_low is None else round(self.ci_low, 6),
            "ci_high": None if self.ci_high is None else round(self.ci_high, 6),
            "method": self.method,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Economics:
    """The economics of one group of rows. ``n_attempts`` / ``n_clean`` are the eligible
    rows (the cell's ``n`` and ``clean``); the ``*_known`` counts are the denominators
    behind each axis; ``pooled`` is ``True`` when the rows span more than one apparatus
    version, in which case every estimate is withheld."""

    n_attempts: int
    n_clean: int
    cost_known: int
    cost_known_clean: int
    latency_known: int
    latency_known_clean: int
    apparatus_versions: tuple[str, ...]
    pooled: bool
    cost_per_attempt: Estimate
    cost_per_clean: Estimate
    latency_per_attempt: Estimate

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_attempts": self.n_attempts,
            "n_clean": self.n_clean,
            "cost_known": self.cost_known,
            "cost_known_clean": self.cost_known_clean,
            "latency_known": self.latency_known,
            "latency_known_clean": self.latency_known_clean,
            "apparatus_versions": list(self.apparatus_versions),
            "pooled": self.pooled,
            "cost_per_attempt": self.cost_per_attempt.to_dict(),
            "cost_per_clean": self.cost_per_clean.to_dict(),
            "latency_per_attempt": self.latency_per_attempt.to_dict(),
        }


def latency_known(row: GradeRow) -> bool:
    """A row's latency is known when it recorded a positive wall clock."""
    return row.latency_s > 0


def _floor(x: float) -> float:
    return max(0.0, x)


def mean_estimate(values: list[float], axis: str) -> Estimate:
    """The mean of ``values`` (the known rows of one axis) with its t interval."""
    n = len(values)
    if n == 0:
        return Estimate(0, None, None, None, METHOD_T_MEAN, REASON_NONE_KNOWN.format(axis=axis))
    m = mean(values)
    if n == 1:
        return Estimate(1, m, None, None, METHOD_T_MEAN, REASON_ONE_KNOWN.format(axis=axis))
    half = t_975(n - 1) * stddev(values) / math.sqrt(n)
    return Estimate(n, m, _floor(m - half), m + half, METHOD_T_MEAN, "")


def ratio_estimate(costs: list[float], clean: list[bool]) -> Estimate:
    """Cost per clean attempt over the known-cost rows: ``R = Σcost / Σclean``.

    Linearised (delta-method) variance of the ratio of means ``ȳ / x̄``: with residuals
    ``dᵢ = yᵢ − R·xᵢ``, ``SE(R) = s_d / (x̄ · √n)``; the interval is ``R ± t(n−1)·SE``."""
    n = len(costs)
    k = sum(1 for c in clean if c)
    if n == 0:
        return Estimate(0, None, None, None, METHOD_T_RATIO, REASON_NONE_KNOWN.format(axis="cost"))
    if k == 0:
        return Estimate(0, None, None, None, METHOD_T_RATIO, REASON_NO_CLEAN)
    r = sum(costs) / k
    if n == 1:
        return Estimate(k, r, None, None, METHOD_T_RATIO, REASON_ONE_KNOWN.format(axis="cost"))
    x_bar = k / n
    resid = [y - r * (1.0 if x else 0.0) for y, x in zip(costs, clean, strict=True)]
    half = t_975(n - 1) * stddev(resid) / (x_bar * math.sqrt(n))
    return Estimate(k, r, _floor(r - half), r + half, METHOD_T_RATIO, "")


def _withheld(n: int, method: str, reason: str) -> Estimate:
    return Estimate(n, None, None, None, method, reason)


def fold_economics(rows: Iterable[GradeRow]) -> Economics:
    """Reduce rows (one cell, or one repository's filtered rows) to :class:`Economics`.

    Only eligible rows count (the cell's ``n``). Pure: the same rows give the same
    numbers in the API, the CLI and a test."""
    rs = list(rows)
    eligible = [r for r in rs if r.eligible]
    versions = tuple(sorted({r.apparatus_version for r in rs}))
    cost_rows = [r for r in eligible if r.cost_known]
    lat_rows = [r for r in eligible if latency_known(r)]
    counts = {
        "n_attempts": len(eligible),
        "n_clean": sum(1 for r in eligible if r.clean),
        "cost_known": len(cost_rows),
        "cost_known_clean": sum(1 for r in cost_rows if r.clean),
        "latency_known": len(lat_rows),
        "latency_known_clean": sum(1 for r in lat_rows if r.clean),
    }
    if len(versions) > 1:
        reason = REASON_POOLED.format(k=len(versions), versions=", ".join(versions))
        return Economics(
            **counts,
            apparatus_versions=versions,
            pooled=True,
            cost_per_attempt=_withheld(counts["cost_known"], METHOD_T_MEAN, reason),
            cost_per_clean=_withheld(counts["cost_known_clean"], METHOD_T_RATIO, reason),
            latency_per_attempt=_withheld(counts["latency_known"], METHOD_T_MEAN, reason),
        )
    return Economics(
        **counts,
        apparatus_versions=versions,
        pooled=False,
        cost_per_attempt=mean_estimate([r.cost_usd for r in cost_rows], "cost"),
        cost_per_clean=ratio_estimate(
            [r.cost_usd for r in cost_rows], [r.clean for r in cost_rows]
        ),
        latency_per_attempt=mean_estimate([r.latency_s for r in lat_rows], "latency"),
    )


__all__ = [
    "METHOD_T_MEAN",
    "METHOD_T_RATIO",
    "Economics",
    "Estimate",
    "fold_economics",
    "latency_known",
    "mean_estimate",
    "ratio_estimate",
]
