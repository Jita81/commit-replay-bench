"""The library's acts in the store: append-only, hash-chained, checked inside the lock.

Navigation
----------
What it is:   Tests of ``crb.store.library.DbLibraryLedger`` on SQLite (and PostgreSQL when
              ``CRB_TEST_PG_URL`` is set).
What it does: Pins that the ``library_acts`` table refuses UPDATE and DELETE, that an act the
              two-person rule refuses writes nothing, that the chain spans repositories and
              verifies from genesis, and that a row changed behind the store is found.
How:          ``init_db`` on the backend fixture → ``DbLibraryLedger.append(new_act(…))``.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0026-the-context-standard.md (item 10),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/library.py (the ledger under test), src/crb/store/models.py
              (``LibraryActRow``), src/crb/core/library.py (the rule the ledger applies),
              tests/conftest_store.py (the backends)
Tested by:    this file
Touch when:   never for a new repository; a new reading of the acts is added to the store
              module.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from crb.core.ledger import LedgerIntegrityError
from crb.core.library import (
    ACT_PROPOSE,
    ACT_SIGN,
    LibraryEntry,
    LibraryRefused,
    Provenance,
)
from crb.store.db import init_db
from crb.store.library import DbLibraryLedger, new_act

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401

ADA, BEN = "a" * 32, "b" * 32


def _entry(repo: str = "calc", slug: str = "errors-wrap") -> LibraryEntry:
    return LibraryEntry(
        repo=repo,
        kind="convention",
        slug=slug,
        title="Wrap errors",
        statement="Every returned error is wrapped with the operation's name.",
        provenance=Provenance(kind="person", person=ADA),
        proposed_by=ADA,
    )


def _propose(ledger: DbLibraryLedger, e: LibraryEntry) -> None:
    ledger.append(
        new_act(e.repo, e.entry_id, e.version, ACT_PROPOSE, ADA, body={"entry": e.content()})
    )


def test_library_acts_are_append_only(backend: Backend) -> None:
    init_db(backend.engine)
    ledger = DbLibraryLedger(backend.factory)
    _propose(ledger, _entry())
    for stmt in ("UPDATE library_acts SET actor = 'x'", "DELETE FROM library_acts"):
        with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
            c.execute(text(stmt))
    assert ledger.states("calc")["convention/errors-wrap"].sponsor == ADA


def test_a_refused_act_writes_nothing_and_a_second_person_signs(backend: Backend) -> None:
    init_db(backend.engine)
    ledger = DbLibraryLedger(backend.factory)
    e = _entry()
    _propose(ledger, e)
    with pytest.raises(LibraryRefused) as exc:
        ledger.append(new_act("calc", e.entry_id, e.version, ACT_SIGN, ADA))
    assert exc.value.code == "same_person"
    assert len(ledger.acts("calc")) == 1
    _chained, state = ledger.append(new_act("calc", e.entry_id, e.version, ACT_SIGN, BEN))
    assert (state.status, state.sponsor, state.approver) == ("signed", ADA, BEN)
    assert ledger.states("calc")[e.entry_id].status == "signed"


def test_one_chain_spans_every_repository_and_verifies_from_genesis(backend: Backend) -> None:
    init_db(backend.engine)
    ledger = DbLibraryLedger(backend.factory)
    _propose(ledger, _entry("calc"))
    _propose(ledger, _entry("koa"))
    acts = ledger.acts()
    assert [a.repo for a in acts] == ["calc", "koa"]
    assert acts[1].prev_hash == acts[0].row_hash
    assert ledger.verify() == 2
    assert [a.repo for a in ledger.acts("koa")] == ["koa"]


def test_a_row_changed_behind_the_store_breaks_the_chain(backend: Backend) -> None:
    if backend.dialect != "sqlite":
        pytest.skip("the tamper drops a SQLite trigger by name; the append-only test covers both")
    init_db(backend.engine)
    ledger = DbLibraryLedger(backend.factory)
    _propose(ledger, _entry())
    with backend.engine.begin() as c:  # an attacker with the file drops the trigger first
        c.execute(text("DROP TRIGGER IF EXISTS library_acts_no_update"))
        c.execute(text("UPDATE library_acts SET actor = :b"), {"b": BEN})
    with pytest.raises(LedgerIntegrityError, match="row_hash"):
        ledger.verify()
