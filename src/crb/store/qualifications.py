"""Task qualifications in the store: append-only, latest-wins, revocation as a row (ADR-0019).

``task_qualifications`` holds every :class:`~crb.core.qualify.Qualification` a deployment
has measured — one per (repository, task, posture) measurement, never edited. The one in
force for a task in a posture is the latest row; a revocation (a trial's gold control was
red in the posture, a sealed dependency set failed its digest) is a NEW row with state
``revoked`` and the code that revoked it. A ``legacy`` row (the back-fill of revision 0011)
is kept for the record and never selected by a gate.

Navigation
----------
What it is:   The store's qualification ledger — append, the latest record per task and
              posture, the projected specs a replay grades against, counts by refusal code,
              fingerprints for cross-posture pooling, and revocation.
What it does: Gives the worker's posture gate, the runs route's 409 and the repository
              posture view one reading of "is this task proven where it will be graded".
How:          SQLAlchemy 2 selects over ``TaskQualification`` ordered by ``seq``; the record
              is ``Qualification.from_dict(body_json)``; projection joins ``tasks.spec_json``.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``TaskQualification``, ``Task``),
              src/crb/core/qualify.py (the record), src/crb/server/worker.py (the gate reads
              and writes it), src/crb/server/routes/runs.py (the submit-time 409),
              src/crb/server/routes/repos.py (the posture view),
              src/crb/store/migrations/versions/v0011_task_qualifications.py (the table)
Tested by:    tests/test_store_qualifications.py, tests/test_store_migrate.py,
              tests/test_worker.py
Touch when:   a gate needs a new reading of the records (add it here, never an UPDATE).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.qualify import (
    STATE_LEGACY,
    STATE_QUALIFIED,
    STATE_REVOKED,
    Qualification,
)
from crb.core.spec import TaskSpec
from crb.store.models import Task, TaskQualification


def append(s: Session, q: Qualification) -> Qualification:
    """Append ``q`` (commits). The record is stored verbatim; the columns beside it are
    copies a gate filters on."""
    posture = dict(q.posture)
    s.add(
        TaskQualification(
            qualification_id=q.qualification_id,
            repo=q.repo,
            task_id=q.task_id,
            posture_id=q.posture_id,
            posture_class=str(posture.get("posture_class", "")),
            executor=str(posture.get("executor", "")),
            image_ref=str(posture.get("image_ref", ""))[:256],
            state=q.state,
            code=q.code,
            fingerprint=q.fingerprint,
            body_json=q.to_dict(),
            created=q.created,
        )
    )
    s.commit()
    return q


def _rows(
    s: Session, repo: str, *, posture_id: str | None = None, task_ids: Sequence[str] | None = None
) -> list[TaskQualification]:
    q = select(TaskQualification).where(TaskQualification.repo == repo)
    if posture_id is not None:
        q = q.where(TaskQualification.posture_id == posture_id)
    if task_ids is not None:
        q = q.where(TaskQualification.task_id.in_(list(task_ids)))
    return list(s.execute(q.order_by(TaskQualification.seq)).scalars().all())


def latest(s: Session, repo: str, task_id: str, posture_id: str) -> Qualification | None:
    """The record in force for ``task_id`` in ``posture_id`` (the latest row), or ``None``."""
    row = s.execute(
        select(TaskQualification)
        .where(
            TaskQualification.repo == repo,
            TaskQualification.task_id == task_id,
            TaskQualification.posture_id == posture_id,
        )
        .order_by(TaskQualification.seq.desc())
        .limit(1)
    ).scalar_one_or_none()
    return Qualification.from_dict(row.body_json) if row is not None else None


def latest_by_task(
    s: Session, repo: str, posture_id: str, task_ids: Sequence[str] | None = None
) -> dict[str, Qualification]:
    """task id → the record in force in ``posture_id`` (qualified or not)."""
    out: dict[str, Qualification] = {}
    for row in _rows(s, repo, posture_id=posture_id, task_ids=task_ids):
        out[row.task_id] = Qualification.from_dict(row.body_json)
    return out


def qualified_specs(
    s: Session, repo: str, posture_id: str, task_ids: Sequence[str] | None = None
) -> list[TaskSpec]:
    """The tasks of ``repo`` whose record in force in ``posture_id`` is ``qualified``,
    projected (in-posture baseline, posture stamp), oldest-authored first. A legacy,
    unqualified or revoked record never selects a task."""
    by_task = latest_by_task(s, repo, posture_id, task_ids)
    keep = {tid: q for tid, q in by_task.items() if q.is_qualified}
    if not keep:
        return []
    rows = (
        s.execute(
            select(Task)
            .where(Task.repo == repo, Task.task_id.in_(list(keep)))
            .order_by(Task.authored, Task.task_id)
        )
        .scalars()
        .all()
    )
    return [keep[r.task_id].project(TaskSpec.from_dict(r.spec_json)) for r in rows]


def counts_by_code(s: Session, repo: str, posture_id: str) -> Counter[str]:
    """How many tasks each refusal code keeps out of ``posture_id`` (latest records only;
    a ``qualified`` record counts under the empty code)."""
    return Counter(q.code for q in latest_by_task(s, repo, posture_id).values())


def latest_posture_for(s: Session, repo: str, *, executor: str = "", image_ref: str = "") -> str:
    """The posture id most recently recorded for ``repo`` (optionally for one executor and
    image) — what a submit-time check reads when it cannot resolve the posture live."""
    q = select(TaskQualification).where(
        TaskQualification.repo == repo, TaskQualification.state != STATE_LEGACY
    )
    if executor:
        q = q.where(TaskQualification.executor == executor)
    if image_ref:
        q = q.where(TaskQualification.image_ref == image_ref)
    row = s.execute(q.order_by(TaskQualification.seq.desc()).limit(1)).scalar_one_or_none()
    return row.posture_id if row is not None else ""


def latest_fingerprints(s: Session, repo: str, classes: Iterable[str]) -> dict[str, dict[str, str]]:
    """posture class → {task id → fingerprint} over the QUALIFIED records in force, the
    latest posture of each class winning — what cross-posture pooling compares
    (ADR-0019 §8: pool two classes only over tasks whose fingerprints match in both)."""
    wanted = set(classes)
    out: dict[str, dict[str, str]] = {c: {} for c in wanted}
    latest_row: dict[tuple[str, str], TaskQualification] = {}
    for row in _rows(s, repo):
        if row.posture_class in wanted:
            latest_row[(row.posture_class, row.task_id)] = row
    for (cls, tid), row in latest_row.items():
        if row.state == STATE_QUALIFIED:
            out[cls][tid] = row.fingerprint
    return out


def revoke(
    s: Session, q: Qualification, code: str, actor: str, reason: str, *, run_id: str = ""
) -> Qualification:
    """Append a ``revoked`` record for ``q``'s task and posture (commits). The revoked
    record carries the facts it revokes, the code and who or what revoked it; the
    original row is untouched."""
    body: dict[str, Any] = {
        **q.to_dict(),
        "qualification_id": "",
        "state": STATE_REVOKED,
        "code": code,
        "message": f"revoked by {actor or 'the worker'}: {reason}"[:500],
        "fix": "",
        "fingerprint": "",
        "run_id": run_id or q.run_id,
        "created": "",
    }
    body.pop("created")
    revoked = Qualification.from_dict(body)
    return append(s, revoked)


__all__ = [
    "append",
    "counts_by_code",
    "latest",
    "latest_by_task",
    "latest_fingerprints",
    "latest_posture_for",
    "qualified_specs",
    "revoke",
]
