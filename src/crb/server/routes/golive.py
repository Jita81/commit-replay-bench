"""``/golive`` and ``/settings/attestations/{line}`` — the go-live checklist, proven or attested.

``GET /golive`` (any signed-in role) serves every line of docs/DEPLOYMENT.md §8 with its
state now: ``proven`` (a check the product ran for this request), ``attested`` (an admin
recorded the act: who, when it was done, when it was recorded, what was done) or
``unproven`` (with the reason). ``PUT /settings/attestations/{line}`` (admin) records an
attestation for a line only the operator can prove, and ``DELETE`` withdraws it; each is one
``golive.*`` event on the ``golive`` system trace, written in the request's transaction.

Navigation
----------
What it is:   The go-live route module: the reading and the attestation record.
What it does: Reads ``/health`` (the same deep probe, with this request's id), the ledger
              verification and whether an organisation sign-in is configured, folds them
              with the accounts, qualifications and attestations into the reading; records
              and withdraws an attestation — refusing an unknown line (404
              ``unknown_line``), a line the product proves (409 ``proven_by_product``), an
              empty statement or an act dated in the future (422 ``invalid_attestation``)
              and a withdrawal with nothing in force (409 ``not_attested``).
How:          ``read_golive`` → ``collect_health`` + ``verify_ledger`` + ``oidc_client`` →
              :func:`crb.server.golive.evaluate` (local admins named to an admin only), and
              keeps the reading's counts on the app; ``golive_counts`` serves ``/flow`` from
              a reading at most a minute old; the writes call ``golive.attest`` /
              ``golive.withdraw`` and commit, then serve the fresh reading.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0045-go-live-lines-are-proven-or-attested.md
Works with:   src/crb/server/golive.py (every rule lives there), src/crb/server/routes/system.py
              (``collect_health``), src/crb/server/routes/ledger.py (``verify_ledger``),
              src/crb/server/routes/flow.py (counts the lines for the platform stream),
              ui/src/api/hooks.ts (``useGoLive``, ``useAttest``, ``useWithdrawAttestation``),
              docs/API.md#admin (the contract these routes serve)
Tested by:    tests/test_server_routes_golive.py
Touch when:   never for a new repository; a new go-live line is added in
              src/crb/server/golive.py, not here.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from crb.server import golive
from crb.server.auth import AdminDep, ViewerDep
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    Principal,
    SessionFactoryDep,
    SettingsDep,
    request_id,
)
from crb.server.routes.ledger import verify_ledger
from crb.server.routes.system import UI_DIST_UNKNOWN, collect_health
from crb.server.settings import ROLE_RANK, Settings

router = APIRouter(tags=["golive"])
_ERR = {"model": ErrorEnvelope}


class AttestationOut(BaseModel):
    """Who recorded the act, the day it was performed, when it was recorded, what was done."""

    model_config = ConfigDict(extra="forbid")

    by: str
    actor: str
    performed_on: str
    recorded_at: str
    statement: str


class GoLiveLineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    proves: Literal["product", "operator"]
    source: str
    doc: str
    state: Literal["proven", "attested", "unproven"]
    detail: str
    attestation: AttestationOut | None


class GoLiveCountsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: int
    proven: int
    attested: int
    unproven: int


class GoLiveOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[GoLiveLineOut]
    counts: GoLiveCountsOut
    checked_at: str


class AttestIn(BaseModel):
    """An operator act, recorded: what was done and the day it was done."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=golive.STATEMENT_MAX)
    performed_on: _dt.date


#: How long a reading serves ``/flow``'s counts before it is taken again (seconds).
FLOW_READING_TTL_S = 60.0


def read_golive(
    request: Request,
    session: Session,
    factory: sessionmaker[Session],
    settings: Settings,
    *,
    names: bool = False,
) -> golive.GoLiveReading:
    """The reading now, from the same probes ``/health`` and ``/ledger/verify`` serve.
    ``names`` lets an admin read local admins' login names. Every reading taken here is
    kept on the app for :func:`golive_counts`."""
    state = request.app.state
    mounted = state.ui_dist if getattr(state, "ui_mounted", False) else UI_DIST_UNKNOWN
    health = collect_health(factory, settings, request_id=request_id(request), ui_dist=mounted)
    try:
        ledger: dict[str, Any] | None = verify_ledger(session).model_dump()
    except Exception:
        ledger = None
    reading = golive.evaluate(
        session,
        settings,
        health=health,
        ledger=ledger,
        oidc_enabled=getattr(state, "oidc_client", None) is not None,
        names=names,
    )
    state.golive_reading = (time.monotonic(), reading.counts())
    return reading


def golive_counts(
    request: Request,
    session: Session,
    factory: sessionmaker[Session],
    settings: Settings,
) -> dict[str, int]:
    """The lines by state for the platform stream's ``/flow`` counts: the reading this
    process took in the last :data:`FLOW_READING_TTL_S` seconds (a ``/golive`` read, an
    attestation or a withdrawal each take one), else a fresh one. ``/flow`` feeds a panel on
    five screens; the deep ``/health`` probes and the ledger's chain walk run at most once a
    minute for it, never once per read."""
    kept = getattr(request.app.state, "golive_reading", None)
    if kept is not None and time.monotonic() - kept[0] < FLOW_READING_TTL_S:
        return dict(kept[1])
    return read_golive(request, session, factory, settings).counts()


def _is_admin(principal: Principal) -> bool:
    return ROLE_RANK.get(principal.role, -1) >= ROLE_RANK["admin"]


def _who(principal: Principal) -> str:
    return principal.display_name or principal.email or principal.id


def _out(reading: golive.GoLiveReading) -> GoLiveOut:
    return GoLiveOut.model_validate(reading.to_dict())


@router.get(
    "/golive",
    response_model=GoLiveOut,
    responses={401: _ERR},
    summary="The go-live checklist: each line proven, attested or unproven, with its source",
)
def get_golive(
    viewer: ViewerDep,
    request: Request,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> GoLiveOut:
    """Every line of DEPLOYMENT §8, its state now and where that state comes from. Only an
    admin reads local admins' login names in the sign-in line; anyone else reads how many."""
    return _out(read_golive(request, db, factory, settings, names=_is_admin(viewer)))


@router.put(
    "/settings/attestations/{line}",
    response_model=GoLiveOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Record that an operator act on the go-live checklist was done (admin)",
)
def put_attestation(
    line: str,
    body: AttestIn,
    *,
    admin: AdminDep,
    request: Request,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> GoLiveOut:
    """One ``golive.attested`` event naming the admin, the day and what was done."""
    try:
        golive.attest(
            db,
            line,
            actor=admin.id,
            by=_who(admin),
            statement=body.statement,
            performed_on=body.performed_on,
        )
    except golive.UnknownLine as exc:
        raise ApiError(404, "unknown_line", f"no go-live line {line!r}") from exc
    except golive.ProvenByProduct as exc:
        raise ApiError(
            409,
            "proven_by_product",
            f"{line!r} is a line the product proves by its own check; an attestation cannot "
            "stand in for it",
        ) from exc
    except ValueError as exc:
        raise ApiError(422, "invalid_attestation", str(exc)) from exc
    db.commit()
    return _out(read_golive(request, db, factory, settings, names=True))


@router.delete(
    "/settings/attestations/{line}",
    response_model=GoLiveOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR},
    summary="Withdraw the attestation in force for a go-live line (admin)",
)
def delete_attestation(
    line: str,
    *,
    admin: AdminDep,
    request: Request,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> GoLiveOut:
    """One ``golive.withdrawn`` event; the line reads unproven again."""
    try:
        golive.withdraw(db, line, actor=admin.id, by=_who(admin))
    except golive.UnknownLine as exc:
        raise ApiError(404, "unknown_line", f"no go-live line {line!r}") from exc
    except golive.NotAttested as exc:
        raise ApiError(409, "not_attested", f"{line!r} has no attestation in force") from exc
    db.commit()
    return _out(read_golive(request, db, factory, settings, names=True))


__all__ = ["FLOW_READING_TTL_S", "AttestIn", "GoLiveOut", "golive_counts", "read_golive", "router"]
