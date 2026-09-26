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
              model money, before its next replay. ``downgrade`` refuses while any measured
              (non-legacy) record exists — grade rows cite them — and otherwise drops the table.
How:          ``op.create_table`` + ``install_append_only_triggers_on`` on Alembic's own
              connection; the back-fill reads ``tasks.spec_json`` and writes each record's
              body from a shape FROZEN in this file (``legacy_body``: the 2.3 record, its
              fingerprint by a local copy of the rule) — a released revision imports nothing
              of the product's runtime, so a later change to ``Qualification`` can neither
              change nor break what it writes.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``TaskQualification``; ``APPEND_ONLY_TABLES``),
              src/crb/store/migrate.py (``REVISION_TABLES`` carries
              ``("0011", "task_qualifications")``; the trigger helper),
              src/crb/store/qualifications.py (reads and appends the rows),
              src/crb/core/qualify.py (reads the record a row's ``body_json`` holds; the
              rule ``_legacy_fingerprint`` copies)
Tested by:    tests/test_store_migrate.py, tests/test_store_qualifications.py
Touch when:   never — a released revision is immutable. Wave 2 holds revisions 0009 and 0010;
              at merge this revision's ``down_revision`` is re-pointed at the head it lands on.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import context, op

from crb.store.migrate import install_append_only_triggers_on

revision: str = "0011"
down_revision: str | None = "0009"
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


#: The record shape this revision writes, frozen as released (apparatus 2.3): a revision
#: never reads these from the product's runtime, whose values move.
LEGACY_POSTURE_ID = "pst_legacy"
STATE_LEGACY = "legacy"
APPARATUS_AT_0011 = "2.3"
CRB_VERSION_AT_0011 = "2.0.0a1"
BACKFILL_MESSAGE = "back-filled from the task's discovery values; never a gate"


def _legacy_fingerprint(baseline_failing: Sequence[str], gold: Mapping[str, Any]) -> str:
    """``crb.core.qualify.fingerprint_of`` as it stood at 2.3, over a legacy record's facts
    (a discovery RED with no ids, no flaky set): sha256 of the canonical JSON."""
    facts = {
        "red_kind": "discovery",
        "red_failing": [],
        "baseline_failing": list(baseline_failing),
        "baseline_flaky": [],
        "gold_clean": gold.get("clean"),
        "gold_lint": gold.get("lint"),
    }
    text = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def legacy_body(
    repo: str, task_id: str, spec: Mapping[str, Any], qualification_id: str, created: str
) -> dict[str, Any]:
    """The ``body_json`` of one back-filled record: the task's discovery values, marked
    ``migrated_unverified`` — the 2.3 ``Qualification.to_dict()`` shape, written literally."""
    baseline = sorted({str(i) for i in (spec.get("baseline_failing") or ())})
    gold = {
        "clean": spec.get("gold_clean"),
        "note": str(spec.get("gold_note") or ""),
        "lint": None,
    }
    return {
        "qualification_id": qualification_id,
        "repo": repo,
        "task_id": task_id,
        "posture_id": LEGACY_POSTURE_ID,
        "posture": {},
        "state": STATE_LEGACY,
        "code": "",
        "message": BACKFILL_MESSAGE,
        "fix": "",
        "deps": {},
        "env_probe": {},
        "red": {"kind": "discovery", "failing": []},
        "baseline_failing": baseline,
        "baseline_flaky": [],
        "gold": gold,
        "fingerprint": _legacy_fingerprint(baseline, gold),
        "delta": {},
        "apparatus_version": APPARATUS_AT_0011,
        "crb_version": CRB_VERSION_AT_0011,
        "run_id": "",
        "created": created,
        "provenance": "migrated_unverified",
    }


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
        created = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()
        body = legacy_body(str(repo), str(task_id), spec, uuid.uuid4().hex, created)
        rows.append(
            {
                "qualification_id": body["qualification_id"],
                "repo": body["repo"],
                "task_id": body["task_id"],
                "posture_id": LEGACY_POSTURE_ID,
                "posture_class": "",
                "executor": "",
                "image_ref": "",
                "state": STATE_LEGACY,
                "code": "",
                "fingerprint": body["fingerprint"],
                "body_json": body,
                "created": created,
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
    """Refused while any record but the back-fill's ``legacy`` ones exists: from apparatus
    2.3 every measured grade row cites its ``qualification_id``, and an append-only table's
    rows are never dropped (0002's pattern; CodeRabbit on PR #56). A table that holds only
    the back-fill is this revision's own writing and is dropped with its triggers. Offline
    (``--sql``) there is nothing to count: the script drops the table and whoever runs it
    owns that check."""
    if not context.is_offline_mode() and _table_exists():
        n: int = (
            op.get_bind()
            .execute(
                sa.text("SELECT COUNT(*) FROM task_qualifications WHERE state <> :legacy"),
                {"legacy": STATE_LEGACY},
            )
            .scalar_one()
        )
        if n:
            raise RuntimeError(
                f"refusing to downgrade 0011: {n} measured qualification record(s) exist "
                "(grade rows cite them); only a table holding the legacy back-fill may go"
            )
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
