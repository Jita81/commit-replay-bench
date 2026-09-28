"""An organisation's class sets, bound to the store: the report, the verdict and the two hooks.

The core (:mod:`crb.core.class_sets`) holds the rule; this module reads what it needs from the
store and serves it to the four places that use a class set: ``/classes`` (the screen), the
intake (it stamps a ticket with the class the version's rule gives), the factory's entry gate
(a version that does not route licenses nothing) and ``POST /readings`` (a reading of an
organisation's class reads only its confirmation commits).

* **The cases.** A version's replayable commits are the mined tasks of the repositories it
  covers. Each is in the derivation or the confirmation set by the version's own split; its
  fields are its linked ticket as it stood at the parent's date where a linked-ticket reader is
  bound (:data:`LINKED_TICKET_READER`, a seam — none is bound by default, and then every commit
  reads its message, marked as a proxy).
* **The relabel.** When a version is proposed, its rule is applied to every commit and written to
  the label table (``class_labels``, ``source = rule``); no stored ledger row is touched.
* **The verdict.** A version routes only when it is signed by a second person, not revoked, and
  its validity report passes.

Navigation
----------
What it is:   The store-bound side of class sets: the cases a report reads, the relabel, the
              report and route verdict per version, the version a repository's intake stamps
              with, the ticket-to-fields mapping and the draft stamper.
What it does: Builds each commit's ``Case`` (split, churn tier, qualified, message or linked
              ticket); writes the rule's labels on proposal; computes the validity report and
              the verdict; picks the latest routing version covering a repository; turns an
              intake ticket into ticket-time fields and stamps its draft with the version, the
              organisation's class, its global parent and how it was decided, and records the
              classification as an event (an override is counted); tells the gate whether the
              points-to-churn agreement passed.
How:          ``DbClassSets`` for the acts and labels, ``Task`` rows for the commits,
              ``Event`` rows for the intake's classifications; everything else is the core's.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   src/crb/core/class_sets.py (the rule, the report, the verdict),
              src/crb/store/class_sets.py (the acts and the label table),
              src/crb/server/routes/classes.py (the screen's routes),
              src/crb/server/intake.py (the draft stamper),
              src/crb/server/factory_standard.py (the gate's readers),
              src/crb/server/routes/readings.py (the reading's pool)
Tested by:    tests/test_server_routes_classes.py, tests/test_class_set_hooks.py,
              tests/test_class_set_worker.py
Touch when:   onboarding a client repository never needs it — a repository joins a class set
              when a version names it; a tracker gains a history reader (bind
              ``LINKED_TICKET_READER``); a place that reads a class set is added (read the
              verdict here, never a second one).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.class_sets import (
    BY_OVERRIDE,
    Case,
    ClassSetVersion,
    PersonLabel,
    RouteVerdict,
    TicketFields,
    ValidityReport,
    VersionState,
    classify,
    from_message,
    routes,
    validity_report,
)
from crb.core.evidence import utc_now_iso
from crb.core.taxonomy import GLOBAL_CLASS_SET, UNCLASSIFIED
from crb.intake.client import Ticket
from crb.intake.draft import Classification, Draft, facts_for, kind_for, size_for
from crb.store.class_sets import SOURCE_PERSON, SOURCE_RULE, DbClassSets
from crb.store.models import Event, Task

#: ``(repo, commit, as_of) → TicketFields | None`` — the commit's linked ticket as it stood at
#: ``as_of`` (the parent's date). SEAM: no tracker history reader is bound by default, so a
#: replayed commit reads its message, marked as a proxy (ADR-0026 item 9; G-761).
LinkedTicketReader = Callable[[str, str, str], "TicketFields | None"]
LINKED_TICKET_READER: list[LinkedTicketReader | None] = [None]

#: The event the intake writes for each ticket a class set classified.
EV_TICKET_CLASSIFIED = "class_set.ticket_classified"
#: The labels a stamped draft carries.
LABEL_TAXONOMY = "taxonomy"
LABEL_ORG_CLASS = "org_class"
LABEL_CLASS_BY = "class_by"
#: The labels only the intake's classification writes; a backlog item registered by hand may
#: not carry them, or it could claim an organisation's class no rule gave and no override
#: counted (P-683).
RESERVED_LABELS: tuple[str, ...] = (LABEL_TAXONOMY, LABEL_ORG_CLASS, LABEL_CLASS_BY)


def points_tier(points: float) -> str:
    """Intake's published points-to-tier scale — the tier a ticket's points name."""
    return size_for(points)[0]


def cases_for(session: Session, version: ClassSetVersion) -> list[Case]:
    """Every mined commit of the version's repositories as the report reads it."""
    reader = LINKED_TICKET_READER[0]
    rows = session.execute(
        select(Task).where(Task.repo.in_(version.repos)).order_by(Task.repo, Task.task_id)
    ).scalars()
    out: list[Case] = []
    for t in rows:
        ticket = reader(t.repo, t.task_id, t.authored) if reader is not None else None
        out.append(
            Case(
                repo=t.repo,
                task_id=t.task_id,
                split=version.split(t.repo, t.task_id),
                size=t.size,
                message=from_message(t.subject),
                ticket=ticket,
                qualified=t.gold_clean is True,
                mined_class=t.capability_class,
            )
        )
    return out


def _factory_of(session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def person_labels(store: DbClassSets, version_id: str) -> list[PersonLabel]:
    return [
        PersonLabel(r.repo, r.task_id, r.capability_class, r.labeller, r.created)
        for r in store.labels(version_id, source=SOURCE_PERSON)
    ]


def intake_counts(session: Session, version_id: str) -> tuple[int, int]:
    """``(overrides, classified)`` — the intake's tickets this version classified, and how
    many a person named with ``crb:class=``."""
    overrides = classified = 0
    payloads: list[dict[str, Any]] = list(
        session.execute(
            select(Event.payload_json).where(Event.action == EV_TICKET_CLASSIFIED)
        ).scalars()
    )
    for payload in payloads:
        p = dict(payload or {})
        if p.get("taxonomy") != version_id or p.get("class") in ("", UNCLASSIFIED):
            continue
        classified += 1
        overrides += 1 if p.get("by") == BY_OVERRIDE else 0
    return overrides, classified


def report_for(session: Session, state: VersionState) -> ValidityReport:
    """The version's validity report over the store as it now reads."""
    store = DbClassSets(_factory_of(session))
    overrides, classified = intake_counts(session, state.version_id)
    return validity_report(
        state.version,
        cases_for(session, state.version),
        person_labels(store, state.version_id),
        points_tier=points_tier,
        intake_overrides=overrides,
        intake_classified=classified,
    )


def verdict_for(session: Session, version_id: str) -> tuple[VersionState | None, RouteVerdict]:
    """The version's state and whether it routes. The global vocabulary always routes."""
    if version_id in ("", GLOBAL_CLASS_SET):
        return None, RouteVerdict(True, "routes", "The global vocabulary.")
    state = DbClassSets(_factory_of(session)).versions().get(version_id)
    if state is None or not state.signed:
        return state, routes(state, None)
    return state, routes(state, report_for(session, state))


def active_version(session: Session, repo: str) -> tuple[VersionState, ValidityReport] | None:
    """The latest version that covers ``repo`` and routes, with its report — the version the
    intake stamps a ticket with — or ``None`` (the global vocabulary)."""
    store = DbClassSets(_factory_of(session))
    signed = sorted(
        (s for s in store.versions().values() if s.signed and repo in s.version.repos),
        key=lambda s: (s.version.org, -s.version.n),
    )
    for state in signed:
        report = report_for(session, state)
        if routes(state, report).ok:
            return state, report
    return None


def relabel(session: Session, state: VersionState, *, actor: str) -> int:
    """Apply the version's rule to every commit and append the labels (``source = rule``):
    the label table changes, never a stored ledger row. Returns the count written."""
    cases = cases_for(session, state.version)
    labels = [(c.repo, c.task_id, classify(state.version, c.fields).slug) for c in cases]
    return DbClassSets(_factory_of(session)).add_labels(
        state.version_id, labels, source=SOURCE_RULE, labeller=actor
    )


def ticket_fields(ticket: Ticket, *, as_of: str = "") -> TicketFields:
    """An intake ticket as the rule reads it: its title, body and acceptance criteria as text,
    its work-item type, its component or area (``extra``), its tags and its points — read now,
    so the source is ``ticket@<today>``."""
    extra = dict(ticket.extra)
    component = extra.get("component") or extra.get("area") or extra.get("area_path") or ""
    text = "\n".join([ticket.title, ticket.body, *ticket.acceptance_criteria])
    return TicketFields(
        text=text,
        work_item_type=ticket.type,
        component=str(component).rsplit("\\", 1)[-1],
        labels=tuple(ticket.tags),
        points=ticket.points,
        source=f"ticket@{(as_of or utc_now_iso())[:10]}",
    )


def stamp(draft: Draft, state: VersionState, *, as_of: str = "") -> tuple[Draft, dict[str, Any]]:
    """The draft classified by ``state``'s version: a ticket in one of its classes carries
    ``taxonomy``, ``org_class`` and ``class_by`` labels and its class's global parent as its
    capability class (the cell key keeps the parent); a ticket in none keeps the global
    classifier's class and vocabulary. Returns the draft and the event payload."""
    decision = classify(state.version, ticket_fields(draft.ticket, as_of=as_of))
    payload = {
        "taxonomy": state.version_id,
        "class": decision.slug,
        "by": decision.by,
        "ticket": draft.ticket.key,
    }
    if not decision.classified:
        return draft, payload
    # everything the class decides is derived again for the parent: the structural facts a
    # ticket's acceptance criteria answer, and whether it is code or infrastructure (P-680)
    facts, prose, unused = facts_for(draft.ticket.acceptance_criteria, decision.parent)
    kind, _why = kind_for(decision.parent, draft.ticket.tags, draft.ticket.type)
    item = replace(
        draft.item,
        capability_class=decision.parent,
        kind=kind,
        structural_facts=facts,
        acceptance_criteria=prose,
        labels={
            **dict(draft.item.labels),
            LABEL_TAXONOMY: state.version_id,
            LABEL_ORG_CLASS: decision.slug,
            LABEL_CLASS_BY: decision.by,
        },
    )
    how = (
        f"The ticket carries the tag crb:class={decision.slug}."
        if decision.by == BY_OVERRIDE
        else f"{state.version_id}'s rule puts the ticket in {decision.slug}."
    )
    classification = Classification(
        decision.parent,
        1.0,
        f"{how} Its global parent is {decision.parent}.",
        ((decision.parent, 0),),
    )
    stamped = replace(draft, item=item, classification=classification, unused_fact_lines=unused)
    return stamped, payload


def draft_stamper(factory: sessionmaker[Session], repo: str) -> Callable[[Draft], Draft]:
    """The intake's hook for ``repo``, bound once per poll: the latest routing version
    covering the repository classifies each draft (the same rule as at replay), and each
    classification is recorded as an event so the report can count overrides. With no routing
    version, drafts pass through unchanged (the global vocabulary)."""
    from crb.server.routes.runs import append_system_event, system_trace_id  # noqa: PLC0415

    with factory() as s:
        active = active_version(s, repo)
    if active is None:
        return lambda draft: draft
    state, _report = active

    def hook(draft: Draft) -> Draft:
        stamped, payload = stamp(draft, state)
        with factory() as s:
            append_system_event(
                s,
                trace_id=system_trace_id("classes", state.version.org),
                action=EV_TICKET_CLASSIFIED,
                repo=repo,
                actor="worker",
                payload=payload,
            )
            s.commit()
        return stamped

    return hook


def size_agreement_passed(session: Session, repo: str) -> bool:
    """Whether the points-to-churn agreement of the routing version covering ``repo`` passed
    — the entry gate's size rule then reads points alone (ADR-0026 item 8)."""
    active = active_version(session, repo)
    return active is not None and active[1].size_from_points


def routing_versions(session: Session, taxonomies: Iterable[str]) -> Mapping[str, bool]:
    """version id → whether it routes, for each organisation version named."""
    return {t: verdict_for(session, t)[1].ok for t in set(taxonomies) if t != GLOBAL_CLASS_SET}


__all__ = [
    "EV_TICKET_CLASSIFIED",
    "LABEL_CLASS_BY",
    "LABEL_ORG_CLASS",
    "LABEL_TAXONOMY",
    "LINKED_TICKET_READER",
    "RESERVED_LABELS",
    "active_version",
    "cases_for",
    "draft_stamper",
    "intake_counts",
    "person_labels",
    "points_tier",
    "relabel",
    "report_for",
    "routing_versions",
    "size_agreement_passed",
    "stamp",
    "ticket_fields",
    "verdict_for",
]
