"""The factory evidence ledger — ``pilot/evidence.jsonl`` in the charter.

Every governed step of forward mode appends ONE :class:`FactoryEvent` here:
the backlog freeze, each gap sign-off, each RED proof, each build (its evidence
pack hash and ledger row id — the grade itself lives in the grade ledger), each
delivery (branch + PR ref; a rework's re-delivery is ``delivery.updated``), each
review verdict, and each horizon checkpoint.
The file is append-only and hash-chained exactly like the grade ledger
(``prev_hash`` → ``row_hash``); :meth:`FactoryEvidence.verify` proves nothing
was edited, reordered or removed.

Two invariants live here rather than in the loop, so no caller can skip them:

* **Verdict before edit.** :meth:`FactoryEvidence.verdict_for` is the only way to
  learn an item's verdict, and :meth:`FactoryEvidence.record_verdict` refuses a
  verdict that claims ``recorded_before_edit`` when an ``edit`` event for the same
  build already exists.
* **Nothing secret.** Every string in a payload passes through
  :mod:`crb.core.redact` at construction.
* **At most closed, then merged, per pull request.**
  :meth:`FactoryEvidence.record_delivery_outcome` appends ``delivery.merged`` /
  ``delivery.closed`` for a pull request at most once per STATE, and only in the order
  GitHub allows: a ``closed`` PR can be reopened and merged by a person, so ``merged``
  after ``closed`` is a real transition and is recorded (newest wins in every fold);
  ``merged`` is terminal, so nothing follows it; the same state twice returns the event
  already there and appends nothing (B-9 / F30 — an outcome sync may run on every factory
  run and by hand, and the record must not grow with the number of syncs).

Persistence is behind the :class:`FactoryStore` protocol; :class:`JsonlFactoryStore`
is the stdlib reference. The database store is a later workstream.

Navigation
----------
What it is:   The factory evidence ledger — one hash-chained event per governed step, and
              the home of the verdict-before-edit invariant.
What it does: Appends ``FactoryEvent`` rows (freeze, evolution, sign-off, readiness, route,
              RED proof, build, delivery opened / updated / refused / merged / closed,
              verdict, edit, checkpoint, outcome) through a typed front
              door; redacts every payload string at construction; refuses to record an edit
              for a build with no verdict, refuses a verdict that claims to precede an
              edit already on the record, and records a pull request's outcome at most
              once; ``verify`` proves the chain.
How:          ``FactoryEvidence.record_*`` → ``FactoryStore.append`` (``JsonlFactoryStore``
              fsyncs a line per event; ``MemoryFactoryStore`` for tests) → ``chained`` with
              the previous ``row_hash``; ``verify_events`` re-walks.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/factory/loop.py (calls a ``record_*`` at every arrow),
              src/crb/factory/review.py (``record_verdict`` before returning; ``permit_edit``),
              src/crb/core/ledger.py (``GENESIS_HASH``, ``LedgerIntegrityError`` — the shared
              chain vocabulary), src/crb/core/redact.py (the payload scrub),
              src/crb/server/factory_state.py (folds the events into the task view; runs
              the outcome sync that calls ``record_delivery_outcome``),
              src/crb/server/routes/factory.py (serves the chain)
Tested by:    tests/test_factory_review.py, tests/test_factory_loop.py,
              tests/test_factory_outcomes.py
Touch when:   never for a new repository; adding a governed step means a new ``EV_*`` kind,
              a ``record_*`` method, and a call from the loop — all in one change (an
              unknown kind is refused at construction).
Claims:       A verified factory ledger proves the ORDER of steps and that none was edited —
              the grade itself is in the grade ledger, cited by pack hash and row id
              (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import (
    GENESIS_HASH,
    LedgerIntegrityError,
    jsonl_append_lock,
    jsonl_last_line,
)
from crb.core.redact import redact

FACTORY_EVIDENCE_SCHEMA = "crb.factory.evidence.v1"

EV_BACKLOG_FROZEN = "backlog.frozen"
EV_BACKLOG_EVOLVED = "backlog.evolved"
EV_GAP_SIGNOFF = "gap.signoff"
EV_READINESS = "readiness.assessed"
EV_ROUTE = "route.decided"
EV_RED_PROOF = "red.proved"
EV_RED_REFUSED = "red.refused"
EV_BUILD = "build.graded"
EV_DELIVERY = "delivery.opened"
EV_DELIVERY_UPDATED = "delivery.updated"
EV_DELIVERY_REFUSED = "delivery.refused"
EV_DELIVERY_MERGED = "delivery.merged"
EV_DELIVERY_CLOSED = "delivery.closed"
EV_VERDICT = "review.verdict"
EV_EDIT = "edit.permitted"
EV_CHECKPOINT = "horizon.checkpoint"
EV_ITEM_OUTCOME = "item.outcome"
#: Intake (ADR-0017): what the listener did with a ticket. These sit on the SAME chain as
#: the manufacture steps on purpose — "who read this ticket, when, at which revision, and
#: what it wrote back" is evidence of the same kind as "who built it", and a reader
#: should not have to visit a second ledger to see the whole life of an item.
EV_INTAKE_POLLED = "intake.polled"
EV_INTAKE_READ = "intake.read"
EV_INTAKE_FEEDBACK = "intake.feedback.posted"
EV_INTAKE_REGISTERED = "intake.registered"
EV_INTAKE_QUEUED = "intake.queued"
EV_INTAKE_DELIVERED = "intake.delivered"
EV_INTAKE_TRANSITIONED = "intake.transitioned"
EV_INTAKE_STOPPED = "intake.stopped"
INTAKE_EVENT_KINDS: tuple[str, ...] = (
    EV_INTAKE_POLLED,
    EV_INTAKE_READ,
    EV_INTAKE_FEEDBACK,
    EV_INTAKE_REGISTERED,
    EV_INTAKE_QUEUED,
    EV_INTAKE_DELIVERED,
    EV_INTAKE_TRANSITIONED,
    EV_INTAKE_STOPPED,
)
EVENT_KINDS: tuple[str, ...] = (
    EV_BACKLOG_FROZEN,
    EV_BACKLOG_EVOLVED,
    EV_GAP_SIGNOFF,
    EV_READINESS,
    EV_ROUTE,
    EV_RED_PROOF,
    EV_RED_REFUSED,
    EV_BUILD,
    EV_DELIVERY,
    EV_DELIVERY_UPDATED,
    EV_DELIVERY_REFUSED,
    EV_DELIVERY_MERGED,
    EV_DELIVERY_CLOSED,
    EV_VERDICT,
    EV_EDIT,
    EV_CHECKPOINT,
    EV_ITEM_OUTCOME,
    *INTAKE_EVENT_KINDS,
)
#: The two ways a delivered pull request ends; the sync records exactly one of them.
OUTCOME_MERGED = "merged"
OUTCOME_CLOSED = "closed"
OUTCOME_KINDS: dict[str, str] = {
    OUTCOME_MERGED: EV_DELIVERY_MERGED,
    OUTCOME_CLOSED: EV_DELIVERY_CLOSED,
}

#: How each horizon level is verified (the T9 horizon ladder, §2).
VERIFICATION_MODES: dict[str, str] = {
    "L1": "authored-tests-green+boot-and-smoke",
    "L2": "deployed-e2e-smoke+test-user-feedback",
    "L3": "slo+escape-watch+monitoring",
}


class VerdictBeforeEditViolation(RuntimeError):
    """A verdict claims to precede an edit that is already on the record."""


def _redact_value(v: Any) -> Any:
    """Redact every string anywhere in a payload (nested mappings and sequences too)."""
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, Mapping):
        return {str(k): _redact_value(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_redact_value(x) for x in v]
    return v


@dataclass(frozen=True)
class FactoryEvent:
    """One governed step's record: a known ``kind``, the item, a redacted payload, and the
    chain fields (``prev_hash`` / ``row_hash``) the store fills in."""

    kind: str
    item_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    actor: str = ""
    repo: str = ""
    created: str = field(default_factory=utc_now_iso)
    schema: str = FACTORY_EVIDENCE_SCHEMA
    event_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"event kind {self.kind!r} not in {EVENT_KINDS}")
        object.__setattr__(self, "payload", _redact_value(dict(self.payload)))
        if not self.event_id:
            object.__setattr__(self, "event_id", uuid.uuid4().hex)

    # --- hashing ---------------------------------------------------------------
    def body(self) -> dict[str, Any]:
        """Every field but ``row_hash`` — what is hashed."""
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "row_hash"}
        d["payload"] = dict(self.payload)
        return d

    def compute_hash(self) -> str:
        """SHA-256 of the canonical JSON of :meth:`body`."""
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> FactoryEvent:
        """A copy with ``prev_hash`` set and ``row_hash`` computed."""
        ev = replace(self, prev_hash=prev_hash)
        object.__setattr__(ev, "row_hash", ev.compute_hash())
        return ev

    def verify_hash(self) -> bool:
        """Whether the stored ``row_hash`` matches the body."""
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """The stored line: body plus ``row_hash``."""
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FactoryEvent:
        """Inverse of :meth:`to_dict` (unknown keys ignored)."""
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class FactoryStore(Protocol):
    """Append-only event persistence. ``append`` chains and returns the stored event."""

    def append(self, event: FactoryEvent) -> FactoryEvent: ...

    def events(self) -> Iterator[FactoryEvent]: ...


class MemoryFactoryStore:
    """In-memory store (tests, dry runs). Same chain discipline as the JSONL store."""

    def __init__(self) -> None:
        self._events: list[FactoryEvent] = []
        self._lock = threading.Lock()

    def append(self, event: FactoryEvent) -> FactoryEvent:
        with self._lock:
            prev = self._events[-1].row_hash if self._events else GENESIS_HASH
            ev = event.chained(prev)
            self._events.append(ev)
            return ev

    def events(self) -> Iterator[FactoryEvent]:
        return iter(list(self._events))


class JsonlFactoryStore:
    """Portable stdlib store: one event per line, fsync'd, hash-chained."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _last_hash(self) -> str:
        """The ``row_hash`` of the last non-blank line (tail read via
        :func:`crb.core.ledger.jsonl_last_line`), or :data:`GENESIS_HASH`."""
        last = jsonl_last_line(self.path)
        if not last:
            return GENESIS_HASH
        row_hash = str(json.loads(last).get("row_hash", ""))
        if not row_hash:
            raise LedgerIntegrityError(f"last event in {self.path} has no row_hash")
        return row_hash

    def append(self, event: FactoryEvent) -> FactoryEvent:
        """Chain onto the head and append one fsync'd line, under the store's thread
        lock AND an OS file lock — the API process and the worker process append to the
        same evidence file, and a thread lock cannot order two processes (CodeRabbit on
        PR #4, 2026-09-15)."""
        with self._lock, jsonl_append_lock(self.path):
            ev = event.chained(self._last_hash())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(ev.to_dict(), sort_keys=True, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            return ev

    def events(self) -> Iterator[FactoryEvent]:
        """Every event in file order (an absent file is an empty ledger)."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield FactoryEvent.from_dict(json.loads(line))


def verify_events(events: Iterable[FactoryEvent]) -> int:
    """Walk a chain; return the count; raise ``LedgerIntegrityError`` on the first break."""
    prev = GENESIS_HASH
    n = 0
    for ev in events:
        n += 1
        if ev.prev_hash != prev:
            raise LedgerIntegrityError(f"factory event {n} ({ev.kind}) prev_hash mismatch")
        if not ev.verify_hash():
            raise LedgerIntegrityError(f"factory event {n} ({ev.kind}) row_hash mismatch")
        prev = ev.row_hash
    return n


def _payload(d: Mapping[str, Any]) -> dict[str, Any]:
    """A record's fields minus ``item_id`` (which is the event's own key)."""
    return {k: v for k, v in d.items() if k != "item_id"}


class FactoryEvidence:
    """Typed front door over a :class:`FactoryStore`. One method per governed step."""

    def __init__(self, store: FactoryStore, *, actor: str = "", repo: str = "") -> None:
        self.store = store
        self.actor = actor
        self.repo = repo

    # --- generic ---------------------------------------------------------------
    def append(self, kind: str, item_id: str = "", **payload: Any) -> FactoryEvent:
        """Append one event of ``kind`` stamped with this ledger's actor and repo."""
        return self.store.append(
            FactoryEvent(
                kind=kind, item_id=item_id, payload=payload, actor=self.actor, repo=self.repo
            )
        )

    def events(self) -> list[FactoryEvent]:
        """Every event, in chain order."""
        return list(self.store.events())

    def events_for(self, item_id: str, kind: str = "") -> list[FactoryEvent]:
        """An item's events, optionally of one kind, in chain order."""
        return [e for e in self.events() if e.item_id == item_id and (not kind or e.kind == kind)]

    def verify(self) -> int:
        """Walk the chain; return the event count; raise on any break."""
        return verify_events(self.store.events())

    # --- the governed steps ------------------------------------------------------
    def record_freeze(
        self, *, backlog_hash: str, item_ids: Iterable[str], frozen_at: str
    ) -> FactoryEvent:
        return self.append(
            EV_BACKLOG_FROZEN,
            backlog_hash=backlog_hash,
            item_ids=list(item_ids),
            frozen_at=frozen_at,
        )

    def record_evolution(
        self, *, item_id: str, supersedes: str, backlog_hash: str, evolutions_hash: str
    ) -> FactoryEvent:
        return self.append(
            EV_BACKLOG_EVOLVED,
            item_id,
            supersedes=supersedes,
            backlog_hash=backlog_hash,
            evolutions_hash=evolutions_hash,
        )

    def record_gap_signoff(self, record: Mapping[str, Any]) -> FactoryEvent:
        return self.append(EV_GAP_SIGNOFF, str(record.get("item_id", "")), record=dict(record))

    def record_readiness(self, readiness: Mapping[str, Any]) -> FactoryEvent:
        return self.append(EV_READINESS, str(readiness.get("item_id", "")), **_payload(readiness))

    def record_route(self, item_id: str, route: str, reason: str, **extra: Any) -> FactoryEvent:
        return self.append(EV_ROUTE, item_id, route=route, reason=reason, **extra)

    def record_red_proof(self, proof: Mapping[str, Any]) -> FactoryEvent:
        return self.append(EV_RED_PROOF, str(proof.get("item_id", "")), **_payload(proof))

    def record_red_refused(self, item_id: str, reason: str, **extra: Any) -> FactoryEvent:
        return self.append(EV_RED_REFUSED, item_id, reason=reason, **extra)

    def record_build(
        self,
        item_id: str,
        *,
        pack_hash: str,
        row_id: str,
        row_hash: str,
        clean: bool,
        belts: Mapping[str, Any],
        rung: str,
        trial: str,
        oracle_commit: str,
        test_sha256: str,
        disqualified: bool = False,
        error: str = "",
    ) -> FactoryEvent:
        return self.append(
            EV_BUILD,
            item_id,
            pack_hash=pack_hash,
            row_id=row_id,
            row_hash=row_hash,
            clean=clean,
            belts=dict(belts),
            rung=rung,
            trial=trial,
            oracle_commit=oracle_commit,
            test_sha256=test_sha256,
            disqualified=disqualified,
            error=error,
        )

    def record_delivery(self, delivery: Mapping[str, Any]) -> FactoryEvent:
        return self.append(EV_DELIVERY, str(delivery.get("item_id", "")), **_payload(delivery))

    def record_delivery_updated(
        self, delivery: Mapping[str, Any], *, rework: int, after_verdict: str
    ) -> FactoryEvent:
        """A rework's re-delivery: the same payload as ``delivery.opened`` (its
        ``previous_commit_sha`` says where the branch moved from, ``pr_url`` / ``pr_number``
        are the pull request it updated) plus the rework number and the verdict it answers."""
        return self.append(
            EV_DELIVERY_UPDATED,
            str(delivery.get("item_id", "")),
            rework=rework,
            after_verdict=after_verdict,
            **_payload(delivery),
        )

    def record_delivery_refused(self, item_id: str, reason: str, **extra: Any) -> FactoryEvent:
        return self.append(EV_DELIVERY_REFUSED, item_id, reason=reason, **extra)

    def record_delivery_outcome(
        self,
        item_id: str,
        *,
        state: str,
        pr_number: int,
        pr_url: str = "",
        merged_at: str = "",
        merged_by: str = "",
        merge_sha: str = "",
        closed_at: str = "",
    ) -> tuple[FactoryEvent, bool]:
        """The pull request's fate, read back from GitHub: ``state`` is ``merged`` or
        ``closed``. Returns ``(event, recorded)``: ``recorded`` is False — and the event is
        the one already on the chain — when this PR's newest outcome is already ``state``,
        or is ``merged`` (terminal: a merge is never followed by anything). ``merged``
        after ``closed`` IS recorded: a person can reopen a closed pull request and merge
        it, and the chain must say so (idempotent per state; at most two outcomes per PR)."""
        kind = OUTCOME_KINDS.get(state)
        if kind is None:
            raise ValueError(f"state must be one of {tuple(OUTCOME_KINDS)}, got {state!r}")
        existing = self.outcome_for(item_id, pr_number)
        if existing is not None and existing.kind in (kind, EV_DELIVERY_MERGED):
            return existing, False
        ev = self.append(
            kind,
            item_id,
            state=state,
            pr_number=int(pr_number),
            pr_url=pr_url,
            merged_at=merged_at,
            merged_by=merged_by,
            merge_sha=merge_sha,
            closed_at=closed_at,
        )
        return ev, True

    def record_verdict(self, verdict: Mapping[str, Any]) -> FactoryEvent:
        """Record a review verdict. Refuses a verdict that claims to precede an edit
        when an edit for the same build (pack hash) is already on the record."""
        item_id = str(verdict.get("item_id", ""))
        pack_hash = str(verdict.get("pack_hash", ""))
        if verdict.get("recorded_before_edit", True) and self.edits_for(item_id, pack_hash):
            raise VerdictBeforeEditViolation(
                f"item {item_id}: an edit of build {pack_hash[:12]} is already on the record — "
                "a verdict cannot claim to precede it"
            )
        return self.append(EV_VERDICT, item_id, **_payload(verdict))

    def record_edit(
        self, item_id: str, *, pack_hash: str, editor: str, note: str = ""
    ) -> FactoryEvent:
        """The gate: an edit is only recordable once a verdict for that build exists."""
        if self.verdict_for(item_id, pack_hash) is None:
            raise VerdictBeforeEditViolation(
                f"item {item_id}: no verdict recorded for build {pack_hash[:12]} — verdict before edit"
            )
        return self.append(EV_EDIT, item_id, pack_hash=pack_hash, editor=editor, note=note)

    def record_checkpoint(
        self,
        *,
        level: str,
        observations: int,
        issues_minted: Iterable[str],
        signed_off_by: str,
        verification_mode: str = "",
        note: str = "",
    ) -> FactoryEvent:
        if level not in VERIFICATION_MODES:
            raise ValueError(f"level must be one of {tuple(VERIFICATION_MODES)}")
        return self.append(
            EV_CHECKPOINT,
            level=level,
            verification_mode=verification_mode or VERIFICATION_MODES[level],
            observations=observations,
            issues_minted=list(issues_minted),
            signed_off_by=signed_off_by,
            note=note,
        )

    def record_item_outcome(self, item_id: str, **outcome: Any) -> FactoryEvent:
        """The loop's final status for an item (the last event of its run)."""
        return self.append(EV_ITEM_OUTCOME, item_id, **outcome)

    # --- queries -----------------------------------------------------------------
    def verdict_for(self, item_id: str, pack_hash: str = "") -> FactoryEvent | None:
        """The LATEST verdict for the item (optionally for one build)."""
        found = None
        for e in self.events_for(item_id, EV_VERDICT):
            if not pack_hash or e.payload.get("pack_hash") == pack_hash:
                found = e
        return found

    def edits_for(self, item_id: str, pack_hash: str = "") -> list[FactoryEvent]:
        """Every permitted edit for the item (optionally for one build)."""
        return [
            e
            for e in self.events_for(item_id, EV_EDIT)
            if not pack_hash or e.payload.get("pack_hash") == pack_hash
        ]

    def outcome_for(self, item_id: str, pr_number: int) -> FactoryEvent | None:
        """The NEWEST outcome event (``delivery.merged`` / ``delivery.closed``) recorded
        for this item's pull request ``pr_number``, or ``None`` (a closed-then-merged PR
        answers the merge)."""
        found: FactoryEvent | None = None
        for e in self.events_for(item_id):
            if e.kind in (EV_DELIVERY_MERGED, EV_DELIVERY_CLOSED) and int(
                e.payload.get("pr_number", 0) or 0
            ) == int(pr_number):
                found = e
        return found

    def signed_gaps(self, item_id: str) -> dict[str, FactoryEvent]:
        """Mirror of the gap ledger: latest sign-off event per slot (revoked dropped)."""
        out: dict[str, FactoryEvent] = {}
        for e in self.events_for(item_id, EV_GAP_SIGNOFF):
            rec = e.payload.get("record", {})
            slot = str(rec.get("slot", ""))
            if rec.get("revoked"):
                out.pop(slot, None)
            elif slot:
                out[slot] = e
        return out


__all__ = [
    "EVENT_KINDS",
    "EV_BACKLOG_EVOLVED",
    "EV_BACKLOG_FROZEN",
    "EV_BUILD",
    "EV_CHECKPOINT",
    "EV_DELIVERY",
    "EV_DELIVERY_CLOSED",
    "EV_DELIVERY_MERGED",
    "EV_DELIVERY_REFUSED",
    "EV_DELIVERY_UPDATED",
    "EV_EDIT",
    "EV_GAP_SIGNOFF",
    "EV_ITEM_OUTCOME",
    "EV_READINESS",
    "EV_RED_PROOF",
    "EV_RED_REFUSED",
    "EV_ROUTE",
    "EV_VERDICT",
    "FACTORY_EVIDENCE_SCHEMA",
    "OUTCOME_CLOSED",
    "OUTCOME_KINDS",
    "OUTCOME_MERGED",
    "VERIFICATION_MODES",
    "FactoryEvent",
    "FactoryEvidence",
    "FactoryStore",
    "JsonlFactoryStore",
    "MemoryFactoryStore",
    "VerdictBeforeEditViolation",
    "verify_events",
]
