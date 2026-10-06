"""``GET /decisions`` — the one inbox, served, with the age of each decision (G-516, F6).

Until F6 the decisions screen rebuilt the inbox in every browser from five queries per
repository — the map, the sign-offs, the factory tasks, the prevention register and the
library — and the nav badge repeated them on every screen. This route is now the inbox: it
derives every row on the server (:func:`crb.server.decisions.decision_rows`) from the same
readings those routes serve, adds the rows only the server can derive without a fan-out (a cell
held by its tests, a cell whose evidence predates the apparatus — G-535), and serves each row
with its act, its link and whether the person reading can take it.

It is also the clock. The full reading stamps ``decisions_due`` and serves each row with
``due_since`` and ``age_s``; reading it therefore WRITES — deliberately: the reading is the
observation, and a deployment where nobody opens the page still has its clock kept by the
worker's idle pass (:meth:`crb.server.worker.Worker.refresh_decisions`), which calls exactly
this derivation. ``?count=1`` is the nav badge's reading: the total and the count per acting
role, and it never writes the clock — a badge on every screen must not be an observation. The
count carries a strong ``ETag``, honours ``If-None-Match`` and is revalidated on every read
(``no-cache``): a person who has just acted must see the new number, and an unchanged count
costs a ``304``. The list carries its clock (``as_of``, each row's ``age_s``), so no two
readings are the same bytes: it has no ``ETag`` and is served fresh (``no-store``) — only the
count can be revalidated.

A repository whose inputs cannot be read (its library's acts no longer fold, say) is named in
``errors`` with the refusal's status, code and message — or, for any other fault (a backlog
that no longer parses), as ``500 internal_error``, logged with the request id, as the worker's
idle pass isolates it (P-612) — and the rest are served: one broken
repository must not blank everyone's inbox, and the count is marked incomplete rather than
read as smaller.

Navigation
----------
What it is:   The ``/decisions`` route module — every due decision with its act, its link, the
              moment it became due and how long it has waited; or, with ``?count=1``, the
              badge's count.
What it does: Reads each repository's inputs (the signed map, the factory tasks as served, the
              prevention register, the library index, the stale sign-offs, the re-measurement
              plan), derives the rows, fits each to the viewer's role, records when each row
              first became due (the full reading only) and serves them. Never decides anything
              and never writes evidence.
How:          ``inbox_for`` → ``rows_for_mode`` → ``rows_for_apparatus`` → ``rows_for_arm`` →
              ``filter_posture`` → ``signed_map``; ``list_tasks``, ``register_for``,
              ``library_index``, ``signoff_out`` and ``derive_remeasure`` (each route's own
              function, so a row reads what that page reads) → ``decision_rows`` →
              ``record_due`` → ``for_viewer`` → the response (the count's with its ``ETag``).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md,
              docs/adr/0015-signoffs-expire-with-the-apparatus.md
Works with:   src/crb/server/decisions.py (the derivation and the clock),
              src/crb/server/routes/capability.py (``signed_map`` — the one reading),
              src/crb/server/routes/factory.py (``list_tasks`` — the items as served),
              src/crb/server/routes/library.py (``library_index`` — the entries),
              src/crb/server/routes/learn.py (``derive_remeasure`` — the stale cells),
              src/crb/server/worker.py (the idle pass that keeps the clock running),
              ui/src/screens/Decisions/useDecisionCount.ts (reads both modes),
              docs/API.md#capability-routing-forecast-sign-off (the routes' contract)
Tested by:    tests/test_server_decisions.py, tests/test_decisions_kinds.py
Touch when:   never for a new repository (``?repo=`` names any connected one); a human act is
              added to the product (src/crb/server/decisions.py first).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.capability import PROJECTION_CLASS_SIZE, CapabilityCell
from crb.core.redact import redact
from crb.core.version import APPARATUS_VERSION
from crb.server.auth import ViewerDep
from crb.server.decisions import (
    DecisionRow,
    age_seconds,
    can_act,
    decision_rows,
    for_viewer,
    record_due,
)
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    Principal,
    SessionFactoryDep,
    SettingsDep,
    request_id,
)
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
from crb.server.routes.factory import _way_forward, list_tasks
from crb.server.routes.learn import derive_remeasure, in_flight_runs
from crb.server.routes.library import library_index
from crb.server.routes.oracle import latest_controls_verdict
from crb.server.routes.repos import get_repo_or_404
from crb.server.routes.signoffs import (
    load_signoff_rows,
    posture_now,
    signoff_out,
    signoff_store_intact,
)
from crb.server.settings import ROLE_RANK
from crb.store.ledger import DbLedger
from crb.store.models import Repo

log = logging.getLogger("crb.server.decisions")
router = APIRouter(tags=["decisions"])
_ERR = {"model": ErrorEnvelope}

#: Who the inputs are read as: the routes this one reuses take a viewer and read nothing of
#: it (each ``del``s it), and the idle pass has no person. A viewer — never a wider role.
_READER = Principal(id="", display_name="the decisions inbox", email="", role="viewer", issuer="")

#: The count is revalidated on every read (its ETag makes an unchanged one a 304): a browser
#: that kept it would show a person who has just acted the act still waiting.
COUNT_CACHE_CONTROL = "private, no-cache"
#: The list carries its clock, so no reading repeats another's bytes: served fresh, no ETag.
LIST_CACHE_CONTROL = "private, no-store"


class DecisionOut(BaseModel):
    """One due decision as the person reading it may act on it, with the clock."""

    repo: str
    kind: str
    #: What the act is about: ``<class>|<size>`` for a cell row, the item id for a factory
    #: row, the entry id, the sign-off id, or ``<full cell>|<mode>`` for a re-measurement.
    key: str
    title: str
    #: The role that takes the act (``viewer`` = anyone reads it).
    role: str
    #: The line under the title: n, interval and reason code; the gaps; the estimate.
    evidence: str = ""
    #: The routing reason code at the evidence line's tail ("" when none).
    reason_code: str = ""
    #: The verb on the button — the row's act when ``can_act``, else ``Read``.
    act: str
    #: Where the act is recorded, or read.
    href: str
    #: Whether the person reading holds a role that can take the act.
    can_act: bool
    #: For ``signoff_stale``: the attestation as ``GET /signoffs`` serves it.
    signoff: dict[str, Any] | None = None
    #: When this row FIRST became due (ISO-8601, UTC). A row that went away and came back
    #: keeps its original stamp: the wait is the person's, not the derivation's.
    due_since: str
    #: How long it has been due, in whole seconds.
    age_s: int


class DecisionError(BaseModel):
    """A repository whose inputs could not be read: the refusal, so the count reads incomplete."""

    repo: str
    status: int
    code: str
    message: str


class DecisionList(BaseModel):
    """``GET /decisions`` body. ``as_of`` is when this reading was taken and stamped."""

    items: list[DecisionOut]
    total: int
    as_of: str
    #: The repositories this reading covered (one, or every connected repository).
    repos: list[str]
    #: Those with at least one measured cell — the rest are connected and never measured.
    measured: list[str]
    #: Repositories whose inputs could not be read; while any is listed the count is incomplete.
    errors: list[DecisionError]


class DecisionCount(BaseModel):
    """``GET /decisions?count=1`` body: the badge's number, the clock left alone."""

    total: int
    #: The number of rows each role takes (``viewer`` = rows anyone reads).
    by_role: dict[str, int]
    #: Repositories whose inputs could not be read; the badge shows no number while any is.
    errors: list[str]


@dataclass(frozen=True)
class Inbox:
    """One repository's rows, and whether it has a measured cell at all."""

    rows: list[DecisionRow]
    measured: bool


def _repos(db: Session, repo: str) -> list[str]:
    """The repositories one reading covers: the one named, which must be connected (404
    ``not_found`` otherwise, as every per-repository route answers — an empty inbox for a
    name nobody connected would read as "nothing is waiting", and the name goes on to a
    filesystem path), or every connected repository."""
    if repo:
        return [get_repo_or_404(db, repo).name]
    return list(db.execute(select(Repo.name).order_by(Repo.name)).scalars().all())


def _served_cells(
    db: Session, factory: sessionmaker[Session], settings: Any, repo: str
) -> Sequence[CapabilityCell]:
    """The map ``GET /capability-map`` serves by default: sighted rows, the current apparatus,
    the repository's own checks arm (ADR-0024) and this deployment's posture class
    (ADR-0019 §8), under the latest controls verdict, sign-offs overlaid."""
    current = rows_for_arm(
        factory,
        repo,
        rows_for_apparatus(rows_for_mode(DbLedger(factory).rows(repo=repo), "sighted"), "current"),
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
    return cmap.cells


def _served_tasks(
    db: Session, factory: sessionmaker[Session], settings: Any, repo: str
) -> list[dict[str, Any]]:
    """The factory items as ``GET /factory/{repo}/tasks`` serves them — its own function, so an
    item not yet run carries the entry gate's preview and a stopped one its way forward, as
    the Factory page shows. No backlog is no rows."""
    try:
        return [t.model_dump() for t in list_tasks(repo, _READER, db, factory, settings)]
    except ApiError as exc:
        if exc.status_code == 404:
            return []
        raise


def _chain_tasks(settings: Any, repo: str) -> list[dict[str, Any]]:
    """The factory items as the chain records them, each with the way forward
    ``GET /factory/{repo}/tasks`` would serve it (whether an approver may fund a calibration
    build) — what the idle pass can read without the API's settings."""
    out: list[dict[str, Any]] = []
    for v in FactoryHome(settings.home, repo).task_views():
        d = v.to_dict()
        way = _way_forward(repo, d)
        out.append({**d, "way_forward": way.model_dump() if way is not None else None})
    return out


def _stale_signoffs(db: Session, repo: str, posture_class: str) -> list[dict[str, Any]]:
    """The repository's attestations as ``GET /signoffs`` serves them (:func:`signoff_out`,
    read against ``posture_class``, the posture the deployment grades the repository in), the
    stale ones only."""
    rows = load_signoff_rows(db, repo)
    chain_ok = signoff_store_intact(db)
    served = (
        signoff_out(db, r, rows, posture_current=posture_class, chain_ok=chain_ok)
        for r in rows
        if not r.revoke
    )
    return [s.model_dump() for s in served if s.stale and not s.revoked]


def _remeasure(
    db: Session, factory: sessionmaker[Session], settings: Any, repo: str
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    """``GET /learn/remeasure``'s plan against the apparatus in force, and the cells whose
    queued runs have not finished (they ask nobody for anything)."""
    plan = derive_remeasure(
        db, factory, repo, apparatus=APPARATUS_VERSION, settings=settings
    ).to_dict()
    busy = {
        (str(c["label"]), str(c["mode"]))
        for c in plan["cells"]
        if in_flight_runs(
            db, repo, cell=str(c["label"]), mode=str(c["mode"]), apparatus=APPARATUS_VERSION
        )
    }
    return plan, busy


def inbox_for(
    db: Session,
    factory: sessionmaker[Session],
    settings: Any,
    repo: str,
    *,
    cells: Sequence[CapabilityCell] | None = None,
    posture_class: str | None = None,
) -> Inbox:
    """The repository's inbox from the readings each page serves, with the API's own
    settings. The worker's idle pass has other settings, so it passes what they cannot give:
    ``cells`` from its own served map (``Worker._served_map`` — the same default reading) and
    ``posture_class`` (``Worker._deployment_posture_class``). Its factory items are then the
    chain's own views with their way forward, without the entry gate's preview for an item no
    run has reached — which is why it keeps ``not_built`` open
    (:data:`crb.server.decisions.IDLE_KEEPS_OPEN`) and this route resolves that kind."""
    if cells is None:
        cells = _served_cells(db, factory, settings, repo)
    if posture_class is None:
        posture = posture_now(db, settings, repo)
        tasks = _served_tasks(db, factory, settings, repo)
    else:
        posture = posture_class
        tasks = _chain_tasks(settings, repo)
    register = register_for(db, factory, settings.home, repo, settings=settings).to_dict()
    plan, busy = _remeasure(db, factory, settings, repo)
    rows = decision_rows(
        cells,
        tasks,
        register,
        repo=repo,
        library=library_index(repo, _READER, db, factory).model_dump(),
        stale=_stale_signoffs(db, repo, posture),
        remeasure=plan,
        in_flight=busy,
    )
    return Inbox(rows=rows, measured=any(c.n > 0 for c in cells))


def rows_for(
    db: Session,
    factory: sessionmaker[Session],
    settings: Any,
    repo: str,
    *,
    cells: Sequence[CapabilityCell] | None = None,
    posture_class: str | None = None,
) -> list[DecisionRow]:
    """The repository's inbox rows (:func:`inbox_for`) — what the idle pass stamps, with
    ``record_due(..., keep_open=IDLE_KEEPS_OPEN)``."""
    return inbox_for(db, factory, settings, repo, cells=cells, posture_class=posture_class).rows


def _conditional(request: Request, body: BaseModel, cache_control: str) -> Response:
    """The body with a strong ``ETag`` (a digest of its bytes), or ``304 Not Modified`` with
    no body when the caller already holds exactly those bytes."""
    raw = body.model_dump_json().encode()
    tag = f'"{hashlib.sha256(raw).hexdigest()[:32]}"'
    headers = {"ETag": tag, "Cache-Control": cache_control}
    held = {t.strip() for t in request.headers.get("if-none-match", "").split(",")}
    if tag in held:
        return Response(status_code=304, headers=headers)
    return Response(content=raw, media_type="application/json", headers=headers)


@router.get(
    "/decisions",
    response_model=DecisionList | DecisionCount,
    responses={
        304: {"description": "Not modified (the count only): the ETag sent still holds"},
        401: _ERR,
        404: _ERR,
    },
    summary="Every decision due now, with its act, its link and how long it has waited",
)
def list_decisions(
    request: Request,
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    *,
    repo: str = Query("", description="One repository; empty = every connected repository"),
    count: bool = Query(False, description="The badge's count only; never writes the clock"),
) -> Response:
    """Derive, then — the full reading only — stamp, fit to the viewer and serve. The stamping
    is why the full reading writes: it is the observation that a decision was due at this
    moment, and without it the age could only ever start when somebody happened to look."""
    names = _repos(db, repo)
    errors: list[DecisionError] = []
    inboxes: list[tuple[str, Inbox]] = []
    for name in names:
        try:
            inboxes.append((name, inbox_for(db, factory, settings, name)))
        except ApiError as exc:
            db.rollback()
            errors.append(
                DecisionError(repo=name, status=exc.status_code, code=exc.code, message=exc.message)
            )
        except Exception as exc:  # one repository's fault stays its own (P-612)
            # The worker's idle pass isolates each repository the same way. Anything but a
            # refusal is logged with the request id, as the app's own 500 handler logs it, and
            # the repository is named: the rest of the inbox is still served.
            db.rollback()
            log.error(
                "decisions: %s's inputs could not be read: %s (request_id=%s): %s",
                name,
                type(exc).__name__,
                request_id(request),
                redact(str(exc)),
                exc_info=exc,
            )
            errors.append(
                DecisionError(
                    repo=name,
                    status=500,
                    code="internal_error",
                    message="this repository's inputs could not be read; the error is logged "
                    "with the request id",
                )
            )

    if count:
        by_role: dict[str, int] = {}
        for _name, inbox in inboxes:
            for row in inbox.rows:
                role = for_viewer(row, viewer.id).role
                by_role[role] = by_role.get(role, 0) + 1
        counted = DecisionCount(
            total=sum(by_role.values()), by_role=by_role, errors=[e.repo for e in errors]
        )
        return _conditional(request, counted, COUNT_CACHE_CONTROL)

    items: list[DecisionOut] = []
    as_of = ""
    for name, inbox in inboxes:
        # the clock is kept on the rows as they are for everyone: the wait is the decision's
        live = record_due(db, name, inbox.rows)
        for neutral in inbox.rows:
            rec = live[(neutral.kind, neutral.key)]
            as_of = as_of or rec.last_seen
            row = for_viewer(neutral, viewer.id)
            allowed = can_act(row, viewer.role, ROLE_RANK)
            items.append(
                DecisionOut(
                    repo=name,
                    kind=row.kind,
                    key=row.key,
                    title=row.title,
                    role=row.role,
                    evidence=row.evidence,
                    reason_code=row.reason_code,
                    act=row.act if allowed else "Read",
                    href=row.href,
                    can_act=allowed,
                    signoff=dict(row.signoff) if row.signoff is not None else None,
                    due_since=rec.first_due,
                    age_s=age_seconds(rec.first_due),
                )
            )
    db.commit()
    listed = DecisionList(
        items=items,
        total=len(items),
        as_of=as_of,
        repos=names,
        measured=[n for n, i in inboxes if i.measured],
        errors=errors,
    )
    return Response(
        content=listed.model_dump_json().encode(),
        media_type="application/json",
        headers={"Cache-Control": LIST_CACHE_CONTROL},
    )
