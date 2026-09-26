"""``GET /value`` — the scorecard: working changes per pound, blind, and whether the loop learns.

One read-only route over the store: the ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load and the request answers
``409 false_q1_refused``) and the standing review per graded row, reduced by
:func:`crb.core.value.value_report`. ``repo`` scopes it to one repository (404 when unknown);
without it the report covers every repository and lists each one's north star. ``apparatus``
defaults to the current version — pooling is ``apparatus=all`` and the response says it pooled.
The bug register behind the learning curve is the prevention loop's
(:func:`crb.core.value.default_register` over every repository's verified chain); the response
names it.

Navigation
----------
What it is:   The ``/value`` route module — the scorecard the Home tile reads.
What it does: Serves ``ValueReport.to_dict()`` for one repository or all of them: the north star
              with its n, interval, method and apparatus; clean → working precision (reviews or
              the labelled proxy); the process-loss share in pounds; the learning curve; the
              prospective routing precision. Never writes and never calls a model.
How:          ``DbLedger.rows`` (every repository — the pooled-review fallback needs them) →
              ``value_row_from_grade``; ``DbReviewLedger.records`` → ``verdicts_from_reviews``
              (latest per row, joined to its row); ``all_prevention_records`` → the register →
              ``value_report`` scoped to ``repo``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/value.py (the report), src/crb/store/ledger.py (the rows and the
              reviews), src/crb/server/routes/repos.py (``get_repo_or_404``),
              src/crb/server/prevention_state.py (the loop's chain and mechanisms),
              ui/src/screens/Home/ValueTile.tsx (the tile that reads it), docs/API.md (the row)
Tested by:    tests/test_server_routes_value.py
Touch when:   never for a new repository; a scorecard field is added in src/crb/core/value.py
              (update docs/API.md and ui/src/api/types.ts with it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from crb.core.ledger import LedgerIntegrityError
from crb.core.value import (
    DEFAULT_USD_PER_GBP,
    DEFAULT_WINDOW,
    REVIEWS_FROM_STORE,
    default_register,
    value_report,
    value_row_from_grade,
    verdicts_from_reviews,
)
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.prevention_state import all_prevention_records, mechanisms
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
    grades = list(DbLedger(factory).rows())
    rows = [value_row_from_grade(r) for r in grades]
    by_hash = {r.row_hash: r for r in rows if r.row_hash}
    reviews = list(DbReviewLedger(factory).records())
    verdicts = verdicts_from_reviews(reviews, by_hash)
    # the learning curve reads the prevention loop's register: its chain (every repository's,
    # each verified) and the reviews that class review defects. A chain that does not verify
    # is a 409 that says so — never a curve served as if nothing were wrong
    try:
        records = all_prevention_records(db)
    except LedgerIntegrityError as exc:
        raise ApiError(
            409,
            "prevention_chain_broken",
            f"a prevention chain does not verify: {exc} — the learning curve is not served "
            "until an operator restores it from the database backup",
        ) from exc
    register = default_register(
        records,
        reviews=reviews,
        mechanisms=mechanisms(rows=grades, repo=repo or ""),
        packs=DbLedger(factory).get_pack,
    )
    return value_report(
        rows,
        verdicts,
        repo=repo,
        apparatus=apparatus,
        window=window,
        usd_per_gbp=usd_per_gbp,
        register=register,
        reviews_source=REVIEWS_FROM_STORE,
    ).to_dict()


__all__ = ["router"]
