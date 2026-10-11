"""A campaign as the store has it: the verified record, its releases, its runs and their spend.

The campaign's trace is its id (``cmp_<24 hex>``): one ``campaign.registered`` event, one
``campaign.released`` per stage released after it, and one ``campaign.admitted`` per run
``POST /runs`` queued under it, in the same transaction as the run. A run's spend is read the
way its own cap reads it (``crb.server.spend_cap.Spend``): the cost of its ledger rows plus
each ``author.attempt`` event on its trace (P-775) — so the campaign and the run never sum one
run two ways. Every reader here takes the caller's session, so ``POST /runs`` reads the tally
and the arm's live run under the events write lock it admits the run under: two submits
cannot both take the last of the line, nor both start one arm.

Navigation
----------
What it is:   The store readers of campaigns: the verified records, the line released, each
              run filed under one with what it has spent, the ids of the runs admitted (a
              campaign-named reading counts only theirs, DL-382), the admitted runs still live
              and the arm each asked for (one live run per arm, F87-2), and the tally and view
              served.
What it does: Keeps a campaign only when its id re-hashes and it sits on its own trace; folds
              its releases into the line (never above the ceiling); reads each admitted run's
              status, rows and author calls into a ``MemberRun``; computes the ``Tally``; serves
              the campaign with its line, spent (author calls apart), held, left and runs; finds
              the admitted runs of a repository still queued or running, and the one live on
              an arm that could attempt a commit of the same reading (``live_on_arm``, keyed
              by ``requested_arm`` and ``runs_overlap``).
How:          ``Event`` rows by action and trace → ``Campaign.from_dict`` → ``verify`` →
              ``rows_of_runs`` and ``author.attempt`` events → ``Spend.of_rows`` /
              ``with_authoring`` per run → ``crb.core.campaign.tally``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md (§3: a run's cap is a guard)
Works with:   src/crb/core/campaign.py (the record, the tally and its refusals),
              src/crb/server/routes/campaigns.py (registers, releases and serves campaigns),
              src/crb/server/routes/runs.py (``POST /runs`` admits a run under the tally and
              while no run on its arm is live), src/crb/server/routes/learn.py
              (``in_flight_runs`` counts the live admitted runs beside the Learn queue's),
              src/crb/store/jobs.py (``ACTIVE_STATUSES``: queued or running),
              src/crb/server/spend_cap.py (``Spend``, ``AUTHOR_ATTEMPT``: a run's own sum),
              src/crb/store/ledger.py (``rows_of_runs``: the rows in the caller's session)
Tested by:    tests/test_server_campaigns.py, tests/test_server_routes_learn.py
Touch when:   never for a new repository; a new kind of spend is recorded outside a run's rows
              and author calls (count it here and in ``Spend``), or a campaign's events change.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.campaign import (
    CAMPAIGN_ADMITTED,
    CAMPAIGN_REGISTERED,
    CAMPAIGN_RELEASED,
    Campaign,
    MemberRun,
    Tally,
    requested_arm,
    runs_overlap,
    tally,
)
from crb.server.spend_cap import AUTHOR_ATTEMPT, Spend
from crb.store.jobs import ACTIVE_STATUSES
from crb.store.ledger import rows_of_runs
from crb.store.models import Event, Run


def load_campaigns(session: Session) -> list[Campaign]:
    """Every verified campaign, in registration order. A record whose id does not re-hash,
    or that sits on another trace than its own id, holds no ceiling and is left out."""
    out: list[Campaign] = []
    for ev in session.execute(
        select(Event).where(Event.action == CAMPAIGN_REGISTERED).order_by(Event.id)
    ).scalars():
        campaign = Campaign.from_dict(dict(ev.payload_json or {}))
        if campaign.verify() and ev.trace_id == campaign.campaign_id:
            out.append(campaign)
    return out


def campaign_of(session: Session, campaign_id: str) -> Campaign | None:
    """The verified campaign with this id, or ``None``."""
    for ev in session.execute(
        select(Event)
        .where(Event.trace_id == campaign_id, Event.action == CAMPAIGN_REGISTERED)
        .order_by(Event.id)
    ).scalars():
        campaign = Campaign.from_dict(dict(ev.payload_json or {}))
        if campaign.verify() and campaign.campaign_id == campaign_id:
            return campaign
    return None


def _events(session: Session, campaign_id: str, action: str) -> list[Event]:
    return list(
        session.execute(
            select(Event)
            .where(Event.trace_id == campaign_id, Event.action == action)
            .order_by(Event.id)
        ).scalars()
    )


def releases(session: Session, campaign: Campaign) -> list[dict[str, Any]]:
    """The stages released after registration, in order (each a ``campaign.released``)."""
    return [
        dict(ev.payload_json or {})
        for ev in _events(session, campaign.campaign_id, CAMPAIGN_RELEASED)
    ]


def line_gbp(session: Session, campaign: Campaign) -> float:
    """The pounds released so far (``Campaign.line_gbp`` over the releases)."""
    return campaign.line_gbp(
        float(r.get("released_gbp") or 0.0) for r in releases(session, campaign)
    )


def admitted_runs(session: Session, campaign_id: str) -> frozenset[str]:
    """The ids of the runs admitted under the campaign — one per ``campaign.admitted`` event on
    its trace. A reading that names the campaign counts only these runs' rows (DL-382)."""
    return frozenset(
        rid
        for ev in _events(session, campaign_id, CAMPAIGN_ADMITTED)
        if (rid := str((ev.payload_json or {}).get("run_id") or ""))
    )


def live_runs(session: Session, *, repo: str, campaign_id: str = "") -> list[Run]:
    """The runs on ``repo`` admitted under ``campaign_id`` (under any campaign when it is
    ``""``) that are still queued or running, in the order they were admitted: what
    ``POST /runs`` keeps one of per arm (F87-2), and what the remeasure plan counts as in
    flight beside the runs the Learn queue filed (``in_flight_runs``)."""
    query = select(Event).where(Event.action == CAMPAIGN_ADMITTED)
    if campaign_id:
        query = query.where(Event.trace_id == campaign_id)
    ids = list(
        dict.fromkeys(
            rid
            for ev in session.execute(query.order_by(Event.id)).scalars()
            if (rid := str((ev.payload_json or {}).get("run_id") or ""))
        )
    )
    if not ids:
        return []
    live = {
        r.id: r
        for r in session.execute(
            select(Run).where(
                Run.id.in_(ids), Run.repo == repo, Run.status.in_(sorted(ACTIVE_STATUSES))
            )
        ).scalars()
    }
    return [live[rid] for rid in ids if rid in live]


def run_arm(run: Run) -> str:
    """The arm a run asked for (``requested_arm`` over its kind, mode and params): the key of
    the run being admitted and of each live one alike, so the two are read one way."""
    params = dict(run.params_json or {})
    return requested_arm(
        kind=run.kind,
        mode=run.mode,
        s1=params.get("arm") == "S1",
        learning=params.get("learning"),
    )


def run_reading(run: Run) -> str:
    """The reading a run is filed under (``params.reading_id``), or ``""``."""
    return str(dict(run.params_json or {}).get("reading_id") or "")


def live_on_arm(
    session: Session, campaign_id: str, *, repo: str, arm: str, reading_id: str = ""
) -> Run | None:
    """The first run of the campaign on ``repo`` and ``arm`` still queued or running that
    could attempt a commit a run filed under ``reading_id`` would (``runs_overlap``: the same
    reading, or either names none), or ``None``: while it is live no such run on that arm is
    admitted (F87-2)."""
    return next(
        (
            r
            for r in live_runs(session, repo=repo, campaign_id=campaign_id)
            if run_arm(r) == arm and runs_overlap(reading_id, run_reading(r))
        ),
        None,
    )


def members(session: Session, campaign_id: str) -> list[MemberRun]:
    """Each run admitted under the campaign, with what it has spent now: its rows and its
    test author's calls, as its own cap counts them (``Spend``)."""
    admitted = [
        dict(ev.payload_json or {}) for ev in _events(session, campaign_id, CAMPAIGN_ADMITTED)
    ]
    ids = [str(a.get("run_id", "")) for a in admitted if a.get("run_id")]
    if not ids:
        return []
    status = {r.id: r.status for r in session.execute(select(Run).where(Run.id.in_(ids))).scalars()}
    rows = defaultdict(list)
    for row in rows_of_runs(session, ids):
        rows[row.run_id].append(row)
    calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in session.execute(
        select(Event)
        .where(Event.trace_id.in_(ids), Event.action == AUTHOR_ATTEMPT)
        .order_by(Event.id)
    ).scalars():
        payload = dict(ev.payload_json or {})
        cost = ev.cost_usd if ev.cost_usd is not None else payload.get("cost_usd")
        calls[ev.trace_id].append({**payload, "action": ev.action, "cost_usd": cost})
    out: list[MemberRun] = []
    for a in admitted:
        rid = str(a.get("run_id", ""))
        if not rid:
            continue
        own = Spend.of_rows(rows[rid])
        total = own.with_authoring(calls[rid])
        out.append(
            MemberRun(
                run_id=rid,
                status=status.get(rid, ""),
                cap_usd=float(a.get("cap_usd") or 0.0),
                s1=bool(a.get("s1")),
                commits=int(a.get("commits") or 0),
                headroom_usd=float(a.get("headroom_usd") or 0.0),
                commits_done=len({r.task_id for r in rows[rid]}),
                rows_usd=own.spent,
                dearest_row_usd=own.dearest,
                rows_unknown=own.unknown,
                authoring_usd=total.spent - own.spent,
                dearest_author_usd=total.dearest_authoring,
                authors_unknown=total.unknown - own.unknown,
            )
        )
    return out


def campaign_tally(session: Session, campaign: Campaign) -> Tally:
    """The campaign's tally now: the line released, over every run admitted under it."""
    return tally(campaign.usd(line_gbp(session, campaign)), members(session, campaign.campaign_id))


def campaign_view(session: Session, campaign: Campaign) -> dict[str, Any]:
    """The campaign as ``GET /campaigns/{id}`` serves it: the record, the line in pounds and
    dollars, the tally, whether it is stopped and why, and each run with its spend."""
    runs = members(session, campaign.campaign_id)
    released = line_gbp(session, campaign)
    t = tally(campaign.usd(released), runs)
    stop = (
        t.refusal(cap_usd=0.0, s1=False, commits=0) if (t.unknown_runs or t.overrun_runs) else None
    )
    return {
        **campaign.to_dict(),
        "ceiling_usd": campaign.usd(campaign.ceiling_gbp),
        "line_gbp": released,
        **t.to_dict(),
        "stopped": None
        if stop is None
        else {"code": stop.code, "message": str(stop), **stop.detail},
        "releases": releases(session, campaign),
        "runs": [
            {
                "run_id": m.run_id,
                "status": m.status,
                "cap_usd": m.cap_usd,
                "s1": m.s1,
                "commits": m.commits,
                "commits_done": m.commits_done,
                "spent_usd": round(m.spent_usd, 6),
                "rows_usd": round(m.rows_usd, 6),
                "authoring_usd": round(m.authoring_usd, 6),
                "cost_unknown": m.unknown,
                "admitted_headroom_usd": round(m.headroom_usd, 6),
                "headroom_usd": round(
                    max(m.headroom_usd, t.headroom(s1=m.s1, commits_left=m.commits_left)), 6
                )
                if m.active
                else 0.0,
            }
            for m in runs
        ],
    }


__all__ = [
    "admitted_runs",
    "campaign_of",
    "campaign_tally",
    "campaign_view",
    "line_gbp",
    "live_on_arm",
    "live_runs",
    "load_campaigns",
    "members",
    "releases",
    "run_arm",
    "run_reading",
]
