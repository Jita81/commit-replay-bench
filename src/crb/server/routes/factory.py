"""``/factory/{repo}/*`` — the forward-mode factory's API: backlog, tasks, gap sign-offs, evidence.

The factory manufactures NEW work under the same governance as a replay (ADR-0001
belts, the append-only ledger, evidence packs, an independent review with the verdict
recorded before any edit — :mod:`crb.factory.loop`). This module serves its records:

* ``POST /factory/{repo}/backlog`` (operator) — register a backlog: the items are
  validated by the factory's own rules, frozen and hashed (:mod:`crb.factory.backlog`),
  written under ``CRB_HOME`` with the freeze recorded in the evidence chain; optional
  operator-authored oracles per item. Refused (409) while a ``factory`` run for the repo
  is queued or running — the hash a run verifies against must not move under it.
* ``GET /factory/{repo}/backlog`` — the active frozen backlog (404 when none), with the
  delivery pre-flight (``delivery``): whether a run could open a pull request for this
  repository, by the same rule the worker's credentials follow (J-FAC-3).
* ``GET /factory/{repo}/tasks`` — every item's latest state, folded from the evidence,
  with every refusal's reason and the newest build's ids (J-FAC-4 / F15).
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
              (the ``factory`` run kind that consumes the backlog; ``_delivery_credentials`` is
              the rule ``_delivery_preflight`` mirrors), src/crb/server/routes/github.py (the
              installation record the pre-flight reads), docs/API.md (the contract),
              ui/src/screens/Factory/FactoryPage.tsx (the screen)
Tested by:    tests/test_server_routes_factory.py
Touch when:   a factory record gains a field the UI needs (extend TaskView + FactoryTask in
              ui/src/api/types.ts together); a new write path (keep it append-only, role-gated).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from crb.core.capability import PROJECTION_CLASS_SIZE
from crb.core.routing import ROUTE_DELIVER
from crb.core.spec import SIZE_TIER_NAMES
from crb.factory.backlog import KINDS, LEVELS, BacklogError, BacklogItem
from crb.factory.evidence import verify_events
from crb.factory.readiness import CATALOGUE, SLOT_VALUE, sign, slots_for
from crb.factory.testfirst import AuthoredTest
from crb.server.auth import ApproverDep, OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.routes.capability import rows_for_apparatus, rows_for_mode, signed_map
from crb.server.routes.oracle import latest_controls_verdict
from crb.server.routes.repos import get_repo_or_404
from crb.store.ledger import DbLedger
from crb.store.models import GitHubInstallation, Grade, Repo, Run

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
    #: What and why, as the operator wrote it — served so a revised backlog can start
    #: from the active one (J-FAC-15).
    description: str = ""


class DeliveryPreflightOut(BaseModel):
    """Whether a factory run could open a pull request for this repository — the worker's
    credentials rule (``Worker._delivery_credentials``) answered BEFORE any build is paid
    for: linked through the GitHub App, on the app's own host, the installation on record,
    not suspended, holding ``Contents: write`` and ``Pull requests: write``. ``reason`` is
    the sentence the page shows when it cannot; ``reason_code`` is one of ``ok``,
    ``not_linked``, ``app_not_configured``, ``host_mismatch``, ``installation_missing``,
    ``installation_suspended``, ``read_only``."""

    can_deliver: bool = False
    reason_code: str = "not_linked"
    reason: str = ""
    full_name: str = ""
    default_branch: str = ""
    installation_id: int | None = None
    account_login: str = ""


class FactoryBacklogOut(BaseModel):
    repo: str
    hash: str
    frozen_at: str | None
    items: list[BacklogItemOut]
    #: J-FAC-3 — where a run would deliver, or why it cannot.
    delivery: DeliveryPreflightOut = DeliveryPreflightOut()


class CellRouteOut(BaseModel):
    """The capability map's decision for the item's (class × size) cell — the SAME signed
    map the delivery gate reads (sighted rows, current apparatus, the repo's latest
    controls verdict, sign-offs overlaid — DL-038), shown BEFORE a run spends anything.
    ``route`` is empty when nobody has measured the cell: delivery would be withheld."""

    route: str = ""
    reason_code: str = ""
    reason: str = ""
    n: int = 0
    #: The cell's measured clean rate with its 95 % Wilson interval and the apparatus its
    #: rows carry — the provenance behind the route (0 / empty when not measured).
    point: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    apparatus_versions: list[str] = []
    #: True only when the gate would let a clean build of this item open a pull request.
    deliverable: bool = False


class RefusalOut(BaseModel):
    """Why the loop stopped the item, from the chain (``factory_state.Refusal``)."""

    step: str
    reason: str
    reason_code: str = ""
    measured_route: str = ""


class FactoryTaskOut(BaseModel):
    id: str
    title: str
    capability_class: str
    size: str
    kind: str
    status: str
    #: The unsigned STRUCTURAL slots: what blocks the build and what an approver can sign.
    dor_gaps: list[str]
    #: The open VALUE slots: they route the item test-first and are never signable.
    value_gaps: list[str] = []
    route_hint: str
    red_proof: bool | None
    build_status: str
    pr_url: str | None
    review_verdict: str | None
    last_event: str
    #: J-FAC-4 — the newest refusal since the item's last readiness pass; null = none.
    refusal: RefusalOut | None = None
    #: The outcome's error (a harness failure, a refused push); "" when none.
    error: str = ""
    #: F15 — the newest build's ledger task (the oracle commit), run, pack and row.
    task_id: str = ""
    run_id: str = ""
    pack_hash: str = ""
    row_hash: str = ""
    #: F28 — the cell's route before the run (absent fields = not measured).
    cell_route: CellRouteOut = CellRouteOut()


class CatalogueSlotOut(BaseModel):
    name: str
    question: str
    #: ``structural`` blocks the build until signed; ``value`` only routes (readiness.py).
    kind: str


class CatalogueClassOut(BaseModel):
    capability_class: str
    slots: list[CatalogueSlotOut]


class FactoryCatalogueOut(BaseModel):
    """What a backlog item may be made of: the change classes the readiness gate knows and
    the facts each needs (F24 — the freeze form asks these questions instead of taking raw
    JSON), the size tiers and the item kinds / levels the backlog accepts."""

    classes: list[CatalogueClassOut]
    sizes: list[str]
    kinds: list[str]
    levels: list[str]


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


def _delivery_preflight(db: Any, settings: Any, repo: Repo) -> DeliveryPreflightOut:
    """The worker's ``_delivery_credentials`` rule, answered from the record (no call to
    GitHub: the worker re-reads the permissions live at delivery, so a pass here is
    "nothing on record stops it", never a promise)."""
    link = dict(dict(repo.config_json or {}).get("github") or {})
    try:
        installation_id = int(link.get("installation_id") or 0) or None
    except (TypeError, ValueError):
        installation_id = None
    out = DeliveryPreflightOut(
        full_name=str(link.get("full_name") or ""),
        default_branch=str(link.get("default_branch") or ""),
        installation_id=installation_id,
    )
    admin_next = "then Sync installations in Settings."
    if installation_id is None:
        out.reason_code = "not_linked"
        out.reason = (
            "Delivery is not possible for this repository: it is connected by URL, not "
            "through the GitHub App. Connect it through the GitHub App with Contents: write "
            f"and Pull requests: write, {admin_next}"
        )
        return out
    if not settings.github.enabled:
        out.reason_code = "app_not_configured"
        out.reason = (
            "Delivery is not possible: the GitHub App is not configured on this deployment, "
            "so no installation token can be minted. An admin registers the app for this "
            "deployment (the GitHub App guide), then syncs installations in Settings."
        )
        return out
    try:
        host = urlsplit(str(repo.url or "")).hostname or ""
        app_host = urlsplit(str(settings.github.web_url)).hostname or ""
    except ValueError:
        host, app_host = "", ""
    if not host or host != app_host:
        out.reason_code = "host_mismatch"
        out.reason = (
            f"Delivery is not possible: the repository URL is not on {app_host or 'the GitHub host the app is registered with'}, "
            "so the installation token is never sent to it. Set the URL back to the linked "
            "GitHub repository in the repository's config."
        )
        return out
    inst = db.get(GitHubInstallation, installation_id)
    if inst is None:
        out.reason_code = "installation_missing"
        out.reason = (
            f"Delivery is not possible: installation {installation_id} is not on record. "
            f"Sync installations in Settings; if it stays missing, reinstall the app on "
            f"{out.full_name.split('/')[0] or 'the organisation'} and connect the repository again."
        )
        return out
    out.account_login = inst.account_login
    if inst.suspended:
        out.reason_code = "installation_suspended"
        out.reason = (
            f"Delivery is not possible: the {inst.account_login} installation is suspended "
            "or was removed. Restore it in GitHub, then Sync installations in Settings."
        )
        return out
    perms = dict(inst.permissions_json or {})
    if perms.get("contents") != "write" or perms.get("pull_requests") != "write":
        held = ", ".join(f"{k}: {v}" for k, v in sorted(perms.items())) or "none"
        out.reason_code = "read_only"
        out.reason = (
            f"Delivery is not possible: the {inst.account_login} installation is read-only "
            f"({held}). Grant Contents: write and Pull requests: write on the installation in "
            f"GitHub, {admin_next}"
        )
        return out
    out.can_deliver = True
    out.reason_code = "ok"
    return out


def _backlog_out(home: FactoryHome, delivery: DeliveryPreflightOut) -> FactoryBacklogOut | None:
    backlog = home.load_backlog()
    if backlog is None:
        return None
    authored = home.authored()
    return FactoryBacklogOut(
        repo=home.repo,
        hash=backlog.backlog_hash,
        frozen_at=backlog.frozen_at or None,
        delivery=delivery,
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
                description=i.description,
            )
            for i in backlog.ordered()
        ],
    )


# --- routes ----------------------------------------------------------------------------


@router.get(
    "/factory/catalogue",
    response_model=FactoryCatalogueOut,
    responses={401: _ERR},
    summary="The change classes, their structural-fact slots, the sizes, kinds and levels a backlog item may use",
)
def factory_catalogue(viewer: ViewerDep) -> FactoryCatalogueOut:
    del viewer
    return FactoryCatalogueOut(
        classes=[
            CatalogueClassOut(
                capability_class=cls,
                slots=[
                    CatalogueSlotOut(name=sl.name, question=sl.question, kind=sl.kind)
                    for sl in slots
                ],
            )
            for cls, slots in CATALOGUE.items()
        ],
        sizes=list(SIZE_TIER_NAMES),
        kinds=list(KINDS),
        levels=list(LEVELS),
    )


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
    row = get_repo_or_404(db, repo)
    out = _backlog_out(_home(settings, repo), _delivery_preflight(db, settings, row))
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
    row = get_repo_or_404(db, repo)
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
    out = _backlog_out(home, _delivery_preflight(db, settings, row))
    assert out is not None and out.hash == backlog.backlog_hash
    return out


@router.get(
    "/factory/{repo}/tasks",
    response_model=list[FactoryTaskOut],
    responses={401: _ERR, 404: _ERR},
    summary="Every backlog item's latest state — DoR gaps, route, RED proof, build, PR, verdict — from the evidence",
)
def list_tasks(
    repo: str, viewer: ViewerDep, db: DbDep, factory: SessionFactoryDep, settings: SettingsDep
) -> list[FactoryTaskOut]:
    del viewer
    get_repo_or_404(db, repo)
    views = _home(settings, repo).task_views()
    routes = _cell_routes(db, factory, repo) if views else {}
    # F15 — the run that produced the newest build, from the ledger row the build event
    # names (the chain carries the row, the row carries the run)
    row_ids = [v.row_id for v in views if v.row_id]
    run_by_row: dict[str, str] = {}
    if row_ids:
        for row_id, run_id in db.execute(
            select(Grade.row_id, Grade.run_id).where(Grade.row_id.in_(row_ids))
        ).all():
            run_by_row[str(row_id)] = str(run_id or "")
    out: list[FactoryTaskOut] = []
    for v in views:
        d = v.to_dict()
        d.pop("row_id")
        out.append(
            FactoryTaskOut(
                **d,
                run_id=run_by_row.get(v.row_id, ""),
                cell_route=routes.get(f"{v.capability_class}|{v.size}", CellRouteOut()),
            )
        )
    return out


def _cell_routes(db: DbDep, factory: SessionFactoryDep, repo: str) -> dict[str, CellRouteOut]:
    """``class|size`` → the map's decision, from exactly the reading the worker's delivery
    gate uses (:meth:`crb.server.worker.Worker._route_lookup`): sighted rows on the current
    apparatus, the repo's latest controls verdict, sign-offs overlaid."""
    rows = rows_for_apparatus(
        rows_for_mode(DbLedger(factory).rows(repo=repo), "sighted"), "current"
    )
    cmap, _ = signed_map(
        rows, PROJECTION_CLASS_SIZE, db, repo, controls=latest_controls_verdict(db, repo)
    )
    out: dict[str, CellRouteOut] = {}
    for c in cmap.cells:
        if c.decision is None:
            continue
        d = c.decision
        st = c.stats
        out[f"{c.key.capability_class}|{c.key.size}"] = CellRouteOut(
            route=d.route,
            reason_code=d.reason_code,
            reason=d.reason,
            n=st.n if st is not None else 0,
            point=st.point if st is not None else 0.0,
            ci_low=st.ci.low if st is not None else 0.0,
            ci_high=st.ci.high if st is not None else 0.0,
            apparatus_versions=list(st.apparatus_versions) if st is not None else [],
            deliverable=d.route == ROUTE_DELIVER,
        )
    return out


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
        # verify the chain we already materialised — one read of evidence.jsonl, not two
        verify_events(events)
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
