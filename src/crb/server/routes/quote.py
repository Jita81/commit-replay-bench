"""``GET /quote/mapping`` — what a first mapping of a repository would run, cost and take.

Read-only: it writes nothing, calls no model and no network, and never walks the repository's
history (the cached change profile is read as it stands). The arithmetic is
:mod:`crb.core.quote`; this module only gathers what the core reads — the gold-clean tasks
available per cell, and the first-rung sighted replay rows of the builder and model under the
target repository's checks arm and posture class, split into its own and every other
repository's — and adds whether the price table knows the model.

Navigation
----------
What it is:   The ``GET /quote/mapping`` route module — the read-only quote of a first mapping
              (a sighted single-rung replay): tasks, recorded cost, builder time and precision.
What it does: Validates ``n`` / ``cells`` / ``pool`` / ``declared`` (422; ``n`` with ``cells``
              is refused) and resolves the model (422 when the builder has no default); counts
              the gold-clean tasks per cell; only when nothing is mined, falls back to the
              cached change profile served as an upper bound (409 ``no_tasks`` with no profile
              or with a ``pool``, which a profile cannot split, and when tasks are mined but
              none is available and no cell is named); prices every cell from the core quote;
              flags a model the price table cannot see.
How:          ``get_repo_or_404`` → ``parse_mix`` for ``cells`` → a ``GROUP BY`` over ``tasks``
              (or ``cached_profile``) → one ``rows_of_rung`` read → ``rows_for_arm`` and
              ``filter_posture`` at the target repository → ``mapping_quote(...).to_dict()`` →
              ``unpriced_rungs`` over ``load_pricing`` → ``MappingQuoteOut``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0058-mapping-quote.md
Works with:   src/crb/core/quote.py (all the arithmetic), src/crb/server/routes/forecast.py
              (``parse_mix``, the forecast's cell grammar), src/crb/server/routes/capability.py
              (``rows_for_arm`` and ``filter_posture``, the map's default view),
              src/crb/store/ledger.py (``rows_of_rung``, the one filtered read),
              src/crb/server/routes/repos.py (``cached_profile`` for the fallback),
              src/crb/server/spend_cap.py (``unpriced_rungs`` for ``model_priced``),
              src/crb/server/schemas_quote.py (the response shapes), docs/API.md (the row)
Tested by:    tests/test_server_routes_quote.py
Touch when:   never for a new repository; a parameter, a default or an error code of the
              quote changes (with docs/API.md, docs/MCP.md and src/crb/mcp/server.py).
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from crb.builders.budget import load_pricing
from crb.core.capability import RepoChangeProfile
from crb.core.forecast import parse_component_key
from crb.core.ledger import PROCESS_REPLAY, GradeRow
from crb.core.quote import (
    AVAILABILITY_MINED,
    AVAILABILITY_PROFILE,
    LADDER,
    MODE_SIGHTED,
    CellKey,
    default_n,
    mapping_quote,
)
from crb.core.spec import POOL_HARD, POOL_STANDARD
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.routes.capability import (
    CHECKS_CURRENT,
    POSTURE_DEPLOYMENT,
    filter_posture,
    rows_for_arm,
)
from crb.server.routes.forecast import parse_mix
from crb.server.routes.repos import cached_profile, get_repo_or_404
from crb.server.routes.runs import default_model_for
from crb.server.schemas_quote import MappingQuoteOut
from crb.server.spend_cap import unpriced_rungs
from crb.store.ledger import rows_of_rung
from crb.store.models import Repo, Task

router = APIRouter(tags=["quote"])
_ERR = {"model": ErrorEnvelope}

MAX_TASKS_PER_CELL = 1000
POOLS = ("", POOL_STANDARD, POOL_HARD)


def _bad(message: str, **detail: object) -> ApiError:
    return ApiError(422, "validation_error", message, detail=dict(detail))


def parse_declared(declared: str) -> tuple[float, float] | None:
    """``"0.01:0.05"`` → ``(0.01, 0.05)`` USD per attempt; ``""`` → ``None``; 422 otherwise."""
    if not declared:
        return None
    parts = declared.split(":")
    try:
        low, high = (float(p) for p in parts) if len(parts) == 2 else (math.nan, math.nan)
    except ValueError:
        low, high = math.nan, math.nan
    if not (math.isfinite(low) and math.isfinite(high)) or not 0 <= low <= high:
        raise _bad(
            f"declared {declared!r} must be low:high USD per attempt with 0 <= low <= high",
            declared=declared,
        )
    return low, high


def parse_cells(cells: str) -> dict[CellKey, int] | None:
    """``cells`` in the forecast's ``class:size:count`` grammar (``*`` = every size of the
    class), each count 1 to :data:`MAX_TASKS_PER_CELL`; ``""`` → ``None`` (every cell)."""
    if not cells:
        return None
    parsed: dict[CellKey, int] = {}
    for key, n in parse_mix(cells).items():
        cell = parse_component_key(key)
        parsed[cell] = parsed.get(cell, 0) + n
    for (cls, size), n in parsed.items():
        if not 1 <= n <= MAX_TASKS_PER_CELL:
            raise _bad(
                f"cells: {cls}:{size or '*'} asks for {n} tasks; expected 1 to "
                f"{MAX_TASKS_PER_CELL}",
                capability_class=cls,
                size=size,
                count=n,
            )
    return parsed


def available_tasks(db: Session, repo: str, pool: str) -> dict[CellKey, int]:
    """The gold-clean tasks per (class, size) — the pool a replay draws from."""
    q = select(Task.capability_class, Task.size, func.count()).where(
        Task.repo == repo, Task.gold_clean.is_(True)
    )
    if pool:
        q = q.where(Task.pool == pool)
    q = q.group_by(Task.capability_class, Task.size)
    return {(str(c), str(s)): int(n) for c, s, n in db.execute(q).all()}


def mined_task_count(db: Session, repo: str) -> int:
    """Every task mined for the repository, clean or not, in any pool: zero only when the
    repository was never mined — the one case the change profile stands in for the tasks."""
    return int(db.scalar(select(func.count()).select_from(Task).where(Task.repo == repo)) or 0)


def basis_rows(
    db: Session,
    factory: sessionmaker[Session],
    settings: object,
    *,
    repo: str,
    builder: str,
    model: str,
) -> list[GradeRow]:
    """Every repository's first-rung sighted replay rows of the builder and model, filtered to
    the TARGET repository's checks arm and posture class (ADR-0024, ADR-0019 §8): a cost
    measured under another arm or class is never pooled into this repository's quote."""
    rows = [
        r
        for trial in LADDER
        for r in rows_of_rung(
            db,
            builder=builder,
            model=model,
            mode=MODE_SIGHTED,
            process_step=PROCESS_REPLAY,
            trial=trial,
        )
    ]
    rows = rows_for_arm(factory, repo, rows, CHECKS_CURRENT)
    return filter_posture(db, repo, rows, POSTURE_DEPLOYMENT, settings).rows


def _available(
    db: Session, repo_row: Repo, pool: str, selection: dict[CellKey, int] | None
) -> tuple[dict[CellKey, int], str]:
    repo = repo_row.name
    available = available_tasks(db, repo, pool)
    if available:
        return available, AVAILABILITY_MINED
    mined = mined_task_count(db, repo)
    if mined:
        if selection is not None:
            return {}, AVAILABILITY_MINED  # the named cells are quoted at zero tasks
        where = f" in the {pool} pool" if pool else ""
        raise ApiError(
            409,
            "no_tasks",
            f"repo {repo!r} has {mined} mined tasks but none is gold-clean{where}: there is "
            "nothing to replay",
            detail={"repo": repo, "mined": mined, "pool": pool},
        )
    cached = cached_profile(repo_row)
    if cached is None:
        raise ApiError(
            409,
            "no_tasks",
            f"repo {repo!r} has no mined task and no change profile: mine the repository or "
            "compute its profile first",
            detail={"repo": repo},
        )
    if pool:
        raise ApiError(
            409,
            "no_tasks",
            f"repo {repo!r} has no mined task, and its change profile cannot tell the "
            f"{pool} pool from the rest: mine the repository, or drop pool",
            detail={"repo": repo, "pool": pool},
        )
    profile = RepoChangeProfile.from_dict(dict(cached["profile"]))
    return {key: int(count) for key, count in profile.cells.items()}, AVAILABILITY_PROFILE


def _model_priced(builder: str, model: str) -> tuple[bool | None, str]:
    try:
        table = load_pricing()
    except (OSError, ValueError):
        return None, "the price table could not be read, so whether it prices the model is unknown"
    if unpriced_rungs([(builder, model)], table):
        return False, (
            f"the price table has no price for {model!r}: its rows would record no known cost, "
            "and a run's spend cap could not see it"
        )
    return True, ""


@router.get(
    "/quote/mapping",
    response_model=MappingQuoteOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Read-only quote of a first mapping: tasks, recorded cost, builder time, precision",
)
def mapping_quote_route(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    *,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
    builder: str = Query(min_length=1, max_length=64),
    model: str = Query(default="", max_length=200),
    n: int | None = Query(default=None, ge=1, le=MAX_TASKS_PER_CELL),
    cells: str = Query(default="", max_length=20_000),
    pool: str = Query(default="", max_length=32),
    declared: str = Query(default="", max_length=64),
) -> MappingQuoteOut:
    del viewer
    repo_row = get_repo_or_404(db, repo)
    if pool not in POOLS:
        raise _bad(f"pool {pool!r} must be standard, hard or empty", pool=pool)
    band = parse_declared(declared)
    model = model or default_model_for(builder)
    if not model:
        raise _bad(f"builder {builder!r} has no default model; pass ?model=", builder=builder)
    if n is not None and cells:
        raise _bad("pass n or cells, not both: cells names each cell's count", n=n, cells=cells)
    selection = parse_cells(cells)
    n_default = n if n is not None else default_n()

    available, source = _available(db, repo_row, pool, selection)
    rows = basis_rows(db, factory, settings, repo=repo, builder=builder, model=model)
    own_rows = [r for r in rows if r.repo == repo]
    other_rows = [r for r in rows if r.repo != repo]
    body = mapping_quote(
        repo=repo,
        builder=builder,
        model=model,
        available=available,
        availability_source=source,
        own_rows=own_rows,
        other_rows=other_rows,
        n_default=n_default,
        selection=selection,
        declared=band,
    ).to_dict()
    priced, why = _model_priced(builder, model)
    return MappingQuoteOut(**body, model_priced=priced, model_priced_reason=why)


__all__ = [
    "MAX_TASKS_PER_CELL",
    "available_tasks",
    "basis_rows",
    "mined_task_count",
    "parse_cells",
    "parse_declared",
    "router",
]
