"""Response models for ``/capability-map``, ``/routes`` and ``/failure-split``.

Extends the base shapes in :mod:`crb.server.schemas` (``CapabilityCellOut``,
``CapabilityMapOut``, ``RouteDecisionOut``, ``RoutesResponse``,
``RoutingPolicyOut``) with what the critical-friend review asked every rate to
carry (action #4):

* the **failure split** — how many of a cell's non-clean rows were the model's
  (``builder_red``), a budget cap (``budget``), a guard refusal (``protocol``),
  an instrument error (``harness``) or excluded (``disqualified``) — next to
  ``model_point`` (clean over fair, finished attempts) with its own ``model_n``
  and Wilson interval. The all-rows ``point`` stays the number that routes.
* the repo's **negative-controls verdict** every cell was routed under, and each
  decision's ``reason_code`` / ``controls_policy``.
* the **economics** (F35) of every cell and of the whole map: the attempts and clean
  attempts with a known cost / latency (the denominators), the mean with a Student-t 95 %
  interval and its method, the apparatus the rows came from — withheld, with the reason,
  when fewer than two rows are known or the rows span more than one apparatus.

Nothing here is computed: every field is a core ``to_dict`` value re-typed so the
OpenAPI document is honest and a drift is a diff.

Navigation
----------
What it is:   The response models for ``/capability-map``, ``/routes`` and
              ``/failure-split`` — the base shapes extended with the failure split, the
              model point and the controls verdict.
What it does: Re-types the core's ``to_dict`` values (``CapabilityCell``, ``RouteDecision``,
              ``ControlsVerdict``, ``FailureSplit``, ``Economics``) so the OpenAPI document is exact and a
              drift between core and API is a diff; validators pin ``state`` /
              ``reason_code`` / failure kinds to the core's closed vocabularies.
How:          Pydantic subclasses of the shapes in src/crb/server/schemas.py; no arithmetic.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/capability.py (the only producer), src/crb/server/schemas.py
              (the base shapes), src/crb/core/routing.py (``REASON_CODES``,
              ``CONTROLS_STATES``), src/crb/core/ledger.py (``FAILURE_KINDS``),
              src/crb/core/economics.py (``Economics.to_dict`` — ``EconomicsOut``),
              ui/src/api/types.ts (the TypeScript twin),
              docs/API.md#capability-routing-forecast-sign-off
Tested by:    tests/test_server_routes_capability.py
Touch when:   never for a new repository; whenever a core ``to_dict`` here gains a field —
              add it in the same change, then ui/src/api/types.ts and docs/API.md.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from crb.core.ledger import FAILURE_KINDS
from crb.core.routing import CONTROLS_STATES, REASON_CODES
from crb.server.schemas import (
    CapabilityCellOut,
    CapabilityMapOut,
    RouteDecisionOut,
    RoutesResponse,
    RoutingPolicyOut,
)


class RoutingPolicyWithControlsOut(RoutingPolicyOut):
    """:meth:`crb.core.routing.RoutingPolicy.to_dict` including the controls-gate
    thresholds (``controls_version`` is the clause set's own version)."""

    min_controls_share: float
    max_controls_escapes: int
    controls_version: str


class ControlsVerdictOut(BaseModel):
    """:meth:`crb.core.routing.ControlsVerdict.to_dict` + ``state`` — the pill word:
    ``passed`` | ``failed`` | ``thin`` | ``escaped`` | ``unmeasured``. ``measured``
    is ``false`` only when the repo has no controls report at all."""

    measured: bool
    passed: bool
    complete: bool
    constructible: int
    total: int
    share: float
    escapes: int
    run_id: str
    created: str
    state: str

    @field_validator("state")
    @classmethod
    def _state_known(cls, v: str) -> str:
        if v not in CONTROLS_STATES:
            raise ValueError(f"controls state {v!r} not in {CONTROLS_STATES}")
        return v


class FailureSplitOut(BaseModel):
    """Counts by :attr:`crb.core.ledger.GradeRow.failure_kind`. ``builder_red +
    lint + budget + protocol + harness + clean == n``; ``disqualified`` sits outside n.
    ``lint_evaluated`` is how many of the n rows carried belt 5 at all (ADR-0011)."""

    builder_red: int
    budget: int
    protocol: int
    harness: int
    disqualified: int
    lint: int = 0
    lint_evaluated: int = 0
    #: Provider outages (usage limit / 429 / dead credential): outside n, like DQ.
    outage: int = 0


class EstimateOut(BaseModel):
    """:meth:`crb.core.economics.Estimate.to_dict`. ``n`` is the denominator (known
    attempts; known clean attempts for cost per clean attempt). ``value`` is ``null`` when
    nothing is known — never ``0`` for unknown; ``ci_low`` / ``ci_high`` are ``null``
    whenever no interval is served, and ``reason`` then says why (``""`` only when the
    value and its interval are both served)."""

    n: int
    value: float | None
    ci_low: float | None
    ci_high: float | None
    method: str
    reason: str


class EconomicsOut(BaseModel):
    """:meth:`crb.core.economics.Economics.to_dict` — cost and latency with their
    denominators, intervals and apparatus. ``pooled`` is ``true`` when the rows span more
    than one apparatus version: every estimate is then withheld (never blended)."""

    n_attempts: int
    n_clean: int
    cost_known: int
    cost_known_clean: int
    latency_known: int
    latency_known_clean: int
    apparatus_versions: list[str]
    pooled: bool
    cost_per_attempt: EstimateOut
    cost_per_clean: EstimateOut
    latency_per_attempt: EstimateOut


class CapabilityCellSplitOut(CapabilityCellOut):
    """A measured cell + its failure split, its model point (with n and interval)
    and the routing reason code. ``model_point`` is ``null`` when no fair, finished
    attempt exists (``model_n == 0``)."""

    reason_code: str
    n_builder_red: int
    n_budget: int
    n_protocol: int
    n_harness: int
    n_disqualified: int
    n_lint: int = 0
    n_lint_evaluated: int = 0
    n_outage: int = 0
    #: distinct tasks behind ``n`` (attempts) — 16 rows on 4 commits is a statement about 4 commits
    n_tasks: int = 0
    model_n: int
    model_point: float | None
    #: ``null`` with ``model_point`` when ``model_n == 0``: never a fabricated ``0.0`` bound.
    model_ci_low: float | None
    model_ci_high: float | None
    failure_split: FailureSplitOut
    #: F35 — this cell's cost and latency with their known counts, intervals and apparatus.
    economics: EconomicsOut

    @field_validator("reason_code")
    @classmethod
    def _reason_known(cls, v: str) -> str:
        if v not in REASON_CODES:
            raise ValueError(f"reason_code {v!r} not in {REASON_CODES}")
        return v


class CapabilityMapWithControlsOut(CapabilityMapOut):
    """``CapabilityMapOut`` whose cells carry the split and which names the controls
    verdict every cell was routed under (always present: ``state: unmeasured`` when
    the repo has no report — never absent, never a pass)."""

    cells: list[CapabilityCellSplitOut]  # type: ignore[assignment]
    controls: ControlsVerdictOut
    policy: RoutingPolicyWithControlsOut
    #: F35 — the economics of every row behind the map (the Baseline's tiles), folded from
    #: the rows themselves: an interval cannot be recombined from the cells' means.
    economics: EconomicsOut


class RouteDecisionWithControlsOut(RouteDecisionOut):
    """``RouteDecisionOut`` + ``reason_code``, ``controls_policy`` (``controls-gate.v1``
    whenever a verdict was evaluated, which the server always does) and the verdict."""

    reason_code: str
    controls_policy: str
    controls: ControlsVerdictOut | None
    model_n: int
    model_point: float | None
    #: ``null`` with ``model_point`` when ``model_n == 0`` — an unmeasured rate has no interval.
    model_ci_low: float | None = None
    model_ci_high: float | None = None
    failure_split: FailureSplitOut


class RoutesWithControlsResponse(RoutesResponse):
    decisions: list[RouteDecisionWithControlsOut]  # type: ignore[assignment]
    policy: RoutingPolicyWithControlsOut
    controls: ControlsVerdictOut


class FailureSplitResponse(BaseModel):
    """:meth:`crb.core.ledger.FailureSplit.to_dict` over one repo (optionally one run).
    Every rate carries its n; ``kinds`` lists the vocabulary so a client never
    hard-codes it."""

    repo: str
    run_id: str
    n: int
    clean: int
    builder_red: int
    budget: int
    protocol: int
    harness: int
    disqualified: int
    rows: int
    lint: int = 0
    lint_evaluated: int = 0
    outage: int = 0
    point: float
    ci_low: float
    ci_high: float
    model_n: int
    #: ``null`` (with both bounds) when ``model_n == 0`` — unmeasured, never a zero row.
    model_point: float | None
    model_ci_low: float | None
    model_ci_high: float | None
    cost_known: int
    cost_unknown: int
    kinds: list[str] = list(FAILURE_KINDS)


__all__ = [
    "CapabilityCellSplitOut",
    "CapabilityMapWithControlsOut",
    "ControlsVerdictOut",
    "EconomicsOut",
    "EstimateOut",
    "FailureSplitOut",
    "FailureSplitResponse",
    "RouteDecisionWithControlsOut",
    "RoutesWithControlsResponse",
    "RoutingPolicyWithControlsOut",
]
