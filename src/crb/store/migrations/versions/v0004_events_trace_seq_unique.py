"""events — ``(trace_id, seq)`` becomes UNIQUE (the SSE resume cursor's invariant)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15 23:30:00+00:00

``seq`` is the resume cursor: a client that reconnects with ``?after=<seq>`` gets every
event it has not seen. Two rows of one trace sharing a ``seq`` (a live emitter and an
out-of-band ``append_event`` allocating the same number) silently lose one of them on
resume. The store now refuses the duplicate at write and re-allocates under the write
lock (:class:`crb.store.events.DbEventSink`); this revision gives the database the same
rule (CodeRabbit on PR #4, 2026-09-15).

Rules for crb migrations (docs/ARCHITECTURE.md §7.3, ADR-0002):
* append-only tables (``grades``, ``events``, ``signoffs``, ``evidence``, ``reviews``) are
  never rewritten — a migration may ADD nullable columns or indexes, never drop or alter
  rows;
* after any change to an append-only table, re-run
  ``crb.store.migrate.install_append_only_triggers_on(op.get_bind(), <tables>)`` with the
  tuple of append-only tables that exist AT THIS REVISION (pinned, not the live constant);
* ``downgrade`` must be real or must raise — never a silent ``pass`` on a data table.

An index is added, no row is touched. A database that already holds a duplicate
``(trace_id, seq)`` pair cannot take the index and the rows cannot be renumbered
(append-only): the upgrade REFUSES with the offending traces so the operator can export
the ledger (``crb ledger export``) and decide — never guessed at. The index is created
only when absent: an ``init_db`` database of this release already carries it from the
model (``uq_events_trace_seq``), and adoption stamps such a database at the newest column
marker (0003) and replays this revision.

Navigation
----------
What it is:   Revision ``0004`` — the unique ``(trace_id, seq)`` index on ``events``.
What it does: Refuses when duplicates exist, drops the old non-unique ``ix_events_trace_seq``
              when present, creates ``uq_events_trace_seq`` when absent, re-asserts the
              append-only triggers. ``downgrade`` restores the non-unique index.
How:          ``_duplicate_pairs`` (a GROUP BY … HAVING COUNT(*) > 1) → ``op.drop_index`` /
              ``op.create_index(unique=True)`` guarded by ``sa.inspect`` →
              ``install_append_only_triggers_on``.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Event.__table_args__`` declares the same index),
              src/crb/store/events.py (``DbEventSink`` retries a collision under the lock),
              src/crb/store/migrate.py (``head_revision`` is now 0004),
              src/crb/store/migrations/versions/v0003_reviews.py (the previous revision)
Tested by:    tests/test_store_migrate.py, tests/test_store_events.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The append-only tables that exist once this revision is applied.
APPEND_ONLY_AT_0004: tuple[str, ...] = ("grades", "events", "signoffs", "evidence", "reviews")
OLD_INDEX = "ix_events_trace_seq"
UNIQUE_INDEX = "uq_events_trace_seq"


def _index_names() -> set[str]:
    """Index names on ``events`` — empty offline (the emitted SQL carries both statements)."""
    if context.is_offline_mode():
        return set()
    return {str(ix["name"]) for ix in sa.inspect(op.get_bind()).get_indexes("events")}


def _duplicate_pairs() -> list[tuple[str, int, int]]:
    """``(trace_id, seq, count)`` for every duplicated pair — none offline."""
    if context.is_offline_mode():
        return []
    rows = op.get_bind().execute(
        sa.text(
            "SELECT trace_id, seq, COUNT(*) AS n FROM events "
            "GROUP BY trace_id, seq HAVING COUNT(*) > 1 ORDER BY trace_id, seq"
        )
    )
    return [(str(t), int(s), int(n)) for t, s, n in rows]


def upgrade() -> None:
    """Make ``(trace_id, seq)`` unique; refuse (with the evidence) if it already is not."""
    dupes = _duplicate_pairs()
    if dupes:
        shown = ", ".join(f"{t[:12]}…#{s} x{n}" for t, s, n in dupes[:10])
        more = f" (+{len(dupes) - 10} more)" if len(dupes) > 10 else ""
        raise RuntimeError(
            f"refusing to upgrade 0004: events holds {len(dupes)} duplicated (trace_id, seq) "
            f"pair(s) — {shown}{more}. Rows are append-only, so this upgrade will not renumber "
            "them for you: back the database up, move the LATER row of each pair to the "
            "trace's max(seq)+1 as docs/DEPLOYMENT.md 'If revision 0004 refuses' shows, "
            "record the ids you moved, then re-run"
        )
    names = _index_names()
    if OLD_INDEX in names or context.is_offline_mode():
        op.drop_index(OLD_INDEX, table_name="events")
    if UNIQUE_INDEX not in names:
        op.create_index(UNIQUE_INDEX, "events", ["trace_id", "seq"], unique=True)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0004)


def downgrade() -> None:
    """Back to the non-unique index — no row is touched, so this is always allowed."""
    names = _index_names()
    if UNIQUE_INDEX in names or context.is_offline_mode():
        op.drop_index(UNIQUE_INDEX, table_name="events")
    if OLD_INDEX not in names:
        op.create_index(OLD_INDEX, "events", ["trace_id", "seq"], unique=False)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0004)
