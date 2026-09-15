"""``/reviews`` — a human's post-hoc verdict on ONE graded row, as a ledger row.

The 2026-09-13 critical-friend review (§5 plays 05/07, action #3) found that a
reviewer's finding on an accepted patch had nowhere to live. It lives here: the
``reviews`` table is append-only and hash-chained on its own (``prev_hash`` = the
previous review's ``row_hash``; ``row_hash`` over the canonical row), every record
names the graded row it is about (``grade_row_hash``) and is ANCHORED to the exact
bytes the reviewer read:

``POST /reviews`` (operator or above; CSRF as every write):

1. resolves the graded row by ``grade_row_hash`` (404) and its stored evidence pack;
2. builds the :class:`~crb.core.review.ReviewRecord` — the verdict is DERIVED from the
   findings by the core's one rule and a client-sent ``verdict`` must agree; every
   construction error is **422 validation_error**;
3. applies the patch-hash anchor (:func:`crb.core.review.check_patch_anchor`): the
   body's ``patch_sha256`` — the hash of the patch the reviewer LOADED through
   ``GET /grades/{row_hash}/patch`` — must equal the pack's ``diff_sha256``, else
   **422 review_refused** with ``detail.code`` (``patch_hash_mismatch`` /
   ``patch_hash_missing`` / ``no_diff_in_pack``), ``detail.expected`` and
   ``detail.observed``; nothing is written and the refusal is a
   ``system/review.refused`` event;
4. chains and inserts under the table's write lock; ``system/review.created``.

Reads are viewer-role. ``GET /reviews/verify`` never raises (it recomputes every hash
from the STORED columns, so a tampered row is reported, not hidden). ``GET
/reviews/stats`` joins the standing verdict per row onto the repo's cells
(:func:`crb.core.review.review_cell_stats`) under the same ``by`` projection the
capability map uses — ``n_reviewed`` / ``n_review_defects`` per cell.

Navigation
----------
What it is:   The ``/reviews`` route module — a human's post-hoc verdict on ONE graded row,
              written as its own hash-chained ledger row.
What it does: Resolves the graded row and its stored pack, derives the verdict from the
              findings (a client-sent verdict must agree), anchors the review to the exact
              patch bytes the reviewer loaded (``patch_sha256`` must equal the pack's
              ``diff_sha256`` — else 422 ``review_refused`` and a ``review.refused`` event,
              nothing written), then chains and inserts through ``DbReviewLedger``. Reads
              serve rows column by column; ``verify`` re-checks every hash and anchor.
How:          ``POST`` = lookup → ``Finding`` / ``derive_verdict`` → ``ReviewRecord`` →
              ``DbReviewLedger.append(record, pack=…)`` → ``review.created`` event;
              ``stats`` joins the standing verdict per row onto the capability projection.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/review.py (``ReviewRecord``, the verdict rule, the anchor),
              src/crb/store/ledger.py (``DbReviewLedger`` — the write path and its lock),
              src/crb/server/routes/grades.py (serves the patch whose hash is attested),
              src/crb/server/schemas_review.py (request / response shapes),
              src/crb/server/routes/capability.py (``parse_by`` for ``/reviews/stats``),
              docs/API.md#reviews-human-verdicts-on-graded-rows
Tested by:    tests/test_server_routes_reviews.py, tests/test_store_reviews.py
Touch when:   never for a new repository; adding a finding kind or verdict is a core change
              (src/crb/core/review.py) mirrored in src/crb/server/schemas_review.py and the
              UI; changing the anchor rule needs an ADR amendment.
Claims:       A review verdict is one named human's statement about one patch — it is
              recorded, never aggregated into a cell's pass rate
              (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.evidence import canonical_json, sha256_text
from crb.core.grade import FalseQ1Violation
from crb.core.ledger import GENESIS_HASH, GradeRow
from crb.core.redact import redact
from crb.core.review import (
    REVIEW_SCHEMA,
    Finding,
    ReviewRecord,
    ReviewRefused,
    derive_verdict,
    pack_diff_sha256,
    review_cell_stats,
)
from crb.observability.events import StepStatus
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.capability import parse_by
from crb.server.routes.grades import grade_to_dict
from crb.server.routes.repos import get_repo_or_404
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas import Page, PageDep
from crb.server.schemas_review import (
    FindingOut,
    ReviewCellStatsOut,
    ReviewCreateRequest,
    ReviewOut,
    ReviewStatsOut,
    ReviewVerifyOut,
)
from crb.store.ledger import DbReviewLedger
from crb.store.models import EvidencePackRow, Grade, Review, Task

router = APIRouter(tags=["reviews"])
_ERR = {"model": ErrorEnvelope}

CODE_REFUSED = "review_refused"
CODE_FALSE_Q1 = "false_q1_refused"

#: The stored columns in ``ReviewRecord`` field order, ``findings`` as ``findings_json``.
REVIEW_FIELDS: tuple[str, ...] = tuple(ReviewRecord.__dataclass_fields__)


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def review_body_from_stored(m: Review) -> dict[str, Any]:
    """The hashed body from the ORM row, WITHOUT constructing :class:`ReviewRecord`
    (whose constructor refuses an inconsistent row — a tampered one must be reported)."""
    d: dict[str, Any] = {}
    for k in REVIEW_FIELDS:
        if k == "row_hash":
            continue
        d[k] = list(m.findings_json or []) if k == "findings" else getattr(m, k)
    return d


def review_hash_from_stored(m: Review) -> str:
    """Recompute ``row_hash`` from the stored columns (the verify walk's comparison)."""
    return sha256_text(canonical_json(review_body_from_stored(m)))


def _subjects(session: Session, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """``(repo, task_id) → commit subject`` for the listed reviews, one query per repo."""
    keys = sorted(set(pairs))
    if not keys:
        return {}
    out: dict[tuple[str, str], str] = {}
    for repo in {r for r, _ in keys}:
        ids = [t for r, t in keys if r == repo]
        q = select(Task.task_id, Task.subject).where(Task.repo == repo, Task.task_id.in_(ids))
        for tid, subj in session.execute(q):
            out[(repo, str(tid))] = str(subj or "")
    return out


def _clean_of(session: Session, hashes: Iterable[str]) -> dict[str, bool]:
    """``row_hash → clean`` for the reviewed rows (shown next to the human verdict)."""
    hs = sorted(set(hashes))
    if not hs:
        return {}
    q = select(Grade.row_hash, Grade.clean).where(Grade.row_hash.in_(hs))
    return {str(h): bool(c) for h, c in session.execute(q)}


def review_out(m: Review, *, subject: str = "", grade_clean: bool | None = None) -> ReviewOut:
    """The stored row as served — column by column (a row that fails the core's
    constructor is still visible to an auditor; ``/reviews/verify`` says why)."""
    return ReviewOut(
        review_id=m.review_id,
        schema=m.schema,
        grade_row_hash=m.grade_row_hash,
        repo=m.repo,
        task_id=m.task_id,
        subject=subject,
        grade_clean=grade_clean,
        reviewer=m.reviewer,
        verdict=m.verdict,
        findings=[
            FindingOut(
                kind=str(f.get("kind", "")),
                note=str(f.get("note", "")),
                file=str(f.get("file", "") or ""),
                line=f.get("line"),
            )
            for f in (m.findings_json or [])
            if isinstance(f, dict)
        ],
        mergeable=m.mergeable,
        statement=m.statement,
        patch_sha256_reviewed=m.patch_sha256_reviewed,
        evidence_pack_hash=m.evidence_pack_hash,
        apparatus_version=m.apparatus_version,
        created=m.created,
        prev_hash=m.prev_hash,
        row_hash=m.row_hash,
    )


def _outs(session: Session, rows: list[Review]) -> list[ReviewOut]:
    """Serialise a page of reviews with subjects and grade verdicts joined in bulk."""
    subjects = _subjects(session, ((r.repo, r.task_id) for r in rows))
    cleans = _clean_of(session, (r.grade_row_hash for r in rows))
    return [
        review_out(
            r,
            subject=subjects.get((r.repo, r.task_id), ""),
            grade_clean=cleans.get(r.grade_row_hash),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get(
    "/reviews",
    response_model=Page[ReviewOut],
    responses={401: _ERR},
    summary="Human reviews as stored (chain order), filterable by repo / task / graded row",
)
def list_reviews(
    viewer: ViewerDep,
    db: DbDep,
    page: PageDep,
    *,
    repo: str | None = Query(default=None, max_length=64),
    task_id: str | None = Query(default=None, max_length=64),
    grade_row_hash: str | None = Query(default=None, max_length=64),
    reviewer: str | None = Query(default=None, max_length=128),
    verdict: str | None = Query(default=None, max_length=16),
) -> Page[ReviewOut]:
    del viewer
    q = select(Review)
    for column, value in (
        (Review.repo, repo),
        (Review.task_id, task_id),
        (Review.grade_row_hash, grade_row_hash),
        (Review.reviewer, reviewer),
        (Review.verdict, verdict),
    ):
        if value:
            q = q.where(column == value)
    rows = list(db.execute(q.order_by(Review.seq)).scalars())
    total = len(rows)
    window = rows[page.offset : page.offset + page.limit]
    return Page[ReviewOut](
        items=_outs(db, window), total=total, limit=page.limit, offset=page.offset
    )


def _iter_reviews(session: Session, batch: int = 1000) -> Iterator[Review]:
    """Every review in ``seq`` order, keyset-paged."""
    last = 0
    while True:
        chunk = list(
            session.execute(
                select(Review).where(Review.seq > last).order_by(Review.seq).limit(batch)
            ).scalars()
        )
        if not chunk:
            return
        yield from chunk
        last = chunk[-1].seq


def verify_reviews(session: Session) -> ReviewVerifyOut:
    """Walk the chain from the stored columns; count the anchor over the stored packs."""
    rows = 0
    prev = GENESIS_HASH
    broken_at: int | None = None
    detail = ""
    anchored = unanchored = 0
    packs: dict[str, str] = {}
    for m in _iter_reviews(session):
        rows += 1
        if broken_at is None:
            if m.prev_hash != prev:
                broken_at, detail = m.seq, f"seq {m.seq}: prev_hash mismatch"
            elif m.row_hash != review_hash_from_stored(m):
                broken_at, detail = m.seq, f"seq {m.seq}: row_hash mismatch (row edited)"
        prev = m.row_hash
        if m.verdict != "not_reviewed":
            if m.evidence_pack_hash not in packs:
                p = session.get(EvidencePackRow, m.evidence_pack_hash)
                packs[m.evidence_pack_hash] = pack_diff_sha256(dict(p.body_json or {})) if p else ""
            expected = packs[m.evidence_pack_hash]
            if expected and expected == m.patch_sha256_reviewed:
                anchored += 1
            else:
                unanchored += 1
    chain_ok = broken_at is None
    ok = chain_ok and unanchored == 0
    if ok:
        detail = f"{rows} reviews, chain intact, every verdict anchored to its pack's diff hash"
    elif chain_ok:
        detail = f"chain intact but {unanchored} review(s) no longer match their pack's diff hash"
    return ReviewVerifyOut(
        rows=rows,
        ok=ok,
        chain_ok=chain_ok,
        broken_at=broken_at,
        detail=detail,
        anchored=anchored,
        unanchored=unanchored,
        verified_at=_now(),
    )


@router.get(
    "/reviews/verify",
    response_model=ReviewVerifyOut,
    responses={401: _ERR},
    summary="Walk the review chain and re-check every anchor against the stored packs (never raises)",
)
def reviews_verify(viewer: ViewerDep, db: DbDep) -> ReviewVerifyOut:
    del viewer
    return verify_reviews(db)


@router.get(
    "/reviews/stats",
    response_model=ReviewStatsOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Per-cell human coverage: n_reviewed / n_review_defects joined onto the repo's rows",
)
def reviews_stats(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    by: str | None = Query(default=None, max_length=128),
) -> ReviewStatsOut:
    del viewer
    get_repo_or_404(db, repo)
    projection = parse_by(by)
    try:
        rows = [
            GradeRow.from_dict(grade_to_dict(g))
            for g in db.execute(
                select(Grade).where(Grade.repo == repo).order_by(Grade.seq)
            ).scalars()
        ]
    except FalseQ1Violation as exc:
        raise ApiError(
            409,
            CODE_FALSE_Q1,
            f"repo {repo!r} holds a false-Q1 row; its cells cannot be reduced: {exc}",
            detail={"repo": repo},
        ) from exc
    reviews = list(DbReviewLedger(factory).records(repo=repo))
    cells = review_cell_stats(rows, reviews, projection=projection)
    return ReviewStatsOut(
        repo=repo,
        by=list(projection),
        n_reviews=len(reviews),
        cells=[ReviewCellStatsOut(**c.to_dict()) for c in cells],
    )


@router.get(
    "/reviews/{review_id}",
    response_model=ReviewOut,
    responses={401: _ERR, 404: _ERR},
    summary="One review as stored",
)
def get_review(review_id: str, viewer: ViewerDep, db: DbDep) -> ReviewOut:
    del viewer
    m = db.execute(select(Review).where(Review.review_id == review_id)).scalar_one_or_none()
    if m is None:
        raise ApiError(404, "not_found", f"no review {review_id!r}")
    return _outs(db, [m])[0]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def _validation_422(msg: str, loc: list[str]) -> ApiError:
    """A 422 in the same ``errors`` shape pydantic's validation handler produces."""
    return ApiError(
        422,
        "validation_error",
        msg,
        detail={"errors": [{"loc": ["body", *loc], "msg": msg, "type": "value_error"}]},
    )


def _refuse(db: Session, *, g: Grade, actor: str, exc: ReviewRefused) -> ApiError:
    """Record the refusal (committed) and build the 422."""
    reason = redact(str(exc))
    append_system_event(
        db,
        trace_id=system_trace_id("reviews", g.repo),
        action="review.refused",
        repo=g.repo,
        actor=actor,
        task_id=g.task_id,
        status=StepStatus.INVALID,
        error=reason,
        payload={"code": exc.code, "grade_row_hash": g.row_hash, "envelope_code": CODE_REFUSED},
    )
    db.commit()
    return ApiError(
        422,
        CODE_REFUSED,
        reason,
        detail={
            "code": exc.code,
            "expected": exc.expected,
            "observed": exc.observed,
            "grade_row_hash": g.row_hash,
            "repo": g.repo,
            "task_id": g.task_id,
        },
    )


@router.post(
    "/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Record a human verdict on a graded row (operator+); 422 review_refused unless the patch hash is the pack's",
)
def create_review(
    body: ReviewCreateRequest, operator: OperatorDep, db: DbDep, factory: SessionFactoryDep
) -> ReviewOut:
    g = db.execute(select(Grade).where(Grade.row_hash == body.grade_row_hash)).scalar_one_or_none()
    if g is None:
        raise ApiError(404, "not_found", f"no grade row with row_hash {body.grade_row_hash[:12]}…")
    pack_row = db.get(EvidencePackRow, g.evidence_pack_hash) if g.evidence_pack_hash else None
    pack = dict(pack_row.body_json or {}) if pack_row is not None else None

    try:
        findings = tuple(
            Finding(kind=f.kind, note=f.note, file=f.file, line=f.line) for f in body.findings
        )
    except ValueError as exc:
        raise _validation_422(str(exc), ["findings"]) from exc
    # The verdict is the core's function of the findings; a client may state it only to
    # be checked against that derivation — it can never override it.
    verdict = "not_reviewed" if body.not_reviewed else derive_verdict(findings)
    if body.verdict is not None and body.verdict != verdict:
        raise _validation_422(
            f"verdict {body.verdict!r} contradicts the findings (derived {verdict!r})",
            ["verdict"],
        )
    try:
        record = ReviewRecord(
            grade_row_hash=g.row_hash,
            repo=g.repo,
            task_id=g.task_id,
            reviewer=operator.id,
            statement=body.statement,
            verdict=verdict,
            findings=findings,
            mergeable=body.mergeable,
            patch_sha256_reviewed=body.patch_sha256,
            evidence_pack_hash=g.evidence_pack_hash,
            apparatus_version=g.apparatus_version,
            schema=REVIEW_SCHEMA,
        )
    except ReviewRefused as exc:
        raise _refuse(db, g=g, actor=operator.id, exc=exc) from exc
    except ValueError as exc:
        raise _validation_422(str(exc), []) from exc

    if pack is None and record.reviewed:
        exc_missing = ReviewRefused(
            "the graded row has no stored evidence pack — nothing to anchor the review to",
            code="no_diff_in_pack",
            expected="",
            observed=record.patch_sha256_reviewed,
        )
        raise _refuse(db, g=g, actor=operator.id, exc=exc_missing)
    try:
        chained = DbReviewLedger(factory).append(record, pack=pack)
    except ReviewRefused as exc:
        raise _refuse(db, g=g, actor=operator.id, exc=exc) from exc

    append_system_event(
        db,
        trace_id=system_trace_id("reviews", g.repo),
        action="review.created",
        repo=g.repo,
        actor=operator.id,
        task_id=g.task_id,
        payload={
            "review_id": chained.review_id,
            "grade_row_hash": g.row_hash,
            "verdict": chained.verdict,
            "findings": len(chained.findings),
            "mergeable": chained.mergeable,
            "patch_sha256_reviewed": chained.patch_sha256_reviewed,
            "row_hash": chained.row_hash,
        },
    )
    db.commit()
    m = db.execute(select(Review).where(Review.review_id == chained.review_id)).scalar_one()
    return _outs(db, [m])[0]


__all__ = [
    "CODE_FALSE_Q1",
    "CODE_REFUSED",
    "REVIEW_FIELDS",
    "review_body_from_stored",
    "review_hash_from_stored",
    "review_out",
    "router",
    "verify_reviews",
]
