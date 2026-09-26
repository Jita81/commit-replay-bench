"""One protocol every tracker speaks, and the two shapes it speaks in.

The product knows six verbs, and no more: read the column, read a ticket, leave one
comment, set one label, make one state transition, attach one link. Everything a
tracker can do beyond those six is deliberately out of reach — the non-goals of
docs/dod/journeys/intake-from-a-ticket.md are enforced here by the size of the
protocol, not by a rule somebody remembers.

Two rules make the writes safe to repeat:

* **A comment is idempotent by its marker.** :func:`marker_for` builds a hidden HTML
  comment (``<!-- crb:intake:ado:4711 -->``) that an adapter looks for before it
  writes: same marker, same text → nothing happens; same marker, new text → the
  existing comment is edited. A restart mid-poll therefore never doubles a comment.
* **A state label replaces, never accumulates.** :data:`LABELS` is a closed set of four;
  an adapter removes the other three as it sets one (:func:`is_state_label`), so a ticket
  shows exactly one state. A ``crb:`` tag that is not one of the four is a classifier
  INPUT and is preserved — clearing those by prefix took the operator's own
  ``crb:class=`` off the ticket and out of the next draft.

Every failure is a :class:`TrackerError` carrying one of :data:`STOP_REASONS` — the
word the listener records as ``intake.stopped``, the health probe reports and the
screen shows. Adapters never raise ``httpx`` errors past this boundary.

Navigation
----------
What it is:   ``TrackerClient`` (the six-verb Protocol), ``TicketRef`` and ``Ticket``
              (what a tracker hands back), ``marker_for``, the four labels and the
              closed set of stop reasons.
What it does: Defines the only vocabulary the rest of the product has for a tracker, so
              a second tracker is an adapter and nothing else changes; carries a
              ticket's revision as text so ADO's integer ``rev`` and Jira's ``updated``
              timestamp are the same idempotency key.
How:          ``typing.Protocol`` with ``@runtime_checkable`` (a fake that drops a verb
              fails ``isinstance`` in its own test); frozen dataclasses whose
              ``__post_init__`` coerces every sequence to a tuple so an item built from a
              ticket hashes the same way twice.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/ado.py and src/crb/intake/jira.py (the implementations),
              src/crb/intake/draft.py (``Ticket`` → a draft ``BacklogItem``),
              src/crb/intake/feedback.py (renders the text ``comment`` posts under the
              marker), src/crb/server/intake.py (the service that calls the six verbs)
Tested by:    tests/test_intake_client.py, tests/test_intake_adapters.py
Touch when:   a seventh verb is genuinely needed — it widens what the product may do to
              somebody's board, so it needs the ADR's non-goals revisited first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: The four labels the product sets, and the only ones it sets. Exactly one is on a
#: ticket at a time: an adapter removes the other three as it writes.
LABEL_NEEDS_INFO = "crb:needs-info"
LABEL_READY = "crb:ready"
LABEL_NOT_DELIVERABLE = "crb:not-deliverable"
LABEL_QUEUED = "crb:queued"
LABELS: tuple[str, ...] = (LABEL_NEEDS_INFO, LABEL_READY, LABEL_NOT_DELIVERABLE, LABEL_QUEUED)

#: The prefix every tag this product understands carries — its own four state labels AND the
#: classifier tags a person writes on a ticket (``crb:class=``, ``crb:kind=``, ``crb:level=``:
#: :mod:`crb.intake.draft`). It recognises a tag; it is NOT the test for removing one.
LABEL_PREFIX = "crb:"

_STATE_LABELS: frozenset[str] = frozenset(label.casefold() for label in LABELS)


def is_state_label(tag: str) -> bool:
    """Is ``tag`` one of the four labels this product sets? The test an adapter applies
    before it REMOVES a tag.

    A ``crb:`` tag that is not one of the four is an input, not a state: the classifier tags
    are somebody's own words about their own ticket, and an adapter that cleared every
    ``crb:`` tag by prefix deleted the operator's classification from the work item.
    """
    return str(tag).strip().casefold() in _STATE_LABELS


#: What a link the product attaches to a ticket is called, so a reader of the ticket knows
#: what they are about to open. The product attaches exactly these two things and no others.
LINK_ITEM = "Backlog item"
LINK_PULL_REQUEST = "Pull request"

#: Why a listener stopped. One of these words is on every ``intake.stopped`` event, the
#: ``/health`` probe and the intake screen; docs/API.md publishes them.
REASON_UNREACHABLE = "unreachable"
REASON_UNAUTHORISED = "unauthorised"
REASON_NO_SECRET = "no_secret"  # noqa: S105 — a reason WORD, not a value
REASON_REFUSED = "refused"
REASON_COLUMN_GONE = "column_gone"
REASON_NOT_CONFIGURED = "not_configured"
REASON_COLUMN_TOO_LARGE = "column_too_large"
REASON_NO_PUBLIC_URL = "no_public_url"
#: A pass ran past its lease and another pass took the repository over: this one stopped
#: before its next tracker call (PR #55 review). Raised by the server's lease fence, never
#: by an adapter.
REASON_LEASE_LOST = "lease_lost"
STOP_REASONS: tuple[str, ...] = (
    REASON_UNREACHABLE,
    REASON_UNAUTHORISED,
    REASON_NO_SECRET,
    REASON_REFUSED,
    REASON_COLUMN_GONE,
    REASON_NOT_CONFIGURED,
    REASON_COLUMN_TOO_LARGE,
    REASON_NO_PUBLIC_URL,
    REASON_LEASE_LOST,
)

#: What a person can do about each stop, in the words the screen and the health probe
#: show. Never a stack trace and never the tracker's own raw body.
STOP_ADVICE: dict[str, str] = {
    REASON_UNREACHABLE: (
        "The tracker did not answer. Check the organisation or site URL and that this "
        "deployment may reach it, then re-read the column."
    ),
    REASON_UNAUTHORISED: (
        "The tracker rejected the stored credential. Ask an admin to set a new token "
        "with permission to read work items and add comments."
    ),
    REASON_NO_SECRET: (
        "No tracker credential is stored. Ask an admin to set one on the Settings screen "
        "before switching the listener on."
    ),
    REASON_REFUSED: (
        "The tracker refused the write — usually a workflow transition it does not allow, "
        "or a permission the credential lacks. Nothing was changed on the ticket."
    ),
    REASON_COLUMN_GONE: (
        "The watched column or state no longer exists on that board. Point the listener at "
        "a column that does, then re-read."
    ),
    REASON_NOT_CONFIGURED: (
        "No tracker is configured for this deployment. Set the intake block in settings first."
    ),
    REASON_COLUMN_TOO_LARGE: (
        "The watched column holds more work than one pass may take, so nothing was read. "
        "Narrow the area path or the JQL so the column holds the tickets that are genuinely "
        "ready, or raise CRB_INTAKE__MAX_PER_POLL if the whole column is meant to be read."
    ),
    REASON_NO_PUBLIC_URL: (
        "This deployment does not know its own address, so a link on a ticket would not open. "
        "Set CRB_PUBLIC_URL to the address people use to reach this product, then re-read."
    ),
    REASON_LEASE_LOST: (
        "This pass took longer than its lease allows, and another pass took the column over. "
        "This pass stopped before its next call to the tracker. The other pass carries on, so "
        "there is nothing to do."
    ),
}


class TrackerError(RuntimeError):
    """A tracker refused or was unreachable.

    ``reason`` is one of :data:`STOP_REASONS` — the stable word the event, the health
    probe and the screen all use. ``detail`` is the human sentence; it never carries a
    credential and never carries the tracker's raw response body.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in STOP_REASONS:
            raise ValueError(f"reason must be one of {STOP_REASONS}, got {reason!r}")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail

    @property
    def advice(self) -> str:
        """What a person does about it (:data:`STOP_ADVICE`)."""
        return STOP_ADVICE[self.reason]


#: The tracker credential the intake listener polls with (ADR-0017): an Azure DevOps
#: personal access token, or a Jira API token. One per deployment, stored here and read
#: back only as a fingerprint — the same handling as the GitHub App's private key.
TRACKER_TOKEN_SECRET = "tracker_token"  # noqa: S105 — a secret NAME, not a value
TRACKER_TOKEN_MIN_LEN = 16
TRACKER_TOKEN_MAX_LEN = 4096


def validate_tracker_token(token: str) -> str:
    """The stripped token, or ``ValueError`` naming the *shape* problem (never the value).

    Neither Azure DevOps nor Jira publishes a token format that is stable enough to match
    against, so the checks are the ones that catch a paste mistake: it must not be empty,
    must be within a sane length, and must contain no whitespace or control characters —
    a pasted "Authorization: Basic …" header or a wrapped line fails here rather than as a
    401 at the first poll.
    """
    cleaned = (token or "").strip()
    if not cleaned:
        raise ValueError("a tracker token is required")
    if len(cleaned) < TRACKER_TOKEN_MIN_LEN:
        raise ValueError(f"token too short (< {TRACKER_TOKEN_MIN_LEN} characters)")
    if len(cleaned) > TRACKER_TOKEN_MAX_LEN:
        raise ValueError(f"token too long (> {TRACKER_TOKEN_MAX_LEN} characters)")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError(
            "the token contains a space or a line break — paste the token itself, not a "
            "header or a wrapped line"
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("the token contains a control character")
    return cleaned


def marker_for(tracker: str, key: str) -> str:
    """The marker that makes this product's comment on this ticket unique.

    An adapter finds the one comment containing this marker and edits it; finding none, it
    adds one. It names the tracker as well as the key, so two deployments watching two
    trackers cannot collide on a shared key.

    The marker is written as an HTML comment because Azure DevOps renders comments as HTML
    and a reader there never sees it. Jira does not: its comments are Atlassian Document
    Format, which has no hidden node, so the Jira adapter carries :func:`marker_token`
    instead, in a one-line attribution footer a reader can understand. Both forms contain
    the token, so either is found by the same lookup.
    """
    return f"<!-- crb:intake:{tracker}:{key} -->"


def marker_token(marker: str) -> str:
    """The marker without its HTML-comment wrapper (``crb:intake:ado:4711``).

    This — not the wrapper — is the identity a tracker is searched for, so a comment
    written as an HTML comment and one written as a plain reference are the same comment.
    """
    return marker.strip().removeprefix("<!--").removesuffix("-->").strip()


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class TicketRef:
    """A ticket as the column listing names it: enough to decide whether to read it.

    ``revision`` is text whatever the tracker calls it (ADO's integer ``System.Rev``,
    Jira's ``updated`` timestamp) because the product only ever compares it for
    equality: ``(tracker, key, revision)`` is the idempotency key of a poll.
    ``changed`` is when the ticket last moved, in the tracker's own ISO form — the
    watermark the next poll asks from.
    """

    key: str
    revision: str = ""
    title: str = ""
    url: str = ""
    changed: str = ""

    def __post_init__(self) -> None:
        if not str(self.key).strip():
            raise ValueError("a ticket ref needs a key")
        object.__setattr__(self, "key", str(self.key).strip())
        object.__setattr__(self, "revision", str(self.revision))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "revision": self.revision,
            "title": self.title,
            "url": self.url,
            "changed": self.changed,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TicketRef:
        return cls(
            key=str(d.get("key", "")),
            revision=str(d.get("revision", "")),
            title=str(d.get("title", "")),
            url=str(d.get("url", "")),
            changed=str(d.get("changed", "")),
        )


@dataclass(frozen=True)
class Ticket:
    """One ticket, in the product's words rather than the tracker's.

    ``body`` and ``acceptance_criteria`` are already plain text: the adapter has turned
    ADO's HTML or Jira's ADF into lines (:mod:`crb.intake.draft`'s converters), because
    everything downstream — the readiness slots, the draft item, the ledger — is text.
    ``points`` is the tracker's own estimate where it has one, and ``None`` where it
    does not; the draft states which it used.
    """

    key: str
    title: str = ""
    body: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    type: str = ""
    tags: tuple[str, ...] = ()
    points: float | None = None
    revision: str = ""
    links: tuple[str, ...] = ()
    url: str = ""
    state: str = ""
    #: Who created the ticket, as the tracker names them (Azure DevOps ``System.CreatedBy``
    #: unique name, Jira ``creator`` email or account id), lower-cased; ``""`` when the
    #: tracker did not say. The ONE input the operator-approval allowlist reads (ADR-0022) —
    #: never part of the draft's content digest, so it cannot make a ticket evolve.
    author: str = ""
    #: Anything else the adapter read and a reader may want on the row. Never parsed.
    extra: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.key).strip():
            raise ValueError("a ticket needs a key")
        object.__setattr__(self, "key", str(self.key).strip())
        object.__setattr__(self, "revision", str(self.revision))
        object.__setattr__(self, "author", str(self.author or "").strip().casefold())
        for attr in ("acceptance_criteria", "tags", "links"):
            object.__setattr__(self, attr, _tuple_of_str(getattr(self, attr)))
        object.__setattr__(
            self, "extra", tuple(sorted((str(k), str(v)) for k, v in dict(self.extra).items()))
        )

    @property
    def extra_map(self) -> dict[str, str]:
        """``extra`` as a mapping (it is stored as a sorted tuple so the ticket hashes)."""
        return dict(self.extra)

    @property
    def ref(self) -> TicketRef:
        """The listing shape of this ticket."""
        return TicketRef(key=self.key, revision=self.revision, title=self.title, url=self.url)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "body": self.body,
            "acceptance_criteria": list(self.acceptance_criteria),
            "type": self.type,
            "tags": list(self.tags),
            "points": self.points,
            "revision": self.revision,
            "links": list(self.links),
            "url": self.url,
            "state": self.state,
            "author": self.author,
            "extra": self.extra_map,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Ticket:
        pts = d.get("points")
        return cls(
            key=str(d.get("key", "")),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            acceptance_criteria=_tuple_of_str(d.get("acceptance_criteria")),
            type=str(d.get("type", "")),
            tags=_tuple_of_str(d.get("tags")),
            points=None if pts in (None, "") else float(pts),
            revision=str(d.get("revision", "")),
            links=_tuple_of_str(d.get("links")),
            url=str(d.get("url", "")),
            state=str(d.get("state", "")),
            author=str(d.get("author", "") or ""),
            extra={str(k): str(v) for k, v in dict(d.get("extra") or {}).items()},
        )


@runtime_checkable
class TrackerClient(Protocol):
    """The six verbs. An adapter that drops one fails ``isinstance`` in its own test.

    Every method raises :class:`TrackerError` and nothing else: the service above
    records ``reason`` and moves on, and a partial read never registers anything.
    """

    #: ``ado`` / ``jira`` / a test's own word. Part of the comment marker and the item id.
    name: str

    def entered(self, column: str, since: str) -> list[TicketRef]:
        """Tickets in ``column`` that changed at or after ``since`` (ISO, ``""`` = all).

        Raises ``TrackerError(REASON_COLUMN_GONE)`` when the board has no such column.
        """
        ...

    def read(self, key: str) -> Ticket:
        """The full ticket. Raises ``TrackerError`` when it cannot be read."""
        ...

    def comment(self, key: str, text: str, marker: str) -> None:
        """Leave ONE comment carrying ``marker``, editing the existing one when the
        marker is already on the ticket. Idempotent: same marker + same text writes
        nothing."""
        ...

    def label(self, key: str, value: str) -> None:
        """Set ``value`` (one of :data:`LABELS`) and remove any other ``crb:`` label."""
        ...

    def transition(self, key: str, state: str) -> None:
        """Move the ticket to ``state``. A workflow that forbids the move raises
        ``TrackerError(REASON_REFUSED)`` — the product never forces it."""
        ...

    def link(self, key: str, url: str, title: str = "") -> None:
        """Attach ``url`` to the ticket, once, under ``title``.

        The same verb attaches two different things at two different moments — the backlog
        item's page when the ticket is queued, and the pull request when one opens — so the
        caller says which, and a tracker that shows a link's name shows the right one.
        ``title`` empty means the tracker's own default.
        """
        ...


__all__ = [
    "LABELS",
    "LABEL_NEEDS_INFO",
    "LABEL_NOT_DELIVERABLE",
    "LABEL_PREFIX",
    "LABEL_QUEUED",
    "LABEL_READY",
    "LINK_ITEM",
    "LINK_PULL_REQUEST",
    "REASON_COLUMN_GONE",
    "REASON_COLUMN_TOO_LARGE",
    "REASON_LEASE_LOST",
    "REASON_NOT_CONFIGURED",
    "REASON_NO_PUBLIC_URL",
    "REASON_NO_SECRET",
    "REASON_REFUSED",
    "REASON_UNAUTHORISED",
    "REASON_UNREACHABLE",
    "STOP_ADVICE",
    "STOP_REASONS",
    "TRACKER_TOKEN_MAX_LEN",
    "TRACKER_TOKEN_MIN_LEN",
    "TRACKER_TOKEN_SECRET",
    "Ticket",
    "TicketRef",
    "TrackerClient",
    "TrackerError",
    "is_state_label",
    "marker_for",
    "marker_token",
    "validate_tracker_token",
]
