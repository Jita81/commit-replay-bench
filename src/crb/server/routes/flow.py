"""``GET /flow`` — how long each value stream takes, what it spent, and what nobody measured.

One read, one repository, every stream. It stores nothing and computes nothing of its own: it
loads the repository's graded rows (through ``DbLedger``, so a false-Q1 row refuses to load and
the request answers ``409 false_q1_refused`` — a flow reading is never folded over untrusted
rows, exactly as the capability map is not), its sign-off records, and the factory chain's
events, and hands them to :func:`crb.server.flow.build_flow`.

Every figure arrives with its ``n``, the ``apparatus`` this deployment reports and a ``method``
sentence saying the numbers are a fold over stored records. A duration nobody has produced yet
is ``null`` with a ``reason``, never 0; a spend with no priced row is ``null`` with the count of
unpriced rows; and each stream lists the figures its definition of done asks for that nothing
records, with the gap that would close them.

Navigation
----------
What it is:   The ``/flow`` route module — the endpoint each screen reads its own stream's lead
              time, spend and counts from.
What it does: Resolves the repository (404 when unknown), loads its rows, sign-offs and factory
              events, reads the go-live checklist (``golive_counts`` — the platform stream's
              count of proven, attested and unproven lines), folds them with
              ``build_flow``, and re-types the reading into ``FlowOut``. A viewer may read it;
              the deployment's account figures are served to an admin only (as
              ``GET /admin/users`` is); nothing here writes.
How:          ``get_repo_or_404`` → ``DbLedger(factory).rows(repo=…)`` →
              ``load_signoff_records`` → ``FactoryHome(settings.home, repo).events()`` →
              ``build_flow`` → ``FlowOut.model_validate(reading.to_dict())``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/flow.py (``build_flow`` — every rule lives there),
              src/crb/server/schemas_flow.py (the response shape),
              src/crb/server/routes/signoffs.py (``load_signoff_records``),
              src/crb/server/factory_state.py (``FactoryHome.events``),
              src/crb/server/routes/repos.py (``get_repo_or_404``),
              src/crb/server/routes/golive.py (``golive_counts``),
              ui/src/api/hooks.ts (``useFlow`` — the one client that reads it),
              docs/API.md (the "Flow" section — the contract this route serves)
Tested by:    tests/test_server_routes_flow.py
Touch when:   a stream's milestone pair changes (that is src/crb/server/flow.py and the
              stream's MEASURE criterion, not this file); never for a new repository.
Claims:       Every duration and spend here is derived from records already written, with its n
              (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from crb.server.auth import ViewerDep
from crb.server.deps import DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.flow import build_flow
from crb.server.routes.golive import golive_counts
from crb.server.routes.repos import get_repo_or_404
from crb.server.routes.signoffs import load_signoff_records
from crb.server.schemas_flow import FlowOut
from crb.server.settings import ROLE_RANK
from crb.store.ledger import DbLedger

router = APIRouter(tags=["flow"])
_ERR = {"model": ErrorEnvelope}


@router.get(
    "/flow",
    response_model=FlowOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Each value stream's own lead time, spend and counts, derived from stored records",
)
def flow(
    request: Request,
    *,
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> FlowOut:
    get_repo_or_404(db, repo)
    rows = list(DbLedger(factory).rows(repo=repo))
    reading = build_flow(
        db,
        repo=repo,
        rows=rows,
        signoffs=load_signoff_records(db, repo),
        factory_events=FactoryHome(settings.home, repo).events(),
        admin=ROLE_RANK.get(viewer.role, -1) >= ROLE_RANK["admin"],
        # the platform stream counts the go-live lines as /golive reads them (G-584), from a
        # reading at most a minute old: /flow never runs the deep probes on every read
        golive=golive_counts(request, db, factory, settings),
    )
    return FlowOut.model_validate(reading.to_dict())
