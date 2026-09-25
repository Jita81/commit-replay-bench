"""users.session_nonce — the per-account value that ends every session when it is rotated

Navigation
----------
What it is:   Revision 0009: ``users.session_nonce`` (``VARCHAR(64) NOT NULL DEFAULT ''``) —
              part of the credential version a session cookie is bound to.
What it does: Lets the server end a stateless session: logout and "sign out everywhere"
              rotate the account's nonce, which moves ``credential_version`` and refuses
              every cookie issued before (assessment 2026-09-25, D4). Every existing row
              reads ``''``, and an empty nonce leaves the version as it was, so the upgrade
              signs nobody out. Mutable account state, not evidence: no append-only
              triggers; ``downgrade`` drops the column.
How:          ``op.add_column`` guarded by an existence check (an ``init_db`` schema from this
              release already has it); the downgrade uses batch mode (SQLite's move-and-copy).
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         none
Works with:   src/crb/store/models.py (``User.session_nonce``), src/crb/store/migrate.py
              (``REVISION_MARKERS`` carries ``("0009", "users", "session_nonce")``),
              src/crb/server/auth.py (``credential_version`` / ``rotate_session_nonce``),
              src/crb/server/routes/auth.py (logout rotates it), src/crb/server/routes/admin.py
              (``POST /users/{id}/sessions/revoke`` rotates it)
Tested by:    tests/test_store_migrate.py, tests/test_server_auth.py
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

TABLE = "users"
COLUMN = "session_nonce"


def _column_exists() -> bool:
    if context.is_offline_mode():
        return False
    insp = sa.inspect(op.get_bind())
    return TABLE in insp.get_table_names() and COLUMN in {
        c["name"] for c in insp.get_columns(TABLE)
    }


def upgrade() -> None:
    """Add the nonce unless ``init_db`` already did; every existing row reads ``''``."""
    if _column_exists():
        return
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Drop the column — every rotated account's sessions end once more, nothing else."""
    if not _column_exists() and not context.is_offline_mode():
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
