"""``/learn/register`` and the operator acts on the prevention loop (ADR-0020).

The register is computed on read from the ledger, the review store, the factory's outcome
events and the loop's own chain, and served to any viewer. Every write here is ONE record on
the repository's prevention chain (``learn.prevention.recorded``), made by an operator whose
signed-in session is the decider — never a field of the body — and every write that changes
something a builder sees, or undoes it, needs a reason:

* ``PUT /learn/switch`` — ``learning.auto_apply`` = ``off`` | ``context`` | ``config``;
* ``POST /learn/tick`` — run the loop now (the worker runs it after every build run);
* ``POST /learn/changes/{change_id}/revert`` — a person's revert: a veto the loop never
  re-applies;
* ``POST /learn/items/{item_id}/register`` — a filed item onto the repository's factory
  backlog in one act (freeze the first, evolve the rest; 409 while a factory run holds it;
  an item for this product's own code never goes on a customer's backlog — 422);
* ``POST /learn/links`` — a person's link from classes to a fix made outside the loop; its
  exposure starts at the link.

Navigation
----------
What it is:   The prevention loop's route module: the register (viewer) and the five operator
              acts on the loop's chain.
What it does: Serves ``GET /learn/register`` (the register, with every decision re-derived
              from the ledger); writes a switch, a tick, a revert, an item registration or a
              link as one chained record each, attributed to the signed-in operator and
              carrying a reason where one is required; registers an item through the factory's
              own register-or-evolve path. Refuses a grader key (the core's allowlist), an
              unknown class, a change not in force, a product-scoped item on a customer's
              backlog and a backlog a run holds.
How:          ``get_repo_or_404`` → ``EventsPreventionStore`` (read + verify) →
              ``register_for`` → the record → ``_append`` (append + commit, one retry on a
              concurrent append) → the response names what was written.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md,
              docs/adr/0017-the-ticket-is-the-backlog-item.md (the register-or-evolve path)
Works with:   src/crb/server/prevention_state.py (the store, the register and the tick),
              src/crb/core/prevention.py (records, the rule, ``link_record``),
              src/crb/server/factory_state.py (``FactoryHome.register_backlog`` /
              ``register_evolution``), src/crb/server/routes/factory.py
              (``_refuse_if_run_active``, ``_next_item_id``), src/crb/server/routes/repos.py
              (``get_repo_or_404``), ui/src/screens/Learn/LearnPage.tsx (the register card)
Tested by:    tests/test_server_routes_prevention.py
Touch when:   never for a new repository; a new operator act on the loop needs a record kind in
              src/crb/core/prevention.py, a route here, a row in docs/API.md and a control on
              the Learn page's register card.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Literal

from fastapi import APIRouter, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crb.core.evidence import utc_now_iso
from crb.core.ledger import LedgerIntegrityError
from crb.core.prevention import (
    PreventionRecord,
    changes,
    link_record,
    proposals,
    switch_state,
    verify_decisions,
)
from crb.core.spec import UNCLASSIFIED
from crb.factory.backlog import KIND_INFRA, KIND_OPERATOR, Backlog, BacklogError, BacklogItem
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.prevention_state import (
    ConcurrentAppend,
    EventsPreventionStore,
    learning_tick,
    register_for,
)
from crb.server.routes.factory import _next_item_id, _refuse_if_run_active
from crb.server.routes.repos import get_repo_or_404

router = APIRouter(tags=["learn"])
_ERR = {"model": ErrorEnvelope}

_SIG_PATTERN = r"^[a-z_]+:[a-z0-9 _.+*/@:-]{1,90}$"


class SwitchIn(BaseModel):
    """One throw of the repository's switch. There is deliberately no ``decided_by``: the
    signed-in operator is the decider."""

    model_config = ConfigDict(extra="forbid")

    auto_apply: Literal["off", "context", "config"]
    reason: str = Field(min_length=1, max_length=500)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class LinkIn(BaseModel):
    """A person's link from classes to a fix made outside the loop (a merged pull request, a
    docs/PREVENTION.md row). Its exposure starts at the link, never before."""

    model_config = ConfigDict(extra="forbid")

    signatures: list[str] = Field(min_length=1, max_length=20)
    ref: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=500)


def _store(db: Session, repo: str) -> EventsPreventionStore:
    return EventsPreventionStore(db, repo)


def _chain(db: Session, repo: str) -> list[PreventionRecord]:
    """The repository's prevention chain, verified — a broken chain is a 409 that says so,
    never a register served as if nothing were wrong."""
    try:
        return _store(db, repo).records()
    except LedgerIntegrityError as exc:
        raise ApiError(
            409,
            "prevention_chain_broken",
            f"the prevention chain of {repo!r} does not verify: {exc} — nothing is served or "
            "written until an operator restores it from the database backup",
        ) from exc


#: How many times a route chains a record before a concurrent writer is reported.
APPEND_ATTEMPTS = 3


def _append(
    db: Session, repo: str, record: PreventionRecord, *, detail: dict[str, Any] | None = None
) -> PreventionRecord:
    """Chain, add and commit one record; on a concurrent append on the trace (a collision on
    ``uq_events_trace_seq`` or a head that moved under the read), roll back and re-chain.
    Every attempt is inside the handler: when the last one collides too, the session is
    rolled back and the caller gets 409 ``prevention_concurrent_append`` (with ``detail``,
    e.g. what was already written elsewhere), never a 500 over a failed session."""
    last: Exception | None = None
    for _ in range(APPEND_ATTEMPTS):
        try:
            rec = _store(db, repo).append(record)
            db.commit()
            return rec
        except (IntegrityError, ConcurrentAppend) as exc:
            db.rollback()
            last = exc
    raise ApiError(
        409,
        "prevention_concurrent_append",
        f"the prevention chain of {repo!r} kept moving while a {record.kind!r} record was "
        f"chained ({APPEND_ATTEMPTS} attempts); nothing was recorded — retry the act",
        detail={"kind": record.kind, **(detail or {})},
    ) from last


def _record(
    kind: str, repo: str, payload: dict[str, Any], *, who: str, reason: str
) -> PreventionRecord:
    return PreventionRecord(
        kind, repo, payload, actor=who, on_behalf_of=who, reason=reason, created=utc_now_iso()
    )


@router.get(
    "/learn/register",
    responses={401: _ERR, 404: _ERR},
    summary="The prevention register: every bug class of a repository, its lever, before → after and status",
)
def learn_register(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    reg = register_for(
        db, factory, settings.home, repo, records=_chain(db, repo), settings=settings
    )
    out = reg.to_dict()
    out["decisions_verified"] = verify_decisions(reg.records, reg.index.rows, sigs=reg.index.of)
    return out


@router.put(
    "/learn/switch",
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Throw the repository's learning switch (off | context | config); a reason is required",
)
def learn_switch(
    body: SwitchIn,
    operator: OperatorDep,
    db: DbDep,
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    get_repo_or_404(db, repo)
    _chain(db, repo)  # nothing is written onto a chain that does not verify
    rec = _append(
        db,
        repo,
        _record(
            "switched", repo, {"auto_apply": body.auto_apply}, who=operator.id, reason=body.reason
        ),
    )
    st = switch_state(_store(db, repo).records())
    return {"repo": repo, "switch": st.to_dict(), "record": rec.to_dict()}


@router.post(
    "/learn/tick",
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="Run the repository's prevention loop now (the worker runs it after every build run)",
)
def learn_tick(
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    get_repo_or_404(db, repo)
    appended = learning_tick(factory, settings.home, repo, settings=settings)
    return {
        "repo": repo,
        "requested_by": operator.id,
        "appended": [r.to_dict() for r in appended],
    }


@router.post(
    "/learn/changes/{change_id}/revert",
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Revert one change the loop applied; the loop never re-applies it to that class",
)
def learn_revert(
    body: ReasonIn,
    operator: OperatorDep,
    db: DbDep,
    change_id: str = Path(min_length=1, max_length=64),
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    get_repo_or_404(db, repo)
    ch = changes(_chain(db, repo)).get(change_id)
    if ch is None or ch.state != "in_force":
        raise ApiError(
            404,
            "not_found",
            f"no change {change_id!r} in force on {repo!r} — read GET /learn/register",
        )
    rec = _append(
        db,
        repo,
        _record(
            "reverted",
            repo,
            {"change_id": change_id, "by": "person", "veto": True},
            who=operator.id,
            reason=body.reason,
        ),
    )
    return {
        "repo": repo,
        "change_id": change_id,
        "lever_id": ch.lever_id,
        "targets": list(ch.targets),
        "record": rec.to_dict(),
    }


def _latest_in_lineage(backlog: Backlog, item_id: str) -> str:
    """The id at the end of ``item_id``'s supersession chain (an evolution must supersede
    the latest item, never one already superseded)."""
    superseded_by = backlog.superseded_by()
    seen: set[str] = set()
    current = item_id
    while current in superseded_by and current not in seen:
        seen.add(current)
        current = superseded_by[current]
    return current


@router.post(
    "/learn/items/{item_id}/register",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register one filed prevention item onto the repository's factory backlog (freeze or evolve)",
)
def learn_register_item(
    operator: OperatorDep,
    db: DbDep,
    settings: SettingsDep,
    item_id: str = Path(min_length=1, max_length=64),
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    get_repo_or_404(db, repo)
    chain = _chain(db, repo)
    prop = proposals(chain).get(item_id)
    if prop is None:
        raise ApiError(404, "not_found", f"no filed prevention item {item_id!r} on {repo!r}")
    if prop.scope == "product":
        raise ApiError(
            422,
            "product_item",
            f"{item_id!r} is a change to this product's own code, never an item on {repo!r}'s "
            "backlog: it is served for the maintainers — link the issue that carries it with "
            "POST /learn/links",
            detail={"lever_id": prop.lever_id},
        )
    _refuse_if_run_active(db, repo)
    evidence = ", ".join(prop.evidence_refs[:5])
    item = BacklogItem(
        id=item_id,
        title=prop.title[:200],
        kind=KIND_INFRA if prop.kind == "infra" else KIND_OPERATOR,
        description=(
            f"{prop.description}\n\nExpected effect: {prop.expected_effect}\nEvidence rows "
            f"({prop.evidence_total}): {evidence}"
        )[:4000],
        acceptance_criteria=(
            f"{', '.join(prop.targets)} stops recurring: the prevention rule keeps and closes "
            "it on the first attempts after the change",
        ),
        capability_class=UNCLASSIFIED,
        labels={
            "prevention_item": item_id,
            "signature": ",".join(prop.targets),
            "lever": prop.lever_id,
            "level": prop.level,
        },
    )
    home = FactoryHome(settings.home, repo)
    active = home.load_backlog()
    recorded = {
        str(r.payload.get("registered_id", ""))
        for r in chain
        if r.kind == "registered" and r.payload.get("item_id") == item_id
    }
    orphan = _unrecorded_registration(active, item_id, recorded)
    try:
        if orphan is not None and active is not None:
            # an earlier call wrote the backlog and then failed to record it: record THAT
            # registration, never register the same item again as a new version
            reg = active
            how, registered_id, supersedes = "recovered", orphan.id, orphan.supersedes
        elif active is None:
            reg = home.register_backlog([item], actor=operator.id)
            how, registered_id, supersedes = "frozen", item.id, ""
        else:
            registered_id, supersedes = item.id, ""
            if active.get(item.id) is not None:
                registered_id = _next_item_id(item.id, [i.id for i in active.all_items()])
                supersedes = _latest_in_lineage(active, item.id)
            reg = home.register_evolution(
                replace(item, id=registered_id, supersedes=supersedes), actor=operator.id
            )
            how = "evolved"
    except (BacklogError, ValueError, LookupError) as exc:
        raise ApiError(409, "register_refused", f"{item_id!r} was not registered: {exc}") from exc
    rec = _append(
        db,
        repo,
        _record(
            "registered",
            repo,
            {
                "item_id": item_id,
                "registered_id": registered_id,
                "supersedes": supersedes,
                "how": how,
                "targets": list(prop.targets),
                "backlog_hash": reg.backlog_hash,
                "evolutions_hash": reg.evolutions_hash,
            },
            who=operator.id,
            reason=f"registered {item_id} onto {repo}'s factory backlog ({how})",
        ),
        detail={
            "item_id": item_id,
            "registered_id": registered_id,
            "backlog_hash": reg.backlog_hash,
            "evolutions_hash": reg.evolutions_hash,
            "retry": "registering again records this registration; it does not add another",
        },
    )
    return {
        "repo": repo,
        "item_id": item_id,
        "registered_id": registered_id,
        "supersedes": supersedes,
        "how": how,
        "backlog_hash": reg.backlog_hash,
        "evolutions_hash": reg.evolutions_hash,
        "record": rec.to_dict(),
    }


def _unrecorded_registration(
    backlog: Backlog | None, item_id: str, recorded: set[str]
) -> BacklogItem | None:
    """An item of ``item_id``'s lineage on the active backlog that no ``registered`` record
    names (``recorded``: the ids the chain names): the backlog write of an earlier call
    whose record failed. ``None`` when every one of them is on the record."""
    if backlog is None:
        return None
    mine = [
        i
        for i in backlog.all_items()
        if i.labels.get("prevention_item") == item_id and i.id not in recorded
    ]
    return mine[-1] if mine else None


@router.post(
    "/learn/links",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Link classes to a fix made outside the loop; exposure starts at the link",
)
def learn_link(  # noqa: PLR0917 — FastAPI dependencies + body + query
    body: LinkIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    get_repo_or_404(db, repo)
    bad = [s for s in body.signatures if not re.match(_SIG_PATTERN, s)]
    if bad:
        raise ApiError(422, "validation_error", "not a class signature", detail={"invalid": bad})
    reg = register_for(
        db, factory, settings.home, repo, records=_chain(db, repo), settings=settings
    )
    unknown = [s for s in body.signatures if reg.entry(s) is None]
    if unknown:
        raise ApiError(
            422,
            "unknown_class",
            f"{len(unknown)} class(es) are not in {repo!r}'s register — read GET /learn/register",
            detail={"unknown": unknown},
        )
    rec = link_record(
        reg,
        targets=list(dict.fromkeys(body.signatures)),
        ref=body.ref,
        note=body.note,
        served_commit=str(getattr(settings, "served_commit", "") or ""),
        actor=operator.id,
    )
    rec = _append(db, repo, rec)
    return {"repo": repo, "record": rec.to_dict()}
