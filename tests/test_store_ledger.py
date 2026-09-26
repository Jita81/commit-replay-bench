"""crb.store.ledger — ``DbLedger``: chain, verify, import/export, packs, concurrency.

Parametrised over SQLite and (when ``CRB_TEST_POSTGRES_URL`` is set) PostgreSQL.

Navigation
----------
What it is:   ``DbLedger``'s test suite — the chain, verify, import / export, packs and
              concurrency, on SQLite and PostgreSQL.
What it does: Pins that appends chain from genesis and verify, that ``append_many`` chains in
              order in one transaction and is atomic, that a false-Q1 row is refused even when
              constructed sideways, row filters by repo and run, that verify catches a row
              tampered underneath dropped triggers, labels through the JSON column,
              ``assert_append_only`` passing with triggers and raising without, that import
              re-chains and keeps the source row hash, that an export re-verifies standalone,
              pack store / get round trip and append-only, and that four threads appending
              concurrently form one valid chain.
How:          ``conftest_store`` backends and row builders; threads for the concurrency case.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/store/ledger.py (under test), src/crb/core/ledger.py (the JSONL twin
              whose hashes must match), src/crb/store/db.py (the write lock and triggers),
              tests/conftest_store.py, tests/test_ledger.py (the core chain's own suite)
Tested by:    tests/test_store_ledger.py
Touch when:   a column is added to ``grades`` (the export must re-verify — pin it); the write
              lock changes (the concurrency case is the proof).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from crb.core.evidence import verify_pack
from crb.core.grade import FalseQ1Violation
from crb.core.ledger import (
    GENESIS_HASH,
    GradeRow,
    JsonlLedger,
    LedgerIntegrityError,
    verify_chain,
)
from crb.store.db import init_db, install_append_only_triggers, make_session_factory
from crb.store.ledger import DbLedger, assert_append_only

try:
    from tests.conftest_store import (
        SHA,
        Backend,
        backend,
        evidence_pack,
        grade_row,
        pg_schema,
    )
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import (  # noqa: F401
        SHA,
        Backend,
        backend,
        evidence_pack,
        grade_row,
        pg_schema,
    )


@pytest.fixture
def ledger(backend: Backend) -> DbLedger:
    """A ``DbLedger`` over an initialised backend (tables and triggers installed)."""
    init_db(backend.engine)
    return DbLedger(backend.factory)


# ---------------------------------------------------------------------------
# append / chain / verify
# ---------------------------------------------------------------------------


def test_append_chains_from_genesis_and_verifies(ledger: DbLedger) -> None:
    r1 = ledger.append(grade_row(trial="1"))
    r2 = ledger.append(grade_row(trial="2", clean=False, target_green=False))
    r3 = ledger.append(grade_row(trial="3"))
    assert r1.prev_hash == GENESIS_HASH
    assert r2.prev_hash == r1.row_hash and r3.prev_hash == r2.row_hash
    assert all(r.verify_hash() for r in (r1, r2, r3))
    assert ledger.count() == 3
    assert ledger.verify() == 3
    assert [r.trial for r in ledger.rows()] == ["1", "2", "3"]
    # what was stored is what was returned (hashes included)
    assert [r.row_hash for r in ledger.rows()] == [r1.row_hash, r2.row_hash, r3.row_hash]


def test_append_many_chains_in_order_in_one_transaction(ledger: DbLedger) -> None:
    ledger.append(grade_row(trial="0"))
    out = ledger.append_many(grade_row(trial=str(i)) for i in range(1, 6))
    assert len(out) == 5
    assert [r.trial for r in ledger.rows()] == [str(i) for i in range(6)]
    assert ledger.verify() == 6


def test_append_many_is_atomic(ledger: DbLedger) -> None:
    """A bad row in the batch rolls the whole batch back — no half-chains."""
    tampered = grade_row(clean=False, target_green=False, trial="bad")
    object.__setattr__(tampered, "clean", True)  # bypass __post_init__, as an attacker would
    with pytest.raises(FalseQ1Violation):
        ledger.append_many([grade_row(trial="ok"), tampered])
    assert ledger.count() == 0


def test_append_refuses_a_false_q1_row_even_if_constructed_sideways(ledger: DbLedger) -> None:
    row = grade_row(clean=False, target_green=False)
    object.__setattr__(row, "clean", True)
    with pytest.raises(FalseQ1Violation, match="refuses clean row"):
        ledger.append(row)
    assert ledger.count() == 0
    no_pack = grade_row(clean=False, evidence_pack_hash="")
    object.__setattr__(no_pack, "clean", True)
    with pytest.raises(FalseQ1Violation, match="no pack"):
        ledger.append(no_pack)
    assert ledger.count() == 0


def test_rows_filters_by_repo_and_run(ledger: DbLedger) -> None:
    ledger.append(grade_row(repo="a", run_id="r1"))
    ledger.append(grade_row(repo="b", run_id="r1"))
    ledger.append(grade_row(repo="a", run_id="r2"))
    assert [r.repo for r in ledger.rows(repo="a")] == ["a", "a"]
    assert [r.repo for r in ledger.rows(run_id="r1")] == ["a", "b"]
    assert [r.run_id for r in ledger.rows(repo="a", run_id="r2")] == ["r2"]
    assert ledger.verify() == 3


def test_verify_detects_a_row_tampered_underneath_the_triggers(
    backend: Backend, ledger: DbLedger
) -> None:
    """If someone drops the triggers and edits a row, ``verify`` still catches it."""
    ledger.append(grade_row(trial="1"))
    ledger.append(grade_row(trial="2"))
    backend.drop_grades_triggers()
    with backend.engine.begin() as c:
        c.execute(text("UPDATE grades SET actor = 'mallory' WHERE trial = '1'"))
    with pytest.raises(LedgerIntegrityError, match="row_hash mismatch"):
        ledger.verify()


def test_labels_round_trip_through_json_column(ledger: DbLedger) -> None:
    r = ledger.append(grade_row(labels={"campaign": "t9", "seed": "1"}))
    stored = next(iter(ledger.rows()))
    assert stored.labels == r.labels  # the posture labels (ADR-0019) round-trip too
    assert stored.labels["campaign"] == "t9" and stored.labels["seed"] == "1"
    assert stored.row_hash == r.row_hash and stored.verify_hash()


# ---------------------------------------------------------------------------
# assert_append_only (the /health probe)
# ---------------------------------------------------------------------------


def test_assert_append_only_passes_with_triggers_and_raises_without(
    backend: Backend, ledger: DbLedger
) -> None:
    assert_append_only(backend.factory)  # empty ledger: nothing to probe, no error
    ledger.append(grade_row())
    assert_append_only(backend.factory)  # UPDATE refused → healthy
    assert ledger.verify() == 1  # the probe rolled back; the row is untouched

    backend.drop_grades_triggers()
    with pytest.raises(LedgerIntegrityError, match="append-only triggers are missing"):
        assert_append_only(backend.factory)
    assert next(iter(ledger.rows())).actor == ""  # the probe's UPDATE was a no-op and rolled back

    install_append_only_triggers(backend.engine)
    assert_append_only(backend.factory)


# ---------------------------------------------------------------------------
# import / export
# ---------------------------------------------------------------------------


def test_import_rows_rechains_and_keeps_source_row_hash(ledger: DbLedger, tmp_path: Path) -> None:
    src = JsonlLedger(tmp_path / "census.jsonl")
    originals = [
        src.append(grade_row(trial=str(i), provenance="imported:census")) for i in range(3)
    ]
    assert src.verify() == 3

    n = ledger.import_rows(src.rows())
    assert n == 3
    imported = list(ledger.rows())
    assert [r.labels["source_row_hash"] for r in imported] == [o.row_hash for o in originals]
    assert imported[0].prev_hash == GENESIS_HASH
    assert [r.row_hash for r in imported] != [o.row_hash for o in originals]  # re-chained
    assert ledger.verify() == 3

    # a second import appends after the existing chain, never restarts it
    ledger.import_rows([grade_row(trial="9")])
    assert ledger.verify() == 4
    assert list(ledger.rows())[3].prev_hash == imported[2].row_hash


def test_import_rows_keeps_an_existing_source_row_hash_label(ledger: DbLedger) -> None:
    row = grade_row(labels={"source_row_hash": "f" * 64}).chained(GENESIS_HASH)
    ledger.import_rows([row])
    assert next(iter(ledger.rows())).labels["source_row_hash"] == "f" * 64


def test_export_jsonl_reverifies_standalone(ledger: DbLedger, tmp_path: Path) -> None:
    rows = [ledger.append(grade_row(trial=str(i))) for i in range(4)]
    out = tmp_path / "export" / "ledger.jsonl"
    assert ledger.export_jsonl(out) == 4

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    parsed = [GradeRow.from_dict(json.loads(line)) for line in lines]
    assert verify_chain(parsed) == 4  # the stdlib verifier, no database in sight
    assert JsonlLedger(out).verify() == 4
    assert [r.row_hash for r in parsed] == [r.row_hash for r in rows]

    # and the export is the exact canonical row: re-importing elsewhere keeps provenance
    assert all(json.loads(line)["prev_hash"] for line in lines)


# ---------------------------------------------------------------------------
# evidence packs
# ---------------------------------------------------------------------------


def test_store_pack_and_get_pack_round_trip(ledger: DbLedger) -> None:
    pack = evidence_pack()
    h = ledger.store_pack(pack)
    assert h == pack.pack_hash
    assert ledger.store_pack(pack) == h  # idempotent on the same hash
    body = ledger.get_pack(h)
    assert body is not None
    assert body["pack_hash"] == h and verify_pack(body)
    assert body["task"]["task_id"] == SHA and body["builder"]["name"] == "agentic"
    assert ledger.get_pack("0" * 64) is None


def test_stored_pack_is_append_only(backend: Backend, ledger: DbLedger) -> None:
    from sqlalchemy.exc import DBAPIError

    h = ledger.store_pack(evidence_pack())
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("DELETE FROM evidence WHERE pack_hash = :h"), {"h": h})
    assert ledger.get_pack(h) is not None


# ---------------------------------------------------------------------------
# concurrency — the write lock serialises appenders into one valid chain
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_concurrent_appends_from_four_threads_form_one_valid_chain(
    backend: Backend, ledger: DbLedger
) -> None:
    per_thread = 15
    errors: list[BaseException] = []
    start = threading.Barrier(4)

    def worker(tag: int) -> None:
        # each thread gets its own engine + ledger: separate connections, same database
        eng = backend.new_engine()
        try:
            own = DbLedger(make_session_factory(eng))
            start.wait(timeout=30)
            for i in range(per_thread):
                own.append(grade_row(trial=f"{tag}-{i}", run_id=f"run-{tag}"))
        except BaseException as e:  # collected and re-raised by the main thread below
            errors.append(e)
        finally:
            eng.dispose()

    threads = [threading.Thread(target=worker, args=(t,), name=f"appender-{t}") for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    assert not errors, errors
    assert ledger.count() == 4 * per_thread
    assert ledger.verify() == 4 * per_thread
    hashes = [r.row_hash for r in ledger.rows()]
    assert len(set(hashes)) == len(hashes)
    trials = sorted(r.trial for r in ledger.rows())
    assert trials == sorted(f"{t}-{i}" for t in range(4) for i in range(per_thread))
