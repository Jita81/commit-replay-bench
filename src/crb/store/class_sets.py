"""An organisation's class sets in the store: acts appended under a lock, labels appended.

``class_set_acts`` holds every act on every organisation's class-set versions in one
hash-chained sequence, as ``library_acts`` holds the library's; an act is written only after
:func:`crb.core.class_sets.apply` accepts it against the versions folded from the acts already
stored — inside the same locked transaction, so two approvers cannot both sign one version and
two sponsors cannot both propose the same number. ``class_labels`` is the label table: a
person's label of a derivation commit, or a version's rule applied to a commit (a relabel);
both only ever appended.

Navigation
----------
What it is:   ``DbClassSets`` — append an act (checked, chained, locked), fold an
              organisation's versions, verify the chain, append labels and read the latest.
What it does: Gives ``/classes`` one write path that enforces the version order and the
              two-person rule at write, one read every screen shares, and the label table the
              validity report and the reading's pool read.
How:          SQLAlchemy 2; ``BEGIN IMMEDIATE`` on SQLite and a transaction-scoped advisory lock
              (7347) on PostgreSQL around read → fold → apply → insert.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0026-the-context-standard.md (item 9),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/class_sets.py (the act, the rule and the fold),
              src/crb/store/models.py (``ClassSetActRow``, ``ClassLabelRow``),
              src/crb/store/migrations/versions/v0047_class_sets.py (the tables),
              src/crb/server/routes/classes.py (the only writer over HTTP)
Tested by:    tests/test_store_class_sets.py, tests/test_server_routes_classes.py
Touch when:   never for a new repository; a new reading of the acts or labels is added here,
              never an UPDATE (the tables' triggers refuse one).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.class_sets import ClassSetAct, VersionState, apply, fold, verify_chain
from crb.core.evidence import utc_now_iso
from crb.core.ledger import GENESIS_HASH
from crb.store.models import ClassLabelRow, ClassSetActRow

#: The PostgreSQL advisory lock key of the class sets' chain (library 7343).
LOCK_KEY = 7347
SOURCE_PERSON = "person"
SOURCE_RULE = "rule"


def _to_act(m: ClassSetActRow) -> ClassSetAct:
    return ClassSetAct(
        act_id=m.act_id,
        org=m.org,
        version_id=m.version_id,
        digest=m.digest,
        act=m.act,
        actor=m.actor,
        created=m.created,
        body=dict(m.body_json or {}),
        schema=m.schema,
        prev_hash=m.prev_hash,
        row_hash=m.row_hash,
    )


def new_act(
    org: str,
    version_id: str,
    digest: str,
    act: str,
    actor: str,
    *,
    body: Mapping[str, Any] | None = None,
    created: str = "",
) -> ClassSetAct:
    """An unchained act stamped now (or at ``created``), with a fresh id."""
    return ClassSetAct(
        act_id=uuid.uuid4().hex,
        org=org,
        version_id=version_id,
        digest=digest,
        act=act,
        actor=actor,
        created=created or utc_now_iso(),
        body=dict(body or {}),
    )


class DbClassSets:
    """The ``class_set_acts`` and ``class_labels`` tables."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def _lock(self, s: Session) -> None:
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7347)"))  # class sets (LOCK_KEY)

    @staticmethod
    def _head(s: Session) -> str:
        last = s.execute(
            select(ClassSetActRow.row_hash).order_by(ClassSetActRow.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return last or GENESIS_HASH

    @staticmethod
    def _org_acts(s: Session, org: str) -> list[ClassSetAct]:
        rows = s.execute(
            select(ClassSetActRow).where(ClassSetActRow.org == org).order_by(ClassSetActRow.seq)
        ).scalars()
        return [_to_act(m) for m in rows]

    def append(self, act: ClassSetAct) -> tuple[ClassSetAct, VersionState]:
        """Check ``act`` against the organisation's versions, chain it and insert it in one
        locked transaction. Raises :class:`~crb.core.class_sets.ClassSetRefused` (nothing
        written) when the rule refuses."""
        with self._factory() as s:
            self._lock(s)
            after = apply(fold(self._org_acts(s, act.org)), act)
            chained = act.chained(self._head(s))
            s.add(
                ClassSetActRow(
                    act_id=chained.act_id,
                    schema=chained.schema,
                    org=chained.org,
                    version_id=chained.version_id,
                    digest=chained.digest,
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

    def acts(self, org: str | None = None) -> list[ClassSetAct]:
        """Every act in append order — one organisation's, or all of them."""
        with self._factory() as s:
            q = select(ClassSetActRow)
            if org is not None:
                q = q.where(ClassSetActRow.org == org)
            return [_to_act(m) for m in s.execute(q.order_by(ClassSetActRow.seq)).scalars()]

    def versions(self, org: str | None = None) -> dict[str, VersionState]:
        """version id → state (one organisation's, or every one's)."""
        out: dict[str, VersionState] = {}
        orgs = [org] if org is not None else self.orgs()
        for o in orgs:
            out.update(fold(self.acts(o)))
        return out

    def orgs(self) -> list[str]:
        """Every organisation with at least one act, sorted."""
        with self._factory() as s:
            return sorted(set(s.execute(select(ClassSetActRow.org)).scalars()))

    def verify(self) -> int:
        """Walk the whole chain from genesis; the count, or ``LedgerIntegrityError``."""
        return verify_chain(self.acts())

    # --- the label table ------------------------------------------------------------------

    def add_labels(
        self,
        taxonomy: str,
        labels: Iterable[tuple[str, str, str]],
        *,
        source: str,
        labeller: str,
    ) -> int:
        """Append ``(repo, task_id, class)`` labels under ``taxonomy``; the count written."""
        now = utc_now_iso()
        n = 0
        with self._factory() as s:
            for repo, task_id, klass in labels:
                s.add(
                    ClassLabelRow(
                        label_id=uuid.uuid4().hex,
                        taxonomy=taxonomy,
                        repo=repo,
                        task_id=task_id,
                        capability_class=klass,
                        source=source,
                        labeller=labeller,
                        created=now,
                    )
                )
                n += 1
            s.commit()
        return n

    def labels(self, taxonomy: str, *, source: str, repo: str | None = None) -> list[ClassLabelRow]:
        """Every label of ``source`` under ``taxonomy`` in append order (one repository's, or
        every one's)."""
        with self._factory() as s:
            q = select(ClassLabelRow).where(
                ClassLabelRow.taxonomy == taxonomy, ClassLabelRow.source == source
            )
            if repo is not None:
                q = q.where(ClassLabelRow.repo == repo)
            rows = list(s.execute(q.order_by(ClassLabelRow.seq)).scalars())
            s.expunge_all()
            return rows

    def rule_labels(self, taxonomy: str, repo: str | None = None) -> dict[tuple[str, str], str]:
        """(repo, task) → the class the version's rule last gave it (the relabel's table)."""
        out: dict[tuple[str, str], str] = {}
        for r in self.labels(taxonomy, source=SOURCE_RULE, repo=repo):
            out[(r.repo, r.task_id)] = r.capability_class
        return out


__all__ = ["LOCK_KEY", "SOURCE_PERSON", "SOURCE_RULE", "DbClassSets", "new_act"]
