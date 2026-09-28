"""class_set_acts, class_labels — an organisation's class sets and the label table (ADR-0026 item 9)

Navigation
----------
What it is:   Revision 0047: the append-only ``class_set_acts`` table (every act on an
              organisation's class-set versions — propose, sign, revoke — hash-chained) and the
              append-only ``class_labels`` table (a task's class under one version: a person's
              label of a derivation commit, or the version's rule applied to a commit).
What it does: Creates both tables (unless ``init_db`` already did) with their lookup indexes,
              and installs the grades table's UPDATE/DELETE-refusing triggers on them, so a
              signature, a revocation or a label can only ever be appended — a relabel never
              rewrites anything. ``downgrade`` refuses while any row exists in either table
              and otherwise drops both.
How:          ``op.create_table`` + ``install_append_only_triggers_on`` on Alembic's own
              connection; the append-only tuple is pinned in this file, as every revision
              pins its own.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0026-the-context-standard.md (item 9),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``ClassSetActRow``, ``ClassLabelRow``;
              ``APPEND_ONLY_TABLES``), src/crb/store/migrate.py (``REVISION_TABLES`` carries
              both tables at 0047; the trigger helper), src/crb/store/class_sets.py (appends
              and reads them), src/crb/core/class_sets.py (the act a row holds)
Tested by:    tests/test_store_migrate.py, tests/test_store_class_sets.py
Touch when:   never for a new repository; never — a released revision is immutable (stream CLS
              of north-star Wave 4b; reserved as 0047, renumbered by the integration).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0047"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTS = "class_set_acts"
LABELS = "class_labels"
#: The append-only tables that exist once this revision is applied (pinned; see 0001).
APPEND_ONLY_AT_0047: tuple[str, ...] = (
    "grades",
    "events",
    "signoffs",
    "evidence",
    "reviews",
    "task_qualifications",
    "library_acts",
    ACTS,
    LABELS,
)


def _tables() -> set[str]:
    if context.is_offline_mode():
        return set()
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Create ``class_set_acts`` and ``class_labels`` (unless ``init_db`` already did) and
    protect both."""
    present = _tables()
    if ACTS not in present:
        op.create_table(
            ACTS,
            sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("act_id", sa.String(length=32), nullable=False),
            sa.Column("schema", sa.String(length=32), nullable=False),
            sa.Column("org", sa.String(length=48), nullable=False),
            sa.Column("version_id", sa.String(length=96), nullable=False),
            sa.Column("digest", sa.String(length=64), nullable=False),
            sa.Column("act", sa.String(length=16), nullable=False),
            sa.Column("actor", sa.String(length=128), nullable=False),
            sa.Column("body_json", sa.JSON(), nullable=False),
            sa.Column("created", sa.String(length=40), nullable=False),
            sa.Column("prev_hash", sa.String(length=64), nullable=False),
            sa.Column("row_hash", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("seq"),
            sa.UniqueConstraint("act_id"),
            sa.UniqueConstraint("row_hash"),
        )
        op.create_index(
            "ix_class_set_acts_org_version", ACTS, ["org", "version_id", "seq"], unique=False
        )
    if LABELS not in present:
        op.create_table(
            LABELS,
            sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("label_id", sa.String(length=32), nullable=False),
            sa.Column("taxonomy", sa.String(length=96), nullable=False),
            sa.Column("repo", sa.String(length=64), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("capability_class", sa.String(length=64), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False),
            sa.Column("labeller", sa.String(length=128), nullable=False),
            sa.Column("created", sa.String(length=40), nullable=False),
            sa.PrimaryKeyConstraint("seq"),
            sa.UniqueConstraint("label_id"),
        )
        op.create_index(
            "ix_class_labels_version_repo", LABELS, ["taxonomy", "repo", "seq"], unique=False
        )
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0047)


def downgrade() -> None:
    """Refused while any act or label exists: a signature, a person's label or a relabel is a
    record, and an append-only table's rows are never dropped. Empty tables go with their
    triggers. Offline (``--sql``) there is nothing to count: the script drops both tables and
    whoever runs it owns that check."""
    present = _tables()
    if not context.is_offline_mode():
        counts = {
            ACTS: "SELECT COUNT(*) FROM class_set_acts",
            LABELS: "SELECT COUNT(*) FROM class_labels",
        }
        for table, query in counts.items():
            if table in present:
                n: int = op.get_bind().execute(sa.text(query)).scalar_one()
                if n:
                    raise RuntimeError(
                        f"refusing to downgrade 0047: {n} row(s) in {table} — signatures and "
                        "labels are never dropped"
                    )
    for table in (LABELS, ACTS):
        if table in present or context.is_offline_mode():
            op.drop_table(table)
