"""``/factory/{repo}/*`` — the forward-mode factory's API: backlog, tasks, gap sign-offs, evidence.

The factory manufactures NEW work under the same governance as a replay (ADR-0001
belts, the append-only ledger, evidence packs, an independent review with the verdict
recorded before any edit — :mod:`crb.factory.loop`). This module serves its records:

* ``POST /factory/{repo}/backlog`` (operator) — register a backlog: the items are
  validated by the factory's own rules, frozen and hashed (:mod:`crb.factory.backlog`),
  written under ``CRB_HOME`` with the freeze recorded in the evidence chain; optional
  operator-authored oracles per item. Refused (409) while a ``factory`` run for the repo
  is queued or running — the hash a run verifies against must not move under it.
* ``GET /factory/{repo}/backlog`` — the active frozen backlog (404 when none).
* ``GET /factory/{repo}/tasks`` — every item's latest state, folded from the evidence.
* ``POST /factory/{repo}/tasks/{id}/signoff-gap`` (approver) — sign one structural
  gap: appended to the hash-chained gap ledger and echoed into the evidence chain.
  Value slots cannot be signed (the DoR gate refuses them by design).
* ``GET /factory/{repo}/evidence`` — the chain, oldest first.

Running the loop is a run kind: ``POST /runs {kind: "factory"}`` (see ``routes/runs.py``
and the worker); this module never builds anything.

Navigation
----------
What it is:   The API over the factory's per-repo state (``FactoryHome``).
What it does: Registers/freezes backlogs, serves the task view and the evidence chain,
              records approver gap sign-offs; every write is append-only and hashed.
How:          Thin FastAPI handlers → ``crb.server.factory_state.FactoryHome`` →
              ``crb.factory`` dataclasses; role gates from ``crb.server.auth``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/factory_state.py (the state), src/crb/factory/backlog.py (item
              validation + hash), src/crb/factory/readiness.py (slots, sign), src/crb/server/worker.py
              (the ``factory`` run kind that consumes the backlog), docs/API.md (the contract),
              ui/src/screens/Factory/FactoryPage.tsx (the screen)
Tested by:    tests/test_server_routes_factory.py
Touch when:   a factory record gains a field the UI needs (extend TaskView + FactoryTask in
              ui/src/api/types.ts together); a new write path (keep it append-only, role-gated).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from crb.factory.backlog import KINDS, LEVELS, BacklogError, BacklogItem
from crb.factory.readiness import SLOT_VALUE, sign, slots_for
from crb.factory.testfirst import AuthoredTest
from crb.server.auth import ApproverDep, OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.routes.repos import get_repo_or_404
from crb.store.models import Run

router = APIRouter(tags=["factory"])
_ERR = {"model": ErrorEnvelope}
ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running")


# --- schemas --------------------------------------------------------------------------


class BacklogItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    title: str = Field(min_length=1, max_length=200)
    kind: str = "code"
    description: str = Field(default="", max_length=8000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    capability_class: str = Field(default="(unclassified)", max_length=64)
    size_estimate: str = Field(default="S", max_length=4)
    structural_facts: list[str] = Field(default_factory=list, max_length=100)
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    level: str = "L1"
    labels: dict[str, str] = Field(default_factory=dict)


class AuthoredTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=400)
    content: str = Field(min_length=1, max_length=200_000)


class BacklogRegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BacklogItemIn] = Field(min_length=1, max_length=500)
    #: operator-authored oracles, keyed by item id (author recorded as ``operator:<id>``)
    authored: dict[str, AuthoredTestIn] = Field(default_factory=dict)


class BacklogItemOut(BaseModel):
    id: str
    title: str
    kind: str
    capability_class: str
    size: str
    level: str
    depends_on: list[str]
    structural_facts: list[str]
    has_authored_test: bool


class FactoryBacklogOut(BaseModel):
    repo: str
    hash: str
    frozen_at: str | None
    items: list[BacklogItemOut]


class FactoryTaskOut(BaseModel):
    id: str
    title: str
    capability_class: str
    size: str
    kind: str
    status: str
    dor_gaps: list[str]
    route_hint: str
    red_proof: bool | None
    build_status: str
    pr_url: str | None
    review_verdict: str | None
    last_event: str


class GapSignoffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=4000)


class GapSignoffOut(BaseModel):
    item_id: str
    slot: str
    kind: str
    verifier: str
    signed_at: str
    row_hash: str


class FactoryEventOut(BaseModel):
    seq: int
    kind: str
    item_id: str
    actor: str
    created: str
    payload: dict[str, Any]
    row_hash: str


class FactoryEvidenceOut(BaseModel):
    repo: str
    total: int
    verified: bool
    items: list[FactoryEventOut]


# --- helpers ---------------------------------------------------------------------------


def _home(settings: Any, repo: str) -> FactoryHome:
    return FactoryHome(settings.home, repo)


def _active_factory_run(db: Any, repo: str) -> Run | None:
    q = (
        select(Run)
        .where(Run.repo == repo, Run.kind == "factory", Run.status.in_(ACTIVE_STATUSES))
        .limit(1)
    )
    run: Run | None = db.execute(q).scalars().first()
    return run


def _backlog_out(home: FactoryHome) -> FactoryBacklogOut | None:
    backlog = home.load_backlog()
    if backlog is None:
        return None
    authored = home.authored()
    return FactoryBacklogOut(
        repo=home.repo,
        hash=backlog.backlog_hash,
        frozen_at=backlog.frozen_at or None,
        items=[
            BacklogItemOut(
                id=i.id,
                title=i.title,
                kind=i.kind,
                capability_class=i.capability_class,
                size=i.size_estimate,
                level=i.level,
                depends_on=list(i.depends_on),
                structural_facts=list(i.structural_facts),
                has_authored_test=i.id in authored,
            )
            for i in backlog.ordered()
        ],
    )


# --- routes ----------------------------------------------------------------------------


@router.get(
    "/factory/{repo}/backlog",
    response_model=FactoryBacklogOut,
    responses={401: _ERR, 404: _ERR},
    summary="The repo's active frozen backlog (hash, freeze time, items in dependency order)",
)
def get_backlog(
    repo: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> FactoryBacklogOut:
    del viewer
    get_repo_or_404(db, repo)
    out = _backlog_out(_home(settings, repo))
    if out is None:
        raise ApiError(404, "not_found", f"no backlog registered for {repo!r}")
    return out


@router.post(
    "/factory/{repo}/backlog",
    response_model=FactoryBacklogOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register and FREEZE a backlog (validated, hashed, recorded); optional authored oracles",
)
def register_backlog(
    repo: str, body: BacklogRegisterIn, operator: OperatorDep, db: DbDep, settings: SettingsDep
) -> FactoryBacklogOut:
    get_repo_or_404(db, repo)
    active = _active_factory_run(db, repo)
    if active is not None:
        raise ApiError(
            409,
            "factory_run_active",
            f"a factory run ({active.id}) is {active.status} on {repo!r}: the backlog it "
            "verifies against cannot change under it — cancel it or wait",
        )
    for it in body.items:
        if it.kind not in KINDS:
            raise ApiError(422, "validation_error", f"item {it.id!r}: kind must be one of {KINDS}")
        if it.level not in LEVELS:
            raise ApiError(
                422, "validation_error", f"item {it.id!r}: level must be one of {LEVELS}"
            )
    unknown = sorted(set(body.authored) - {it.id for it in body.items})
    if unknown:
        raise ApiError(422, "validation_error", f"authored tests for unknown items: {unknown}")
    home = _home(settings, repo)
    try:
        items = [
            BacklogItem(
                id=it.id,
                title=it.title,
                kind=it.kind,
                description=it.description,
                acceptance_criteria=tuple(it.acceptance_criteria),
                capability_class=it.capability_class,
                size_estimate=it.size_estimate,
                structural_facts=tuple(it.structural_facts),
                depends_on=tuple(it.depends_on),
                level=it.level,
                labels=dict(it.labels),
            )
            for it in body.items
        ]
        authored = {
            item_id: AuthoredTest(path=t.path, content=t.content, author=f"operator:{operator.id}")
            for item_id, t in body.authored.items()
        }
        backlog = home.register_backlog(items, actor=operator.id)
    except (BacklogError, ValueError) as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    home.save_authored(authored)
    out = _backlog_out(home)
    assert out is not None and out.hash == backlog.backlog_hash
    return out


@router.get(
    "/factory/{repo}/tasks",
    response_model=list[FactoryTaskOut],
    responses={401: _ERR, 404: _ERR},
    summary="Every backlog item's latest state — DoR gaps, route, RED proof, build, PR, verdict — from the evidence",
)
def list_tasks(
    repo: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> list[FactoryTaskOut]:
    del viewer
    get_repo_or_404(db, repo)
    return [FactoryTaskOut(**v.to_dict()) for v in _home(settings, repo).task_views()]


@router.post(
    "/factory/{repo}/tasks/{item_id}/signoff-gap",
    response_model=GapSignoffOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Sign one STRUCTURAL gap of an item (appended to the gap ledger and the evidence chain)",
)
def signoff_gap(  # noqa: PLR0917 — FastAPI dependencies + path/body
    repo: str,
    item_id: str,
    body: GapSignoffIn,
    approver: ApproverDep,
    db: DbDep,
    settings: SettingsDep,
) -> GapSignoffOut:
    get_repo_or_404(db, repo)
    home = _home(settings, repo)
    backlog = home.load_backlog()
    if backlog is None:
        raise ApiError(404, "not_found", f"no backlog registered for {repo!r}")
    item = next((i for i in (*backlog.items, *backlog.evolutions) if i.id == item_id), None)
    if item is None:
        raise ApiError(404, "not_found", f"no item {item_id!r} in the backlog of {repo!r}")
    slots = {s.name: s for s in slots_for(item.capability_class)}
    slot = slots.get(body.slot)
    if slot is None:
        raise ApiError(
            422,
            "validation_error",
            f"{body.slot!r} is not a slot of class {item.capability_class!r} "
            f"(known: {sorted(slots)})",
        )
    if slot.kind == SLOT_VALUE:
        raise ApiError(
            422,
            "value_slot_unsignable",
            f"{body.slot!r} is a VALUE slot: a value nobody derived from the answer cannot be "
            "signed into readiness (docs/EVIDENCE-AND-CLAIMS.md)",
        )
    record = sign(home.gap_ledger(), item, body.slot, body.answer, verifier=approver.id)
    home.evidence(actor=approver.id).record_gap_signoff(
        {
            "item_id": record.item_id,
            "slot": record.slot,
            "kind": record.kind,
            "verifier": record.verifier,
            "signed_at": record.signed_at,
            "row_hash": record.row_hash,
        }
    )
    return GapSignoffOut(
        item_id=record.item_id,
        slot=record.slot,
        kind=record.kind,
        verifier=record.verifier,
        signed_at=record.signed_at,
        row_hash=record.row_hash,
    )


@router.get(
    "/factory/{repo}/evidence",
    response_model=FactoryEvidenceOut,
    responses={401: _ERR, 404: _ERR},
    summary="The factory evidence chain, oldest first (hash-verified on read)",
)
def get_evidence(  # noqa: PLR0917 — FastAPI dependencies + query params
    repo: str,
    viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    item_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> FactoryEvidenceOut:
    del viewer
    get_repo_or_404(db, repo)
    home = _home(settings, repo)
    events = home.events()
    verified = True
    try:
        if events:
            home.evidence().verify()
    except Exception:  # a broken chain is reported, never hidden
        verified = False
    if item_id:
        events = [e for e in events if e.item_id == item_id]
    page = events[offset : offset + limit]
    return FactoryEvidenceOut(
        repo=repo,
        total=len(events),
        verified=verified,
        items=[
            FactoryEventOut(
                seq=i + offset,
                kind=e.kind,
                item_id=e.item_id,
                actor=e.actor,
                created=e.created,
                payload=dict(e.payload),
                row_hash=e.row_hash,
            )
            for i, e in enumerate(page)
        ],
    )
