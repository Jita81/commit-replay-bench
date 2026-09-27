"""The ``events`` chain's hash rule and walk (ADR-0041, backlog F51), without a database.

Navigation
----------
What it is:   The unit suite for ``crb.core.event_chain`` — the body an event row hashes and
              the walk that proves the audit trail was not altered.
What it does: Pins that the body covers every hashed field and normalises values to what a
              database hands back (``1`` and ``1.0`` in ``cost_usd``, a tuple in the payload),
              that a chain built from genesis walks intact and serves its head, and that an
              edited, a deleted and a reordered row are each reported at the right id with
              the walk still counting every row.
How:          Plain dict rows chained by ``event_row_hash``; each tamper is applied to a copy.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0041-the-audit-trail-is-hash-chained.md
Works with:   src/crb/core/event_chain.py (under test), src/crb/core/evidence.py (the
              canonical JSON and SHA-256 the rule hashes with), tests/test_store_events_chain.py
              (the same rule against SQLite and PostgreSQL), tests/test_store_migrate.py (the
              revision's frozen copy of the rule, held to this one)
Tested by:    tests/test_event_chain.py
Touch when:   the hashed field set or its normalisation changes (a new chain schema).
"""

from __future__ import annotations

from typing import Any

from crb.core.event_chain import (
    EVENT_CHAIN_FIELDS,
    GENESIS_HASH,
    event_body,
    event_row_hash,
    walk_event_chain,
)


def _row(i: int, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": i,
        "event_id": f"{i:032x}",
        "trace_id": "t" * 32,
        "seq": i,
        "timestamp": "2026-09-27T10:00:00+00:00",
        "stage": "system",
        "action": "user.login",
        "status": "ok",
        "step_id": "",
        "parent_step_id": "",
        "actor": "u1",
        "repo": "",
        "task_id": "",
        "input_ref": "",
        "output_ref": "",
        "error_code": "",
        "error_message": "",
        "duration_ms": None,
        "cost_usd": None,
        "payload_json": {"method": "local"},
    }
    base.update(kw)
    return base


def _chain(n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prev = GENESIS_HASH
    for i in range(1, n + 1):
        r = _row(i)
        r["prev_hash"] = prev
        r["row_hash"] = event_row_hash(r, prev)
        prev = r["row_hash"]
        rows.append(r)
    return rows


def test_the_body_covers_every_field_and_normalises_to_what_a_database_returns() -> None:
    body = event_body(_row(1))
    assert set(body) == {"schema", *EVENT_CHAIN_FIELDS}
    # a REAL column hands back 1.0 for 1; a JSON column a list for a tuple
    assert event_body(_row(1, cost_usd=1)) == event_body(_row(1, cost_usd=1.0))
    assert event_body(_row(1, payload_json={"a": (1, 2)})) == event_body(
        _row(1, payload_json={"a": [1, 2]})
    )
    assert event_row_hash(_row(1), GENESIS_HASH) != event_row_hash(_row(1), "1" * 64)


def test_an_intact_chain_walks_and_serves_its_head() -> None:
    rows = _chain(4)
    report = walk_event_chain(rows)
    assert report.ok and report.rows == 4 and report.broken_at is None
    assert report.head == rows[-1]["row_hash"]
    assert walk_event_chain([]).head == "" and walk_event_chain([]).ok


def test_an_edited_row_is_reported_at_its_own_id() -> None:
    rows = _chain(4)
    rows[1] = {**rows[1], "actor": "someone-else"}
    report = walk_event_chain(rows)
    assert not report.ok and report.broken_at == 2 and "edited" in report.detail
    assert report.rows == 4


def test_a_deleted_row_is_reported_at_the_row_after_the_gap() -> None:
    rows = _chain(4)
    del rows[1]
    report = walk_event_chain(rows)
    assert not report.ok and report.broken_at == 3 and "prev_hash" in report.detail


def test_a_reordered_row_is_reported() -> None:
    rows = _chain(4)
    rows[1], rows[2] = rows[2], rows[1]
    report = walk_event_chain(rows)
    assert not report.ok and report.broken_at == 3


def test_a_rechained_forgery_that_skips_the_head_still_verifies_so_the_head_is_the_anchor() -> None:
    """The chain alone cannot see a table replaced wholesale: a forger who rewrites every
    hash gets an intact walk. Only a head recorded outside the store tells them apart
    (G-601) — so the report serves it."""
    real = _chain(3)
    forged: list[dict[str, Any]] = []
    prev = GENESIS_HASH
    for r in real:
        f = {**r, "actor": "forger"}
        f["prev_hash"] = prev
        f["row_hash"] = event_row_hash(f, prev)
        prev = f["row_hash"]
        forged.append(f)
    report = walk_event_chain(forged)
    assert report.ok and report.head != walk_event_chain(real).head
