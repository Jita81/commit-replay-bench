"""The factory evidence ledger — ``pilot/evidence.jsonl`` in the charter.

Every governed step of forward mode appends ONE :class:`FactoryEvent` here:
the backlog freeze, each gap sign-off, each RED proof, each build (its evidence
pack hash and ledger row id — the grade itself lives in the grade ledger), each
delivery (branch + PR ref), each review verdict, and each horizon checkpoint.
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

Persistence is behind the :class:`FactoryStore` protocol; :class:`JsonlFactoryStore`
is the stdlib reference. The database store is a later workstream.
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
from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
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
EV_DELIVERY_REFUSED = "delivery.refused"
EV_VERDICT = "review.verdict"
EV_EDIT = "edit.permitted"
EV_CHECKPOINT = "horizon.checkpoint"
EV_ITEM_OUTCOME = "item.outcome"
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
    EV_DELIVERY_REFUSED,
    EV_VERDICT,
    EV_EDIT,
    EV_CHECKPOINT,
    EV_ITEM_OUTCOME,
)

#: How each horizon level is verified (the T9 horizon ladder, §2).
VERIFICATION_MODES: dict[str, str] = {
    "L1": "authored-tests-green+boot-and-smoke",
    "L2": "deployed-e2e-smoke+test-user-feedback",
    "L3": "slo+escape-watch+monitoring",
}


class VerdictBeforeEditViolation(RuntimeError):
    """A verdict claims to precede an edit that is already on the record."""


def _redact_value(v: Any) -> Any:
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, Mapping):
        return {str(k): _redact_value(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_redact_value(x) for x in v]
    return v


@dataclass(frozen=True)
class FactoryEvent:
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
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "row_hash"}
        d["payload"] = dict(self.payload)
        return d

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> FactoryEvent:
        ev = replace(self, prev_hash=prev_hash)
        object.__setattr__(ev, "row_hash", ev.compute_hash())
        return ev

    def verify_hash(self) -> bool:
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FactoryEvent:
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
            raise LedgerIntegrityError(f"last event in {self.path} has no row_hash")
        return row_hash

    def append(self, event: FactoryEvent) -> FactoryEvent:
        with self._lock:
            ev = event.chained(self._last_hash())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(ev.to_dict(), sort_keys=True, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            return ev

    def events(self) -> Iterator[FactoryEvent]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield FactoryEvent.from_dict(json.loads(line))


def verify_events(events: Iterable[FactoryEvent]) -> int:
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
        return self.store.append(
            FactoryEvent(
                kind=kind, item_id=item_id, payload=payload, actor=self.actor, repo=self.repo
            )
        )

    def events(self) -> list[FactoryEvent]:
        return list(self.store.events())

    def events_for(self, item_id: str, kind: str = "") -> list[FactoryEvent]:
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

    def record_delivery_refused(self, item_id: str, reason: str, **extra: Any) -> FactoryEvent:
        return self.append(EV_DELIVERY_REFUSED, item_id, reason=reason, **extra)

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
        return [
            e
            for e in self.events_for(item_id, EV_EDIT)
            if not pack_hash or e.payload.get("pack_hash") == pack_hash
        ]

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
    "EV_DELIVERY_REFUSED",
    "EV_EDIT",
    "EV_GAP_SIGNOFF",
    "EV_ITEM_OUTCOME",
    "EV_READINESS",
    "EV_RED_PROOF",
    "EV_RED_REFUSED",
    "EV_ROUTE",
    "EV_VERDICT",
    "FACTORY_EVIDENCE_SCHEMA",
    "VERIFICATION_MODES",
    "FactoryEvent",
    "FactoryEvidence",
    "FactoryStore",
    "JsonlFactoryStore",
    "MemoryFactoryStore",
    "VerdictBeforeEditViolation",
    "verify_events",
]
