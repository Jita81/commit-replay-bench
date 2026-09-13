"""The ONE routing rule (ADR-0003).

Given a cell's measured statistics and, when measured, the oracle strength of
its tasks, decide what the factory may do with that class of change:

* ``deliver``      — auto-deliver as a branch + PR: n ≥ 10 ∧ point ≥ 0.90 ∧
  Wilson-lower ≥ 0.80 ∧ false-Q1 = 0 ∧ (oracle strength ≥ 0.80 when measured).
* ``do_not_ship``  — any false-Q1 in the cell: the evidence is untrusted until
  audited. (Structurally impossible with the write-time invariant; kept as the
  read-time re-check.)
* ``human``        — the oracle is too weak to license auto-delivery
  (strength < 0.80 when measured) even if the numbers look green.
* ``granularize``  — XL changes are split before they are attempted.
* ``calibrate``    — not enough evidence, or the point/interval is below the bar.

The rule is deliberately the *published* one (the essay's "≥90% point and ≥80%
lower bound on enough samples"). The SPC variant (σ ≤ 0.10, n ≥ 20) that also
existed upstream is reported as an advisory signal, not a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crb.core.ledger import CellStats

POLICY_VERSION = "routing.v1"

ROUTE_DELIVER = "deliver"
ROUTE_CALIBRATE = "calibrate"
ROUTE_GRANULARIZE = "granularize"
ROUTE_HUMAN = "human"
ROUTE_DO_NOT_SHIP = "do_not_ship"
ROUTES: tuple[str, ...] = (
    ROUTE_DELIVER,
    ROUTE_CALIBRATE,
    ROUTE_GRANULARIZE,
    ROUTE_HUMAN,
    ROUTE_DO_NOT_SHIP,
)


@dataclass(frozen=True)
class RoutingPolicy:
    min_n: int = 10
    min_point: float = 0.90
    min_ci_low: float = 0.80
    min_oracle_strength: float = 0.80
    granularize_sizes: tuple[str, ...] = ("XL",)
    version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_n": self.min_n,
            "min_point": self.min_point,
            "min_ci_low": self.min_ci_low,
            "min_oracle_strength": self.min_oracle_strength,
            "granularize_sizes": list(self.granularize_sizes),
            "version": self.version,
        }


DEFAULT_POLICY = RoutingPolicy()


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    cell: dict[str, str]
    n: int
    point: float
    ci_low: float
    false_q1: int
    oracle_strength: float | None
    policy_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "reason": self.reason,
            "cell": dict(self.cell),
            "n": self.n,
            "point": round(self.point, 4),
            "ci_low": round(self.ci_low, 4),
            "false_q1": self.false_q1,
            "oracle_strength": None
            if self.oracle_strength is None
            else round(self.oracle_strength, 4),
            "policy_version": self.policy_version,
        }


def route(
    stats: CellStats,
    *,
    oracle_strength: float | None = None,
    policy: RoutingPolicy = DEFAULT_POLICY,
) -> RouteDecision:
    strength = oracle_strength if oracle_strength is not None else stats.oracle_strength_mean
    base: dict[str, Any] = {
        "cell": stats.cell.to_dict(),
        "n": stats.n,
        "point": stats.point,
        "ci_low": stats.ci.low,
        "false_q1": stats.false_q1,
        "oracle_strength": strength,
        "policy_version": policy.version,
    }
    if stats.false_q1 > 0:
        return RouteDecision(
            ROUTE_DO_NOT_SHIP,
            f"{stats.false_q1} false-Q1 row(s) in cell — evidence untrusted",
            **base,
        )
    if stats.cell.size in policy.granularize_sizes:
        return RouteDecision(
            ROUTE_GRANULARIZE, f"size {stats.cell.size} is split before attempting", **base
        )
    if stats.n < policy.min_n:
        return RouteDecision(ROUTE_CALIBRATE, f"n={stats.n} < {policy.min_n}", **base)
    if strength is not None and strength < policy.min_oracle_strength:
        return RouteDecision(
            ROUTE_HUMAN,
            f"oracle strength {strength:.2f} < {policy.min_oracle_strength:.2f} — green cannot license auto-delivery",
            **base,
        )
    if stats.point < policy.min_point:
        return RouteDecision(
            ROUTE_CALIBRATE, f"point {stats.point:.3f} < {policy.min_point:.2f}", **base
        )
    if stats.ci.low < policy.min_ci_low:
        return RouteDecision(
            ROUTE_CALIBRATE,
            f"Wilson lower {stats.ci.low:.3f} < {policy.min_ci_low:.2f} (point ok, interval too wide)",
            **base,
        )
    return RouteDecision(
        ROUTE_DELIVER,
        f"n={stats.n} point={stats.point:.3f} ci_low={stats.ci.low:.3f} false_q1=0"
        + ("" if strength is None else f" oracle={strength:.2f}"),
        **base,
    )
