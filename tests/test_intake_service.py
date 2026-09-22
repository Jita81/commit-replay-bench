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
              ``intake.stopped`` event with a published reason and advice, and that an
              empty outcome map moves no ticket at all.
How:          A real ``FactoryHome`` under ``tmp_path`` (so the hash chain is the real
              one) plus ``tests/test_intake_client.py``'s ``FakeTracker``. No HTTP, no
              database, no model — the whole flow is exercised in milliseconds.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/server/intake.py (under test), src/crb/server/factory_state.py (the
              ``FactoryHome`` it registers through), src/crb/intake/client.py (the fake's
              protocol), tests/test_intake_client.py (the fake)
Tested by:    tests/test_intake_service.py
Touch when:   a step is added to the poll — pin its idempotency here before its behaviour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.test_intake_client import FakeTracker

from crb.factory.backlog import BacklogItem
from crb.intake import client as c
from crb.server import intake as sv
from crb.server.factory_state import FactoryHome

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
    report = _poll(home, _tracker(_ticket()), route=_deliver())
    row = report.rows[0]
    assert row.capability_class == "backend.route.add"
    assert row.confidence > 0
    assert row.item_url.endswith("item=fake-4711")
    assert row.cell_route is not None and row.cell_route["n"] == 42
    assert "POST /health" not in row.feedback or row.feedback  # the comment text is served


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
        item_url=lambda i: f"/factory?item={i}",
        evidence=home.evidence(actor="worker"),
    )
    assert written == ["4711"]
    assert "https://github.invalid/o/r/pull/7" in "".join(tracker.comments["4711"].values())
    # and it is told once, however often the poll runs
    assert (
        sv.post_outcomes_to_tickets(
            tracker,
            home=home,
            item_url=lambda i: f"/factory?item={i}",
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
        item_url=lambda i: f"/factory?item={i}",
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
            item_url=lambda i: f"/factory?item={i}",
            evidence=home.evidence(actor="worker"),
        )
        == []
    )


def test_a_ticket_with_a_pull_request_is_told_about_that_rather_than_an_earlier_stop(
    home: FactoryHome,
) -> None:
    tracker = _tracker(_ticket())
    _poll(home, tracker, route=_deliver())
    ev = home.evidence(actor="run")
    ev.append("item.outcome", "fake-4711", status="not_ready", error="a gap")
    ev.append("delivery.opened", "fake-4711", pr_url="https://github.invalid/pr/9")
    sv.post_outcomes_to_tickets(
        tracker, home=home, item_url=lambda i: f"/factory?item={i}", evidence=home.evidence()
    )
    body = "".join(tracker.comments["4711"].values())
    assert "https://github.invalid/pr/9" in body
    assert "not_ready" not in body
