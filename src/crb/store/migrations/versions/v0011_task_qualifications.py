"""task_qualifications — each task's qualification per posture, append-only (ADR-0019)

Navigation
----------
What it is:   Revision 0011: the append-only ``task_qualifications`` table and a back-fill of
              one ``legacy`` record per existing task.
What it does: Creates the table (unless ``init_db`` already did), installs the grades
              table's UPDATE/DELETE-refusing triggers on it (SQLite and PostgreSQL), and
              writes, for the record, one ``legacy`` row per task carrying its discovery
              values (``posture_id: pst_legacy``, ``provenance: migrated_unverified``). A
              legacy row never satisfies the gate: every repository qualifies once, for no
              model money, before its next replay. ``downgrade`` drops the table.
How:          ``op.create_table`` + ``install_append_only_triggers_on`` on Alembic's own
              connection; the back-fill reads ``tasks.spec_json`` and builds each record with
              ``crb.core.qualify.Qualification``.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``TaskQualification``; ``APPEND_ONLY_TABLES``),
              src/crb/store/migrate.py (``REVISION_TABLES`` carries
              ``("0011", "task_qualifications")``; the trigger helper),
              src/crb/store/qualifications.py (reads and appends the rows),
              src/crb/core/qualify.py (the record a row's ``body_json`` holds)
Tested by:    tests/test_store_migrate.py, tests/test_store_qualifications.py
Touch when:   never — a released revision is immutable. Wave 2 holds revisions 0009 and 0010;
              at merge this revision's ``down_revision`` is re-pointed at the head it lands on.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from crb.core.posture import LEGACY_POSTURE_ID
from crb.core.qualify import STATE_LEGACY, Qualification
from crb.store.migrate import install_append_only_triggers_on

revision: str = "0011"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "task_qualifications"
#: The append-only tables that exist once this revision is applied.
APPEND_ONLY_AT_0011: tuple[str, ...] = (
    "grades",
    "events",
    "signoffs",
    "evidence",
    "reviews",
    TABLE,
)


def _table_exists() -> bool:
    if context.is_offline_mode():
        return False
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def _backfill() -> None:
    """One ``legacy`` record per task, for the record: its discovery values, marked
    ``migrated_unverified``. Never a qualification the gate accepts."""
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if "tasks" not in sa.inspect(bind).get_table_names():
        return
    tasks = bind.execute(sa.text("SELECT repo, task_id, spec_json FROM tasks")).fetchall()
    table = sa.table(
        TABLE,
        sa.column("qualification_id", sa.String),
        sa.column("repo", sa.String),
        sa.column("task_id", sa.String),
        sa.column("posture_id", sa.String),
        sa.column("posture_class", sa.String),
        sa.column("executor", sa.String),
        sa.column("image_ref", sa.String),
        sa.column("state", sa.String),
        sa.column("code", sa.String),
        sa.column("fingerprint", sa.String),
        sa.column("body_json", sa.JSON),
        sa.column("created", sa.String),
    )
    rows = []
    for repo, task_id, raw in tasks:
        # SQLite hands raw JSON text to a text() query; PostgreSQL a dict
        loaded = json.loads(raw or "{}") if isinstance(raw, str | bytes) else raw
        spec = loaded if isinstance(loaded, dict) else {}
        q = Qualification(
            qualification_id="",
            repo=str(repo),
            task_id=str(task_id),
            posture_id=LEGACY_POSTURE_ID,
            posture={},
            state=STATE_LEGACY,
            message="back-filled from the task's discovery values; never a gate",
            red={"kind": "discovery", "failing": []},
            baseline_failing=tuple(spec.get("baseline_failing") or ()),
            gold={
                "clean": spec.get("gold_clean"),
                "note": str(spec.get("gold_note") or ""),
                "lint": None,
            },
        )
        body = {**q.to_dict(), "provenance": "migrated_unverified"}
        rows.append(
            {
                "qualification_id": q.qualification_id,
                "repo": q.repo,
                "task_id": q.task_id,
                "posture_id": q.posture_id,
                "posture_class": "",
                "executor": "",
                "image_ref": "",
                "state": q.state,
                "code": "",
                "fingerprint": q.fingerprint,
                "body_json": body,
                "created": q.created,
            }
        )
    if rows:
        op.bulk_insert(table, rows)


def upgrade() -> None:
    """Create ``task_qualifications`` (unless ``init_db`` already did), protect it, and
    back-fill one legacy record per task."""
    created = False
    if not _table_exists():
        op.create_table(
            TABLE,
            sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("qualification_id", sa.String(length=64), nullable=False),
            sa.Column("repo", sa.String(length=64), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("posture_id", sa.String(length=32), nullable=False),
            sa.Column("posture_class", sa.String(length=64), nullable=False),
            sa.Column("executor", sa.String(length=16), nullable=False),
            sa.Column("image_ref", sa.String(length=256), nullable=False),
            sa.Column("state", sa.String(length=16), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("body_json", sa.JSON(), nullable=False),
            sa.Column("created", sa.String(length=40), nullable=False),
            sa.PrimaryKeyConstraint("seq"),
            sa.UniqueConstraint("qualification_id"),
        )
        op.create_index(
            "ix_task_qualifications_lookup",
            TABLE,
            ["repo", "task_id", "posture_id", "seq"],
            unique=False,
        )
        created = True
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0011)
    if created:
        _backfill()


def downgrade() -> None:
    """Drop the table (its triggers go with it). The records are re-measurable facts —
    qualifying again costs no model money — so dropping them destroys no evidence a row
    cites."""
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
