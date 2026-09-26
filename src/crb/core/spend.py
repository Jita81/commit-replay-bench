"""Stop paying for nothing: a budget calibrated from the ledger, and escalation that pays.

Two measured leaks [measured — n = 322 valid rows of 618 in the operator's export of
2026-09-25, apparatus 2.0–2.2, builder ``claude_code`` / ``claude-sonnet-5``, method: the
product's failure rule, ``scripts/spend_from_export.py``]:

* **Budget stops.** 47 of 322 valid attempts ended ``budget`` — cut short by their own
  caps — and cost $28.87 of $120.21 for no output; 14 of them hit the 900 s wall clock.
  The caps were one global default, whatever the size of the change or the mode.
* **Escalation.** Every non-clean attempt climbed the ladder. The ladders in that export
  were bare rung labels (``r1, r2, r3``), which the worker resolves to the run's OWN
  builder and model at the SAME budget: a blind retry on a fresh worktree with the same
  brief and nothing learned from the failure. 40 valid r2/r3 attempts produced 2 clean
  ones (5%) for $20.70 — about $10.35 per clean patch, against $1.35 on r1 blind.

This module is the pure, stdlib half of the answer; the worker and the build adapter
apply it.

The calibrated budget (opt-in: ``budget_profile: "calibrated"``)
-------------------------------------------------------------------
For an attempt in a cell, :func:`calibrate` reads the ledger's own CLEAN completions (the
same builder and model; valid rows only) at the most specific level that has at least
:data:`CALIBRATION_MIN_CLEAN` of them — ``repo × mode × size``, then ``mode × size`` — and
sets each cap to the p90 of what those completions used × :data:`CALIBRATION_MARGIN`,
never below the run's own cap (the floor: today's default is never cut) and never above
:data:`CALIBRATION_CEILING` × the floor. Wall clock comes from ``latency_s``; turns from
the builder's recorded turns (the evidence pack's ``builder.turns``) when known — without
them the turn cap stays at the floor. A cell without enough clean rows keeps the floor and
the row says so. What the attempt ran under is recorded on the row (``budget_profile``,
``budget_calibration``, and ``budget_tier`` of the caps it actually had). The profile
changes what the builder is given, so it is OFF by default until a paired A/B measures it
[hypothesis: more room turns some budget stops into clean patches]
— per run (``POST /runs`` ``budget_profile``) or per repository (``spend.budget_profile``,
the surface the prevention loop writes); the run wins.

The measured escalation rule (default: ``escalation: "measured"``)
-------------------------------------------------------------------
Before a non-clean, non-disqualified attempt climbs to the next rung,
:func:`escalation_decision` reads the ledger's prior escalated attempts (trial ``r2`` or
later) made by that next rung's builder and model, at the most specific level with at
least :data:`ESCALATION_MIN_N` of them — ``repo × mode × size``, ``mode × size``, ``mode``.
When their clean yield is below :data:`ESCALATION_BAR` (10%: fewer than one clean patch
per ten paid retries) the task stops climbing; with too little data, or a yield at or over
the bar, it climbs as before. The decision, its level, ``clean/n`` and the bar are stamped
on the row that stopped or climbed (``escalation`` / ``escalation_rule``). Stopping
changes nothing a builder sees — it withholds a paid retry — so it is the default; a run
(``escalation: "always"``) or a repository (``spend.escalation``) opts back in.

Only prior data: both functions read the rows that exist when the run starts; a run's own
rows never feed its own decisions.

Navigation
----------
What it is:   The spend rules — the calibrated budget profile and the measured escalation
              rule, as pure functions over ledger rows, plus the per-run / per-repository
              policy they are switched by.
What it does: Computes per-cell caps from clean completions (p90 × margin, floored at the
              run's caps, ceilinged, with a minimum n) and decides whether a failed attempt
              climbs the ladder from the measured yield of prior escalations (a stated bar and
              minimum n); names every decision in row labels so old and new rows never mix.
How:          ``SpendObservation`` per row → ``calibrate`` (levels, nearest-rank p90) →
              ``Calibration.caps`` / ``labels``; ``escalation_decision`` (levels, yield vs
              bar) → ``EscalationDecision``; ``resolve_policy`` (run > repository > default).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/core/run.py (asks the escalation gate before a task climbs),
              src/crb/builders/adapter.py (``budget_for_task`` applies a calibration to an
              attempt), src/crb/server/worker.py (``spend_hooks`` builds both from the ledger
              at run start), src/crb/core/spec.py (``RepoConfig.spend``, the per-repository
              surface), src/crb/server/schemas.py (``budget_profile`` / ``escalation`` on
              ``POST /runs``), scripts/spend_from_export.py (the same functions over an export)
Tested by:    tests/test_spend.py, tests/test_worker_spend.py
Touch when:   a cap is added to ``Budget`` (add it to ``CAP_FIELDS`` and ``calibrate``); a bar
              or a minimum n changes (an apparatus-visible change: the rule is on every row —
              docs/API.md and docs/OPERATOR.md say the numbers).
Claims:       A calibrated cap is what clean completions USED, not what an attempt NEEDS:
              the slowest clean completions can still be cut short, and where the cap was
              binding (p90 at the cap) the data is censored. The benefit is a hypothesis
              until the paired A/B (docs/EVIDENCE-AND-CLAIMS.md); the escalation rule's
              in-sample saving on the export is a ceiling, not a prospective measurement.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # spec.py imports this module for RepoConfig.spend; ledger imports spec
    from crb.core.ledger import GradeRow

#: ``budget_profile`` values: ``default`` = the run's caps as declared; ``calibrated`` = caps
#: from the ledger's clean completions per cell (:func:`calibrate`).
PROFILE_DEFAULT = "default"
PROFILE_CALIBRATED = "calibrated"
BUDGET_PROFILES: tuple[str, ...] = (PROFILE_DEFAULT, PROFILE_CALIBRATED)
#: ``escalation`` values: ``measured`` = stop where prior escalations' yield is below the
#: bar (the default); ``always`` = climb every rung while the grade is not clean (the old rule).
ESCALATION_MEASURED = "measured"
ESCALATION_ALWAYS = "always"
ESCALATION_POLICIES: tuple[str, ...] = (ESCALATION_MEASURED, ESCALATION_ALWAYS)
DEFAULT_BUDGET_PROFILE = PROFILE_DEFAULT
DEFAULT_ESCALATION = ESCALATION_MEASURED

#: Calibration: clean completions a level needs before it sets caps.
CALIBRATION_MIN_CLEAN = 8
#: Calibration: the quantile of what clean completions used (nearest rank).
CALIBRATION_QUANTILE = 0.9
#: Calibration: headroom over that quantile.
CALIBRATION_MARGIN = 1.5
#: Calibration: a calibrated cap never exceeds this multiple of the run's own cap.
CALIBRATION_CEILING = 2.0

#: Escalation: prior escalated attempts a level needs before it can stop a climb.
ESCALATION_MIN_N = 10
#: Escalation: the clean yield below which a climb is withheld (1 in 10).
ESCALATION_BAR = 0.10

#: Row labels (``str → str``, hashed with the row).
LABEL_BUDGET_PROFILE = "budget_profile"
LABEL_BUDGET_CALIBRATION = "budget_calibration"
LABEL_ESCALATION = "escalation"
LABEL_ESCALATION_RULE = "escalation_rule"
#: ``escalation`` label values.
ESCALATION_CLIMBED = "climbed"
ESCALATION_STOPPED = "stopped"

#: The ``Budget`` caps a calibration may raise.
CAP_FIELDS: tuple[str, ...] = ("wall_clock_s", "max_turns", "max_tool_calls")

#: The per-repository surface (``RepoConfig.spend``): the keys it may carry.
SPEND_CONFIG_KEYS: tuple[str, ...] = ("budget_profile", "escalation")

#: Calibration levels, most specific first (each a tuple of observation fields).
CALIBRATION_LEVELS: tuple[tuple[str, ...], ...] = (("repo", "mode", "size"), ("mode", "size"))
#: Escalation levels, most specific first.
ESCALATION_LEVELS: tuple[tuple[str, ...], ...] = (
    ("repo", "mode", "size"),
    ("mode", "size"),
    ("mode",),
)


@dataclass(frozen=True)
class SpendObservation:
    """What the spend rules read from one ledger row. ``valid`` = the row observed the
    builder (not an outage, not a harness error, not disqualified, a judgeable gold);
    ``turns`` is ``None`` when the row's pack did not record them."""

    repo: str
    mode: str
    size: str
    builder: str
    model: str
    trial: str
    clean: bool
    valid: bool
    latency_s: float = 0.0
    cost_usd: float = 0.0
    turns: int | None = None

    @property
    def escalated(self) -> bool:
        """An attempt past the first rung (trial ``r2``, ``r3`` …)."""
        return is_escalated_trial(self.trial)


def observation_from_row(row: GradeRow, *, turns: int | None = None) -> SpendObservation:
    """The spend rules' view of a ledger row. ``valid`` follows the product's failure rule:
    a row that observed nothing (``outage``), was not judgeable (DQ, bad gold) or whose
    instrument failed (``harness``) is not an observation of what an attempt needs."""
    from crb.core.ledger import FAILURE_HARNESS  # noqa: PLC0415 — see the TYPE_CHECKING note

    return SpendObservation(
        repo=row.repo,
        mode=row.mode,
        size=row.size,
        builder=row.builder,
        model=row.model,
        trial=row.trial,
        clean=row.clean,
        valid=row.eligible and row.failure_kind != FAILURE_HARNESS,
        latency_s=float(row.latency_s or 0.0),
        cost_usd=float(row.cost_usd or 0.0),
        turns=turns,
    )


def is_escalated_trial(trial: str) -> bool:
    """``r2`` and later are escalations; ``r1`` (and anything unparseable) is not."""
    t = trial.strip().lower()
    if not t.startswith("r"):
        return False
    try:
        return int(t[1:]) >= 2
    except ValueError:
        return False


def quantile(values: Sequence[float], q: float) -> float:
    """Nearest-rank quantile (deterministic; no interpolation). ``values`` non-empty."""
    xs = sorted(values)
    rank = max(1, math.ceil(q * len(xs)))
    return float(xs[rank - 1])


def _match(o: SpendObservation, level: Sequence[str], want: Mapping[str, str]) -> bool:
    return all(getattr(o, f) == want[f] for f in level)


def _level_name(level: Sequence[str], want: Mapping[str, str]) -> str:
    return "+".join(level) + "=" + "|".join(want[f] for f in level)


# ---------------------------------------------------------------------------
# The calibrated budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Calibration:
    """The outcome of :func:`calibrate` for one attempt: the caps it runs under and why."""

    applied: bool
    caps: Mapping[str, int]
    level: str = ""
    n: int = 0
    p90_latency_s: float | None = None
    p90_turns: float | None = None
    reason: str = ""

    def labels(self) -> dict[str, str]:
        """``budget_profile`` + ``budget_calibration`` for the row."""
        if self.applied:
            parts = [self.level, f"n={self.n}", f"p90_s={_num(self.p90_latency_s)}"]
            parts.append(f"p90_turns={_num(self.p90_turns)}")
            text = ":".join(parts)
        else:
            text = f"floor:{self.reason}"
        return {LABEL_BUDGET_PROFILE: PROFILE_CALIBRATED, LABEL_BUDGET_CALIBRATION: text[:200]}


def _num(v: float | None) -> str:
    if v is None:
        return "unknown"
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def calibrate(
    observations: Iterable[SpendObservation],
    *,
    repo: str,
    mode: str,
    size: str,
    builder: str,
    model: str,
    floor: Mapping[str, int],
    min_clean: int = CALIBRATION_MIN_CLEAN,
    q: float = CALIBRATION_QUANTILE,
    margin: float = CALIBRATION_MARGIN,
    ceiling: float = CALIBRATION_CEILING,
) -> Calibration:
    """The caps for an attempt in ``(repo, mode, size)`` by ``builder:model``.

    ``floor`` is the attempt's own caps (``wall_clock_s``, ``max_turns``,
    ``max_tool_calls``); a calibrated cap is ``clamp(ceil(p90 × margin), floor, floor ×
    ceiling)``. The tool-call cap scales by the same factor as the turn cap (the rows
    record turns, not tool calls). A level with fewer than ``min_clean`` clean valid
    completions is skipped; when none qualifies the floor stands and the reason says so."""
    base = {k: int(floor[k]) for k in CAP_FIELDS}
    for k, v in base.items():
        if v <= 0:
            # a zero cap divides the tool-call factor by zero and clamps every calibrated
            # cap to 0 (floor × ceiling): refused here, where the cause can be named
            raise ValueError(f"calibration floor {k}={v}: every cap of the floor must be > 0")
    want = {"repo": repo, "mode": mode, "size": size}
    pool = [
        o for o in observations if o.valid and o.clean and o.builder == builder and o.model == model
    ]
    for level in CALIBRATION_LEVELS:
        rows = [o for o in pool if _match(o, level, want)]
        if len(rows) < min_clean:
            continue
        p90_s = quantile([o.latency_s for o in rows], q)
        turns = [float(o.turns) for o in rows if o.turns is not None and o.turns > 0]
        p90_t = quantile(turns, q) if len(turns) >= min_clean else None
        caps = dict(base)
        caps["wall_clock_s"] = _clamp(p90_s * margin, base["wall_clock_s"], ceiling)
        if p90_t is not None:
            caps["max_turns"] = _clamp(p90_t * margin, base["max_turns"], ceiling)
            factor = caps["max_turns"] / base["max_turns"]
            caps["max_tool_calls"] = _clamp(
                base["max_tool_calls"] * factor, base["max_tool_calls"], ceiling
            )
        return Calibration(
            applied=True,
            caps=caps,
            level=_level_name(level, want),
            n=len(rows),
            p90_latency_s=p90_s,
            p90_turns=p90_t,
        )
    best = max(
        (sum(1 for o in pool if _match(o, lv, want)) for lv in CALIBRATION_LEVELS), default=0
    )
    return Calibration(
        applied=False,
        caps=base,
        n=best,
        reason=f"n={best}<{min_clean} clean completions for {mode}|{size}",
    )


def _clamp(value: float, floor: int, ceiling: float) -> int:
    return int(min(max(math.ceil(value), floor), math.floor(floor * ceiling)))


# ---------------------------------------------------------------------------
# The measured escalation rule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationDecision:
    """Whether a failed attempt climbs to the next rung, and the labels that say why."""

    climb: bool
    labels: Mapping[str, str] = field(default_factory=dict)


#: ``gate(task_size, next_rung_index) -> decision`` as :class:`crb.core.run.RunSpec`
#: carries it; the worker binds the repo, mode and the ladder's rungs.
EscalationGate = Callable[[str, int], EscalationDecision]


def escalation_yield(
    observations: Iterable[SpendObservation],
    *,
    repo: str,
    mode: str,
    size: str,
    builder: str,
    model: str,
    min_n: int = ESCALATION_MIN_N,
) -> tuple[str, int, int]:
    """``(level, n, clean)`` of prior valid escalated attempts by ``builder:model`` at the
    most specific level with at least ``min_n`` of them; ``("", best_n, clean)`` when none
    qualifies."""
    want = {"repo": repo, "mode": mode, "size": size}
    pool = [
        o
        for o in observations
        if o.valid and o.escalated and o.builder == builder and o.model == model
    ]
    best: tuple[int, int] = (0, 0)
    for level in ESCALATION_LEVELS:
        rows = [o for o in pool if _match(o, level, want)]
        clean = sum(1 for o in rows if o.clean)
        if len(rows) >= min_n:
            return _level_name(level, want), len(rows), clean
        if len(rows) > best[0]:
            best = (len(rows), clean)
    return "", best[0], best[1]


def escalation_decision(
    observations: Iterable[SpendObservation],
    *,
    policy: str,
    repo: str,
    mode: str,
    size: str,
    builder: str,
    model: str,
    bar: float = ESCALATION_BAR,
    min_n: int = ESCALATION_MIN_N,
) -> EscalationDecision:
    """THE rule for one climb (module docstring). ``always`` climbs and says so."""
    if policy == ESCALATION_ALWAYS:
        return EscalationDecision(
            True, {LABEL_ESCALATION: ESCALATION_CLIMBED, LABEL_ESCALATION_RULE: "always"}
        )
    level, n, clean = escalation_yield(
        observations, repo=repo, mode=mode, size=size, builder=builder, model=model, min_n=min_n
    )
    if not level:
        rule = f"measured:insufficient:n={n}<{min_n}:bar={bar:.2f}"
        return EscalationDecision(
            True, {LABEL_ESCALATION: ESCALATION_CLIMBED, LABEL_ESCALATION_RULE: rule}
        )
    yield_ = clean / n
    climb = yield_ >= bar
    op = ">=" if climb else "<"
    rule = f"measured:{level}:yield={clean}/{n}{op}{bar:.2f}"
    return EscalationDecision(
        climb,
        {
            LABEL_ESCALATION: ESCALATION_CLIMBED if climb else ESCALATION_STOPPED,
            LABEL_ESCALATION_RULE: rule[:200],
        },
    )


# ---------------------------------------------------------------------------
# The policy: run > repository > default
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpendPolicy:
    """The spend switches one run runs under, and where each came from
    (``run`` | ``repository`` | ``default``) — stamped into the run's apparatus."""

    budget_profile: str = DEFAULT_BUDGET_PROFILE
    escalation: str = DEFAULT_ESCALATION
    sources: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_profile": self.budget_profile,
            "escalation": self.escalation,
            "sources": dict(self.sources),
        }


def validate_spend_config(config: Mapping[str, Any]) -> dict[str, str]:
    """The per-repository surface's shape: only :data:`SPEND_CONFIG_KEYS`, each one of its
    allowed values. Raises ``ValueError`` naming the offending key."""
    out: dict[str, str] = {}
    for key, value in dict(config or {}).items():
        if key not in SPEND_CONFIG_KEYS:
            raise ValueError(f"spend.{key} is not a spend setting (one of {SPEND_CONFIG_KEYS})")
        allowed = BUDGET_PROFILES if key == "budget_profile" else ESCALATION_POLICIES
        if value not in allowed:
            raise ValueError(f"spend.{key} must be one of {allowed}, got {value!r}")
        out[key] = str(value)
    return out


def resolve_policy(params: Mapping[str, Any], repo_spend: Mapping[str, Any]) -> SpendPolicy:
    """Run parameter > repository configuration > default, per switch."""
    repo_cfg = validate_spend_config(repo_spend)
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    defaults = {"budget_profile": DEFAULT_BUDGET_PROFILE, "escalation": DEFAULT_ESCALATION}
    for key in SPEND_CONFIG_KEYS:
        run_value = params.get(key)
        if run_value:
            values[key] = str(validate_spend_config({key: run_value})[key])
            sources[key] = "run"
        elif key in repo_cfg:
            values[key] = repo_cfg[key]
            sources[key] = "repository"
        else:
            values[key] = defaults[key]
            sources[key] = "default"
    return SpendPolicy(values["budget_profile"], values["escalation"], sources)


__all__ = [
    "BUDGET_PROFILES",
    "CALIBRATION_CEILING",
    "CALIBRATION_LEVELS",
    "CALIBRATION_MARGIN",
    "CALIBRATION_MIN_CLEAN",
    "CALIBRATION_QUANTILE",
    "CAP_FIELDS",
    "DEFAULT_BUDGET_PROFILE",
    "DEFAULT_ESCALATION",
    "ESCALATION_ALWAYS",
    "ESCALATION_BAR",
    "ESCALATION_CLIMBED",
    "ESCALATION_LEVELS",
    "ESCALATION_MEASURED",
    "ESCALATION_MIN_N",
    "ESCALATION_POLICIES",
    "ESCALATION_STOPPED",
    "LABEL_BUDGET_CALIBRATION",
    "LABEL_BUDGET_PROFILE",
    "LABEL_ESCALATION",
    "LABEL_ESCALATION_RULE",
    "PROFILE_CALIBRATED",
    "PROFILE_DEFAULT",
    "SPEND_CONFIG_KEYS",
    "Calibration",
    "EscalationDecision",
    "EscalationGate",
    "SpendObservation",
    "SpendPolicy",
    "calibrate",
    "escalation_decision",
    "escalation_yield",
    "is_escalated_trial",
    "observation_from_row",
    "quantile",
    "resolve_policy",
    "validate_spend_config",
]
