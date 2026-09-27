"""Gathering the flow reading — every value stream's own lead time, spend and counts.

The stores already hold the moments: a repository's ``repo.created`` event, a run's
``created`` and its graded rows, a ``controls.report`` event, a sign-off's ``created`` and the
row its approver attested, the factory chain's ``intake.registered`` / ``backlog.frozen`` /
``delivery.opened`` / ``delivery.merged``, a ``user.password_set`` event and the account's next
sign-in. Nothing here writes anything: this module reads those records, hands the pairs to
:mod:`crb.core.flow`, and returns one :class:`~crb.core.flow.FlowReading`.

**The milestone pairs, per stream** (each is the pair its MEASURE criterion names in
``docs/dod/streams/``):

| stream | from → to |
|---|---|
| connect-and-prove | repository registered → its first controls report that passed |
| measure | run queued → its last row graded; a cell's first row → its tenth |
| decide-and-license | a cell first routed ``deliver`` in the sign-off's own scope (recorded, |
| | ADR-0028 §6) → the cell signed; |
| | the attested row graded clean (accepted) → the cell signed; and the |
| | minutes each review took, as the reviewer stated them on ``POST /reviews`` |
| manufacture-and-deliver | item registered → pull request opened → merged |
| learn | a refusal raised → the strengthening item that supersedes it registered |
| run-the-platform | an admin set an account's password → that account signed in again; |
| | the install → the first green ``/health`` (both recorded, ADR-0028) |

**Money is counted once.** Every graded row belongs to exactly one stream's spend
(:func:`partition_rows`: a factory-built row is manufacture's, a row of a £0 proving run is
connect's, every other row is measure's); the reading also serves the repository's cumulative
spend, which the parts add up to. The sums use the product's one spend rule
(``crb.core.flow.spend_of_rows``), which the value scorecard also uses. A cost per unit is the
price of the rows that bought the unit (a cell's first ten rows; the factory's rows per merged
pull request) and is withheld with the reason while any of them is unpriced, never divided
over a floor (DL-066).

**Who reads what.** Every figure is a viewer's except the platform stream's account counts
and its recovery lead time, which are an admin's (ADR-0028 §7): anyone else reads the lead time
as unmeasured with :data:`ADMIN_ONLY` and no account count.

**What it refuses to invent.** Three figures those criteria ask for are not recorded anywhere,
so they are served as :class:`~crb.core.flow.NotCaptured` — named, with why and with the gap
that would close them — and never derived from a neighbouring number: the developer hours of
the guide's "real work" (G-556), how many go-live lines are proven (G-584) and the guard's
false-positive rate (G-536). A screen prints the absence; nobody can mistake it for a zero.
Three moments that were missing are now recorded when they happen (ADR-0028,
:mod:`crb.server.flow_record`) and read back here: a cell first routing ``deliver``, the
install and the first green ``/health``. A moment that passed before recording began is
counted and never dated.

Navigation
----------
What it is:   The server-side gatherer behind ``GET /flow``: one function per stream that finds
              its milestone pairs in the stores, plus ``build_flow`` which assembles them.
What it does: Reads runs, graded rows, system events, sign-offs, reviews, users and the
              factory's evidence chain for one repository; reduces them through
              ``crb.core.flow`` into a lead time, a spend (an unknown cost never counted as
              zero), a cost per unit (never over a floor) and counts per stream; pairs a
              deliver stamp only with a signature of its own scope; serves the account
              figures to an admin only; and names the figures the product does not capture.
How:          SQLAlchemy selects over ``Run`` / ``Event`` / ``Signoff`` / ``Review`` / ``User``
              / ``Task``, the repository's ``GradeRow`` list as the caller loaded it, and
              ``FactoryHome.events()``; each stream's pairs go to ``lead_time`` and its rows to
              ``spend_of``. Pure after the reads — every rule is testable on its own.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/flow.py (the arithmetic and the shapes this module fills),
              src/crb/server/routes/flow.py (the endpoint that calls ``build_flow``),
              src/crb/server/factory_state.py (``FactoryHome.events`` — the manufacture chain),
              src/crb/factory/evidence.py (the event kinds the manufacture and learn folds
              match on), src/crb/server/routes/oracle.py (``CONTROLS_ACTION`` — the controls
              report this module looks for the FIRST passing one of),
              src/crb/store/models.py (``Run``, ``Event``, ``Signoff``, ``Review``, ``User``)
Tested by:    tests/test_server_routes_flow.py, tests/test_flow.py,
              tests/test_flow_known_answers.py (every served figure against a known answer)
Touch when:   a stream's milestone pair changes (change it here, in the stream's MEASURE
              criterion and in tests/test_flow_known_answers.py's ``KNOWN`` together); a
              figure named in ``NOT_CAPTURED`` becomes recorded (remove it here, close its
              gap, and flip the criterion in the same commit).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crb.core.capability import WILDCARD
from crb.core.evidence import utc_now_iso
from crb.core.flow import (
    STREAM_NAMES,
    FlowReading,
    NotCaptured,
    Spend,
    StreamFlow,
    lead_time,
    parse_ts,
    per_unit,
    per_unit_withheld,
    spend_of_rows,
    stated_durations,
)
from crb.core.ledger import PROCESS_FACTORY, GradeRow
from crb.core.routing import DEFAULT_POLICY, ControlsVerdict
from crb.core.signoff import SignoffRecord
from crb.core.version import APPARATUS_VERSION
from crb.factory.evidence import (
    EV_BACKLOG_EVOLVED,
    EV_BACKLOG_FROZEN,
    EV_DELIVERY,
    EV_DELIVERY_CLOSED,
    EV_DELIVERY_MERGED,
    EV_DELIVERY_REFUSED,
    EV_DELIVERY_UPDATED,
    EV_INTAKE_REGISTERED,
    EV_RED_REFUSED,
    FactoryEvent,
)
from crb.server.flow_record import (
    MOMENT_OBSERVED,
    DeliverStamp,
    deliver_moments,
    deliver_stamps,
    inherited_cells,
    install_moments,
)
from crb.store.models import Event, Repo, Review, Run, Task, User

#: The run kinds whose rows belong to "prove the instrument" — the stages the guide prices
#: at £0 (docs/ONBOARDING-A-REPO.md steps 1–3). A row of one of these is the connect stream's
#: spend; every row of the repository is the measure stream's.
PROVE_KINDS: frozenset[str] = frozenset({"setup", "probe", "mine", "label", "oracle", "controls"})
#: The run kinds the measure stream buys attempts with.
MEASURE_KINDS: frozenset[str] = frozenset({"replay", "blind"})
#: The event a repository's registration writes (src/crb/server/routes/repos.py).
REPO_CREATED = "repo.created"
#: The event a negative-controls run writes (src/crb/server/routes/oracle.py).
CONTROLS_REPORT = "controls.report"
#: The event an admin's password reset writes (src/crb/server/routes/admin.py).
RESET_ACTION = "user.password_set"
#: How many rows a cell needs before the map will route on it (docs/adr/0003-one-routing-rule.md).
CELL_N_BAR = 10
#: The method every figure in a reading carries, so no number reads as a live measurement of
#: something it is not: this is a fold over records already written.
METHOD = "derived from the stored runs, graded rows, events, sign-offs and factory chain"


def repo_registered(session: Session, repo: str) -> str:
    """The registration moment: the ``repo.created`` event, else the repository row's own
    ``created`` stamp (a repository connected before the event existed, or whose event was
    pruned). Never guessed — an unknown repository answers an empty stamp, and the lead time
    then reads unmeasured rather than dating the repository from now."""
    ev = session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == REPO_CREATED)
        .order_by(Event.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    if ev is not None:
        return ev.timestamp
    row = session.get(Repo, repo)
    return row.created if row is not None else ""


def first_controls_pass(session: Session, repo: str) -> str:
    """The timestamp of the FIRST controls report that passed the routing gate, or ``""``.

    "Passed" is the same word the map routes under — :meth:`ControlsVerdict.state` against
    ``DEFAULT_POLICY`` — so a report with an escape or too few constructible controls does not
    count here either. Source order matches ``latest_controls_verdict``, read oldest first:
    the ``controls.report`` events, then the finished ``controls`` runs' counts.
    """
    events = session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == CONTROLS_REPORT)
        .order_by(Event.id.asc())
    ).scalars()
    for ev in events:
        if _passed(ControlsVerdict.from_counts(dict(ev.payload_json or {}))):
            return ev.timestamp
    runs = session.execute(
        select(Run).where(Run.repo == repo, Run.kind == "controls").order_by(Run.created.asc())
    ).scalars()
    for run in runs:
        counts = dict(run.counts_json or {})
        if "passed" in counts and _passed(ControlsVerdict.from_counts(counts)):
            return run.finished or run.created
    return ""


def _passed(verdict: ControlsVerdict) -> bool:
    return (
        verdict.state(
            min_share=DEFAULT_POLICY.min_controls_share,
            max_escapes=DEFAULT_POLICY.max_controls_escapes,
        )
        == "passed"
    )


def _costs(rows: Iterable[GradeRow]) -> Spend:
    """The spend of ``rows`` by THE spend rule (:func:`crb.core.flow.spend_of_rows`), which
    honours :attr:`GradeRow.cost_known` — the same rule ``GET /value`` sums with."""
    return spend_of_rows(rows)


#: The partition keys: which stream's spend a graded row belongs to (exactly one).
PART_CONNECT = "connect-and-prove"
PART_MEASURE = "measure"
PART_MANUFACTURE = "manufacture-and-deliver"


def partition_rows(
    rows: Sequence[GradeRow], run_kinds: dict[str, str]
) -> dict[str, list[GradeRow]]:
    """Every graded row in exactly ONE stream's spend, so no row is counted twice.

    A row the factory built (``process_step == factory``) is the manufacture stream's; a row
    written by a run of one of :data:`PROVE_KINDS` is the connect stream's (none writes a
    graded row today, and the stream says so); every other row — a replay or blind attempt,
    including a historical or imported row whose run the runs table never had — is the
    measure stream's. The parts add up to the repository's cumulative spend."""
    parts: dict[str, list[GradeRow]] = {PART_CONNECT: [], PART_MEASURE: [], PART_MANUFACTURE: []}
    for r in rows:
        if r.process_step == PROCESS_FACTORY:
            parts[PART_MANUFACTURE].append(r)
        elif run_kinds.get(r.run_id, "") in PROVE_KINDS:
            parts[PART_CONNECT].append(r)
        else:
            parts[PART_MEASURE].append(r)
    return parts


# ---------------------------------------------------------------------------
# One fold per stream
# ---------------------------------------------------------------------------


def connect_and_prove(session: Session, repo: str, rows: Sequence[GradeRow]) -> StreamFlow:
    """Registration → a passed controls report, and what proving the instrument cost."""
    registered = repo_registered(session, repo)
    passed_at = first_controls_pass(session, repo)
    pairs = [(registered, passed_at)] if registered and passed_at else []
    reason = (
        "no controls report has passed for this repository yet, so there is nothing to measure"
        if not passed_at
        else "the registration moment is not on record for this repository"
    )
    mined = int(
        session.execute(
            select(func.count()).select_from(Task).where(Task.repo == repo)
        ).scalar_one()
    )
    gold = int(
        session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.repo == repo, Task.gold_clean.is_(True))
        ).scalar_one()
    )
    return StreamFlow(
        stream="connect-and-prove",
        name=STREAM_NAMES["connect-and-prove"],
        lead_times=(
            lead_time(
                "registered_to_controls",
                "Registered → controls passed",
                pairs,
                reason=reason,
            ),
        ),
        spend=_costs(rows),
        spend_label=(
            "the £0 stages: setup, probe, mine, label, oracle and controls write no graded "
            "row, so nothing is spent here"
        ),
        counts={
            "tasks_mined": mined,
            "tasks_gold_clean": gold,
            "controls_passed": 1 if passed_at else 0,
        },
        not_captured=(NOT_CAPTURED["developer_hours"],),
    )


def measure(
    rows: Sequence[GradeRow],
    run_kinds: dict[str, str],
    run_created: dict[str, str],
    *,
    repository: Spend | None = None,
) -> StreamFlow:
    """Run queued → last row graded, a cell's first row → its tenth, what measuring spent (the
    replay and blind rows — the stream's own part of the repository's spend) and what one
    routable cell has cost — the price of each at-the-bar cell's FIRST TEN rows, divided by
    the cells at the bar (never the stream's whole spend, which also pays for cells that never
    reach the bar and for rows after the tenth). While any of those ten rows carried no price
    the figure is withheld with the reason, never divided over a floor.

    A cell here is what the map keys a cell by before it routes: class and size WITHIN one
    apparatus version, one mode and one checks arm. Rows of two apparatus versions, of
    sighted and blind, or of two arms are never pooled into one cell's ten (the map would not
    pool them either, ADR-0003 and ADR-0024). ``repository`` is the cumulative spend of every
    graded row of the repository (the criterion's "cumulative spend per repository"); it is
    served on the reading, and named here in a count so the two are never confused."""
    by_run: dict[str, list[GradeRow]] = {}
    for r in rows:
        if run_kinds.get(r.run_id, "") in MEASURE_KINDS:
            by_run.setdefault(r.run_id, []).append(r)
    run_pairs = [
        (run_created.get(run_id, ""), max(r.created for r in rs))
        for run_id, rs in by_run.items()
        if rs
    ]
    by_cell: dict[tuple[str, str, str, str, str], list[GradeRow]] = {}
    for r in rows:
        key = (r.apparatus_version, r.mode, r.checks_arm, r.capability_class, r.size)
        by_cell.setdefault(key, []).append(r)
    bar_pairs: list[tuple[str, str]] = []
    to_bar: list[GradeRow] = []
    for cell_rows in by_cell.values():
        # a cell's rows in the order they were graded; its first ten are what reaching the
        # bar took — in time (first → tenth stamp) and in money (those ten rows' prices)
        ordered = sorted(cell_rows, key=lambda r: r.created)
        if len(ordered) >= CELL_N_BAR:
            first_ten = ordered[:CELL_N_BAR]
            bar_pairs.append((first_ten[0].created, first_ten[-1].created))
            to_bar.extend(first_ten)
    spend = _costs(rows)
    bar_spend = _costs(to_bar)
    counts = {
        "graded_rows": len(rows),
        "runs_graded": len(by_run),
        "cells_at_bar": len(bar_pairs),
    }
    if repository is not None:
        counts["repository_rows_priced"] = repository.rows_priced
        counts["repository_rows_unpriced"] = repository.rows_unpriced
    return StreamFlow(
        stream="measure",
        name=STREAM_NAMES["measure"],
        lead_times=(
            lead_time(
                "queued_to_graded",
                "Run queued → its last row graded",
                run_pairs,
                reason="no replay or blind run of this repository has graded a row yet",
            ),
            lead_time(
                "first_row_to_bar",
                f"A cell's first row → its {CELL_N_BAR}th",
                bar_pairs,
                reason=(
                    f"no class and size has reached {CELL_N_BAR} graded rows yet within one "
                    "apparatus version, mode and checks arm"
                ),
            ),
        ),
        spend=spend,
        spend_label="the replay and blind attempts graded for this repository",
        per_unit=per_unit(bar_spend, len(bar_pairs)),
        per_unit_label=f"per cell that reached {CELL_N_BAR} rows, over its first {CELL_N_BAR} rows",
        per_unit_spend=bar_spend,
        per_unit_units=len(bar_pairs),
        per_unit_reason=per_unit_withheld(
            bar_spend, len(bar_pairs), unit=f"cell that reached {CELL_N_BAR} rows"
        ),
        counts=counts,
    )


def decide_and_license(
    session: Session, repo: str, records: Sequence[SignoffRecord], rows: Sequence[GradeRow]
) -> StreamFlow:
    """The attested row graded clean → the cell signed. The row is the one the approver said
    they read (``attestation.reviewed_row_hash``), so the duration is that decision's own, not
    an average over rows nobody named."""
    graded_at = {r.row_hash: r.created for r in rows}
    pairs: list[tuple[str, str]] = []
    unattested = 0
    for rec in records:
        if rec.revoked:
            continue
        att = rec.attestation
        if att is None or att.reviewed_row_hash not in graded_at:
            unattested += 1
            continue
        pairs.append((graded_at[att.reviewed_row_hash], rec.verified_at))
    minutes = [
        m
        for (m,) in session.execute(
            select(Review.minutes).where(Review.repo == repo).order_by(Review.seq.asc())
        )
    ]
    stated = [int(m) for m in minutes if m is not None]
    moments = deliver_moments(session, repo)
    stamps = deliver_stamps(session, repo)
    routed_pairs: list[tuple[str, str]] = []
    for rec in records:
        if rec.revoked:
            continue
        # the latest first-deliver stamp of THIS cell, in THIS record's own scope, at or
        # before the signature: the transition this signature answered (a wildcard size
        # matches every size). A stamp of another apparatus, posture or checks arm is a cell
        # this sign-off can never lift (apply_signoffs), so it never dates the decision.
        starts = [
            st.timestamp
            for st in stamps
            if answers(rec, st) and _before(st.timestamp, rec.verified_at)
        ]
        if starts:
            routed_pairs.append((max(starts, key=_instant), rec.verified_at))
    return StreamFlow(
        stream="decide-and-license",
        name=STREAM_NAMES["decide-and-license"],
        lead_times=(
            lead_time(
                "accepted_to_signed",
                "Attested row accepted → cell signed",
                pairs,
                reason="no sign-off of this repository names a row this ledger holds",
            ),
            lead_time(
                "routed_deliver_to_signed",
                "Cell first routed deliver → cell signed",
                routed_pairs,
                reason=(
                    "no signed cell of this repository first routed deliver while the product "
                    "was recording it"
                ),
            ),
            stated_durations(
                "review_minutes",
                "Reviewer time per review, as the reviewer stated it",
                [m * 60.0 for m in stated],
                reason="no review of this repository has stated its minutes yet",
            ),
        ),
        spend=Spend(),
        spend_label=(
            "no model spend: deciding is human time, shown above as the minutes reviewers stated"
        ),
        counts={
            "signoffs": sum(1 for r in records if not r.revoked),
            "revocations": sum(1 for r in records if r.revoked),
            "signoffs_without_an_attested_row": unattested,
            "human_reviews": len(minutes),
            "reviews_with_minutes": len(stated),
            "review_minutes_total": sum(stated),
            "cells_routed_deliver": len(moments),
            "cells_at_deliver_before_recording": inherited_cells(session, repo),
        },
    )


def answers(rec: SignoffRecord, stamp: DeliverStamp) -> bool:
    """Could ``rec`` be the signature that answered ``stamp``? Only for the same cell (a
    wildcard size matches every size) in the record's own scope: an apparatus the record was
    stamped at, the record's posture class and its checks arm — the three things a sign-off
    must cover to lift a cell (``SignoffRecord.covers_apparatus`` / ``covers_posture`` /
    ``covers_arm``). A stamp or a record that names no scope matches nothing."""
    versions = {v.strip() for v in rec.apparatus_version.split(",") if v.strip()}
    return (
        stamp.capability_class == rec.capability_class
        and rec.size in (stamp.size, WILDCARD)
        and bool(stamp.apparatus)
        and stamp.apparatus in versions
        and bool(stamp.posture_class)
        and stamp.posture_class == rec.posture_class
        and bool(stamp.checks_arm)
        and stamp.checks_arm == rec.arm
    )


def _instant(ts: str) -> float:
    parsed = parse_ts(ts)
    return parsed.timestamp() if parsed is not None else float("-inf")


def _before(ts: str, end: str) -> bool:
    """``ts`` at or before ``end`` as instants (two stamps of different precision or offset
    compare correctly); an unreadable stamp is never before anything."""
    a, b = parse_ts(ts), parse_ts(end)
    return a is not None and b is not None and a <= b


def manufacture_and_deliver(events: Sequence[FactoryEvent], rows: Sequence[GradeRow]) -> StreamFlow:
    """Item registered → pull request opened → merged, and the cost of a certified change."""
    registered: dict[str, str] = {}
    opened: dict[str, str] = {}
    merged: dict[str, str] = {}
    closed = 0
    refused = 0
    for ev in events:
        if ev.kind == EV_BACKLOG_FROZEN:
            for item_id in ev.payload.get("item_ids", ()) or ():
                registered.setdefault(str(item_id), ev.created)
        elif ev.kind in (EV_BACKLOG_EVOLVED, EV_INTAKE_REGISTERED) and ev.item_id:
            registered.setdefault(ev.item_id, ev.created)
        elif ev.kind in (EV_DELIVERY, EV_DELIVERY_UPDATED) and ev.item_id:
            opened.setdefault(ev.item_id, ev.created)
        elif ev.kind == EV_DELIVERY_MERGED and ev.item_id:
            # GitHub's own merge stamp when the sync read one; else when we recorded it
            merged.setdefault(ev.item_id, str(ev.payload.get("merged_at") or "") or ev.created)
        elif ev.kind == EV_DELIVERY_CLOSED:
            closed += 1
        elif ev.kind == EV_DELIVERY_REFUSED:
            refused += 1
    to_pr = [(registered[i], opened[i]) for i in opened if i in registered]
    to_merge = [(opened[i], merged[i]) for i in merged if i in opened]
    end_to_end = [(registered[i], merged[i]) for i in merged if i in registered]
    spend = _costs(rows)
    return StreamFlow(
        stream="manufacture-and-deliver",
        name=STREAM_NAMES["manufacture-and-deliver"],
        lead_times=(
            lead_time(
                "registered_to_pr",
                "Item registered → pull request opened",
                to_pr,
                reason="no item of this repository has reached a pull request yet",
            ),
            lead_time(
                "pr_to_merged",
                "Pull request opened → merged",
                to_merge,
                reason="no pull request of this repository has been read back as merged yet",
            ),
            lead_time(
                "registered_to_merged",
                "Item registered → merged",
                end_to_end,
                reason="no item of this repository has been merged yet",
            ),
        ),
        spend=spend,
        spend_label="the graded rows the factory built for this repository",
        per_unit=per_unit(spend, len(merged)),
        per_unit_label="per merged pull request",
        per_unit_spend=spend,
        per_unit_units=len(merged),
        per_unit_reason=per_unit_withheld(spend, len(merged), unit="merged pull request"),
        counts={
            "items_registered": len(registered),
            "pull_requests_opened": len(opened),
            "merged": len(merged),
            "closed_unmerged": closed,
            "deliveries_refused": refused,
        },
    )


def learn(events: Sequence[FactoryEvent]) -> StreamFlow:
    """A refusal raised → the strengthening item that supersedes it registered."""
    refused_at: dict[str, str] = {}
    strengthened: list[tuple[str, str]] = []
    evolutions = 0
    for ev in events:
        if ev.kind in (EV_RED_REFUSED, EV_DELIVERY_REFUSED) and ev.item_id:
            refused_at.setdefault(ev.item_id, ev.created)
        elif ev.kind == EV_BACKLOG_EVOLVED:
            evolutions += 1
            supersedes = str(ev.payload.get("supersedes") or "")
            if supersedes in refused_at:
                strengthened.append((refused_at[supersedes], ev.created))
    return StreamFlow(
        stream="learn",
        name=STREAM_NAMES["learn"],
        lead_times=(
            lead_time(
                "refusal_to_strengthening",
                "Refusal raised → strengthening item registered",
                strengthened,
                reason="no refusal of this repository has been answered by an evolution yet",
            ),
        ),
        spend=Spend(),
        spend_label="no model spend: learning reads what other streams already paid for",
        counts={
            "refusals": len(refused_at),
            "evolutions": evolutions,
            "refusals_answered": len(strengthened),
        },
        not_captured=(NOT_CAPTURED["guard_false_positives"],),
    )


#: Why a caller below admin reads no account figure: the deployment's accounts are the
#: admin's to see (``GET /admin/users`` refuses anyone else), and a recovery lead time of n = 1
#: is one person's recovery, timed.
ADMIN_ONLY = (
    "shown to an admin only: the deployment's accounts, and how long a person's account "
    "recovery took, are the admin's to see"
)


def run_the_platform(session: Session, *, admin: bool = False) -> StreamFlow:
    """An admin set an account's password → that account signed in again.

    This is the deployment's figure, not the repository's: the accounts are the deployment's.
    A recovery counts only when someone else set the password (an admin recovering a person,
    not a person changing their own) and the account has signed in since. The account counts
    and the recovery lead time are served only to an admin (``admin``); anyone else reads the
    lead time as unmeasured with :data:`ADMIN_ONLY` and no account count at all — the same
    line ``GET /admin/users`` draws.
    """
    users = list(session.execute(select(User)).scalars())
    last_login = {u.id: u.last_login for u in users}
    installed_at, moment, healthy_at = install_moments(session)
    observed = bool(installed_at) and moment == MOMENT_OBSERVED
    install_reason = (
        "the install passed before this product recorded it (an existing deployment "
        "upgraded), so it is not dated"
        if installed_at and not observed
        else "no install moment is on record for this deployment"
        if not installed_at
        else "this deployment has not yet read green on /health"
    )
    resets = session.execute(
        select(Event).where(Event.action == RESET_ACTION).order_by(Event.id.asc())
    ).scalars()
    pairs: list[tuple[str, str]] = []
    recovered = 0
    for ev in resets:
        target = str((ev.payload_json or {}).get("target") or "")
        if not target or target == ev.actor:
            continue
        recovered += 1
        back = last_login.get(target, "")
        set_at, back_at = parse_ts(ev.timestamp), parse_ts(back)
        if set_at is not None and back_at is not None and back_at >= set_at:
            pairs.append((ev.timestamp, back))
    accounts = {
        "accounts": len(users),
        "accounts_active": sum(1 for u in users if u.active),
        "admins_active": sum(1 for u in users if u.active and u.role == "admin"),
        "recoveries_started": recovered,
    }
    return StreamFlow(
        stream="run-the-platform",
        name=STREAM_NAMES["run-the-platform"],
        lead_times=(
            lead_time(
                "password_set_to_signed_in",
                "Password reset by an admin → the person signed in again",
                pairs if admin else [],
                reason=(
                    "no account on this deployment has been recovered by an admin yet"
                    if admin
                    else ADMIN_ONLY
                ),
            ),
            lead_time(
                "installed_to_healthy",
                "Installed → first green /health",
                [(installed_at, healthy_at)] if observed and healthy_at else [],
                reason=install_reason,
            ),
        ),
        spend=Spend(),
        spend_label="no model spend: running the platform buys no attempts",
        counts={
            **(accounts if admin else {}),
            "install_recorded": 1 if observed else 0,
        },
        not_captured=(NOT_CAPTURED["go_live_lines"],),
    )


#: The figures a stream's MEASURE criterion asks for that nothing records. Each is served with
#: the gap that would close it, so the screen states an absence instead of deriving a number.
NOT_CAPTURED: dict[str, NotCaptured] = {
    "developer_hours": NotCaptured(
        figure="the developer hours of the guide's “real work”",
        why=(
            "making a repository's oracle reproducible is work a person does outside this "
            "product, and nothing here times it"
        ),
        gap="G-556",
    ),
    "go_live_lines": NotCaptured(
        figure="how many go-live lines are proven",
        why="nothing reads the go-live checklist against this deployment's own probes",
        gap="G-584",
    ),
    "guard_false_positives": NotCaptured(
        figure="the guard's false-positive rate and how often a defect class comes back",
        why="a refusal is recorded, and whether it was right is not",
        gap="G-536",
    ),
}


def build_flow(
    session: Session,
    *,
    repo: str,
    rows: Sequence[GradeRow],
    signoffs: Sequence[SignoffRecord],
    factory_events: Sequence[FactoryEvent],
    apparatus: str = APPARATUS_VERSION,
    admin: bool = False,
) -> FlowReading:
    """Every stream's numbers for ``repo``, folded from what the stores already hold;
    ``admin`` says whether the caller may read the deployment's account figures."""
    runs = list(session.execute(select(Run).where(Run.repo == repo)).scalars())
    run_kinds = {r.id: r.kind for r in runs}
    run_created = {r.id: r.created for r in runs}
    parts = partition_rows(rows, run_kinds)
    total = _costs(rows)
    streams = (
        connect_and_prove(session, repo, parts[PART_CONNECT]),
        measure(parts[PART_MEASURE], run_kinds, run_created, repository=total),
        decide_and_license(session, repo, signoffs, rows),
        manufacture_and_deliver(factory_events, parts[PART_MANUFACTURE]),
        learn(factory_events),
        run_the_platform(session, admin=admin),
    )
    return FlowReading(
        repo=repo,
        apparatus=apparatus,
        generated=utc_now_iso(),
        method=METHOD,
        streams=streams,
        spend=total,
    )
