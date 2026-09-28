"""The ONE routing rule — ``routing.v2`` (ADR-0025 as ADR-0026 amends it).

Given one cell's measured statistics — one apparatus, one context arm, one class-set version,
one checks arm (``crb.core.ledger.cell_stats`` refuses any pooling) — what the cell's
registered reading says about that arm, the oracle evidence of the commits it counted and the
repository's negative-controls verdict at the same apparatus, decide what the factory may do
with that class of change:

* ``deliver``      — the arm is the cell's **standard**: its registered reading delivered under
  the look rule (distinct commits clean on their first observed attempt, in the seeded order,
  graded in the sealed posture, read only at the rule's looks), the richer arms of the
  hierarchy delivered before it, it certifies (``S1@<author>`` or ``S2``; ``S3`` is a ceiling
  and ``A0`` is descriptive), false-Q1 = 0, an oracle strength of at least 0.80 was measured
  under ``mutation.v2`` on at least half of the commits it counted, and a complete
  negative-controls report at the same apparatus passed, exercised at least half its controls
  and let no measurement control escape.
* ``do_not_ship``  — any false-Q1 in the cell: the evidence is untrusted until audited.
* ``human``        — green cannot license auto-delivery: the controls gate FAILED, the oracle is
  weak, a measurement control escaped, or the reading read ``insufficient`` (a person, a richer
  arm in a new reading within the budget, or a split).
* ``granularize``  — XL changes are split before they are attempted.
* ``calibrate``    — something is not measured yet: the posture is not sealed, belt 5 was
  switched off, no reading is registered, the look is pending, the oracle or the controls are
  unmeasured or thin, the reading is ``undecided``, the arm is a ceiling or not the standard.

``route`` is first-match for the route and its reason code, in the ADR's order, and lists
EVERY clause that fails on ``RouteDecision.shortfalls`` with the next measurement and its count,
so an operator never pays for one shortfall to discover the next. Nothing unmeasured delivers:
``oracle=None`` and ``controls=None`` read as unmeasured, and a reading that does not exist reads
``reading_unregistered``. The per-attempt numbers (``n``, ``point``, ``ci_low``, ``ci_high``)
and the per-change numbers (``n_tasks``, ``task_clean``, the task interval) are carried for
display; they route nothing — the look rule does.

Navigation
----------
What it is:   The routing rule — ``route``, the one function that turns a measured cell and its
              reading into ``deliver`` / ``calibrate`` / ``granularize`` / ``human`` /
              ``do_not_ship`` with a reason, a reason code and every shortfall.
What it does: Applies ``routing.v2``'s clauses in a fixed order (first match wins): false-Q1,
              size, a failed controls gate, the sealed posture, belt 5 switched off, the
              reading (unregistered, look pending), the oracle (unmeasured, thin, weak), escaped
              controls, the reading (insufficient, undecided), the standard (ceiling, a leaner
              standard), unmeasured and thin controls; renders the published bar as one
              sentence (``RoutingPolicy.describe``) that README carries byte for byte. Pure.
How:          ``route(stats, oracle=OracleEvidence, controls=ControlsVerdict,
              reading=ArmVerdict)`` → ``RouteDecision`` stamped ``routing.v2`` and
              ``controls-gate.v2`` with its thresholds and ``Shortfall`` list.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md (items 3 to 6),
              docs/adr/0003-one-routing-rule.md, docs/adr/0010-polyglot-negative-controls.md
Works with:   src/crb/core/ledger.py (CellStats — one apparatus, arm and class-set version),
              src/crb/core/reading.py (the reading an arm is routed on — ``verdict_for``),
              src/crb/core/capability.py (the map that routes every cell),
              src/crb/core/oracle/controls.py (the report a ControlsVerdict reduces),
              src/crb/core/signoff.py (a sign-off needs the standard arm's ``deliver``),
              src/crb/server/routes/capability.py (serves decisions),
              src/crb/cli/commands/route.py (``crb route``), scripts/claims_check.py (the README
              bar is ``describe()`` byte for byte)
Tested by:    tests/test_routing.py, tests/test_routing_v2.py, tests/test_capability.py,
              tests/test_signoff.py, tests/test_server_routes_capability.py,
              tests/test_claims_check.py
Touch when:   never for a new repository (the rule is the same for every cell); changing a
              threshold, a clause, the rule or a reason code changes what ``deliver`` means —
              bump ``POLICY_VERSION`` / ``CONTROLS_POLICY_VERSION`` and the apparatus, write an
              ADR superseding docs/adr/0025-routing-v2.md, regenerate README's routing bar, and
              update the UI's reason-code copy.
Claims:       ``deliver`` licenses auto-delivery as a branch + PR under review, not mergeability
              (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from crb.core.context_arm import BASE_S2, parse_arm
from crb.core.ledger import CellStats, is_v2_apparatus
from crb.core.reading import (
    CELL_ERROR_BUDGET,
    RULE_LOOK_V1,
    VERDICT_CEILING,
    VERDICT_DELIVER,
    VERDICT_DESCRIPTIVE,
    VERDICT_INSUFFICIENT,
    VERDICT_LEANER,
    VERDICT_LOOK_PENDING,
    VERDICT_UNDECIDED,
    VERDICT_UNREGISTERED,
    ArmVerdict,
    rule_looks,
    rule_spend,
)

#: Stamped on every decision. A decision made under an older version is not comparable
#: with one made under a newer one; bump on any change to a clause or a threshold.
POLICY_VERSION = "routing.v2"
#: The retired rule (ADR-0003's numeric bar): refused as a policy name, kept so stored
#: decisions stamped with it still name what they were.
POLICY_VERSION_V1 = "routing.v1"
CONTROLS_POLICY_VERSION = "controls-gate.v2"
#: How a decision counts (ADR-0025 item 2): each distinct change once, by its first observed
#: attempt.
BASIS_FIRST_OBSERVED_ATTEMPT = "first_observed_attempt"

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

# --- reason codes: one per clause, in evaluation order ----------------------------
# A code is the machine-readable half of a decision (the UI keys copy and pills on it; the
# learning loop groups on it); ``reason`` is the human sentence.
REASON_FALSE_Q1 = "false_q1"
REASON_GRANULARIZE = "granularize"
REASON_CONTROLS_FAILED = "controls_failed"
REASON_POSTURE_UNSEALED = "posture_unsealed"
REASON_LINT_DISABLED = "lint_disabled"
REASON_READING_UNREGISTERED = "reading_unregistered"
REASON_DESCRIPTIVE = "descriptive"
REASON_LOOK_PENDING = "look_pending"
REASON_ORACLE_UNMEASURED = "oracle_unmeasured"
REASON_ORACLE_THIN = "oracle_thin"
REASON_ORACLE_WEAK = "oracle_weak"
REASON_CONTROLS_ESCAPES = "controls_escapes"
REASON_INSUFFICIENT = "insufficient"
REASON_UNDECIDED = "undecided"
REASON_CEILING = "ceiling"
REASON_LEANER_STANDARD = "leaner_standard"
REASON_CONTROLS_UNMEASURED = "controls_unmeasured"
REASON_CONTROLS_THIN = "controls_thin"
REASON_DELIVER = "deliver"
#: routing.v1's codes, retired by routing.v2 — readable so a stored v1 decision still validates.
REASON_N_BELOW_MIN = "n_below_min"
REASON_POINT_BELOW_BAR = "point_below_bar"
REASON_CI_LOW_BELOW_BAR = "ci_low_below_bar"
REASON_CODES_V1: tuple[str, ...] = (
    REASON_N_BELOW_MIN,
    REASON_POINT_BELOW_BAR,
    REASON_CI_LOW_BELOW_BAR,
)
#: routing.v2's codes, in the order ``route`` applies them.
REASON_CODES_V2: tuple[str, ...] = (
    REASON_FALSE_Q1,
    REASON_GRANULARIZE,
    REASON_CONTROLS_FAILED,
    REASON_POSTURE_UNSEALED,
    REASON_LINT_DISABLED,
    REASON_READING_UNREGISTERED,
    REASON_DESCRIPTIVE,
    REASON_LOOK_PENDING,
    REASON_ORACLE_UNMEASURED,
    REASON_ORACLE_THIN,
    REASON_ORACLE_WEAK,
    REASON_CONTROLS_ESCAPES,
    REASON_INSUFFICIENT,
    REASON_UNDECIDED,
    REASON_CEILING,
    REASON_LEANER_STANDARD,
    REASON_CONTROLS_UNMEASURED,
    REASON_CONTROLS_THIN,
    REASON_DELIVER,
)
REASON_CODES: tuple[str, ...] = (*REASON_CODES_V2, *REASON_CODES_V1)

# --- the next measurement a shortfall names (ADR-0025 item 8) -------------------------
NEXT_AUDIT = "audit"
NEXT_SPLIT = "split"
NEXT_CONTROLS = "controls"
NEXT_SEAL = "seal"
NEXT_CONFIG = "config"
NEXT_REGISTER = "register"
NEXT_REPLAY = "replay"
NEXT_QUALIFY = "qualify"
NEXT_MINE = "mine"
NEXT_ORACLE = "oracle"
NEXT_STRENGTHEN = "strengthen"
NEXT_NEW_READING = "new_reading"
NEXT_CALIBRATION_BUILDS = "calibration_builds"
NEXT_BUILD_ON_STANDARD = "build_on_standard"
NEXT_NONE = "none"
NEXT_ACTS: tuple[str, ...] = (
    NEXT_AUDIT,
    NEXT_SPLIT,
    NEXT_CONTROLS,
    NEXT_SEAL,
    NEXT_CONFIG,
    NEXT_REGISTER,
    NEXT_REPLAY,
    NEXT_QUALIFY,
    NEXT_MINE,
    NEXT_ORACLE,
    NEXT_STRENGTHEN,
    NEXT_NEW_READING,
    NEXT_CALIBRATION_BUILDS,
    NEXT_BUILD_ON_STANDARD,
    NEXT_NONE,
)
#: The acts that spend model money (a replay attempt, a calibration build).
MODEL_MONEY_ACTS: frozenset[str] = frozenset({NEXT_REPLAY, NEXT_CALIBRATION_BUILDS})

# --- controls verdict states (what a UI pill says) --------------------------------
CONTROLS_UNMEASURED = "unmeasured"
CONTROLS_FAILED = "failed"
CONTROLS_THIN = "thin"
CONTROLS_ESCAPED = "escaped"
CONTROLS_PASSED = "passed"
CONTROLS_STATES: tuple[str, ...] = (
    CONTROLS_UNMEASURED,
    CONTROLS_FAILED,
    CONTROLS_THIN,
    CONTROLS_ESCAPED,
    CONTROLS_PASSED,
)


@dataclass(frozen=True)
class ControlsVerdict:
    """The negative-controls gate of ONE repo at ONE apparatus, reduced to what routing needs.

    ``passed`` is the gate (no VIOLATION — see :class:`crb.core.oracle.controls.
    ControlsReport`). ``total`` counts the control rows that had a RED oracle to exercise
    (``rows − skipped``); ``constructible`` those that were actually built and graded
    (``total − not_constructible``). ``escapes`` counts measurement controls (``hardcode_cheat``,
    ``env_poison``) that graded CLEAN. ``measured`` is ``False`` only for the sentinel
    :meth:`unmeasured`; ``complete`` is ``False`` when the run that produced the report was
    cancelled part-way — such a report can fail and can escape (a violation found is a
    violation) but it can never pass (controls-gate.v2). ``apparatus_version`` is the apparatus
    the report was produced at: a report of another apparatus routes as unmeasured. ``detail``
    says why a verdict is unmeasured.
    """

    passed: bool
    constructible: int
    total: int
    escapes: int
    run_id: str = ""
    created: str = ""
    complete: bool = True
    measured: bool = True
    apparatus_version: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.constructible < 0 or self.total < 0 or self.escapes < 0:
            raise ValueError("controls counts cannot be negative")
        if self.constructible > self.total:
            raise ValueError("constructible cannot exceed total")

    @classmethod
    def unmeasured(cls, detail: str = "") -> ControlsVerdict:
        """The honest absence: no controls report for the repo at this apparatus."""
        return cls(
            passed=False,
            constructible=0,
            total=0,
            escapes=0,
            measured=False,
            detail=detail or "no negative-controls report",
        )

    @classmethod
    def from_counts(
        cls, counts: Mapping[str, Any], *, run_id: str = "", created: str = ""
    ) -> ControlsVerdict:
        """From a worker ``controls`` run's ``counts_json`` (``{tasks, total, rows,
        violations, escapes, not_constructible, skipped, passed, complete}``) or a
        ``controls.report`` event payload (``ControlsReport.to_dict()``:
        ``n_rows`` for ``rows``, ``apparatus.complete`` for ``complete``,
        ``apparatus.apparatus_version`` for the apparatus)."""

        def _int(k: str, *alts: str) -> int:
            for key in (k, *alts):
                v = counts.get(key)
                if isinstance(v, bool):
                    return int(v)
                if isinstance(v, int | float):
                    return int(v)
                if isinstance(v, list | tuple):
                    return len(v)  # the report's ``rows`` is the row list itself
            return 0

        rows = _int("n_rows", "rows")
        skipped = _int("skipped")
        not_constructible = _int("not_constructible")
        # a skipped row (no RED oracle to exercise) is not a control that failed to be
        # built: it leaves both the numerator and the denominator of ``share``
        total = max(0, rows - skipped)
        apparatus = counts.get("apparatus")
        complete = counts.get("complete")
        if complete is None and isinstance(apparatus, Mapping):
            complete = apparatus.get("complete")
        version = counts.get("apparatus_version")
        if not version and isinstance(apparatus, Mapping):
            version = apparatus.get("apparatus_version")
        return cls(
            passed=bool(counts.get("passed", False)),
            constructible=max(0, min(total, total - not_constructible)),
            total=total,
            escapes=_int("escapes"),
            run_id=run_id or str(counts.get("run_id", "") or ""),
            created=created or str(counts.get("reported_at", "") or ""),
            complete=True if complete is None else bool(complete),
            apparatus_version=str(version or ""),
        )

    def at(self, apparatus_version: str) -> ControlsVerdict:
        """This verdict as a cell of ``apparatus_version`` reads it (controls-gate.v2): a
        report of another apparatus is history and reads as unmeasured, and an incomplete run
        that found nothing is unmeasured — never a pass, and never an older pass in its place.
        A cell below apparatus 2.4 reads a report as it did (its reports carry no stamp)."""
        if not self.measured:
            return self
        if is_v2_apparatus(apparatus_version) and self.apparatus_version != apparatus_version:
            return ControlsVerdict.unmeasured(
                f"the latest report is of apparatus {self.apparatus_version or 'unstamped'}, "
                f"not {apparatus_version} — history, never read as this apparatus's"
            )
        if not self.complete and self.passed and self.escapes == 0:
            return ControlsVerdict.unmeasured(
                "the latest controls run was cancelled before it finished and found nothing — "
                "an incomplete run cannot pass"
            )
        return self

    @property
    def share(self) -> float:
        """The share of controls actually exercised; ``0.0`` when none could be."""
        return self.constructible / self.total if self.total else 0.0

    def thin(self, min_share: float) -> bool:
        """Fewer than ``min_share`` of the controls could be built — "passed" then
        says little. Unmeasured is not thin (it has its own clause)."""
        return self.measured and self.share < min_share

    def state(self, *, min_share: float, max_escapes: int) -> str:
        """The one-word state a pill shows, in the order the router applies it."""
        if not self.measured:
            return CONTROLS_UNMEASURED
        if not self.passed:
            return CONTROLS_FAILED
        if self.escapes > max_escapes:
            return CONTROLS_ESCAPED
        if not self.complete:
            return CONTROLS_UNMEASURED
        if self.thin(min_share):
            return CONTROLS_THIN
        return CONTROLS_PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "passed": self.passed,
            "complete": self.complete,
            "constructible": self.constructible,
            "total": self.total,
            "share": round(self.share, 4),
            "escapes": self.escapes,
            "run_id": self.run_id,
            "created": self.created,
            "apparatus_version": self.apparatus_version,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class OracleEvidence:
    """What a route reads about the oracle (ADR-0025 item 3): the mean, over the counted
    commits that have one, of each commit's MINIMUM scoreable ``mutation.v2`` strength at the
    reading's apparatus (a minimum cannot rise when a flaky suite is re-scored), with how many
    commits carry one out of how many the route counted. ``strength=None`` is unmeasured."""

    strength: float | None
    scored_tasks: int
    n_tasks: int
    mutation_version: str = ""
    apparatus_version: str = ""

    def __post_init__(self) -> None:
        if self.scored_tasks < 0 or self.n_tasks < 0:
            raise ValueError("oracle evidence counts cannot be negative")
        if self.scored_tasks > self.n_tasks:
            raise ValueError("scored_tasks cannot exceed n_tasks")

    @property
    def share(self) -> float:
        return self.scored_tasks / self.n_tasks if self.n_tasks else 0.0

    @property
    def measured(self) -> bool:
        return self.strength is not None and self.scored_tasks > 0

    @classmethod
    def unmeasured(cls, n_tasks: int = 0) -> OracleEvidence:
        return cls(strength=None, scored_tasks=0, n_tasks=max(n_tasks, 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strength": None if self.strength is None else round(self.strength, 4),
            "scored_tasks": self.scored_tasks,
            "n_tasks": self.n_tasks,
            "share": round(self.share, 4),
            "mutation_version": self.mutation_version,
            "apparatus_version": self.apparatus_version,
        }


@dataclass(frozen=True)
class Shortfall:
    """One clause a cell fails, with what to measure next (ADR-0025 item 8): ``next`` is one
    of :data:`NEXT_ACTS`, ``count`` how many of it (commits still needed to the next look for
    ``replay``; unscored commits for ``oracle``) and ``model_money`` whether it spends any."""

    code: str
    route: str
    observed: Any
    threshold: Any
    next: str
    count: int = 0
    model_money: bool = False

    def __post_init__(self) -> None:
        if self.code not in REASON_CODES_V2:
            raise ValueError(f"shortfall code {self.code!r} not in {REASON_CODES_V2}")
        if self.next not in NEXT_ACTS:
            raise ValueError(f"next act {self.next!r} not in {NEXT_ACTS}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "route": self.route,
            "observed": self.observed,
            "threshold": self.threshold,
            "next": self.next,
            "count": self.count,
            "model_money": self.model_money,
        }


def _looks_phrase(rule: str) -> str:
    """``"20 of the first 20, 29 of the first 30 or 38 of the first 40"``."""
    looks = rule_looks(rule)
    parts = [f"{n - m} of the first {n}" for n, m in sorted(looks.items())]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " or " + parts[-1]


@dataclass(frozen=True)
class RoutingPolicy:
    """The thresholds of the rule. The defaults ARE the published rule (ADR-0025 as ADR-0026
    amends it); a caller may tighten them for a deployment, and the ``version`` fields travel
    with every decision so a relaxed policy can never pass as the standard one. The look rule
    (``rule``) replaces routing.v1's ``min_n`` and its point and Wilson bars."""

    min_oracle_strength: float = 0.80
    #: ``deliver`` needs an oracle score on at least this share of the counted commits.
    min_oracle_share: float = 0.5
    granularize_sizes: tuple[str, ...] = ("XL",)
    #: The look rule a reading is read under (``crb.core.reading.RULES``).
    rule: str = RULE_LOOK_V1
    #: One error budget per cell (ADR-0026 item 5; the operator's value).
    cell_error_budget: float = CELL_ERROR_BUDGET
    version: str = POLICY_VERSION
    #: ``deliver`` needs at least this share of the repo's control rows to have been
    #: constructible (exercised): a majority, so "passed" means the load-bearing
    #: controls ran, not just the three easy ones.
    min_controls_share: float = 0.5
    #: ``deliver`` is refused while more than this many measurement controls have
    #: graded clean on the repo (a re-run with the oracle hardened clears it).
    max_controls_escapes: int = 0
    controls_version: str = CONTROLS_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version == POLICY_VERSION_V1:
            raise ValueError(
                f"{POLICY_VERSION_V1!r} is retired (ADR-0025): an old policy file cannot pose "
                f"as the published bar, which is {POLICY_VERSION!r}"
            )
        rule_looks(self.rule)
        # A policy LOOSER than the published one on any clause cannot travel under the
        # published version string: every decision it produces would read as ``routing.v2``
        # while clearing a lower bar. Tightening is allowed (the same name is honest — the
        # rule holds and more); the oracle share and the look rule cannot be loosened at all.
        relaxed = self.relaxed_clauses()
        if {"min_oracle_share", "rule"} & set(relaxed):
            raise ValueError(
                "routing.v2 refuses to relax min_oracle_share or the look rule under any name"
            )
        if self.version == POLICY_VERSION and relaxed:
            raise ValueError(
                f"a routing policy looser than the published rule cannot use version "
                f"{POLICY_VERSION!r}: relaxed {relaxed} — give it its own "
                "version string so every decision names the bar it cleared"
            )

    def relaxed_clauses(self) -> tuple[str, ...]:
        """The clauses on which this policy is LOOSER than the published defaults."""
        d = _PUBLISHED
        out: list[str] = []
        if self.min_oracle_strength < d["min_oracle_strength"]:
            out.append("min_oracle_strength")
        if self.min_oracle_share < d["min_oracle_share"]:
            out.append("min_oracle_share")
        if rule_spend(self.rule) > rule_spend(d["rule"]) + 1e-12:
            out.append("rule")
        if self.cell_error_budget > d["cell_error_budget"]:
            out.append("cell_error_budget")
        if self.min_controls_share < d["min_controls_share"]:
            out.append("min_controls_share")
        if self.max_controls_escapes > d["max_controls_escapes"]:
            out.append("max_controls_escapes")
        return tuple(out)

    def thresholds(self) -> dict[str, Any]:
        """The bar as numbers — stamped into every decision (``policy_thresholds``)."""
        return {
            "rule": self.rule,
            "looks": {str(n): m for n, m in sorted(rule_looks(self.rule).items())},
            "p_deliver_at_0_80": round(rule_spend(self.rule), 6),
            "cell_error_budget": self.cell_error_budget,
            "min_oracle_strength": self.min_oracle_strength,
            "min_oracle_share": self.min_oracle_share,
            "granularize_sizes": list(self.granularize_sizes),
            "min_controls_share": self.min_controls_share,
            "max_controls_escapes": self.max_controls_escapes,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.thresholds(),
            "version": self.version,
            "controls_version": self.controls_version,
            "description": self.describe(),
        }

    def describe(self) -> str:
        """The published bar as ONE sentence (ADR-0025 item 10, ADR-0026 item 6). README's
        "Not a licence to deploy" carries it between the ``routing-bar`` markers and
        ``scripts/claims_check.py --check`` fails on any byte of difference."""
        return (
            f"A cell routes `deliver` ({self.version}) only for its standard context arm, "
            "when a reading registered before its first attempt, over a frozen pool read in "
            "its seeded order, counts each distinct change once by its first observed attempt "
            f"at rung r1 in the sealed posture and finds {_looks_phrase(self.rule)} clean "
            f"(the look rule {self.rule}, read only at those looks); the reading's hierarchy "
            "is read richest arm first and stops at the first arm that does not deliver, `S3` "
            "alone is a ceiling that licenses nothing, only `S1@<author>` and `S2` certify, "
            "and `A0` is descriptive; every reading on a cell spends its rule's chance of "
            f"delivering at a true rate of 0.80 ({rule_spend(self.rule):.4f} for {self.rule}) "
            f"from one error budget of {self.cell_error_budget:.2f} per cell; and the cell "
            "also needs false-Q1 = 0, an oracle strength of at least "
            f"{self.min_oracle_strength:.2f} under `mutation.v2` measured on at least half of "
            "the commits the reading counted, and a complete negative-controls report at the "
            "same apparatus that passed, exercised at least half its controls and let no "
            "measurement control escape."
        )


#: The published bar, by number — what ``RoutingPolicy.relaxed_clauses`` compares against.
_PUBLISHED: dict[str, Any] = {
    "min_oracle_strength": 0.80,
    "min_oracle_share": 0.5,
    "rule": RULE_LOOK_V1,
    "cell_error_budget": CELL_ERROR_BUDGET,
    "min_controls_share": 0.5,
    "max_controls_escapes": 0,
}
DEFAULT_POLICY = RoutingPolicy()


@dataclass(frozen=True)
class RouteDecision:
    """One cell's route with the evidence it was decided on and the policy versions — enough
    for a reader to re-derive it from the ledger and the reading. ``n``, ``point``, ``ci_low``
    and ``ci_high`` are per attempt, for display; ``n_tasks``, ``task_clean`` and the task
    interval are per distinct change; the route reads the arm's reading (``look_state``,
    ``counted``, ``needed``) and every failing clause is on ``shortfalls``."""

    route: str
    reason: str
    cell: dict[str, str]
    n: int
    point: float
    ci_low: float
    false_q1: int
    oracle_strength: float | None
    policy_version: str
    #: The UPPER end of the same Wilson interval as ``ci_low`` — required, never defaulted.
    ci_high: float
    reason_code: str = ""
    controls: ControlsVerdict | None = None
    controls_policy: str = ""
    policy_thresholds: dict[str, Any] = field(default_factory=dict)
    # --- routing.v2 -----------------------------------------------------------------
    n_tasks: int = 0
    task_clean: int = 0
    task_ci_low: float = 0.0
    task_ci_high: float = 1.0
    basis: str = BASIS_FIRST_OBSERVED_ATTEMPT
    oracle_scored_tasks: int = 0
    oracle_share: float = 0.0
    shortfalls: tuple[Shortfall, ...] = ()
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

    def __post_init__(self) -> None:
        if self.reason_code and self.reason_code not in REASON_CODES:
            raise ValueError(f"reason_code {self.reason_code!r} not in {REASON_CODES}")
        object.__setattr__(self, "shortfalls", tuple(self.shortfalls))

    @property
    def task_point(self) -> float:
        return self.task_clean / self.n_tasks if self.n_tasks else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "cell": dict(self.cell),
            "n": self.n,
            "point": round(self.point, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "false_q1": self.false_q1,
            "oracle_strength": None
            if self.oracle_strength is None
            else round(self.oracle_strength, 4),
            "policy_version": self.policy_version,
            "policy_thresholds": dict(self.policy_thresholds),
            "controls_policy": self.controls_policy,
            "controls": None if self.controls is None else self.controls.to_dict(),
            "n_tasks": self.n_tasks,
            "task_clean": self.task_clean,
            "task_point": round(self.task_point, 4),
            "task_ci_low": round(self.task_ci_low, 4),
            "task_ci_high": round(self.task_ci_high, 4),
            "basis": self.basis,
            "oracle_scored_tasks": self.oracle_scored_tasks,
            "oracle_share": round(self.oracle_share, 4),
            "shortfalls": [s.to_dict() for s in self.shortfalls],
            "apparatus_version": self.apparatus_version,
            "context_arm": self.context_arm,
            "taxonomy": self.taxonomy,
            "reading_id": self.reading_id,
            "look_state": self.look_state,
            "counted": self.counted,
            "counted_clean": self.counted_clean,
            "needed": self.needed,
            "next_look": self.next_look,
            "standard": self.standard,
        }


def _controls_reason(prefix: str, c: ControlsVerdict, detail: str) -> str:
    """A controls reason names the run it came from, so the reader can open it."""
    run = f" (controls run {c.run_id[:8]})" if c.run_id else ""
    return f"{prefix}: {detail}{run}"


def is_arm_s2(arm: str) -> bool:
    """``True`` for an ``S2`` arm (a person's failing test, graded on held-out acceptance
    tests): the one arm the sealed-posture clause does not apply to (ADR-0026 item 6)."""
    try:
        return parse_arm(arm).base == BASE_S2
    except ValueError:
        return False


class _Clauses:
    """The failing clauses of one decision, in the order they were found."""

    def __init__(self) -> None:
        self.found: list[tuple[str, str, Shortfall]] = []

    def fail(
        self,
        code: str,
        route_: str,
        reason: str,
        *,
        observed: Any,
        threshold: Any,
        next_act: str,
        count: int = 0,
    ) -> None:
        shortfall = Shortfall(
            code, route_, observed, threshold, next_act, count, next_act in MODEL_MONEY_ACTS
        )
        self.found.append((route_, reason, shortfall))


def _reading_clause(out: _Clauses, arm: str, verdict: ArmVerdict) -> None:
    """Clause 5 (replacing routing.v1's ``n_below_min``): no registered reading, a descriptive
    arm, or a look still pending — with the commits still needed."""
    if verdict.state == VERDICT_UNREGISTERED:
        out.fail(
            REASON_READING_UNREGISTERED,
            ROUTE_CALIBRATE,
            f"no registered reading reads the arm {arm or '(unstamped)'} on this cell — a cell "
            "is licensed only by a reading registered before its first attempt",
            observed=None,
            threshold="registered",
            next_act=NEXT_REGISTER,
        )
    elif verdict.state == VERDICT_DESCRIPTIVE:
        out.fail(
            REASON_DESCRIPTIVE,
            ROUTE_CALIBRATE,
            f"{arm} is a descriptive arm (the ticket only): it is read for the north star and "
            "the loop's pair, and never licenses a delivery",
            observed=arm,
            threshold="S1@<author> or S2",
            next_act=NEXT_NONE,
        )
    elif verdict.state == VERDICT_LOOK_PENDING:
        waits = f" (the hierarchy waits on {verdict.blocking})" if verdict.blocking else ""
        out.fail(
            REASON_LOOK_PENDING,
            ROUTE_CALIBRATE,
            f"the reading waits for its look at {verdict.next_look}: {verdict.needed} commit(s) "
            f"still need a first attempt{waits}",
            observed=verdict.counted,
            threshold=verdict.next_look,
            next_act=NEXT_REPLAY if verdict.needed > 0 else NEXT_QUALIFY,
            count=verdict.needed,
        )


def _oracle_clause(out: _Clauses, ora: OracleEvidence, policy: RoutingPolicy) -> None:
    """Clauses 6 to 8: the oracle, measured under ``mutation.v2`` at this apparatus, on the
    commits the reading counted."""
    unscored = max(ora.n_tasks - ora.scored_tasks, 0)
    if not ora.measured or ora.strength is None:
        out.fail(
            REASON_ORACLE_UNMEASURED,
            ROUTE_CALIBRATE,
            "no counted commit has a mutation.v2 score at this apparatus — the oracle's "
            "strength is unknown, so a green here is not evidence; run an 'oracle' run",
            observed=None,
            threshold="measured",
            next_act=NEXT_ORACLE,
            count=unscored,
        )
    elif ora.share < policy.min_oracle_share:
        out.fail(
            REASON_ORACLE_THIN,
            ROUTE_CALIBRATE,
            f"only {ora.scored_tasks} of {ora.n_tasks} counted commits have an oracle score "
            f"({ora.share:.0%} < {policy.min_oracle_share:.0%}) — a mean over a minority "
            "describes those commits, not the cell",
            observed=round(ora.share, 4),
            threshold=policy.min_oracle_share,
            next_act=NEXT_ORACLE,
            count=unscored,
        )
    elif ora.strength < policy.min_oracle_strength:
        out.fail(
            REASON_ORACLE_WEAK,
            ROUTE_HUMAN,
            f"oracle strength {ora.strength:.2f} < {policy.min_oracle_strength:.2f} — green "
            "cannot license auto-delivery",
            observed=round(ora.strength, 4),
            threshold=policy.min_oracle_strength,
            next_act=NEXT_STRENGTHEN,
        )


def _decided_clauses(out: _Clauses, arm: str, verdict: ArmVerdict) -> None:
    """Clauses 10 and 11 (replacing ``point_below_bar`` and ``ci_low_below_bar``): the reading
    decided against, or delivered for an arm that is not the standard."""
    if verdict.state == VERDICT_INSUFFICIENT:
        by = f" (read on {verdict.blocking})" if verdict.blocking else ""
        out.fail(
            REASON_INSUFFICIENT,
            ROUTE_HUMAN,
            f"the reading read insufficient{by}: its third miss put its last look out of "
            "reach; it has spent its share of the cell's budget and is never read again — a "
            "richer arm in a new reading within the budget, a split, or a person",
            observed=verdict.counted - verdict.clean,
            threshold="fewer than three misses",
            next_act=NEXT_NEW_READING,
        )
    elif verdict.state == VERDICT_UNDECIDED:
        out.fail(
            REASON_UNDECIDED,
            ROUTE_CALIBRATE,
            f"the reading's pool ended before a look decided ({verdict.counted} read, the next "
            f"look is {verdict.next_look}) — mine further back, or leave the class to a person",
            observed=verdict.counted,
            threshold=verdict.next_look,
            next_act=NEXT_MINE,
            count=verdict.needed,
        )
    if verdict.state == VERDICT_CEILING:
        out.fail(
            REASON_CEILING,
            ROUTE_CALIBRATE,
            f"{arm} delivered, but its tests were written with the change: a ceiling, "
            "forward-unvalidated, never a certificate — calibration builds toward S2",
            observed=arm,
            threshold="S1@<author> or S2",
            next_act=NEXT_CALIBRATION_BUILDS,
        )
    elif verdict.state == VERDICT_LEANER:
        out.fail(
            REASON_LEANER_STANDARD,
            ROUTE_CALIBRATE,
            f"{arm} delivered, but the cell's standard is the leaner arm {verdict.standard}: "
            "a build carries the standard's context and nothing it was not measured with",
            observed=arm,
            threshold=verdict.standard,
            next_act=NEXT_BUILD_ON_STANDARD,
        )


def _controls_clauses(out: _Clauses, c: ControlsVerdict, policy: RoutingPolicy) -> None:
    """Clauses 12 and 13: the controls, measured and complete at this apparatus."""
    if not c.measured:
        out.fail(
            REASON_CONTROLS_UNMEASURED,
            ROUTE_CALIBRATE,
            f"{REASON_CONTROLS_UNMEASURED}: {c.detail or 'no negative-controls report'} — run a "
            "'controls' run before anything here can deliver",
            observed="unmeasured",
            threshold="measured",
            next_act=NEXT_CONTROLS,
        )
    elif c.passed and c.thin(policy.min_controls_share):
        out.fail(
            REASON_CONTROLS_THIN,
            ROUTE_CALIBRATE,
            _controls_reason(
                REASON_CONTROLS_THIN,
                c,
                f"only {c.constructible} of {c.total} control rows were constructible "
                f"({c.share:.0%} < {policy.min_controls_share:.0%}) — 'passed' means the easy "
                "controls passed; the load-bearing ones never ran",
            ),
            observed=round(c.share, 4),
            threshold=policy.min_controls_share,
            next_act=NEXT_CONTROLS,
        )


def route(
    stats: CellStats,
    *,
    oracle: OracleEvidence | None = None,
    controls: ControlsVerdict | None = None,
    reading: ArmVerdict | None = None,
    policy: RoutingPolicy = DEFAULT_POLICY,
) -> RouteDecision:
    """Evaluate ``routing.v2`` in the order ADR-0025 item 8 publishes it, as ADR-0026 item 6
    amends it; first match wins, and every failing clause is a shortfall.

    ``oracle=None`` is unmeasured; ``controls=None`` is unmeasured; ``reading=None`` is no
    registered reading for the cell's arm. The controls verdict is read at the cell's apparatus
    (:meth:`ControlsVerdict.at`)."""
    arm = stats.context_arm
    verdict = reading if reading is not None else ArmVerdict(arm, VERDICT_UNREGISTERED)
    c = (controls if controls is not None else ControlsVerdict.unmeasured()).at(
        stats.apparatus_version
    )
    ora = oracle if oracle is not None else OracleEvidence.unmeasured(verdict.counted)
    base: dict[str, Any] = {
        "cell": stats.cell.to_dict(),
        "n": stats.n,
        "point": stats.point,
        "ci_low": stats.ci.low,
        "ci_high": stats.ci.high,
        "false_q1": stats.false_q1,
        "oracle_strength": ora.strength if ora.measured else None,
        "policy_version": policy.version,
        "policy_thresholds": policy.thresholds(),
        "controls": c,
        "controls_policy": policy.controls_version,
        "n_tasks": stats.n_tasks,
        "task_clean": stats.task_clean,
        "task_ci_low": stats.task_ci.low,
        "task_ci_high": stats.task_ci.high,
        "oracle_scored_tasks": ora.scored_tasks,
        "oracle_share": ora.share,
        "apparatus_version": stats.apparatus_version,
        "context_arm": arm,
        "taxonomy": stats.taxonomy,
        "reading_id": verdict.reading_id,
        "look_state": verdict.state,
        "counted": verdict.counted,
        "counted_clean": verdict.clean,
        "needed": verdict.needed,
        "next_look": verdict.next_look,
        "standard": verdict.standard,
    }
    out = _Clauses()
    # 1 — the instrument's integrity comes first: a broken instrument never reads "calibrate"
    if stats.false_q1 > 0:
        out.fail(
            REASON_FALSE_Q1,
            ROUTE_DO_NOT_SHIP,
            f"{stats.false_q1} false-Q1 row(s) in cell — evidence untrusted",
            observed=stats.false_q1,
            threshold=0,
            next_act=NEXT_AUDIT,
        )
    # 2
    if stats.cell.size in policy.granularize_sizes:
        out.fail(
            REASON_GRANULARIZE,
            ROUTE_GRANULARIZE,
            f"size {stats.cell.size} is split before attempting",
            observed=stats.cell.size,
            threshold=list(policy.granularize_sizes),
            next_act=NEXT_SPLIT,
        )
    # 3 — a failed gate at this apparatus (an incomplete run that found a violation fails too)
    if c.measured and not c.passed:
        out.fail(
            REASON_CONTROLS_FAILED,
            ROUTE_HUMAN,
            _controls_reason(
                REASON_CONTROLS_FAILED,
                c,
                "the negative-controls gate FAILED on this repo — an instrument defect, "
                "nothing measured under it licenses autonomy",
            ),
            observed="failed",
            threshold="passed",
            next_act=NEXT_CONTROLS,
        )
    # 3a — the sealed posture (ADR-0025 as amended; ADR-0026 item 2): a replayed arm counts
    # only rows graded with the builder in its sealed container and the tests in the docker
    # sandbox's sealed mode; S2 reads ADR-0026 item 8's held-out rule instead
    if not is_arm_s2(arm) and stats.n_unsealed > 0:
        out.fail(
            REASON_POSTURE_UNSEALED,
            ROUTE_CALIBRATE,
            f"{stats.n_unsealed} of the cell's rows were not graded in the sealed posture (the "
            "builder in its sealed container, the tests in the docker sandbox's sealed mode) — "
            "in any other posture the target commit is reachable, so nothing here can deliver; "
            "read the sealed posture class, or measure there",
            observed=stats.n_unsealed,
            threshold=0,
            next_act=NEXT_SEAL,
        )
    # 4 — belt 5 switched off by configuration never helps a cell
    if stats.n_tasks_lint_disabled > 0 and verdict.state != VERDICT_DELIVER:
        out.fail(
            REASON_LINT_DISABLED,
            ROUTE_CALIBRATE,
            f"{stats.n_tasks_lint_disabled} commit(s) had their first attempt graded with belt 5 "
            "switched off by configuration — switch it back on and measure new commits",
            observed=stats.n_tasks_lint_disabled,
            threshold=0,
            next_act=NEXT_CONFIG,
        )
    _reading_clause(out, arm, verdict)  # 5
    _oracle_clause(out, ora, policy)  # 6-8
    # 9
    if c.measured and c.escapes > policy.max_controls_escapes:
        out.fail(
            REASON_CONTROLS_ESCAPES,
            ROUTE_HUMAN,
            _controls_reason(
                REASON_CONTROLS_ESCAPES,
                c,
                f"{c.escapes} measurement control(s) graded clean on this repo — the oracle "
                "cannot tell an implementation from a cheat; green cannot license "
                "auto-delivery until the oracle is hardened and re-measured",
            ),
            observed=c.escapes,
            threshold=policy.max_controls_escapes,
            next_act=NEXT_STRENGTHEN,
        )
    _decided_clauses(out, arm, verdict)  # 10-11
    _controls_clauses(out, c, policy)  # 12-13
    shortfalls = tuple(s for _, _, s in out.found)
    if out.found:
        route_, reason, first = out.found[0]
        return RouteDecision(route_, reason, reason_code=first.code, shortfalls=shortfalls, **base)
    strength = ora.strength if ora.strength is not None else 0.0
    return RouteDecision(
        ROUTE_DELIVER,
        f"{arm} is the cell's standard: {verdict.clean} of {verdict.counted} clean at the look "
        f"({policy.rule}, reading {verdict.reading_id[:12]}) · oracle={strength:.2f} on "
        f"{ora.scored_tasks}/{ora.n_tasks} · controls passed {c.constructible}/{c.total} "
        f"escapes={c.escapes} · false_q1=0",
        reason_code=REASON_DELIVER,
        **base,
    )


__all__ = [
    "BASIS_FIRST_OBSERVED_ATTEMPT",
    "CONTROLS_POLICY_VERSION",
    "CONTROLS_STATES",
    "DEFAULT_POLICY",
    "MODEL_MONEY_ACTS",
    "NEXT_ACTS",
    "POLICY_VERSION",
    "POLICY_VERSION_V1",
    "REASON_CODES",
    "REASON_CODES_V1",
    "REASON_CODES_V2",
    "ROUTES",
    "ControlsVerdict",
    "OracleEvidence",
    "RouteDecision",
    "RoutingPolicy",
    "Shortfall",
    "is_arm_s2",
    "route",
]
