"""crb.intake.client — the tracker protocol, its two dataclasses and its refusal words.

Navigation
----------
What it is:   The protocol layer's test suite: ``TicketRef`` / ``Ticket`` shape and round
              trip, the marker that makes a comment idempotent, the closed label set and
              the closed set of stop reasons a listener may report.
What it does: Pins that a fake implementing the six verbs satisfies ``TrackerClient`` at
              runtime (so an adapter cannot quietly drop a verb), that ``Ticket`` coerces
              every sequence field to a tuple and is hashable, that ``marker_for`` is
              stable for the same (tracker, key) and different for different ones, and
              that ``TrackerError`` carries one of the published reason words.
How:          A ``FakeTracker`` recording every call in memory; no network anywhere.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (under test), tests/test_intake_draft.py and
              tests/test_intake_feedback.py (they import ``FakeTracker`` from here),
              src/crb/intake/ado.py and src/crb/intake/jira.py (the real implementations)
Tested by:    tests/test_intake_client.py
Touch when:   a verb is added to the protocol — add it to ``FakeTracker`` first, then the
              adapters; a new stop reason — publish it in docs/API.md's intake vocabulary.
"""

from __future__ import annotations

import pytest

from crb.intake import client as c


class FakeTracker:
    """An in-memory tracker: every write is recorded, every read is what a test seeded.

    Shared by the draft, feedback, service and route suites — the ONE fake, so a change
    to the protocol breaks every consumer at once instead of drifting per suite.
    """

    name = "fake"

    def __init__(self, tickets: dict[str, c.Ticket] | None = None) -> None:
        self.tickets: dict[str, c.Ticket] = dict(tickets or {})
        self.column: list[c.TicketRef] = []
        self.comments: dict[str, dict[str, str]] = {}  # key → marker → text
        self.labels: dict[str, str] = {}
        self.states: dict[str, str] = {}
        self.links: dict[str, list[str]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail: c.TrackerError | None = None

    def _maybe_fail(self) -> None:
        if self.fail is not None:
            raise self.fail

    def entered(self, column: str, since: str) -> list[c.TicketRef]:
        self._maybe_fail()
        self.calls.append(("entered", column))
        return [r for r in self.column if not since or r.changed >= since]

    def read(self, key: str) -> c.Ticket:
        self._maybe_fail()
        self.calls.append(("read", key))
        try:
            return self.tickets[key]
        except KeyError:
            raise c.TrackerError(c.REASON_REFUSED, f"no ticket {key!r}") from None

    def comment(self, key: str, text: str, marker: str) -> None:
        self._maybe_fail()
        self.calls.append(("comment", key))
        self.comments.setdefault(key, {})[marker] = text

    def label(self, key: str, value: str) -> None:
        self._maybe_fail()
        self.calls.append(("label", key))
        self.labels[key] = value

    def transition(self, key: str, state: str) -> None:
        self._maybe_fail()
        self.calls.append(("transition", key))
        self.states[key] = state

    def link(self, key: str, url: str) -> None:
        self._maybe_fail()
        self.calls.append(("link", key))
        self.links.setdefault(key, []).append(url)


def a_ticket(**kw: object) -> c.Ticket:
    """A minimal valid ticket; keywords override."""
    base: dict[str, object] = {
        "key": "4711",
        "title": "Add a health route",
        "body": "The service needs a health route.",
        "revision": "1",
    }
    base.update(kw)
    return c.Ticket(**base)  # type: ignore[arg-type]


# --- the protocol ----------------------------------------------------------------


def test_a_fake_with_the_six_verbs_satisfies_the_protocol() -> None:
    assert isinstance(FakeTracker(), c.TrackerClient)


def test_an_object_missing_a_verb_does_not_satisfy_the_protocol() -> None:
    class Partial:
        name = "partial"

        def entered(self, column: str, since: str) -> list[c.TicketRef]:
            return []

    assert not isinstance(Partial(), c.TrackerClient)


# --- the dataclasses -------------------------------------------------------------


def test_ticket_coerces_sequences_to_tuples_and_is_hashable() -> None:
    t = c.Ticket(
        key="4711",
        title="t",
        acceptance_criteria=["a", "b"],  # type: ignore[arg-type]
        tags=["area:api"],  # type: ignore[arg-type]
        links=["https://example.invalid/1"],  # type: ignore[arg-type]
        revision="2",
    )
    assert t.acceptance_criteria == ("a", "b")
    assert t.tags == ("area:api",)
    assert t.links == ("https://example.invalid/1",)
    assert hash(t)  # frozen + tuples: usable as a dict key


def test_ticket_round_trips_through_its_dict() -> None:
    t = a_ticket(acceptance_criteria=("given x, then y",), tags=("area:api",), points=3.0)
    assert c.Ticket.from_dict(t.to_dict()) == t


def test_ticket_refuses_a_blank_key() -> None:
    with pytest.raises(ValueError, match="key"):
        c.Ticket(key="  ", title="t")


def test_ticket_ref_round_trips_and_keeps_its_revision_as_text() -> None:
    r = c.TicketRef(key="4711", revision=7, title="t", url="https://x.invalid")  # type: ignore[arg-type]
    assert r.revision == "7"
    assert c.TicketRef.from_dict(r.to_dict()) == r


# --- the marker ------------------------------------------------------------------


def test_marker_is_an_html_comment_stable_per_tracker_and_key() -> None:
    m = c.marker_for("ado", "4711")
    assert m.startswith("<!--") and m.endswith("-->")
    assert m == c.marker_for("ado", "4711")
    assert m != c.marker_for("jira", "4711")
    assert m != c.marker_for("ado", "4712")


def test_marker_survives_a_key_with_punctuation() -> None:
    assert c.marker_for("jira", "ABC-123") == c.marker_for("jira", "ABC-123")
    assert "ABC-123" in c.marker_for("jira", "ABC-123")


# --- labels and stop reasons -----------------------------------------------------


def test_the_label_set_is_closed_and_every_label_is_namespaced() -> None:
    assert set(c.LABELS) == {
        c.LABEL_NEEDS_INFO,
        c.LABEL_READY,
        c.LABEL_NOT_DELIVERABLE,
        c.LABEL_QUEUED,
    }
    assert all(label.startswith("crb:") for label in c.LABELS)


def test_a_tracker_error_carries_a_published_reason_word() -> None:
    err = c.TrackerError(c.REASON_UNREACHABLE, "connect timed out")
    assert err.reason in c.STOP_REASONS
    assert "connect timed out" in str(err)


def test_a_tracker_error_refuses_an_unpublished_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        c.TrackerError("something_went_wrong", "…")
