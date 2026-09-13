"""Ex-ante build forecast and the readiness gate — price a mix before building it.

A piece of work is a *composition of component classes the ledger has already
measured*: ``{"bug.fix/S": 4, "backend.route.add/M": 2, "docs.update": 1}``.
Given that mix and the grade rows, :func:`forecast_build` says — before any
model is called — what it would cost (μ ± σ), how long it would take, how many
units the ONE routing rule would auto-deliver / hand to a human / send to
calibration, and the expected clean rate with its deviation band.
:func:`assess_readiness` turns the same resolution into a deterministic
punch-list against a frozen :class:`ReadinessThresholds`.

Honest by construction
----------------------
* A component the ledger has never measured is listed in ``unmeasured`` and
  contributes nothing to any total — no number is fabricated for it.
* Cost and time totals are over the units that carry the axis; the counts of
  costed / timed units are reported next to them.
* The per-unit clean probability is the routed cell's point estimate (the
  chosen config's cell when the component is deliverable); its band is the
  Bernoulli propagation over the units, and the cell's ``n`` travels with it.
* Readiness never relaxes a gate: false-Q1 = 0 is checked explicitly even
  though the routing rule already refuses such cells.

Pure aggregation over :mod:`crb.core.capability`; no I/O, no model calls.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from crb.core.capability import (
    CELL_STATES,
    NOT_YET_MEASURED,
    PROJECTION_CLASS,
    PROJECTION_CLASS_SIZE,
    WILDCARD,
    CapabilityCell,
    ConfigPick,
    best_config,
    build_capability_map,
)
from crb.core.ledger import GradeRow, group_by_cell
from crb.core.routing import (
    DEFAULT_POLICY,
    ROUTE_CALIBRATE,
    ROUTE_DELIVER,
    ROUTE_HUMAN,
    RoutingPolicy,
)
from crb.core.signoff import SignoffRecord, apply_signoffs_to_map
from crb.core.spec import SIZE_TIER_NAMES
from crb.core.stats import mean, stddev

ComponentKey = str | tuple[str, str]


def parse_component_key(key: ComponentKey) -> tuple[str, str]:
    """``"bug.fix/S"`` or ``("bug.fix", "S")`` → ``("bug.fix", "S")``; a bare class → size ``""``.

    An unknown size tier is an input mistake and is refused, not silently
    reported as unmeasured.
    """
    if isinstance(key, tuple):
        cls, size = key
    elif "/" in key:
        cls, size = key.rsplit("/", 1)
    else:
        cls, size = key, ""
    cls, size = cls.strip(), size.strip()
    if not cls:
        raise ValueError(f"component key {key!r} has no capability class")
    if size and size not in SIZE_TIER_NAMES:
        raise ValueError(f"component key {key!r}: size {size!r} not in {SIZE_TIER_NAMES}")
    return cls, size


def component_label(cls: str, size: str) -> str:
    return f"{cls}/{size}" if size else cls


# ---------------------------------------------------------------------------
# Resolution (shared by the forecast and the readiness gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Axis:
    cost_mean: float | None
    cost_sigma: float | None
    latency_mean: float | None


def _axis(rows: Sequence[GradeRow]) -> _Axis:
    costs = [r.cost_usd for r in rows if r.eligible and r.cost_usd > 0]
    lats = [r.latency_s for r in rows if r.eligible and r.latency_s > 0]
    return _Axis(
        cost_mean=mean(costs) if costs else None,
        cost_sigma=stddev(costs) if costs else None,
        latency_mean=mean(lats) if lats else None,
    )


@dataclass(frozen=True)
class _Resolved:
    cls: str
    size: str
    count: int
    cell: CapabilityCell
    pick: ConfigPick | None
    axis: _Axis

    @property
    def label(self) -> str:
        return component_label(self.cls, self.size)

    @property
    def deliverable(self) -> bool:
        return self.cell.route == ROUTE_DELIVER and self.pick is not None

    @property
    def p_clean(self) -> float | None:
        if self.pick is not None:
            return self.pick.cell.point
        return self.cell.point


def _resolve(
    component_mix: Mapping[ComponentKey, int],
    rows: Iterable[GradeRow],
    *,
    policy: RoutingPolicy,
    signoffs: Iterable[SignoffRecord] | None,
    repo: str,
    language: str | None,
) -> list[_Resolved]:
    rs = list(rows)
    cs_map = build_capability_map(rs, projection=PROJECTION_CLASS_SIZE, policy=policy)
    c_map = build_capability_map(rs, projection=PROJECTION_CLASS, policy=policy)
    if signoffs is not None:
        sign = list(signoffs)
        cs_map = apply_signoffs_to_map(cs_map, sign, repo=repo)
        c_map = apply_signoffs_to_map(c_map, sign, repo=repo)
    groups: dict[tuple[str, ...], dict[tuple[str, ...], list[GradeRow]]] = {}

    def rows_for(projection: tuple[str, ...], key: tuple[str, ...]) -> list[GradeRow]:
        if projection not in groups:
            groups[projection] = group_by_cell(rs, key_fields=projection)
        return groups[projection].get(key, [])

    out: list[_Resolved] = []
    for key, raw_count in component_mix.items():
        count = int(raw_count)
        if count < 0:
            raise ValueError(f"component {key!r}: count cannot be negative")
        cls, size = parse_component_key(key)
        if size:
            cell = cs_map.get(capability_class=cls, size=size)
            cell_rows = rows_for(PROJECTION_CLASS_SIZE, (cls, size))
        else:
            cell = c_map.get(capability_class=cls)
            cell_rows = rows_for(PROJECTION_CLASS, (cls,))
        pick = (
            best_config(
                rs,
                capability_class=cls,
                size=size or None,
                language=language,
                policy=policy,
            )
            if cell.route == ROUTE_DELIVER
            else None
        )
        if pick is not None:
            proj = pick.cell.projection
            axis_rows = rows_for(proj, tuple(getattr(pick.cell.key, f) for f in proj))
        else:
            axis_rows = cell_rows
        out.append(_Resolved(cls, size, count, cell, pick, _axis(axis_rows)))
    return out


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentForecast:
    """One component of the mix, as the rule would route it today."""

    capability_class: str
    size: str
    count: int
    route: str
    n: int
    point: float | None
    ci_low: float | None
    verification_tier: str | None
    config: str
    unit_cost_usd: float | None
    unit_cost_sigma: float | None
    unit_minutes: float | None
    p_clean: float | None
    why: str

    @property
    def label(self) -> str:
        return component_label(self.capability_class, self.size)

    @property
    def measured(self) -> bool:
        return self.route != NOT_YET_MEASURED

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.label,
            "capability_class": self.capability_class,
            "size": self.size,
            "count": self.count,
            "route": self.route,
            "n": self.n,
            "point": self.point,
            "ci_low": self.ci_low,
            "verification_tier": self.verification_tier,
            "config": self.config,
            "unit_cost_usd": self.unit_cost_usd,
            "unit_cost_sigma": self.unit_cost_sigma,
            "unit_minutes": self.unit_minutes,
            "p_clean": self.p_clean,
            "why": self.why,
        }


@dataclass(frozen=True)
class Forecast:
    components: int
    measured_components: int
    costed_components: int
    timed_components: int
    total_cost_mean: float
    total_cost_stddev: float
    total_build_minutes: float
    units_by_route: Mapping[str, int]
    expected_clean_units: float
    p_clean_mean: float
    p_clean_stddev: float
    unmeasured: tuple[str, ...]
    per_component: tuple[ComponentForecast, ...]
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "units_by_route", dict(self.units_by_route))

    @property
    def coverage(self) -> float:
        return self.measured_components / self.components if self.components else 0.0

    @property
    def deliver(self) -> int:
        return self.units_by_route.get(ROUTE_DELIVER, 0)

    @property
    def human(self) -> int:
        return self.units_by_route.get(ROUTE_HUMAN, 0)

    @property
    def calibrate(self) -> int:
        return self.units_by_route.get(ROUTE_CALIBRATE, 0)

    @property
    def single_rep_band(self) -> bool:
        """True when every measured unit sits on a degenerate p ∈ {0, 1}: the band
        is 0 not because the process is certain but because there is no spread."""
        return self.measured_components > 0 and self.p_clean_stddev == 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": self.components,
            "measured_components": self.measured_components,
            "coverage": round(self.coverage, 4),
            "costed_components": self.costed_components,
            "timed_components": self.timed_components,
            "total_cost_mean": round(self.total_cost_mean, 4),
            "total_cost_stddev": round(self.total_cost_stddev, 4),
            "total_build_minutes": round(self.total_build_minutes, 1),
            "units_by_route": dict(self.units_by_route),
            "deliver": self.deliver,
            "human": self.human,
            "calibrate": self.calibrate,
            "expected_clean_units": round(self.expected_clean_units, 3),
            "p_clean_mean": round(self.p_clean_mean, 4),
            "p_clean_stddev": round(self.p_clean_stddev, 4),
            "unmeasured": list(self.unmeasured),
            "per_component": [c.to_dict() for c in self.per_component],
            "policy_version": self.policy_version,
        }


def forecast_build(
    component_mix: Mapping[ComponentKey, int],
    rows: Iterable[GradeRow],
    *,
    policy: RoutingPolicy = DEFAULT_POLICY,
    signoffs: Iterable[SignoffRecord] | None = None,
    repo: str = WILDCARD,
    language: str | None = None,
) -> Forecast:
    """Forecast ``component_mix`` (``{class or class/size: count}``) against the ledger.

    Each component is routed exactly as the factory would route it (the class ×
    size cell, or the class cell for a size-less key); a deliverable component
    is priced at its cheapest + fastest passing config. Cost variance adds across
    independent units: σ_total = sqrt(Σ count · σ_unit²).
    """
    resolved = _resolve(
        component_mix, rows, policy=policy, signoffs=signoffs, repo=repo, language=language
    )
    total = measured = costed = timed = 0
    cost_mean = cost_var = minutes = 0.0
    p_sum = p_var = 0.0
    by_route: dict[str, int] = dict.fromkeys(CELL_STATES, 0)
    unmeasured: list[str] = []
    per: list[ComponentForecast] = []

    for r in resolved:
        total += r.count
        by_route[r.cell.route] += r.count
        p = r.p_clean
        unit_cost = unit_sigma = unit_minutes = None
        if r.cell.measured:
            measured += r.count
            if p is not None:
                p_sum += r.count * p
                p_var += r.count * p * (1.0 - p)
            if r.axis.cost_mean is not None:
                unit_cost = r.axis.cost_mean
                unit_sigma = r.axis.cost_sigma or 0.0
                costed += r.count
                cost_mean += r.count * unit_cost
                cost_var += r.count * unit_sigma**2
            if r.axis.latency_mean is not None:
                unit_minutes = r.axis.latency_mean / 60.0
                timed += r.count
                minutes += r.count * unit_minutes
        else:
            unmeasured.append(r.label)
        src = r.pick.cell if r.pick is not None else r.cell
        per.append(
            ComponentForecast(
                capability_class=r.cls,
                size=r.size,
                count=r.count,
                route=r.cell.route,
                n=src.n,
                point=src.point,
                ci_low=src.stats.ci.low if src.stats is not None else None,
                verification_tier=r.cell.verification_tier,
                config=r.pick.label if r.pick is not None else "",
                unit_cost_usd=unit_cost,
                unit_cost_sigma=unit_sigma,
                unit_minutes=unit_minutes,
                p_clean=p,
                why=r.cell.decision.reason if r.cell.decision else "no rows for this cell",
            )
        )

    return Forecast(
        components=total,
        measured_components=measured,
        costed_components=costed,
        timed_components=timed,
        total_cost_mean=cost_mean,
        total_cost_stddev=math.sqrt(cost_var),
        total_build_minutes=minutes,
        units_by_route=by_route,
        expected_clean_units=p_sum,
        p_clean_mean=(p_sum / measured) if measured else 0.0,
        p_clean_stddev=(math.sqrt(p_var) / measured) if measured else 0.0,
        unmeasured=tuple(unmeasured),
        per_component=tuple(per),
        policy_version=policy.version,
    )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadinessThresholds:
    """What "ready" means, as numbers. Frozen: a gate is tightened by a new
    version, never loosened in place.

    * ``min_coverage`` — share of units the ledger can route at all;
    * ``min_reps``     — least ``n`` any routed cell may carry (a real interval);
    * ``require_earned_tier`` — every measured unit's cell must be human-verified
      or A/B-confirmed (see :mod:`crb.core.signoff`);
    * ``max_false_q1`` — CARDINAL, 0;
    * ``min_buildable`` — share of measured units that route to ``deliver`` with a
      passing config.
    """

    min_coverage: float = 0.90
    min_reps: int = 5
    require_earned_tier: bool = True
    max_false_q1: int = 0
    min_buildable: float = 0.80
    version: str = "readiness.v1"

    def __post_init__(self) -> None:
        if self.max_false_q1 != 0:
            raise ValueError("max_false_q1 is the honesty floor and is always 0")
        for name in ("min_coverage", "min_buildable"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.min_reps < 1:
            raise ValueError("min_reps must be ≥ 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_coverage": self.min_coverage,
            "min_reps": self.min_reps,
            "require_earned_tier": self.require_earned_tier,
            "max_false_q1": self.max_false_q1,
            "min_buildable": self.min_buildable,
            "version": self.version,
        }


DEFAULT_THRESHOLDS = ReadinessThresholds()


@dataclass(frozen=True)
class ReadinessReport:
    ok: bool
    total: int
    measured: int
    min_reps_seen: int
    earned_units: int
    buildable_units: int
    false_q1_total: int
    gaps: tuple[str, ...]
    thresholds: ReadinessThresholds
    policy_version: str

    @property
    def coverage(self) -> float:
        return self.measured / self.total if self.total else 0.0

    @property
    def buildable_frac(self) -> float:
        return self.buildable_units / self.measured if self.measured else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total": self.total,
            "measured": self.measured,
            "coverage": round(self.coverage, 4),
            "min_reps_seen": self.min_reps_seen,
            "earned_units": self.earned_units,
            "buildable_units": self.buildable_units,
            "buildable_frac": round(self.buildable_frac, 4),
            "false_q1_total": self.false_q1_total,
            "gaps": list(self.gaps),
            "thresholds": self.thresholds.to_dict(),
            "policy_version": self.policy_version,
        }


def assess_readiness(
    component_mix: Mapping[ComponentKey, int],
    rows: Iterable[GradeRow],
    *,
    thresholds: ReadinessThresholds = DEFAULT_THRESHOLDS,
    policy: RoutingPolicy = DEFAULT_POLICY,
    signoffs: Iterable[SignoffRecord] | None = None,
    repo: str = WILDCARD,
    language: str | None = None,
) -> ReadinessReport:
    """Is the evidence good enough to let the factory loose on this mix?

    Routes every component as :func:`forecast_build` does, then checks the
    gates in :class:`ReadinessThresholds`. Returns ``ok`` or the specific gaps.
    """
    t = thresholds
    resolved = _resolve(
        component_mix, rows, policy=policy, signoffs=signoffs, repo=repo, language=language
    )
    total = measured = earned = buildable = fq1 = 0
    min_reps_seen: int | None = None
    unmeasured: list[str] = []
    under_reps: list[str] = []
    unearned: list[str] = []
    untrusted: list[str] = []
    not_buildable: dict[str, int] = {}

    for r in resolved:
        total += r.count
        if not r.cell.measured:
            unmeasured.append(r.label)
            continue
        measured += r.count
        n = r.cell.n
        min_reps_seen = n if min_reps_seen is None else min(min_reps_seen, n)
        if n < t.min_reps:
            under_reps.append(f"{r.label} (n={n})")
        if r.cell.earned:
            earned += r.count
        else:
            unearned.append(f"{r.label} ({r.cell.verification_tier})")
        if r.cell.false_q1 > t.max_false_q1:
            fq1 += r.cell.false_q1
            untrusted.append(f"{r.label} (false_q1={r.cell.false_q1})")
        if r.deliverable:
            buildable += r.count
        else:
            not_buildable[r.cell.route] = not_buildable.get(r.cell.route, 0) + r.count

    coverage = (measured / total) if total else 0.0
    buildable_frac = (buildable / measured) if measured else 0.0
    gaps: list[str] = []
    if coverage < t.min_coverage:
        miss = ", ".join(unmeasured) or "—"
        gaps.append(
            f"coverage {coverage:.0%} < {t.min_coverage:.0%} — {len(unmeasured)} unmeasured: {miss}"
        )
    if under_reps:
        gaps.append(
            f"{len(under_reps)} component(s) under {t.min_reps} trials — interval not estimable: "
            + ", ".join(under_reps)
        )
    if t.require_earned_tier and unearned:
        gaps.append(
            f"{measured - earned}/{measured} measured units not earned-trusted — "
            "certainty asserted, not earned: " + ", ".join(unearned)
        )
    if untrusted:
        gaps.append(
            f"{len(untrusted)} component(s) with false-Q1 > 0 — CARDINAL: " + ", ".join(untrusted)
        )
    if buildable_frac < t.min_buildable:
        detail = ", ".join(f"{n} {route}" for route, n in sorted(not_buildable.items())) or "—"
        gaps.append(
            f"buildable {buildable_frac:.0%} < {t.min_buildable:.0%} of measured units route to "
            f"deliver — the rest: {detail}"
        )
    return ReadinessReport(
        ok=not gaps,
        total=total,
        measured=measured,
        min_reps_seen=min_reps_seen or 0,
        earned_units=earned,
        buildable_units=buildable,
        false_q1_total=fq1,
        gaps=tuple(gaps),
        thresholds=t,
        policy_version=policy.version,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_forecast(f: Forecast) -> str:
    lines = [
        f"# Build forecast — {f.components} unit(s) · policy={f.policy_version}",
        "",
        f"- **Cost:** ${f.total_cost_mean:.2f} ± ${f.total_cost_stddev:.2f} "
        f"(over {f.costed_components}/{f.components} costed units)",
        f"- **Build time:** ~{f.total_build_minutes:.0f} min "
        f"(over {f.timed_components}/{f.components} timed units)",
        "- **Routing:** "
        + " · ".join(f"{n} {route}" for route, n in f.units_by_route.items() if n),
        f"- **Coverage:** {f.measured_components}/{f.components} units measured "
        f"({f.coverage:.0%}) — {len(f.unmeasured)} unmeasured",
        f"- **Expected clean:** {f.expected_clean_units:.1f} of {f.measured_components} measured "
        f"({f.p_clean_mean:.0%} ± {f.p_clean_stddev:.0%}, 1 sigma; "
        f"95% band ≈ ±{1.96 * f.p_clean_stddev:.0%})",
    ]
    if f.single_rep_band:
        lines.append(
            "  - deviation band is 0% because every routed cell sits at exactly 0% or 100% — "
            "that is the absence of spread, not certainty; look at each cell's n and CI."
        )
    if f.unmeasured:
        lines.append(
            f"- **Unmeasured (cannot forecast — measure first):** {', '.join(f.unmeasured)}"
        )
    lines += [
        "",
        "| component | count | route | n | point | tier | config | unit $ | unit min | why |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in f.per_component:
        uc = f"${c.unit_cost_usd:.3f}" if c.unit_cost_usd is not None else "—"
        um = f"{c.unit_minutes:.1f}" if c.unit_minutes is not None else "—"
        pt = f"{c.point:.1%}" if c.point is not None else "—"
        lines.append(
            f"| `{c.label}` | {c.count} | **{c.route}** | {c.n} | {pt} | "
            f"{c.verification_tier or '—'} | {c.config or '—'} | {uc} | {um} | {c.why} |"
        )
    return "\n".join(lines)


def render_readiness(r: ReadinessReport) -> str:
    head = "GO — evidence is ready" if r.ok else "NOT READY"
    lines = [
        f"# Readiness — {head}",
        "",
        f"- Coverage: {r.coverage:.0%} ({r.measured}/{r.total} units measured)",
        f"- Earned-trusted: {r.earned_units}/{r.measured} measured units",
        f"- Buildable of measured: {r.buildable_frac:.0%} ({r.buildable_units} units route to deliver)",
        f"- Min trials on any routed cell: {r.min_reps_seen}",
        f"- false-Q1 across routed cells: {r.false_q1_total}",
        f"- Thresholds: {r.thresholds.version} · policy: {r.policy_version}",
    ]
    if r.gaps:
        lines += ["", "**Gaps (the punch-list):**", *[f"- {g}" for g in r.gaps]]
    else:
        lines += ["", "All gates pass."]
    return "\n".join(lines)
