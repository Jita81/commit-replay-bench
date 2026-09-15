"""The DB-backed hash-chained ledger, with the same contract as ``JsonlLedger``.

``append`` runs in one transaction under a write lock (``BEGIN IMMEDIATE`` on
SQLite, ``SELECT … FOR UPDATE`` semantics on PostgreSQL via an advisory lock):
read the last ``row_hash``, chain, validate the false-Q1 invariant, insert.
Because ``prev_hash``/``row_hash`` are stored, an exported JSONL verifies
standalone with :func:`crb.core.ledger.verify_chain`.

Imports (``import_rows``) re-chain foreign rows into this ledger and keep the
source row's own hash in ``labels['source_row_hash']`` for traceability.

:class:`DbReviewLedger` is the same contract for the ``reviews`` table
(:class:`crb.core.review.ReviewRecord`): its own chain, its own write lock, and the
anchor rule (:func:`crb.core.review.check_review_anchor`) applied at append against the
REVIEWED ROW's stored evidence pack — resolved through the row named by
``grade_row_hash``, never through the record's own pack field — so a review of bytes the
instrument did not grade for that row cannot be written.

Navigation
----------
What it is:   The database ledgers — ``DbLedger`` for ``grades`` (+ the ``evidence`` packs)
              and ``DbReviewLedger`` for ``reviews`` — plus ``assert_append_only`` for
              ``/health``.
What it does: Appends hash-chained rows under a per-table write lock, re-asserting the
              false-Q1 invariant before every insert; reads rows back as the core's
              dataclasses; imports foreign JSONL rows by re-chaining them (source hash kept
              in ``labels``); exports rows that verify standalone. Refuses a review whose row
              is unknown, whose pack is not the row's, or which has nothing to anchor to.
How:          ``append`` = lock → last ``row_hash`` → ``GradeRow.chained`` → insert → commit;
              ``verify`` re-walks the chain with the core's ``verify_chain``;
              ``DbReviewLedger.append`` resolves the reviewed row and its stored pack, runs
              ``check_review_anchor``, then chains and inserts the same way.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/ledger.py (``GradeRow``, ``verify_chain``, ``GENESIS_HASH`` — the
              contract this mirrors), src/crb/core/review.py (``ReviewRecord`` and the anchor
              rule), src/crb/store/models.py (the ``Grade`` / ``Review`` / ``EvidencePackRow``
              columns), src/crb/store/db.py (the triggers that make append-only true at the
              database), src/crb/server/worker.py (the writer), src/crb/server/routes/ledger.py
              (verify / export over HTTP)
Tested by:    tests/test_store_ledger.py, tests/test_store_reviews.py, tests/test_store_db.py,
              tests/test_store_migrate.py
Touch when:   never for a new repository; when ``GradeRow`` or ``ReviewRecord`` gains a field
              (the column tuples are derived from the dataclasses, so a new field needs a
              migration and a ``labels``-style exclusion if it is not a column); changing the
              lock or chain semantics needs docs/adr/0002-append-only-hash-chained-ledger.md.
Claims:       A verified chain proves rows were not edited or reordered since they were
              written — not that the apparatus that wrote them was sound
              (docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import EvidencePack
from crb.core.ledger import (
    GENESIS_HASH,
    GradeRow,
    LedgerIntegrityError,
    verify_chain,
)
from crb.core.review import (
    REFUSAL_NO_DIFF_IN_PACK,
    REFUSAL_PACK_MISMATCH,
    REFUSAL_ROW_NOT_FOUND,
    ReviewRecord,
    ReviewRefused,
    check_review_anchor,
    pack_is_authentic,
    verify_review_chain,
)
from crb.store.models import EvidencePackRow, Grade, Review

# Column lists are DERIVED from the core dataclasses so a field added there cannot be
# silently dropped here; the one field each holds as JSON is excluded and mapped by hand.
_ROW_COLUMNS = tuple(k for k in GradeRow.__dataclass_fields__ if k != "labels")
_REVIEW_COLUMNS = tuple(k for k in ReviewRecord.__dataclass_fields__ if k != "findings")


def _to_model(row: GradeRow) -> Grade:
    data: dict[str, Any] = {k: getattr(row, k) for k in _ROW_COLUMNS}
    data["labels_json"] = dict(row.labels)
    return Grade(**data)


def _from_model(m: Grade) -> GradeRow:
    d: dict[str, Any] = {k: getattr(m, k) for k in _ROW_COLUMNS}
    d["labels"] = dict(m.labels_json or {})
    return GradeRow(**d)


class DbLedger:
    """The ``grades`` table as a hash-chained ledger of :class:`GradeRow`, plus the
    content-addressed ``evidence`` packs the rows point at."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    # --- write ----------------------------------------------------------------
    def _lock(self, s: Session) -> None:
        # One writer at a time so "last row_hash" cannot be read twice by two appenders.
        # SQLite: BEGIN IMMEDIATE takes the file's write lock now, not at first write.
        # PostgreSQL: a transaction-scoped advisory lock keyed per ledger (7331 = grades).
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7331)"))  # grades

    def _last_hash(self, s: Session) -> str:
        """The chain head: the newest row's ``row_hash``, or the genesis hash when empty."""
        last = s.execute(
            select(Grade.row_hash).order_by(Grade.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return last or GENESIS_HASH

    def append(self, row: GradeRow) -> GradeRow:
        """Chain ``row`` onto the head and insert it; returns the chained copy.

        The invariant check runs BEFORE the lock is taken so a false-Q1 row costs nothing
        but the exception; the database constraint and triggers are the second line.
        """
        row.assert_invariants()
        with self._factory() as s:
            self._lock(s)
            chained = row.chained(self._last_hash(s))
            s.add(_to_model(chained))
            s.commit()
        return chained

    def append_many(self, rows: Iterable[GradeRow]) -> list[GradeRow]:
        """Chain and insert ``rows`` in order under one lock and one transaction — all or
        nothing, so a rejected row in the middle leaves the chain where it was."""
        out: list[GradeRow] = []
        with self._factory() as s:
            self._lock(s)
            prev = self._last_hash(s)
            for row in rows:
                row.assert_invariants()
                chained = row.chained(prev)
                s.add(_to_model(chained))
                prev = chained.row_hash
                out.append(chained)
            s.commit()
        return out

    def store_pack(self, pack: EvidencePack) -> str:
        """Store a pack body under its hash; a second store of the same hash is a no-op
        (content-addressed, so a re-run cannot overwrite the evidence a row cites)."""
        with self._factory() as s:
            existing = s.get(EvidencePackRow, pack.pack_hash)
            if existing is None:
                s.add(
                    EvidencePackRow(
                        pack_hash=pack.pack_hash,
                        repo=pack.task.repo,
                        task_id=pack.task.task_id,
                        run_id=pack.run_id,
                        body_json=pack.to_dict(),
                    )
                )
                s.commit()
        return pack.pack_hash

    # --- read -----------------------------------------------------------------
    def rows(self, *, repo: str | None = None, run_id: str | None = None) -> Iterator[GradeRow]:
        """Rows in chain (``seq``) order, optionally filtered. A filtered read is not a
        verifiable chain on its own — ``verify`` always reads everything."""
        with self._factory() as s:
            q = select(Grade).order_by(Grade.seq)
            if repo:
                q = q.where(Grade.repo == repo)
            if run_id:
                q = q.where(Grade.run_id == run_id)
            for m in s.execute(q).scalars():
                yield _from_model(m)

    def count(self) -> int:
        """Total rows in the ledger."""
        with self._factory() as s:
            return int(s.execute(select(func.count(Grade.seq))).scalar_one())

    def get_pack(self, pack_hash: str) -> dict[str, Any] | None:
        """The stored pack body for ``pack_hash`` (``EvidencePack.to_dict()`` shape), or
        ``None``."""
        with self._factory() as s:
            m = s.get(EvidencePackRow, pack_hash)
            return None if m is None else dict(m.body_json)

    def verify(self) -> int:
        """Walk the whole chain in ``seq`` order; raise :class:`LedgerIntegrityError`."""
        return verify_chain(self.rows())

    # --- import / export ------------------------------------------------------
    def import_rows(self, rows: Iterable[GradeRow]) -> int:
        """Re-chain foreign rows into this ledger (source hash kept in labels)."""
        prepared: list[GradeRow] = []
        for r in rows:
            labels = dict(r.labels)
            if r.row_hash:
                labels.setdefault("source_row_hash", r.row_hash)
            d = r.fields()
            d["labels"] = labels
            # Blank prev_hash: ``chained`` in append_many recomputes it against THIS
            # ledger's head; the source ledger's chain position is not ours to keep.
            d["prev_hash"] = ""
            prepared.append(GradeRow(**d))
        return len(self.append_many(prepared))

    def export_jsonl(self, path: str | Path) -> int:
        """Write every row, in chain order, as one JSON object per line (sorted keys, so
        the file is byte-stable); returns the row count. The file verifies standalone."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with p.open("w", encoding="utf-8") as f:
            for r in self.rows():
                f.write(json.dumps(r.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                n += 1
        return n


def _review_to_model(rec: ReviewRecord) -> Review:
    data: dict[str, Any] = {k: getattr(rec, k) for k in _REVIEW_COLUMNS}
    data["findings_json"] = [f.to_dict() for f in rec.findings]
    return Review(**data)


def _review_from_model(m: Review) -> ReviewRecord:
    d: dict[str, Any] = {k: getattr(m, k) for k in _REVIEW_COLUMNS}
    d["findings"] = list(m.findings_json or [])
    return ReviewRecord.from_dict(d)


class DbReviewLedger:
    """The ``reviews`` table as a hash-chained ledger of :class:`ReviewRecord`."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def _lock(self, s: Session) -> None:
        # The reviews chain has its own head, so its own lock (see DbLedger._lock).
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7333)"))  # reviews

    def _last_hash(self, s: Session) -> str:
        """The review chain's head, or the genesis hash when empty."""
        last = s.execute(
            select(Review.row_hash).order_by(Review.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return last or GENESIS_HASH

    def append(self, record: ReviewRecord, *, pack: dict[str, Any] | None = None) -> ReviewRecord:
        """Anchor-check, chain and insert in one locked transaction.

        The reviewed row is resolved by ``record.grade_row_hash`` (a review of a row
        this ledger does not hold is refused — ``row_not_found``) and the pack by THE
        ROW's ``evidence_pack_hash`` — never by the record's own field, which must
        agree with the row's (``pack_hash_mismatch``; the independent review pass of
        2026-09-14, finding 5, anchored a review of row A to row B's pack that way).
        ``pack`` is optional: the stored pack is the anchor; a caller's copy is only
        accepted in its place when it is self-certifying for the row's hash, and is
        refused when it is not the row's. A record with a verdict whose row has no
        stored (or supplied, authentic) pack is refused — ``no_diff_in_pack``.
        """
        with self._factory() as s:
            g = s.execute(
                select(Grade).where(Grade.row_hash == record.grade_row_hash)
            ).scalar_one_or_none()
            if g is None:
                raise ReviewRefused(
                    f"no graded row with row_hash {record.grade_row_hash[:12]}… — a review "
                    "is a verdict on a row this ledger holds",
                    code=REFUSAL_ROW_NOT_FOUND,
                    expected=record.grade_row_hash,
                )
            row = _from_model(g)
            body: dict[str, Any] | None = None
            if g.evidence_pack_hash:
                m = s.get(EvidencePackRow, g.evidence_pack_hash)
                if m is not None:
                    body = dict(m.body_json)
            if pack is not None and not pack_is_authentic(pack, g.evidence_pack_hash):
                raise ReviewRefused(
                    "the evidence pack handed in is not the reviewed row's",
                    code=REFUSAL_PACK_MISMATCH,
                    expected=g.evidence_pack_hash,
                    observed=str(pack.get("pack_hash", "") or ""),
                )
            if body is None and pack is not None:
                body = dict(pack)  # a self-certifying copy of the row's own pack
            if body is None and record.reviewed:
                raise ReviewRefused(
                    f"no evidence pack {g.evidence_pack_hash[:12]!r}… stored for the "
                    "reviewed row — nothing to anchor the review to",
                    code=REFUSAL_NO_DIFF_IN_PACK,
                    expected=g.evidence_pack_hash,
                    observed=record.patch_sha256_reviewed,
                )
            check_review_anchor(record, pack=body, row=row)
            # Lock only once the anchor holds: a refused review never blocks a writer.
            self._lock(s)
            chained = record.chained(self._last_hash(s))
            s.add(_review_to_model(chained))
            s.commit()
        return chained

    def records(
        self,
        *,
        repo: str | None = None,
        task_id: str | None = None,
        grade_row_hash: str | None = None,
    ) -> Iterator[ReviewRecord]:
        """Reviews in chain order, optionally filtered by repo, task or reviewed row."""
        with self._factory() as s:
            q = select(Review).order_by(Review.seq)
            if repo:
                q = q.where(Review.repo == repo)
            if task_id:
                q = q.where(Review.task_id == task_id)
            if grade_row_hash:
                q = q.where(Review.grade_row_hash == grade_row_hash)
            for m in s.execute(q).scalars():
                yield _review_from_model(m)

    def get(self, review_id: str) -> ReviewRecord | None:
        """One review by its id, or ``None``."""
        with self._factory() as s:
            m = s.execute(select(Review).where(Review.review_id == review_id)).scalar_one_or_none()
            return None if m is None else _review_from_model(m)

    def count(self) -> int:
        """Total reviews in the ledger."""
        with self._factory() as s:
            return int(s.execute(select(func.count(Review.seq))).scalar_one())

    def verify(self) -> int:
        """Walk the whole review chain in ``seq`` order; raise :class:`LedgerIntegrityError`."""
        return verify_review_chain(self.records())


def assert_append_only(factory: sessionmaker[Session]) -> None:
    """Prove the triggers are live: an UPDATE on grades must fail. Used by /health."""
    with factory() as s:
        first = s.execute(select(Grade).order_by(Grade.seq).limit(1)).scalar_one_or_none()
        if first is None:
            return
        try:
            # A no-op UPDATE (actor = actor): a live trigger aborts it; a missing one lets
            # it through, the rollback undoes the harmless write, and we report the gap.
            s.execute(text("UPDATE grades SET actor = actor WHERE seq = :seq"), {"seq": first.seq})
            s.rollback()
        except Exception:
            s.rollback()
            return
        raise LedgerIntegrityError(
            "grades table accepted an UPDATE — append-only triggers are missing"
        )
