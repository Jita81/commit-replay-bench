"""The listener: one watched column becomes backlog items, with every write on the chain.

This is the only place that decides what happens to a ticket. It owns four questions:

**What is configured?** The *connection* (which tracker, which organisation or site,
which project, which column, the credential) is a deployment-wide setting an admin owns
(:class:`crb.server.settings.IntakeSettings` plus the ``tracker_token`` secret). The
*listener* is per repository and **default OFF**: an operator switches it on, and that
switch is recorded on the repository row with who threw it and when
(:class:`ListenerState`).

**Has this been seen?** ``(tracker, key, revision)`` is the idempotency key, and it lives
on the factory's own hash-chained evidence, not in memory. A worker that restarts
mid-poll re-reads the chain, finds the ticket already read at that revision, and writes
nothing. An edit moves the revision, so the same ticket comes back as an *evolution* —
a new item superseding the old one. Nothing is ever overwritten.

**What does the ticket learn?** One marked comment and one label, rendered by
:mod:`crb.intake.feedback` from the readiness gate and the pre-run cell route. Both
writes are idempotent, so a poll that finds nothing changed touches nothing.

**When does money move?** Only when every structural gap is closed *and* the class is
one the product has questions for. Then the draft is registered through the same
``FactoryHome`` path ``POST /factory/{repo}/backlog`` uses. A registration that arrives
while a factory run is active is **queued, not lost**: the ticket keeps ``crb:ready``,
the chain records why, and the next poll registers it.

Every stop — tracker unreachable, credential missing, a write the tracker refused, the
column gone — is an ``intake.stopped`` event carrying one of the published reasons, and
it is what ``/health`` and the intake screen show.

Navigation
----------
What it is:   The intake service: ``build_tracker``, ``ListenerState``, ``IntakeStore``
              (the served state file), ``poll_repository`` (the whole flow) and
              ``apply_outcome_map`` (the merge moves the ticket).
What it does: Turns a watched column into registered backlog items and gap feedback, once
              per ticket revision, recording each step on the factory's evidence chain and
              serving the same rows to the API and the screen.
How:          Plain functions over injected callables (the tracker, the route lookup, the
              clock, "is a run active") so the whole flow is exercised by a fake tracker
              with no HTTP, no database and no model; state the screen reads is one JSON
              file beside the repository's evidence chain.
Layer:        server — docs/ARCHITECTURE.md#43-server
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the six verbs and the stop reasons),
              src/crb/intake/ado.py and src/crb/intake/jira.py (the adapters it builds),
              src/crb/intake/draft.py (ticket → draft item),
              src/crb/intake/feedback.py (the comment and the label),
              src/crb/server/settings.py (``IntakeSettings``),
              src/crb/server/secrets.py (``TRACKER_TOKEN_SECRET``),
              src/crb/server/factory_state.py (``FactoryHome`` — the backlog and the
              chain), src/crb/server/worker.py (calls ``poll_repository`` from the idle
              loop), src/crb/server/routes/factory.py (serves and configures it)
Tested by:    tests/test_intake_service.py, tests/test_server_routes_intake.py
Touch when:   a fifth label or a new stop reason appears (publish it in docs/API.md
              first); never to widen what is written to a ticket without the ADR.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from crb.core.evidence import utc_now_iso
from crb.factory.backlog import BacklogItem
from crb.factory.evidence import (
    EV_INTAKE_DELIVERED,
    EV_INTAKE_FEEDBACK,
    EV_INTAKE_POLLED,
    EV_INTAKE_QUEUED,
    EV_INTAKE_READ,
    EV_INTAKE_REGISTERED,
    EV_INTAKE_STOPPED,
    EV_INTAKE_TRANSITIONED,
    INTAKE_EVENT_KINDS,
)
from crb.factory.readiness import assess
from crb.intake.ado import AdoConfig, AdoTracker
from crb.intake.client import (
    LABEL_QUEUED,
    REASON_NO_SECRET,
    REASON_NOT_CONFIGURED,
    STOP_ADVICE,
    Ticket,
    TicketRef,
    TrackerClient,
    TrackerError,
    marker_for,
)
from crb.intake.draft import Draft, draft_from
from crb.intake.fake import FileTracker, fake_tracker_enabled, fake_tracker_path
from crb.intake.feedback import render_delivered, render_feedback, render_queued, render_refusal
from crb.intake.jira import JiraConfig, JiraTracker
from crb.server.factory_state import FactoryHome

log = logging.getLogger("crb.server.intake")

#: The evidence kinds this service appends to the factory chain. They are DEFINED in
#: :mod:`crb.factory.evidence` (which owns the chain's closed vocabulary) and aliased here
#: so a reader of the listener sees the words it writes. Published in docs/API.md.
EV_POLLED = EV_INTAKE_POLLED
EV_READ = EV_INTAKE_READ
EV_FEEDBACK = EV_INTAKE_FEEDBACK
EV_REGISTERED = EV_INTAKE_REGISTERED
EV_QUEUED = EV_INTAKE_QUEUED
EV_DELIVERED = EV_INTAKE_DELIVERED
EV_TRANSITIONED = EV_INTAKE_TRANSITIONED
EV_STOPPED = EV_INTAKE_STOPPED
INTAKE_EVENTS: tuple[str, ...] = INTAKE_EVENT_KINDS

#: The key in a repository row's ``config_json`` that holds its listener.
CONFIG_KEY = "intake"
#: The file beside the repository's evidence chain that the screen and the API read.
STATE_FILE = "intake-state.json"

#: What the product will do to a ticket when a delivered pull request reaches its fate.
#: Empty by default: a deployment that configures nothing moves no ticket, ever.
OUTCOME_MERGED = "merged"
OUTCOME_CLOSED = "closed"

#: Item outcomes the ticket is told about as a refusal, with the way forward. These are
#: exactly the statuses the API serves a ``way_forward`` for
#: (:func:`crb.server.routes.factory._way_forward`): a stop a revised ticket answers.
STOPPED_STATUSES: frozenset[str] = frozenset(
    {
        "not_ready",
        "not_red",
        "no_oracle",
        "oracle_needs_strengthening",
        "rejected",
        "rework_exhausted",
    }
)


class RunActive(RuntimeError):
    """A registration arrived while a factory run holds the repository's backlog hash."""


@dataclass(frozen=True)
class ListenerState:
    """One repository's listener. Default OFF, and the switch names who threw it."""

    enabled: bool = False
    #: An override for the deployment's watched column, for a repository whose team uses
    #: a different word for the same step. Empty means "the deployment's column".
    column: str = ""
    switched_by: str = ""
    switched_at: str = ""
    #: A watermark the poll may ask from (``entered(column, since)``). It is carried on
    #: the row and preserved across switches, and nothing advances it yet: correctness
    #: does not rest on it — ``(tracker, key, revision)`` on the evidence chain is what
    #: makes a re-read a no-op — so a whole-column read is the safe default, and a
    #: watermark is an optimisation for a board with a long column.
    since: str = ""

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> ListenerState:
        d = dict((config or {}).get(CONFIG_KEY) or {})
        return cls(
            enabled=bool(d.get("enabled", False)),
            column=str(d.get("column", "")),
            switched_by=str(d.get("switched_by", "")),
            switched_at=str(d.get("switched_at", "")),
            since=str(d.get("since", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "column": self.column,
            "switched_by": self.switched_by,
            "switched_at": self.switched_at,
            "since": self.since,
        }


@dataclass(frozen=True)
class IntakeRow:
    """One ticket as the screen and the API show it, exactly as the last poll saw it."""

    key: str
    title: str
    url: str
    revision: str
    label: str
    state: str
    item_id: str
    item_url: str
    feedback: str
    open_questions: tuple[Mapping[str, str], ...] = ()
    capability_class: str = ""
    confidence: float = 0.0
    size: str = ""
    registered: bool = False
    is_evolution: bool = False
    supersedes: str = ""
    cell_route: Mapping[str, Any] | None = None
    read_at: str = ""
    #: Set when this ticket's own step stopped (a write the tracker refused).
    stopped: str = ""
    stopped_advice: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "url": self.url,
            "revision": self.revision,
            "label": self.label,
            "state": self.state,
            "item_id": self.item_id,
            "item_url": self.item_url,
            "feedback": self.feedback,
            "open_questions": [dict(q) for q in self.open_questions],
            "capability_class": self.capability_class,
            "confidence": self.confidence,
            "size": self.size,
            "registered": self.registered,
            "is_evolution": self.is_evolution,
            "supersedes": self.supersedes,
            "cell_route": dict(self.cell_route) if self.cell_route else None,
            "read_at": self.read_at,
            "stopped": self.stopped,
            "stopped_advice": self.stopped_advice,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> IntakeRow:
        return cls(
            key=str(d.get("key", "")),
            title=str(d.get("title", "")),
            url=str(d.get("url", "")),
            revision=str(d.get("revision", "")),
            label=str(d.get("label", "")),
            state=str(d.get("state", "")),
            item_id=str(d.get("item_id", "")),
            item_url=str(d.get("item_url", "")),
            feedback=str(d.get("feedback", "")),
            open_questions=tuple(dict(q) for q in (d.get("open_questions") or [])),
            capability_class=str(d.get("capability_class", "")),
            confidence=float(d.get("confidence") or 0.0),
            size=str(d.get("size", "")),
            registered=bool(d.get("registered", False)),
            is_evolution=bool(d.get("is_evolution", False)),
            supersedes=str(d.get("supersedes", "")),
            cell_route=dict(d["cell_route"]) if d.get("cell_route") else None,
            read_at=str(d.get("read_at", "")),
            stopped=str(d.get("stopped", "")),
            stopped_advice=str(d.get("stopped_advice", "")),
        )


@dataclass
class PollReport:
    """What one poll of one repository did. Every number here is on the chain too."""

    repo: str
    column: str = ""
    seen: int = 0
    read: int = 0
    skipped: int = 0
    commented: int = 0
    registered: int = 0
    queued: int = 0
    rows: list[IntakeRow] = field(default_factory=list)
    stopped: str = ""
    detail: str = ""
    at: str = ""

    @property
    def ok(self) -> bool:
        return not self.stopped

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "column": self.column,
            "seen": self.seen,
            "read": self.read,
            "skipped": self.skipped,
            "commented": self.commented,
            "registered": self.registered,
            "queued": self.queued,
            "stopped": self.stopped,
            "detail": self.detail,
            "advice": STOP_ADVICE.get(self.stopped, "") if self.stopped else "",
            "at": self.at,
        }


class IntakeStore:
    """The one file the screen reads: the last poll's rows and its outcome.

    It is a cache of what the chain already says, written after every poll so a viewer
    never waits on a tracker. The chain stays the record; this file can be deleted and
    the next poll rebuilds it.
    """

    def __init__(self, home: str | Path, repo: str) -> None:
        self.dir = FactoryHome(home, repo).dir
        self.path = self.dir / STATE_FILE

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"rows": [], "last_poll": None}
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("intake state unreadable", extra={"path": str(self.path)})
            return {"rows": [], "last_poll": None}

    def rows(self) -> list[IntakeRow]:
        return [IntakeRow.from_dict(r) for r in self.read().get("rows", [])]

    def last_poll(self) -> dict[str, Any] | None:
        got = self.read().get("last_poll")
        return dict(got) if got else None

    def write(self, report: PollReport) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        body = {"rows": [r.to_dict() for r in report.rows], "last_poll": report.to_dict()}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, sort_keys=True, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)


# ---------------------------------------------------------------------------
# building a tracker from settings + the stored credential
# ---------------------------------------------------------------------------


def build_tracker(
    intake: Any,
    token: str,
    *,
    client: httpx.Client | None = None,
    home: str | Path = "",
) -> TrackerClient:
    """The adapter this deployment is configured for.

    Raises ``TrackerError(REASON_NOT_CONFIGURED)`` when no tracker is set and
    ``TrackerError(REASON_NO_SECRET)`` when one is set but no credential is stored — the
    two stops an operator sees before anything is polled.

    ``fake`` is the walkthrough's file-backed board and needs no credential; it is refused
    unless ``CRB_ENABLE_FAKE_TRACKER=1`` is in the environment, so it cannot be reached by
    a deployment that has not deliberately asked for it.
    """
    kind = str(getattr(intake, "tracker", "none") or "none")
    if kind == "none":
        raise TrackerError(REASON_NOT_CONFIGURED, "no tracker is configured for this deployment")
    if kind == "fake":
        if not fake_tracker_enabled():
            raise TrackerError(
                REASON_NOT_CONFIGURED,
                "the fake tracker is a test fixture and needs CRB_ENABLE_FAKE_TRACKER=1",
            )
        return FileTracker(fake_tracker_path(home or "."))
    if not token:
        raise TrackerError(REASON_NO_SECRET, "no tracker credential is stored")
    if kind == "ado":
        return AdoTracker(
            AdoConfig(
                organisation_url=intake.url,
                project=intake.project,
                column=intake.column,
                area_path=intake.area_path,
            ),
            token,
            client=client,
        )
    if kind == "jira":
        return JiraTracker(
            JiraConfig(
                site_url=intake.url,
                project=intake.project,
                column=intake.column,
                email=intake.email,
                jql=intake.jql,
                points_field=intake.points_field,
                acceptance_field=intake.acceptance_field,
            ),
            token,
            client=client,
        )
    raise TrackerError(REASON_NOT_CONFIGURED, f"unknown tracker {kind!r}")


# ---------------------------------------------------------------------------
# the chain: what has already been read, and what a ticket became
# ---------------------------------------------------------------------------


def _read_events(home: FactoryHome) -> list[Any]:
    return [e for e in home.events() if e.kind in INTAKE_EVENTS]


def already_handled(events: Sequence[Any], tracker: str, key: str, revision: str) -> bool:
    """Has this exact ticket revision already been read AND finished with?

    "Finished with" means the poll either registered it or decided it was not ready.
    A revision read but left waiting for a busy factory run is NOT finished, so the next
    poll picks it up — that is how a queued registration is never lost.
    """
    for e in reversed(list(events)):
        p = e.payload
        if e.kind != EV_READ:
            continue
        if str(p.get("tracker")) != tracker or str(p.get("key")) != key:
            continue
        if str(p.get("revision")) != revision:
            return False
        return not bool(p.get("awaiting_registration", False))
    return False


def item_for_ticket(events: Sequence[Any], tracker: str, key: str) -> str:
    """The id of the item this ticket was last registered as, or ``""``."""
    for e in reversed(list(events)):
        if (
            e.kind == EV_REGISTERED
            and str(e.payload.get("key")) == key
            and str(e.payload.get("tracker")) == tracker
        ):
            return str(e.item_id)
    return ""


# ---------------------------------------------------------------------------
# the poll
# ---------------------------------------------------------------------------


def _register(home: FactoryHome, item: BacklogItem, *, actor: str) -> str:
    """Register through exactly the path the API uses: freeze the first item, evolve the
    rest. Returns the word for what happened (``frozen`` / ``evolved``)."""
    if home.load_backlog() is None:
        home.register_backlog([item], actor=actor)
        return "frozen"
    home.register_evolution(item, actor=actor)
    return "evolved"


def poll_repository(
    repo: str,
    *,
    tracker: TrackerClient,
    listener: ListenerState,
    column: str,
    home: FactoryHome,
    route_for: Callable[[BacklogItem], Mapping[str, Any] | None],
    item_url: Callable[[str], str],
    run_active: Callable[[], bool] = lambda: False,
    actor: str = "intake",
    now: Callable[[], str] = utc_now_iso,
    force: bool = False,
) -> PollReport:
    """Read the watched column once and do whatever each ticket has earned.

    Never raises: a tracker failure is a :class:`PollReport` with ``stopped`` set and an
    ``intake.stopped`` event on the chain, and the next poll retries. Nothing is
    registered from a partial read — a ticket whose own read fails is skipped and the
    rest of the column is still served.

    ``force`` ignores the idempotency key and re-reads every ticket in the column. It is
    what "Post the feedback again" does, for a person who deleted the comment or wants to
    see the current numbers on the ticket. It is still safe to repeat: the comment and the
    label are idempotent on the tracker's side, so an unchanged ticket gets identical text
    and nothing is written.
    """
    report = PollReport(repo=repo, column=column, at=now())
    evidence = home.evidence(actor=actor)
    try:
        refs = tracker.entered(column, listener.since)
    except TrackerError as exc:
        report.stopped, report.detail = exc.reason, exc.detail
        evidence.append(EV_STOPPED, "", step="entered", reason=exc.reason, detail=exc.detail)
        return report
    report.seen = len(refs)
    events = _read_events(home)
    signoffs = list(home.gap_ledger().records()) if home.dir.exists() else []
    for ref in refs:
        row = _handle_ticket(
            ref,
            tracker=tracker,
            home=home,
            evidence=evidence,
            events=events,
            signoffs=signoffs,
            route_for=route_for,
            item_url=item_url,
            run_active=run_active,
            actor=actor,
            now=now,
            report=report,
            force=force,
        )
        if row is not None:
            report.rows.append(row)
    evidence.append(
        EV_POLLED,
        "",
        column=column,
        seen=report.seen,
        read=report.read,
        skipped=report.skipped,
        registered=report.registered,
        queued=report.queued,
    )
    return report


def _handle_ticket(
    ref: TicketRef,
    *,
    tracker: TrackerClient,
    home: FactoryHome,
    evidence: Any,
    events: Sequence[Any],
    signoffs: Sequence[Any],
    route_for: Callable[[BacklogItem], Mapping[str, Any] | None],
    item_url: Callable[[str], str],
    run_active: Callable[[], bool],
    actor: str,
    now: Callable[[], str],
    report: PollReport,
    force: bool = False,
) -> IntakeRow | None:
    """One ticket, end to end. Returns the row to serve, or ``None`` when it was skipped."""
    del actor
    if not force and already_handled(events, tracker.name, ref.key, ref.revision):
        report.skipped += 1
        return _row_from_state(home, ref)
    try:
        ticket = tracker.read(ref.key)
    except TrackerError as exc:
        evidence.append(
            EV_STOPPED, "", step="read", key=ref.key, reason=exc.reason, detail=exc.detail
        )
        report.skipped += 1
        return IntakeRow(
            key=ref.key,
            title=ref.title,
            url=ref.url,
            revision=ref.revision,
            label="",
            state="",
            item_id="",
            item_url="",
            feedback="",
            read_at=now(),
            stopped=exc.reason,
            stopped_advice=exc.advice,
        )
    report.read += 1
    previous_id = item_for_ticket(events, tracker.name, ticket.key)
    backlog = home.load_backlog()
    previous = backlog.get(previous_id) if (backlog is not None and previous_id) else None
    draft = draft_from(ticket, tracker=tracker.name, previous=previous)
    readiness = assess(draft.item, signoffs)
    route = route_for(draft.item)
    feedback = render_feedback(draft, readiness, cell_route=route)
    row = IntakeRow(
        key=ticket.key,
        title=ticket.title,
        url=ticket.url,
        revision=ticket.revision,
        label=feedback.label,
        state=ticket.state,
        item_id=draft.item.id,
        item_url=item_url(draft.item.id),
        feedback=feedback.text,
        open_questions=feedback.open_questions,
        capability_class=draft.item.capability_class,
        confidence=draft.classification.confidence,
        size=draft.item.size_estimate,
        is_evolution=draft.is_evolution,
        supersedes=draft.item.supersedes,
        cell_route=route,
        read_at=now(),
    )
    try:
        tracker.comment(ticket.key, feedback.text, feedback.marker)
        tracker.label(ticket.key, feedback.label)
    except TrackerError as exc:
        evidence.append(
            EV_STOPPED,
            draft.item.id,
            step="feedback",
            key=ticket.key,
            reason=exc.reason,
            detail=exc.detail,
        )
        return _stopped(row, exc)
    report.commented += 1
    evidence.append(
        EV_FEEDBACK,
        draft.item.id,
        tracker=tracker.name,
        key=ticket.key,
        label=feedback.label,
        marker=feedback.marker,
        open_questions=len(feedback.open_questions),
        route=(route or {}).get("route", ""),
    )
    awaiting = False
    already_registered = backlog is not None and backlog.get(draft.item.id) is not None
    if feedback.ready_to_register and already_registered:
        # a forced re-read of a ticket nothing has changed: the item is already on the
        # frozen record, so registering it again would be an ItemExists refusal recorded
        # as a stop. The comment and the label have been refreshed; that is the whole job.
        row = replace_row(row, registered=True, label=LABEL_QUEUED)
    elif feedback.ready_to_register:
        awaiting = not _register_and_queue(
            draft,
            tracker=tracker,
            home=home,
            evidence=evidence,
            item_url=item_url,
            run_active=run_active,
            report=report,
            row=row,
        )
        row = replace_row(
            row, registered=not awaiting, label=LABEL_QUEUED if not awaiting else row.label
        )
    evidence.append(
        EV_READ,
        draft.item.id,
        tracker=tracker.name,
        key=ticket.key,
        revision=ticket.revision,
        ready=feedback.ready_to_register,
        awaiting_registration=awaiting,
    )
    return row


def replace_row(row: IntakeRow, **changes: Any) -> IntakeRow:
    """A copy of ``row`` with ``changes`` applied (``dataclasses.replace`` by another name,
    kept here so a reader sees one shape)."""
    body = {**row.to_dict(), **dict(changes)}
    body["open_questions"] = [dict(q) for q in row.open_questions]
    body["cell_route"] = dict(row.cell_route) if row.cell_route else None
    return IntakeRow.from_dict(body)


def _stopped(row: IntakeRow, exc: TrackerError) -> IntakeRow:
    return replace_row(row, stopped=exc.reason, stopped_advice=exc.advice)


def _register_and_queue(
    draft: Draft,
    *,
    tracker: TrackerClient,
    home: FactoryHome,
    evidence: Any,
    item_url: Callable[[str], str],
    run_active: Callable[[], bool],
    report: PollReport,
    row: IntakeRow,
) -> bool:
    """Register the draft and tell the ticket. ``False`` means "queued, try next poll"."""
    del row
    if run_active():
        report.queued += 1
        evidence.append(
            EV_QUEUED,
            draft.item.id,
            tracker=tracker.name,
            key=draft.ticket.key,
            reason="a factory run holds this repository's backlog; the next poll registers it",
        )
        return False
    try:
        how = _register(home, draft.item, actor=f"intake:{tracker.name}")
    except Exception as exc:  # a malformed item or a frozen-record refusal: never crash a poll
        evidence.append(
            EV_STOPPED,
            draft.item.id,
            step="register",
            key=draft.ticket.key,
            reason="refused",
            detail=str(exc)[:300],
        )
        return True
    report.registered += 1
    url = item_url(draft.item.id)
    evidence.append(
        EV_REGISTERED,
        draft.item.id,
        tracker=tracker.name,
        key=draft.ticket.key,
        how=how,
        supersedes=draft.item.supersedes,
        url=url,
    )
    try:
        tracker.label(draft.ticket.key, LABEL_QUEUED)
        tracker.comment(
            draft.ticket.key,
            render_queued(draft.item.id, url),
            marker_for(tracker.name, f"{draft.ticket.key}:queued"),
        )
        tracker.link(draft.ticket.key, url)
    except TrackerError as exc:
        # the item IS registered; only the courtesy write failed. Say so and move on.
        evidence.append(
            EV_STOPPED,
            draft.item.id,
            step="queued",
            key=draft.ticket.key,
            reason=exc.reason,
            detail=exc.detail,
        )
    return True


def _row_from_state(home: FactoryHome, ref: TicketRef) -> IntakeRow | None:
    """The row a previous poll served for this ticket, so a skip still shows something."""
    store = IntakeStore(home.dir.parent.parent, home.repo)
    for row in store.rows():
        if row.key == ref.key:
            return row
    return None


# ---------------------------------------------------------------------------
# the later moments: the pull request, the refusal, the merge
# ---------------------------------------------------------------------------


def post_delivery(
    tracker: TrackerClient, key: str, item_id: str, pr_url: str, *, evidence: Any
) -> bool:
    """Tell the ticket its pull request is open. ``False`` when the tracker refused."""
    try:
        tracker.comment(
            key, render_delivered(item_id, pr_url), marker_for(tracker.name, f"{key}:pr")
        )
        tracker.link(key, pr_url)
    except TrackerError as exc:
        evidence.append(
            EV_STOPPED, item_id, step="delivered", key=key, reason=exc.reason, detail=exc.detail
        )
        return False
    evidence.append(EV_DELIVERED, item_id, tracker=tracker.name, key=key, url=pr_url)
    return True


def post_refusal(
    tracker: TrackerClient,
    key: str,
    item_id: str,
    *,
    status: str,
    reason: str,
    way_forward: str,
    url: str,
    evidence: Any,
) -> bool:
    """Tell the ticket the loop stopped, carrying the served way forward verbatim."""
    text = render_refusal(item_id, status=status, reason=reason, way_forward=way_forward, url=url)
    try:
        tracker.comment(key, text, marker_for(tracker.name, f"{key}:refusal"))
    except TrackerError as exc:
        evidence.append(
            EV_STOPPED, item_id, step="refusal", key=key, reason=exc.reason, detail=exc.detail
        )
        return False
    return True


def post_outcomes_to_tickets(
    tracker: TrackerClient,
    *,
    home: FactoryHome,
    item_url: Callable[[str], str],
    evidence: Any,
) -> list[str]:
    """Tell each ticket what happened to the item it became: the pull request link when one
    opened, or the refusal with the way forward the API serves.

    Read from the chain rather than pushed from inside the loop: the loop knows nothing
    about tickets, and it should not — intake is a layer above it, and the chain already
    carries both facts. Each is posted once, under its own marker, so this is safe to run
    on every poll. Returns the ticket keys written to.
    """
    events = home.events()
    keys = {
        str(e.item_id): str(e.payload.get("key", ""))
        for e in events
        if e.kind == EV_REGISTERED and e.payload.get("key")
    }
    if not keys:
        return []
    told = {str(e.item_id) for e in events if e.kind == EV_DELIVERED}
    delivered: dict[str, str] = {}
    stopped: dict[str, tuple[str, str]] = {}
    for e in events:
        item_id = str(e.item_id)
        if item_id not in keys:
            continue
        if e.kind in ("delivery.opened", "delivery.updated"):
            url = str(e.payload.get("pr_url") or "")
            if url:
                delivered[item_id] = url
        elif e.kind == "item.outcome":
            status = str(e.payload.get("status") or "")
            if status in STOPPED_STATUSES:
                stopped[item_id] = (status, str(e.payload.get("error") or ""))
            else:
                stopped.pop(item_id, None)
    written: list[str] = []
    for item_id, url in delivered.items():
        if item_id in told:
            continue
        if post_delivery(tracker, keys[item_id], item_id, url, evidence=evidence):
            written.append(keys[item_id])
    for item_id, (status, reason) in stopped.items():
        if item_id in delivered:
            continue
        ok = post_refusal(
            tracker,
            keys[item_id],
            item_id,
            status=status,
            reason=reason,
            way_forward=(
                "Answer what is missing on this ticket and the product will read it again: "
                "the edit becomes a new item that supersedes this one."
            ),
            url=item_url(item_id),
            evidence=evidence,
        )
        if ok:
            written.append(keys[item_id])
    return written


def apply_outcome_map(
    tracker: TrackerClient,
    *,
    home: FactoryHome,
    outcome_map: Mapping[str, str],
    evidence: Any,
) -> list[str]:
    """Move each ticket whose pull request has reached its fate, per the configured map.

    The default map is empty, so a deployment that configured nothing moves no ticket.
    Each transition is recorded as ``intake.transitioned`` on the item's chain; a
    workflow that refuses the move is recorded and never retried with something else.
    """
    if not outcome_map:
        return []
    events = home.events()
    intake_keys = {
        str(e.item_id): str(e.payload.get("key", ""))
        for e in events
        if e.kind == EV_REGISTERED and e.payload.get("key")
    }
    done = {
        (str(e.item_id), str(e.payload.get("outcome", "")))
        for e in events
        if e.kind == EV_TRANSITIONED
    }
    moved: list[str] = []
    for e in events:
        if e.kind not in ("delivery.merged", "delivery.closed"):
            continue
        item_id = str(e.item_id)
        key = intake_keys.get(item_id, "")
        outcome = OUTCOME_MERGED if e.kind == "delivery.merged" else OUTCOME_CLOSED
        state = str(outcome_map.get(outcome, ""))
        if not key or not state or (item_id, outcome) in done:
            continue
        try:
            tracker.transition(key, state)
        except TrackerError as exc:
            evidence.append(
                EV_STOPPED,
                item_id,
                step="transition",
                key=key,
                reason=exc.reason,
                detail=exc.detail,
            )
            continue
        evidence.append(EV_TRANSITIONED, item_id, key=key, outcome=outcome, state=state)
        done.add((item_id, outcome))
        moved.append(key)
    return moved


__all__ = [
    "CONFIG_KEY",
    "EV_DELIVERED",
    "EV_FEEDBACK",
    "EV_POLLED",
    "EV_QUEUED",
    "EV_READ",
    "EV_REGISTERED",
    "EV_STOPPED",
    "EV_TRANSITIONED",
    "INTAKE_EVENTS",
    "OUTCOME_CLOSED",
    "OUTCOME_MERGED",
    "STATE_FILE",
    "STOPPED_STATUSES",
    "IntakeRow",
    "IntakeStore",
    "ListenerState",
    "PollReport",
    "RunActive",
    "Ticket",
    "already_handled",
    "apply_outcome_map",
    "build_tracker",
    "item_for_ticket",
    "poll_repository",
    "post_delivery",
    "post_outcomes_to_tickets",
    "post_refusal",
    "replace_row",
]
