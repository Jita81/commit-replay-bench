"""events.prev_hash / events.row_hash — the audit trail becomes a hash chain (ADR-0041, F51)

Navigation
----------
What it is:   Revision 0031: the two chain columns on ``events`` and the chaining of every row
              that existed before them.
What it does: Adds ``prev_hash`` and ``row_hash`` (``VARCHAR(64) NOT NULL``, server default
              ``''`` so a populated table can take them), chains the existing rows in id
              order from the genesis hash — deterministically: the same rows give the same
              hashes on any run, on either dialect — and then adds the unique indexes on
              both columns (one successor per row, so the chain cannot fork). ``events`` is
              append-only, so its UPDATE trigger is dropped for the back-fill and the
              triggers are re-installed at the end, in the same transaction on PostgreSQL.
              ``downgrade`` drops the indexes and the columns; the events themselves stay.
How:          ``op.add_column`` twice (skipped when ``init_db`` already made them) → drop
              ``events_no_update`` → read the rows in id pages and ``UPDATE`` each by id with
              the hashes of a FROZEN copy of the chain rule (``_row_hash``; a released
              revision imports nothing of the product's runtime, and a test holds this copy
              to ``crb.core.event_chain``) → ``op.create_index`` twice →
              ``install_append_only_triggers_on``. Offline (``--sql``) there are no rows to
              read, so the back-fill is skipped.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0041-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Event.prev_hash`` / ``Event.row_hash`` are declared
              LAST so the column order matches), src/crb/store/migrate.py
              (``REVISION_MARKERS`` carries ``("0031", "events", "row_hash")``; the trigger
              helper), src/crb/core/event_chain.py (the runtime rule this file copies),
              src/crb/store/events.py (chains every row written after this revision)
Tested by:    tests/test_store_migrate.py
Touch when:   never — a released revision is immutable. This id is temporary (stream I of the
              north-star Wave 2); at integration it is renumbered to follow the head it lands
              on and its ``down_revision`` re-pointed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0031"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "events"
#: The append-only tables that exist at this revision (pinned; see 0001).
APPEND_ONLY_AT_0031: tuple[str, ...] = (
    "grades",
    "events",
    "signoffs",
    "evidence",
    "reviews",
    "task_qualifications",
)
PREV_INDEX = "uq_events_prev_hash"
ROW_INDEX = "uq_events_row_hash"
BATCH = 1000

# --- the chain rule of 2026-09-27, frozen (crb.core.event_chain, schema v1) ----------------
GENESIS_HASH = "0" * 64
CHAIN_SCHEMA = "crb.events.chain.v1"
CHAIN_FIELDS: tuple[str, ...] = (
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


def _normal(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in ("seq", "duration_ms"):
        return int(value)
    if key == "cost_usd":
        return float(value)
    if key == "payload":
        return json.loads(json.dumps(dict(value)))
    return str(value)


def _row_hash(values: Mapping[str, Any], prev_hash: str) -> str:
    """The ``row_hash`` of one stored row chained onto ``prev_hash`` (frozen copy)."""
    body: dict[str, Any] = {"schema": CHAIN_SCHEMA}
    for key in CHAIN_FIELDS:
        raw = values.get("payload_json") if key == "payload" else values.get(key)
        body[key] = _normal(key, raw)
    body["prev_hash"] = prev_hash
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------

_EVENTS = sa.table(
    TABLE,
    sa.column("id", sa.Integer),
    *(
        sa.column(k, sa.String)
        for k in CHAIN_FIELDS
        if k not in ("seq", "duration_ms", "cost_usd", "payload")
    ),
    sa.column("seq", sa.Integer),
    sa.column("duration_ms", sa.Integer),
    sa.column("cost_usd", sa.Float),
    sa.column("payload_json", sa.JSON),
    sa.column("prev_hash", sa.String),
    sa.column("row_hash", sa.String),
)


def _columns() -> set[str]:
    if context.is_offline_mode():
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _indexes() -> set[str]:
    if context.is_offline_mode():
        return set()
    return {str(ix["name"]) for ix in sa.inspect(op.get_bind()).get_indexes(TABLE)}


def _drop_update_trigger(bind: sa.Connection) -> None:
    on = " ON events" if bind.dialect.name == "postgresql" else ""
    bind.execute(sa.text(f"DROP TRIGGER IF EXISTS events_no_update{on}"))


def _chain_existing_rows(bind: sa.Connection) -> int:
    """Chain every row in id order from genesis; returns how many were chained."""
    prev = GENESIS_HASH
    last = 0
    n = 0
    while True:
        rows = list(
            bind.execute(
                sa.select(_EVENTS).where(_EVENTS.c.id > last).order_by(_EVENTS.c.id).limit(BATCH)
            ).mappings()
        )
        if not rows:
            return n
        for row in rows:
            h = _row_hash(dict(row), prev)
            bind.execute(
                sa.update(_EVENTS)
                .where(_EVENTS.c.id == row["id"])
                .values(prev_hash=prev, row_hash=h)
            )
            prev = h
            n += 1
        last = int(rows[-1]["id"])


def upgrade() -> None:
    """Add the columns, chain the rows already there, then make each link unique."""
    cols = _columns()
    for name in ("prev_hash", "row_hash"):
        if name not in cols:
            op.add_column(TABLE, sa.Column(name, sa.String(64), nullable=False, server_default=""))
    if not context.is_offline_mode():
        bind = op.get_bind()
        _drop_update_trigger(bind)
        _chain_existing_rows(bind)
    names = _indexes()
    if PREV_INDEX not in names:
        op.create_index(PREV_INDEX, TABLE, ["prev_hash"], unique=True)
    if ROW_INDEX not in names:
        op.create_index(ROW_INDEX, TABLE, ["row_hash"], unique=True)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0031)


def downgrade() -> None:
    """Drop the indexes and the chain columns; every event row stays as it was."""
    names = _indexes()
    for ix in (ROW_INDEX, PREV_INDEX):
        if ix in names or context.is_offline_mode():
            op.drop_index(ix, table_name=TABLE)
    cols = _columns()
    # batch mode is "move and copy" on SQLite (the only way to drop a column there) and a
    # plain ALTER elsewhere; the copy fires no row trigger, and the triggers are re-installed
    with op.batch_alter_table(TABLE) as batch:
        for name in ("row_hash", "prev_hash"):
            if name in cols or context.is_offline_mode():
                batch.drop_column(name)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0031)
