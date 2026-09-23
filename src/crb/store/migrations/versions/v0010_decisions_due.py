"""decisions_due — when each decisions-inbox row first became due, and when it was last seen

Navigation
----------
What it is:   Revision 0010: the ``decisions_due`` table — ``id``, ``repo``, ``kind``, ``key``,
              ``title``, ``role``, ``first_due``, ``last_seen``, ``resolved``, unique on
              ``(repo, kind, key)``.
What it does: Gives the derived decisions inbox a memory (G-516). The rows are derived at read
              from the capability map, the sign-offs and the factory chain, so before this table
              a decision existed only while somebody had the page open and nothing could say a
              cell had been waiting eleven days for an approver. The worker refreshes it on its
              idle pass, so the clock runs with nobody watching.
How:          ``op.create_table`` guarded by an existence check (an ``init_db`` schema from this
              release already has it); offline (``--sql``) emits the whole table; ``downgrade``
              drops it — allowed, because it is a clock over a derivation and holds no evidence
              (the evidence is the ledger and the factory chain).
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         none
Works with:   src/crb/store/models.py (``DecisionDue``), src/crb/store/migrate.py
              (``REVISION_TABLES`` carries ``("0010", "decisions_due")``),
              src/crb/server/decisions.py (the derivation and the upsert),
              src/crb/server/routes/decisions.py (serves the age with the row)
Tested by:    tests/test_store_migrate.py, tests/test_server_decisions.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "decisions_due"


def _table_exists() -> bool:
    if context.is_offline_mode():
        return False
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Create ``decisions_due`` unless ``init_db`` already did."""
    if _table_exists():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("repo", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("first_due", sa.String(length=40), nullable=False),
        sa.Column("last_seen", sa.String(length=40), nullable=False),
        sa.Column("resolved", sa.String(length=40), nullable=False),
        # inline, not an ALTER: SQLite cannot add a constraint to an existing table
        sa.UniqueConstraint("repo", "kind", "key", name="uq_decisions_due_row"),
    )
    op.create_index("ix_decisions_due_repo", TABLE, ["repo"])


def downgrade() -> None:
    """Drop the table — a clock over a derivation; the evidence is elsewhere."""
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
