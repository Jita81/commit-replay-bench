"""A campaign as the store has it: the verified record, its releases, its runs and their spend.

The campaign's trace is its id (``cmp_<24 hex>``): one ``campaign.registered`` event, one
``campaign.released`` per stage released after it, and one ``campaign.admitted`` per run
``POST /runs`` queued under it, in the same transaction as the run. A run's spend is read the
way its own cap reads it (``crb.server.spend_cap.Spend``): the cost of its ledger rows plus
each ``author.attempt`` event on its trace (P-775) — so the campaign and the run never sum one
run two ways — plus each of its **unplaced** attempts (F8): an attempt built (its
``build.done``) or reserved (its ``reading.reserved``) with no row of the run for its commit
and trial once the attempt is settled, charged at its ``build.done`` cost, else at its
reservation's hold. One reader (``unplaced_attempts``) feeds both the tally and a reading's
``settled_unrowed`` count, so the two never disagree. Every reader here takes the caller's
session, so ``POST /runs`` reads the tally under the events write lock it admits the run
under, and two submits cannot both take the last of the line.

Navigation
----------
What it is:   The store readers of campaigns: the verified records, the line released, each
              run filed under one with what it has spent, the ids of the runs admitted (a
              campaign-named reading counts only theirs, DL-382), the tally and view served,
              a reserved.v1 reading's reservations with their runs' state (P-792), and the
              attempts that spent with no row to place them against (``UnplacedAttempt``, F8).
What it does: Keeps a campaign only when its id re-hashes and it sits on its own trace; folds
              its releases into the line (never above the ceiling); reads each admitted run's
              status, rows, author calls and unplaced attempts into a ``MemberRun``; computes
              the ``Tally``; serves the campaign with its line, spent (author calls apart,
              and each run's unplaced spend), held, left, its stop and its runs; reads each first
              ``reading.reserved`` as a ``Reservation``, settled once its run is terminal,
              missing or reclaimed past the claim it reserved under; lists each settled
              attempt with no row of its run for its commit and trial, at its ``build.done``
              cost, else its reservation's hold, else unknown — never one still in flight,
              which its run's cap and headroom hold.
How:          ``Event`` rows by action and trace → ``Campaign.from_dict`` → ``verify`` →
              ``rows_of_runs``, ``author.attempt`` events and ``unplaced_attempts`` →
              ``Spend.of_rows`` / ``with_authoring`` per run → ``crb.core.campaign.tally``;
              ``reading.reserved`` events → their runs (one read) → ``Reservation``
              (``reservations_of``); a ``build`` stage ``build.done`` per attempt less the
              rows of its (run, commit, trial), plus each settled reservation with neither →
              ``UnplacedAttempt`` (``unplaced_attempts``).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md (§3: a run's cap is a guard)
Works with:   src/crb/core/campaign.py (the record, the tally and its refusals),
              src/crb/server/routes/campaigns.py (registers, releases and serves campaigns),
              src/crb/server/routes/runs.py (``POST /runs`` admits a run under the tally),
              src/crb/server/spend_cap.py (``Spend``, ``AUTHOR_ATTEMPT``: a run's own sum),
              src/crb/store/ledger.py (``rows_of_runs``: the rows in the caller's session),
              src/crb/server/reading_book.py (``load_readings`` fills a reading's reservations),
              src/crb/core/run.py (writes the ``build.done`` an attempt is read by),
              src/crb/server/routes/readings.py (``served_reading``: ``settled_unrowed``)
Tested by:    tests/test_server_campaigns.py, tests/test_p792_reserved.py
Touch when:   never for a new repository; a new kind of spend is recorded outside a run's rows,
              author calls and attempts (count it here and in ``Spend``), ``build.done`` or a
              reservation changes shape, or a campaign's events change.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
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
    tally,
)
from crb.core.reading import READING_RESERVED_ACTION, RUNG_R1, Reservation
from crb.server.spend_cap import AUTHOR_ATTEMPT, Spend
from crb.store.jobs import ACTIVE_STATUSES, RECLAIMS_KEY
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


def _claim_of(value: Any) -> int:
    """A reservation's ``claim`` as written, or -1 when it is not a whole number — which no
    run's ``reclaims`` count ever equals, so such a reservation reads settled."""
    if isinstance(value, bool):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _usd_of(value: Any) -> float | None:
    """A dollar figure as written (a reservation's ``hold_usd``, an attempt's ``cost_usd``),
    or ``None`` when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def reservations_of(session: Session, reading_ids: Iterable[str]) -> list[Reservation]:
    """The ``reading.reserved`` events of the readings named, the first per ``(reading, arm,
    commit)`` by ``Event.id``, each with whether its run is settled: missing, no longer queued
    or running, or reclaimed past the claim it reserved under (P-792). A settled
    reservation with no row is a miss, never pending, so a run that died after reserving
    costs its commit. One read of the events and one of their runs, whatever the count."""
    ids = sorted({str(r) for r in reading_ids if r})
    if not ids:
        return []
    first: dict[tuple[str, str, str], Event] = {}
    for ev in session.execute(
        select(Event)
        .where(Event.action == READING_RESERVED_ACTION, Event.trace_id.in_(ids))
        .order_by(Event.id)
    ).scalars():
        first.setdefault((ev.trace_id, ev.step_id, ev.task_id), ev)
    payloads = {key: dict(ev.payload_json or {}) for key, ev in first.items()}
    run_ids = sorted({str(p.get("run_id") or "") for p in payloads.values()} - {""})
    runs = (
        {r.id: r for r in session.execute(select(Run).where(Run.id.in_(run_ids))).scalars()}
        if run_ids
        else {}
    )
    out: list[Reservation] = []
    for key, ev in first.items():
        payload = payloads[key]
        run_id = str(payload.get("run_id") or "")
        claim = _claim_of(payload.get("claim"))
        run = runs.get(run_id)
        settled = (
            run is None
            or run.status not in ACTIVE_STATUSES
            or int((run.counts_json or {}).get(RECLAIMS_KEY, 0) or 0) > claim
        )
        out.append(
            Reservation(
                arm=ev.step_id,
                task_id=ev.task_id,
                run_id=run_id,
                event_id=ev.event_id,
                event_seq_id=int(ev.id),
                claim=claim,
                treatment=str(payload.get("treatment") or ""),
                hold_usd=_usd_of(payload.get("hold_usd")),
                settled=settled,
            )
        )
    return out


#: The ``build.done`` an attempt is read by: core/run.py's, after the builder and before
#: ``grade()``, routed to the ``build`` stage with the commit as its ``task_id``. A builder's
#: own (``builder.build.done``) and the factory's (stage ``factory``, keyed by its item, whose
#: row names the oracle's commit) are not attempts here.
_BUILD_DONE = "build.done"
_BUILD_STAGE = "build"


@dataclass(frozen=True)
class UnplacedAttempt:
    """One attempt of a campaign's run that spent with no row of its run to place it against
    (F8): built (a ``build.done``) or reserved (a ``reading.reserved``) for ``task_id`` at
    ``trial``, with no row of ``run_id`` for that commit and trial, and settled — its run has
    ended, or its reservation's claim is below the run's ``reclaims``. ``cost_usd`` is the
    ``build.done`` cost when it is known, else the reservation's hold, else ``None`` (a cost
    the tally cannot know). ``rung`` is the ``build.done``'s rung (empty for a reservation
    never built); ``reservation_event_id`` and ``reading_id`` name the reservation, when the
    attempt was reserved."""

    run_id: str
    task_id: str
    trial: str
    rung: str
    cost_usd: float | None
    reservation_event_id: str = ""
    reading_id: str = ""


def _attempt_cost(ev: Event) -> float | None:
    """A ``build.done``'s cost: the event's cost column, else its payload's ``cost_usd`` —
    ``None`` when the payload says ``cost_known`` false or no number is there."""
    payload = dict(ev.payload_json or {})
    if payload.get("cost_known") is False:
        return None
    return _usd_of(ev.cost_usd if ev.cost_usd is not None else payload.get("cost_usd"))


def unplaced_attempts(session: Session, run_ids: Iterable[str]) -> list[UnplacedAttempt]:
    """The runs' attempts that spent with no row to place them against, settled (F8).

    Per (run, commit, trial), each ``build.done`` beyond the rows the run wrote there is one
    attempt — the earliest first, since a re-run after a reclaim builds the commit again and
    writes its row last. It is counted once settled: its run is no longer queued or running
    (or is missing), or, at ``r1`` under a reservation, the run was reclaimed past the claim
    that reserved it. Then each settled reservation of these runs with neither a
    ``build.done`` nor a row at ``r1`` — killed between its reservation and its build's end —
    is one more, at its hold. An attempt still in flight is not here: its run's cap and
    headroom hold it, so it is never both held and charged. One read each of the runs, their
    ``build.done`` events, their rows and their readings' reservations."""
    ids = sorted({str(r) for r in run_ids if r})
    if not ids:
        return []
    runs = {r.id: r for r in session.execute(select(Run).where(Run.id.in_(ids))).scalars()}
    built: dict[tuple[str, str, str], list[Event]] = defaultdict(list)
    for ev in session.execute(
        select(Event)
        .where(
            Event.trace_id.in_(ids),
            Event.action == _BUILD_DONE,
            Event.stage == _BUILD_STAGE,
            Event.task_id != "",
        )
        .order_by(Event.id)
    ).scalars():
        trial = str(dict(ev.payload_json or {}).get("trial") or "")
        built[(ev.trace_id, ev.task_id, trial)].append(ev)
    rowed: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows_of_runs(session, ids):
        rowed[(row.run_id, row.task_id, row.trial)] += 1
    reading_of = {
        rid: str((run.params_json or {}).get("reading_id") or "") for rid, run in runs.items()
    }
    reserved = {
        (res.run_id, res.task_id): res
        for res in reservations_of(session, reading_of.values())
        if res.run_id in runs
    }

    def ended(run_id: str) -> bool:
        run = runs.get(run_id)
        return run is None or run.status not in ACTIVE_STATUSES

    out: list[UnplacedAttempt] = []
    for (run_id, task_id, trial), events in built.items():
        res = reserved.get((run_id, task_id)) if trial == RUNG_R1 else None
        extra = len(events) - rowed[(run_id, task_id, trial)]
        if extra <= 0 or not (ended(run_id) or (res is not None and res.settled)):
            continue
        for ev in events[:extra]:
            payload = dict(ev.payload_json or {})
            out.append(
                UnplacedAttempt(
                    run_id=run_id,
                    task_id=task_id,
                    trial=trial,
                    rung=str(payload.get("rung") or ""),
                    cost_usd=_attempt_cost(ev),
                    reservation_event_id=res.event_id if res is not None else "",
                    reading_id=reading_of.get(run_id, "") if res is not None else "",
                )
            )
    for (run_id, task_id), res in reserved.items():
        if (
            res.settled
            and (run_id, task_id, RUNG_R1) not in built
            and not rowed[(run_id, task_id, RUNG_R1)]
        ):
            out.append(
                UnplacedAttempt(
                    run_id=run_id,
                    task_id=task_id,
                    trial=RUNG_R1,
                    rung="",
                    cost_usd=res.hold_usd,
                    reservation_event_id=res.event_id,
                    reading_id=reading_of.get(run_id, ""),
                )
            )
    return out


def members(session: Session, campaign_id: str) -> list[MemberRun]:
    """Each run admitted under the campaign, with what it has spent now: its rows and its
    test author's calls, as its own cap counts them (``Spend``), and its unplaced attempts
    (``unplaced_attempts``: their known costs, how many, how many with a cost not known)."""
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
    unplaced: dict[str, list[UnplacedAttempt]] = defaultdict(list)
    for attempt in unplaced_attempts(session, ids):
        unplaced[attempt.run_id].append(attempt)
    out: list[MemberRun] = []
    for a in admitted:
        rid = str(a.get("run_id", ""))
        if not rid:
            continue
        own = Spend.of_rows(rows[rid])
        total = own.with_authoring(calls[rid])
        lost = unplaced[rid]
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
                unrowed_usd=sum(a.cost_usd for a in lost if a.cost_usd is not None),
                unrowed=len(lost),
                unrowed_unknown=sum(1 for a in lost if a.cost_usd is None),
            )
        )
    return out


def campaign_tally(session: Session, campaign: Campaign) -> Tally:
    """The campaign's tally now: the line released, over every run admitted under it."""
    return tally(campaign.usd(line_gbp(session, campaign)), members(session, campaign.campaign_id))


def campaign_view(session: Session, campaign: Campaign) -> dict[str, Any]:
    """The campaign as ``GET /campaigns/{id}`` serves it: the record, the line in pounds and
    dollars, the tally, whether it is stopped and why (``Tally.refusal``'s order: a cost not
    known, an overrun, unplaced spend), and each run with its spend."""
    runs = members(session, campaign.campaign_id)
    released = line_gbp(session, campaign)
    t = tally(campaign.usd(released), runs)
    stop = t.refusal(cap_usd=0.0, s1=False, commits=0) if t.stopped else None
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
                "unrowed_usd": round(m.unrowed_usd, 6),
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
    "UnplacedAttempt",
    "admitted_runs",
    "campaign_of",
    "campaign_tally",
    "campaign_view",
    "line_gbp",
    "load_campaigns",
    "members",
    "releases",
    "reservations_of",
    "unplaced_attempts",
]
