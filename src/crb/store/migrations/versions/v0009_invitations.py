"""invitations — the one-time invitation that brings the second person in (G-518)

Navigation
----------
What it is:   Revision 0009: the ``invitations`` table — ``id``, ``user_id``, ``token_hash``,
              ``role``, ``created``, ``expires``, ``accepted``, ``revoked``, ``created_by``,
              ``revoked_reason``, with a unique index on the token hash.
What it does: Lets a deployment invite its approver instead of asking an admin to type a
              password on somebody else's behalf: the account is created inactive with a
              password nobody knows, the token is handed over once and kept only as a
              SHA-256 hash, and accepting it sets the person's own password and activates the
              account. Before this table, inviting the second person was an out-of-band act
              nothing recorded (G-518).
How:          ``op.create_table`` guarded by an existence check (an ``init_db`` schema from
              this release already has it); offline (``--sql``) emits the whole table;
              ``downgrade`` drops it — allowed, because an invitation is mutable state and
              the audit trail lives in the append-only ``events`` table, not here.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         none
Works with:   src/crb/store/models.py (``Invitation``), src/crb/store/migrate.py
              (``REVISION_TABLES`` carries ``("0009", "invitations")``),
              src/crb/server/routes/invitations.py (the routes that write it),
              src/crb/server/routes/admin.py (``record_user_event`` — the audit trail)
Tested by:    tests/test_store_migrate.py, tests/test_server_invitations.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "invitations"


def _table_exists() -> bool:
    if context.is_offline_mode():
        return False
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Create ``invitations`` unless ``init_db`` already did."""
    if _table_exists():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("expires", sa.String(length=40), nullable=False),
        sa.Column("accepted", sa.String(length=40), nullable=False),
        sa.Column("revoked", sa.String(length=40), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("revoked_reason", sa.Text(), nullable=False),
        # inline, not an ALTER: SQLite cannot add a constraint to an existing table
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_user", TABLE, ["user_id"])


def downgrade() -> None:
    """Drop the table — mutable invitations; the audit trail is on ``events``."""
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
