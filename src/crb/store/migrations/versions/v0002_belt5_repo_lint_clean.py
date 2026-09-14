"""belt 5 — ``grades.repo_lint_clean`` (nullable), apparatus 2.2 / ``belt_set="v5"``

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14 12:00:00+00:00

ADR-0011: the repository's own formatter/linter becomes belt 5. The ledger gains ONE
nullable column; nothing else moves. Every existing row keeps ``NULL`` there, which for a
``v3-legacy`` / ``v4`` row means *unrecorded* (the apparatus had no belt 5) and for a
``v5`` row means *not evaluated* (the repository configures no linter) — ``belt_set``
says which, and :meth:`crb.core.ledger.GradeRow.body` hashes the column only for ``v5``
rows, so every row written before this revision still verifies byte-for-byte.

Rules for crb migrations (docs/ARCHITECTURE.md §7.3, ADR-0002):
* append-only tables (``grades``, ``events``, ``signoffs``, ``evidence``) are never
  rewritten — a migration may ADD nullable columns or indexes, never drop or alter rows;
* after any change to an append-only table, re-run
  ``crb.store.migrate.install_append_only_triggers_on(op.get_bind(), <tables>)`` with the
  append-only tables that exist AT THAT REVISION (pinned in the script);
* ``downgrade`` must be real or must raise — never a silent ``pass`` on a data table.

``ALTER TABLE … ADD COLUMN`` is in-place on both SQLite and PostgreSQL: no row is
rewritten and no trigger fires. The triggers are re-asserted anyway (rule 2).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The append-only tables that exist at this revision (pinned; see 0001).
APPEND_ONLY_AT_0002: tuple[str, ...] = ("grades", "events", "signoffs", "evidence")


def upgrade() -> None:
    op.add_column("grades", sa.Column("repo_lint_clean", sa.Boolean(), nullable=True))
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0002)


def downgrade() -> None:
    """Refused while any ``v5`` row exists: dropping the column would erase a recorded
    belt from evidence. With no ``v5`` row the column is empty and may go."""
    bind = op.get_bind()
    n = bind.execute(sa.text("SELECT COUNT(*) FROM grades WHERE belt_set = 'v5'")).scalar_one()
    if n:
        raise RuntimeError(
            f"refusing to downgrade 0002: {n} grade row(s) record belt 5 (belt_set='v5')"
        )
    # batch mode is "move and copy" on SQLite (the only way to drop a column there) and a
    # plain ALTER elsewhere; the copy is an INSERT … SELECT + DROP TABLE, which fires no
    # row trigger, and the triggers are re-installed on the new table below.
    with op.batch_alter_table("grades") as batch:
        batch.drop_column("repo_lint_clean")
    install_append_only_triggers_on(bind, APPEND_ONLY_AT_0002)
