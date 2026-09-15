"""The capability map — what the ledger licenses, per cell, honestly.

A :class:`CapabilityMap` is the read side of the ledger: the rows are grouped
by a *projection* of the cell key (the full cell, class × size, class × size ×
language, class × size × model …), each group is reduced to a
:class:`~crb.core.ledger.CellStats`, and the ONE routing rule
(:func:`crb.core.routing.route`) is applied to it unchanged. Nothing here
re-derives a verdict, a belt, or a statistic; nothing here fabricates a row.

Invariants
----------
* **Honest-empty.** A cell that has no rows is reported as
  :data:`NOT_YET_MEASURED` with ``stats=None`` and ``decision=None`` — never a
  zero-filled row, never a default point estimate.
* **One rule.** A cell's route is exactly ``route(stats, controls=…)``. The SPC
  variant (σ ≤ 0.10, n ≥ 20) is NOT a gate here; σ is exposed on the cell as an
  advisory field only. The repo's negative-controls verdict
  (:class:`~crb.core.routing.ControlsVerdict`) is a map-level input applied to
  every cell: a failed gate routes ``human``, an absent or thin one withholds
  ``deliver`` (see ADR-0003). A map built without one says so
  (``controls=None``) — absence is visible, never a pass.
* **Two rates, next to each other.** Every measured cell carries the all-rows
  point (the fail-closed number the router consumes) AND ``model_point`` —
  clean over the rows where the model got a fair, finished attempt — with the
  ``failure_kind`` split (``builder_red · budget · protocol · harness ·
  disqualified``) that separates them. The split never replaces the point.
* **Trust before economics.** A config is a candidate for "cheapest + fastest"
  only if its own full-key cell routes to ``deliver``; any cell with
  ``false_q1 > 0`` is excluded before cost or latency is even looked at.
* **Every number carries its n and its method.** Cells carry ``n``, the Wilson
  interval, the routing policy version and the apparatus versions of the rows
  that fed them; legacy census rows (``belt_set="v3-legacy"``) are reported
  as a separate apparatus via ``belt_sets``.

Trusted Autonomy Coverage (TAC) is the share of a repository's *change
profile* — a (class × size) histogram of its recent history, see
:func:`profile_repo` — that routes to ``deliver``. ``earned_coverage`` is the
stricter share whose cells also carry an earned verification tier (a human
signed off — see :mod:`crb.core.signoff`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from crb.core.git import GitError, GitRepo
from crb.core.ledger import (
    CELL_FIELDS,
    CellKey,
    CellStats,
    GradeRow,
    cell_stats,
    false_q1_total,
    group_by_cell,
)
from crb.core.routing import (
    DEFAULT_POLICY,
    ROUTE_DELIVER,
    ROUTES,
    ControlsVerdict,
    RouteDecision,
    RoutingPolicy,
    route,
)
from crb.core.spec import RepoConfig, classify_commit, size_tier
from crb.core.stats import stddev

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: The value a non-projected key field takes in a projected :class:`CellKey`.
WILDCARD = "*"

#: The honest state of a cell with no rows. Distinct from ``calibrate`` (some
#: evidence, not enough): here there is *no* evidence at all.
NOT_YET_MEASURED = "not_yet_measured"

#: Every state a cell can be in: the five routes plus the honest-empty one.
CELL_STATES: tuple[str, ...] = (*ROUTES, NOT_YET_MEASURED)

PROJECTION_CELL: tuple[str, ...] = CELL_FIELDS
PROJECTION_CLASS: tuple[str, ...] = ("capability_class",)
PROJECTION_CLASS_SIZE: tuple[str, ...] = ("capability_class", "size")
PROJECTION_CLASS_SIZE_LANGUAGE: tuple[str, ...] = ("capability_class", "size", "language")
PROJECTION_CLASS_SIZE_MODEL: tuple[str, ...] = ("capability_class", "size", "model")

#: The named views the CLI and the API expose.
PROJECTIONS: Mapping[str, tuple[str, ...]] = {
    "cell": PROJECTION_CELL,
    "class": PROJECTION_CLASS,
    "class_size": PROJECTION_CLASS_SIZE,
    "class_size_language": PROJECTION_CLASS_SIZE_LANGUAGE,
    "class_size_model": PROJECTION_CLASS_SIZE_MODEL,
}

#: Verification tiers — how far a cell's claim has been EARNED, never asserted.
#: ``untrusted`` is forced by ``false_q1 > 0``; ``automated-pass`` is the most
#: the ledger alone can grant; the two *earned* tiers come only from a human
#: attestation in :mod:`crb.core.signoff`.
TIER_UNTRUSTED = "untrusted"
TIER_AUTOMATED_PASS = "automated-pass"  # noqa: S105 — a tier name, not a secret
TIER_HUMAN_VERIFIED = "human-verified"
TIER_AB_CONFIRMED = "ab-confirmed"
EARNED_TIERS: tuple[str, ...] = (TIER_HUMAN_VERIFIED, TIER_AB_CONFIRMED)
TIERS: tuple[str, ...] = (TIER_UNTRUSTED, TIER_AUTOMATED_PASS, *EARNED_TIERS)

SELECTION_COST_THEN_LATENCY = "cost_then_latency"
SELECTION_POINT = "point"
SELECTIONS: tuple[str, ...] = (SELECTION_COST_THEN_LATENCY, SELECTION_POINT)


def _check_projection(projection: Sequence[str]) -> tuple[str, ...]:
    proj = tuple(projection)
    if not proj:
        raise ValueError("a projection needs at least one cell-key field")
    unknown = [f for f in proj if f not in CELL_FIELDS]
    if unknown:
        raise ValueError(f"unknown cell-key field(s) {unknown}; expected a subset of {CELL_FIELDS}")
    return proj


def projected_key(source: CellKey | Mapping[str, str], projection: Sequence[str]) -> CellKey:
    """The :class:`CellKey` of ``source`` with every non-projected field set to ``"*"``."""
    proj = _check_projection(projection)
    src = source.to_dict() if isinstance(source, CellKey) else dict(source)
    return CellKey(
        **{f: (str(src.get(f, WILDCARD)) if f in proj else WILDCARD) for f in CELL_FIELDS}
    )


def key_matches(pattern: CellKey, key: CellKey) -> bool:
    """``pattern`` matches ``key`` when every field is equal or ``"*"`` in the pattern.

    A ``"*"`` in ``key`` (a projected cell) only matches a ``"*"`` in ``pattern``: a
    class-wide aggregate is never matched by a narrower pattern.
    """
    return all(p in (WILDCARD, k) for p, k in zip(pattern.to_tuple(), key.to_tuple(), strict=True))


def projected_stats(rows: Sequence[GradeRow], projection: Sequence[str]) -> CellStats:
    """:func:`~crb.core.ledger.cell_stats` re-keyed to the projection (``"*"`` elsewhere)."""
    stats = cell_stats(rows)
    return replace(stats, cell=projected_key(rows[0].cell, projection))


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityCell:
    """One cell of the map: its key, its statistics, and what the rule says.

    ``stats`` and ``decision`` are ``None`` for a cell with no rows — the honest
    empty. ``sigma`` is the sample standard deviation of the per-trial clean
    indicator (advisory; the Wilson interval on ``stats`` is the method the
    product routes on). ``cost_known`` / ``latency_known`` say whether any
    eligible row recorded the axis — :class:`CellStats` reports ``0.0`` for an
    unmeasured axis, and an axis we cannot compare on is never on a Pareto
    frontier.
    """

    key: CellKey
    projection: tuple[str, ...]
    stats: CellStats | None
    decision: RouteDecision | None
    verification_tier: str | None
    sigma: float | None
    repos: int
    rows: int
    belt_sets: tuple[str, ...]
    cost_known: bool
    latency_known: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection", _check_projection(self.projection))
        if self.verification_tier is not None and self.verification_tier not in TIERS:
            raise ValueError(f"verification_tier {self.verification_tier!r} not in {TIERS}")
        if (self.stats is None) != (self.decision is None):
            raise ValueError("stats and decision are both present or both absent")
        if self.stats is None and self.verification_tier is not None:
            raise ValueError("an unmeasured cell cannot carry a verification tier")
        if (
            self.stats is not None
            and self.stats.false_q1 > 0
            and self.verification_tier != TIER_UNTRUSTED
        ):
            raise ValueError("a cell with false_q1 > 0 is 'untrusted' — no other tier is possible")

    # --- convenience -----------------------------------------------------------
    @property
    def measured(self) -> bool:
        return self.stats is not None

    @property
    def route(self) -> str:
        return self.decision.route if self.decision is not None else NOT_YET_MEASURED

    @property
    def n(self) -> int:
        return self.stats.n if self.stats is not None else 0

    @property
    def point(self) -> float | None:
        return self.stats.point if self.stats is not None else None

    @property
    def false_q1(self) -> int:
        return self.stats.false_q1 if self.stats is not None else 0

    @property
    def reason(self) -> str:
        return self.decision.reason if self.decision is not None else "no rows for this cell"

    @property
    def reason_code(self) -> str:
        return self.decision.reason_code if self.decision is not None else ""

    # --- the failure split (see FailureSplit) --------------------------------------
    @property
    def n_builder_red(self) -> int:
        return self.stats.n_builder_red if self.stats is not None else 0

    @property
    def n_budget(self) -> int:
        return self.stats.n_budget if self.stats is not None else 0

    @property
    def n_protocol(self) -> int:
        return self.stats.n_protocol if self.stats is not None else 0

    @property
    def n_harness(self) -> int:
        return self.stats.n_harness if self.stats is not None else 0

    @property
    def n_outage(self) -> int:
        return self.stats.n_outage if self.stats is not None else 0

    @property
    def n_disqualified(self) -> int:
        return self.stats.n_disqualified if self.stats is not None else 0

    @property
    def model_n(self) -> int:
        return self.stats.model_n if self.stats is not None else 0

    @property
    def model_point(self) -> float | None:
        """``clean / (clean + builder_red)`` — the model's rate on fair, finished
        attempts; ``None`` when unmeasured or when no such attempt exists."""
        if self.stats is None or self.stats.model_n == 0:
            return None
        return self.stats.model_point

    @property
    def earned(self) -> bool:
        return self.verification_tier in EARNED_TIERS

    @property
    def label(self) -> str:
        return "|".join(getattr(self.key, f) for f in self.projection)

    def with_tier(self, tier: str) -> CapabilityCell:
        """A copy at ``tier``. Refuses to lift an untrusted or unmeasured cell."""
        if tier not in TIERS:
            raise ValueError(f"tier {tier!r} not in {TIERS}")
        if self.stats is None:
            raise ValueError("an unmeasured cell has no tier to change")
        if self.stats.false_q1 > 0 and tier != TIER_UNTRUSTED:
            raise ValueError("false_q1 > 0: the cell is untrusted and cannot be lifted")
        return replace(self, verification_tier=tier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.to_dict(),
            "projection": list(self.projection),
            "label": self.label,
            "measured": self.measured,
            "route": self.route,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "stats": None if self.stats is None else self.stats.to_dict(),
            "decision": None if self.decision is None else self.decision.to_dict(),
            "verification_tier": self.verification_tier,
            "sigma": None if self.sigma is None else round(self.sigma, 4),
            "repos": self.repos,
            "rows": self.rows,
            "belt_sets": list(self.belt_sets),
            "cost_known": self.cost_known,
            "latency_known": self.latency_known,
            "failure_split": {
                "builder_red": self.n_builder_red,
                "budget": self.n_budget,
                "protocol": self.n_protocol,
                "harness": self.n_harness,
                "disqualified": self.n_disqualified,
                "outage": self.n_outage,
            },
            "model_n": self.model_n,
            "model_point": None if self.model_point is None else round(self.model_point, 4),
        }


def empty_cell(key: CellKey, projection: Sequence[str] = PROJECTION_CELL) -> CapabilityCell:
    """The honest-empty cell: no rows, no stats, no decision, no tier."""
    proj = _check_projection(projection)
    return CapabilityCell(
        key=projected_key(key, proj),
        projection=proj,
        stats=None,
        decision=None,
        verification_tier=None,
        sigma=None,
        repos=0,
        rows=0,
        belt_sets=(),
        cost_known=False,
        latency_known=False,
    )


def measure_cell(
    rows: Sequence[GradeRow],
    projection: Sequence[str] = PROJECTION_CELL,
    *,
    policy: RoutingPolicy = DEFAULT_POLICY,
    controls: ControlsVerdict | None = None,
) -> CapabilityCell:
    """Reduce one group of rows (all sharing the projected key) to a cell.

    The route is ``route(stats, controls=controls, policy=policy)`` — nothing
    else. ``controls`` is the repo's negative-controls verdict (``None`` = not
    evaluated by this caller; the decision records the absence). The tier is
    ``untrusted`` iff ``false_q1 > 0`` (structurally impossible for rows written
    through :class:`~crb.core.ledger.GradeRow`, re-checked here anyway) and
    ``automated-pass`` otherwise; earned tiers are overlaid by
    :mod:`crb.core.signoff`, never granted here.
    """
    proj = _check_projection(projection)
    if not rows:
        raise ValueError("measure_cell needs at least one row; use empty_cell for none")
    stats = projected_stats(rows, proj)
    eligible = [r for r in rows if r.eligible]
    decision = route(stats, controls=controls, policy=policy)
    tier = TIER_UNTRUSTED if stats.false_q1 > 0 else TIER_AUTOMATED_PASS
    return CapabilityCell(
        key=stats.cell,
        projection=proj,
        stats=stats,
        decision=decision,
        verification_tier=tier,
        sigma=stddev([1.0 if r.clean else 0.0 for r in eligible]) if eligible else None,
        repos=len({r.repo for r in rows}),
        rows=len(rows),
        belt_sets=tuple(sorted({r.belt_set for r in rows})),
        cost_known=any(r.cost_usd > 0 for r in eligible),
        latency_known=any(r.latency_s > 0 for r in eligible),
    )


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityMap:
    """All cells of one projection, plus the numbers that qualify every other number.

    ``controls`` is the repo-level negative-controls verdict every cell was routed
    under (``None`` when the caller evaluated none — visible as an absence)."""

    projection: tuple[str, ...]
    cells: tuple[CapabilityCell, ...]
    rows: int
    false_q1_total: int
    policy: RoutingPolicy
    apparatus_versions: tuple[str, ...]
    controls: ControlsVerdict | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection", _check_projection(self.projection))
        for c in self.cells:
            if c.projection != self.projection:
                raise ValueError(
                    f"cell {c.label!r} has projection {c.projection}, map has {self.projection}"
                )

    def lookup(self, key: CellKey | Mapping[str, str]) -> CapabilityCell:
        """The cell for ``key`` (projected first); the honest-empty cell when absent."""
        want = projected_key(key, self.projection)
        for c in self.cells:
            if c.key == want:
                return c
        return empty_cell(want, self.projection)

    def get(self, **fields: str) -> CapabilityCell:
        """``lookup`` by keyword, e.g. ``cmap.get(capability_class="bug.fix", size="S")``."""
        unknown = [f for f in fields if f not in self.projection]
        if unknown:
            raise ValueError(f"field(s) {unknown} are not in projection {self.projection}")
        return self.lookup(dict(fields))

    def by_route(self) -> dict[str, list[CapabilityCell]]:
        out: dict[str, list[CapabilityCell]] = {s: [] for s in CELL_STATES}
        for c in self.cells:
            out[c.route].append(c)
        return out

    def with_cells(self, cells: Iterable[CapabilityCell]) -> CapabilityMap:
        """The same map with ``cells`` replaced (used by the sign-off overlay)."""
        return replace(self, cells=tuple(sorted(cells, key=lambda c: c.key.to_tuple())))

    def to_dict(self) -> dict[str, Any]:
        routes = {s: len(cs) for s, cs in self.by_route().items()}
        return {
            "projection": list(self.projection),
            "rows": self.rows,
            "false_q1_total": self.false_q1_total,
            "policy": self.policy.to_dict(),
            "apparatus_versions": list(self.apparatus_versions),
            "controls": None if self.controls is None else self.controls.to_dict(),
            "cells": [c.to_dict() for c in self.cells],
            "cells_by_route": routes,
        }

    def render_markdown(self) -> str:
        return render_markdown(self)


def build_capability_map(
    rows: Iterable[GradeRow],
    *,
    projection: Sequence[str] = PROJECTION_CLASS_SIZE,
    policy: RoutingPolicy = DEFAULT_POLICY,
    controls: ControlsVerdict | None = None,
) -> CapabilityMap:
    """Group ``rows`` by ``projection`` and route every group under ``controls``
    (the repo's negative-controls verdict; ``None`` = not evaluated). Pure; no I/O."""
    proj = _check_projection(projection)
    rs = list(rows)
    groups = group_by_cell(rs, key_fields=proj)
    cells = [measure_cell(g, proj, policy=policy, controls=controls) for g in groups.values()]
    cells.sort(key=lambda c: c.key.to_tuple())
    return CapabilityMap(
        projection=proj,
        cells=tuple(cells),
        rows=len(rs),
        false_q1_total=false_q1_total(rs),
        policy=policy,
        apparatus_versions=tuple(sorted({r.apparatus_version for r in rs})),
        controls=controls,
    )


def capability_views(
    rows: Iterable[GradeRow],
    *,
    policy: RoutingPolicy = DEFAULT_POLICY,
    controls: ControlsVerdict | None = None,
) -> dict[str, CapabilityMap]:
    """Every named projection in :data:`PROJECTIONS`, built from one pass over the rows."""
    rs = list(rows)
    return {
        name: build_capability_map(rs, projection=proj, policy=policy, controls=controls)
        for name, proj in PROJECTIONS.items()
    }


# ---------------------------------------------------------------------------
# Cheapest + fastest passing config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigPick:
    """The config a (class × size) cell would be routed to, and how it was chosen.

    ``selection`` is ``cost_then_latency`` when at least one passing config
    carried both axes (the pick is then the cheapest point of the cost/latency
    Pareto frontier, ties to the fastest, then the highest point estimate) and
    ``point`` when none did (the pick is then the best-evidenced config — highest
    Wilson lower bound, then point, then n; no economic claim is made). ``frontier`` lists the labels of the non-dominated
    configs considered; ``candidates`` is how many passing configs there were.
    """

    cell: CapabilityCell
    selection: str
    frontier: tuple[str, ...]
    candidates: int

    def __post_init__(self) -> None:
        if self.selection not in SELECTIONS:
            raise ValueError(f"selection {self.selection!r} not in {SELECTIONS}")
        if self.cell.route != ROUTE_DELIVER:
            raise ValueError("a ConfigPick must be a config whose own cell routes to deliver")

    @property
    def label(self) -> str:
        k = self.cell.key
        return f"{k.builder}/{k.model}@{k.provider}"

    @property
    def cost_usd(self) -> float | None:
        return self.cell.stats.cost_usd_mean if self.cell.cost_known and self.cell.stats else None

    @property
    def latency_s(self) -> float | None:
        return (
            self.cell.stats.latency_s_mean if self.cell.latency_known and self.cell.stats else None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.label,
            "key": self.cell.key.to_dict(),
            "selection": self.selection,
            "n": self.cell.n,
            "point": self.cell.point,
            "cost_usd": self.cost_usd,
            "latency_s": self.latency_s,
            "frontier": list(self.frontier),
            "candidates": self.candidates,
        }


def config_projection(*, size: str | None, language: str | None) -> tuple[str, ...]:
    """The cell fields that identify a *config* for a pick.

    A config is ``(process_step, builder, model, provider)`` within a class. Size
    and language are part of the cell only when the caller pins them; otherwise
    they are pooled, so a config is judged on everything it was measured on
    rather than on its best-looking slice.
    """
    drop = {f for f, v in (("size", size), ("language", language)) if v is None}
    return tuple(f for f in CELL_FIELDS if f not in drop)


def config_candidates(
    rows: Iterable[GradeRow],
    *,
    capability_class: str,
    size: str | None = None,
    language: str | None = None,
    policy: RoutingPolicy = DEFAULT_POLICY,
    controls: ControlsVerdict | None = None,
) -> list[CapabilityCell]:
    """Config cells (see :func:`config_projection`) for the class that PASS.

    Passing = the config's own cell routes to ``deliver`` under ``policy`` (and
    ``controls``, when given). Cells with ``false_q1 > 0`` are dropped first,
    explicitly, before routing — the routing rule would also refuse them, but
    the exclusion is not left implicit.
    """
    proj = config_projection(size=size, language=language)
    cmap = build_capability_map(rows, projection=proj, policy=policy, controls=controls)
    out: list[CapabilityCell] = []
    for c in cmap.cells:
        k = c.key
        if k.capability_class != capability_class:
            continue
        if size is not None and k.size != size:
            continue
        if language is not None and k.language != language:
            continue
        if c.false_q1 > 0:
            continue
        if c.route == ROUTE_DELIVER:
            out.append(c)
    return out


def pareto_frontier(cells: Iterable[CapabilityCell]) -> list[CapabilityCell]:
    """The non-dominated (cost, latency) set over trusted, fully-costed cells.

    A cell is dominated when another is no worse on both axes and strictly better
    on one. Unmeasured cells, cells with ``false_q1 > 0`` and cells missing either
    axis are not on the frontier. Sorted ascending by (cost, latency).
    """
    pts = [
        c
        for c in cells
        if c.stats is not None and c.false_q1 == 0 and c.cost_known and c.latency_known
    ]

    def axes(c: CapabilityCell) -> tuple[float, float]:
        assert c.stats is not None
        return (c.stats.cost_usd_mean, c.stats.latency_s_mean)

    def dominated(a: CapabilityCell) -> bool:
        ca, la = axes(a)
        for b in pts:
            if b is a:
                continue
            cb, lb = axes(b)
            if cb <= ca and lb <= la and (cb < ca or lb < la):
                return True
        return False

    frontier = [c for c in pts if not dominated(c)]
    frontier.sort(key=lambda c: (*axes(c), -(c.point or 0.0), c.key.to_tuple()))
    return frontier


def best_config(
    rows: Iterable[GradeRow],
    *,
    capability_class: str,
    size: str | None = None,
    language: str | None = None,
    policy: RoutingPolicy = DEFAULT_POLICY,
    selection: str = SELECTION_COST_THEN_LATENCY,
    controls: ControlsVerdict | None = None,
) -> ConfigPick | None:
    """The cheapest + fastest PASSING config for a class (× size × language).

    ``None`` when no config passes — the cell is not deliverable by anyone we
    have measured, and no fallback "best effort" pick is fabricated.
    """
    if selection not in SELECTIONS:
        raise ValueError(f"selection must be one of {SELECTIONS}, got {selection!r}")
    rs = list(rows)
    candidates = config_candidates(
        rs,
        capability_class=capability_class,
        size=size,
        language=language,
        policy=policy,
        controls=controls,
    )
    if not candidates:
        return None
    frontier = pareto_frontier(candidates) if selection == SELECTION_COST_THEN_LATENCY else []
    if frontier:
        pick = frontier[0]  # already sorted by (cost, latency, -point, key)
        return ConfigPick(
            cell=pick,
            selection=SELECTION_COST_THEN_LATENCY,
            frontier=tuple(c.label for c in frontier),
            candidates=len(candidates),
        )
    # No passing config carries both axes: pick by evidence, claim nothing about cost.
    # Wilson lower bound first — the quantity the rule itself keys on — so a thin
    # 100% config never outranks a well-measured 93% one (more evidence wins).
    ranked = sorted(
        candidates,
        key=lambda c: (
            -(c.stats.ci.low if c.stats else 0.0),
            -(c.point or 0.0),
            -c.n,
            c.key.to_tuple(),
        ),
    )
    return ConfigPick(
        cell=ranked[0], selection=SELECTION_POINT, frontier=(), candidates=len(candidates)
    )


# ---------------------------------------------------------------------------
# Repo change profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoChangeProfile:
    """A repository's (class × size) change histogram over its recent history.

    ``n_commits`` counts commits that touched at least one *source* file (per
    :meth:`RepoConfig.is_src`) and whose churn could be measured; ``examined``
    is how many commits were walked; ``skipped`` those with no source change or
    no parent. Measurement input only — it never touches a verdict.
    """

    repo: str
    n_commits: int
    examined: int
    skipped: int
    cells: Mapping[tuple[str, str], int]
    ref: str = "HEAD"

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", dict(self.cells))
        if self.n_commits != sum(self.cells.values()):
            raise ValueError("n_commits must equal the sum of the cell counts")

    def class_totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for (cls, _), n in self.cells.items():
            out[cls] = out.get(cls, 0) + n
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    def size_totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for (_, size), n in self.cells.items():
            out[size] = out.get(size, 0) + n
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    def ranked(self) -> list[tuple[tuple[str, str], int]]:
        """Cells most-frequent first, then by (class, size)."""
        return sorted(self.cells.items(), key=lambda kv: (-kv[1], kv[0]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "ref": self.ref,
            "n_commits": self.n_commits,
            "examined": self.examined,
            "skipped": self.skipped,
            "cells": [
                {
                    "capability_class": cls,
                    "size": size,
                    "count": n,
                    "share": round(n / self.n_commits, 4) if self.n_commits else 0.0,
                }
                for (cls, size), n in self.ranked()
            ],
            "class_totals": self.class_totals(),
            "size_totals": self.size_totals(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RepoChangeProfile:
        cells = {
            (str(c["capability_class"]), str(c["size"])): int(c["count"])
            for c in d.get("cells", [])
        }
        return cls(
            repo=str(d.get("repo", "")),
            n_commits=int(d.get("n_commits", sum(cells.values()))),
            examined=int(d.get("examined", 0)),
            skipped=int(d.get("skipped", 0)),
            cells=cells,
            ref=str(d.get("ref", "HEAD")),
        )


def profile_repo(
    repo: GitRepo,
    config: RepoConfig,
    *,
    log_n: int = 0,
    ref: str = "HEAD",
) -> RepoChangeProfile:
    """Walk ``log_n`` recent non-merge commits and histogram their (class × size).

    Class is :func:`~crb.core.spec.classify_commit` over the commit's *source*
    files; size is :func:`~crb.core.spec.size_tier` over their churn
    (:meth:`GitRepo.numstat_churn` against the first parent). Commits with no
    source file, or without a parent (the root), are skipped and counted.
    """
    n = log_n or int(config.mining.get("log_n", 500))
    cells: dict[tuple[str, str], int] = {}
    examined = skipped = 0
    for sha in repo.log_shas(n, ref=ref):
        examined += 1
        src = [f for f in repo.changed_files(sha) if config.is_src(f)]
        if not src:
            skipped += 1
            continue
        try:
            churn = repo.numstat_churn(f"{sha}~1", sha, src)
        except GitError:
            skipped += 1  # root commit (no parent) or unreadable object
            continue
        key = (classify_commit(src), size_tier(churn))
        cells[key] = cells.get(key, 0) + 1
    return RepoChangeProfile(
        repo=config.name,
        n_commits=sum(cells.values()),
        examined=examined,
        skipped=skipped,
        cells=cells,
        ref=ref,
    )


# ---------------------------------------------------------------------------
# Trusted Autonomy Coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfiledCell:
    """One (class × size) of a repo's change mix, joined to what the map says."""

    capability_class: str
    size: str
    count: int
    cell: CapabilityCell
    pick: ConfigPick | None

    @property
    def route(self) -> str:
        return self.cell.route

    @property
    def deliverable(self) -> bool:
        """Routes to ``deliver`` AND has a passing config to route to."""
        return self.cell.route == ROUTE_DELIVER and self.pick is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_class": self.capability_class,
            "size": self.size,
            "count": self.count,
            "route": self.route,
            "deliverable": self.deliverable,
            "verification_tier": self.cell.verification_tier,
            "n": self.cell.n,
            "point": self.cell.point,
            "false_q1": self.cell.false_q1,
            "pick": None if self.pick is None else self.pick.to_dict(),
            "why": self.cell.reason,
            "reason_code": self.cell.reason_code,
        }


@dataclass(frozen=True)
class CoverageSummary:
    """Trusted Autonomy Coverage: the share of a repo's change VOLUME the factory
    may deliver autonomously. Volume-weighted (a repo dominated by a few
    deliverable change types is more automated than one where they are rare)."""

    repo: str
    total_volume: int
    deliver_volume: int
    earned_volume: int
    volume_by_route: Mapping[str, int]
    cells: tuple[ProfiledCell, ...]
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "volume_by_route", dict(self.volume_by_route))

    @property
    def coverage(self) -> float:
        return self.deliver_volume / self.total_volume if self.total_volume else 0.0

    @property
    def earned_coverage(self) -> float:
        return self.earned_volume / self.total_volume if self.total_volume else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "total_volume": self.total_volume,
            "deliver_volume": self.deliver_volume,
            "earned_volume": self.earned_volume,
            "coverage": round(self.coverage, 4),
            "earned_coverage": round(self.earned_coverage, 4),
            "volume_by_route": dict(self.volume_by_route),
            "cells": [c.to_dict() for c in self.cells],
            "policy_version": self.policy_version,
        }


def trusted_autonomy_coverage(
    profile: RepoChangeProfile,
    rows: Iterable[GradeRow],
    *,
    cells: CapabilityMap | None = None,
    policy: RoutingPolicy = DEFAULT_POLICY,
    language: str | None = None,
) -> CoverageSummary:
    """Join a change profile to the (class × size) map and weight routes by volume.

    ``cells`` may be a class × size map with sign-offs already applied (see
    :func:`crb.core.signoff.apply_signoffs`); otherwise it is built from ``rows``.
    ``rows`` are always needed for the config pick, which is routed under the
    map's own controls verdict so a config never passes on a gate the map failed.
    A profiled cell counts toward ``deliver_volume`` only when it routes to
    ``deliver`` AND a passing config exists; ``earned_volume`` additionally
    requires an earned tier.
    """
    rs = list(rows)
    cmap = cells if cells is not None else build_capability_map(rs, policy=policy)
    if cmap.projection != PROJECTION_CLASS_SIZE:
        raise ValueError("trusted_autonomy_coverage needs the class x size projection")
    out: list[ProfiledCell] = []
    by_route: dict[str, int] = dict.fromkeys(CELL_STATES, 0)
    deliver_volume = earned_volume = 0
    for (cls, size), count in profile.ranked():
        cell = cmap.get(capability_class=cls, size=size)
        pick = (
            best_config(
                rs,
                capability_class=cls,
                size=size,
                language=language,
                policy=policy,
                controls=cmap.controls,
            )
            if cell.route == ROUTE_DELIVER
            else None
        )
        pc = ProfiledCell(cls, size, count, cell, pick)
        out.append(pc)
        by_route[cell.route] += count
        if pc.deliverable:
            deliver_volume += count
            if cell.earned:
                earned_volume += count
    return CoverageSummary(
        repo=profile.repo,
        total_volume=profile.n_commits,
        deliver_volume=deliver_volume,
        earned_volume=earned_volume,
        volume_by_route=by_route,
        cells=tuple(out),
        policy_version=cmap.policy.version,
    )


# ---------------------------------------------------------------------------
# Rendering (CLI)
# ---------------------------------------------------------------------------


def _fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.1%}"


def _fmt_controls(c: ControlsVerdict | None, policy: RoutingPolicy) -> str:
    if c is None:
        return "not evaluated"
    state = c.state(min_share=policy.min_controls_share, max_escapes=policy.max_controls_escapes)
    if not c.measured:
        return state
    return f"{state} ({c.constructible}/{c.total} constructible, {c.escapes} escape(s))"


def render_markdown(cmap: CapabilityMap) -> str:
    """One markdown table, one row per cell, every number next to its n. The
    all-rows point sits beside the model point and the failure split that
    separates them (``red·budget·protocol·harness·DQ``)."""
    head = [
        *cmap.projection,
        "n",
        "clean",
        "point",
        "95% CI",
        "model",
        "split r·b·p·h·dq",
        "sigma",
        "false-Q1",
        "tier",
        "route",
        "why",
    ]
    lines = [
        f"# Capability map — {' x '.join(cmap.projection)}",
        "",
        f"rows={cmap.rows} · false-Q1={cmap.false_q1_total} · policy={cmap.policy.version} · "
        f"apparatus={','.join(cmap.apparatus_versions) or '—'} · "
        f"controls={_fmt_controls(cmap.controls, cmap.policy)}",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "---|" * len(head),
    ]
    if not cmap.cells:
        lines.append(
            "| " + " | ".join(["_(no rows)_", *["—"] * (len(head) - 2), NOT_YET_MEASURED]) + " |"
        )
        return "\n".join(lines)
    for c in cmap.cells:
        keyvals = [f"`{getattr(c.key, f)}`" for f in c.projection]
        if c.stats is None:
            body = ["0", "0", "—", "—", "—", "—", "—", "0", "—", f"**{c.route}**", "no rows"]
        else:
            s = c.stats
            body = [
                str(s.n),
                str(s.clean),
                _fmt_pct(s.point),
                f"[{s.ci.low:.2f}, {s.ci.high:.2f}]",
                f"{_fmt_pct(c.model_point)} (n={s.model_n})",
                f"{s.n_builder_red}·{s.n_budget}·{s.n_protocol}·{s.n_harness}·{s.n_disqualified}",
                "—" if c.sigma is None else f"{c.sigma:.2f}",
                str(s.false_q1),
                c.verification_tier or "—",
                f"**{c.route}**",
                c.decision.reason if c.decision else "",
            ]
        lines.append("| " + " | ".join(keyvals + body) + " |")
    return "\n".join(lines)


def render_profile(profile: RepoChangeProfile, *, top: int = 20) -> str:
    lines = [
        f"# Change profile — {profile.repo} ({profile.ref})",
        "",
        f"commits profiled: {profile.n_commits} (examined {profile.examined}, skipped {profile.skipped})",
        "size mix: " + "  ".join(f"{s} {n}" for s, n in profile.size_totals().items()),
        "",
        "| class | size | count | share |",
        "|---|---|---|---|",
    ]
    for (cls, size), n in profile.ranked()[:top]:
        share = n / profile.n_commits if profile.n_commits else 0.0
        lines.append(f"| `{cls}` | {size} | {n} | {share:.1%} |")
    return "\n".join(lines)


def render_coverage(summary: CoverageSummary) -> str:
    lines = [
        f"# Trusted Autonomy Coverage — {summary.repo}",
        "",
        f"**{summary.coverage:.0%}** of change volume routes to deliver "
        f"({summary.deliver_volume}/{summary.total_volume} commits); "
        f"**{summary.earned_coverage:.0%}** with an earned tier ({summary.earned_volume}) · "
        f"policy={summary.policy_version}",
        "volume by route: "
        + " · ".join(f"{r} {n}" for r, n in summary.volume_by_route.items() if n),
        "",
        "| class | size | count | route | n | point | tier | config | why |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pc in summary.cells:
        cfg = "—" if pc.pick is None else pc.pick.label
        why = pc.cell.decision.reason if pc.cell.decision else "no rows for this cell"
        lines.append(
            f"| `{pc.capability_class}` | {pc.size} | {pc.count} | **{pc.route}** | "
            f"{pc.cell.n} | {_fmt_pct(pc.cell.point)} | {pc.cell.verification_tier or '—'} | "
            f"{cfg} | {why} |"
        )
    return "\n".join(lines)
