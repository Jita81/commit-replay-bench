"""``/capability-map``, ``/routes`` and ``/failure-split`` — what the ledger licenses,
per cell, honestly.

All three routes are pure reads: the repo's rows come out of the store as
:class:`~crb.core.ledger.GradeRow` (so a false-Q1 row that bypassed the write path
refuses to load and the request answers ``409 false_q1_refused`` — the map is never
computed over untrusted rows), are reduced by
:func:`crb.core.capability.build_capability_map` under the ONE routing rule, and
the active human sign-offs are overlaid at read time
(:func:`crb.core.signoff.apply_signoffs_to_map`, which re-checks false-Q1 = 0).

The repo's negative-controls verdict is ALWAYS evaluated here
(:func:`crb.server.routes.oracle.latest_controls_verdict` — the same latest report
``/oracle/{repo}/controls`` serves, or ``unmeasured`` when there is none), so a
cell can never reach ``deliver`` on the product surface while the gate failed, was
never run, or exercised fewer than half its controls (ADR-0003 amendment). Every
cell and decision carries the ``failure_kind`` split and ``model_point`` next to
the all-rows point, and the decision's ``reason_code``.

Honest-empty: only MEASURED cells are returned. A (class × size) the ledger has
never seen is absent — the UI renders absence as ``NOT_YET_MEASURED`` — and
``summary.trusted_autonomy_coverage`` is ``null`` until the repo has a change
profile to weight the cells by.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from crb.core.capability import (
    PROJECTION_CELL,
    PROJECTION_CLASS_SIZE,
    CapabilityCell,
    CapabilityMap,
    RepoChangeProfile,
    build_capability_map,
    trusted_autonomy_coverage,
)
from crb.core.ledger import CELL_FIELDS, GradeRow, failure_split
from crb.core.routing import DEFAULT_POLICY, ROUTE_DELIVER, ControlsVerdict
from crb.core.signoff import apply_signoffs_to_map
from crb.core.spec import SIZE_TIER_NAMES
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.oracle import latest_controls_verdict, verdict_dict
from crb.server.routes.repos import cached_profile, get_repo_or_404
from crb.server.routes.signoffs import load_signoff_records
from crb.server.schemas import CapabilitySummary
from crb.server.schemas_capability import (
    CapabilityCellSplitOut,
    CapabilityMapWithControlsOut,
    ControlsVerdictOut,
    FailureSplitOut,
    FailureSplitResponse,
    RouteDecisionWithControlsOut,
    RoutesWithControlsResponse,
    RoutingPolicyWithControlsOut,
)
from crb.store.ledger import DbLedger

router = APIRouter(tags=["capability"])
_ERR = {"model": ErrorEnvelope}

#: ``?by=`` vocabulary (the CLI's ``--by`` aliases).
BY_ALIASES: dict[str, str] = {
    "class": "capability_class",
    "capability_class": "capability_class",
    "size": "size",
    "language": "language",
    "lang": "language",
    "model": "model",
    "builder": "builder",
    "provider": "provider",
    "step": "process_step",
    "process_step": "process_step",
}
DEFAULT_BY = "class,size"


def parse_by(by: str | None) -> tuple[str, ...]:
    """``"class,size,language"`` → the cell-key projection, in :data:`CELL_FIELDS` order."""
    tokens = [t.strip().lower() for t in (by or DEFAULT_BY).split(",") if t.strip()]
    fields: list[str] = []
    for t in tokens:
        if t not in BY_ALIASES:
            raise ApiError(
                422,
                "validation_error",
                f"unknown by field {t!r}",
                detail={"allowed": sorted(set(BY_ALIASES))},
            )
        f = BY_ALIASES[t]
        if f not in fields:
            fields.append(f)
    if not fields:
        raise ApiError(422, "validation_error", "by needs at least one field")
    return tuple(f for f in CELL_FIELDS if f in fields)


def signed_map(
    rows: Sequence[GradeRow],
    projection: Sequence[str],
    session: Session,
    repo: str,
    *,
    controls: ControlsVerdict | None = None,
) -> tuple[CapabilityMap, int]:
    """The projection's map with the repo's active sign-offs overlaid; returns the number
    of sign-off records considered. ``controls`` is the verdict every cell is routed
    under (``None`` = not evaluated — the forecast/sign-off callers' contract today)."""
    records = load_signoff_records(session, repo)
    cmap = build_capability_map(
        rows, projection=projection, policy=DEFAULT_POLICY, controls=controls
    )
    return apply_signoffs_to_map(cmap, records, repo=repo), len(records)


def controls_out(verdict: ControlsVerdict) -> ControlsVerdictOut:
    return ControlsVerdictOut(**verdict_dict(verdict, DEFAULT_POLICY))


def split_out(c: CapabilityCell) -> FailureSplitOut:
    return FailureSplitOut(
        builder_red=c.n_builder_red,
        budget=c.n_budget,
        protocol=c.n_protocol,
        harness=c.n_harness,
        disqualified=c.n_disqualified,
    )


def cell_out(c: CapabilityCell) -> CapabilityCellSplitOut:
    assert c.stats is not None and c.decision is not None  # only measured cells are serialised
    s = c.stats
    return CapabilityCellSplitOut(
        **c.key.to_dict(),
        label=c.label,
        n=s.n,
        clean=s.clean,
        disqualified=s.disqualified,
        errors=s.errors,
        rows=c.rows,
        repos=c.repos,
        point=round(s.point, 4),
        ci_low=round(s.ci.low, 4),
        ci_high=round(s.ci.high, 4),
        sigma=None if c.sigma is None else round(c.sigma, 4),
        false_q1=s.false_q1,
        cost_usd_mean=round(s.cost_usd_mean, 6),
        latency_s_mean=round(s.latency_s_mean, 3),
        cost_known=c.cost_known,
        latency_known=c.latency_known,
        oracle_strength_mean=(
            None if s.oracle_strength_mean is None else round(s.oracle_strength_mean, 4)
        ),
        route=c.route,
        reason=c.decision.reason,
        reason_code=c.decision.reason_code,
        verification_tier=c.verification_tier or "automated-pass",
        apparatus_versions=list(s.apparatus_versions),
        belt_set=",".join(c.belt_sets),
        belt_sets=list(c.belt_sets),
        n_builder_red=s.n_builder_red,
        n_budget=s.n_budget,
        n_protocol=s.n_protocol,
        n_harness=s.n_harness,
        n_disqualified=s.n_disqualified,
        model_n=s.model_n,
        model_point=None if c.model_point is None else round(c.model_point, 4),
        model_ci_low=round(s.model_ci.low, 4),
        model_ci_high=round(s.model_ci.high, 4),
        failure_split=split_out(c),
    )


def _distinct(rows: Sequence[GradeRow], field: str) -> list[str]:
    values = {getattr(r, field) for r in rows}
    if field == "size":
        return [s for s in SIZE_TIER_NAMES if s in values]
    return sorted(v for v in values if v)


def _coverage(
    session: Session, repo: str, rows: Sequence[GradeRow], controls: ControlsVerdict
) -> tuple[float | None, float | None, int | None]:
    """TAC over the cached change profile; ``None`` everywhere when no profile exists."""
    cached = cached_profile(get_repo_or_404(session, repo))
    if cached is None:
        return None, None, None
    profile = RepoChangeProfile.from_dict(dict(cached["profile"]))
    cs_map, _ = signed_map(rows, PROJECTION_CLASS_SIZE, session, repo, controls=controls)
    summary = trusted_autonomy_coverage(profile, rows, cells=cs_map, policy=DEFAULT_POLICY)
    return round(summary.coverage, 4), round(summary.earned_coverage, 4), profile.n_commits


@router.get(
    "/capability-map",
    response_model=CapabilityMapWithControlsOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Measured cells of one repo under the routing rule + controls verdict, sign-offs overlaid",
)
def capability_map(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    by: str | None = Query(default=None, max_length=128),
) -> CapabilityMapWithControlsOut:
    del viewer
    get_repo_or_404(db, repo)
    projection = parse_by(by)
    rows = list(DbLedger(factory).rows(repo=repo))
    controls = latest_controls_verdict(db, repo)
    cmap, n_signoffs = signed_map(rows, projection, db, repo, controls=controls)
    cells = [c for c in cmap.cells if c.measured]
    by_route = {route: len(cs) for route, cs in cmap.by_route().items()}
    grid = 1
    for f in projection:
        grid *= max(1, len(_distinct(rows, f)))
    tac, earned, commits = _coverage(db, repo, rows, controls)
    return CapabilityMapWithControlsOut(
        repo=repo,
        by=list(projection),
        classes=_distinct(rows, "capability_class"),
        sizes=_distinct(rows, "size"),
        languages=_distinct(rows, "language"),
        models=_distinct(rows, "model"),
        cells=[cell_out(c) for c in cells],
        summary=CapabilitySummary(
            trusted_autonomy_coverage=tac,
            earned_coverage=earned,
            profile_commits=commits,
            total_cells=grid if rows else 0,
            measured_cells=len(cells),
            deliver_cells=sum(1 for c in cells if c.route == ROUTE_DELIVER),
            cells_by_route=by_route,
            n_total=sum(c.n for c in cells),
            rows=cmap.rows,
            false_q1_total=cmap.false_q1_total,
            apparatus_versions=list(cmap.apparatus_versions),
            signoffs_applied=n_signoffs,
        ),
        policy=RoutingPolicyWithControlsOut(**cmap.policy.to_dict()),
        controls=controls_out(controls),
    )


@router.get(
    "/routes",
    response_model=RoutesWithControlsResponse,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Route decisions per (full) cell with reasons, reason codes, the controls verdict and the policy in force",
)
def routes(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    by: str | None = Query(default=None, max_length=128),
) -> RoutesWithControlsResponse:
    del viewer
    get_repo_or_404(db, repo)
    projection = parse_by(by) if by else PROJECTION_CELL
    rows = list(DbLedger(factory).rows(repo=repo))
    controls = latest_controls_verdict(db, repo)
    cmap, _ = signed_map(rows, projection, db, repo, controls=controls)
    decisions: list[RouteDecisionWithControlsOut] = []
    for c in cmap.cells:
        if c.decision is None or c.stats is None:
            continue
        d = c.decision.to_dict()
        d["controls"] = None if c.decision.controls is None else verdict_dict(c.decision.controls)
        decisions.append(
            RouteDecisionWithControlsOut(
                **d,
                label=c.label,
                verification_tier=c.verification_tier or "automated-pass",
                apparatus_versions=list(c.stats.apparatus_versions),
                model_n=c.model_n,
                model_point=None if c.model_point is None else round(c.model_point, 4),
                failure_split=split_out(c),
            )
        )
    return RoutesWithControlsResponse(
        repo=repo,
        by=list(projection),
        policy=RoutingPolicyWithControlsOut(**cmap.policy.to_dict()),
        decisions=decisions,
        controls=controls_out(controls),
    )


@router.get(
    "/failure-split",
    response_model=FailureSplitResponse,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="The failure_kind split (and both rates) over a repo's rows, or one run's",
)
def failure_split_route(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    run_id: str = Query(default="", max_length=32),
) -> FailureSplitResponse:
    """``clean · builder_red · budget · protocol · harness`` (= n) + ``disqualified``
    over the repo's rows, or the run's when ``run_id`` is given, with the all-rows
    point and the model point side by side. An unknown ``run_id`` answers an empty
    split (n = 0), never an invented one."""
    del viewer
    get_repo_or_404(db, repo)
    rows = list(DbLedger(factory).rows(repo=repo, run_id=run_id or None))
    split = failure_split(rows)
    return FailureSplitResponse(repo=repo, run_id=run_id, **split.to_dict())


__all__ = [
    "BY_ALIASES",
    "DEFAULT_BY",
    "cell_out",
    "controls_out",
    "parse_by",
    "router",
    "signed_map",
    "split_out",
]
