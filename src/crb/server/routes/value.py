"""``GET /value`` — the scorecard: working changes per pound, blind, and whether the loop learns.

One read-only route over the store: the ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load and the request answers
``409 false_q1_refused``) and the standing review per graded row, reduced by
:func:`crb.core.value.value_report`. ``repo`` scopes it to one repository (404 when unknown);
without it the report covers every repository and lists each one's north star. ``apparatus``
defaults to the current version — pooling is ``apparatus=all`` and the response says it pooled.
The bug register behind the learning curve is :func:`crb.core.value.default_register` (a stub
until the prevention loop is wired; the response names it).

Navigation
----------
What it is:   The ``/value`` route module — the scorecard the Home tile reads.
What it does: Serves ``ValueReport.to_dict()`` for one repository or all of them: the north star
              with its n, interval, method and apparatus; clean → working precision (reviews or
              the labelled proxy); the process-loss share in pounds; the learning curve; the
              prospective routing precision. Never writes and never calls a model.
How:          ``DbLedger.rows`` (every repository — the pooled-review fallback needs them) →
              ``value_row_from_grade``; ``DbReviewLedger.records`` → ``verdicts_from_reviews``
              (latest per row, joined to its row) → ``value_report`` scoped to ``repo``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/value.py (the report), src/crb/store/ledger.py (the rows and the
              reviews), src/crb/server/routes/repos.py (``get_repo_or_404``),
              ui/src/screens/Home/ValueTile.tsx (the tile that reads it), docs/API.md (the row)
Tested by:    tests/test_server_routes_value.py
Touch when:   never for a new repository; a scorecard field is added in src/crb/core/value.py
              (update docs/API.md and ui/src/api/types.ts with it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from crb.core.value import (
    DEFAULT_USD_PER_GBP,
    DEFAULT_WINDOW,
    value_report,
    value_row_from_grade,
    verdicts_from_reviews,
)
from crb.server.auth import ViewerDep
from crb.server.deps import DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.repos import get_repo_or_404
from crb.store.ledger import DbLedger, DbReviewLedger

router = APIRouter(tags=["value"])
_ERR = {"model": ErrorEnvelope}


@router.get(
    "/value",
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="The value scorecard — working changes per pound (blind), precision, loss, learning",
)
def value(  # noqa: PLR0917 — FastAPI dependencies + query params
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str | None = Query(default=None, min_length=1, max_length=64),
    apparatus: str = Query(default="current", max_length=32),
    window: int = Query(default=DEFAULT_WINDOW, ge=5, le=1000),
    usd_per_gbp: float = Query(default=DEFAULT_USD_PER_GBP, gt=0.2, le=5.0),
) -> dict[str, Any]:
    del viewer
    if repo is not None:
        get_repo_or_404(db, repo)
    # every repository is read even for one: a repository with too few reviews borrows every
    # repository's before it falls back to the proxy, and a false-Q1 row anywhere refuses
    rows = [value_row_from_grade(r) for r in DbLedger(factory).rows()]
    by_hash = {r.row_hash: r for r in rows if r.row_hash}
    verdicts = verdicts_from_reviews(DbReviewLedger(factory).records(), by_hash)
    return value_report(
        rows,
        verdicts,
        repo=repo,
        apparatus=apparatus,
        window=window,
        usd_per_gbp=usd_per_gbp,
    ).to_dict()


__all__ = ["router"]
