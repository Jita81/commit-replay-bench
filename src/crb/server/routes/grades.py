"""``/grades``, ``/tasks/{repo}/{task_id}``, ``/evidence/{pack_hash}`` — the audit surface.

These routes serialise ``grades`` rows STRAIGHT FROM THE STORE, column by column,
without constructing :class:`~crb.core.ledger.GradeRow`. That is deliberate:
``GradeRow.__post_init__`` refuses a false-Q1 row, so a row that somehow bypassed
the write path (tampering, a hand-written INSERT) would be unreadable through the
core type — and an auditor must be able to SEE the offending row. ``/grades`` shows
every row exactly as stored, chain fields included; ``/ledger/verify`` says whether
the chain and the floor hold; the capability routes (which reduce rows to numbers)
still go through ``GradeRow`` and therefore refuse with ``409 false_q1_refused``.

``/evidence/{hash}`` returns the stored pack body and ``verified`` = the canonical
SHA-256 of the body equals the key it was stored under (and, for a native pack, its
own ``pack_hash`` field).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from crb.core.evidence import canonical_json, sha256_text, verify_pack
from crb.core.ledger import GradeRow
from crb.core.spec import TaskSpec
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope
from crb.server.schemas import (
    EvidenceResponse,
    GradeRowOut,
    Page,
    PageDep,
    TaskDetail,
    TaskSpecOut,
)
from crb.store.models import EvidencePackRow, Grade, Task

router = APIRouter(tags=["grades"])
_ERR = {"model": ErrorEnvelope}

#: The hashed body of a row, in ``GradeRow`` field order (``labels`` is stored as ``labels_json``).
ROW_FIELDS: tuple[str, ...] = tuple(GradeRow.__dataclass_fields__)


def grade_to_dict(g: Grade) -> dict[str, Any]:
    """:meth:`GradeRow.to_dict` shape from the ORM row, plus the store's ``seq``."""
    d: dict[str, Any] = {}
    for k in ROW_FIELDS:
        d[k] = dict(g.labels_json or {}) if k == "labels" else getattr(g, k)
    d["seq"] = g.seq
    return d


def grade_out(g: Grade) -> GradeRowOut:
    return GradeRowOut(**grade_to_dict(g))


def _apply_filters(q: Select[Any], filters: dict[str, Any]) -> Select[Any]:
    for name, value in filters.items():
        if value is None or value == "":
            continue
        column = getattr(Grade, name)
        q = q.where(column.is_(value) if isinstance(value, bool) else column == value)
    return q


@router.get(
    "/grades",
    response_model=Page[GradeRowOut],
    responses={401: _ERR},
    summary="Ledger rows as stored (chain order), with filters",
)
def list_grades(
    viewer: ViewerDep,
    db: DbDep,
    page: PageDep,
    *,
    repo: str | None = Query(default=None, max_length=64),
    run_id: str | None = Query(default=None, max_length=32),
    task_id: str | None = Query(default=None, max_length=64),
    clean: bool | None = Query(default=None),
    mode: str | None = Query(default=None, max_length=16),
    builder: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=128),
    provider: str | None = Query(default=None, max_length=64),
    capability_class: str | None = Query(default=None, max_length=64),
    size: str | None = Query(default=None, max_length=4),
    language: str | None = Query(default=None, max_length=16),
    pool: str | None = Query(default=None, max_length=16),
    process_step: str | None = Query(default=None, max_length=16),
    belt_set: str | None = Query(default=None, max_length=16),
    disqualified: bool | None = Query(default=None),
) -> Page[GradeRowOut]:
    del viewer
    filters = {
        "repo": repo,
        "run_id": run_id,
        "task_id": task_id,
        "clean": clean,
        "mode": mode,
        "builder": builder,
        "model": model,
        "provider": provider,
        "capability_class": capability_class,
        "size": size,
        "language": language,
        "pool": pool,
        "process_step": process_step,
        "belt_set": belt_set,
        "disqualified": disqualified,
    }
    q = _apply_filters(select(Grade), filters)
    c = _apply_filters(select(func.count(Grade.seq)), filters)
    total = int(db.execute(c).scalar_one())
    rows = list(db.execute(q.order_by(Grade.seq).limit(page.limit).offset(page.offset)).scalars())
    return Page[GradeRowOut](
        items=[grade_out(g) for g in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/grades/{row_id}", response_model=GradeRowOut, responses={401: _ERR, 404: _ERR})
def get_grade(row_id: str, viewer: ViewerDep, db: DbDep) -> GradeRowOut:
    del viewer
    g = db.execute(select(Grade).where(Grade.row_id == row_id)).scalar_one_or_none()
    if g is None:
        raise ApiError(404, "not_found", f"no grade row {row_id!r}")
    return grade_out(g)


@router.get(
    "/tasks/{repo}/{task_id}",
    response_model=TaskDetail,
    responses={401: _ERR, 404: _ERR},
    summary="A mined task's spec + every grade row for it",
)
def get_task(repo: str, task_id: str, viewer: ViewerDep, db: DbDep) -> TaskDetail:
    del viewer
    task = db.get(Task, (repo, task_id))
    if task is None:
        raise ApiError(404, "not_found", f"no task {task_id!r} in repo {repo!r}")
    rows = list(
        db.execute(
            select(Grade).where(Grade.repo == repo, Grade.task_id == task_id).order_by(Grade.seq)
        ).scalars()
    )
    return TaskDetail(
        spec=TaskSpecOut(**TaskSpec.from_dict(task.spec_json).to_dict()),
        grades=[grade_out(g) for g in rows],
    )


def pack_verified(pack_hash: str, body: dict[str, Any]) -> bool:
    """A native pack carries ``pack_hash`` (checked with :func:`verify_pack`); an imported
    pack is hashed whole (:func:`crb.core.legacy.imported_pack_hash` semantics). Either
    way the recomputed hash must equal the key the pack is stored under."""
    if "pack_hash" in body:
        return verify_pack(body) and body.get("pack_hash") == pack_hash
    return sha256_text(canonical_json(body)) == pack_hash


def evidence_out(row: EvidencePackRow) -> EvidenceResponse:
    body = dict(row.body_json or {})
    return EvidenceResponse(
        pack=body,
        verified=pack_verified(row.pack_hash, body),
        pack_hash=row.pack_hash,
        schema=str(body.get("schema", "")),
        repo=row.repo,
        task_id=row.task_id,
        run_id=row.run_id,
        created=row.created,
    )


def get_pack_row(session: Session, pack_hash: str) -> EvidencePackRow:
    row = session.get(EvidencePackRow, pack_hash)
    if row is None:
        raise ApiError(404, "not_found", f"no evidence pack {pack_hash!r}")
    return row


@router.get(
    "/evidence/{pack_hash}",
    response_model=EvidenceResponse,
    responses={401: _ERR, 404: _ERR},
    summary="The evidence pack (redacted at write) + verified: recomputed hash matches",
)
def get_evidence(pack_hash: str, viewer: ViewerDep, db: DbDep) -> EvidenceResponse:
    del viewer
    return evidence_out(get_pack_row(db, pack_hash))


__all__ = ["ROW_FIELDS", "evidence_out", "grade_out", "grade_to_dict", "pack_verified", "router"]
