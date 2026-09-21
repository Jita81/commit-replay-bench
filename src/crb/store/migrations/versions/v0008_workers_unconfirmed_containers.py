"""workers.unconfirmed_containers — how many killed-but-unconfirmed containers a worker is reaping

Navigation
----------
What it is:   Revision 0008: ``workers.unconfirmed_containers`` (``INTEGER NOT NULL DEFAULT 0``)
              — the count the worker stamps on its check-in row from its reaper queue.
What it does: Lets the ``/health`` worker probe report ``unconfirmed_containers`` and read
              ``degraded`` while a container whose ``docker kill`` the daemon never confirmed is
              still being reaped (src/crb/server/reaper.py). Mutable liveness state, not
              evidence: no append-only triggers; ``downgrade`` drops the column.
How:          ``op.add_column`` guarded by an existence check (an ``init_db`` schema from this
              release already has it); the downgrade uses batch mode (SQLite's move-and-copy).
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/store/models.py (``WorkerRow.unconfirmed_containers``),
              src/crb/store/migrate.py (``REVISION_MARKERS`` carries
              ``("0008", "workers", "unconfirmed_containers")``), src/crb/server/worker.py
              (stamps it on check-in), src/crb/server/routes/system.py (the probe reads it),
              src/crb/store/migrations/versions/v0007_workers.py (the table it extends)
Tested by:    tests/test_store_migrate.py, tests/test_worker.py, tests/test_server_system.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "workers"
COLUMN = "unconfirmed_containers"


def _column_exists() -> bool:
    if context.is_offline_mode():
        return False
    insp = sa.inspect(op.get_bind())
    return TABLE in insp.get_table_names() and COLUMN in {
        c["name"] for c in insp.get_columns(TABLE)
    }


def upgrade() -> None:
    """Add the count unless ``init_db`` already did; every existing row reads 0."""
    if _column_exists():
        return
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Drop the column — a count the next check-in re-derives from the reaper's file."""
    if not _column_exists() and not context.is_offline_mode():
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
