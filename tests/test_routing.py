"""crb.core.routing — every branch of the ONE published routing rule."""

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
    strict = rt.RoutingPolicy(granularize_sizes=("L", "XL"))
    assert rt.route(stats(50, 50, size="L"), policy=strict).route == rt.ROUTE_GRANULARIZE
    assert lenient.to_dict() == {
        "min_n": 5,
        "min_point": 0.8,
        "min_ci_low": 0.5,
        "min_oracle_strength": 0.3,
        "granularize_sizes": [],
        "version": "routing.test",
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
