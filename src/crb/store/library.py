"""The context library in the store: acts appended under a lock, entries folded on read.

``library_acts`` holds every act on every repository's library, in one hash-chained
sequence (``prev_hash`` = the previous act's ``row_hash``, whatever its repository), as the
reviews table holds reviews. An act is written only after :func:`crb.core.library.apply`
accepts it against the entry's state folded from the acts already stored — inside the same
locked transaction, so two approvers cannot both sign one version, and a sponsor cannot
sign between another person's read and write.

Navigation
----------
What it is:   ``DbLibraryLedger`` — append an act (checked, chained, locked), mark the entries
              whose source file changed at head stale, read a repository's acts, fold them
              into entry states, and verify the chain.
What it does: Gives ``/library`` one write path that enforces the two-person rule and the
              status machine at write, and one read that every page and the Decisions inbox
              share.
How:          SQLAlchemy 2; ``BEGIN IMMEDIATE`` on SQLite and a transaction-scoped advisory
              lock (7343) on PostgreSQL around read-head → fold → apply → insert.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0026-the-context-standard.md (item 10),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/library.py (the act, the rule and the fold),
              src/crb/store/models.py (``LibraryActRow``),
              src/crb/store/migrations/versions/v0016_library_acts.py (the table),
              src/crb/server/routes/library.py (the only writer over HTTP),
              src/crb/server/worker.py (``mark_stale`` after every mine, G-736)
Tested by:    tests/test_store_library.py, tests/test_server_routes_library.py
Touch when:   never for a new repository; a new reading of the acts is added here, never an
              UPDATE (the table's triggers refuse one).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import utc_now_iso
from crb.core.ledger import GENESIS_HASH
from crb.core.library import (
    ACT_STALE,
    EntryState,
    LibraryAct,
    LibraryRefused,
    apply,
    fold,
    stale_candidates,
    verify_library_chain,
)
from crb.store.models import LibraryActRow

#: The PostgreSQL advisory lock key of the library's chain (grades 7331, reviews 7333).
LOCK_KEY = 7343


def _to_act(m: LibraryActRow) -> LibraryAct:
    return LibraryAct(
        act_id=m.act_id,
        repo=m.repo,
        entry_id=m.entry_id,
        version=m.version,
        act=m.act,
        actor=m.actor,
        created=m.created,
        body=dict(m.body_json or {}),
        schema=m.schema,
        prev_hash=m.prev_hash,
        row_hash=m.row_hash,
    )


def new_act(
    repo: str,
    entry_id: str,
    version: str,
    act: str,
    actor: str,
    *,
    body: Mapping[str, Any] | None = None,
) -> LibraryAct:
    """An unchained act stamped now, with a fresh id."""
    return LibraryAct(
        act_id=uuid.uuid4().hex,
        repo=repo,
        entry_id=entry_id,
        version=version,
        act=act,
        actor=actor,
        created=utc_now_iso(),
        body=dict(body or {}),
    )


class DbLibraryLedger:
    """The ``library_acts`` table as a hash-chained ledger of :class:`LibraryAct`."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def _lock(self, s: Session) -> None:
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text(f"SELECT pg_advisory_xact_lock({LOCK_KEY})"))  # library

    @staticmethod
    def _head(s: Session) -> str:
        last = s.execute(
            select(LibraryActRow.row_hash).order_by(LibraryActRow.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return last or GENESIS_HASH

    @staticmethod
    def _entry_acts(s: Session, repo: str, entry_id: str) -> list[LibraryAct]:
        rows = s.execute(
            select(LibraryActRow)
            .where(LibraryActRow.repo == repo, LibraryActRow.entry_id == entry_id)
            .order_by(LibraryActRow.seq)
        ).scalars()
        return [_to_act(m) for m in rows]

    def append(self, act: LibraryAct) -> tuple[LibraryAct, EntryState]:
        """Check ``act`` against its entry's state, chain it and insert it in one locked
        transaction; returns the chained act and the entry's new state. Raises
        :class:`~crb.core.library.LibraryRefused` (nothing written) when the rule refuses."""
        with self._factory() as s:
            self._lock(s)
            before = fold(self._entry_acts(s, act.repo, act.entry_id)).get(act.entry_id)
            after = apply(before, act)
            chained = act.chained(self._head(s))
            s.add(
                LibraryActRow(
                    act_id=chained.act_id,
                    schema=chained.schema,
                    repo=chained.repo,
                    entry_id=chained.entry_id,
                    version=chained.version,
                    act=chained.act,
                    actor=chained.actor,
                    body_json=dict(chained.body),
                    created=chained.created,
                    prev_hash=chained.prev_hash,
                    row_hash=chained.row_hash,
                )
            )
            s.commit()
            return chained, after

    def mark_stale(
        self,
        repo: str,
        head_commit: str,
        digests_at_head: Mapping[str, str | None],
        actor: str,
    ) -> list[tuple[LibraryAct, EntryState]]:
        """Append a ``stale`` act for each proposed or signed entry of ``repo`` whose source
        file's bytes at ``head_commit`` differ from the ones it was signed against
        (:func:`~crb.core.library.stale_candidates`; a digest of ``None`` or ``""`` is a file
        gone at head; a path not in ``digests_at_head`` is not judged). The one staleness
        path for ``POST /library/{repo}/freshness`` and the worker's read after a mine
        (DL-114, G-736). An entry another reader marked between the fold and the write is
        skipped, never marked twice."""
        out: list[tuple[LibraryAct, EntryState]] = []
        for state, digest in stale_candidates(self.states(repo).values(), digests_at_head):
            try:
                out.append(
                    self.append(
                        new_act(
                            repo,
                            state.entry_id,
                            state.entry.version,
                            ACT_STALE,
                            actor,
                            body={"head_commit": head_commit, "digest": digest},
                        )
                    )
                )
            except LibraryRefused:
                continue
        return out

    def acts(self, repo: str | None = None) -> list[LibraryAct]:
        """Every act in append order — one repository's, or all of them."""
        with self._factory() as s:
            q = select(LibraryActRow)
            if repo is not None:
                q = q.where(LibraryActRow.repo == repo)
            return [_to_act(m) for m in s.execute(q.order_by(LibraryActRow.seq)).scalars()]

    def states(self, repo: str) -> dict[str, EntryState]:
        """entry id → its state, for one repository."""
        return fold(self.acts(repo))

    def verify(self) -> int:
        """Walk the whole chain from genesis; the count, or ``LedgerIntegrityError``."""
        return verify_library_chain(self.acts())


__all__ = ["LOCK_KEY", "DbLibraryLedger", "new_act"]
