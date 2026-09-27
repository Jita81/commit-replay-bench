"""The one comment the ticket gets, and the label that goes with it.

Before any money is spent, the ticket learns three things in its own thread:

1. **What is missing.** Every open structural slot as the catalogue's question, plus the
   exact ``slot: text`` line to paste into the acceptance criteria to close it.
2. **What the product knows about work like this.** The (class × size) cell's route with
   its n, its 95 % interval, whether the honesty floor is intact and which apparatus
   version measured it — read from the capability map *before* the run, never a number
   the run itself produced.
3. **What the product needs before it builds this** (ADR-0026 item 8). The entry gate's
   decision — the same call the factory's pre-build check makes: the cell's proven context
   standard and what the ticket must carry for it, or why it will NOT BE BUILT (no proven
   standard, a ceiling, a size split, an unsigned cell) with each measured arm's state, n
   and interval and the way forward. Never "built and withheld".
4. **What the product will and will not do to the ticket.** One comment, one label, and
   at most the one state transition the deployment configured.

The renderer is pure and deterministic: the same draft, readiness and route render the
same bytes, which is what makes a re-post a no-op (:func:`crb.intake.client.marker_for`
carries the identity, the text carries the content). It never uses a term from the
instrument without glossing it — :data:`GLOSSED` is the list, and the test asserts each
gloss is present, so a future edit cannot quietly reintroduce jargon.

Navigation
----------
What it is:   ``render_feedback`` (draft + readiness + cell route → one marked comment and
              one label) plus the short renderers for the later moments —
              ``render_queued``, ``render_delivered``, ``render_refusal``.
What it does: Turns the gate's open questions, the entry gate's stop and the map's decision
              into GOV.UK plain English a person who has never heard of this product can act
              on, and picks exactly one of the four ``crb:`` labels (``crb:not-deliverable``
              for a ticket the entry gate stops, which will not be built, also once
              registered; ``crb:ready`` for one it admits, which is built whatever its
              cell routes — the route decides only whether a pull request opens, P-129).
How:          String building over :class:`crb.factory.readiness.Readiness` and the plain
              ``cell_route`` mapping the API and the worker both serve; no I/O, no clock,
              no randomness — determinism is the idempotency.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the labels and the marker),
              src/crb/intake/draft.py (the draft it describes),
              src/crb/factory/readiness.py (``open_questions`` and the gaps),
              src/crb/core/routing.py (the route words it explains),
              src/crb/factory/standard.py (the entry gate's decision it renders),
              src/crb/server/intake.py (posts the text through the adapter)
Tested by:    tests/test_intake_feedback.py
Touch when:   the comment gains a section (keep it deterministic); a routing word is added
              (gloss it in ``ROUTE_WORDS`` or the comment will show a bare code).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from crb.core.spec import UNCLASSIFIED
from crb.factory.readiness import Readiness, open_questions, slots_for
from crb.factory.standard import (
    REASON_CEILING,
    STOP_GRANULARIZE,
    STOP_NEEDS_CONTEXT,
    STOP_NO_PROVEN_STANDARD,
    STOP_UNSIGNED_CELL,
    STOP_UNSIZED,
    ArmReading,
    Entry,
)
from crb.intake.client import (
    LABEL_NEEDS_INFO,
    LABEL_NOT_DELIVERABLE,
    LABEL_QUEUED,
    LABEL_READY,
    marker_for,
)
from crb.intake.draft import Draft

#: Every instrument word the comment is allowed to use, and the gloss that must appear
#: with it. The test walks this table, so a word added here without its gloss fails.
GLOSSED: dict[str, str] = {
    "wilson": "the range the true rate is likely to sit in",
    "apparatus": "the version of the measuring rig",
    "cell": "changes of this kind and this size",
    "false-q1": "a change credited as clean although its own checks contradicted it",
    "context standard": (
        "the context the product has measured it needs to build changes like this one well"
    ),
    "calibration build": (
        "a build an approver pays for to measure the cell, which never becomes a pull request"
    ),
}

#: What each routing decision means for this ticket's PULL REQUEST, in one sentence a person
#: can act on. The route gate decides delivery only: whether the ticket is BUILT is the entry
#: gate's word (``_entry_block``), so no sentence here says "not built" (P-121, P-129).
ROUTE_WORDS: dict[str, str] = {
    "deliver": ("the product may build this and open a pull request for a person to review"),
    "calibrate": (
        "there is not enough evidence yet, so no pull request opens for changes in this "
        "cell until it has been measured"
    ),
    "granularize": (
        "changes this large are split into smaller ones, so no pull request opens for one "
        "this size — please split this ticket"
    ),
    "human": (
        "a pass here would not be trustworthy whatever the rate, so a person decides and "
        "no pull request opens from the product"
    ),
    "do_not_ship": (
        "the record for this cell is under audit, so nothing measured in it counts as "
        "evidence and no pull request opens in it"
    ),
}


#: What this product does to a ticket, stated as the COUNT a reader can check against their
#: own board, not as a reassuring "only". Over a ticket's life it adds up to four comments,
#: each marked as its own: this one about what is missing, a note when the work is queued, a
#: note when a pull request opens, and a note if the work stopped. It sets one ``crb:``
#: label, attaches a link to the backlog item and to the pull request, and — only where the
#: team configured it — makes one state change when the pull request is merged. Those, and
#: nothing else, are the six verbs the adapter has (docs/adr/0017); the sentence must keep
#: matching them, which is why a test counts them rather than looking for the word "never".
_NON_GOALS = (
    "What this product writes on this ticket: up to four comments, each marked as its own "
    "(this one about what is missing, a note when the work is queued, a note when a pull "
    "request opens, and a note if the work stopped); one crb: label; a link to the backlog "
    "item and to the pull request; and — only where the team configured it — one state "
    "change when the pull request is merged. It edits no other field, it never creates a "
    "ticket, and it never reads a column it was not pointed at."
)


@dataclass(frozen=True)
class Feedback:
    """One rendered comment, its marker, its label, and the machine-readable gaps."""

    text: str
    marker: str
    label: str
    #: True when every structural slot is filled, the ticket is sized and it carries what
    #: its cell's standard needs — the draft may be registered. A cell with no proven
    #: standard does NOT make this false: the item waits on the record, is NOT BUILT
    #: (the factory's pre-build check stops it too), and is never silently dropped.
    ready_to_register: bool
    open_questions: tuple[Mapping[str, str], ...] = ()
    cell_route: Mapping[str, Any] | None = None
    #: The entry gate's decision (ADR-0026 item 8) as the ticket was told it.
    entry: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "marker": self.marker,
            "label": self.label,
            "ready_to_register": self.ready_to_register,
            "open_questions": [dict(q) for q in self.open_questions],
            "cell_route": dict(self.cell_route) if self.cell_route else None,
            "entry": dict(self.entry) if self.entry else None,
        }


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f} %"
    except (TypeError, ValueError):
        return "unknown"


def _route_block(item_class: str, size: str, route: Mapping[str, Any] | None) -> list[str]:
    """What the product knows about this cell, before any run. Never a default it invented."""
    head = (
        f"**What we know about work like this** ({GLOSSED['cell']}: "
        f"{item_class or 'unclassified'}, size {size})"
    )
    if not route:
        return [
            head,
            "",
            "This cell has not been measured on this repository, so the product has no rate "
            "to quote. It says nothing, not zero. No pull request opens in it until "
            "somebody measures the cell.",
        ]
    word = str(route.get("route", ""))
    meaning = ROUTE_WORDS.get(word, "the product will hold any change back until a person decides")
    n = int(route.get("n") or 0)
    apparatus = ", ".join(str(a) for a in (route.get("apparatus_versions") or [])) or "unrecorded"
    lines = [
        head,
        "",
        f"Route: **{word}** — {meaning}.",
        f"Measured on {n} graded attempt(s); the pass rate is {_pct(route.get('point'))} with a "
        f"95 % Wilson interval ({GLOSSED['wilson']}) of {_pct(route.get('ci_low'))} to "
        f"{_pct(route.get('ci_high'))}.",
        f"Apparatus ({GLOSSED['apparatus']}): {apparatus}.",
    ]
    if word == "do_not_ship":
        lines.append(
            f"This cell has a false-Q1 ({GLOSSED['false-q1']}) on the record, so the numbers "
            "above are not evidence until the record is audited."
        )
    else:
        lines.append(
            f"No false-Q1 ({GLOSSED['false-q1']}) is on this cell's record; that floor never moves."
        )
    reason = str(route.get("reason") or "")
    if reason:
        lines.append(f"Why that route: {reason}.")
    return lines


def _class_block(draft: Draft) -> list[str]:
    cl = draft.classification
    if cl.capability_class == UNCLASSIFIED:
        return [
            "**What kind of change this is**",
            "",
            cl.reason,
            "",
            "Until the product knows the kind of change, it cannot say which questions a good "
            "test needs answered, and it will not spend anything on it.",
        ]
    return [
        "**What kind of change this is**",
        "",
        f"{cl.capability_class} (confidence {cl.confidence:.2f}). {cl.reason}",
        f"Size {draft.item.size_estimate}: {draft.size_reason}",
        f"Kind {draft.item.kind}: {draft.kind_reason}",
        "If that is wrong, add a tag such as `crb:class=bug.fix` to the ticket and the product "
        "will use it on the next read.",
    ]


def _questions_block(draft: Draft, readiness: Readiness) -> list[str]:
    if readiness.ready and not readiness.gaps:
        return [
            "**What is missing**",
            "",
            "Nothing. Every question a good test for this kind of change needs answered is "
            "answered on this ticket.",
        ]
    lines = ["**What is missing**", ""]
    if readiness.blocking_gaps:
        lines.append(
            "The product will not build this until these are answered. Add each one to the "
            "acceptance criteria as its own line, exactly in the form shown:"
        )
        lines.append("")
        for g in readiness.blocking_gaps:
            lines.append(f"- {g.question}")
            lines.append(f"  `{g.slot}: <your answer>`")
    if readiness.value_gaps:
        lines.append("")
        lines.append(
            "These do not block the build; they are the exact values the acceptance test will "
            "pin, so answering them makes the test sharper:"
        )
        for g in readiness.value_gaps:
            lines.append(f"- {g.question}")
            lines.append(f"  `{g.slot}: <your answer>`")
    if not slots_for(draft.item.capability_class):
        lines.append("")
        lines.append(
            "This kind of change is not in the product's catalogue of question sets, so a "
            "person has to design the test for it."
        )
    if draft.unused_fact_lines:
        lines.append("")
        lines.append(
            "These lines name a question belonging to a different kind of change, so the "
            "product did not read them as answers: "
            + ", ".join(f"`{line.strip()}`" for line in draft.unused_fact_lines)
            + "."
        )
    return lines


#: The entry stops the person can answer on the ticket: add points, attach what the arm needs.
_ASK_STOPS: frozenset[str] = frozenset({STOP_UNSIZED, STOP_NEEDS_CONTEXT})


def _label_for(readiness: Readiness, route: Mapping[str, Any] | None, entry: Entry) -> str:
    """The one label. Needs-info first: answering a question is the only step the person
    can take on their own, so it is never hidden behind a routing verdict — a missing slot,
    a missing size, or what the cell's standard needs (`needs_context`). A ticket the
    product could not classify is needs-info too — an unclassified item has no question
    set, so "nothing is missing" would be an artefact of not knowing what to ask. Then any
    other entry stop — no proven standard, a ceiling, a size split, an unsigned cell — is
    not deliverable: NOT BUILT (ADR-0026 item 8). A ticket the entry gate admits is ready:
    it is built, graded and reviewed whatever its cell routes; the route decides only
    whether a pull request opens, and the headline says which (P-129). ``route`` is not
    read here, so the label stays true once the ticket is registered (``crb:queued``)."""
    if not readiness.ready or not readiness.catalogued or entry.code in _ASK_STOPS:
        return LABEL_NEEDS_INFO
    if not entry.enters:
        return LABEL_NOT_DELIVERABLE
    return LABEL_READY


def _delivers(route: Mapping[str, Any] | None) -> bool:
    """Whether the cell's measured route opens a pull request (the loop's route gate)."""
    return bool(route) and str((route or {}).get("route", "")) == "deliver"


def _pct_or(value: float) -> str:
    return f"{value * 100:.0f} %"


def _arms_lines(arms: Sequence[ArmReading]) -> list[str]:
    """Each measured arm of the cell with its state, n and interval — or the plain fact
    that no arm has a registered reading yet (never a zero)."""
    if not arms:
        return ["No arm of this cell has a registered reading yet, so no rate is quoted."]
    return [
        f"- `{a.arm}`: {a.state} — {a.clean} of {a.n} commit(s) clean, 95 % Wilson interval "
        f"{_pct_or(a.ci_low)} to {_pct_or(a.ci_high)}"
        for a in arms
    ]


def _entry_block(draft: Draft, entry: Entry, arms: Sequence[ArmReading]) -> list[str]:
    """What the product needs before it builds this, and — when it will not — why and what
    closes it (ADR-0026 item 8). Every stop says "not built", never "built and withheld"."""
    head = "**What the product needs before it builds this**"
    cs = f"context standard ({GLOSSED['context standard']})"
    cal = f"calibration build ({GLOSSED['calibration build']})"
    if entry.enters:
        return [head, "", f"This ticket carries what its cell's {cs}, `{entry.arm}`, needs."]
    if entry.code == STOP_UNSIZED:
        return [
            head,
            "",
            "Story points. Without an estimate the product will not guess a size, because a "
            "guess could be smaller than the change. Put story points on the ticket.",
        ]
    if entry.code == STOP_NEEDS_CONTEXT:
        what = ", ".join(f"`{n}`" for n in entry.needs)
        return [
            head,
            "",
            f"This cell's {cs} is `{entry.arm}`, and the ticket lacks what it needs: {what}. "
            "Attach it to the ticket; nothing is built until it is there.",
        ]
    if entry.code == STOP_GRANULARIZE:
        return [head, "", f"{entry.reason[:1].upper()}{entry.reason[1:]}. It will not be built."]
    if entry.code == STOP_UNSIGNED_CELL:
        return [
            head,
            "",
            f"This cell's {cs}, `{entry.arm}`, is proven but nobody has signed it off, so "
            "this ticket will not be built. What closes it: a second person's sign-off of the "
            "cell, or an approver's named override for one run, which lifts only the "
            "sign-off.",
        ]
    ceiling = entry.reason_code == REASON_CEILING
    sizes = " and ".join(str(c.get("size", "")) for c in entry.cells) or draft.item.size_estimate
    return [
        head,
        "",
        (
            f"The only standard proven for this cell ({draft.item.capability_class}, size "
            f"{sizes}) is a ceiling: the commits' own tests, which a ticket never carries. "
            "It licenses nothing"
            if ceiling
            else f"No {cs} is proven for this cell ({draft.item.capability_class}, size {sizes})"
        )
        + ", so this ticket will not be built. Each arm measured in this cell:",
        "",
        *_arms_lines(arms),
        "",
        f"What closes it: measure the cell, or an approver funds one {cal}.",
    ]


def render_feedback(
    draft: Draft,
    readiness: Readiness,
    *,
    entry: Entry,
    cell_route: Mapping[str, Any] | None = None,
    arms: Sequence[ArmReading] = (),
) -> Feedback:
    """The gap feedback for one ticket: one marked comment and one label.

    ``entry`` is the entry gate's decision for the draft (:func:`crb.factory.standard.gate_for`
    — the same call the factory's pre-build check makes); ``arms`` the cell's measured arms.
    ``cell_route`` is the capability map's decision for the draft's (class × size) cell
    as the API and the worker both serve it, or ``None`` when nobody has measured it.
    """
    marker = marker_for(draft.tracker, draft.ticket.key)
    label = _label_for(readiness, cell_route, entry)
    headline = {
        LABEL_READY: (
            "This ticket is ready to manufacture."
            if _delivers(cell_route)
            else "This ticket will be built, graded and reviewed, but no pull request opens "
            "for it: its cell does not route deliver."
        ),
        LABEL_NEEDS_INFO: "This ticket needs more information before anything is built.",
        LABEL_NOT_DELIVERABLE: (
            "This ticket will not be built: nothing measured yet licenses changes like it."
        ),
    }[label]
    body = [
        marker,
        "## Commit Replay Bench",
        "",
        headline,
        "",
        *_class_block(draft),
        "",
        *_questions_block(draft, readiness),
        "",
        *_entry_block(draft, entry, arms),
        "",
        *_route_block(draft.item.capability_class, draft.item.size_estimate, cell_route),
        "",
        f"The product will record this as item `{draft.item.id}`."
        + (f" It replaces `{draft.item.supersedes}`." if draft.item.supersedes else ""),
        "",
        _NON_GOALS,
    ]
    return Feedback(
        text="\n".join(body).rstrip() + "\n",
        marker=marker,
        label=label,
        ready_to_register=(
            readiness.ready and readiness.catalogued and entry.code not in _ASK_STOPS
        ),
        open_questions=tuple(open_questions(readiness)),
        cell_route=dict(cell_route) if cell_route else None,
        entry=entry.to_dict(),
    )


#: The entry stops a REGISTERED item waits under: on the record, labelled not deliverable,
#: NOT BUILT until the stop is answered (ADR-0026 item 8) — never labelled queued.
WAITING_STOPS: frozenset[str] = frozenset(
    {STOP_NO_PROVEN_STANDARD, STOP_UNSIGNED_CELL, STOP_GRANULARIZE}
)


def label_once_registered(entry_stop: str) -> str:
    """The label a registered ticket carries: queued, or — when its cell's entry stop
    stands — not deliverable, because a queued label would say it is about to be built."""
    return LABEL_NOT_DELIVERABLE if entry_stop in WAITING_STOPS else LABEL_QUEUED


def render_queued(item_id: str, item_url: str, *, not_built: str = "") -> str:
    """The comment that goes with :data:`crb.intake.client.LABEL_QUEUED` — or, for an
    item registered under an entry stop (``not_built`` is its sentence), the note that it
    is on the record and will NOT be built until that is answered."""
    if not_built:
        return (
            f"This ticket is now item `{item_id}` in the factory's frozen backlog. It will not "
            f"be built: {not_built}. Follow it here: {item_url}\n"
        )
    return (
        f"This ticket is now item `{item_id}` in the factory's frozen backlog and is queued "
        f"to be manufactured. Follow it here: {item_url}\n"
    )


def render_delivered(item_id: str, pr_url: str) -> str:
    """The comment posted when the pull request opens."""
    return (
        f"The factory has opened a pull request for item `{item_id}`: {pr_url}\n\n"
        "Nothing is merged. A person reviews it exactly as they would any other pull request.\n"
    )


def render_refusal(item_id: str, *, status: str, reason: str, way_forward: str, url: str) -> str:
    """The comment posted when the loop stopped, carrying the served way forward verbatim."""
    lines = [
        f"The factory stopped on item `{item_id}` at `{status}`.",
        "",
        f"Why: {reason}" if reason else "",
        "",
        f"What closes it: {way_forward}" if way_forward else "",
        "",
        f"The item and its full record: {url}",
    ]
    return "\n".join(lines).strip() + "\n"


LABEL_ORDER: tuple[str, ...] = (
    LABEL_NEEDS_INFO,
    LABEL_NOT_DELIVERABLE,
    LABEL_READY,
    LABEL_QUEUED,
)

__all__ = [
    "GLOSSED",
    "LABEL_ORDER",
    "ROUTE_WORDS",
    "WAITING_STOPS",
    "Feedback",
    "label_once_registered",
    "render_delivered",
    "render_feedback",
    "render_queued",
    "render_refusal",
]
