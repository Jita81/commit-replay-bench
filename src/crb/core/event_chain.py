"""The ``events`` hash chain: what one event row hashes, and the walk that proves the audit
trail was not altered.

The grade ledger has been a chain since ADR-0002; the audit trail beside it (``events``:
who signed in, who changed a role, who set the unsealed override, every step of every run)
was append-only by trigger only, so a person with the database's owner role could drop the
trigger, edit a row and put the trigger back without a trace (backlog F51). ADR-0041 chains
it the same way: each row carries ``prev_hash`` (the previous row's ``row_hash``, or
:data:`GENESIS_HASH` for the first) and ``row_hash`` (the SHA-256 of the canonical JSON of
the row's fields and ``prev_hash``). The chain order is the row id order.

Invariants
----------
* **One body.** :func:`event_body` is the only definition of what an event row hashes; the
  store's write path and every verifier call it, so the two cannot disagree. Revision 0031
  carries a frozen copy (a released revision imports nothing of the runtime) and a test
  holds the copy to this function.
* **Values are normalised to what the database hands back.** ``seq`` and ``duration_ms``
  are integers, ``cost_usd`` a float (a ``REAL`` column returns ``1.0`` for ``1``), the
  payload a JSON round trip (tuples become lists, keys strings) — so a row hashes the same
  when it is written and when it is read.
* **The walk never raises.** :func:`walk_event_chain` reports the first break by row id and
  keeps counting, so a route can serve a broken chain as a finding, not a 500.

What the chain proves: no row was edited, deleted from the middle or moved. What it cannot
prove alone: that rows were not cut from the end, or that the whole table was not replaced
by a new, self-consistent chain. The head (:attr:`EventChainReport.head`) is served on
``/ledger/verify`` and written to the log at every worker start so an operator can record it
outside the store (G-601, docs/DEPLOYMENT.md §8).

Navigation
----------
What it is:   The ``events`` chain's hash rule and verifier — stdlib only, shared by the
              store's writer, ``/ledger/verify``, ``crb ledger verify --store`` and the tests.
What it does: Names the hashed fields (``EVENT_CHAIN_FIELDS``), builds the canonical body
              of one row (``event_body``), hashes it onto its predecessor
              (``event_row_hash``) and walks a sequence of stored rows reporting the first
              broken link or edited row (``walk_event_chain`` → ``EventChainReport``), from
              genesis or resumed from a head already walked.
How:          ``canonical_json`` + ``sha256_text`` from crb.core.evidence (the one
              serialisation every hash in the product is taken over); the walk compares each
              ``prev_hash`` with the running head and each ``row_hash`` with a recomputation.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0041-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/events.py (chains every new ``events`` row in the writer's own
              flush), src/crb/store/migrations/versions/v0031_events_hash_chain.py (chains
              the rows that existed before, with a frozen copy of ``event_body``),
              src/crb/server/routes/ledger.py (``/ledger/verify`` serves the report),
              src/crb/cli/commands/ledger.py (``crb ledger verify --store``)
Tested by:    tests/test_event_chain.py, tests/test_store_events_chain.py
Touch when:   never for a new repository; a column added to ``events`` is either added to
              ``EVENT_CHAIN_FIELDS`` under a new ``EVENT_CHAIN_SCHEMA`` (old rows keep
              verifying under the old one) or named in ``EVENT_CHAIN_UNHASHED``, and ADR-0041
              says which — tests/test_event_chain.py fails until one of the two is done.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from crb.core.evidence import canonical_json, sha256_text

#: The first row's ``prev_hash`` (the same genesis the grade ledger uses).
GENESIS_HASH = "0" * 64
#: Hashed into every body, so a later change of the field set is a new schema, not a
#: silent re-definition of the old rows.
EVENT_CHAIN_SCHEMA = "crb.events.chain.v1"
#: Every ``events`` column a row's hash covers — all of them but the database id and the
#: two chain columns. ``payload`` is the ``payload_json`` column.
EVENT_CHAIN_FIELDS: tuple[str, ...] = (
    "event_id",
    "trace_id",
    "seq",
    "timestamp",
    "stage",
    "action",
    "status",
    "step_id",
    "parent_step_id",
    "actor",
    "repo",
    "task_id",
    "input_ref",
    "output_ref",
    "error_code",
    "error_message",
    "duration_ms",
    "cost_usd",
    "payload",
)
#: ``events`` columns deliberately left OUT of the hash (besides the id and the chain). Empty:
#: every column is hashed. A test holds ``EVENT_CHAIN_FIELDS`` plus this tuple to the table's
#: columns (P-124), so a new column is a reviewed decision — hashed under a new schema, or
#: named here with the reason in ADR-0041 — never an edit the walk cannot see.
EVENT_CHAIN_UNHASHED: tuple[str, ...] = ()
_INT_FIELDS = frozenset({"seq", "duration_ms"})


def _normal(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _INT_FIELDS:
        return int(value)
    if key == "cost_usd":
        return float(value)
    if key == "payload":
        return json.loads(json.dumps(dict(value)))
    return str(value)


def event_body(values: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical body of one event row, from its stored values. ``values`` is a row
    mapping (``payload`` or the column name ``payload_json``); a missing field reads as
    ``None`` so a tampered row hashes (wrongly) rather than raising."""
    body: dict[str, Any] = {"schema": EVENT_CHAIN_SCHEMA}
    for key in EVENT_CHAIN_FIELDS:
        raw = values.get(key)
        if key == "payload" and raw is None:
            raw = values.get("payload_json")
        body[key] = _normal(key, raw)
    return body


def event_row_hash(values: Mapping[str, Any], prev_hash: str) -> str:
    """The ``row_hash`` of an event row chained onto ``prev_hash``."""
    return sha256_text(canonical_json({**event_body(values), "prev_hash": prev_hash}))


@dataclass(frozen=True)
class EventChainReport:
    """What a walk of the ``events`` chain found. ``head`` is the last row's ``row_hash``
    (``""`` when the table is empty) — the value to record outside the store."""

    rows: int
    ok: bool
    broken_at: int | None
    detail: str
    head: str
    #: ``full`` — every row re-hashed from genesis; ``tail`` — only the rows appended since
    #: the last full walk, from its head (``crb.store.events.EventChainVerifier``).
    walk: str = "full"
    #: How many rows this walk re-hashed (``rows`` on a full walk).
    walked: int = 0
    #: When the last FULL walk behind this report ran (ISO 8601, UTC; ``""`` = not stamped).
    full_walk_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "chain_ok": self.ok,
            "broken_at": self.broken_at,
            "detail": self.detail,
            "head_row_hash": self.head,
            "walk": self.walk,
            "full_walk_at": self.full_walk_at,
        }


def walk_event_chain(
    rows: Iterable[Mapping[str, Any]], *, prev: str = GENESIS_HASH, verified: int = 0
) -> EventChainReport:
    """Walk stored rows in id order: every ``prev_hash`` must be the previous ``row_hash``
    (genesis first) and every ``row_hash`` must recompute. Never raises; the first break is
    reported by row id — an edited row as ``row_hash mismatch``, a row deleted from the
    middle or moved as ``prev_hash mismatch`` at the row that follows the gap.

    ``prev`` and ``verified`` resume a walk: the rows given follow ``verified`` rows already
    walked intact, the last of which hashed to ``prev`` (a tail walk)."""
    n = verified
    broken_at: int | None = None
    detail = ""
    head = prev if verified else ""
    for row in rows:
        n += 1
        rid = int(row.get("id") or n)
        stored_prev = str(row.get("prev_hash") or "")
        stored_hash = str(row.get("row_hash") or "")
        if broken_at is None:
            if stored_prev != prev:
                broken_at = rid
                detail = (
                    f"event id {rid}: prev_hash mismatch (a row before it was removed or moved)"
                )
            elif stored_hash != event_row_hash(row, stored_prev):
                broken_at = rid
                detail = f"event id {rid}: row_hash mismatch (the row was edited)"
        prev = stored_hash
        head = stored_hash
    if broken_at is None:
        detail = f"{n} events, chain intact"
    return EventChainReport(
        rows=n,
        ok=broken_at is None,
        broken_at=broken_at,
        detail=detail,
        head=head,
        walk="tail" if verified else "full",
        walked=n - verified,
    )


__all__ = [
    "EVENT_CHAIN_FIELDS",
    "EVENT_CHAIN_SCHEMA",
    "EVENT_CHAIN_UNHASHED",
    "GENESIS_HASH",
    "EventChainReport",
    "event_body",
    "event_row_hash",
    "walk_event_chain",
]
