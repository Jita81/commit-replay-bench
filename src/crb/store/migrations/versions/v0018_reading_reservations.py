"""events — one reading reservation per (reading, arm, commit): a partial unique index (P-792)

Navigation
----------
What it is:   Revision 0018: the partial unique index ``uq_events_reading_reserved`` on
              ``events(trace_id, step_id, task_id) WHERE action = 'reading.reserved'`` — the
              reading, the arm and the commit of a reservation.
What it does: Creates the index (unless ``init_db`` already did), so the database refuses a
              second reservation of one commit on one arm of one reading whatever wrote it:
              the backstop behind the reserver's check under the events lock (C1, C19).
              Only reservation rows are bound — every other event shares those columns
              freely — and no row is touched: the action is new, so there is nothing to
              back-fill, and a release before this one never wrote a reservation to collide.
              ``downgrade`` drops the index and keeps every row.
How:          ``op.create_index(unique=True)`` with the predicate as ``sqlite_where`` and
              ``postgresql_where``, guarded by ``sa.inspect``; the index name and predicate
              are pinned in this file, never read from the models. An index changes no
              trigger, so the append-only tuple is not re-installed here
              (``crb.store.migrate.upgrade`` re-asserts the triggers after every upgrade).
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/store/models.py (``Event.__table_args__`` declares the same index),
              src/crb/store/migrate.py (``REVISION_INDEXES`` carries it at 0018; the drift
              check compares its predicate, which ``compare_metadata`` does not read),
              src/crb/store/events.py (``append_event_checked`` raises ``ReservationExists``
              when it refuses), src/crb/core/reading.py (``READING_RESERVED_ACTION``),
              src/crb/store/migrations/versions/v0017_class_sets.py (the previous revision)
Tested by:    tests/test_p792_reserved_store.py, tests/test_store_migrate.py
Touch when:   never for a new repository; never — a released revision is immutable (a
              changed key or predicate is a new revision).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_events_reading_reserved"
#: The reservation's key: the reading (``trace_id``), the arm (``step_id``), the commit.
COLUMNS = ["trace_id", "step_id", "task_id"]
#: Pinned here, not read from ``crb.core.reading``: what a released revision writes must not
#: move when the product's constants do.
WHERE = "action = 'reading.reserved'"


def _index_names() -> set[str]:
    """Index names on ``events`` — empty offline (the emitted SQL carries the statement)."""
    if context.is_offline_mode():
        return set()
    return {str(ix["name"]) for ix in sa.inspect(op.get_bind()).get_indexes("events")}


def upgrade() -> None:
    """Create the reservation index unless ``init_db`` already did."""
    if INDEX not in _index_names():
        op.create_index(
            INDEX,
            "events",
            COLUMNS,
            unique=True,
            sqlite_where=sa.text(WHERE),
            postgresql_where=sa.text(WHERE),
        )


def downgrade() -> None:
    """Drop the index; every row stays (an index holds no record, so this is always
    allowed). The release before this one never reads a reservation."""
    if INDEX in _index_names() or context.is_offline_mode():
        op.drop_index(INDEX, table_name="events")
