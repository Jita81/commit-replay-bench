"""``/campaigns`` — register a campaign's money ceiling, release its stages, read its tally.

G-957 (Q-06: each campaign is approved with a stated maximum): the product holds a campaign's
ceiling instead of the operator's hand. ``POST /campaigns`` (operator; CSRF-bound like every
cookie-authenticated write) registers one — its name, its ceiling in pounds, the pounds
released now, the USD-per-GBP rate the pounds convert at (stored as given, never fetched) and
the decision that approved it — as a ``campaign.registered`` event on the campaign's own trace
(its id, ``cmp_<24 hex>``, the record's hash). ``POST /campaigns/{id}/release`` raises the line
to a later stage, never above the ceiling and never down. A run is filed under a campaign by
``POST /runs`` with ``campaign_id`` (src/crb/server/routes/runs.py, ``admit_under_campaign``),
which reads the tally under the events write lock and refuses 409 ``campaign_ceiling`` before
anything is queued. ``GET /campaigns`` and ``GET /campaigns/{id}`` serve each campaign's line,
spent (its runs' rows and test-author calls), held, left, whether it is stopped, and its runs.

Navigation
----------
What it is:   The campaigns route module: registration, stage release and the served tally.
What it does: Registers a campaign (a name registered already is refused 409
              ``campaign_exists``); releases a stage (409 ``campaign_release_invalid`` for one
              that does not raise the line or passes the ceiling; 404 ``campaign_unknown``);
              lists campaigns and serves one with its tally and runs (viewer).
How:          ``append_event_checked`` (lock → the name or the line read under it → insert) →
              ``crb.server.campaigns`` (``load_campaigns``, ``campaign_of``, ``campaign_view``).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md (§3: a run's cap is a guard)
Works with:   src/crb/core/campaign.py (the record, the tally and its refusal codes),
              src/crb/server/campaigns.py (the store readers and the served view),
              src/crb/server/routes/runs.py (``POST /runs`` with ``campaign_id`` admits a run),
              src/crb/store/events.py (``append_event_checked``: the locked event write),
              docs/API.md#campaigns-a-campaigns-money-ceiling (the routes documented)
Tested by:    tests/test_server_campaigns.py
Touch when:   never for a new repository; a campaign's record or its release rule changes (a
              decision first, then crb.core.campaign and docs/API.md).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy.orm import Session

from crb.core.campaign import (
    CAMPAIGN_REGISTERED,
    CAMPAIGN_RELEASED,
    REFUSAL_EXISTS,
    REFUSAL_RELEASE,
    REFUSAL_UNKNOWN,
    Campaign,
)
from crb.core.evidence import utc_now_iso
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.campaigns import campaign_of, campaign_view, line_gbp, load_campaigns
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.store.events import append_event_checked

router = APIRouter(tags=["campaigns"])
_ERR = {"model": ErrorEnvelope}

#: Stripped and never blank: a campaign is registered with its name and its decision.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Decision = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
#: Pounds: above nothing, at most a million.
Pounds = Annotated[float, Field(gt=0, le=1_000_000)]


class CampaignIn(BaseModel):
    """A campaign as the operator approved it (Q-06): the ceiling, the pounds released now
    (the first stage; all of it for a campaign of one stage), the rate and the decision."""

    name: Name
    ceiling_gbp: Pounds
    released_gbp: Pounds
    #: US dollars per pound, as the decision states it (e.g. 1.35); stored, never fetched.
    rate_usd_per_gbp: float = Field(gt=0, le=100)
    #: The decision that approved the ceiling (a DECISION-LOG entry, a review's Q-number).
    decision: Decision

    @model_validator(mode="after")
    def _released_within_ceiling(self) -> CampaignIn:
        if self.released_gbp > self.ceiling_gbp:
            raise ValueError("released_gbp may not pass ceiling_gbp")
        return self


class ReleaseIn(BaseModel):
    """A later stage: the pounds released in all, after this release."""

    released_gbp: Pounds
    decision: Decision


@router.post(
    "/campaigns",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Register a campaign's money ceiling in pounds, its first stage and its rate (operator)",
)
def register_campaign(
    body: CampaignIn, operator: OperatorDep, factory: SessionFactoryDep
) -> dict[str, Any]:
    campaign = Campaign(
        name=body.name,
        ceiling_gbp=float(body.ceiling_gbp),
        released_gbp=float(body.released_gbp),
        rate_usd_per_gbp=float(body.rate_usd_per_gbp),
        decision=body.decision,
        actor=operator.id,
        registered_at=utc_now_iso(),
    )

    def build(s: Session) -> dict[str, Any]:
        if any(c.name == campaign.name for c in load_campaigns(s)):
            raise ApiError(
                409,
                REFUSAL_EXISTS,
                f"a campaign named {campaign.name!r} is registered already",
                detail={"name": campaign.name},
            )
        return campaign.to_dict()

    append_event_checked(
        factory,
        trace_id=campaign.campaign_id,
        stage="system",
        action=CAMPAIGN_REGISTERED,
        build=build,
        actor=operator.id,
    )
    with factory() as s:
        return campaign_view(s, campaign)


@router.post(
    "/campaigns/{campaign_id}/release",
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Release a campaign's next stage: raise its line, never above the ceiling (operator)",
)
def release_campaign(
    campaign_id: str, body: ReleaseIn, operator: OperatorDep, factory: SessionFactoryDep
) -> dict[str, Any]:
    def build(s: Session) -> dict[str, Any]:
        campaign = campaign_of(s, campaign_id)
        if campaign is None:
            raise ApiError(404, REFUSAL_UNKNOWN, f"no verified campaign {campaign_id!r}")
        previous = line_gbp(s, campaign)
        wanted = float(body.released_gbp)
        if wanted <= previous or wanted > campaign.ceiling_gbp:
            raise ApiError(
                409,
                REFUSAL_RELEASE,
                f"a release raises the line above £{previous:,.2f} and stays within the "
                f"£{campaign.ceiling_gbp:,.2f} ceiling; £{wanted:,.2f} does not",
                detail={
                    "campaign_id": campaign_id,
                    "line_gbp": previous,
                    "ceiling_gbp": campaign.ceiling_gbp,
                    "released_gbp": wanted,
                },
            )
        return {
            "campaign_id": campaign_id,
            "released_gbp": wanted,
            "previous_gbp": previous,
            "line_usd": campaign.usd(wanted),
            "rate_usd_per_gbp": campaign.rate_usd_per_gbp,
            "decision": body.decision,
            "actor": operator.id,
            "released_at": utc_now_iso(),
        }

    append_event_checked(
        factory,
        trace_id=campaign_id,
        stage="system",
        action=CAMPAIGN_RELEASED,
        build=build,
        actor=operator.id,
    )
    with factory() as s:
        campaign = campaign_of(s, campaign_id)
        assert campaign is not None  # registered: the release above read it under the lock
        return campaign_view(s, campaign)


@router.get(
    "/campaigns",
    responses={401: _ERR},
    summary="Every verified campaign with its line, spent, held and left (viewer)",
)
def list_campaigns(viewer: ViewerDep, db: DbDep) -> dict[str, Any]:
    del viewer
    return {"items": [campaign_view(db, c) for c in load_campaigns(db)]}


@router.get(
    "/campaigns/{campaign_id}",
    responses={401: _ERR, 404: _ERR},
    summary="One campaign's tally: line, spent (author calls apart), held, left, its runs (viewer)",
)
def get_campaign(campaign_id: str, viewer: ViewerDep, db: DbDep) -> dict[str, Any]:
    del viewer
    campaign = campaign_of(db, campaign_id)
    if campaign is None:
        raise ApiError(404, REFUSAL_UNKNOWN, f"no verified campaign {campaign_id!r}")
    return campaign_view(db, campaign)


__all__ = ["CampaignIn", "ReleaseIn", "router"]
