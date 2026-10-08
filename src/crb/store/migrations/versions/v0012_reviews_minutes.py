"""reviews.minutes — the reviewer's own minutes on a review, stated on POST /reviews

Navigation
----------
What it is:   Revision 0012: ``reviews.minutes`` (``INTEGER NULL``) — how long a review took,
              in whole minutes, as the reviewer stated it (DL-067, G-557).
What it does: Lets the decide stream show the reviewer minutes each decision cost, from a
              figure the reviewer gave rather than one derived from timestamps. Every existing
              review reads ``NULL`` (not stated), and a record that states nothing hashes
              exactly as before, so the review chain still verifies. ``reviews`` is
              append-only: the triggers are re-installed after the change. ``downgrade`` is
              refused while any review states its minutes (dropping the column would erase a
              hashed field) and, on SQLite, while ``reviews`` holds any row (SQLite drops a
              column only by rewriting the table, and a migration never rewrites the rows
              of an append-only table); otherwise it drops the column.
How:          ``op.add_column`` guarded by an existence check (an ``init_db`` schema from this
              release already has it) → ``install_append_only_triggers_on`` with the tables of
              this revision; the downgrade counts the rows first, then uses batch mode
              (a plain ALTER on PostgreSQL; on SQLite the move-and-copy of an EMPTY table)
              and re-installs the triggers on the new table.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Review.minutes`` is declared LAST so the column order
              matches), src/crb/core/review.py (``ReviewRecord.minutes`` — hashed only when
              stated), src/crb/store/migrate.py (``REVISION_MARKERS`` carries
              ``("0012", "reviews", "minutes")``; the trigger helper),
              src/crb/server/routes/reviews.py (``POST /reviews`` takes the minutes)
Tested by:    tests/test_store_migrate.py
Touch when:   never for a new repository; never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "reviews"
COLUMN = "minutes"
#: The append-only tables that exist at this revision (pinned; see 0001).
APPEND_ONLY_AT_0012: tuple[str, ...] = (
    "grades",
    "events",
    "signoffs",
    "evidence",
    "reviews",
    "task_qualifications",
)


def _column_exists() -> bool:
    if context.is_offline_mode():
        return False
    insp = sa.inspect(op.get_bind())
    return TABLE in insp.get_table_names() and COLUMN in {
        c["name"] for c in insp.get_columns(TABLE)
    }


def upgrade() -> None:
    """Add the nullable column unless ``init_db`` already did; NULL on every existing row."""
    if not _column_exists():
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0012)


def downgrade() -> None:
    """Refused while any review states its minutes: the field is hashed, and dropping it
    would break every such record's chain hash. Refused on SQLite while ``reviews`` holds
    any row: SQLite drops a column only by copying every row into a new table (batch mode's
    move-and-copy, and its native ``DROP COLUMN`` alike), and a migration never rewrites the
    rows of an append-only table. PostgreSQL drops the column in place."""
    if not _column_exists() and not context.is_offline_mode():
        return
    bind = op.get_bind()
    n: int = bind.execute(
        sa.text("SELECT COUNT(*) FROM reviews WHERE minutes IS NOT NULL")
    ).scalar_one()
    if n:
        raise RuntimeError(f"refusing to downgrade 0012: {n} review(s) state their minutes")
    if bind.dialect.name == "sqlite":
        rows: int = bind.execute(sa.text("SELECT COUNT(*) FROM reviews")).scalar_one()
        if rows:
            raise RuntimeError(
                f"refusing to downgrade 0012 on SQLite: dropping the column would copy all "
                f"{rows} review(s) into a new table, and reviews is append-only"
            )
    # batch mode is "move and copy" on SQLite (here only ever of an empty table) and a plain
    # ALTER elsewhere; the triggers are re-installed on the table that results
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
    install_append_only_triggers_on(bind, APPEND_ONLY_AT_0012)
