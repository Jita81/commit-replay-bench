"""The DB-backed hash-chained ledger, with the same contract as ``JsonlLedger``.

``append`` runs in one transaction under a write lock (``BEGIN IMMEDIATE`` on
SQLite, ``SELECT … FOR UPDATE`` semantics on PostgreSQL via an advisory lock):
read the last ``row_hash``, chain, validate the false-Q1 invariant, insert.
Because ``prev_hash``/``row_hash`` are stored, an exported JSONL verifies
standalone with :func:`crb.core.ledger.verify_chain`.

Imports (``import_rows``) re-chain foreign rows into this ledger and keep the
source row's own hash in ``labels['source_row_hash']`` for traceability.
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
from crb.store.models import EvidencePackRow, Grade

_ROW_COLUMNS = tuple(k for k in GradeRow.__dataclass_fields__ if k != "labels")


def _to_model(row: GradeRow) -> Grade:
    data: dict[str, Any] = {k: getattr(row, k) for k in _ROW_COLUMNS}
    data["labels_json"] = dict(row.labels)
    return Grade(**data)


def _from_model(m: Grade) -> GradeRow:
    d: dict[str, Any] = {k: getattr(m, k) for k in _ROW_COLUMNS}
    d["labels"] = dict(m.labels_json or {})
    return GradeRow(**d)


class DbLedger:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    # --- write ----------------------------------------------------------------
    def _lock(self, s: Session) -> None:
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7331)"))

    def _last_hash(self, s: Session) -> str:
        last = s.execute(
            select(Grade.row_hash).order_by(Grade.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return last or GENESIS_HASH

    def append(self, row: GradeRow) -> GradeRow:
        row.assert_invariants()
        with self._factory() as s:
            self._lock(s)
            chained = row.chained(self._last_hash(s))
            s.add(_to_model(chained))
            s.commit()
        return chained

    def append_many(self, rows: Iterable[GradeRow]) -> list[GradeRow]:
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
        with self._factory() as s:
            q = select(Grade).order_by(Grade.seq)
            if repo:
                q = q.where(Grade.repo == repo)
            if run_id:
                q = q.where(Grade.run_id == run_id)
            for m in s.execute(q).scalars():
                yield _from_model(m)

    def count(self) -> int:
        with self._factory() as s:
            return int(s.execute(select(func.count(Grade.seq))).scalar_one())

    def get_pack(self, pack_hash: str) -> dict[str, Any] | None:
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
            d["prev_hash"] = ""
            prepared.append(GradeRow(**d))
        return len(self.append_many(prepared))

    def export_jsonl(self, path: str | Path) -> int:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with p.open("w", encoding="utf-8") as f:
            for r in self.rows():
                f.write(json.dumps(r.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                n += 1
        return n


def assert_append_only(factory: sessionmaker[Session]) -> None:
    """Prove the triggers are live: an UPDATE on grades must fail. Used by /health."""
    with factory() as s:
        first = s.execute(select(Grade).order_by(Grade.seq).limit(1)).scalar_one_or_none()
        if first is None:
            return
        try:
            s.execute(text("UPDATE grades SET actor = actor WHERE seq = :seq"), {"seq": first.seq})
            s.rollback()
        except Exception:
            s.rollback()
            return
        raise LedgerIntegrityError(
            "grades table accepted an UPDATE — append-only triggers are missing"
        )
