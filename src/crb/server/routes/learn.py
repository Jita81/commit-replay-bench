"""``/learn/{refusals,strengthen,remeasure}`` — the learning half of the loop, read-only.

Each route reduces the repo's ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load) with the
matching :mod:`crb.core.learn` derivation and returns its ``to_dict()``:

* ``/learn/refusals`` — protocol rows → candidate guard-corpus lines, every verdict
  ``unsure`` (a human applies decisions with ``crb learn refusals --apply``; there is
  deliberately no ``POST`` here — the corpus lives in the repository, not the store);
* ``/learn/strengthen`` — oracle-held cells of the class × size map (routed under the
  repo's latest controls verdict, as ``/capability-map`` does) joined to the latest
  ``oracle.score`` events → ``test.add`` items in the frozen-backlog shape;
* ``/learn/remeasure`` — cells stamped with an older apparatus → ``n`` needed, cost and
  the ``POST /runs`` bodies an operator can queue. Nothing is queued.

All three are viewer-readable and pure. See ``docs/LEARNING-LOOP.md``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.capability import PROJECTIONS, build_capability_map
from crb.core.learn import (
    load_oracle_scores,
    remeasure_plan,
    strengthening_backlog,
    triage_refusals,
)
from crb.core.routing import DEFAULT_POLICY
from crb.core.version import APPARATUS_VERSION
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.oracle import SCORE_ACTIONS, latest_controls_verdict
from crb.server.routes.repos import get_repo_or_404
from crb.store.ledger import DbLedger
from crb.store.models import Event, Task

router = APIRouter(tags=["learn"])
_ERR = {"model": ErrorEnvelope}


def _scores(session: Session, repo: str) -> list[dict[str, Any]]:
    """The latest ``oracle.score`` payload per task (events are in insertion order)."""
    latest: dict[str, dict[str, Any]] = {}
    for ev in session.execute(
        select(Event)
        .where(Event.repo == repo, Event.stage == "oracle", Event.action.in_(SCORE_ACTIONS))
        .order_by(Event.id)
    ).scalars():
        payload = dict(ev.payload_json or {})
        tid = str(ev.task_id or payload.get("task_id") or "")
        if tid:
            payload["task_id"] = tid
            latest[tid] = payload
    return [latest[k] for k in sorted(latest)]


def _subjects(session: Session, repo: str) -> dict[str, str]:
    return {
        t.task_id: t.subject
        for t in session.execute(select(Task).where(Task.repo == repo)).scalars()
    }


@router.get(
    "/learn/refusals",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="Protocol rows triaged into candidate guard-corpus lines (every verdict 'unsure')",
)
def learn_refusals(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    rows = list(DbLedger(factory).rows(repo=repo))
    return {"repo": repo, **triage_refusals(rows).to_dict()}


@router.get(
    "/learn/strengthen",
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Oracle-held cells → 'strengthen the target tests' items (frozen-backlog shape)",
)
def learn_strengthen(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    *,
    repo: str = Query(min_length=1, max_length=64),
    by: str = Query(default="class_size", max_length=32),
    since: str = Query(default="", max_length=32),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    if by not in PROJECTIONS:
        raise ApiError(
            422,
            "validation_error",
            f"unknown projection {by!r}",
            detail={"allowed": sorted(PROJECTIONS)},
        )
    rows = list(DbLedger(factory).rows(repo=repo))
    controls = latest_controls_verdict(db, repo)
    cmap = build_capability_map(
        rows, projection=PROJECTIONS[by], policy=DEFAULT_POLICY, controls=controls
    )
    backlog = strengthening_backlog(
        cmap,
        load_oracle_scores(_scores(db, repo)),
        policy=DEFAULT_POLICY,
        subjects=_subjects(db, repo),
        since=since,
    )
    return {"repo": repo, "projection": by, **backlog.to_dict()}


@router.get(
    "/learn/remeasure",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="Cells stamped with an older apparatus → n needed, cost, POST /runs bodies (nothing queued)",
)
def learn_remeasure(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    apparatus: str = Query(default=APPARATUS_VERSION, max_length=32),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    rows = list(DbLedger(factory).rows(repo=repo))
    plan = remeasure_plan(rows, current_apparatus=apparatus, policy=DEFAULT_POLICY)
    return {"repo": repo, **plan.to_dict()}


__all__ = ["learn_refusals", "learn_remeasure", "learn_strengthen", "router"]
