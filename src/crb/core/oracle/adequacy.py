"""Oracle-adequacy gate — the routing consequence of a measured oracle strength.

``false-Q1 = 0`` is the HONESTY floor: no graded-clean trial ever lacked a green
oracle. But a green *weak* oracle is a low bar — mutation testing on a sealed corpus
put the changed-line kill-rate at 58% aggregate with a 25–76% per-cell spread, and
several confirmatory tasks passed on an oracle that catches under half of the faults
planted in the very code they changed. For those, "clean" understates the risk of an
incorrect-but-passing patch.

This module encodes the prevention: **a clean grade licenses AUTO-DELIVERY only when
its oracle is adequate.** Below the floor a pass is real but low-confidence — it routes
to a human even on green. That makes "trust a weak-oracle pass" non-producible in the
router without weakening false-Q1 = 0, which is orthogonal: the floor forbids a clean
grade with a RED oracle; adequacy governs how much a GREEN one is worth.

The thresholds live in one frozen :class:`AdequacyPolicy`. Its auto-ship floor is,
by construction, the same number as ``RoutingPolicy.min_oracle_strength`` in
:mod:`crb.core.routing` — the two gates cannot drift apart silently.

Navigation
----------
What it is:   The oracle-adequacy gate — pure functions from a measured ``oracle_strength`` to
              a band (``strong``/``adequate``/``weak``/``unscoreable``) and a per-trial
              routing decision.
What it does: Decides how much a GREEN oracle is worth: a clean grade auto-ships only at or
              above the auto-ship floor; below it (or unmeasured) the pass routes to a human.
              It never touches whether a grade is clean — that is false-Q1's floor.
How:          ``AdequacyPolicy`` (frozen, validated, auto-ship floor imported from the routing
              policy) → ``classify_oracle`` → ``licenses_autoship`` → ``routing_decision`` →
              the self-describing ``AdequacyVerdict``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/routing.py (``RoutingPolicy.min_oracle_strength`` is the auto-ship
              floor — the two are one number), src/crb/core/oracle/mutation.py (produces the
              strength this consumes), src/crb/server/routes/oracle.py (serves the verdict),
              src/crb/factory/review.py (applies it to manufactured work)
Tested by:    tests/test_oracle_adequacy.py
Touch when:   never for a new repository; moving a floor is a change to the routing policy
              first (docs/adr/0003-one-routing-rule.md) and to
              docs/EVIDENCE-AND-CLAIMS.md — then ``ADEQUACY_POLICY_VERSION`` bumps.
Claims:       ``auto_ship`` is a routing recommendation on measured evidence, not a
              statement that the patch is correct (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crb.core.routing import DEFAULT_POLICY as DEFAULT_ROUTING_POLICY
from crb.core.routing import RoutingPolicy

ADEQUACY_POLICY_VERSION = "adequacy.v1"

ORACLE_STRONG = "strong"
ORACLE_ADEQUATE = "adequate"
ORACLE_WEAK = "weak"
ORACLE_UNSCOREABLE = "unscoreable"
ORACLE_BANDS: tuple[str, ...] = (ORACLE_STRONG, ORACLE_ADEQUATE, ORACLE_WEAK, ORACLE_UNSCOREABLE)

DECISION_AUTO_SHIP = "auto_ship"
DECISION_HUMAN_REVIEW = "human_review"
DECISION_NEEDS_HUMAN = "needs_human"
DECISIONS: tuple[str, ...] = (DECISION_AUTO_SHIP, DECISION_HUMAN_REVIEW, DECISION_NEEDS_HUMAN)


@dataclass(frozen=True)
class AdequacyPolicy:
    """The two floors. ``autoship_floor`` ≥ ``adequate_floor``; both within [0, 1]."""

    #: Kill-rate at/above which a green oracle is strong enough to license auto-delivery.
    autoship_floor: float = DEFAULT_ROUTING_POLICY.min_oracle_strength
    #: Kill-rate at/above which an oracle is "adequate" (usable, but review-gated).
    adequate_floor: float = 0.5
    version: str = ADEQUACY_POLICY_VERSION

    def __post_init__(self) -> None:
        if not 0.0 <= self.adequate_floor <= self.autoship_floor <= 1.0:
            raise ValueError(
                f"need 0 ≤ adequate_floor ({self.adequate_floor}) ≤ autoship_floor "
                f"({self.autoship_floor}) ≤ 1"
            )

    @classmethod
    def from_routing(cls, routing: RoutingPolicy, *, adequate_floor: float = 0.5) -> AdequacyPolicy:
        """Derive the auto-ship floor from a routing policy so the two never disagree."""
        return cls(autoship_floor=routing.min_oracle_strength, adequate_floor=adequate_floor)

    def consistent_with(self, routing: RoutingPolicy) -> bool:
        """``True`` iff this policy's auto-ship floor is the routing policy's — the drift check."""
        return self.autoship_floor == routing.min_oracle_strength

    def to_dict(self) -> dict[str, Any]:
        """The policy as stored next to a verdict (so a reader sees the floors that applied)."""
        return {
            "autoship_floor": self.autoship_floor,
            "adequate_floor": self.adequate_floor,
            "version": self.version,
        }


DEFAULT_POLICY = AdequacyPolicy()
AUTOSHIP_FLOOR = DEFAULT_POLICY.autoship_floor
ADEQUATE_FLOOR = DEFAULT_POLICY.adequate_floor


def classify_oracle(strength: float | None, *, policy: AdequacyPolicy = DEFAULT_POLICY) -> str:
    """``strong`` (≥ autoship) | ``adequate`` (≥ adequate) | ``weak`` | ``unscoreable`` (None)."""
    if strength is None:
        return ORACLE_UNSCOREABLE
    if strength >= policy.autoship_floor:
        return ORACLE_STRONG
    if strength >= policy.adequate_floor:
        return ORACLE_ADEQUATE
    return ORACLE_WEAK


def licenses_autoship(strength: float | None, *, policy: AdequacyPolicy = DEFAULT_POLICY) -> bool:
    """True iff a CLEAN grade on this oracle may auto-deliver without a human.

    Unscoreable oracles (no mutants / not measured) never license auto-ship — absence
    of a strength signal is treated as not-yet-trusted, never as pass.
    """
    return strength is not None and strength >= policy.autoship_floor


def routing_decision(
    clean: bool, oracle_strength: float | None, *, policy: AdequacyPolicy = DEFAULT_POLICY
) -> str:
    """Combine a grade and its oracle strength into a per-trial routing verdict.

    * ``auto_ship``    — clean AND the oracle is strong enough to trust the pass;
    * ``human_review`` — clean but the oracle is weak/unscoreable (low-confidence pass);
    * ``needs_human``  — not clean (no green, regression-free change was produced).

    false-Q1 = 0 guarantees a clean grade always had a GREEN oracle; this only decides
    how much to TRUST that green.
    """
    if not clean:
        return DECISION_NEEDS_HUMAN
    return (
        DECISION_AUTO_SHIP
        if licenses_autoship(oracle_strength, policy=policy)
        else DECISION_HUMAN_REVIEW
    )


@dataclass(frozen=True)
class AdequacyVerdict:
    """The classification and decision for one (clean, strength) pair, with its n."""

    clean: bool
    oracle_strength: float | None
    band: str
    decision: str
    mutants: int = 0
    policy_version: str = ADEQUACY_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        """The API/report shape; strength rounded so the JSON is stable across platforms."""
        return {
            "clean": self.clean,
            "oracle_strength": (
                None if self.oracle_strength is None else round(self.oracle_strength, 4)
            ),
            "band": self.band,
            "decision": self.decision,
            "mutants": self.mutants,
            "policy_version": self.policy_version,
        }


def adequacy_verdict(
    clean: bool,
    oracle_strength: float | None,
    *,
    mutants: int = 0,
    policy: AdequacyPolicy = DEFAULT_POLICY,
) -> AdequacyVerdict:
    """The self-describing form of :func:`routing_decision` (band + decision + n)."""
    return AdequacyVerdict(
        clean=clean,
        oracle_strength=oracle_strength,
        band=classify_oracle(oracle_strength, policy=policy),
        decision=routing_decision(clean, oracle_strength, policy=policy),
        mutants=mutants,
        policy_version=policy.version,
    )
