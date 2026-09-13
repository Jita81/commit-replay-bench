"""``/forecast/build`` and ``/forecast/readiness`` — price a mix before building it.

``mix`` is ``class:size:count,...`` (``size`` may be empty for a size-less class
key). Both routes resolve every component exactly as the factory would route it
(:mod:`crb.core.forecast` over the repo's rows with its active sign-offs overlaid).
A component the ledger has never measured is listed in ``unmeasured`` and priced
at nothing — no number is fabricated for it.

``/forecast/readiness`` without ``mix`` uses the repo's cached change profile as
the mix ("is the evidence ready for what this repo actually changes?"); a repo with
neither a profile nor an explicit mix answers ``409 no_profile``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from crb.core.capability import RepoChangeProfile
from crb.core.forecast import (
    DEFAULT_THRESHOLDS,
    ComponentKey,
    assess_readiness,
    forecast_build,
    parse_component_key,
)
from crb.core.routing import DEFAULT_POLICY
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.repos import cached_profile, get_repo_or_404
from crb.server.routes.signoffs import load_signoff_records
from crb.server.schemas import (
    ComponentForecastOut,
    ForecastBuildOut,
    ForecastMixItem,
    ForecastReadinessOut,
    ReadinessThresholdsOut,
)
from crb.store.ledger import DbLedger

router = APIRouter(tags=["forecast"])
_ERR = {"model": ErrorEnvelope}

MAX_MIX_ITEMS = 500


def parse_mix(mix: str) -> dict[ComponentKey, int]:
    """``"bug.fix:S:4,docs.update::1"`` → ``{("bug.fix", "S"): 4, ("docs.update", ""): 1}``.

    Malformed items are an input mistake (422), not an unmeasured component.
    """
    out: dict[ComponentKey, int] = {}
    items = [p.strip() for p in mix.split(",") if p.strip()]
    if not items:
        raise ApiError(422, "validation_error", "mix is empty; expected class:size:count,...")
    if len(items) > MAX_MIX_ITEMS:
        raise ApiError(422, "validation_error", f"mix has more than {MAX_MIX_ITEMS} items")
    for item in items:
        parts = item.split(":")
        if len(parts) == 2:
            cls, size, count_s = parts[0], "", parts[1]
        elif len(parts) == 3:
            cls, size, count_s = parts
        else:
            raise ApiError(
                422,
                "validation_error",
                f"mix item {item!r} must be class:size:count",
                detail={"item": item},
            )
        if size == "*":
            size = ""
        try:
            key = parse_component_key((cls, size))
            count = int(count_s)
        except ValueError as exc:
            raise ApiError(
                422, "validation_error", f"mix item {item!r}: {exc}", detail={"item": item}
            ) from exc
        if count < 0:
            raise ApiError(422, "validation_error", f"mix item {item!r}: count cannot be negative")
        out[key] = out.get(key, 0) + count
    return out


def _mix_items(mix: dict[ComponentKey, int]) -> list[ForecastMixItem]:
    out: list[ForecastMixItem] = []
    for key, n in mix.items():
        cls, size = parse_component_key(key)
        out.append(ForecastMixItem(capability_class=cls, size=size, count=n))
    return out


@router.get(
    "/forecast/build",
    response_model=ForecastBuildOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Ex-ante forecast for a mix: cost mean/stddev, minutes, routed counts, expected clean",
)
def forecast_build_route(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    mix: str = Query(min_length=1, max_length=20_000),
) -> ForecastBuildOut:
    del viewer
    get_repo_or_404(db, repo)
    parsed = parse_mix(mix)
    rows = list(DbLedger(factory).rows(repo=repo))
    f = forecast_build(
        parsed, rows, policy=DEFAULT_POLICY, signoffs=load_signoff_records(db, repo), repo=repo
    )
    d = f.to_dict()
    return ForecastBuildOut(
        repo=repo,
        mix=_mix_items(parsed),
        cost_usd_mean=d["total_cost_mean"],
        cost_usd_std=d["total_cost_stddev"],
        minutes=d["total_build_minutes"],
        deliver=f.deliver,
        human=f.human,
        calibrate=f.calibrate,
        buildable_p=d["p_clean_mean"],
        buildable_p_stddev=d["p_clean_stddev"],
        unmeasured=d["unmeasured"],
        components=d["components"],
        measured_components=d["measured_components"],
        coverage=d["coverage"],
        costed_components=d["costed_components"],
        timed_components=d["timed_components"],
        units_by_route=d["units_by_route"],
        expected_clean_units=d["expected_clean_units"],
        single_rep_band=f.single_rep_band,
        per_component=[ComponentForecastOut(**c) for c in d["per_component"]],
        policy_version=d["policy_version"],
    )


@router.get(
    "/forecast/readiness",
    response_model=ForecastReadinessOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Readiness gate: ok + the punch-list of gaps (mix defaults to the change profile)",
)
def forecast_readiness_route(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    mix: str | None = Query(default=None, max_length=20_000),
) -> ForecastReadinessOut:
    del viewer
    repo_row = get_repo_or_404(db, repo)
    parsed: dict[ComponentKey, int]
    if mix:
        parsed = parse_mix(mix)
        source = "mix"
    else:
        cached = cached_profile(repo_row)
        if cached is None:
            raise ApiError(
                409,
                "no_profile",
                f"repo {repo!r} has no change profile; pass ?mix= or GET /repos/{repo}/profile first",
                detail={"repo": repo},
            )
        profile = RepoChangeProfile.from_dict(dict(cached["profile"]))
        parsed = {(cls, size): n for (cls, size), n in profile.ranked()}
        source = "profile"
    rows = list(DbLedger(factory).rows(repo=repo))
    r = assess_readiness(
        parsed,
        rows,
        thresholds=DEFAULT_THRESHOLDS,
        policy=DEFAULT_POLICY,
        signoffs=load_signoff_records(db, repo),
        repo=repo,
    )
    d = r.to_dict()
    return ForecastReadinessOut(
        repo=repo,
        ok=d["ok"],
        gaps=d["gaps"],
        mix=_mix_items(parsed),
        mix_source=source,
        total=d["total"],
        measured=d["measured"],
        coverage=d["coverage"],
        min_reps_seen=d["min_reps_seen"],
        earned_units=d["earned_units"],
        buildable_units=d["buildable_units"],
        buildable_frac=d["buildable_frac"],
        false_q1_total=d["false_q1_total"],
        thresholds=ReadinessThresholdsOut(**d["thresholds"]),
        policy_version=d["policy_version"],
    )


__all__ = ["MAX_MIX_ITEMS", "parse_mix", "router"]
