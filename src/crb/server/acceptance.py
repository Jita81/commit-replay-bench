"""The store of held-out acceptance tests, and the assignments a second person answers.

ADR-0026 item 8. A calibration build on a ticket that carries a person's failing test is graded,
on its first attempt, on held-out acceptance tests a SECOND person writes from the ticket alone.
This module keeps those tests where no builder can reach them — one ``acceptance.written`` event
per calibration grant, on the repository's ``acceptance:<repo>`` trace of the hash-chained
``events`` table, content included — and serves only what a page may show: who wrote them,
when, the digest and the paths.

An **assignment** is a funded, unclaimed calibration grant on a ticket that carries a person's
failing test and was never built: the second person sees the ticket's title, description,
acceptance criteria, class and size — never its failing test, and there is no build to see.

Navigation
----------
What it is:   The server's reader and writer of held-out acceptance-test records, the reader
              the factory worker binds for a run, and the assignment list a person answers.
What it does: Loads a repository's verified records oldest first; writes one record per grant
              under the events write lock (a second is refused ``acceptance_written``); lists
              each ticket that needs held-out tests or has them, with whether the signed-in
              person may write them and why not; binds ``(item, grant) → record`` for a run.
How:          ``append_event_checked`` (the lock, a check for a record of the same grant, the
              insert) → ``load_held_out`` reads ``acceptance.written`` events in insertion order
              and keeps those whose digest and id re-hash; the assignment list folds the
              factory chain (grants, claims, builds, gradings) with the backlog.
Layer:        server — docs/ARCHITECTURE.md#41-c4-level-2--containers
ADRs:         docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/core/acceptance.py (the record and the two-person rule),
              src/crb/server/routes/acceptance.py (the routes), src/crb/server/worker.py (binds
              ``held_out_reader`` into the factory run), src/crb/server/routes/readings.py
              (enrols a forward reading's pool from these records), src/crb/store/events.py
              (the locked write), src/crb/server/factory_state.py (the backlog and the chain)
Tested by:    tests/test_server_acceptance.py, tests/test_forward_reading_e2e.py
Touch when:   never for a new repository; the record's shape changes (crb.core.acceptance
              first); an assignment gains a field (docs/API.md's Factory table and
              ui/src/api/types.ts with it).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.acceptance import (
    EVENT_ACTION,
    WHY_NO_TESTS,
    WHY_NOT_FIRST,
    WHY_SAME_PERSON,
    HeldOutTests,
    person,
    trace_for,
    writer_refusal,
)
from crb.core.reading import Reading
from crb.factory.backlog import BacklogItem
from crb.factory.evidence import (
    EV_ACCEPTANCE_GRADED,
    EV_ACCEPTANCE_NOT_GRADED,
    EV_BUILD,
    EV_CALIBRATION_CLAIMED,
    EV_CALIBRATION_FUNDED,
    EV_ITEM_OUTCOME,
    FactoryEvent,
    attempted_before,
    spent_grants,
    ticket_authors,
)
from crb.factory.testfirst import AuthoredTest
from crb.store.events import append_event_checked
from crb.store.models import Event

#: A second record for the same grant.
CODE_WRITTEN = "acceptance_written"

#: An assignment's states.
STATUS_OPEN = "open"
STATUS_WRITTEN = "written"
STATUS_BUILDING = "building"
STATUS_GRADED = "graded"
#: The build ran and its first attempt was NOT graded on held-out tests (the chain's
#: ``acceptance.not_graded`` says why, recorded before the build).
STATUS_NOT_GRADED = "not_graded"
#: The ticket was attempted before this grant: its next attempt is never graded on them.
STATUS_CANNOT_GRADE = "cannot_grade"


class AcceptanceRefused(ValueError):
    """A write the rules refuse — ``code`` names the rule, ``status`` the HTTP status."""

    def __init__(self, message: str, *, code: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def load_held_out(session: Session, repo: str) -> list[HeldOutTests]:
    """``repo``'s held-out records, oldest first; a record whose digest or id does not
    re-hash is left out (it grades nothing and enrols nothing)."""
    out: list[HeldOutTests] = []
    for ev in session.execute(
        select(Event)
        .where(Event.trace_id == trace_for(repo), Event.action == EVENT_ACTION)
        .order_by(Event.id)
    ).scalars():
        rec = HeldOutTests.from_dict(dict(ev.payload_json or {}))
        if rec.verify() and rec.repo == repo:
            out.append(rec)
    return out


def record_for(records: Iterable[HeldOutTests], item_id: str, grant: str) -> HeldOutTests | None:
    """The record written for ``item_id``'s grant ``grant``, or ``None``."""
    return next((r for r in records if (r.item_id, r.grant) == (item_id, grant)), None)


def held_out_reader(
    factory: sessionmaker[Session], repo: str
) -> Callable[[str, str], HeldOutTests | None]:
    """``FactorySpec.held_out`` for a run on ``repo``: read at the moment the loop asks —
    after it claimed the grant, before any build."""

    def read(item_id: str, grant: str) -> HeldOutTests | None:
        with factory() as s:
            return record_for(load_held_out(s, repo), item_id, grant)

    return read


def write_held_out(factory: sessionmaker[Session], record: HeldOutTests) -> HeldOutTests:
    """Write ``record`` as one ``acceptance.written`` event, refused ``acceptance_written``
    when its grant already has one — decided under the events write lock, so two people
    pressing at once write one record."""

    def build(s: Session) -> dict[str, Any]:
        if record_for(load_held_out(s, record.repo), record.item_id, record.grant) is not None:
            raise AcceptanceRefused(
                "held-out acceptance tests are already written for this calibration build",
                code=CODE_WRITTEN,
            )
        return record.to_dict()

    append_event_checked(
        factory,
        trace_id=trace_for(record.repo),
        stage="system",
        action=EVENT_ACTION,
        build=build,
        actor=person(record.author),
        repo=record.repo,
    )
    return record


def latest_grant(events: Sequence[FactoryEvent]) -> FactoryEvent | None:
    """The item's newest ``calibration.funded`` event, or ``None``."""
    grants = [e for e in events if e.kind == EV_CALIBRATION_FUNDED]
    return grants[-1] if grants else None


#: Why a calibration build's first attempt was not graded on the held-out tests, in words.
NOT_GRADED_WHY: dict[str, str] = {
    WHY_NO_TESTS: (
        "the build started before any held-out tests were written, so its first attempt was "
        "graded on the ticket's own test only"
    ),
    WHY_NOT_FIRST: (
        "the ticket was attempted before, so this build was not its first attempt and was not "
        "graded on the held-out tests"
    ),
    WHY_SAME_PERSON: (
        "the tests were not used: whoever wrote them is the ticket's author, the approver who "
        "funded the build or the person who ran it"
    ),
}


def _state(
    events: Sequence[FactoryEvent], grant: FactoryEvent, rec: HeldOutTests | None
) -> tuple[str, str]:
    """The assignment's state and why it cannot be written, read from the item's chain."""
    gid = grant.event_id
    if any(e.kind == EV_ACCEPTANCE_GRADED and e.payload.get("grant") == gid for e in events):
        return STATUS_GRADED, "the build's first attempt has been graded on the held-out tests"
    refused = next(
        (e for e in events if e.kind == EV_ACCEPTANCE_NOT_GRADED and e.payload.get("grant") == gid),
        None,
    )
    if refused is not None:
        why = str(refused.payload.get("why", ""))
        return STATUS_NOT_GRADED, NOT_GRADED_WHY.get(why, why or "the build was not graded")
    if gid in spent_grants(events):
        claim = next(
            (
                i
                for i, e in enumerate(events)
                if e.kind == EV_CALIBRATION_CLAIMED and e.payload.get("grant") == gid
            ),
            None,
        )
        after = events[claim + 1 :] if claim is not None else ()
        if claim is None or any(e.kind in (EV_BUILD, EV_ITEM_OUTCOME) for e in after):
            # built, or ended, and never graded on held-out tests (a chain from before
            # ``acceptance.not_graded`` existed, or a run that ended without building)
            return STATUS_NOT_GRADED, "the build ran without being graded on held-out tests"
        return STATUS_BUILDING, "the build has started: tests written now could not be held out"
    if attempted_before(events, grant.item_id, grant=gid):
        return (
            STATUS_CANNOT_GRADE,
            "the ticket was attempted before: its next attempt is never graded on held-out tests",
        )
    if rec is not None:
        return STATUS_WRITTEN, "held-out acceptance tests are already written for this build"
    return STATUS_OPEN, ""


def assignment(
    item: BacklogItem,
    chain: Sequence[FactoryEvent],
    authored: AuthoredTest | None,
    records: Sequence[HeldOutTests],
    *,
    viewer: str,
    viewer_may_write: bool,
    language: str = "",
    forwards: Sequence[Reading] = (),
    path: str = "",
) -> dict[str, Any] | None:
    """One ticket's assignment as the page shows it to ``viewer``, or ``None`` when it has
    none: a ticket with no person's failing test, or no calibration grant. ``chain`` is the
    repository's whole factory chain. Never the failing test, never a build — the second
    person writes from the ticket alone. ``forwards`` are the repository's registered forward
    readings (enrolled), so the page can say whether one will count this ticket; ``path`` is a
    test path the runner accepts."""
    if authored is None or not authored.operator_authored:
        return None
    events = [e for e in chain if e.item_id == item.id]
    grant = latest_grant(events)
    if grant is None:
        return None
    rec = record_for(records, item.id, grant.event_id)
    graded = next(
        (
            e
            for e in events
            if e.kind == EV_ACCEPTANCE_GRADED and e.payload.get("grant") == grant.event_id
        ),
        None,
    )
    status, why = _state(events, grant, rec)
    if status == STATUS_OPEN:
        if not viewer_may_write:
            why = "writing held-out acceptance tests needs the operator role or above"
        else:
            why = writer_refusal(
                viewer,
                ticket_authors=ticket_authors(chain, item.id, authored.author),
                sponsor=str(grant.payload.get("approver", "")),
            )
    funded_by = str(grant.payload.get("approver", ""))
    cell = (item.capability_class, item.size_estimate, language)
    on_cell = [
        r
        for r in forwards
        if (
            r.cell.get("capability_class", ""),
            r.cell.get("size", ""),
            r.cell.get("language", ""),
        )
        == cell
    ]
    counted_by = next((r.reading_id for r in on_cell if item.id in r.pool), "")
    return {
        "item_id": item.id,
        "title": item.title,
        "description": item.description,
        "acceptance_criteria": list(item.acceptance_criteria),
        "capability_class": item.capability_class,
        "size": item.size_estimate,
        "grant": grant.event_id,
        "funded_by": funded_by,
        "funded_at": grant.created,
        "status": status,
        "can_write": not why,
        "why_not": why,
        "record": rec.public() if rec is not None else None,
        "result": str(graded.payload.get("result", "")) if graded is not None else "",
        "forward_reading": on_cell[-1].reading_id if on_cell else "",
        "counted_by": counted_by,
        "suggested_path": path,
    }


__all__ = [
    "CODE_WRITTEN",
    "NOT_GRADED_WHY",
    "STATUS_BUILDING",
    "STATUS_CANNOT_GRADE",
    "STATUS_GRADED",
    "STATUS_NOT_GRADED",
    "STATUS_OPEN",
    "STATUS_WRITTEN",
    "AcceptanceRefused",
    "assignment",
    "held_out_reader",
    "latest_grant",
    "load_held_out",
    "record_for",
    "write_held_out",
]
