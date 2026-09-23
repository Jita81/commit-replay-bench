"""The ONE routing rule (ADR-0003, amended 2026-09-13 with the controls gate).

Given a cell's measured statistics, the oracle strength of its tasks (when
measured) and the repo's negative-controls verdict (when evaluated), decide what
the factory may do with that class of change:

* ``deliver``      — auto-deliver as a branch + PR: n ≥ 10 ∧ point ≥ 0.90 ∧
  Wilson-lower ≥ 0.80 ∧ false-Q1 = 0 ∧ (oracle strength ≥ 0.80 when measured)
  ∧ (the controls gate PASSED, a majority of its controls were actually
  exercised and no measurement control escaped — when a verdict is evaluated).
* ``do_not_ship``  — any false-Q1 in the cell: the evidence is untrusted until
  audited. (Structurally impossible with the write-time invariant; kept as the
  read-time re-check.)
* ``human``        — green cannot license auto-delivery: the oracle is too weak
  (strength < 0.80 when measured), the negative-controls gate FAILED on this
  repo (an instrument defect — belt 3 blind, a guard broken …), or a
  measurement control ESCAPED (a deterministic cheat graded clean, so the
  oracle demonstrably cannot tell an implementation from a lookup table).
* ``granularize``  — XL changes are split before they are attempted.
* ``calibrate``    — not enough evidence, the point/interval is below the bar,
  the controls were never run (``controls_unmeasured``) or fewer than half of
  them could be constructed for this repo (``controls_thin`` — "passed" then
  means "the easy ones passed").

The rule is deliberately the *published* one (the essay's "≥90% point and ≥80%
lower bound on enough samples"). The SPC variant (σ ≤ 0.10, n ≥ 20) that also
existed upstream is reported as an advisory signal, not a gate.

Two clause sets, two versions. The numeric clauses are ``routing.v1``,
unchanged. The controls clauses are ``controls-gate.v1`` and apply only when the
caller hands :func:`route` a :class:`ControlsVerdict` — the server's capability
map always does (fail-closed: it passes :meth:`ControlsVerdict.unmeasured` when
the repo has no controls report); a caller that evaluates none (a JSONL ledger
on the CLI, a unit test) gets a decision stamped ``controls_policy=""`` and
``controls=None`` so the absence is visible, never mistaken for a pass.

Navigation
----------
What it is:   The routing rule — ``route``, the one function that turns a measured cell into
              ``deliver`` / ``calibrate`` / ``granularize`` / ``human`` / ``do_not_ship``
              with a reason and a reason code.
What it does: Applies the published thresholds (``RoutingPolicy``: n, point, Wilson lower
              bound, oracle strength) and the negative-controls gate (``ControlsVerdict``) in
              a fixed order, first match wins; refuses ``deliver`` on any false-Q1, on an
              unmeasured or thin controls report, and on an escaped measurement control.
              Pure: reads statistics, never rows or a model.
How:          false-Q1 → granularize by size → controls failed → n → oracle strength →
              controls escapes → point → CI lower → controls unmeasured → controls thin →
              deliver; every branch returns a ``RouteDecision`` stamped with the policy
              versions that produced it.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0010-polyglot-negative-controls.md
Works with:   src/crb/core/ledger.py (CellStats — the input), src/crb/core/capability.py (the
              map that routes every cell), src/crb/core/oracle/controls.py (the report a
              ControlsVerdict reduces), src/crb/core/oracle/adequacy.py (oracle strength),
              src/crb/core/signoff.py (a signed cell must still route ``deliver``),
              src/crb/server/routes/capability.py (serves decisions; passes ``unmeasured``
              when no report exists), src/crb/cli/commands/route.py (``crb route``)
Tested by:    tests/test_routing.py, tests/test_capability.py, tests/test_signoff.py,
              tests/test_server_routes_capability.py
Touch when:   never for a new repository (the rule is the same for every cell; run a
              ``controls`` run so the gate is measured); changing a threshold, adding a
              clause or a reason code changes what ``deliver`` means — bump
              ``POLICY_VERSION`` / ``CONTROLS_POLICY_VERSION``, write an ADR superseding
              docs/adr/0003-one-routing-rule.md, and update
              docs/EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity and the UI's
              reason-code copy.
Claims:       ``deliver`` licenses auto-delivery as a branch + PR under review, not
              mergeability (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from crb.core.ledger import CellStats

#: Stamped on every decision. A decision made under an older version is not comparable
#: with one made under a newer one; bump on any change to a clause or a threshold.
POLICY_VERSION = "routing.v1"
CONTROLS_POLICY_VERSION = "controls-gate.v1"

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
# A code is the machine-readable half of a decision (the UI keys copy and pills on
# it; the learning loop groups on it); ``reason`` is the human sentence.
REASON_FALSE_Q1 = "false_q1"
REASON_GRANULARIZE = "granularize"
REASON_CONTROLS_FAILED = "controls_failed"
REASON_N_BELOW_MIN = "n_below_min"
REASON_ORACLE_WEAK = "oracle_weak"
REASON_CONTROLS_ESCAPES = "controls_escapes"
REASON_POINT_BELOW_BAR = "point_below_bar"
REASON_CI_LOW_BELOW_BAR = "ci_low_below_bar"
REASON_CONTROLS_UNMEASURED = "controls_unmeasured"
REASON_CONTROLS_THIN = "controls_thin"
REASON_DELIVER = "deliver"
REASON_CODES: tuple[str, ...] = (
    REASON_FALSE_Q1,
    REASON_GRANULARIZE,
    REASON_CONTROLS_FAILED,
    REASON_N_BELOW_MIN,
    REASON_ORACLE_WEAK,
    REASON_CONTROLS_ESCAPES,
    REASON_POINT_BELOW_BAR,
    REASON_CI_LOW_BELOW_BAR,
    REASON_CONTROLS_UNMEASURED,
    REASON_CONTROLS_THIN,
    REASON_DELIVER,
)

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
    """The negative-controls gate of ONE repo, reduced to what routing needs.

    ``passed`` is the gate (no VIOLATION — see :class:`crb.core.oracle.controls.
    ControlsReport`). ``total`` counts the control rows that had a RED oracle to
    exercise (``rows − skipped``); ``constructible`` those that were actually
    built and graded (``total − not_constructible``) — on a Go or JS repo where
    only ``gold``/``noop``/``test_tamper`` are constructible that is 3 of every
    7. ``escapes`` counts measurement controls (``hardcode_cheat``,
    ``env_poison``) that graded CLEAN. ``measured`` is ``False`` only for the
    sentinel :meth:`unmeasured` (no report exists); ``complete`` is ``False``
    when the run that produced the report was cancelled part-way.
    """

    passed: bool
    constructible: int
    total: int
    escapes: int
    run_id: str = ""
    created: str = ""
    complete: bool = True
    measured: bool = True

    def __post_init__(self) -> None:
        if self.constructible < 0 or self.total < 0 or self.escapes < 0:
            raise ValueError("controls counts cannot be negative")
        if self.constructible > self.total:
            raise ValueError("constructible cannot exceed total")

    @classmethod
    def unmeasured(cls) -> ControlsVerdict:
        """The honest absence: no controls report for the repo."""
        return cls(passed=False, constructible=0, total=0, escapes=0, measured=False)

    @classmethod
    def from_counts(
        cls, counts: Mapping[str, Any], *, run_id: str = "", created: str = ""
    ) -> ControlsVerdict:
        """From a worker ``controls`` run's ``counts_json`` (``{tasks, total, rows,
        violations, escapes, not_constructible, skipped, passed, complete}``) or a
        ``controls.report`` event payload (``ControlsReport.to_dict()``:
        ``n_rows`` for ``rows``, ``apparatus.complete`` for ``complete``)."""

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
        return cls(
            passed=bool(counts.get("passed", False)),
            constructible=max(0, min(total, total - not_constructible)),
            total=total,
            escapes=_int("escapes"),
            run_id=run_id or str(counts.get("run_id", "") or ""),
            created=created or str(counts.get("reported_at", "") or ""),
            complete=True if complete is None else bool(complete),
        )

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
        }


@dataclass(frozen=True)
class RoutingPolicy:
    """The thresholds of the rule. The defaults ARE the published rule (ADR-0003);
    a caller may tighten them for a deployment, and the ``version`` fields travel
    with every decision so a relaxed policy can never pass as the standard one."""

    min_n: int = 10
    min_point: float = 0.90
    min_ci_low: float = 0.80
    min_oracle_strength: float = 0.80
    granularize_sizes: tuple[str, ...] = ("XL",)
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
        # A policy that is LOOSER than the published one on any clause cannot travel under
        # the published version string: every decision it produces would read as
        # ``routing.v1`` while clearing a lower bar. Tightening is allowed (the same name
        # is honest — the rule holds and more); loosening needs its own version name.
        # Mirrors ``SignoffPolicy.relaxed`` (external review 2026-09-16, point 9).
        if self.version == POLICY_VERSION and self.relaxed_clauses():
            raise ValueError(
                f"a routing policy looser than the published rule cannot use version "
                f"{POLICY_VERSION!r}: relaxed {self.relaxed_clauses()} — give it its own "
                "version string so every decision names the bar it cleared"
            )

    def relaxed_clauses(self) -> tuple[str, ...]:
        """The clauses on which this policy is LOOSER than the published defaults."""
        d = _PUBLISHED
        out: list[str] = []
        if self.min_n < d["min_n"]:
            out.append("min_n")
        if self.min_point < d["min_point"]:
            out.append("min_point")
        if self.min_ci_low < d["min_ci_low"]:
            out.append("min_ci_low")
        if self.min_oracle_strength < d["min_oracle_strength"]:
            out.append("min_oracle_strength")
        if self.min_controls_share < d["min_controls_share"]:
            out.append("min_controls_share")
        if self.max_controls_escapes > d["max_controls_escapes"]:
            out.append("max_controls_escapes")
        return tuple(out)

    def thresholds(self) -> dict[str, Any]:
        """The bar as numbers — stamped into every decision (``policy_thresholds``)."""
        return {
            "min_n": self.min_n,
            "min_point": self.min_point,
            "min_ci_low": self.min_ci_low,
            "min_oracle_strength": self.min_oracle_strength,
            "granularize_sizes": list(self.granularize_sizes),
            "min_controls_share": self.min_controls_share,
            "max_controls_escapes": self.max_controls_escapes,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_n": self.min_n,
            "min_point": self.min_point,
            "min_ci_low": self.min_ci_low,
            "min_oracle_strength": self.min_oracle_strength,
            "granularize_sizes": list(self.granularize_sizes),
            "version": self.version,
            "min_controls_share": self.min_controls_share,
            "max_controls_escapes": self.max_controls_escapes,
            "controls_version": self.controls_version,
        }


#: The published bar, by number — what ``RoutingPolicy.relaxed_clauses`` compares against.
_PUBLISHED: dict[str, Any] = {
    "min_n": 10,
    "min_point": 0.90,
    "min_ci_low": 0.80,
    "min_oracle_strength": 0.80,
    "min_controls_share": 0.5,
    "max_controls_escapes": 0,
}
DEFAULT_POLICY = RoutingPolicy()


@dataclass(frozen=True)
class RouteDecision:
    """One cell's route with the evidence it was decided on (``n``, ``point``, the whole
    Wilson interval as ``ci_low`` and ``ci_high``, ``false_q1``, ``oracle_strength``, the
    controls verdict) and the policy versions — enough for a reader to re-derive it from the
    ledger, and enough for any reader of a decision to quote the interval as a range."""

    route: str
    reason: str
    cell: dict[str, str]
    n: int
    point: float
    ci_low: float
    false_q1: int
    oracle_strength: float | None
    policy_version: str
    #: The UPPER end of the same Wilson interval as ``ci_low``. The rule never reads it —
    #: the bar is on the lower bound — but every reader quotes the interval as a range, and
    #: a decision that carried only one end made the comment on a customer's ticket say
    #: "67 % to unknown" wherever it was rendered from a decision rather than from the
    #: capability map's row. REQUIRED, and deliberately: it carried ``1.0`` (the Wilson
    #: upper bound of no data) as a default, so a caller that measured ``ci_low`` and forgot
    #: this one serialised a made-up upper bound beside a measured lower one. A decision
    #: with no data says so by passing ``1.0`` itself.
    ci_high: float
    reason_code: str = ""
    controls: ControlsVerdict | None = None
    controls_policy: str = ""
    #: The bar this decision cleared or failed, as numbers — a reader never has to look
    #: the version up, and a tightened deployment policy is visible on every decision.
    policy_thresholds: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason_code and self.reason_code not in REASON_CODES:
            raise ValueError(f"reason_code {self.reason_code!r} not in {REASON_CODES}")

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
        }


def _controls_reason(prefix: str, c: ControlsVerdict, detail: str) -> str:
    """A controls reason names the run it came from, so the reader can open it."""
    run = f" (controls run {c.run_id[:8]})" if c.run_id else ""
    return f"{prefix}: {detail}{run}"


def route(
    stats: CellStats,
    *,
    oracle_strength: float | None = None,
    controls: ControlsVerdict | None = None,
    policy: RoutingPolicy = DEFAULT_POLICY,
) -> RouteDecision:
    """Evaluate the rule in the order ADR-0003 publishes it; first match wins.

    ``controls=None`` means the caller evaluated no verdict: the controls clauses
    do not apply and the decision says so (``controls_policy=""``). Pass
    :meth:`ControlsVerdict.unmeasured` to say "we looked and there is none" — the
    fail-closed reading the server's capability map uses.
    """
    # an explicit strength (the adequacy gate's) outranks the mean the rows carry
    strength = oracle_strength if oracle_strength is not None else stats.oracle_strength_mean
    base: dict[str, Any] = {
        "cell": stats.cell.to_dict(),
        "n": stats.n,
        "point": stats.point,
        "ci_low": stats.ci.low,
        "ci_high": stats.ci.high,
        "false_q1": stats.false_q1,
        "oracle_strength": strength,
        "policy_version": policy.version,
        "policy_thresholds": policy.thresholds(),
        "controls": controls,
        "controls_policy": policy.controls_version if controls is not None else "",
    }
    measured_controls = controls is not None and controls.measured
    # the order below is the ADR's: instrument defects (false-Q1, a failed gate) are
    # named before sample size, so a broken instrument never reads as "calibrate"
    if stats.false_q1 > 0:
        return RouteDecision(
            ROUTE_DO_NOT_SHIP,
            f"{stats.false_q1} false-Q1 row(s) in cell — evidence untrusted",
            reason_code=REASON_FALSE_Q1,
            **base,
        )
    if stats.cell.size in policy.granularize_sizes:
        return RouteDecision(
            ROUTE_GRANULARIZE,
            f"size {stats.cell.size} is split before attempting",
            reason_code=REASON_GRANULARIZE,
            **base,
        )
    if controls is not None and measured_controls and not controls.passed:
        return RouteDecision(
            ROUTE_HUMAN,
            _controls_reason(
                REASON_CONTROLS_FAILED,
                controls,
                "the negative-controls gate FAILED on this repo — an instrument defect, "
                "nothing measured under it licenses autonomy",
            ),
            reason_code=REASON_CONTROLS_FAILED,
            **base,
        )
    if stats.n < policy.min_n:
        return RouteDecision(
            ROUTE_CALIBRATE,
            f"n={stats.n} < {policy.min_n}",
            reason_code=REASON_N_BELOW_MIN,
            **base,
        )
    if strength is not None and strength < policy.min_oracle_strength:
        return RouteDecision(
            ROUTE_HUMAN,
            f"oracle strength {strength:.2f} < {policy.min_oracle_strength:.2f} — green cannot license auto-delivery",
            reason_code=REASON_ORACLE_WEAK,
            **base,
        )
    if (
        controls is not None
        and measured_controls
        and controls.escapes > policy.max_controls_escapes
    ):
        return RouteDecision(
            ROUTE_HUMAN,
            _controls_reason(
                REASON_CONTROLS_ESCAPES,
                controls,
                f"{controls.escapes} measurement control(s) graded clean on this repo — "
                "the oracle cannot tell an implementation from a cheat; green cannot license "
                "auto-delivery until the oracle is hardened and re-measured",
            ),
            reason_code=REASON_CONTROLS_ESCAPES,
            **base,
        )
    if stats.point < policy.min_point:
        return RouteDecision(
            ROUTE_CALIBRATE,
            f"point {stats.point:.3f} < {policy.min_point:.2f}",
            reason_code=REASON_POINT_BELOW_BAR,
            **base,
        )
    if stats.ci.low < policy.min_ci_low:
        return RouteDecision(
            ROUTE_CALIBRATE,
            f"Wilson lower {stats.ci.low:.3f} < {policy.min_ci_low:.2f} (point ok, interval too wide)",
            reason_code=REASON_CI_LOW_BELOW_BAR,
            **base,
        )
    if controls is not None and not measured_controls:
        return RouteDecision(
            ROUTE_CALIBRATE,
            f"{REASON_CONTROLS_UNMEASURED}: no negative-controls report for this repo — "
            "run a 'controls' run before anything here can deliver",
            reason_code=REASON_CONTROLS_UNMEASURED,
            **base,
        )
    if controls is not None and controls.thin(policy.min_controls_share):
        return RouteDecision(
            ROUTE_CALIBRATE,
            _controls_reason(
                REASON_CONTROLS_THIN,
                controls,
                f"only {controls.constructible} of {controls.total} control rows were "
                f"constructible ({controls.share:.0%} < {policy.min_controls_share:.0%}) — "
                "'passed' means the easy controls passed; the load-bearing ones never ran",
            ),
            reason_code=REASON_CONTROLS_THIN,
            **base,
        )
    tail = "" if strength is None else f" oracle={strength:.2f}"
    if controls is not None:
        tail += (
            f" controls=passed {controls.constructible}/{controls.total} escapes={controls.escapes}"
        )
    return RouteDecision(
        ROUTE_DELIVER,
        f"n={stats.n} point={stats.point:.3f} ci_low={stats.ci.low:.3f} false_q1=0" + tail,
        reason_code=REASON_DELIVER,
        **base,
    )
