"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Rules for crb migrations (docs/ARCHITECTURE.md §7.3, ADR-0002):
* append-only tables (``grades``, ``events``, ``signoffs``, ``evidence``) are never
  rewritten — a migration may ADD nullable columns or indexes, never drop or alter rows;
* after any change to an append-only table, re-run
  ``crb.store.migrate.install_append_only_triggers_on(op.get_bind())``;
* ``downgrade`` must be real or must raise — never a silent ``pass`` on a data table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
