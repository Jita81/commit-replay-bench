"""workers — one liveness row per worker process, upserted every heartbeat even when idle

Navigation
----------
What it is:   Revision 0007: the ``workers`` table — ``worker_id``, ``hostname``, ``executor``,
              ``kinds``, ``started``, ``heartbeat``, ``heartbeat_s``, ``current_run_id``,
              ``version``, ``stopped``. Mutable state, not a ledger: no append-only triggers.
What it does: Gives ``/health`` a liveness source that exists while the worker is IDLE. Before
              this the probe read RUNNING runs' heartbeats only, so a crashed worker with three
              queued runs answered ``ok "idle, 3 queued"`` (J-TEL-2). The worker loop upserts
              its row every ``heartbeat_s``; the probe reports a worker seen within
              3 × ``heartbeat_s`` as alive and names a stale one.
How:          ``op.create_table`` guarded by an existence check (an ``init_db`` schema from
              this release already has it); offline (``--sql``) emits the whole table;
              ``downgrade`` drops it — allowed, because the rows are re-created by the next
              check-in and hold no evidence.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         none
Works with:   src/crb/store/models.py (``WorkerRow``), src/crb/store/migrate.py
              (``REVISION_TABLES`` carries ``("0007", "workers")``),
              src/crb/server/worker.py (upserts the row), src/crb/server/routes/system.py
              (the worker probe reads it)
Tested by:    tests/test_store_migrate.py, tests/test_worker.py, tests/test_server_system.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "workers"


def _table_exists() -> bool:
    if context.is_offline_mode():
        return False
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Create ``workers`` unless ``init_db`` already did."""
    if _table_exists():
        return
    op.create_table(
        TABLE,
        sa.Column("worker_id", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("hostname", sa.String(length=256), nullable=False),
        sa.Column("executor", sa.String(length=16), nullable=False),
        sa.Column("kinds", sa.JSON(), nullable=False),
        sa.Column("started", sa.String(length=40), nullable=False),
        sa.Column("heartbeat", sa.String(length=40), nullable=False),
        sa.Column("heartbeat_s", sa.Float(), nullable=False),
        sa.Column("current_run_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("stopped", sa.String(length=40), nullable=False),
    )


def downgrade() -> None:
    """Drop the table — liveness rows, re-created by the next check-in, never evidence."""
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
