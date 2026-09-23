"""The one in-memory tracker the intake suites share, and a minimal valid ticket.

Navigation
----------
What it is:   ``FakeTracker`` — an in-memory implementation of the six-verb
              ``crb.intake.client.TrackerClient`` protocol — and ``a_ticket``, a minimal
              valid ``Ticket`` whose fields a keyword overrides.
What it does: Gives the protocol, draft, feedback, service and route suites ONE fake, so a
              change to the protocol breaks every consumer at once instead of drifting per
              suite; records every write in memory so a test can assert what reached the
              ticket, and raises a seeded ``TrackerError`` from every verb so a refusal path
              is exercised without a network.
How:          Plain classes in the ``fixtures`` package, imported as ``from fixtures.intake
              import FakeTracker`` — the same idiom as ``fixtures.pyrepo``; a test module is
              never imported by another test module, because pytest's import mode puts
              ``tests/`` on ``sys.path`` and not the repository root.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the protocol it implements), tests/test_intake_client.py
              (proves the fake satisfies the protocol at runtime), tests/test_intake_draft.py and
              tests/test_intake_feedback.py (``a_ticket``), tests/test_intake_service.py (drives
              the service against this fake), tests/fixtures/__init__.py (the package marker)
Tested by:    tests/test_intake_client.py
Touch when:   a verb is added to the protocol — add it here first, then the adapters; never add
              behaviour the real adapters do not have, or a suite passes against a fiction.
"""

from __future__ import annotations

from collections.abc import Callable

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
        #: url → the name the link was given ("Backlog item" / "Pull request").
        self.link_titles: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        #: Raised by EVERY verb — the blunt instrument, for "the tracker is unreachable".
        self.fail: c.TrackerError | None = None
        #: ``(verb, what) -> TrackerError | None`` — raised by that one call, so a test can
        #: fail exactly one write (the queued comment, say) and let the rest of the poll
        #: through, which is how a real tracker fails. ``what`` is the marker for a comment
        #: and the ticket key for every other verb.
        self.fail_when: Callable[[str, str], c.TrackerError | None] | None = None

    def _maybe_fail(self, verb: str = "", what: str = "") -> None:
        if self.fail is not None:
            raise self.fail
        if self.fail_when is not None:
            exc = self.fail_when(verb, what)
            if exc is not None:
                raise exc

    def entered(self, column: str, since: str) -> list[c.TicketRef]:
        self._maybe_fail("entered", column)
        self.calls.append(("entered", column))
        return [r for r in self.column if not since or r.changed >= since]

    def read(self, key: str) -> c.Ticket:
        self._maybe_fail("read", key)
        self.calls.append(("read", key))
        try:
            return self.tickets[key]
        except KeyError:
            raise c.TrackerError(c.REASON_REFUSED, f"no ticket {key!r}") from None

    def comment(self, key: str, text: str, marker: str) -> None:
        self._maybe_fail("comment", marker)
        self.calls.append(("comment", key))
        self.comments.setdefault(key, {})[marker] = text

    def label(self, key: str, value: str) -> None:
        self._maybe_fail("label", key)
        self.calls.append(("label", key))
        self.labels[key] = value

    def transition(self, key: str, state: str) -> None:
        self._maybe_fail("transition", key)
        self.calls.append(("transition", key))
        self.states[key] = state

    def link(self, key: str, url: str, title: str = "") -> None:
        self._maybe_fail("link", key)
        self.calls.append(("link", key))
        self.links.setdefault(key, []).append(url)
        self.link_titles[url] = title


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
