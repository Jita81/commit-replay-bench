"""reviews — human post-hoc verdicts on graded rows (append-only, hash-chained)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14 18:00:00+00:00

ADR-0006 amendment / critical-friend review action #3: a human's verdict on an accepted
patch becomes a first-class ledger row. ONE new table, ``reviews`` (columns mirror
:class:`crb.core.review.ReviewRecord`), with its own ``prev_hash`` / ``row_hash`` chain
and the same append-only triggers as ``grades``. Nothing else moves.

Rules for crb migrations (docs/ARCHITECTURE.md §7.3, ADR-0002):
* append-only tables (``grades``, ``events``, ``signoffs``, ``evidence``, ``reviews``) are
  never rewritten — a migration may ADD nullable columns or indexes, never drop or alter
  rows;
* after any change to an append-only table, re-run
  ``crb.store.migrate.install_append_only_triggers_on(op.get_bind(), <tables>)`` with the
  tuple of append-only tables that exist AT THIS REVISION (pinned, not the live constant);
* ``downgrade`` must be real or must raise — never a silent ``pass`` on a data table.

The table is created only when absent: a database that ``init_db`` created under THIS
release already has it (adoption stamps such a database at the newest *column* marker,
0002, and replays this revision), and ``CREATE TABLE`` is not idempotent on either
dialect. Creating it twice would fail; skipping it when present changes nothing.

Navigation
----------
What it is:   Revision ``0003`` — the ``reviews`` table (human verdicts, append-only,
              hash-chained).
What it does: Creates ``reviews`` and its indexes when absent (an ``init_db`` database of this
              release already has it), then installs the triggers on the five append-only
              tables. ``downgrade`` refuses while any review exists.
How:          ``_reviews_table_exists`` (always ``False`` offline so the emitted SQL carries
              the CREATE) → ``op.create_table`` → ``install_append_only_triggers_on``.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Review``), src/crb/core/review.py (``ReviewRecord``
              — the columns), src/crb/store/ledger.py (``DbReviewLedger`` writes here),
              src/crb/store/migrate.py (the ``0003`` marker and ``REVISION_TABLES`` entry),
              src/crb/store/migrations/versions/v0002_belt5_repo_lint_clean.py (the previous
              revision)
Tested by:    tests/test_store_migrate.py, tests/test_store_reviews.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The append-only tables that exist once this revision is applied.
APPEND_ONLY_AT_0003: tuple[str, ...] = ("grades", "events", "signoffs", "evidence", "reviews")


def _reviews_table_exists() -> bool:
    """``False`` in offline (``--sql``) mode — there is no database to ask, and the
    emitted script must contain the CREATE."""
    if context.is_offline_mode():
        return False
    return "reviews" in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Create ``reviews`` (unless ``init_db`` already did) and protect it."""
    if not _reviews_table_exists():
        op.create_table(
            "reviews",
            sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("review_id", sa.String(length=32), nullable=False),
            sa.Column("schema", sa.String(length=32), nullable=False),
            sa.Column("grade_row_hash", sa.String(length=64), nullable=False),
            sa.Column("repo", sa.String(length=64), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("reviewer", sa.String(length=128), nullable=False),
            sa.Column("verdict", sa.String(length=16), nullable=False),
            sa.Column("findings_json", sa.JSON(), nullable=False),
            sa.Column("mergeable", sa.Boolean(), nullable=True),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("patch_sha256_reviewed", sa.String(length=64), nullable=False),
            sa.Column("evidence_pack_hash", sa.String(length=64), nullable=False),
            sa.Column("apparatus_version", sa.String(length=32), nullable=False),
            sa.Column("created", sa.String(length=40), nullable=False),
            sa.Column("prev_hash", sa.String(length=64), nullable=False),
            sa.Column("row_hash", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("seq"),
            sa.UniqueConstraint("review_id"),
            sa.UniqueConstraint("row_hash"),
        )
        op.create_index("ix_reviews_grade_row_hash", "reviews", ["grade_row_hash"], unique=False)
        op.create_index("ix_reviews_repo", "reviews", ["repo"], unique=False)
        op.create_index("ix_reviews_repo_task", "reviews", ["repo", "task_id"], unique=False)
        op.create_index("ix_reviews_task_id", "reviews", ["task_id"], unique=False)
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0003)


def downgrade() -> None:
    """Refused while any review exists: a review is governance evidence and no migration
    may destroy it (docs/DATA-RETENTION.md). An empty table may go."""
    bind = op.get_bind()
    n: int = bind.execute(sa.text("SELECT COUNT(*) FROM reviews")).scalar_one()
    if n:
        raise RuntimeError(f"refusing to downgrade 0003: {n} review row(s) would be destroyed")
    op.drop_table("reviews")
    install_append_only_triggers_on(bind, APPEND_ONLY_AT_0003[:-1])
