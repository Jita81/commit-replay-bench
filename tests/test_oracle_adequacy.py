"""Hermetic tests for the oracle-adequacy gate (``crb.core.oracle.adequacy``).

Locks the routing consequence: a CLEAN grade auto-ships only on a strong oracle; a
weak/unscoreable oracle routes a real pass to human review; false-Q1 = 0 is
orthogonal; and the adequacy floor is the SAME number as the routing policy's
``min_oracle_strength`` (the two gates cannot drift apart silently).

Navigation
----------
What it is:   The oracle-adequacy gate's test suite (``crb.core.oracle.adequacy``).
What it does: Pins the strength bands, that only a strong oracle licenses auto-ship, that a
              clean grade on a weak or unscoreable oracle routes to human review (the five
              confirmatory tasks that passed on a weak oracle upstream), that the adequacy floor
              is the SAME number as ``RoutingPolicy.min_oracle_strength`` (derived, so the two
              gates cannot drift), that inverted or out-of-range floors are refused, and that the
              policy is frozen.
How:          Pure calls over the module's constants and ``AdequacyPolicy``; no runner, no git.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/oracle/adequacy.py (under test), src/crb/core/routing.py (the
              policy the floor is derived from), src/crb/core/oracle/mutation.py (the strength
              number the gate consumes), tests/test_oracle_mutation.py
Tested by:    tests/test_oracle_adequacy.py
Touch when:   the routing policy's oracle floor moves (an ADR; the derivation case here fails
              first); a band is added.
"""

from __future__ import annotations

import pytest

from crb.core.oracle.adequacy import (
    ADEQUATE_FLOOR,
    AUTOSHIP_FLOOR,
    DECISION_AUTO_SHIP,
    DECISION_HUMAN_REVIEW,
    DECISION_NEEDS_HUMAN,
    DEFAULT_POLICY,
    AdequacyPolicy,
    adequacy_verdict,
    classify_oracle,
    licenses_autoship,
    routing_decision,
)
from crb.core.routing import DEFAULT_POLICY as ROUTING_POLICY
from crb.core.routing import RoutingPolicy


def test_classify_oracle_bands():
    assert classify_oracle(1.0) == "strong"
    assert classify_oracle(AUTOSHIP_FLOOR) == "strong"
    assert classify_oracle(0.79) == "adequate"
    assert classify_oracle(ADEQUATE_FLOOR) == "adequate"
    assert classify_oracle(0.49) == "weak"
    assert classify_oracle(0.0) == "weak"
    assert classify_oracle(None) == "unscoreable"


def test_licenses_autoship_only_when_strong():
    assert licenses_autoship(0.85) is True
    assert licenses_autoship(0.80) is True
    assert licenses_autoship(0.79) is False
    assert licenses_autoship(0.25) is False
    # unscoreable never licenses auto-ship — no signal is treated as not-yet-trusted
    assert licenses_autoship(None) is False


def test_routing_decision_combines_grade_and_strength():
    # not clean -> needs a human regardless of oracle
    assert routing_decision(False, 1.0) == DECISION_NEEDS_HUMAN
    # clean + strong oracle -> auto-ship
    assert routing_decision(True, 0.9) == DECISION_AUTO_SHIP
    # clean + WEAK oracle -> the pass is real but low-confidence -> human review
    assert routing_decision(True, 0.25) == DECISION_HUMAN_REVIEW
    # clean + unscoreable oracle -> human review (absence of signal != trust)
    assert routing_decision(True, None) == DECISION_HUMAN_REVIEW


def test_the_five_weak_but_passed_confirmatory_tasks_route_to_human():
    """The concrete upstream finding: 5 confirmatory tasks passed on a weak oracle.
    Each must route to human review, not auto-ship, even though they graded clean."""
    weak_passed = {
        "0030839c": 0.44,
        "06ecfa2a": 0.45,
        "920beef1": 0.39,
        "aa7ec5c3": 0.40,
        "b150e0b3": 0.25,
    }
    for task, strength in weak_passed.items():
        assert routing_decision(True, strength) == DECISION_HUMAN_REVIEW, task
        assert adequacy_verdict(True, strength).band == "weak", task  # every strength < 0.5


# --- the policy is one frozen object, consistent with routing ---------------------------
def test_default_floors_match_the_published_routing_rule():
    assert AUTOSHIP_FLOOR == 0.8 and ADEQUATE_FLOOR == 0.5
    assert DEFAULT_POLICY.autoship_floor == ROUTING_POLICY.min_oracle_strength
    assert DEFAULT_POLICY.consistent_with(ROUTING_POLICY)
    assert DEFAULT_POLICY.to_dict() == {
        "autoship_floor": 0.8,
        "adequate_floor": 0.5,
        "version": "adequacy.v1",
    }


def test_policy_derived_from_routing_cannot_drift():
    routing = RoutingPolicy(min_oracle_strength=0.9)
    policy = AdequacyPolicy.from_routing(routing)
    assert policy.autoship_floor == 0.9 and policy.consistent_with(routing)
    assert licenses_autoship(0.85, policy=policy) is False
    assert routing_decision(True, 0.85, policy=policy) == DECISION_HUMAN_REVIEW
    assert classify_oracle(0.85, policy=policy) == "adequate"
    assert not AdequacyPolicy().consistent_with(routing)


def test_policy_rejects_inverted_or_out_of_range_floors():
    with pytest.raises(ValueError):
        AdequacyPolicy(autoship_floor=0.4, adequate_floor=0.5)
    with pytest.raises(ValueError):
        AdequacyPolicy(autoship_floor=1.2)
    with pytest.raises(ValueError):
        AdequacyPolicy(adequate_floor=-0.1)


def test_policy_is_frozen():
    with pytest.raises(AttributeError):
        DEFAULT_POLICY.autoship_floor = 0.1  # type: ignore[misc]


# --- the self-describing verdict carries its n ------------------------------------------
def test_adequacy_verdict_carries_band_decision_and_n():
    v = adequacy_verdict(True, 0.8333, mutants=12)
    assert v.band == "strong" and v.decision == DECISION_AUTO_SHIP and v.mutants == 12
    assert v.to_dict() == {
        "clean": True,
        "oracle_strength": 0.8333,
        "band": "strong",
        "decision": "auto_ship",
        "mutants": 12,
        "policy_version": "adequacy.v1",
    }
    u = adequacy_verdict(True, None)
    assert u.band == "unscoreable" and u.decision == DECISION_HUMAN_REVIEW
    assert u.to_dict()["oracle_strength"] is None
    n = adequacy_verdict(False, 1.0)
    assert n.decision == DECISION_NEEDS_HUMAN
