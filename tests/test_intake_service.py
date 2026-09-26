"""crb.server.intake — the listener's whole flow, against a fake tracker and a real chain.

Navigation
----------
What it is:   The service suite: the poll's idempotency, the draft → readiness → comment →
              label → registration path, the queued registration, the evolution on a
              re-read, every refusal path, and the outcome map.
What it does: Pins that the same column polled twice writes to the ticket once, that a
              ticket edited between polls becomes an EVOLUTION rather than an overwrite,
              that a registration arriving while a factory run is active is queued and
              picked up by the next poll rather than 409ing, that every stop is an
              ``intake.stopped`` event with a published reason and advice, that an
              empty outcome map moves no ticket at all, and (C6, ADR-0022) that a ready
              ticket waits as a draft until an operator's Register act registers the
              revision they read, that an allowlisted author bypasses it on the record, and
              that two overlapping passes register once because a pass takes a lease that
              expires when its holder dies. Since the PR #55 review: that no public
              function taking an ``item_url`` builder lets a relative link reach a ticket
              (a ratchet lists every such function).
How:          A real ``FactoryHome`` under ``tmp_path`` (so the hash chain is the real
              one) plus ``fixtures.intake``'s ``FakeTracker``. No HTTP, no
              database, no model — the whole flow is exercised in milliseconds.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/server/intake.py (under test), src/crb/server/factory_state.py (the
              ``FactoryHome`` it registers through), src/crb/intake/client.py (the fake's
              protocol), tests/fixtures/intake.py (the fake)
Tested by:    tests/test_intake_service.py
Touch when:   a step is added to the poll — pin its idempotency here before its behaviour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.factory.backlog import BacklogItem
from crb.intake import client as c
from crb.server import intake as sv
from crb.server.factory_state import FactoryHome
from fixtures.intake import FakeTracker

READY_AC = (
    "method_path: POST /health",
    "request_shape: no body",
    "response_shape: 200 with {status: string}",
    "error_contract: 503 when a dependency is down",
)


def _ticket(**kw: Any) -> c.Ticket:
    base: dict[str, Any] = {
        "key": "4711",
        "title": "Add a POST /health route",
        "body": "a new HTTP endpoint on the api",
        "acceptance_criteria": READY_AC,
        "revision": "1",
        "url": "https://tracker.invalid/4711",
    }
    base.update(kw)
    return c.Ticket(**base)


def _tracker(ticket: c.Ticket) -> FakeTracker:
    t = FakeTracker({ticket.key: ticket})
    t.column = [
        c.TicketRef(
            key=ticket.key, revision=ticket.revision, title=ticket.title, changed="2026-09-22"
        )
    ]
    return t


def _poll(
    home: FactoryHome, tracker: FakeTracker, *, route: dict[str, Any] | None = None, **kw: Any
) -> sv.PollReport:
    defaults: dict[str, Any] = {
        "tracker": tracker,
        "listener": sv.ListenerState(enabled=True),
        "column": "Ready",
        "home": home,
        "route_for": lambda item: route,
        "item_url": lambda item_id: f"https://crb.invalid/factory?item={item_id}",
        # the registration MECHANICS these tests pin (idempotency, the queued registration,
        # evolution) run with operator approval OFF; the approval gate itself — ON by
        # default in the service and the setting (ADR-0022) — is pinned in its own tests
        "approval": sv.ApprovalPolicy(required=False),
    }
    defaults.update(kw)
    return sv.poll_repository("alpha", **defaults)


def _deliver() -> dict[str, Any]:
    return {
        "route": "deliver",
        "reason": "every bar cleared",
        "n": 42,
        "point": 0.81,
        "ci_low": 0.67,
        "ci_high": 0.9,
        "apparatus_versions": ["2.2"],
    }


@pytest.fixture
def home(tmp_path: Path) -> FactoryHome:
    return FactoryHome(tmp_path, "alpha")


# --- the happy path -----------------------------------------------------------------


def test_a_ready_ticket_is_commented_labelled_registered_and_linked(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    report = _poll(home, tracker, route=_deliver())

    assert report.ok and report.read == 1 and report.registered == 1
    # the ticket learned everything, in one comment plus the queued note
    assert c.marker_for("fake", "4711") in tracker.comments["4711"]
    assert tracker.labels["4711"] == c.LABEL_QUEUED
    assert tracker.links["4711"] == ["https://crb.invalid/factory?item=fake-4711"]
    # the item is in the frozen backlog through the same path the API uses
    backlog = home.load_backlog()
    assert backlog is not None and backlog.frozen
    assert [i.id for i in backlog.items] == ["fake-4711"]
    # and every step is on the chain
    kinds = [e.kind for e in home.events()]
    assert sv.EV_FEEDBACK in kinds
    assert sv.EV_REGISTERED in kinds
    assert sv.EV_READ in kinds
    assert sv.EV_POLLED in kinds


def test_the_row_the_screen_will_show_carries_the_draft_and_the_route(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    report = _poll(home, tracker, route=_deliver())
    row = report.rows[0]
    assert row.capability_class == "backend.route.add"
    assert row.confidence > 0
    assert row.item_url.endswith("item=fake-4711")
    assert row.cell_route is not None and row.cell_route["n"] == 42
    # the comment text is served VERBATIM (docs/API.md): the screen and the ticket cannot
    # disagree. The assertion here was `"POST /health" not in row.feedback or row.feedback`,
    # which is true for an empty string and true for every non-empty one — it checked nothing.
    posted = tracker.comments["4711"][c.marker_for("fake", "4711")]
    assert row.feedback == posted
    assert row.feedback.startswith(c.marker_for("fake", "4711"))


# --- idempotency --------------------------------------------------------------------


def test_the_same_column_polled_twice_writes_to_the_ticket_once(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    before = len(tracker.calls)
    second = _poll(home, tracker, route=_deliver())
    assert second.skipped == 1 and second.read == 0
    # exactly one further call: the column listing
    assert [k for k, _ in tracker.calls[before:]] == ["entered"]


def test_a_restart_between_the_comment_and_the_registration_does_not_double_comment(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    # the factory is busy, so the registration is queued and the read is NOT finished
    _poll(home, tracker, route=_deliver(), run_active=lambda: True)
    posted = dict(tracker.comments["4711"])
    # a restart re-polls the same revision; the comment is re-rendered identically
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 1
    assert (
        tracker.comments["4711"][c.marker_for("fake", "4711")]
        == posted[c.marker_for("fake", "4711")]
    )


# --- the queued registration ---------------------------------------------------------


def test_a_registration_during_a_factory_run_is_queued_not_refused(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    report = _poll(home, tracker, route=_deliver(), run_active=lambda: True)
    assert report.queued == 1 and report.registered == 0
    assert home.load_backlog() is None  # nothing frozen under a running backlog hash
    assert tracker.labels["4711"] == c.LABEL_READY  # not queued yet, and honest about it
    assert sv.EV_QUEUED in [e.kind for e in home.events()]


def test_the_next_poll_registers_the_ticket_the_run_held_up(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), run_active=lambda: True)
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 1
    assert tracker.labels["4711"] == c.LABEL_QUEUED


# --- needs-info and the re-read ------------------------------------------------------


def test_a_ticket_missing_a_slot_is_labelled_needs_info_and_nothing_is_registered(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket(acceptance_criteria=("method_path: POST /health",)))
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 0
    assert tracker.labels["4711"] == c.LABEL_NEEDS_INFO
    assert home.load_backlog() is None
    assert "response_shape" in tracker.comments["4711"][c.marker_for("fake", "4711")]


def test_a_ticket_edited_to_close_the_gaps_registers_on_the_next_poll(home: FactoryHome) -> None:
    thin = _ticket(acceptance_criteria=("method_path: POST /health",))
    tracker = _tracker(thin)
    _poll(home, tracker, route=_deliver())
    # the person answers the questions; the tracker's revision moves
    full = _ticket(revision="2")
    tracker.tickets["4711"] = full
    tracker.column = [c.TicketRef(key="4711", revision="2", changed="2026-09-23")]
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 1
    assert [i.id for i in (home.load_backlog() or BacklogItemsEmpty()).items] == ["fake-4711"]


class BacklogItemsEmpty:
    items: tuple[BacklogItem, ...] = ()


def test_a_re_read_after_registration_is_an_evolution_not_an_overwrite(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    frozen = home.load_backlog()
    assert frozen is not None
    original_hash = frozen.backlog_hash

    tracker.tickets["4711"] = _ticket(revision="5", title="Add a POST /health route (revised)")
    tracker.column = [c.TicketRef(key="4711", revision="5", changed="2026-09-24")]
    report = _poll(home, tracker, route=_deliver())

    assert report.registered == 1
    after = home.load_backlog()
    assert after is not None
    assert after.backlog_hash == original_hash  # the frozen record never moved
    assert [e.id for e in after.evolutions] == ["fake-4711.r5"]
    assert after.evolutions[0].supersedes == "fake-4711"
    assert (
        after.get("fake-4711") is not None
        and after.get("fake-4711").title != after.evolutions[0].title
    )  # type: ignore[union-attr]


def test_a_revision_the_product_itself_moved_registers_no_second_item(home: FactoryHome) -> None:
    """The product's own writes move the ticket's revision — an Azure DevOps tag PATCH
    increments ``System.Rev``, and every Jira write moves ``fields.updated``. Compared on the
    revision alone, the next poll read a ticket NOBODY had edited as an evolution: one more
    backlog item per pass, each superseding the last, and the evolutions hash moving with
    them. The pre-filter is still the revision; the decision is the draft's own content."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    frozen = home.load_backlog()
    assert frozen is not None and [i.id for i in frozen.items] == ["fake-4711"]

    for revision in ("2", "3"):  # as the tracker would report it after the product's writes
        tracker.column = [
            c.TicketRef(key="4711", revision=revision, changed="2026-09-2" + revision)
        ]
        tracker.tickets["4711"] = _ticket(revision=revision, tags=("crb:queued",))
        report = _poll(home, tracker, route=_deliver())
        assert report.read == 1 and report.registered == 0  # re-read, nothing registered
        row = report.rows[0]
        assert row.is_evolution is False and row.item_id == "fake-4711"
        assert row.registered is True and row.label == c.LABEL_QUEUED

    after = home.load_backlog()
    assert after is not None
    assert [i.id for i in after.items] == ["fake-4711"]
    assert after.evolutions == ()  # not one needless evolution
    assert after.backlog_hash == frozen.backlog_hash
    read = [e for e in home.events() if e.kind == sv.EV_READ]
    assert read[-1].payload["revision"] == "3"  # the revision IS recorded, honestly
    assert read[-1].payload["content_revision"] == read[0].payload["content_revision"]


def test_a_deferred_registration_is_still_retried_when_the_revision_moved(
    home: FactoryHome,
) -> None:
    """The queued-registration retry does not go through the digest: nothing is registered
    yet, so there is no previous item to compare with. A ticket read while a factory run held
    the backlog is registered by the next poll, at whatever revision it is then on."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), run_active=lambda: True)
    assert home.load_backlog() is None
    assert "intake.queued" in [e.kind for e in home.events()]

    tracker.column = [c.TicketRef(key="4711", revision="2", changed="2026-09-23")]
    tracker.tickets["4711"] = _ticket(revision="2")
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 1
    backlog = home.load_backlog()
    assert backlog is not None and [i.id for i in backlog.items] == ["fake-4711"]


# --- refusal paths --------------------------------------------------------------------


def test_an_unreachable_tracker_stops_the_poll_with_a_reason_and_advice(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    tracker.fail = c.TrackerError(c.REASON_UNREACHABLE, "connect timed out")
    report = _poll(home, tracker)
    assert not report.ok
    assert report.stopped == c.REASON_UNREACHABLE
    assert report.to_dict()["advice"]
    assert [e.kind for e in home.events()] == [sv.EV_STOPPED]


def test_a_column_that_is_gone_is_its_own_reason(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    tracker.fail = c.TrackerError(c.REASON_COLUMN_GONE, "no such state")
    assert _poll(home, tracker).stopped == c.REASON_COLUMN_GONE


def test_a_ticket_whose_read_fails_is_skipped_and_the_rest_of_the_column_is_still_served(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    tracker.column = [
        c.TicketRef(key="9999", revision="1", changed="2026-09-22"),  # not in tickets → refused
        c.TicketRef(key="4711", revision="1", changed="2026-09-22"),
    ]
    report = _poll(home, tracker, route=_deliver())
    assert report.read == 1 and report.skipped == 1
    assert report.registered == 1
    assert {r.key for r in report.rows} == {"9999", "4711"}
    bad = next(r for r in report.rows if r.key == "9999")
    assert bad.stopped == c.REASON_REFUSED and bad.stopped_advice


def test_a_write_the_tracker_refuses_leaves_the_row_stopped_and_registers_nothing(
    home: FactoryHome,
) -> None:
    class RefusesWrites(FakeTracker):
        def comment(self, key: str, text: str, marker: str) -> None:
            raise c.TrackerError(c.REASON_REFUSED, "the credential may not comment")

    tracker = RefusesWrites({"4711": _ticket()})
    tracker.column = [c.TicketRef(key="4711", revision="1", changed="2026-09-22")]
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 0
    assert report.rows[0].stopped == c.REASON_REFUSED
    assert home.load_backlog() is None
    assert sv.EV_STOPPED in [e.kind for e in home.events()]


def test_a_registration_the_frozen_record_refuses_is_served_as_stopped_not_as_queued(
    home: FactoryHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_register_and_queue`` had one boolean for three outcomes, so a refusal read as "not
    awaiting": the row said registered and queued for an item that is not on the record at
    all, while the label on the board still said ready. The stop event alone did not correct
    the row, and ``already_handled`` then made every later poll skip the revision."""

    def refuse(*a: Any, **kw: Any) -> str:
        raise RuntimeError("the frozen record would not take it")

    monkeypatch.setattr(sv, "_register", refuse)
    tracker = _tracker(_ticket())
    report = _poll(home, tracker, route=_deliver())

    row = report.rows[0]
    assert row.registered is False
    assert row.stopped == c.REASON_REFUSED and row.stopped_advice
    assert row.label == c.LABEL_READY  # what the board was actually told, not "queued"
    assert report.registered == 0
    assert home.load_backlog() is None
    stops = [e for e in home.events() if e.kind == sv.EV_STOPPED]
    assert stops and stops[-1].payload["reason"] == c.REASON_REFUSED


def test_an_unclassified_ticket_is_never_registered_and_says_why(home: FactoryHome) -> None:
    tracker = _tracker(_ticket(title="Do the thing", body="by Friday", acceptance_criteria=()))
    report = _poll(home, tracker, route=_deliver())
    assert report.registered == 0
    assert tracker.labels["4711"] == c.LABEL_NEEDS_INFO
    assert "could not classify" in tracker.comments["4711"][c.marker_for("fake", "4711")].lower()


# --- building the tracker ------------------------------------------------------------


class _Intake:
    def __init__(self, **kw: Any) -> None:
        self.tracker = kw.get("tracker", "none")
        self.url = kw.get("url", "https://dev.azure.invalid/contoso")
        self.project = kw.get("project", "Widgets")
        self.column = kw.get("column", "Ready")
        self.area_path = kw.get("area_path", "")
        self.jql = ""
        self.email = ""
        self.points_field = ""
        self.acceptance_field = ""


def test_no_tracker_configured_is_its_own_stop_reason() -> None:
    with pytest.raises(c.TrackerError) as err:
        sv.build_tracker(_Intake(), "token")
    assert err.value.reason == c.REASON_NOT_CONFIGURED


def test_a_configured_tracker_without_a_stored_credential_is_no_secret() -> None:
    with pytest.raises(c.TrackerError) as err:
        sv.build_tracker(_Intake(tracker="ado"), "")
    assert err.value.reason == c.REASON_NO_SECRET


def test_the_configured_tracker_is_built_and_names_itself() -> None:
    assert sv.build_tracker(_Intake(tracker="ado"), "tok").name == "ado"
    assert (
        sv.build_tracker(_Intake(tracker="jira", url="https://x.atlassian.invalid"), "tok").name
        == "jira"
    )


# --- the listener state ----------------------------------------------------------------


def test_a_repository_with_no_intake_config_has_its_listener_off() -> None:
    assert sv.ListenerState.from_config(None).enabled is False
    assert sv.ListenerState.from_config({}).enabled is False
    assert sv.ListenerState.from_config({"intake": {}}).enabled is False


def test_the_switch_records_who_threw_it_and_when() -> None:
    st = sv.ListenerState.from_config(
        {"intake": {"enabled": True, "switched_by": "ops@example", "switched_at": "2026-09-22"}}
    )
    assert st.enabled and st.switched_by == "ops@example"
    assert sv.ListenerState.from_config({"intake": st.to_dict()}) == st


# --- the served state file ---------------------------------------------------------------


def test_the_state_file_round_trips_the_rows_the_screen_reads(
    tmp_path: Path, home: FactoryHome
) -> None:
    report = _poll(home, _tracker(_ticket()), route=_deliver())
    store = sv.IntakeStore(tmp_path, "alpha")
    store.write(report)
    rows = store.rows()
    assert [r.key for r in rows] == ["4711"]
    assert rows[0].item_id == "fake-4711"
    assert store.last_poll() is not None and store.last_poll()["registered"] == 1  # type: ignore[index]


def test_a_missing_or_corrupt_state_file_reads_as_empty_rather_than_raising(tmp_path: Path) -> None:
    store = sv.IntakeStore(tmp_path, "alpha")
    assert store.rows() == []
    store.dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not json", encoding="utf-8")
    assert store.rows() == []


# --- the outcome map ----------------------------------------------------------------------


def _merged_delivery(home: FactoryHome) -> None:
    ev = home.evidence(actor="test")
    ev.append("delivery.merged", "fake-4711", pr_url="https://pr/1")


def test_an_empty_outcome_map_moves_no_ticket(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    _merged_delivery(home)
    assert sv.apply_outcome_map(tracker, home=home, outcome_map={}, evidence=home.evidence()) == []
    assert tracker.states == {}


def test_a_configured_outcome_map_moves_the_ticket_once_and_records_it(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    _merged_delivery(home)
    moved = sv.apply_outcome_map(
        tracker, home=home, outcome_map={"merged": "Done"}, evidence=home.evidence(actor="x")
    )
    assert moved == ["4711"] and tracker.states["4711"] == "Done"
    assert sv.EV_TRANSITIONED in [e.kind for e in home.events()]
    # a second sweep does nothing: the transition is on the chain
    again = sv.apply_outcome_map(
        tracker, home=home, outcome_map={"merged": "Done"}, evidence=home.evidence(actor="x")
    )
    assert again == []


def test_a_workflow_that_refuses_the_transition_is_recorded_not_forced(home: FactoryHome) -> None:
    class RefusesTransition(FakeTracker):
        def transition(self, key: str, state: str) -> None:
            raise c.TrackerError(c.REASON_REFUSED, "no such transition")

    tracker = RefusesTransition({"4711": _ticket()})
    tracker.column = [c.TicketRef(key="4711", revision="1", changed="2026-09-22")]
    _poll(home, tracker, route=_deliver())
    _merged_delivery(home)
    assert (
        sv.apply_outcome_map(
            tracker, home=home, outcome_map={"merged": "Done"}, evidence=home.evidence(actor="x")
        )
        == []
    )
    assert tracker.states == {}
    stops = [e for e in home.events() if e.kind == sv.EV_STOPPED]
    assert stops and stops[-1].payload["step"] == "transition"


# --- the later comments -------------------------------------------------------------------


def test_the_pull_request_link_is_posted_on_the_ticket_and_recorded(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    ev = home.evidence(actor="x")
    assert sv.post_delivery(
        tracker, "4711", "fake-4711", "https://github.invalid/pr/7", evidence=ev
    )
    assert "https://github.invalid/pr/7" in "".join(tracker.comments["4711"].values())
    assert sv.EV_DELIVERED in [e.kind for e in home.events()]


def test_a_refusal_comment_carries_the_served_way_forward(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    assert sv.post_refusal(
        tracker,
        "4711",
        "fake-4711",
        status="no_oracle",
        reason="no test",
        way_forward="Register an evolution carrying the acceptance test.",
        url="https://crb.invalid/factory?item=fake-4711",
        evidence=home.evidence(actor="x"),
    )
    body = "".join(tracker.comments["4711"].values())
    assert "Register an evolution carrying the acceptance test." in body


# --- the pull request and the refusal, told to the ticket --------------------------------


def test_the_pull_request_link_reaches_the_ticket_it_came_from(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    home.evidence(actor="run").append(
        "delivery.opened", "fake-4711", pr_url="https://github.invalid/o/r/pull/7"
    )
    written = sv.post_outcomes_to_tickets(
        tracker,
        home=home,
        item_url=lambda i: f"https://crb.invalid/factory?item={i}",
        evidence=home.evidence(actor="worker"),
    )
    assert written == ["4711"]
    assert "https://github.invalid/o/r/pull/7" in "".join(tracker.comments["4711"].values())
    # and it is told once, however often the poll runs
    assert (
        sv.post_outcomes_to_tickets(
            tracker,
            home=home,
            item_url=lambda i: f"https://crb.invalid/factory?item={i}",
            evidence=home.evidence(actor="worker"),
        )
        == []
    )


def test_a_stopped_item_tells_its_ticket_the_status_and_the_way_forward(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    home.evidence(actor="run").append(
        "item.outcome", "fake-4711", status="no_oracle", error="no authored test"
    )
    assert sv.post_outcomes_to_tickets(
        tracker,
        home=home,
        item_url=lambda i: f"https://crb.invalid/factory?item={i}",
        evidence=home.evidence(actor="worker"),
    ) == ["4711"]
    body = "".join(tracker.comments["4711"].values())
    assert "no_oracle" in body
    assert "supersedes this one" in body


def test_an_accepted_item_is_not_told_it_was_refused(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    ev = home.evidence(actor="run")
    ev.append("item.outcome", "fake-4711", status="not_ready", error="a gap")
    ev.append("item.outcome", "fake-4711", status="accepted", error="")
    assert (
        sv.post_outcomes_to_tickets(
            tracker,
            home=home,
            item_url=lambda i: f"https://crb.invalid/factory?item={i}",
            evidence=home.evidence(actor="worker"),
        )
        == []
    )


def test_only_the_latest_item_registered_from_a_ticket_writes_its_refusal(
    home: FactoryHome,
) -> None:
    """A refusal is one comment per TICKET (marker ``<key>:refusal``), and its once-only guard
    covers deliveries, not refusals. An item and its evolution both stopped therefore wrote
    that ONE comment twice on every poll — the superseded item's refusal onto somebody's
    ticket, then the live one over it. What this product writes on a ticket is counted and
    bounded (ADR-0017), and a write nobody asked for is not in the count. Only the latest item
    registered from a ticket speaks for it; the superseded stop stays on the chain."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())  # registers fake-4711
    tracker.tickets["4711"] = _ticket(revision="5", title="Add a POST /health route (revised)")
    tracker.column = [c.TicketRef(key="4711", revision="5", changed="2026-09-24")]
    _poll(home, tracker, route=_deliver())  # registers fake-4711.r5, superseding it
    ev = home.evidence(actor="run")
    ev.append("item.outcome", "fake-4711", status="not_ready", error="the first stop")
    ev.append("item.outcome", "fake-4711.r5", status="no_oracle", error="the live stop")

    marker = c.marker_for("fake", "4711:refusal")
    for _ in range(2):  # twice: a poll runs this every pass
        before = len(tracker.calls)
        written = sv.post_outcomes_to_tickets(
            tracker,
            home=home,
            item_url=lambda i: f"https://crb.invalid/factory?item={i}",
            evidence=home.evidence(),
        )
        writes = [verb for verb, key in tracker.calls[before:] if verb == "comment"]
        assert writes == ["comment"]  # ONE write, not one per item the ticket ever produced
        assert written == ["4711"]
        assert "the live stop" in tracker.comments["4711"][marker]
        assert "the first stop" not in tracker.comments["4711"][marker]


def test_a_ticket_with_a_pull_request_is_told_about_that_rather_than_an_earlier_stop(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    ev = home.evidence(actor="run")
    ev.append("item.outcome", "fake-4711", status="not_ready", error="a gap")
    ev.append("delivery.opened", "fake-4711", pr_url="https://github.invalid/pr/9")
    sv.post_outcomes_to_tickets(
        tracker,
        home=home,
        item_url=lambda i: f"https://crb.invalid/factory?item={i}",
        evidence=home.evidence(),
    )
    body = "".join(tracker.comments["4711"].values())
    assert "https://github.invalid/pr/9" in body
    assert "not_ready" not in body


def test_a_forced_re_read_of_a_registered_ticket_re_posts_without_registering_again(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    tracker.comments["4711"].clear()
    report = _poll(home, tracker, route=_deliver(), force=True)
    assert report.read == 1 and report.registered == 0
    # the comment is back, the item is untouched, and nothing was recorded as a stop
    assert c.marker_for("fake", "4711") in tracker.comments["4711"]
    assert report.rows[0].registered is True
    assert report.rows[0].label == c.LABEL_QUEUED
    assert [e.kind for e in home.events() if e.kind == sv.EV_STOPPED] == []


# --- what a ticket already registered is owed ------------------------------------------


def test_a_re_read_of_a_registered_ticket_re_asserts_the_label_the_board_should_show(
    home: FactoryHome,
) -> None:
    """The row said queued and registered; the BOARD said `crb:ready`, for ever. Nothing
    pinned the label, so the screen and the customer's own ticket disagreed permanently."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    tracker.labels["4711"] = c.LABEL_READY  # as an earlier poll left it
    report = _poll(home, tracker, route=_deliver(), force=True)
    assert tracker.labels["4711"] == c.LABEL_QUEUED
    assert report.rows[0].label == c.LABEL_QUEUED and report.rows[0].registered is True


def test_a_queued_note_that_failed_once_is_repaired_by_the_next_read(home: FactoryHome) -> None:
    """The tracker was briefly unreachable when the queued note was posted. The item IS
    registered, so the next poll must not register it again — and must still finish telling
    the ticket what happened to it."""
    tracker = _tracker(_ticket())
    queued_marker = c.marker_for("fake", "4711:queued")

    def fail_the_queued_note(verb: str, what: str) -> c.TrackerError | None:
        if verb == "comment" and what == queued_marker:
            return c.TrackerError(c.REASON_UNREACHABLE, "the tracker did not answer")
        return None

    tracker.fail_when = fail_the_queued_note
    first = _poll(home, tracker, route=_deliver())
    assert first.registered == 1
    assert queued_marker not in tracker.comments["4711"]
    assert tracker.links.get("4711") is None

    tracker.fail_when = None
    second = _poll(home, tracker, route=_deliver(), force=True)
    assert second.registered == 0  # the item is on the frozen record; it is not registered twice
    assert queued_marker in tracker.comments["4711"]
    assert tracker.links["4711"] == ["https://crb.invalid/factory?item=fake-4711"]
    assert tracker.labels["4711"] == c.LABEL_QUEUED


def test_a_link_this_product_attaches_is_named_by_what_it_points_at(home: FactoryHome) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    assert tracker.link_titles["https://crb.invalid/factory?item=fake-4711"] == c.LINK_ITEM


# --- the served view is a cache, and the poll rebuilds it -------------------------------


def test_the_served_view_is_written_by_the_poll_itself(home: FactoryHome) -> None:
    """Not by each caller in turn: a poll whose caller was killed before its own write left
    the screen showing a ticket it had already commented on as unread."""
    report = _poll(home, _tracker(_ticket()), route=_deliver())
    rows = sv.store_for(home).rows()
    assert [r.key for r in rows] == ["4711"]
    assert sv.store_for(home).last_poll() == report.to_dict()


def test_deleting_the_state_file_is_survivable_because_the_next_poll_rebuilds_it(
    home: FactoryHome,
) -> None:
    """The docstring's promise, pinned. The chain stays the record: the item is not
    registered again and the ticket is not written to, because every write is idempotent."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    sv.store_for(home).path.unlink()
    before = dict(tracker.comments["4711"])
    report = _poll(home, tracker, route=_deliver())
    assert [r.key for r in report.rows] == ["4711"]
    assert [r.key for r in sv.store_for(home).rows()] == ["4711"]
    assert report.registered == 0
    assert tracker.comments["4711"] == before  # identical text: the board is untouched
    assert len(home.load_backlog().items) == 1  # type: ignore[union-attr]


# --- one pass is bounded ---------------------------------------------------------------


def _column_of(n: int) -> FakeTracker:
    tickets = {str(i): _ticket(key=str(i)) for i in range(n)}
    t = FakeTracker(tickets)
    t.column = [
        c.TicketRef(key=k, revision="1", title=v.title, changed="2026-09-22")
        for k, v in tickets.items()
    ]
    return t


def test_a_column_bigger_than_one_pass_may_read_stops_rather_than_walking_it(
    home: FactoryHome,
) -> None:
    """A pass costs about eleven tracker calls per ticket and holds the worker's heartbeat
    and an API thread. Reading an arbitrary 200 of somebody's board and saying nothing about
    the rest would be worse than reading none of it, so nothing is read."""
    tracker = _column_of(5)
    report = _poll(home, tracker, route=_deliver(), max_tickets=4)
    assert report.stopped == c.REASON_COLUMN_TOO_LARGE
    assert report.seen == 5 and report.read == 0 and report.rows == []
    assert "Narrow the area path" in report.to_dict()["advice"]
    assert tracker.calls == [("entered", "Ready")]  # not one ticket was read
    stop = [e for e in home.events() if e.kind == sv.EV_STOPPED][-1]
    assert stop.payload["reason"] == c.REASON_COLUMN_TOO_LARGE
    assert stop.payload["max_per_poll"] == 4


def test_a_pass_that_runs_out_of_time_serves_what_it_has_and_says_so(home: FactoryHome) -> None:
    tracker = _column_of(3)

    # time runs out the moment the first ticket has been told everything (its link is the
    # last write): the pass then stops before the second one rather than walking the column
    def clock() -> float:
        return 99.0 if ("link", "0") in tracker.calls else 0.0

    report = _poll(home, tracker, route=_deliver(), budget_s=10.0, clock=clock)
    assert report.stopped == c.REASON_COLUMN_TOO_LARGE
    assert report.read == 1 and len(report.rows) == 1  # what it got through is served
    assert "1 of 3 tickets" in report.detail
    assert "the next pass" in report.detail
    assert [k for verb, k in tracker.calls if verb == "read"] == ["0"]  # ticket 1 only


def test_a_budget_that_runs_out_inside_a_ticket_starts_no_further_tracker_call(
    home: FactoryHome,
) -> None:
    """The budget was checked only BETWEEN tickets. One ticket costs about eleven synchronous
    tracker calls, each with its own 20-second timeout, so a single ticket could hold this
    request — and its database session — for minutes against a 60-second budget. The check is
    at the tracker boundary now: an expired pass starts no further call, records the stop it
    already has a word for, and leaves the rest to the next pass. It cannot cancel a call
    already in flight, so the bound is the budget plus the verb in progress."""
    tracker = _tracker(_ticket())

    def clock() -> float:  # expired as soon as the ticket has been read
        return 99.0 if ("read", "4711") in tracker.calls else 0.0

    report = _poll(home, tracker, route=_deliver(), budget_s=10.0, clock=clock)
    assert [verb for verb, _ in tracker.calls] == ["entered", "read"]  # not one write
    row = report.rows[0]
    assert row.stopped == c.REASON_COLUMN_TOO_LARGE and row.stopped_advice
    assert report.registered == 0 and home.load_backlog() is None
    stops = [e for e in home.events() if e.kind == sv.EV_STOPPED]
    ticket_stop = [e for e in stops if e.payload.get("step") == "feedback"][-1]
    assert "budget" in ticket_stop.payload["detail"]
    assert "next pass" in ticket_stop.payload["detail"]


def test_a_budget_that_runs_out_inside_the_last_ticket_stops_the_pass_not_only_the_row(
    home: FactoryHome,
) -> None:
    """A one-ticket column, the budget gone the moment that ticket has been read.

    The stop used to reach the ROW and stop there: ``_handle_ticket`` catches the budget
    error, and the pass-level stop was set only by the check at the top of the NEXT
    iteration, which a one-ticket column never runs. The pass then reported nothing
    stopped — so the served view, `/health`'s intake line and the screen all read ``ok``
    on a pass that had run out of time, and OPERATOR §11's "records the same reason with
    how far it got" was not true of the last ticket.
    """
    tracker = _tracker(_ticket())

    def clock() -> float:  # expired as soon as the one ticket has been read
        return 99.0 if ("read", "4711") in tracker.calls else 0.0

    report = _poll(home, tracker, route=_deliver(), budget_s=10.0, clock=clock)
    assert report.stopped == c.REASON_COLUMN_TOO_LARGE
    assert not report.ok
    assert "inside ticket 1 of 1" in report.detail and "the next pass" in report.detail
    assert report.rows[0].stopped == c.REASON_COLUMN_TOO_LARGE  # the row still says it too
    pass_stop = [
        e for e in home.events() if e.kind == sv.EV_STOPPED and e.payload.get("step") == "budget"
    ]
    assert len(pass_stop) == 1
    assert pass_stop[0].payload["handled"] == 0 and pass_stop[0].payload["seen"] == 1


def test_a_pass_whose_last_ticket_finished_inside_the_budget_does_not_say_it_stopped(
    home: FactoryHome,
) -> None:
    """The other half of the bound: the stop is reported when the budget CURTAILED a ticket,
    never merely because the clock passed the deadline as the pass finished. A pass that got
    everything done must not read ``stopped`` — that would be a false alarm on the screen and
    a false ``degraded`` on `/health`."""
    tracker = _tracker(_ticket())

    # The clock goes past the deadline the moment the ticket's last tracker write has
    # happened, so a deadline check added AFTER that write fails this control (CodeRabbit on
    # PR #48): a generous call ceiling would keep returning 0.0 and pass either way.
    def clock() -> float:  # inside the budget while the ticket is worked, then long past it
        return 99.0 if tracker.calls and tracker.calls[-1][0] == "link" else 0.0

    report = _poll(home, tracker, route=_deliver(), budget_s=10.0, clock=clock)
    assert report.registered == 1 and report.stopped == "" and report.ok
    assert [e for e in home.events() if e.kind == sv.EV_STOPPED] == []


def test_the_default_bounds_are_the_settings_defaults(home: FactoryHome) -> None:
    """A caller that names no bound is bounded anyway — the same numbers the deployment
    ships with, so a test can never exercise an unbounded pass the product cannot make."""
    from crb.server.settings import IntakeSettings

    cfg = IntakeSettings()
    assert cfg.max_per_poll == sv.DEFAULT_MAX_PER_POLL
    assert float(cfg.poll_budget_s) == sv.DEFAULT_POLL_BUDGET_S


# --- a link a reader cannot open is worse than no link ---------------------------------


def test_a_deployment_that_does_not_know_its_own_address_writes_nothing(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    report = _poll(home, tracker, route=_deliver(), item_url=sv.item_url_for("", "alpha"))
    assert report.stopped == c.REASON_NO_PUBLIC_URL
    assert report.read == 0 and tracker.calls == []
    assert "CRB_PUBLIC_URL" in report.to_dict()["advice"]


def test_the_url_a_ticket_is_given_is_absolute_and_escaped() -> None:
    build = sv.item_url_for("https://crb.example.com/", "alpha/beta")
    url = build("fake-4711")
    assert url == "https://crb.example.com/factory?repo=alpha%2Fbeta&item=fake-4711"
    assert sv.is_absolute_url(url)
    assert not sv.is_absolute_url(sv.item_url_for("", "alpha")("fake-4711"))


# --- one unmappable ticket costs that ticket and nothing else --------------------------


def test_a_ticket_whose_key_cannot_become_an_item_id_skips_only_itself(
    home: FactoryHome,
) -> None:
    """``poll_repository`` promises never to raise and that the rest of the column is still
    served. A key with no character an item id may use used to propagate a ValueError out of
    the whole pass: no stop event, no state file, every other ticket unread."""
    good = _ticket(key="4711")
    bad = _ticket(key="!!!")
    tracker = FakeTracker({"!!!": bad, "4711": good})
    tracker.column = [
        c.TicketRef(key="!!!", revision="1", title=bad.title, changed="2026-09-22"),
        c.TicketRef(key="4711", revision="1", title=good.title, changed="2026-09-22"),
    ]
    report = _poll(home, tracker, route=_deliver())
    assert report.seen == 2 and report.read == 1 and report.skipped == 1
    assert [r.key for r in report.rows] == ["!!!", "4711"]
    assert report.rows[0].stopped == c.REASON_REFUSED and report.rows[0].stopped_advice
    assert report.rows[1].registered is True
    stops = [e for e in home.events() if e.kind == sv.EV_STOPPED]
    assert [e.payload["step"] for e in stops] == ["draft"]


# --- C6 (assessment 2026-09-25): an operator approves the draft; the pass takes a lease ---


def test_a_ready_ticket_is_not_registered_until_an_operator_approves_it(
    home: FactoryHome,
) -> None:
    """C6(a): a ticket whose slots are filled was registered and queued with no human step,
    so anyone who could edit a ticket in the watched column could put work — and its text —
    into the factory. By default (``ApprovalPolicy()``, the setting's default too) a ready
    ticket lands as a DRAFT awaiting an operator's Register act: labelled ready, nothing on
    the frozen record, the draft on the chain for the act to register."""
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    report = sv.poll_repository(
        "alpha",
        tracker=tracker,
        listener=sv.ListenerState(enabled=True),
        column="Ready",
        home=home,
        route_for=lambda item: _deliver(),
        item_url=lambda item_id: f"https://crb.invalid/factory?item={item_id}",
    )
    assert report.ok and report.read == 1 and report.registered == 0 and report.awaiting == 1
    assert home.load_backlog() is None
    assert tracker.labels["4711"] == c.LABEL_READY
    assert "4711" not in tracker.links
    (row,) = report.rows
    assert row.awaiting_approval and not row.registered and row.author == "mallory@example.invalid"
    kinds = [e.kind for e in home.events()]
    assert sv.EV_AWAITING in kinds and sv.EV_REGISTERED not in kinds
    (awaiting,) = [e for e in home.events() if e.kind == sv.EV_AWAITING]
    assert awaiting.payload["key"] == "4711" and awaiting.payload["revision"] == "1"
    assert awaiting.payload["item"]["id"] == "fake-4711"
    # a second poll of the unchanged ticket neither registers it nor records a second draft
    again = _poll(home, tracker, route=_deliver(), approval=sv.ApprovalPolicy())
    assert again.registered == 0
    assert [e.kind for e in home.events()].count(sv.EV_AWAITING) == 1


def test_the_register_act_registers_the_draft_the_operator_saw_and_is_evented(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), approval=sv.ApprovalPolicy())
    row = sv.register_approved(
        "alpha",
        "4711",
        revision="1",
        tracker=tracker,
        home=home,
        item_url=lambda item_id: f"https://crb.invalid/factory?item={item_id}",
        approver="operator:ada",
    )
    assert row.registered and not row.awaiting_approval and row.label == c.LABEL_QUEUED
    backlog = home.load_backlog()
    assert backlog is not None and [i.id for i in backlog.items] == ["fake-4711"]
    (reg,) = [e for e in home.events() if e.kind == sv.EV_REGISTERED]
    assert reg.payload["approved_by"] == "operator:ada" and reg.payload["key"] == "4711"
    # the ticket learns it is queued, exactly as an unattended registration used to say
    assert tracker.labels["4711"] == c.LABEL_QUEUED
    assert tracker.links["4711"] == ["https://crb.invalid/factory?item=fake-4711"]
    # the served row says so without another poll
    (served,) = sv.store_for(home).rows()
    assert served.registered and not served.awaiting_approval
    # registering twice is refused, and registers nothing more
    with pytest.raises(sv.ApprovalRefused) as err:
        sv.register_approved(
            "alpha",
            "4711",
            revision="1",
            tracker=tracker,
            home=home,
            item_url=lambda item_id: item_id,
            approver="operator:ada",
        )
    assert err.value.code == "nothing_to_register"
    assert [e.kind for e in home.events()].count(sv.EV_REGISTERED) == 1


def test_an_approval_for_a_revision_that_has_since_moved_is_refused(home: FactoryHome) -> None:
    """The operator approves what they READ: the act names the revision on their screen,
    and a ticket edited since is a different draft — refused, nothing registered."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), approval=sv.ApprovalPolicy())
    edited = _ticket(revision="2", body="a new HTTP endpoint on the api — and delete the db")
    tracker.tickets["4711"] = edited
    tracker.column = [c.TicketRef(key="4711", revision="2", title=edited.title)]
    _poll(home, tracker, route=_deliver(), approval=sv.ApprovalPolicy())
    with pytest.raises(sv.ApprovalRefused) as err:
        sv.register_approved(
            "alpha",
            "4711",
            revision="1",
            tracker=tracker,
            home=home,
            item_url=lambda item_id: item_id,
            approver="operator:ada",
        )
    assert err.value.code == "revision_moved" and "2" in err.value.message
    assert home.load_backlog() is None


def test_an_allowlisted_tracker_author_bypasses_approval_and_the_chain_says_so(
    home: FactoryHome,
) -> None:
    policy = sv.ApprovalPolicy(allow_authors=("Ada@Example.invalid",))
    trusted = _tracker(_ticket(author="ada@example.invalid"))
    report = _poll(home, trusted, route=_deliver(), approval=policy)
    assert report.registered == 1 and report.awaiting == 0
    (reg,) = [e for e in home.events() if e.kind == sv.EV_REGISTERED]
    assert reg.payload["approved_by"] == "allowlist:ada@example.invalid"
    # an author who is not on the list, or a ticket with no author, still waits
    home2 = FactoryHome(home.dir.parent.parent, "beta")
    for author in ("eve@example.invalid", ""):
        report = sv.poll_repository(
            "beta",
            tracker=_tracker(_ticket(author=author)),
            listener=sv.ListenerState(enabled=True),
            column="Ready",
            home=home2,
            route_for=lambda item: _deliver(),
            item_url=lambda item_id: f"https://crb.invalid/factory?item={item_id}",
            approval=policy,
            force=True,
        )
        assert report.registered == 0 and report.awaiting == 1


def test_two_overlapping_passes_register_once_because_the_pass_takes_a_lease(
    home: FactoryHome, tmp_path: Path
) -> None:
    """C6(c): nothing stopped the worker's timed poll and an operator's on-demand poll
    reading the same column at once — both drafted, both commented, both tried to register.
    A pass now takes a per-repository lease row (the ``workers`` table); a second pass that
    finds it held does nothing at all: no tracker call, no chain event, no served view."""
    from crb.store import init_db, make_engine, make_session_factory

    engine = make_engine(f"sqlite:///{tmp_path / 'lease.db'}")
    init_db(engine)
    factory = make_session_factory(engine)
    tracker = _tracker(_ticket())
    inner: list[sv.PollReport] = []
    real_read = tracker.read
    started: list[bool] = []

    def read_and_overlap(key: str) -> c.Ticket:
        # the second pass starts while the first is inside the ticket (once)
        if started:
            return real_read(key)
        started.append(True)
        inner.append(
            _poll(
                home,
                tracker,
                route=_deliver(),
                approval=sv.ApprovalPolicy(required=False),
                lease=sv.intake_lease(factory, "alpha", ttl_s=300),
            )
        )
        return real_read(key)

    tracker.read = read_and_overlap  # type: ignore[method-assign]
    outer = _poll(
        home,
        tracker,
        route=_deliver(),
        approval=sv.ApprovalPolicy(required=False),
        lease=sv.intake_lease(factory, "alpha", ttl_s=300),
    )
    (second,) = inner
    assert second.busy and second.read == 0 and second.registered == 0 and not second.rows
    assert outer.registered == 1
    kinds = [e.kind for e in home.events()]
    assert kinds.count(sv.EV_REGISTERED) == 1 and kinds.count(sv.EV_POLLED) == 1
    assert not [e for e in home.events() if e.kind == sv.EV_STOPPED]
    # the lease is released when the pass ends: the next pass runs
    tracker.read = real_read  # type: ignore[method-assign]
    third = _poll(
        home,
        tracker,
        route=_deliver(),
        approval=sv.ApprovalPolicy(required=False),
        lease=sv.intake_lease(factory, "alpha", ttl_s=300),
    )
    assert not third.busy and third.skipped == 1


def test_a_lease_left_by_a_crashed_pass_expires(tmp_path: Path) -> None:
    from crb.store import init_db, make_engine, make_session_factory

    engine = make_engine(f"sqlite:///{tmp_path / 'lease.db'}")
    init_db(engine)
    factory = make_session_factory(engine)
    clock = [1000.0]
    a = sv.intake_lease(factory, "alpha", ttl_s=60, clock=lambda: clock[0])
    b = sv.intake_lease(factory, "alpha", ttl_s=60, clock=lambda: clock[0])
    assert a.acquire() and not b.acquire()
    clock[0] += 61  # the holder died without releasing
    assert b.acquire()
    a.release()  # a stale holder cannot release a lease it no longer holds
    c2 = sv.intake_lease(factory, "alpha", ttl_s=60, clock=lambda: clock[0])
    assert not c2.acquire()
    b.release()
    assert c2.acquire()


# --- PR #55 review: no public writer lets a relative link reach a ticket -----------------

#: A builder that marks every link it makes, so a test can look for it on the board.
_DEAD = "/NOT-ABSOLUTE"


def _relative(item_id: str) -> str:
    return f"{_DEAD}/factory?item={item_id}"


def _on_the_board(tracker: FakeTracker) -> list[str]:
    """Every comment and link this product has written on the fake board."""
    return [text for by_marker in tracker.comments.values() for text in by_marker.values()] + [
        url for urls in tracker.links.values() for url in urls
    ]


def _scenario_poll(home: FactoryHome) -> FakeTracker:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), item_url=_relative)
    return tracker


def _scenario_register(home: FactoryHome) -> FakeTracker:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), approval=sv.ApprovalPolicy())  # a draft waits
    with pytest.raises(sv.ApprovalRefused) as err:
        sv.register_approved(
            "alpha",
            "4711",
            revision="1",
            tracker=tracker,
            home=home,
            item_url=_relative,
            approver="operator:ada",
        )
    assert err.value.code == c.REASON_NO_PUBLIC_URL
    assert "CRB_PUBLIC_URL" in err.value.message
    assert home.load_backlog() is None  # refused before the frozen record was touched
    assert sv.EV_REGISTERED not in [e.kind for e in home.events()]
    return tracker


def _scenario_outcomes(home: FactoryHome) -> FakeTracker:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())  # registered, with an absolute link
    home.evidence(actor="run").append(
        "item.outcome", "fake-4711", status="no_oracle", error="no authored test"
    )
    sv.post_outcomes_to_tickets(
        tracker, home=home, item_url=_relative, evidence=home.evidence(actor="worker")
    )
    return tracker


#: Every public function in ``crb.server.intake`` that takes an ``item_url`` builder, with
#: a scenario that hands it a RELATIVE one after whatever state it needs.
_ITEM_URL_WRITERS = {
    "poll_repository": _scenario_poll,
    "register_approved": _scenario_register,
    "post_outcomes_to_tickets": _scenario_outcomes,
}


def test_the_register_act_refuses_a_relative_link_before_any_write(home: FactoryHome) -> None:
    """PR #55 review: the Register act had no address check of its own, so a deployment
    that lost ``CRB_PUBLIC_URL`` after the switch wrote ``crb:queued``, a comment and a link
    that all pointed nowhere. It is refused, and nothing after the poll reaches the board."""
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver(), approval=sv.ApprovalPolicy())
    before = list(tracker.calls)
    with pytest.raises(sv.ApprovalRefused) as err:
        sv.register_approved(
            "alpha",
            "4711",
            revision="1",
            tracker=tracker,
            home=home,
            item_url=sv.item_url_for("", "alpha"),
            approver="operator:ada",
        )
    assert err.value.code == c.REASON_NO_PUBLIC_URL
    assert tracker.calls == before
    assert home.load_backlog() is None


@pytest.mark.parametrize("name", sorted(_ITEM_URL_WRITERS))
def test_no_writer_puts_a_relative_link_on_a_ticket(name: str, tmp_path: Path) -> None:
    """The prevention for the class: whichever function is handed a relative builder, no
    comment and no link it writes carries that link."""
    tracker = _ITEM_URL_WRITERS[name](FactoryHome(tmp_path, "alpha"))
    assert [text for text in _on_the_board(tracker) if _DEAD in text] == []


def test_every_public_function_that_takes_an_item_url_is_held_to_the_absolute_rule() -> None:
    """The ratchet: a new public function that takes an ``item_url`` builder fails here until
    it has a scenario in ``_ITEM_URL_WRITERS`` — so the next writer cannot be the one that
    forgets the check."""
    import inspect

    takers = {
        name
        for name, fn in vars(sv).items()
        if inspect.isfunction(fn)
        and fn.__module__ == sv.__name__
        and not name.startswith("_")
        and "item_url" in inspect.signature(fn).parameters
    }
    assert takers == set(_ITEM_URL_WRITERS)
