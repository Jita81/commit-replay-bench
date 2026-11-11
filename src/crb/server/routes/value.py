"""``GET /value`` — the scorecard: working changes per pound, blind, and whether the loop learns.

One read-only route over the store: the ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load and the request answers
``409 false_q1_refused``) and the standing review per graded row, reduced by
:func:`crb.core.value.value_report`. ``repo`` scopes it to one repository (404 when unknown);
without it the report covers every repository and lists each one's north star. ``apparatus``
defaults to the current version — pooling is ``apparatus=all`` and the response says it pooled.
``checks`` is the one checks arm the headline reads (ADR-0024; there is no pooled view): by
default the repository's own arm (``checks_arm_in``) when ``repo`` is given and ``off`` for the
cross-repository report; the response names it in ``checks``.
``posture`` is the one posture class every figure reads (ADR-0019 §8: a filter, never a blend
— P-135), as on the capability map: by default the deployment's own class (the repository's,
when ``repo`` is given — its ``sandbox_tree`` can change it); ``posture=<class>`` reads that
class; ``posture=all`` reads the one class the scope holds and refuses two with ``422
posture_pooling_refused`` (``detail.present`` names them) — the map pools rates over
fingerprint-invariant tasks, but a pound is never invariant across postures. A row from before
2.3 is placed by its run's executor (``legacy:local`` reads as ``local/inplace/host-env``); a
``legacy:docker`` row is in no figure and is counted ``unqualified_posture``.
The bug register behind the learning curve is the prevention loop's
(:func:`crb.core.value.default_register` over every repository's verified chain); the response
names it.

Navigation
----------
What it is:   The ``/value`` route module — the scorecard the Home tile reads.
What it does: Serves ``ValueReport.to_dict()`` for one repository or all of them: the north star
              with its n, interval, method and apparatus; clean → working precision (reviews or
              the labelled proxy); the process-loss share in pounds; the learning curve; the
              prospective routing precision — every figure over one posture class, named
              in ``posture_class``, and only that class's reading outcomes (each naming
              it; others counted in ``readings_other_posture``). Never writes and never
              calls a model.
How:          ``DbLedger.rows`` (every repository — the pooled-review fallback needs them) →
              ``value_row_from_grade`` with each row's comparable class
              (``row_posture_class`` / ``comparable_class``, the map's rule);
              ``DbReviewLedger.records`` → ``verdicts_from_reviews``
              (latest per row, joined to its row); ``all_prevention_records`` → the register →
              ``value_report`` scoped to ``repo`` and the posture class.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0024-working-by-construction.md,
              docs/adr/0019-qualification-is-posture-relative.md (§8: one posture class)
Works with:   src/crb/core/value.py (the report), src/crb/store/ledger.py (the rows and the
              reviews), src/crb/server/routes/repos.py (``get_repo_or_404``),
              src/crb/server/routes/capability.py (the map's posture rule and vocabulary),
              src/crb/server/posture_view.py (``deployment_posture_class``),
              src/crb/server/prevention_state.py (the loop's chain and mechanisms),
              ui/src/screens/Home/ValueTile.tsx (the tile that reads it), docs/API.md (the row)
Tested by:    tests/test_server_routes_value.py
Touch when:   never for a new repository; a scorecard field is added in src/crb/core/value.py
              (update docs/API.md and ui/src/api/types.ts with it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from crb.core.capability import ReadingBook
from crb.core.checks import ARM_OFF
from crb.core.ledger import LedgerIntegrityError
from crb.core.value import (
    DEFAULT_USD_PER_GBP,
    DEFAULT_WINDOW,
    REVIEWS_FROM_STORE,
    PosturePoolingError,
    default_register,
    select_rows,
    value_report,
    value_row_from_grade,
    verdicts_from_reviews,
)
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.posture_view import deployment_posture_class
from crb.server.prevention_state import all_prevention_records, current_checks_arm, mechanisms
from crb.server.routes.capability import (
    CHECKS_CURRENT,
    CHECKS_PATTERN,
    LEGACY_CLASS_PREFIX,
    POSTURE_DEPLOYMENT,
    comparable_class,
    legacy_executor_lookup,
    row_posture_class,
)
from crb.server.routes.readings import budget_by_cell, load_readings
from crb.server.routes.repos import get_repo_or_404
from crb.store.ledger import DbLedger, DbReviewLedger

router = APIRouter(tags=["value"])
_ERR = {"model": ErrorEnvelope}
#: A pre-2.3 row the sandbox graded against a baseline measured elsewhere: in no figure.
_LEGACY_DOCKER = LEGACY_CLASS_PREFIX + "docker"


@router.get(
    "/value",
    responses={
        401: _ERR,
        404: _ERR,
        409: _ERR,
        422: {
            "model": ErrorEnvelope,
            "description": "a query parameter is invalid, or ``posture_pooling_refused``: "
            "``posture=all`` over rows of two posture classes (``detail.present``) — ADR-0019 "
            "§8, posture is a filter, never a blend; name one with ``posture=<class>``",
        },
    },
    summary="The value scorecard — working changes per pound (blind), precision, loss, learning",
)
def value(  # noqa: PLR0917 — FastAPI dependencies + query params
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str | None = Query(default=None, min_length=1, max_length=64),
    apparatus: str = Query(default="current", max_length=32),
    window: int = Query(default=DEFAULT_WINDOW, ge=5, le=1000),
    usd_per_gbp: float = Query(default=DEFAULT_USD_PER_GBP, gt=0.2, le=5.0),
    checks: str = Query(default=CHECKS_CURRENT, pattern=CHECKS_PATTERN),
    posture: str = Query(default=POSTURE_DEPLOYMENT, max_length=64),
) -> dict[str, Any]:
    del viewer
    repo_row = get_repo_or_404(db, repo) if repo is not None else None
    # the headline reads one arm: the repository's own, or ``off`` across repositories
    if checks == CHECKS_CURRENT:
        checks = current_checks_arm(factory, repo) if repo is not None else ARM_OFF
    # every figure reads one posture class (ADR-0019 §8): the deployment's own by default —
    # the repository's when one is named — as the capability map reads it
    if posture in ("", POSTURE_DEPLOYMENT):
        posture = deployment_posture_class(settings, repo_row)
    # every repository is read even for one: a repository with too few reviews borrows every
    # repository's before it falls back to the proxy, and a false-Q1 row anywhere refuses
    grades = list(DbLedger(factory).rows())
    legacy_of = legacy_executor_lookup(db)
    classed = [(g, comparable_class(row_posture_class(g, legacy_of))) for g in grades]
    rows = [value_row_from_grade(g, posture_class=c) for g, c in classed if c != _LEGACY_DOCKER]
    unqualified = select_rows(
        (value_row_from_grade(g) for g, c in classed if c == _LEGACY_DOCKER),
        repo=repo,
        apparatus=apparatus,
    )
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
    try:
        report = value_report(
            rows,
            verdicts,
            repo=repo,
            apparatus=apparatus,
            window=window,
            usd_per_gbp=usd_per_gbp,
            register=register,
            reviews_source=REVIEWS_FROM_STORE,
            checks=checks,
            posture=posture,
        ).to_dict()
    except PosturePoolingError as exc:
        raise ApiError(
            422,
            "posture_pooling_refused",
            f"{exc} — name one with posture=<class>",
            detail={"present": list(exc.classes)},
        ) from exc
    # a pre-2.3 row the sandbox graded: in no figure, and counted (as on the map)
    report["unqualified_posture"] = len(unqualified)
    # ADR-0026: the repository's registered readings, one state per context arm (the loop on
    # and off are two arms), with each cell's budget spent — read over every arm's rows. Only
    # the readings of the one posture class the figures read are served, each naming it; one
    # of another class is counted (ADR-0019 §8). A cell's budget spans postures: unchanged
    if repo is not None:
        readings = load_readings(db, repo)
        book = ReadingBook.evaluate(readings, (g for g in grades if g.repo == repo))
        read = report["posture_class"]
        report["readings"] = [
            {**o.to_dict(), "posture_class": o.reading.posture_class}
            for o in book.outcomes
            if o.reading.posture_class == read
        ]
        report["readings_other_posture"] = len(book.outcomes) - len(report["readings"])
        report["reading_budgets"] = budget_by_cell(readings)
    return report


__all__ = ["router"]
