"""``GET /decisions`` — the inbox with the age of each decision (G-516).

The decisions screen derives its own rows and always has: it holds the map, the sign-offs
and the factory tasks already, and a person should not wait for a round trip to see their
own inbox. What a screen cannot know is WHEN a row first became due — nothing was written
down, so a decision existed only while somebody had the page open and "this cell has been
waiting eleven days" was unanswerable.

This route is that clock. It derives the same rows on the server
(:func:`crb.server.decisions.decision_rows`), stamps ``decisions_due`` and serves each row
with ``due_since`` and ``age_s``. Reading it therefore WRITES — deliberately: the reading is
the observation, and a deployment where nobody ever opens the page still has its clock kept
by the worker's idle pass (:meth:`crb.server.worker.Worker.refresh_decisions`), which calls
exactly this derivation. A viewer may read it; the write it causes is not the viewer's act
and carries no actor, which is why it is a clock and not evidence.

Navigation
----------
What it is:   The ``/decisions`` route module — every due decision with the moment it became
              due and how long it has been waiting.
What it does: Folds the eight inbox kinds per repository from the same readings the screen
              uses, records when each row first became due, and serves the row with its age
              and the resolved rows' waits. Never decides anything and never writes evidence.
How:          ``rows_for_mode`` → ``rows_for_apparatus`` → ``rows_for_arm`` →
              ``filter_posture`` → ``signed_map`` (the reading ``/capability-map`` serves by
              default), ``FactoryHome.task_views`` and ``register_for`` → ``decision_rows``
              → ``record_due`` → the response.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md,
              docs/adr/0015-signoffs-expire-with-the-apparatus.md
Works with:   src/crb/server/decisions.py (the derivation and the clock),
              src/crb/server/routes/capability.py (``signed_map`` — the one reading),
              src/crb/server/factory_state.py (``FactoryHome.task_views``),
              src/crb/server/worker.py (the idle pass that keeps the clock running),
              ui/src/screens/Decisions/useDecisionCount.ts (joins these ages to its own
              rows), docs/API.md#capability-routing-forecast-sign-off (the routes' contract)
Tested by:    tests/test_server_decisions.py
Touch when:   never for a new repository (``?repo=`` names any connected one); a human act is
              added to the product (src/crb/server/decisions.py first).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.capability import PROJECTION_CLASS_SIZE, CapabilityCell
from crb.server.auth import ViewerDep
from crb.server.decisions import DecisionRow, age_seconds, decision_rows, record_due
from crb.server.deps import DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.prevention_state import register_for
from crb.server.routes.capability import (
    CHECKS_CURRENT,
    POSTURE_DEPLOYMENT,
    filter_posture,
    rows_for_apparatus,
    rows_for_arm,
    rows_for_mode,
    signed_map,
)
from crb.server.routes.oracle import latest_controls_verdict
from crb.server.routes.repos import get_repo_or_404
from crb.store.ledger import DbLedger
from crb.store.models import Repo

router = APIRouter(tags=["decisions"])
_ERR = {"model": ErrorEnvelope}


class DecisionOut(BaseModel):
    """One due decision, with the clock the screen cannot keep for itself."""

    repo: str
    kind: str
    #: What the act is about: ``<class>|<size>`` for a cell row, the item id for a factory
    #: row — the identity the screen's own derivation computes, so it can join on it.
    key: str
    title: str
    role: str
    #: When this row FIRST became due (ISO-8601, UTC). A row that went away and came back
    #: keeps its original stamp: the wait is the person's, not the derivation's.
    due_since: str
    #: How long it has been due, in whole seconds.
    age_s: int


class DecisionList(BaseModel):
    """``GET /decisions`` body. ``as_of`` is when this reading was taken and stamped."""

    items: list[DecisionOut]
    total: int
    as_of: str
    #: The repositories this reading covered (one, or every connected repository).
    repos: list[str]


def _repos(db: Session, repo: str) -> list[str]:
    """The repositories one reading covers: the one named, which must be connected (404
    ``not_found`` otherwise, as every per-repository route answers — an empty inbox for a
    name nobody connected would read as "nothing is waiting", and the name goes on to a
    filesystem path), or every connected repository."""
    if repo:
        return [get_repo_or_404(db, repo).name]
    return list(db.execute(select(Repo.name).order_by(Repo.name)).scalars().all())


def rows_for(
    db: Session,
    factory: sessionmaker[Session],
    settings: Any,
    repo: str,
    *,
    cells: Sequence[CapabilityCell] | None = None,
) -> list[DecisionRow]:
    """The repository's inbox rows, from the same readings the screen folds: the map
    ``GET /capability-map`` serves by default (sighted rows, the current apparatus, the
    repository's own checks arm — ADR-0024 — and this deployment's posture class —
    ADR-0019 §8 — under the latest controls verdict, sign-offs overlaid, so a stale sign-off
    puts its cell back in the inbox), the factory items, and the prevention register
    ``GET /learn/register`` serves. The worker's idle pass calls this function, so the
    clock and the page read one derivation; it passes ``cells`` from its own served map
    (``Worker._served_map`` — the same default reading, taken with the worker's settings)."""
    if cells is None:
        current = rows_for_arm(
            factory,
            repo,
            rows_for_apparatus(
                rows_for_mode(DbLedger(factory).rows(repo=repo), "sighted"), "current"
            ),
            CHECKS_CURRENT,
        )
        ledger_rows = filter_posture(db, repo, current, POSTURE_DEPLOYMENT, settings).rows
        cmap, _ = signed_map(
            ledger_rows,
            PROJECTION_CLASS_SIZE,
            db,
            repo,
            controls=latest_controls_verdict(db, repo),
        )
        cells = cmap.cells
    home = FactoryHome(settings.home, repo)
    register = register_for(db, factory, settings.home, repo, settings=settings).to_dict()
    return decision_rows(cells, home.task_views(), register)


@router.get(
    "/decisions",
    response_model=DecisionList,
    responses={401: _ERR, 404: _ERR},
    summary="Every decision due now, with the moment it became due and how long it has waited",
)
def list_decisions(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query("", description="One repository; empty = every connected repository"),
) -> DecisionList:
    """Derive, stamp and serve. The stamping is why this read writes: it is the observation
    that a decision was due at this moment, and without it the age could only ever start
    when somebody happened to look."""
    del viewer
    items: list[DecisionOut] = []
    names = _repos(db, repo)
    as_of = ""
    for name in names:
        rows = rows_for(db, factory, settings, name)
        live = record_due(db, name, rows)
        for row in rows:
            rec = live[(row.kind, row.key)]
            as_of = as_of or rec.last_seen
            items.append(
                DecisionOut(
                    repo=name,
                    kind=row.kind,
                    key=row.key,
                    title=row.title,
                    role=row.role,
                    due_since=rec.first_due,
                    age_s=age_seconds(rec.first_due),
                )
            )
    db.commit()
    return DecisionList(items=items, total=len(items), as_of=as_of, repos=names)
