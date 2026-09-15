"""The Definition-of-Ready gate — structural readiness + routing, never conjured answers.

The corrected finding in *The Quality Floor* ("The value of a specification,
isolated") bounds what this gate may claim: a specification helps only where it
carries **structure** — API-shaped facts a competent product owner can state
without having seen the implementation (a route's method and path, a field's
name/type/nullability, a component's props and states, a bug's reproduction and
expected behaviour). Where the missing fact is a **value** that lives only in
the test, the gate cannot conjure it; its honest output is a *routed decision*.

So the catalogue below has two kinds of slot per capability class:

* ``structural`` — REQUIRED. An unfilled, unsigned structural slot is a blocking
  gap: the factory refuses to build (:class:`NotReady`). It is filled by a
  ``slot: text`` line in the item's ``structural_facts``, or signed off by a
  human :class:`GapSignoff` record that supplies the fact.
* ``value`` — NEVER blocking. An open value slot routes the item to
  ``test_first_authoring`` (an independent test author pins the value in a
  test the operator can read) rather than to blind manufacture.

Routing hints (:data:`ROUTE_HINTS`):

* ``human``               — operator-kind work (money / accounts / legal —
  never delegable), a weak-oracle class (docs, CI, IaC: the test only proves
  the build), or a class the catalogue does not know;
* ``test_first_authoring`` — structurally ready, value slots open;
* ``build``               — every slot filled; an authored oracle can be built to.

Gap sign-offs are an append-only, hash-chained JSONL ledger of
:class:`GapSignoff` records (the same discipline as :mod:`crb.core.signoff`),
so the audit trail shows which fact came from whom and when.

Navigation
----------
What it is:   The Definition-of-Ready gate — per-class catalogue of structural and value
              slots, the append-only gap sign-off ledger, and the routed assessment.
What it does: Refuses to build an item with an unsigned STRUCTURAL gap (``NotReady``);
              never blocks on a VALUE gap (that routes to test-first authoring); routes
              operator-kind, uncatalogued and weak-oracle classes to ``human``. A gap is
              always reported as a question, never an invented answer; a signed fact
              carries who supplied it and when, hash-chained.
How:          ``assess`` = catalogue slots − (item facts ∪ active sign-offs) → gaps → route
              hint by the precedence in the module docstring; ``JsonlGapSignoffLedger``
              chains ``GapSignoff`` records like the grade ledger.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/factory/backlog.py (``BacklogItem`` and ``KIND_OPERATOR``),
              src/crb/factory/loop.py (``_assess`` — the first step of every item),
              src/crb/factory/evidence.py (``record_readiness`` / ``record_gap_signoff``),
              src/crb/factory/testfirst.py (where a value gap is resolved),
              src/crb/cli/commands/learn.py (runs ``assess`` on the items it emits),
              docs/OPERATOR.md#31-oracle-adequacy--mutation-scoring (what a weak oracle
              means for a class)
Tested by:    tests/test_factory_readiness.py, tests/test_factory_loop.py, tests/test_cli_learn.py
Touch when:   onboarding a repository whose change classes need different structural
              facts — extend ``CATALOGUE`` (a slot is a question a product owner can
              answer without seeing the implementation) and add the class to
              ``WEAK_ORACLE_CLASSES`` if green proves only the build; a catalogue change
              needs a note in docs/EVIDENCE-AND-CLAIMS.md.
Claims:       ``ready`` licenses an attempt, not a delivery; the route hint says who should
              act, never what the answer is (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.core.redact import redact
from crb.factory.backlog import KIND_OPERATOR, BacklogItem

GAP_SIGNOFF_SCHEMA = "crb.factory.gap_signoff.v1"

SLOT_STRUCTURAL = "structural"
SLOT_VALUE = "value"
SLOT_KINDS: tuple[str, ...] = (SLOT_STRUCTURAL, SLOT_VALUE)

ROUTE_BUILD = "build"
ROUTE_TEST_FIRST = "test_first_authoring"
ROUTE_HUMAN = "human"
ROUTE_HINTS: tuple[str, ...] = (ROUTE_BUILD, ROUTE_TEST_FIRST, ROUTE_HUMAN)

#: Classes whose oracle typically proves only the build; green cannot license
#: auto-delivery on the test alone — they route ``human`` (the DL-011 lesson).
WEAK_ORACLE_CLASSES: frozenset[str] = frozenset(
    {"docs.update", "ci.workflow.edit", "infra.helm.edit", "infra.terraform.edit"}
)


class NotReady(ValueError):
    """The factory refuses to build an item with an unsigned STRUCTURAL gap."""


@dataclass(frozen=True)
class Slot:
    """One fact a class needs: its name, the question a product owner answers, and
    whether an open slot blocks (``structural``) or routes (``value``)."""

    name: str
    question: str
    kind: str = SLOT_STRUCTURAL

    def __post_init__(self) -> None:
        if self.kind not in SLOT_KINDS:
            raise ValueError(f"slot kind must be one of {SLOT_KINDS}")


def _s(name: str, question: str) -> Slot:
    """A structural slot (catalogue shorthand)."""
    return Slot(name, question, SLOT_STRUCTURAL)


def _v(name: str, question: str) -> Slot:
    """A value slot (catalogue shorthand)."""
    return Slot(name, question, SLOT_VALUE)


#: Per capability class: the STRUCTURAL facts a good test needs (required) and
#: the value facts that route rather than block. Ported from the shape of the
#: upstream ``capability_catalog.SLOTS`` — structural slots only are required.
CATALOGUE: dict[str, tuple[Slot, ...]] = {
    "backend.route.add": (
        _s("method_path", "What HTTP method and path does the new route answer?"),
        _s("request_shape", "What is the request shape (params / body fields and types)?"),
        _s("response_shape", "What is the response shape (status code, body fields and types)?"),
        _s("error_contract", "What error responses must it return, and for which inputs?"),
        _v("example_payload", "A representative request and its exact expected response."),
    ),
    "backend.route.edit": (
        _s("route_identity", "Which existing route (method + path) changes?"),
        _s("behaviour_change", "What changes in its request/response shape or semantics?"),
        _s("error_contract", "Which error responses change, and which must stay the same?"),
        _v("example_payload", "A representative request and its exact expected response."),
    ),
    "backend.model.edit": (
        _s("field_name_type", "Which model, and what is the field's name and type?"),
        _s("nullability", "Is the field nullable? Is it unique / indexed?"),
        _s("migration_needed", "Is a schema migration needed (yes/no), and is it reversible?"),
        _v("default_value", "The exact default value when the field is unset."),
    ),
    "backend.migration.add": (
        _s("schema_change", "Which table(s) / column(s) does the migration add or alter?"),
        _s("reversible", "What does the downgrade do (or why is it irreversible)?"),
        _v("data_backfill", "The exact backfill value or rule for existing rows, if any."),
    ),
    "frontend.component.add": (
        _s("props", "What props does the component take (names, types, required)?"),
        _s("states", "What visual states does it have (loading / empty / error / populated)?"),
        _v("rendered_text", "The exact text or labels rendered in each state."),
    ),
    "frontend.component.edit": (
        _s("component_identity", "Which component changes?"),
        _s("prop_or_state_change", "Which props or states are added, removed or changed?"),
        _v("rendered_text", "The exact text or labels rendered after the change."),
    ),
    "frontend.route.add": (
        _s("route_path", "What client-side path is added, and which component renders it?"),
        _s("guard", "Is the route guarded (auth / role)? What happens when denied?"),
    ),
    "bug.fix": (
        _s("reproduction", "How is the bug reproduced (the input / sequence that fails)?"),
        _s("expected_behaviour", "What is the correct behaviour instead?"),
        _v("exact_value", "The exact output value / message at the reproduction input."),
    ),
    "test.add": (
        _s("subject_under_test", "Which module / function / behaviour is under test?"),
        _s("behaviour_asserted", "What behaviour must the new test assert?"),
    ),
    "test.fix": (
        _s("failing_test", "Which test is wrong (id), and why is it wrong?"),
        _s("corrected_assertion", "What must it assert instead?"),
    ),
    "docs.update": (_s("doc_target", "Which document / section changes, and what must it say?"),),
    "ci.workflow.edit": (
        _s("workflow", "Which workflow file and job change?"),
        _s("trigger_and_steps", "What triggers it, and which steps are added or changed?"),
    ),
    "infra.helm.edit": (
        _s("chart_and_values", "Which chart / template / values key changes?"),
        _s("provisioning", "What operator provisioning (cluster, credentials) must exist first?"),
    ),
    "infra.terraform.edit": (
        _s("resource", "Which resource(s) and attribute(s) change?"),
        _s(
            "provisioning",
            "What operator provisioning (account, billing, domain) must exist first?",
        ),
    ),
}

_FACT_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[:=]\s*(\S.*)$")


def parse_facts(facts: Iterable[str]) -> dict[str, str]:
    """``slot: text`` / ``slot = text`` lines → ``{slot: text}``. Free text without a
    slot prefix is passed to the builder but fills nothing."""
    out: dict[str, str] = {}
    for line in facts:
        m = _FACT_RE.match(line)
        if m and m.group(2).strip():
            out.setdefault(m.group(1), m.group(2).strip())
    return out


# ---------------------------------------------------------------------------
# Gap sign-off ledger (append-only, hash-chained)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GapSignoff:
    """A human supplied (or revoked) the fact for one slot of one item."""

    item_id: str
    slot: str
    verifier: str
    answer: str = ""
    kind: str = SLOT_STRUCTURAL
    revoked: bool = False
    signed_at: str = field(default_factory=utc_now_iso)
    schema: str = GAP_SIGNOFF_SCHEMA
    record_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if not self.item_id or not self.slot:
            raise ValueError("a gap sign-off needs an item_id and a slot")
        if not self.verifier:
            raise ValueError("verifier is required (who signed, or who revoked)")
        if self.kind not in SLOT_KINDS:
            raise ValueError(f"kind must be one of {SLOT_KINDS}")
        if not self.revoked and not self.answer.strip():
            raise ValueError("an attestation must carry the fact it supplies (answer)")
        object.__setattr__(self, "answer", redact(self.answer))
        if not self.record_id:
            object.__setattr__(self, "record_id", uuid.uuid4().hex)

    def key(self) -> tuple[str, str]:
        """``(item_id, slot)`` — the scope a later record supersedes."""
        return (self.item_id, self.slot)

    def body(self) -> dict[str, Any]:
        """Every field but ``row_hash`` — what is hashed."""
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "row_hash"}

    def compute_hash(self) -> str:
        """SHA-256 of the canonical JSON of :meth:`body`."""
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> GapSignoff:
        """A copy with ``prev_hash`` set and ``row_hash`` computed."""
        rec = replace(self, prev_hash=prev_hash)
        object.__setattr__(rec, "row_hash", rec.compute_hash())
        return rec

    def verify_hash(self) -> bool:
        """Whether the stored ``row_hash`` matches the body."""
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        """The stored line: body plus ``row_hash``."""
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> GapSignoff:
        """Inverse of :meth:`to_dict` (unknown keys ignored)."""
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class JsonlGapSignoffLedger:
    """Portable stdlib gap sign-off ledger. Same chain discipline as the grade ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        """The chain head from the file's last line (reads only the tail, so appending to a
        long ledger stays O(1))."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        last = ""
        with self.path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            step = min(size, 65536)
            f.seek(size - step)
            chunk = f.read().decode("utf-8", errors="replace")
        for line in reversed(chunk.splitlines()):
            if line.strip():
                last = line
                break
        if not last:
            return GENESIS_HASH
        row_hash = str(json.loads(last).get("row_hash", ""))
        if not row_hash:
            raise LedgerIntegrityError(f"last record in {self.path} has no row_hash")
        return row_hash

    def append(self, record: GapSignoff) -> GapSignoff:
        """Chain ``record`` onto the head and append one fsync'd line."""
        chained = record.chained(self._last_hash())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return chained

    def records(self) -> Iterator[GapSignoff]:
        """Every record in file order (an absent file is an empty ledger)."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield GapSignoff.from_dict(json.loads(line))

    def verify(self) -> int:
        """Walk the chain; return the count; raise ``LedgerIntegrityError`` on a break."""
        prev = GENESIS_HASH
        n = 0
        for rec in self.records():
            n += 1
            if rec.prev_hash != prev:
                raise LedgerIntegrityError(f"gap sign-off {n} prev_hash mismatch")
            if not rec.verify_hash():
                raise LedgerIntegrityError(f"gap sign-off {n} row_hash mismatch")
            prev = rec.row_hash
        return n

    def for_item(self, item_id: str) -> list[GapSignoff]:
        """The item's records (attestations and revocations), in order."""
        return [r for r in self.records() if r.item_id == item_id]


def active_signoffs(records: Iterable[GapSignoff]) -> dict[tuple[str, str], GapSignoff]:
    """Latest record per (item, slot); revoked scopes dropped."""
    latest: dict[tuple[str, str], GapSignoff] = {}
    for rec in records:
        latest[rec.key()] = rec
    return {k: r for k, r in latest.items() if not r.revoked}


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gap:
    """An open slot, reported as its question."""

    slot: str
    question: str
    kind: str

    @property
    def blocking(self) -> bool:
        """Structural gaps block the build; value gaps only route."""
        return self.kind == SLOT_STRUCTURAL

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "question": self.question, "kind": self.kind}


@dataclass(frozen=True)
class Readiness:
    """The gate's answer. ``ready`` iff no unsigned structural gap; ``gaps`` lists
    every open slot (structural and value) as a question, never an answer;
    ``facts`` is the merged (item + signed) fact set a builder may be shown."""

    item_id: str
    capability_class: str
    ready: bool
    gaps: tuple[Gap, ...]
    route_hint: str
    reason: str
    facts: Mapping[str, str] = field(default_factory=dict)
    signed_slots: tuple[str, ...] = ()
    catalogued: bool = True

    def __post_init__(self) -> None:
        if self.route_hint not in ROUTE_HINTS:
            raise ValueError(f"route_hint must be one of {ROUTE_HINTS}")
        object.__setattr__(self, "facts", dict(self.facts))
        if self.ready and any(g.blocking for g in self.gaps):
            raise ValueError("a ready assessment cannot carry a blocking gap")

    @property
    def blocking_gaps(self) -> tuple[Gap, ...]:
        """The structural gaps (empty whenever ``ready``)."""
        return tuple(g for g in self.gaps if g.blocking)

    @property
    def value_gaps(self) -> tuple[Gap, ...]:
        """The value gaps (what test-first authoring must pin)."""
        return tuple(g for g in self.gaps if not g.blocking)

    def fact_lines(self) -> tuple[str, ...]:
        """The facts as ``slot: text`` lines for a builder brief (structural + signed)."""
        return tuple(f"{k}: {v}" for k, v in self.facts.items())

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "capability_class": self.capability_class,
            "ready": self.ready,
            "gaps": [g.to_dict() for g in self.gaps],
            "route_hint": self.route_hint,
            "reason": self.reason,
            "facts": dict(self.facts),
            "signed_slots": list(self.signed_slots),
            "catalogued": self.catalogued,
        }


def slots_for(capability_class: str) -> tuple[Slot, ...]:
    """The catalogue's slots for a class; empty for an uncatalogued class."""
    return CATALOGUE.get(capability_class, ())


def assess(item: BacklogItem, signoffs: Iterable[GapSignoff] = ()) -> Readiness:
    """Assess one item against its class's catalogue and the active sign-offs.

    Structural slots are filled by the item's own ``structural_facts`` or by a
    signed-off answer; value slots likewise but never block. The route hint is
    derived — it is a decision about *who* should act, not an answer.
    """
    slots = slots_for(item.capability_class)
    catalogued = bool(slots)
    active = {k[1]: r for k, r in active_signoffs(signoffs).items() if k[0] == item.id}
    facts = parse_facts(item.structural_facts)
    for slot, rec in active.items():
        facts.setdefault(slot, rec.answer)
    gaps = tuple(Gap(s.name, s.question, s.kind) for s in slots if s.name not in facts)
    blocking = [g for g in gaps if g.blocking]
    ready = not blocking

    # Route precedence is deliberate: the reasons a HUMAN must act come first, so a
    # fully-filled operator item or weak-oracle class can never read as "build".
    if item.kind == KIND_OPERATOR:
        route, reason = ROUTE_HUMAN, "operator-kind work is never delegated to the factory"
    elif not catalogued:
        route, reason = (
            ROUTE_HUMAN,
            f"class {item.capability_class!r} is not in the readiness catalogue — human test-design",
        )
    elif item.capability_class in WEAK_ORACLE_CLASSES:
        route, reason = (
            ROUTE_HUMAN,
            f"class {item.capability_class!r} has a weak oracle (green proves the build only)",
        )
    elif blocking:
        route, reason = (
            ROUTE_HUMAN,
            f"{len(blocking)} unsigned structural gap(s): {', '.join(g.slot for g in blocking)}",
        )
    elif any(not g.blocking for g in gaps):
        route, reason = (
            ROUTE_TEST_FIRST,
            "value slot(s) open — the value lives in the test; route to test-first authoring, "
            f"never blind manufacture: {', '.join(g.slot for g in gaps if not g.blocking)}",
        )
    else:
        route, reason = ROUTE_BUILD, "every catalogued slot is filled"

    return Readiness(
        item_id=item.id,
        capability_class=item.capability_class,
        ready=ready,
        gaps=gaps,
        route_hint=route,
        reason=reason,
        facts=facts,
        signed_slots=tuple(sorted(active)),
        catalogued=catalogued,
    )


def require_ready(item: BacklogItem, signoffs: Iterable[GapSignoff] = ()) -> Readiness:
    """:func:`assess`, raising :class:`NotReady` on any unsigned structural gap."""
    r = assess(item, signoffs)
    if not r.ready:
        qs = "; ".join(f"{g.slot}: {g.question}" for g in r.blocking_gaps)
        raise NotReady(f"item {item.id} is not ready — unsigned structural gap(s): {qs}")
    return r


def open_questions(readiness: Readiness) -> list[dict[str, str]]:
    """The gaps as the DoR ``{ref, severity, reason}`` shape the readiness surface speaks."""
    return [
        {
            "ref": f"{readiness.item_id}::{readiness.capability_class}::{g.slot}",
            "severity": "blocking" if g.blocking else "routed",
            "reason": g.question,
        }
        for g in readiness.gaps
    ]


def sign(
    ledger: JsonlGapSignoffLedger,
    item: BacklogItem,
    slot: str,
    answer: str,
    *,
    verifier: str,
) -> GapSignoff:
    """Convenience: sign one slot of one item (kind taken from the catalogue)."""
    kinds = {s.name: s.kind for s in slots_for(item.capability_class)}
    return ledger.append(
        GapSignoff(
            item_id=item.id,
            slot=slot,
            verifier=verifier,
            answer=answer,
            kind=kinds.get(slot, SLOT_STRUCTURAL),
        )
    )


__all__ = [
    "CATALOGUE",
    "GAP_SIGNOFF_SCHEMA",
    "ROUTE_BUILD",
    "ROUTE_HINTS",
    "ROUTE_HUMAN",
    "ROUTE_TEST_FIRST",
    "SLOT_KINDS",
    "SLOT_STRUCTURAL",
    "SLOT_VALUE",
    "WEAK_ORACLE_CLASSES",
    "Gap",
    "GapSignoff",
    "JsonlGapSignoffLedger",
    "NotReady",
    "Readiness",
    "Slot",
    "active_signoffs",
    "assess",
    "open_questions",
    "parse_facts",
    "require_ready",
    "sign",
    "slots_for",
]
