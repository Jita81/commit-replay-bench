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
What it does: Folds the seven inbox kinds per repository from the same readings the screen
              uses, records when each row first became due, and serves the row with its age
              and the resolved rows' waits. Never decides anything and never writes evidence.
How:          ``rows_for_mode`` → ``rows_for_apparatus`` → ``signed_map`` (the same reading
              ``/capability-map`` and the delivery gate use) and ``FactoryHome.task_views``
              → ``decision_rows`` → ``record_due`` → the response.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md,
              docs/adr/0015-signoffs-expire-with-the-apparatus.md
Works with:   src/crb/server/decisions.py (the derivation and the clock),
              src/crb/server/routes/capability.py (``signed_map`` — the one reading),
              src/crb/server/factory_state.py (``FactoryHome.task_views``),
              src/crb/server/worker.py (the idle pass that keeps the clock running),
              ui/src/screens/Decisions/useDecisionCount.ts (joins these ages to its own
              rows), docs/API.md#capability-routing-forecast-sign-off
Tested by:    tests/test_server_decisions.py
Touch when:   a human act is added to the product (src/crb/server/decisions.py first).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.capability import PROJECTION_CLASS_SIZE
from crb.server.auth import ViewerDep
from crb.server.decisions import DecisionRow, age_seconds, decision_rows, record_due
from crb.server.deps import DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.routes.capability import rows_for_apparatus, rows_for_mode, signed_map
from crb.server.routes.oracle import latest_controls_verdict
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
    if repo:
        return [repo]
    return list(db.execute(select(Repo.name).order_by(Repo.name)).scalars().all())


def _rows_for(
    db: Session, factory: sessionmaker[Session], settings: Any, repo: str
) -> list[DecisionRow]:
    """The repository's inbox rows, from the same reading the delivery gate and the
    capability screen use: sighted rows on the current apparatus, the repo's latest controls
    verdict, sign-offs overlaid (so a stale sign-off puts its cell back in the inbox)."""
    ledger_rows = rows_for_apparatus(
        rows_for_mode(DbLedger(factory).rows(repo=repo), "sighted"), "current"
    )
    cmap, _ = signed_map(
        ledger_rows, PROJECTION_CLASS_SIZE, db, repo, controls=latest_controls_verdict(db, repo)
    )
    home = FactoryHome(settings.home, repo)
    return decision_rows(cmap.cells, home.task_views())


@router.get(
    "/decisions",
    response_model=DecisionList,
    responses={401: _ERR},
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
        rows = _rows_for(db, factory, settings, name)
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
