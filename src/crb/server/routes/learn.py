"""``/learn/{refusals,strengthen,remeasure}`` — the learning half of the loop, read-only.

Each route reduces the repo's ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load) with the
matching :mod:`crb.core.learn` derivation and returns its ``to_dict()``:

* ``/learn/refusals`` — protocol rows → candidate guard-corpus lines, every verdict
  ``unsure`` (a human applies decisions with ``crb learn refusals --apply``; there is
  deliberately no ``POST`` here — the corpus lives in the repository, not the store);
* ``/learn/strengthen`` — oracle-held cells of the class × size map (routed under the
  repo's latest controls verdict, as ``/capability-map`` does) joined to the latest
  ``oracle.score`` events → ``test.add`` items in the frozen-backlog shape. The
  per-task scores are read from the store's **events** (one ``oracle.score`` per task
  per oracle run; an oracle run's ``counts_json`` keeps only the per-cell roll-up, and
  there is no per-task score table) — the same reader ``/oracle/{repo}`` uses, so the
  two screens can never disagree about a task's strength. Every score carries the
  repo, so the item ids equal what ``crb learn strengthen --oracle <GET /oracle/{repo}>
  --controls <GET /oracle/{repo}/controls>`` derives from the exports;
* ``/learn/remeasure`` — cells stamped with an older apparatus → ``n`` needed, cost and
  the ``POST /runs`` bodies an operator can queue. Nothing is queued.

All three are viewer-readable and pure. See ``docs/LEARNING-LOOP.md``.

Navigation
----------
What it is:   The ``/learn/*`` route module — the read-only half of the learning loop
              (refusal triage, oracle-strengthening backlog, re-measurement plan).
What it does: Reduces the repo's rows with the matching ``crb.core.learn`` derivation and
              returns its ``to_dict``; joins the latest ``oracle.score`` event per task so
              the strengthening items carry the same strengths ``/oracle/{repo}`` shows.
              Never writes: decisions are applied by the CLI against the repository, and
              re-measurement runs are queued by an operator, not here.
How:          ``DbLedger.rows(repo)`` → ``triage_refusals`` | ``build_capability_map`` +
              ``strengthening_backlog`` (scores from the events table) | ``remeasure_plan``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/learn.py (the three derivations), src/crb/server/routes/oracle.py
              (``SCORE_ACTIONS``, ``latest_controls_verdict``), src/crb/cli/commands/learn.py
              (the CLI twin that can ``--apply``), docs/LEARNING-LOOP.md (what loops
              mechanically and what a human still does), ui/src/screens/Learn
Tested by:    tests/test_server_routes_learn.py, tests/test_cli_learn.py
Touch when:   never for a new repository; adding a derivation means a function in
              src/crb/core/learn.py, a route here, a CLI verb, and a section in
              docs/LEARNING-LOOP.md.
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
    """The latest ``oracle.score`` payload per task, from the store's events (the
    per-task scores live nowhere else: ``runs.counts_json`` is the cell roll-up).
    Events are in insertion order, so the last one per task is the latest oracle
    run's. ``repo`` is stamped on every payload — the item id is
    ``sha(cell, repo, task)`` and must equal the CLI's over the same export."""
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
            payload.setdefault("repo", repo)
            latest[tid] = payload
    return [latest[k] for k in sorted(latest)]


def _subjects(session: Session, repo: str) -> dict[str, str]:
    """``task_id → commit subject`` so a strengthening item reads as a sentence."""
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
    # Every verdict comes back "unsure" by design: the API proposes, a human decides.
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
