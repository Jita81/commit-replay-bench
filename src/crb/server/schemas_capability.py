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
OpenAPI document is honest and a drift is a diff — except a cell's ``signed``, which
the route fills from the entry gate's own reading (P-411).

Navigation
----------
What it is:   The response models for ``/capability-map``, ``/routes`` and
              ``/failure-split`` — the base shapes extended with the failure split, the
              model point and the controls verdict.
What it does: Re-types the core's ``to_dict`` values (``CapabilityCell``, ``RouteDecision``,
              ``ControlsVerdict``, ``FailureSplit``, ``Economics``) so the OpenAPI document
              is exact and a drift between core and API is a diff; validators pin ``state`` /
              ``reason_code`` / failure kinds to the core's closed vocabularies.
How:          Pydantic subclasses of the shapes in src/crb/server/schemas.py; no arithmetic.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/capability.py (the only producer; fills ``signed`` from
              ``crb.factory.standard.cell_signed``), src/crb/server/schemas.py
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

from typing import Any

from pydantic import BaseModel, Field, field_validator

from crb.core.checks import ARMS
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
    #: controls-gate.v2: the apparatus the report was produced at, and why a verdict is
    #: unmeasured (no report, a report of another apparatus, a cancelled run).
    apparatus_version: str = ""
    detail: str = ""

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
    #: Of ``outage``, the rows whose login this deployment presented was refused (pilot D1).
    outage_auth: int = 0
    #: Belt 6 (opt-in, ADR-0024): working code that changed the public API unlike the gold.
    api: int = 0


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
    than one apparatus version, posture class or checks arm: every estimate is then
    withheld (never blended) and ``pooled_reason`` names what the rows span."""

    n_attempts: int
    n_clean: int
    cost_known: int
    cost_known_clean: int
    latency_known: int
    latency_known_clean: int
    apparatus_versions: list[str]
    posture_classes: list[str]
    checks_arms: list[str]
    pooled: bool
    pooled_reason: str
    cost_per_attempt: EstimateOut
    cost_per_clean: EstimateOut
    latency_per_attempt: EstimateOut


class ShortfallOut(BaseModel):
    """:meth:`crb.core.routing.Shortfall.to_dict` — one clause the cell fails, the next
    measurement it names (``next``), how many (``count``) and whether it spends model money."""

    code: str
    route: str
    observed: Any = None
    threshold: Any = None
    next: str
    count: int = 0
    model_money: bool = False


class ArmReadingOut(BaseModel):
    """One arm of a registered reading (``crb.core.reading.ArmReading.to_dict``): its state
    under the look rule, the distinct commits read in the seeded order, clean, the Wilson
    interval, the next look and the commits still needed."""

    arm: str
    state: str
    descriptive: bool = False
    stopped_by: str = ""
    counted: int = 0
    clean: int = 0
    misses: int = 0
    ci_low: float = 0.0
    ci_high: float = 1.0
    next_look: int | None = None
    needed: int = 0
    decided_at: int | None = None
    look_state: str = ""
    left: list[dict[str, Any]] = Field(default_factory=list)
    counted_commits: list[str] = Field(default_factory=list)


class ReadingOut(BaseModel):
    """A registered reading evaluated (``crb.core.reading.ReadingOutcome.to_dict``): every arm,
    the unbroken chain, the standard (or ``null``) and the budget share it spent."""

    reading_id: str
    rule: str
    hierarchy: list[str]
    state: str
    standard: str | None
    ceiling: bool
    chain: list[str]
    stopped_at: str | None
    needed: int
    spend: float
    registered_at: str
    pool: int
    pool_sha256: str
    arms: list[ArmReadingOut]


class CellStandardOut(BaseModel):
    """What a cell's proven context is: the standard arm (``null`` — "no proven standard"),
    whether it is only a ceiling, the next measurement and the cell's budget spent."""

    standard: str | None
    ceiling: bool = False
    label: str
    next: str = ""
    next_count: int = 0
    budget: float
    spent: float


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
    n_api: int = 0
    n_outage: int = 0
    #: distinct tasks behind ``n`` (attempts) — 16 rows on 4 commits is a statement about 4 commits
    n_tasks: int = 0
    model_n: int
    model_point: float | None
    #: ``null`` with ``model_point`` when ``model_n == 0``: never a fabricated ``0.0`` bound.
    model_ci_low: float | None
    model_ci_high: float | None
    failure_split: FailureSplitOut
    #: The one checks arm every row of the cell was graded under (ADR-0024 §6) — the arm
    #: ``checks=current`` resolved to, so a reader never has to guess it.
    checks_arm: str
    #: F35 — this cell's cost and latency with their known counts, intervals and apparatus.
    economics: EconomicsOut
    # --- routing.v2 (ADR-0025, ADR-0026) ------------------------------------------------
    #: The one context arm and class-set version the cell reads (never pooled).
    context_arm: str = ""
    taxonomy: str = ""
    apparatus_version: str = ""
    #: Distinct changes, each by its first observed attempt, and how many routed.
    n_tasks_eligible: int = 0
    task_clean: int = 0
    task_ci_low: float = 0.0
    task_ci_high: float = 1.0
    n_unsealed: int = 0
    #: What the cell's reading says about this arm, and the counts it read at.
    look_state: str = ""
    reading_id: str = ""
    counted: int = 0
    counted_clean: int = 0
    counted_ci_low: float = 0.0
    counted_ci_high: float = 1.0
    needed: int = 0
    next_look: int | None = None
    oracle_scored_tasks: int = 0
    oracle_share: float = 0.0
    shortfalls: list[ShortfallOut] = Field(default_factory=list)
    #: Every arm of the reading that speaks for the cell (``null`` — none registered).
    reading: ReadingOut | None = None
    standard: CellStandardOut | None = None
    #: Whether the entry gate reads the cell's (class × size) proven standard as signed: an
    #: active sign-off made on its arm, class-set version, reading and apparatus, on the
    #: repository's own checks arm and this deployment's posture class, whatever this view's
    #: filters (``crb.factory.standard.cell_signed``, ADR-0026 item 8). The ONE reading of
    #: "signed" (P-411): ``verification_tier`` records the sign-off overlay, which matches
    #: sign-offs by another rule and never says whether an item would be built. ``null`` for a
    #: cell that pools classes or sizes — the gate reads one class × size — and on an
    #: organisation's class-set view, whose cells are keyed by the global parent (G-763).
    signed: bool | None = None
    #: What the cell's briefs carried beyond their arm (label → distinct values): shown as
    #: provenance, never a reason to split the cell (ADR-0026 item 1).
    provenance: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("reason_code")
    @classmethod
    def _reason_known(cls, v: str) -> str:
        if v not in REASON_CODES:
            raise ValueError(f"reason_code {v!r} not in {REASON_CODES}")
        return v

    @field_validator("checks_arm")
    @classmethod
    def _arm_known(cls, v: str) -> str:
        if v not in ARMS:
            raise ValueError(f"checks_arm {v!r} not in {ARMS}")
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
    #: The one context arm and class-set version the map reads, and the arms and versions
    #: the repository's rows carry (``?arm=`` / ``?taxonomy=`` select; ``all`` is refused).
    arm: str = ""
    arms: list[str] = Field(default_factory=list)
    taxonomy: str = ""
    taxonomies: list[str] = Field(default_factory=list)
    #: ADR-0025 item 1: the apparatus the map reads and what an earlier one holds as history.
    apparatus: dict[str, Any] = Field(default_factory=dict)


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
    #: Rows behind the decision that were imported, not measured here (EI-2 residual): 0 on
    #: the default ``apparatus=current`` reading; above 0 the route is a reader's view of
    #: someone else's evidence and licenses nothing.
    rows_imported: int = 0
    # --- routing.v2 --------------------------------------------------------------------
    n_tasks: int = 0
    task_clean: int = 0
    task_point: float = 0.0
    task_ci_low: float = 0.0
    task_ci_high: float = 1.0
    basis: str = ""
    oracle_scored_tasks: int = 0
    oracle_share: float = 0.0
    shortfalls: list[ShortfallOut] = Field(default_factory=list)
    apparatus_version: str = ""
    context_arm: str = ""
    taxonomy: str = ""
    reading_id: str = ""
    look_state: str = ""
    counted: int = 0
    counted_clean: int = 0
    needed: int = 0
    next_look: int | None = None
    standard: str = ""


class RoutesWithControlsResponse(RoutesResponse):
    decisions: list[RouteDecisionWithControlsOut]  # type: ignore[assignment]
    policy: RoutingPolicyWithControlsOut
    controls: ControlsVerdictOut
    arm: str = ""
    arms: list[str] = Field(default_factory=list)
    taxonomy: str = ""


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
    #: Of ``outage``, the rows whose login this deployment presented was refused — "your
    #: login", not "the provider" (pilot D1; rows of apparatus 2.4 and later carry the cause).
    outage_auth: int = 0
    api: int = 0
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
    "ArmReadingOut",
    "CapabilityCellSplitOut",
    "CapabilityMapWithControlsOut",
    "CellStandardOut",
    "ControlsVerdictOut",
    "EconomicsOut",
    "EstimateOut",
    "FailureSplitOut",
    "FailureSplitResponse",
    "ReadingOut",
    "RouteDecisionWithControlsOut",
    "RoutesWithControlsResponse",
    "RoutingPolicyWithControlsOut",
    "ShortfallOut",
]
