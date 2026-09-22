"""Intake — the enterprise's own board is the front door of the factory.

A person moves a ticket into one column on their tracker (Azure DevOps first, Jira
second). The product treats that move as the request to manufacture: it reads the
ticket, drafts a backlog item from it, tells the ticket what is missing *before* any
spend, and registers the item when the gaps close. The ticket is the backlog item;
the column is the consent gate (docs/adr/0017-the-ticket-is-the-backlog-item.md).

Nothing in this package talks to a database, a session or FastAPI: one
:class:`~crb.intake.client.TrackerClient` protocol, two adapters over ``httpx``, a
pure ticket → draft mapping and a pure comment renderer. The server wires them
(:mod:`crb.server.intake`), and the worker polls.

Navigation
----------
What it is:   The intake package — the tracker protocol, its two adapters, the
              ticket → draft mapping and the feedback renderer.
What it does: Re-exports the names the server and the worker use, so a caller writes
              ``from crb.intake import Ticket, draft_from, render_feedback`` and never
              reaches past this door into an adapter.
How:          Plain re-exports; every symbol is defined in one of the four modules.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the protocol and the two dataclasses),
              src/crb/intake/ado.py and src/crb/intake/jira.py (the adapters),
              src/crb/intake/draft.py (ticket → draft item),
              src/crb/intake/feedback.py (the one idempotent comment),
              src/crb/server/intake.py (the service that wires them)
Tested by:    tests/test_intake_client.py, tests/test_intake_draft.py,
              tests/test_intake_feedback.py, tests/test_intake_adapters.py
Touch when:   a third tracker is added — write its adapter beside the other two and
              export it here; never add a vendor SDK (stdlib + httpx only).
"""

from __future__ import annotations

from crb.intake.client import (
    LABEL_NEEDS_INFO,
    LABEL_NOT_DELIVERABLE,
    LABEL_QUEUED,
    LABEL_READY,
    LABELS,
    REASON_COLUMN_GONE,
    REASON_NO_SECRET,
    REASON_REFUSED,
    REASON_UNAUTHORISED,
    REASON_UNREACHABLE,
    Ticket,
    TicketRef,
    TrackerClient,
    TrackerError,
    marker_for,
)
from crb.intake.draft import Classification, Draft, classify, draft_from
from crb.intake.feedback import Feedback, render_feedback

__all__ = [
    "LABELS",
    "LABEL_NEEDS_INFO",
    "LABEL_NOT_DELIVERABLE",
    "LABEL_QUEUED",
    "LABEL_READY",
    "REASON_COLUMN_GONE",
    "REASON_NO_SECRET",
    "REASON_REFUSED",
    "REASON_UNAUTHORISED",
    "REASON_UNREACHABLE",
    "Classification",
    "Draft",
    "Feedback",
    "Ticket",
    "TicketRef",
    "TrackerClient",
    "TrackerError",
    "classify",
    "draft_from",
    "marker_for",
    "render_feedback",
]
