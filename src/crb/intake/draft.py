"""One ticket becomes one draft backlog item — and every mapping says which rule it used.

A draft is not a registration. It is what the product would register, shown on the
intake row and quoted back to the ticket, so a person can correct it before a penny is
spent. Six mappings make it, and each of the six carries its own sentence:

=================  ===========================================================
id                 ``<tracker>-<key>`` lowercased, anything outside the
                   backlog's id regex replaced by ``-`` (``ado-4711``,
                   ``jira-abc-123``). A re-read at a new revision is a NEW id,
                   ``<id>.r<revision>``, superseding the previous one.
body               ADO's HTML or Jira's ADF turned into plain lines. Everything
                   downstream is text.
facts              an acceptance-criteria line of the form ``slot: text`` whose
                   ``slot`` is in **this item's class** catalogue becomes a
                   structural fact. A line naming another class's slot is left
                   as prose: the product never invents an answer.
size               story points → a tier (``points`` column below). No estimate
                   is ``S`` and the reason says so.
kind               an explicit ``crb:kind=`` tag, else ``infra`` for an
                   ``infra.``/``ci.`` class, else ``code``.
class              the classifier (:func:`classify`), which SERVES ITS
                   CONFIDENCE. Below :data:`MIN_CONFIDENCE` the class is
                   ``unclassified`` — never a silent guess, and the comment on
                   the ticket says the product could not classify it.
=================  ===========================================================

Points → size (Fibonacci, the common board scale; published in docs/ONBOARDING.md):
``≤ 1 → XS``, ``≤ 3 → S``, ``≤ 8 → M``, ``≤ 20 → L``, above → ``XL``.

Navigation
----------
What it is:   ``draft_from`` (ticket → :class:`Draft`), ``classify`` (title + body →
              :class:`Classification` with a confidence), and the two rich-text
              converters ``html_to_text`` / ``adf_to_text``.
What it does: Produces the ``BacklogItem`` the registration route would take, plus the
              plain sentence behind every mapping, plus the supersession link when the
              ticket has been edited since the product last read it.
How:          Pure functions over :class:`crb.intake.client.Ticket`; ``html.parser`` for
              HTML and a recursive walk for ADF (stdlib only); the classifier scores a
              closed table of cue groups per class and reports ``strength × margin`` as
              its confidence, so one weak cue can never read as certainty.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the ``Ticket`` it maps),
              src/crb/factory/backlog.py (``BacklogItem``, the id regex, the kinds and
              levels), src/crb/factory/readiness.py (the slot catalogue whose names a
              fact line must use, and the gate that reads the facts back),
              src/crb/core/spec.py (``SIZE_TIER_NAMES``, ``UNCLASSIFIED``),
              src/crb/intake/feedback.py (renders the draft's gaps onto the ticket)
Tested by:    tests/test_intake_draft.py
Touch when:   a capability class joins the readiness catalogue — give it cues in ``CUES``
              or it can only ever arrive by an explicit ``crb:class=`` tag; the points
              scale changes (it is published, so change the guide in the same commit).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from crb.core.evidence import utc_now_iso
from crb.core.spec import UNCLASSIFIED
from crb.factory.backlog import (
    ID_MAX_LEN,
    KIND_CODE,
    KIND_INFRA,
    KINDS,
    LEVEL_L1,
    LEVELS,
    BacklogItem,
)
from crb.factory.readiness import CATALOGUE, slots_for
from crb.intake.client import Ticket

#: Below this the classifier says ``unclassified`` instead of guessing. Chosen so that a
#: single cue on its own (strength 1/3) can never clear it: two independent cues with no
#: rival class can.
MIN_CONFIDENCE = 0.4

#: Cues at which the classifier is fully confident in its *strength* term. Three
#: independent cue groups is "the ticket says what it is" without needing a fourth.
TARGET_CUES = 3

#: Tags a person writes on the ticket to override a mapping. Anything else is a label.
TAG_CLASS = "crb:class="
TAG_KIND = "crb:kind="
TAG_LEVEL = "crb:level="

_ID_ILLEGAL = re.compile(r"[^a-z0-9._-]+")
_FACT_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[:=]\s*(\S.*)$")

#: Story points → size tier. Upper bound (inclusive) → tier; above the last bound is XL.
POINTS_TO_SIZE: tuple[tuple[float, str], ...] = ((1.0, "XS"), (3.0, "S"), (8.0, "M"), (20.0, "L"))
SIZE_WITHOUT_POINTS = "S"

#: Cue groups per capability class. A group is a tuple of alternative phrases; matching
#: ANY phrase in a group scores the group once, so repeating a synonym cannot inflate a
#: score. Ordered by class, and every class here is a key of the readiness CATALOGUE.
CUES: dict[str, tuple[tuple[str, ...], ...]] = {
    "backend.route.add": (
        ("add a", "new ", "create ", "expose ", "introduce "),
        ("route", "endpoint", "get /", "post /", "put /", "patch /", "delete /"),
        ("http", "rest", " api", "request", "response", "status code"),
    ),
    "backend.route.edit": (
        ("change the", "update the", "modify the", "existing route", "existing endpoint"),
        ("route", "endpoint"),
        ("response shape", "request shape", "status code", " api"),
    ),
    "backend.model.edit": (
        ("add a field", "new field", "change the field", "model field", "field to the"),
        ("model", "entity", "orm"),
        ("nullable", "unique", "index", "default value"),
    ),
    "backend.migration.add": (
        ("migration", "alembic", "schema change"),
        ("add a column", "new column", "alter table", "drop column", "to the table"),
        ("database", "schema", "table"),
    ),
    "frontend.component.add": (
        ("add a", "new ", "create ", "build a", "introduce "),
        ("component",),
        ("react", "vue", "svelte", "tsx", "jsx", "props", "renders"),
    ),
    "frontend.component.edit": (
        ("change the", "update the", "modify the", "existing component", "rename the"),
        ("component",),
        ("props", "prop ", "state", "react", "vue", "svelte"),
    ),
    "frontend.route.add": (
        ("add a", "new ", "create "),
        ("screen", "page", "client-side route", "url path"),
        ("router", "guarded", "requires sign-in", "requires a role", "navigation"),
    ),
    "bug.fix": (
        ("bug", "crash", "defect", "regression", "broken", "fails when", "does not work"),
        ("reproduce", "steps to reproduce", "repro"),
        ("expected", "should instead", "incorrect", "wrong result"),
    ),
    "test.add": (
        ("add a test", "new test", "missing test", "cover with a test", "test coverage"),
        ("unit test", "test case", "coverage"),
        ("assert", "asserts"),
    ),
    "test.fix": (
        ("failing test", "flaky test", "wrong test", "fix the test"),
        ("assertion", "asserts the wrong"),
        ("test suite", "test file"),
    ),
    "docs.update": (
        ("documentation", "readme", "the docs", "user guide", "changelog"),
        ("update the", "correct the", "rewrite the", "is wrong", "out of date", "clarify"),
        ("section", "page", "paragraph", "sentence"),
    ),
    "ci.workflow.edit": (
        ("workflow", "pipeline", "github actions", "ci job"),
        ("job", "step", "trigger"),
        ("ci ", "build pipeline", ".yml", ".yaml"),
    ),
    "infra.helm.edit": (
        ("helm", "chart"),
        ("values.yaml", "template", "values key"),
        ("kubernetes", "cluster", "deployment manifest"),
    ),
    "infra.terraform.edit": (
        ("terraform", "hcl", "tfstate"),
        ("resource", "attribute", "module"),
        ("provider", "state file", "infrastructure", "bucket", "aws", "azure", "gcp"),
    ),
}

#: Classes whose work the factory writes but an operator applies (``kind: infra``).
_INFRA_PREFIXES = ("infra.", "ci.")


# ---------------------------------------------------------------------------
# rich text → plain text
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    """HTML → lines. Block tags break the line, ``<li>`` becomes ``- ``, and the body of
    a ``<script>`` or ``<style>`` is dropped rather than read as text."""

    _BREAK = frozenset({"br", "p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "li"})
    _DROP = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._dropping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._DROP:
            self._dropping += 1
            return
        if tag in self._BREAK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROP and self._dropping:
            self._dropping -= 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._dropping:
            self.parts.append(data)


def _tidy(text: str) -> str:
    """Collapse runs of spaces and blank lines; strip each line; drop empty ones."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> str:
    """ADO's rich-text HTML as plain lines. Malformed HTML degrades to its text."""
    if not html:
        return ""
    if "<" not in html:
        return _tidy(html)
    p = _TextExtractor()
    p.feed(html)
    p.close()
    return _tidy("".join(p.parts))


def adf_to_text(doc: Any) -> str:
    """Jira's Atlassian Document Format as plain lines; a plain string passes through.

    Only the node kinds a ticket body actually uses are understood — text, paragraph,
    heading, lists, code blocks, hard breaks. An unknown node is walked for its
    ``content`` so nothing is silently lost.
    """
    if doc is None:
        return ""
    if isinstance(doc, str):
        return _tidy(doc)
    out: list[str] = []

    def walk(node: Any, bullet: bool = False) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, bullet)
            return
        if not isinstance(node, dict):
            return
        kind = str(node.get("type", ""))
        if kind == "text":
            out.append(str(node.get("text", "")))
            return
        if kind == "hardBreak":
            out.append("\n")
            return
        if kind in ("paragraph", "heading", "codeBlock"):
            out.append("\n")
            if bullet:
                out.append("- ")
            walk(node.get("content"), False)
            out.append("\n")
            return
        if kind == "listItem":
            walk(node.get("content"), True)
            return
        walk(node.get("content"), bullet)

    walk(doc)
    return _tidy("".join(out))


# ---------------------------------------------------------------------------
# the classifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Classification:
    """What class the product thinks this is, how sure it is, and why.

    ``confidence`` is ``strength × margin`` rounded to two places: ``strength`` is how
    many independent cue groups matched (capped at :data:`TARGET_CUES`), ``margin`` is
    how far ahead of the runner-up it is. Both terms must be healthy, so a ticket that
    reads equally like two classes is never confident even when both score well.
    """

    capability_class: str
    confidence: float
    reason: str
    #: ``(class, score)`` for every class that scored, best first — what the row shows
    #: under "what else it could be".
    considered: tuple[tuple[str, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_class": self.capability_class,
            "confidence": self.confidence,
            "reason": self.reason,
            "considered": [{"capability_class": k, "score": s} for k, s in self.considered],
        }


def classify(title: str, body: str = "") -> Classification:
    """Classify a ticket by its words alone, and say how sure that is.

    Deterministic and offline: no model is called here. The point is not to be right
    every time; it is to be *honestly unsure* when it is unsure, so the comment on the
    ticket asks the person rather than routing money at a guess.
    """
    text = f"{title}\n{body}".lower()
    scores: list[tuple[str, int]] = []
    hits: dict[str, list[str]] = {}
    for klass, groups in CUES.items():
        matched = [g[0] for g in groups if any(phrase in text for phrase in g)]
        if matched:
            scores.append((klass, len(matched)))
            hits[klass] = matched
    if not scores:
        return Classification(
            UNCLASSIFIED,
            0.0,
            "The product could not classify this ticket from its title and description. "
            "Say what kind of change it is, or add a crb:class= tag.",
            (),
        )
    scores.sort(key=lambda kv: (-kv[1], kv[0]))
    best_class, best = scores[0]
    runner = scores[1][1] if len(scores) > 1 else 0
    strength = min(best / TARGET_CUES, 1.0)
    # +1 on both sides so a lone cue with no rival is still only *some* evidence:
    # margin is about ties, strength about how much the ticket actually said.
    margin = (best - runner + 1) / (best + 1)
    confidence = round(strength * margin, 2)
    words = ", ".join(repr(w) for w in hits[best_class])
    if confidence < MIN_CONFIDENCE:
        rival = f" and {scores[1][0]!r} reads just as likely" if runner else ""
        return Classification(
            UNCLASSIFIED,
            confidence,
            f"The product could not classify this ticket confidently: it matched {words}"
            f"{rival}. Say what kind of change it is, or add a crb:class= tag.",
            tuple(scores),
        )
    return Classification(
        best_class,
        confidence,
        f"Classified {best_class} because the ticket mentions {words}.",
        tuple(scores),
    )


# ---------------------------------------------------------------------------
# the draft
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Draft:
    """What the product would register for this ticket, and why each part is what it is."""

    item: BacklogItem
    ticket: Ticket
    tracker: str
    classification: Classification
    size_reason: str
    kind_reason: str
    #: True when this draft supersedes an item already registered from the same ticket.
    is_evolution: bool = False
    #: Acceptance-criteria lines that named a slot of ANOTHER class — shown on the row so
    #: a person can see why an answer they wrote was not used.
    unused_fact_lines: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "ticket": self.ticket.to_dict(),
            "tracker": self.tracker,
            "classification": self.classification.to_dict(),
            "size_reason": self.size_reason,
            "kind_reason": self.kind_reason,
            "is_evolution": self.is_evolution,
            "unused_fact_lines": list(self.unused_fact_lines),
        }


def item_id_for(tracker: str, key: str) -> str:
    """``<tracker>-<key>`` lowercased and legal for the backlog's id regex.

    The KEY is checked on its own: a key that sanitises to nothing would make an id that
    names only the tracker, and two such tickets would collide. That is refused, never
    guessed at.

    Two keys can never become one id. The backlog's ids are capped at 64 characters, and a
    plain truncation would map two keys sharing a 64-character prefix onto the same item —
    the second ticket would be told, on its own board, that it had been recorded as the
    first one's item while nothing was registered for it. An id that has to be shortened
    therefore keeps 55 characters of the slug and ends in eight characters of its SHA-256,
    which is derived from the WHOLE key.
    """
    key_slug = _ID_ILLEGAL.sub("-", str(key).lower()).strip("-.")
    if not key_slug:
        raise ValueError(f"ticket key {key!r} has no characters an item id may use")
    slug = _ID_ILLEGAL.sub("-", f"{tracker}-{key_slug}".lower()).strip("-.")
    if not slug or not slug[0].isalnum():
        raise ValueError(f"ticket key {key!r} does not make a usable item id")
    if len(slug) <= ID_MAX_LEN:
        return slug
    digest = hashlib.sha256(f"{tracker}-{key}".encode()).hexdigest()[:8]
    return f"{slug[: ID_MAX_LEN - 9].rstrip('-.')}-{digest}"


def _tag_value(tags: tuple[str, ...], prefix: str) -> str:
    for t in tags:
        raw = t.strip()
        if raw.lower().startswith(prefix):
            return raw[len(prefix) :].strip()
    return ""


def size_for(points: float | None) -> tuple[str, str]:
    """``(tier, the sentence that says why)`` for a story-point estimate."""
    if points is None or points <= 0:
        return (
            SIZE_WITHOUT_POINTS,
            f"The ticket carries no estimate, so the size is {SIZE_WITHOUT_POINTS} by default. "
            "Put story points on the ticket to change it.",
        )
    for upper, tier in POINTS_TO_SIZE:
        if points <= upper:
            return tier, f"{points:g} story points is {tier} on the published scale."
    return "XL", f"{points:g} story points is above {POINTS_TO_SIZE[-1][0]:g}, which is XL."


def kind_for(capability_class: str, tags: tuple[str, ...], work_item_type: str) -> tuple[str, str]:
    """``(kind, the sentence that says why)``: an explicit tag, else the class, else code."""
    tagged = _tag_value(tags, TAG_KIND)
    if tagged:
        if tagged in KINDS:
            return tagged, f"The ticket carries the tag crb:kind={tagged}."
        return (
            KIND_CODE,
            f"The tag crb:kind={tagged} names no kind this product has "
            f"({', '.join(KINDS)}), so the item is code.",
        )
    if capability_class.startswith(_INFRA_PREFIXES):
        return (
            KIND_INFRA,
            f"Class {capability_class} is infrastructure: the factory writes the change and "
            "an operator applies it.",
        )
    kindly = f" ({work_item_type})" if work_item_type else ""
    return KIND_CODE, f"The work item{kindly} is a code change the factory can build."


def level_for(tags: tuple[str, ...]) -> str:
    """The horizon from a ``crb:level=`` tag; L1 when absent or unknown."""
    tagged = _tag_value(tags, TAG_LEVEL).upper()
    return tagged if tagged in LEVELS else LEVEL_L1


def _class_for(ticket: Ticket) -> Classification:
    tagged = _tag_value(ticket.tags, TAG_CLASS)
    if tagged:
        if tagged in CATALOGUE:
            return Classification(
                tagged, 1.0, f"The ticket carries the tag crb:class={tagged}.", ((tagged, 0),)
            )
        return Classification(
            UNCLASSIFIED,
            0.0,
            f"The tag crb:class={tagged} names a class that is not in the catalogue, so the "
            "product did not use it. Use one of the published classes, or remove the tag.",
            (),
        )
    return classify(ticket.title, ticket.body)


def _facts_from(
    lines: tuple[str, ...], capability_class: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """``(facts, prose, lines that named another class's slot)``.

    A line is a fact only when its name is a slot of THIS item's class. Anything else
    stays as acceptance criteria: the product records what the person wrote and never
    promotes it to an answer the gate would treat as filled.
    """
    known = {s.name for s in slots_for(capability_class)}
    every_slot = {s.name for slots in CATALOGUE.values() for s in slots}
    facts: list[str] = []
    prose: list[str] = []
    unused: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        m = _FACT_LINE.match(raw)
        name = m.group(1) if m else ""
        if m and name in known and name not in seen:
            seen.add(name)
            facts.append(f"{name}: {m.group(2).strip()}")
        elif m and name in every_slot:
            unused.append(raw)
            prose.append(raw)
        else:
            prose.append(raw)
    return tuple(facts), tuple(prose), tuple(unused)


def draft_from(
    ticket: Ticket,
    *,
    tracker: str,
    previous: BacklogItem | None = None,
    registered: str = "",
) -> Draft:
    """Map one ticket to the item the product would register, with every rule stated.

    ``previous`` is the item already registered from this ticket, if any. When the
    ticket's revision has moved on since, the draft is an EVOLUTION: a new id
    (``<id>.r<revision>``) that supersedes ``previous``. The frozen record is never
    rewritten — that is the whole point of reading a ticket twice.
    """
    base_id = item_id_for(tracker, ticket.key)
    classification = _class_for(ticket)
    facts, prose, unused = _facts_from(ticket.acceptance_criteria, classification.capability_class)
    size, size_reason = size_for(ticket.points)
    kind, kind_reason = kind_for(classification.capability_class, ticket.tags, ticket.type)
    is_evolution = previous is not None and previous.labels.get("revision", "") != ticket.revision
    item_id = (
        f"{base_id}.r{_ID_ILLEGAL.sub('-', ticket.revision.lower())}" if is_evolution else base_id
    )
    labels = {
        "tracker": tracker,
        "ticket": ticket.key,
        "revision": ticket.revision,
        "source": "intake",
    }
    if ticket.url:
        labels["url"] = ticket.url
    if ticket.tags:
        labels["tags"] = ", ".join(ticket.tags)
    item = BacklogItem(
        id=item_id,
        title=ticket.title or f"{tracker} {ticket.key}",
        kind=kind,
        description=ticket.body,
        acceptance_criteria=prose,
        capability_class=classification.capability_class,
        size_estimate=size,
        structural_facts=facts,
        level=level_for(ticket.tags),
        supersedes=previous.id if (is_evolution and previous is not None) else "",
        labels=labels,
        # ``registered`` defaults to "now"; a caller pins it so two reads of the same
        # unchanged ticket produce the same item bytes (and therefore the same hash)
        registered=registered or utc_now_iso(),
    )
    return Draft(
        item=item,
        ticket=ticket,
        tracker=tracker,
        classification=classification,
        size_reason=size_reason,
        kind_reason=kind_reason,
        is_evolution=is_evolution,
        unused_fact_lines=unused,
    )


__all__ = [
    "CUES",
    "MIN_CONFIDENCE",
    "POINTS_TO_SIZE",
    "SIZE_WITHOUT_POINTS",
    "TAG_CLASS",
    "TAG_KIND",
    "TAG_LEVEL",
    "TARGET_CUES",
    "UNCLASSIFIED",
    "Classification",
    "Draft",
    "adf_to_text",
    "classify",
    "draft_from",
    "html_to_text",
    "item_id_for",
    "kind_for",
    "level_for",
    "size_for",
]
