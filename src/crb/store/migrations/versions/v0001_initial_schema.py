"""initial schema — every table in ``crb.store.models`` plus the append-only triggers

Revision ID: 0001
Revises:
Create Date: 2026-09-13 13:14:38+00:00

This revision is, by construction and by test, identical to
``Base.metadata.create_all`` at the time it was written (``tests/test_store_migrate.py``
compares the autogenerate diff and, on SQLite, the ``sqlite_master`` rows). That equality
is what lets :func:`crb.store.migrate.upgrade` adopt a database created by ``init_db`` by
stamping it at ``0001``.

Rules for crb migrations (docs/ARCHITECTURE.md §7.3, ADR-0002):
* append-only tables (``grades``, ``events``, ``signoffs``, ``evidence``) are never
  rewritten — a migration may ADD nullable columns or indexes, never drop or alter rows;
* after any change to an append-only table, re-run
  ``crb.store.migrate.install_append_only_triggers_on(op.get_bind(), <tables>)`` with the
  append-only tables that exist AT THAT REVISION (pinned in the script);
* ``downgrade`` must be real or must raise — never a silent ``pass`` on a data table.

Navigation
----------
What it is:   Revision ``0001`` — the base schema: every table of the first release plus the
              append-only triggers.
What it does: Creates ``repos``, ``runs``, ``tasks``, ``grades``, ``evidence``, ``events``,
              ``signoffs``, ``users`` and their indexes, then installs the triggers on the
              four append-only tables that exist at this revision. ``downgrade`` refuses
              while any append-only table holds a row.
How:          ``op.create_table`` per table in dependency order → ``create_index`` →
              ``install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0001)``.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (what this revision plus its successors must equal),
              src/crb/store/migrate.py (``install_append_only_triggers_on``; adoption stamps
              an ``init_db`` database here),
              src/crb/store/migrations/versions/v0002_belt5_repo_lint_clean.py (the next
              revision)
Tested by:    tests/test_store_migrate.py
Touch when:   never — a released revision is immutable; schema changes are new revisions.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The append-only tables THIS revision creates — pinned, not the live
#: ``crb.store.models.APPEND_ONLY_TABLES`` (a later revision's table does not exist yet
#: when this one runs, and a trigger on a missing table fails the whole upgrade).
APPEND_ONLY_AT_0001: tuple[str, ...] = ("grades", "events", "signoffs", "evidence")


def upgrade() -> None:
    """Create the release-1 schema. Table order follows the foreign keys (``repos`` first)."""
    # --- reference data ---------------------------------------------------------
    op.create_table(
        "repos",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("runner", sa.String(length=16), nullable=False),
        sa.Column("clone_path", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("probe_status", sa.String(length=16), nullable=False),
        sa.Column("probe_detail", sa.Text(), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("updated", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("builder", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ladder_json", sa.JSON(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("apparatus_json", sa.JSON(), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("heartbeat", sa.String(length=40), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("started", sa.String(length=40), nullable=False),
        sa.Column("finished", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["repo"], ["repos.name"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_repo", "runs", ["repo"], unique=False)
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("repo", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("pool", sa.String(length=16), nullable=False),
        sa.Column("size", sa.String(length=4), nullable=False),
        sa.Column("capability_class", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("authored", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("red_checked", sa.Boolean(), nullable=False),
        sa.Column("gold_clean", sa.Boolean(), nullable=True),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["repo"], ["repos.name"]),
        sa.PrimaryKeyConstraint("repo", "task_id"),
    )

    # --- APPEND-ONLY: grades (GradeRow columns; hash-chained) ------------------
    op.create_table(
        "grades",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("row_id", sa.String(length=32), nullable=False),
        sa.Column("schema", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("trial", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("clean", sa.Boolean(), nullable=False),
        sa.Column("tests_unmodified", sa.Boolean(), nullable=True),
        sa.Column("target_green", sa.Boolean(), nullable=True),
        sa.Column("no_new_failures", sa.Boolean(), nullable=True),
        sa.Column("source_changed", sa.Boolean(), nullable=True),
        sa.Column("capability_class", sa.String(length=64), nullable=False),
        sa.Column("size", sa.String(length=4), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("pool", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("process_step", sa.String(length=16), nullable=False),
        sa.Column("builder", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("disqualified", sa.Boolean(), nullable=False),
        sa.Column("dq_reason", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("new_failures_count", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_s", sa.Float(), nullable=False),
        sa.Column("oracle_strength", sa.Float(), nullable=True),
        sa.Column("gold_clean", sa.Boolean(), nullable=True),
        sa.Column("evidence_pack_hash", sa.String(length=64), nullable=False),
        sa.Column("apparatus_version", sa.String(length=32), nullable=False),
        sa.Column("belt_set", sa.String(length=16), nullable=False),
        sa.Column("provenance", sa.String(length=128), nullable=False),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("row_id"),
        sa.UniqueConstraint("row_hash"),
    )
    op.create_index(
        "ix_grades_cell",
        "grades",
        ["process_step", "capability_class", "size", "language", "builder", "model", "provider"],
        unique=False,
    )
    op.create_index("ix_grades_repo", "grades", ["repo"], unique=False)
    op.create_index("ix_grades_repo_task", "grades", ["repo", "task_id"], unique=False)
    op.create_index("ix_grades_run_id", "grades", ["run_id"], unique=False)
    op.create_index("ix_grades_task_id", "grades", ["task_id"], unique=False)

    # --- APPEND-ONLY: evidence (pack bodies keyed by pack hash) -----------------
    op.create_table(
        "evidence",
        sa.Column("pack_hash", sa.String(length=64), nullable=False),
        sa.Column("repo", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("pack_hash"),
    )
    op.create_index("ix_evidence_repo", "evidence", ["repo"], unique=False)
    op.create_index("ix_evidence_run_id", "evidence", ["run_id"], unique=False)
    op.create_index("ix_evidence_task_id", "evidence", ["task_id"], unique=False)

    # --- APPEND-ONLY: events (StepEvent stream) --------------------------------
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.String(length=40), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("parent_step_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("repo", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("input_ref", sa.Text(), nullable=False),
        sa.Column("output_ref", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_events_repo", "events", ["repo"], unique=False)
    op.create_index("ix_events_trace_id", "events", ["trace_id"], unique=False)
    op.create_index("ix_events_trace_seq", "events", ["trace_id", "seq"], unique=False)

    # --- APPEND-ONLY: signoffs (human attestations; revocation = new row) -------
    op.create_table(
        "signoffs",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("signoff_id", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=64), nullable=False),
        sa.Column("cell_json", sa.JSON(), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("verifier", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("revoke", sa.Boolean(), nullable=False),
        sa.Column("evidence_rows", sa.Integer(), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("signoff_id"),
        sa.UniqueConstraint("row_hash"),
    )
    op.create_index("ix_signoffs_repo", "signoffs", ["repo"], unique=False)

    # --- accounts -------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("issuer", sa.String(length=256), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("last_login", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
    )

    # --- the store-level half of the honesty invariant ---------------------------
    # Same helper, same SQL as init_db(); on THIS connection, inside THIS transaction.
    install_append_only_triggers_on(op.get_bind(), APPEND_ONLY_AT_0001)


def downgrade() -> None:
    """Drop the schema — refused while any append-only table holds rows.

    The ledger is evidence; no migration may destroy it. Export and verify
    (``crb ledger export`` / ``verify``), then drop the tables by hand if you really mean it.
    """
    bind = op.get_bind()
    for table in APPEND_ONLY_AT_0001:
        n = bind.execute(sa.select(sa.func.count()).select_from(sa.table(table))).scalar_one()
        if n:
            raise RuntimeError(
                f"refusing to downgrade 0001: append-only table {table!r} holds {n} row(s)"
            )
    for table in ("users", "signoffs", "events", "evidence", "grades", "tasks", "runs", "repos"):
        op.drop_table(table)
