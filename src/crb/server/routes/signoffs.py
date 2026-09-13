"""``/signoffs`` — human attestations; the verification tier is EARNED, never asserted.

The ``signoffs`` table is append-only and hash-chained on its own (``prev_hash`` =
the previous sign-off's ``row_hash``; ``row_hash`` = SHA-256 of the canonical JSON
of the row minus ``row_hash``). A revocation is a new row with ``revoke=True`` for
the same scope; the latest row per ``(repo, scope)`` wins.

The cardinal invariant is enforced in BOTH directions, exactly as
:mod:`crb.core.signoff` specifies:

* **At write** — the cell's rows are re-read from the ledger and the cell's
  ``false_q1`` is counted in SQL over the STORED belts (the same predicate
  ``/health`` uses), so a row that bypassed the write path is caught here too.
  ``false_q1 > 0`` or an unmeasured cell → **409 false_q1_refused**, nothing is
  written, and the refusal itself is recorded as a ``system/signoff.refused`` event.
  The evidence the approver saw (n, point, interval, false-Q1, apparatus) is stamped
  into the row and covered by its hash.
* **At read** — every listed attestation carries ``current_false_q1`` and ``active``
  (latest for its scope, not revoked, and the cell's CURRENT false-Q1 is 0); the
  capability/forecast overlays use :func:`crb.core.signoff.apply_signoffs`, which
  refuses to lift a cell whose false-Q1 is now > 0. A later violation
  auto-invalidates the attestation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import APIRouter, Query, status
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from crb.core.capability import WILDCARD, measure_cell
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import (
    BELT_SET_V3_LEGACY,
    CELL_FIELDS,
    GENESIS_HASH,
    CellKey,
    GradeRow,
    LedgerIntegrityError,
)
from crb.core.redact import redact
from crb.core.signoff import SignoffRecord, SignoffRefused, check_signable, stamp_evidence
from crb.observability.events import StepStatus
from crb.server.auth import ApproverDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope
from crb.server.routes.grades import grade_to_dict
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas import (
    Page,
    PageDep,
    SignoffCreateRequest,
    SignoffEvidence,
    SignoffOut,
    SignoffRevokeRequest,
)
from crb.store.models import Grade, Repo, Signoff

router = APIRouter(tags=["signoffs"])
_ERR = {"model": ErrorEnvelope}

#: Snapshot keys stored (as strings) next to the scope in ``cell_json``.
_EV_N = "evidence_n"
_EV_POINT = "evidence_point"
_EV_CI_LOW = "evidence_ci_low"
_EV_CI_HIGH = "evidence_ci_high"
_EV_FQ1 = "evidence_false_q1"
_EV_APPARATUS = "evidence_apparatus"

#: A clean row whose STORED belts are not all True (legacy rows: three belts).
FALSE_Q1_PREDICATE = or_(
    Grade.tests_unmodified.is_not(True),
    Grade.target_green.is_not(True),
    Grade.no_new_failures.is_not(True),
    (Grade.belt_set != BELT_SET_V3_LEGACY) & Grade.source_changed.is_not(True),
)


# ---------------------------------------------------------------------------
# Row hashing (the table's own chain)
# ---------------------------------------------------------------------------


def signoff_body(row: Signoff) -> dict[str, Any]:
    """Everything that is hashed: the row minus ``row_hash`` (and minus the store's ``seq``)."""
    return {
        "signoff_id": row.signoff_id,
        "repo": row.repo,
        "cell": dict(row.cell_json or {}),
        "tier": row.tier,
        "verifier": row.verifier,
        "note": row.note,
        "revoke": bool(row.revoke),
        "evidence_rows": int(row.evidence_rows),
        "created": row.created,
        "prev_hash": row.prev_hash,
    }


def signoff_hash(row: Signoff) -> str:
    return sha256_text(canonical_json(signoff_body(row)))


def verify_signoff_rows(rows: Iterable[Signoff]) -> int:
    """Walk the sign-off chain in ``seq`` order; raise :class:`LedgerIntegrityError`."""
    prev = GENESIS_HASH
    n = 0
    for r in rows:
        n += 1
        if r.prev_hash != prev:
            raise LedgerIntegrityError(f"sign-off {n} ({r.signoff_id[:8]}) prev_hash mismatch")
        if r.row_hash != signoff_hash(r):
            raise LedgerIntegrityError(f"sign-off {n} ({r.signoff_id[:8]}) row_hash mismatch")
        prev = r.row_hash
    return n


def _lock(session: Session) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    elif dialect == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7332)"))


def _last_hash(session: Session) -> str:
    last = session.execute(
        select(Signoff.row_hash).order_by(Signoff.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return str(last) if last else GENESIS_HASH


def _chain_and_add(session: Session, row: Signoff) -> Signoff:
    row.prev_hash = _last_hash(session)
    row.row_hash = signoff_hash(row)
    session.add(row)
    return row


# ---------------------------------------------------------------------------
# Scope ↔ core records
# ---------------------------------------------------------------------------


def scope_of(row: Signoff) -> CellKey:
    cj = dict(row.cell_json or {})
    return CellKey(**{f: str(cj.get(f, WILDCARD) or WILDCARD) for f in CELL_FIELDS})


def _scope_key(row: Signoff) -> tuple[str, ...]:
    return (row.repo, *scope_of(row).to_tuple())


def to_record(row: Signoff) -> SignoffRecord:
    """The :class:`~crb.core.signoff.SignoffRecord` view of a stored row (for the overlay)."""
    cj = dict(row.cell_json or {})
    scope = scope_of(row)
    return SignoffRecord(
        repo=row.repo,
        capability_class=scope.capability_class,
        verifier=row.verifier,
        size=scope.size,
        language=scope.language,
        builder=scope.builder,
        model=scope.model,
        provider=scope.provider,
        process_step=scope.process_step,
        tier=row.tier,
        note=row.note,
        revoked=bool(row.revoke),
        verified_at=row.created,
        n_at_signoff=int(cj.get(_EV_N, row.evidence_rows) or 0),
        point_at_signoff=float(cj.get(_EV_POINT, 0.0) or 0.0),
        false_q1_at_signoff=int(cj.get(_EV_FQ1, 0) or 0),
        apparatus_version=str(cj.get(_EV_APPARATUS, "") or ""),
        record_id=row.signoff_id,
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
    )


def load_signoff_rows(session: Session, repo: str | None = None) -> list[Signoff]:
    q = select(Signoff).order_by(Signoff.seq)
    if repo:
        q = q.where(Signoff.repo.in_([repo, WILDCARD]))
    return list(session.execute(q).scalars())


def load_signoff_records(session: Session, repo: str | None = None) -> list[SignoffRecord]:
    """Every stored sign-off (attestations and revocations) as core records, chain order.
    Feed these to :func:`crb.core.signoff.apply_signoffs_to_map`, which collapses to the
    latest per scope and re-checks the cell's current false-Q1."""
    return [to_record(r) for r in load_signoff_rows(session, repo)]


# ---------------------------------------------------------------------------
# Cell evidence from the ledger
# ---------------------------------------------------------------------------


def _scope_where(q: Any, repo: str, scope: CellKey) -> Any:
    q = q.where(Grade.repo == repo)
    for field in CELL_FIELDS:
        value = getattr(scope, field)
        if value != WILDCARD:
            q = q.where(getattr(Grade, field) == value)
    return q


def cell_false_q1(session: Session, repo: str, scope: CellKey) -> tuple[int, list[str]]:
    """``(count, row_ids)`` of clean rows in scope whose stored belts are not all True."""
    q = _scope_where(
        select(Grade.row_id).where(Grade.clean.is_(True), FALSE_Q1_PREDICATE), repo, scope
    )
    ids = [str(r) for r in session.execute(q.order_by(Grade.seq)).scalars()]
    return len(ids), ids


def cell_rows(session: Session, repo: str, scope: CellKey) -> list[GradeRow]:
    """The scope's rows as :class:`GradeRow` (raises ``FalseQ1Violation`` on a bad row —
    call :func:`cell_false_q1` first so the refusal is explicit, not incidental)."""
    q = _scope_where(select(Grade), repo, scope).order_by(Grade.seq)
    return [GradeRow.from_dict(grade_to_dict(g)) for g in session.execute(q).scalars()]


def _projection(scope: CellKey) -> tuple[str, ...]:
    return tuple(f for f in CELL_FIELDS if getattr(scope, f) != WILDCARD)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _evidence(row: Signoff) -> SignoffEvidence:
    cj = dict(row.cell_json or {})
    apparatus = str(cj.get(_EV_APPARATUS, "") or "")
    return SignoffEvidence(
        n=int(cj.get(_EV_N, row.evidence_rows) or 0),
        point=float(cj.get(_EV_POINT, 0.0) or 0.0),
        ci_low=float(cj.get(_EV_CI_LOW, 0.0) or 0.0),
        ci_high=float(cj.get(_EV_CI_HIGH, 0.0) or 0.0),
        false_q1=int(cj.get(_EV_FQ1, 0) or 0),
        apparatus_versions=[a for a in apparatus.split(",") if a],
    )


def _revocation_for(row: Signoff, all_rows: Sequence[Signoff]) -> Signoff | None:
    key = _scope_key(row)
    for r in all_rows:
        if r.seq > row.seq and r.revoke and _scope_key(r) == key:
            return r
    return None


def _superseded(row: Signoff, all_rows: Sequence[Signoff]) -> bool:
    key = _scope_key(row)
    return any(r.seq > row.seq and not r.revoke and _scope_key(r) == key for r in all_rows)


def signoff_out(session: Session, row: Signoff, all_rows: Sequence[Signoff]) -> SignoffOut:
    revocation = _revocation_for(row, all_rows)
    current_fq1, _ = (
        cell_false_q1(session, row.repo, scope_of(row)) if row.repo != WILDCARD else (0, [])
    )
    active = revocation is None and not _superseded(row, all_rows) and current_fq1 == 0
    return SignoffOut(
        id=row.signoff_id,
        repo=row.repo,
        cell=scope_of(row).to_dict(),
        tier=row.tier,
        note=row.note,
        approver=row.verifier,
        created=row.created,
        revoked=revocation is not None,
        revoked_by=revocation.verifier if revocation is not None else None,
        revoked_at=revocation.created if revocation is not None else None,
        active=active,
        current_false_q1=current_fq1,
        evidence=_evidence(row),
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/signoffs",
    response_model=Page[SignoffOut],
    responses={401: _ERR},
    summary="Attestations (active by default; ?include_revoked=true for the history)",
)
def list_signoffs(
    viewer: ViewerDep,
    db: DbDep,
    page: PageDep,
    repo: str | None = Query(default=None, max_length=64),
    include_revoked: bool = Query(default=False),
) -> Page[SignoffOut]:
    del viewer
    rows = load_signoff_rows(db, repo)
    items = [signoff_out(db, r, rows) for r in rows if not r.revoke]
    if not include_revoked:
        items = [s for s in items if not s.revoked]
    items.reverse()  # newest first
    return Page[SignoffOut](
        items=items[page.offset : page.offset + page.limit],
        total=len(items),
        limit=page.limit,
        offset=page.offset,
    )


def _refuse(
    db: Session, *, repo: str, actor: str, scope: CellKey, reason: str, detail: dict[str, Any]
) -> ApiError:
    """Record the refusal as a system event (committed) and build the 409."""
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", repo),
        action="signoff.refused",
        repo=repo,
        actor=actor,
        status=StepStatus.INVALID,
        error=reason,
        payload={"cell": scope.to_dict(), **detail},
    )
    db.commit()
    return ApiError(
        409,
        "false_q1_refused",
        reason,
        detail={"cell": scope.to_dict(), "repo": repo, **detail},
    )


@router.post(
    "/signoffs",
    response_model=SignoffOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Attest a cell (approver); 409 false_q1_refused if false-Q1 > 0 or unmeasured",
)
def create_signoff(body: SignoffCreateRequest, approver: ApproverDep, db: DbDep) -> SignoffOut:
    if db.get(Repo, body.repo) is None:
        raise ApiError(404, "not_found", f"no repo {body.repo!r}")
    try:
        record = SignoffRecord(
            repo=body.repo,
            capability_class=body.cell["capability_class"],
            verifier=approver.id,
            size=body.cell.get("size", WILDCARD),
            language=body.cell.get("language", WILDCARD),
            builder=body.cell.get("builder", WILDCARD),
            model=body.cell.get("model", WILDCARD),
            provider=body.cell.get("provider", WILDCARD),
            process_step=body.cell.get("process_step", WILDCARD),
            tier=body.tier,
            note=body.note,
        )
    except SignoffRefused as exc:
        raise ApiError(409, "false_q1_refused", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(
            422,
            "validation_error",
            str(exc),
            detail={"errors": [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]},
        ) from exc
    scope = record.scope()

    # 1. The floor, over the STORED belts — catches rows that bypassed the write path.
    fq1, bad_ids = cell_false_q1(db, body.repo, scope)
    if fq1 > 0:
        raise _refuse(
            db,
            repo=body.repo,
            actor=approver.id,
            scope=scope,
            reason=f"cell has false_q1={fq1} > 0 — untrusted, cannot be signed off",
            detail={"false_q1": fq1, "rows": bad_ids},
        )
    # 2. Evidence: the cell must be measured.
    rows = cell_rows(db, body.repo, scope)
    if not rows:
        raise _refuse(
            db,
            repo=body.repo,
            actor=approver.id,
            scope=scope,
            reason="cell has no measured evidence — nothing to sign off",
            detail={"false_q1": 0, "reason": "not_measured"},
        )
    cell = measure_cell(rows, _projection(scope))
    # 3. The core's own write-boundary check (scope match, evidence, false-Q1).
    try:
        check_signable(record, cell, repo=body.repo)
    except SignoffRefused as exc:
        raise _refuse(
            db,
            repo=body.repo,
            actor=approver.id,
            scope=scope,
            reason=redact(str(exc)),
            detail={"false_q1": cell.false_q1},
        ) from exc
    stamped = stamp_evidence(record, cell)
    assert cell.stats is not None  # guaranteed by check_signable

    cell_json: dict[str, str] = {
        **scope.to_dict(),
        _EV_N: str(cell.stats.n),
        _EV_POINT: f"{cell.stats.point:.6f}",
        _EV_CI_LOW: f"{cell.stats.ci.low:.6f}",
        _EV_CI_HIGH: f"{cell.stats.ci.high:.6f}",
        _EV_FQ1: str(cell.stats.false_q1),
        _EV_APPARATUS: ",".join(cell.stats.apparatus_versions),
    }
    _lock(db)
    row = _chain_and_add(
        db,
        Signoff(
            signoff_id=uuid.uuid4().hex,
            repo=body.repo,
            cell_json=cell_json,
            tier=stamped.tier,
            verifier=approver.id,
            note=stamped.note,
            revoke=False,
            evidence_rows=cell.stats.n,
            created=utc_now_iso(),
        ),
    )
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", body.repo),
        action="signoff.created",
        repo=body.repo,
        actor=approver.id,
        payload={
            "signoff_id": row.signoff_id,
            "cell": scope.to_dict(),
            "tier": row.tier,
            "n": cell.stats.n,
            "point": round(cell.stats.point, 4),
            "row_hash": row.row_hash,
        },
    )
    db.commit()
    return signoff_out(db, row, load_signoff_rows(db, body.repo))


@router.post(
    "/signoffs/{signoff_id}/revoke",
    response_model=SignoffOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR},
    summary="Withdraw an attestation (appends a revocation row; never edits)",
)
def revoke_signoff(
    signoff_id: str,
    approver: ApproverDep,
    db: DbDep,
    body: SignoffRevokeRequest | None = None,
) -> SignoffOut:
    row = db.execute(
        select(Signoff).where(Signoff.signoff_id == signoff_id, Signoff.revoke.is_(False))
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", f"no attestation {signoff_id!r}")
    all_rows = load_signoff_rows(db, row.repo)
    if _revocation_for(row, all_rows) is not None:
        raise ApiError(409, "already_revoked", f"attestation {signoff_id!r} is already revoked")
    note = body.note if body is not None else ""
    _lock(db)
    _chain_and_add(
        db,
        Signoff(
            signoff_id=uuid.uuid4().hex,
            repo=row.repo,
            cell_json=scope_of(row).to_dict(),
            tier=row.tier,
            verifier=approver.id,
            note=redact(note) or f"revokes {signoff_id}",
            revoke=True,
            evidence_rows=0,
            created=utc_now_iso(),
        ),
    )
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", row.repo),
        action="signoff.revoked",
        repo=row.repo,
        actor=approver.id,
        payload={"signoff_id": signoff_id, "cell": scope_of(row).to_dict()},
    )
    db.commit()
    return signoff_out(db, row, load_signoff_rows(db, row.repo))


__all__ = [
    "FALSE_Q1_PREDICATE",
    "cell_false_q1",
    "cell_rows",
    "load_signoff_records",
    "load_signoff_rows",
    "router",
    "scope_of",
    "signoff_body",
    "signoff_hash",
    "signoff_out",
    "to_record",
    "verify_signoff_rows",
]
