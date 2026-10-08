"""events.prev_hash / events.row_hash — the audit trail becomes a hash chain (ADR-0029, F51)

Navigation
----------
What it is:   Revision 0013: the two chain columns on ``events`` and the chaining of every row
              that existed before them.
What it does: Adds ``prev_hash`` and ``row_hash`` (``VARCHAR(64) NOT NULL``, server default
              ``''`` so a populated table can take them), chains the existing rows in id
              order from the genesis hash — deterministically: the same rows give the same
              hashes on any run, on either dialect — then drops the server default and adds
              a CHECK that each column holds 64 characters (so a writer that names no chain
              column, the release before this one included, is refused row by row — P-254),
              and adds the unique indexes on both columns (one successor per row, so the
              chain cannot fork). ``events`` is append-only, so its UPDATE trigger is dropped
              for the back-fill and the triggers are re-installed at the end, in the same
              transaction on PostgreSQL. ``downgrade`` drops the indexes, the CHECK and the
              columns; the events themselves stay. Filling the new columns of existing rows is
              the store rule's one recorded exception (ADR-0029 §3, DL-350): every column a
              row held before this revision stays byte for byte as it was.
How:          ``op.add_column`` twice (skipped when ``init_db`` already made them) → drop
              ``events_no_update`` → read the rows in id pages and ``UPDATE`` each by id with
              the hashes of a FROZEN copy of the chain rule (``_row_hash``; a released
              revision imports nothing of the product's runtime, and a test holds this copy
              to ``crb.core.event_chain``) → ``batch_alter_table`` (no default, the CHECK;
              a table rebuild on SQLite, copied from a pinned table offline) →
              ``op.create_index`` twice →
              ``install_append_only_triggers_on``. Offline (``--sql``) there are no rows to
              read, so the back-fill is skipped.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Event.prev_hash`` / ``Event.row_hash`` are declared
              LAST so the column order matches), src/crb/store/migrate.py
              (``REVISION_MARKERS`` carries ``("0013", "events", "row_hash")``; the trigger
              helper), src/crb/core/event_chain.py (the runtime rule this file copies),
              src/crb/store/events.py (chains every row written after this revision)
Tested by:    tests/test_store_migrate.py
Touch when:   never for a new repository; never — a released revision is immutable (stream I of the
              north-star Wave 2 held a temporary id; the Wave 2 integration numbered it 0013 on
              0012).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "events"
#: The append-only tables that exist at this revision (pinned; see 0001).
APPEND_ONLY_AT_0013: tuple[str, ...] = (
    "grades",
    "events",
    "signoffs",
    "evidence",
    "reviews",
    "task_qualifications",
)
PREV_INDEX = "uq_events_prev_hash"
#: P-254: after the back-fill both chain columns lose the server default and must hold a
#: SHA-256, so a writer that names no chain column (the release before this revision, still
#: running during the upgrade or after a rollback) is refused for that row instead of
#: storing a head of '' that no later write can chain onto. Pinned text, not imported.
CHECK_NAME = "ck_events_chain_hashes"
CHECK_SQL = "length(prev_hash) = 64 AND length(row_hash) = 64"
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


def _events_at_0013(*, checked: bool) -> sa.Table:
    """The whole ``events`` table at this revision, pinned — what an OFFLINE (``--sql``)
    SQLite rebuild copies from, since there is no database to reflect. ``checked`` is the
    state after this revision (no default, the CHECK); otherwise the state before it."""
    default = None if checked else sa.text("''")
    s64 = sa.String(64)
    cols: list[Any] = [
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(32), nullable=False, unique=True),
        sa.Column("trace_id", sa.String(32), nullable=False, index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("action", s64, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("step_id", s64, nullable=False),
        sa.Column("parent_step_id", s64, nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("repo", s64, nullable=False, index=True),
        sa.Column("task_id", s64, nullable=False),
        sa.Column("input_ref", sa.Text, nullable=False),
        sa.Column("output_ref", sa.Text, nullable=False),
        sa.Column("error_code", s64, nullable=False),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("payload_json", sa.JSON, nullable=False),
        sa.Column("prev_hash", s64, nullable=False, server_default=default),
        sa.Column("row_hash", s64, nullable=False, server_default=default),
        sa.Index("uq_events_trace_seq", "trace_id", "seq", unique=True),
    ]
    if checked:
        cols.append(sa.CheckConstraint(CHECK_SQL, name=CHECK_NAME))
    return sa.Table(TABLE, sa.MetaData(), *cols)


def _copy_from(*, checked: bool) -> sa.Table | None:
    offline_sqlite = context.is_offline_mode() and op.get_context().dialect.name == "sqlite"
    return _events_at_0013(checked=checked) if offline_sqlite else None


def _checks() -> set[str]:
    if context.is_offline_mode():
        return set()
    return {str(ck["name"]) for ck in sa.inspect(op.get_bind()).get_check_constraints(TABLE)}


def upgrade() -> None:
    """Add the columns, chain the rows already there, refuse an unchained row from then on,
    then make each link unique."""
    cols = _columns()
    added = False
    for name in ("prev_hash", "row_hash"):
        if name not in cols:
            op.add_column(TABLE, sa.Column(name, sa.String(64), nullable=False, server_default=""))
            added = True
    if not context.is_offline_mode():
        bind = op.get_bind()
        _drop_update_trigger(bind)
        _chain_existing_rows(bind)
    if added or CHECK_NAME not in _checks():
        # SQLite rebuilds the table (move and copy; the copy fires no row trigger and the
        # indexes are re-created from the reflection); PostgreSQL alters it in place
        with op.batch_alter_table(TABLE, copy_from=_copy_from(checked=False)) as batch:
            for name in ("prev_hash", "row_hash"):
                batch.alter_column(
                    name, existing_type=sa.String(64), existing_nullable=False, server_default=None
                )
            if CHECK_NAME not in _checks():
                batch.create_check_constraint(CHECK_NAME, sa.text(CHECK_SQL))
    names = _indexes()
    if PREV_INDEX not in names:
        op.create_index(PREV_INDEX, TABLE, ["prev_hash"], unique=True)
    if ROW_INDEX not in names:
        op.create_index(ROW_INDEX, TABLE, ["row_hash"], unique=True)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0013)


def downgrade() -> None:
    """Drop the indexes and the chain columns; every event row stays as it was."""
    names = _indexes()
    for ix in (ROW_INDEX, PREV_INDEX):
        if ix in names or context.is_offline_mode():
            op.drop_index(ix, table_name=TABLE)
    cols = _columns()
    checks = _checks()
    # batch mode is "move and copy" on SQLite (the only way to drop a column there) and a
    # plain ALTER elsewhere; the copy fires no row trigger, and the triggers are re-installed
    with op.batch_alter_table(TABLE, copy_from=_copy_from(checked=True)) as batch:
        if CHECK_NAME in checks or context.is_offline_mode():
            batch.drop_constraint(CHECK_NAME, type_="check")
        for name in ("row_hash", "prev_hash"):
            if name in cols or context.is_offline_mode():
                batch.drop_column(name)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0013)
