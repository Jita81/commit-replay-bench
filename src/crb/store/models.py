"""SQLAlchemy 2.0 models.

Tables
------
repos      — one row per configured repository (config JSON = ``RepoConfig.to_dict()``)
runs       — a run (replay | blind | oracle | factory) with status, counts, apparatus stamp
tasks      — mined TaskSpecs, keyed (repo, task_id)
grades     — APPEND-ONLY: one row per graded attempt, hash-chained (``GradeRow`` columns)
evidence   — evidence pack bodies keyed by pack hash (opt-in retention window applies
             to any transcript ref inside; the pack itself is always kept)
events     — APPEND-ONLY: StepEvent stream, ordered by (trace_id, seq)
signoffs   — APPEND-ONLY: human attestations (revocations are new rows)
reviews    — APPEND-ONLY: human post-hoc verdicts on ONE graded row each, hash-chained
             (``ReviewRecord`` columns; revision 0003)
users      — local accounts / OIDC subjects and their role
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


class Base(DeclarativeBase):
    pass


class Repo(Base):
    __tablename__ = "repos"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    runner: Mapped[str] = mapped_column(String(16), nullable=False)
    clone_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    probe_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    probe_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)
    updated: Mapped[str] = mapped_column(String(40), nullable=False, default=_now, onupdate=_now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    repo: Mapped[str] = mapped_column(
        String(64), ForeignKey("repos.name"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="replay"
    )  # replay|blind|oracle|factory|mine
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="sighted")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    builder: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    ladder_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    apparatus_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    heartbeat: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)
    started: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    finished: Mapped[str] = mapped_column(String(40), nullable=False, default="")


class Task(Base):
    __tablename__ = "tasks"
    repo: Mapped[str] = mapped_column(String(64), ForeignKey("repos.name"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pool: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    size: Mapped[str] = mapped_column(String(4), nullable=False, default="XS")
    capability_class: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    authored: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    red_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gold_clean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)


class Grade(Base):
    """APPEND-ONLY. Columns mirror :class:`crb.core.ledger.GradeRow`."""

    __tablename__ = "grades"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    schema: Mapped[str] = mapped_column(String(32), nullable=False)
    repo: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    trial: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created: Mapped[str] = mapped_column(String(40), nullable=False)
    clean: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tests_unmodified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    target_green: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    no_new_failures: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_changed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    capability_class: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size: Mapped[str] = mapped_column(String(4), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    pool: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="sighted")
    process_step: Mapped[str] = mapped_column(String(16), nullable=False, default="replay")
    builder: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    disqualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dq_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    new_failures_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    oracle_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    gold_clean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evidence_pack_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    apparatus_version: Mapped[str] = mapped_column(String(32), nullable=False)
    belt_set: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance: Mapped[str] = mapped_column(String(128), nullable=False, default="measured")
    labels_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Belt 5 (ADR-0011, revision 0002). Declared LAST so ``create_all`` and
    # ``ALTER TABLE … ADD COLUMN`` produce the same column order (the migration parity
    # test compares them). NULL on every pre-belt-5 row and on a ``v5`` row whose
    # repository has no linter; only ``belt_set`` says which.
    repo_lint_clean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        Index(
            "ix_grades_cell",
            "process_step",
            "capability_class",
            "size",
            "language",
            "builder",
            "model",
            "provider",
        ),
        Index("ix_grades_repo_task", "repo", "task_id"),
    )


class EvidencePackRow(Base):
    __tablename__ = "evidence"
    pack_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)


class Event(Base):
    """APPEND-ONLY. Columns mirror :class:`crb.observability.events.StepEvent`."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    parent_step_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    repo: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_events_trace_seq", "trace_id", "seq"),)


class Signoff(Base):
    """APPEND-ONLY. A revocation is a new row with ``revoke=True``."""

    __tablename__ = "signoffs"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signoff_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    repo: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cell_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="human-verified")
    verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoke: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class Review(Base):
    """APPEND-ONLY. Columns mirror :class:`crb.core.review.ReviewRecord`: one human
    verdict on the graded row ``grade_row_hash``, chained on its own ``prev_hash`` /
    ``row_hash``. A later review of the same row is a new row; nothing is edited."""

    __tablename__ = "reviews"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    schema: Mapped[str] = mapped_column(String(32), nullable=False)
    grade_row_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    repo: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    mergeable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False, default="")
    patch_sha256_reviewed: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    evidence_pack_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    apparatus_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created: Mapped[str] = mapped_column(String(40), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (Index("ix_reviews_repo_task", "repo", "task_id"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)  # oidc sub or "local:<name>"
    issuer: Mapped[str] = mapped_column(String(256), nullable=False, default="local")
    email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="viewer"
    )  # viewer|operator|approver|admin
    password_hash: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )  # local accounts only
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)
    last_login: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),)


#: Every append-only table of the CURRENT schema. A revision script pins the tuple that
#: existed at its own revision (a table a later revision adds has no triggers to install
#: yet); ``init_db`` and ``migrate.upgrade`` use this live one.
APPEND_ONLY_TABLES: tuple[str, ...] = ("grades", "events", "signoffs", "evidence", "reviews")
