"""The write bound on somebody else's ticket — counted, per verb and per HTTP call.

Three documents state a bound on what intake writes: ``docs/API.md``'s poll row, ``docs/
SECURITY.md`` §2's tenant-boundary table and ``docs/OPERATOR.md`` §11's *Bounds on one
pass*. Until this suite two of those numbers were prose: the four marked comments were
counted against the renderers (``tests/test_intake_feedback.py``) but nothing counted the
*calls*, so "about eleven tracker calls per ticket" was an estimate nobody could re-derive
and the poll row read as though one comment and one label were the whole of it.

This file counts. It drives the two real adapters through the verb sequence a first pass
makes and counts the HTTP requests each verb costs, and it drives the real service over the
shared fake and counts the distinct markers, labels, links and transitions one ticket can
ever collect. A verb that grows a request, or a poll that starts writing a fifth comment,
fails here before a customer's board learns about it.

Navigation
----------
What it is:   The intake write-bound suite: the per-verb HTTP cost of a first pass and the
              whole-life count of what one ticket is written.
What it does: Pins that a first pass over a one-ticket column ending in registration costs
              ELEVEN Azure DevOps requests and NINE Jira requests; that one poll of a ready
              ticket leaves exactly two marked comments, one ``crb:`` label and one link;
              and that the whole life of a ticket is at most four marked comments, two
              links, one label and one configured state change.
How:          ``httpx.MockTransport`` counts every request the adapter makes (no tracker is
              contacted, here or in CI) for the exact verb sequence ``poll_repository``
              makes; then a real ``FactoryHome`` under ``tmp_path`` plus
              ``fixtures.intake``'s ``FakeTracker``, whose ``calls`` list is the count.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/ado.py and src/crb/intake/jira.py (the per-verb request cost),
              src/crb/server/intake.py (the poll and the later moments it counts),
              src/crb/intake/client.py (the six verbs and the four labels),
              tests/fixtures/intake.py (the fake whose ``calls`` list is the count),
              tests/test_intake_feedback.py (counts the renderers; this counts the calls),
              docs/OPERATOR.md (§11's *Bounds on one pass* cites this file)
Tested by:    tests/test_intake_write_bound.py
Touch when:   an adapter changes how many requests a verb costs, or the poll gains a write —
              change the count here and in docs/API.md, docs/SECURITY.md §2 and
              docs/OPERATOR.md §11 in the same change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from crb.intake import ado, jira
from crb.intake import client as c
from crb.server import intake as sv
from crb.server.factory_state import FactoryHome
from fixtures.intake import FakeTracker

ORG = "https://dev.azure.invalid/contoso"
SITE = "https://contoso.atlassian.invalid"
KEY = "4711"

#: The acceptance criteria that make a ticket ready, so the poll reaches registration and
#: the count is the FULL first pass rather than the needs-info half of it.
READY_AC = (
    "method_path: POST /health",
    "request_shape: no body",
    "response_shape: 200 with {status: string}",
    "error_contract: 503 when a dependency is down",
)


# --- the per-verb HTTP cost of a first pass -----------------------------------------


def _ready_ticket() -> c.Ticket:
    return c.Ticket(
        key=KEY,
        title="Add a POST /health route",
        body="a new HTTP endpoint on the api",
        acceptance_criteria=READY_AC,
        revision="1",
        url=f"https://tracker.invalid/{KEY}",
    )


def _first_pass(tracker: Any, *, key: str) -> None:
    """The verb sequence ``poll_repository`` makes on a ready ticket it registers.

    Read from ``crb.server.intake.poll_repository`` / ``_register_and_queue``: the column,
    the ticket, the readiness comment, the label, the queued note and the item link.
    """
    tracker.entered("Ready for manufacture", "")
    tracker.read(key)
    tracker.comment(key, "what is missing", c.marker_for(tracker.name, key))
    tracker.label(key, c.LABEL_QUEUED)
    tracker.comment(key, "queued", c.marker_for(tracker.name, f"{key}:queued"))
    tracker.link(key, "https://crb.invalid/factory?item=x", c.LINK_ITEM)


def test_a_first_pass_on_one_ready_ticket_costs_eleven_azure_devops_requests() -> None:
    """The number ``docs/OPERATOR.md`` §11 and ``docs/SECURITY.md`` §2 quote.

    Azure DevOps is the dearer of the two because three of its verbs read before they
    write: ``comment`` lists the thread to find its own marker, and ``label`` and ``link``
    both re-read the work item so they leave everybody else's tags and relations alone.
    """
    counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        counts[f"{request.method} {path}"] = counts.get(f"{request.method} {path}", 0) + 1
        if path.endswith("/wiql"):
            return httpx.Response(200, json={"workItems": [{"id": int(KEY)}]})
        if path.endswith("/comments"):
            if request.method == "GET":
                return httpx.Response(200, json={"comments": []})
            return httpx.Response(201, json={})
        if path.endswith("/_apis/wit/workitems"):
            return httpx.Response(
                200, json={"value": [{"id": int(KEY), "fields": {ado.FIELD_TITLE: "x"}}]}
            )
        return httpx.Response(200, json={"id": int(KEY), "fields": {ado.FIELD_TITLE: "x"}})

    tracker = ado.AdoTracker(
        ado.AdoConfig(organisation_url=ORG, project="Widgets", column="Ready for manufacture"),
        "pat-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    _first_pass(tracker, key=KEY)

    assert sum(counts.values()) == 11, counts
    # and WHERE the eleven go, so a reader can check the arithmetic against the adapter
    assert counts["POST /contoso/Widgets/_apis/wit/wiql"] == 1  # the WIQL query
    assert counts["GET /contoso/Widgets/_apis/wit/workitems"] == 1  # the ids batch
    assert counts[f"GET /contoso/Widgets/_apis/wit/workitems/{KEY}"] == 3  # read + label + link
    assert counts[f"GET /contoso/Widgets/_apis/wit/workItems/{KEY}/comments"] == 2  # both markers
    assert counts[f"POST /contoso/Widgets/_apis/wit/workItems/{KEY}/comments"] == 2  # both notes
    assert counts[f"PATCH /contoso/Widgets/_apis/wit/workitems/{KEY}"] == 2  # the tag and the link


def test_the_same_first_pass_costs_nine_jira_requests() -> None:
    """Jira is cheaper: its search is one call and a remote link is idempotent on its own
    ``globalId``, so ``link`` writes without reading first."""
    counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        counts[f"{request.method} {path}"] = counts.get(f"{request.method} {path}", 0) + 1
        if path.endswith("/search/jql"):
            return httpx.Response(200, json={"issues": [{"key": KEY, "fields": {}}]})
        if path.endswith("/comment"):
            if request.method == "GET":
                return httpx.Response(200, json={"comments": []})
            return httpx.Response(201, json={})
        if path.endswith("/remotelink"):
            return httpx.Response(201, json={})
        if request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(200, json={"key": KEY, "fields": {"summary": "x"}})

    tracker = jira.JiraTracker(
        jira.JiraConfig(
            site_url=SITE, project="WID", column="Ready for manufacture", email="b@e.invalid"
        ),
        "api-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    _first_pass(tracker, key=KEY)

    assert sum(counts.values()) == 9, counts
    assert counts["POST /rest/api/3/search/jql"] == 1
    assert counts[f"GET /rest/api/3/issue/{KEY}"] == 2  # read + label's own read
    assert counts[f"GET /rest/api/3/issue/{KEY}/comment"] == 2
    assert counts[f"POST /rest/api/3/issue/{KEY}/comment"] == 2
    assert counts[f"PUT /rest/api/3/issue/{KEY}"] == 1  # the labels update
    assert counts[f"POST /rest/api/3/issue/{KEY}/remotelink"] == 1


# --- what one ticket is ever written ------------------------------------------------


class _Evidence:
    """The append-only recorder ``post_delivery`` / ``post_refusal`` write their steps to."""

    def __init__(self) -> None:
        self.kinds: list[str] = []

    def append(self, kind: str, item_id: str, **payload: Any) -> None:
        self.kinds.append(kind)


@pytest.fixture
def home(tmp_path: Path) -> FactoryHome:
    return FactoryHome(tmp_path, "alpha")


def _tracker() -> FakeTracker:
    ticket = _ready_ticket()
    t = FakeTracker({ticket.key: ticket})
    t.column = [
        c.TicketRef(key=ticket.key, revision=ticket.revision, title=ticket.title, changed="2026")
    ]
    return t


def _poll(home: FactoryHome, tracker: FakeTracker) -> sv.PollReport:
    return sv.poll_repository(
        "alpha",
        tracker=tracker,
        listener=sv.ListenerState(enabled=True),
        column="Ready",
        home=home,
        route_for=lambda item: None,
        item_url=lambda item_id: f"https://crb.invalid/factory?item={item_id}",
    )


def test_one_poll_of_a_ready_ticket_leaves_two_marked_comments_one_label_and_one_link(
    home: FactoryHome,
) -> None:
    """The observation DL-052 records: the sentence that claimed "this one comment" was
    already contradicted by the first pass, which leaves the readiness feedback AND the
    queued note, and attaches the backlog item."""
    tracker = _tracker()
    report = _poll(home, tracker)

    assert report.registered == 1
    assert sorted(tracker.comments[KEY]) == sorted(
        [c.marker_for("fake", KEY), c.marker_for("fake", f"{KEY}:queued")]
    )
    assert len(tracker.comments[KEY]) == 2
    assert tracker.labels[KEY] == c.LABEL_QUEUED
    assert tracker.links[KEY] == ["https://crb.invalid/factory?item=fake-4711"]
    assert tracker.states == {}  # nothing is moved without a configured outcome map
    assert [verb for verb, _ in tracker.calls].count("comment") == 2


def test_the_whole_life_of_a_ticket_is_four_comments_two_links_one_label_one_transition(
    home: FactoryHome,
) -> None:
    """The bound docs/API.md, docs/SECURITY.md §2 and the ticket's own comment all state.

    A poll, then the two later moments (the pull request and a stop), then the configured
    transition: four distinct markers and no fifth, both links, one ``crb:`` label at a
    time out of the four that exist, and one state change.
    """
    tracker = _tracker()
    _poll(home, tracker)
    evidence = _Evidence()
    assert sv.post_delivery(
        tracker, KEY, "fake-4711", "https://github.invalid/o/r/pull/7", evidence=evidence
    )
    assert sv.post_refusal(
        tracker,
        KEY,
        "fake-4711",
        status="not_red",
        reason="the authored test did not fail at the base",
        way_forward="answer on the ticket",
        url="https://crb.invalid/factory?item=fake-4711",
        evidence=evidence,
    )
    tracker.transition(KEY, "Done")

    assert sorted(tracker.comments[KEY]) == sorted(
        [
            c.marker_for("fake", KEY),
            c.marker_for("fake", f"{KEY}:queued"),
            c.marker_for("fake", f"{KEY}:pr"),
            c.marker_for("fake", f"{KEY}:refusal"),
        ]
    )
    assert len(tracker.comments[KEY]) == 4
    assert tracker.links[KEY] == [
        "https://crb.invalid/factory?item=fake-4711",
        "https://github.invalid/o/r/pull/7",
    ]
    assert tracker.labels[KEY] == c.LABEL_QUEUED and len(c.LABELS) == 4
    assert tracker.states == {KEY: "Done"}
    assert [verb for verb, _ in tracker.calls].count("transition") == 1


def test_a_repeat_of_a_later_write_adds_no_fifth_comment(home: FactoryHome) -> None:
    """The bound is per ticket, not per pass: the marker is the identity, so the same note
    posted again is the same comment. (Only the comments are counted here — the fake keeps
    every link it is handed; the two real adapters de-duplicate a link on its URL, which
    ``tests/test_intake_adapters.py`` pins.)"""
    tracker = _tracker()
    _poll(home, tracker)
    evidence = _Evidence()
    for _ in range(3):
        sv.post_delivery(
            tracker, KEY, "fake-4711", "https://github.invalid/o/r/pull/7", evidence=evidence
        )
    assert len(tracker.comments[KEY]) == 3
