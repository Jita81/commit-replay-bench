"""library_acts — the context library's append-only, hash-chained acts (ADR-0026 item 10)

Navigation
----------
What it is:   Revision 0043: the append-only ``library_acts`` table — every act on a
              repository's context library (propose, sponsor, sign, stale, revoke, retire).
What it does: Creates the table (unless ``init_db`` already did) with its lookup index, and
              installs the grades table's UPDATE/DELETE-refusing triggers on it (SQLite and
              PostgreSQL), so a signature, a revocation or a retirement can only ever be
              appended. ``downgrade`` refuses while any act exists — an append-only table's
              rows are never dropped (0011's pattern) — and otherwise drops the table.
How:          ``op.create_table`` + ``install_append_only_triggers_on`` on Alembic's own
              connection; the append-only tuple is pinned in this file, as every revision
              pins its own.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0026-the-context-standard.md (item 10),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``LibraryActRow``; ``APPEND_ONLY_TABLES``),
              src/crb/store/migrate.py (``REVISION_TABLES`` carries
              ``("0043", "library_acts")``; the trigger helper),
              src/crb/store/library.py (appends and reads the acts),
              src/crb/core/library.py (the act a row holds)
Tested by:    tests/test_store_migrate.py, tests/test_store_library.py
Touch when:   never — a released revision is immutable. The number is stream L's
              reservation in north-star Wave 4; at merge this revision's ``down_revision`` is
              re-pointed at the head it lands on, and the integration renumbers it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0043"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "library_acts"
#: The append-only tables that exist once this revision is applied (pinned; see 0001).
APPEND_ONLY_AT_0043: tuple[str, ...] = (
    "grades",
    "events",
    "signoffs",
    "evidence",
    "reviews",
    "task_qualifications",
    TABLE,
)


def _table_exists() -> bool:
    if context.is_offline_mode():
        return False
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Create ``library_acts`` (unless ``init_db`` already did) and protect it."""
    if not _table_exists():
        op.create_table(
            TABLE,
            sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("act_id", sa.String(length=32), nullable=False),
            sa.Column("schema", sa.String(length=32), nullable=False),
            sa.Column("repo", sa.String(length=64), nullable=False),
            sa.Column("entry_id", sa.String(length=96), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("act", sa.String(length=16), nullable=False),
            sa.Column("actor", sa.String(length=128), nullable=False),
            sa.Column("body_json", sa.JSON(), nullable=False),
            sa.Column("created", sa.String(length=40), nullable=False),
            sa.Column("prev_hash", sa.String(length=64), nullable=False),
            sa.Column("row_hash", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("seq"),
            sa.UniqueConstraint("act_id"),
            sa.UniqueConstraint("row_hash"),
        )
        op.create_index(
            "ix_library_acts_repo_entry", TABLE, ["repo", "entry_id", "seq"], unique=False
        )
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0043)


def downgrade() -> None:
    """Refused while any act exists: a signature or a revocation is a record two people
    made, and an append-only table's rows are never dropped. An empty table goes with its
    triggers. Offline (``--sql``) there is nothing to count: the script drops the table
    and whoever runs it owns that check."""
    if not context.is_offline_mode() and _table_exists():
        n: int = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM library_acts")).scalar_one()
        if n:
            raise RuntimeError(
                f"refusing to downgrade 0043: {n} library act(s) exist — signatures and "
                "revocations are never dropped"
            )
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
