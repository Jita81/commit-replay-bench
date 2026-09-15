"""crb.store.ledger.DbReviewLedger — chain, anchor against the stored pack, append-only.

Parametrised over SQLite and (when ``CRB_TEST_POSTGRES_URL`` is set) PostgreSQL.

Navigation
----------
What it is:   ``DbReviewLedger``'s test suite — chain, anchor against the stored pack,
              append-only, on SQLite and PostgreSQL.
What it does: Pins that appends chain, anchor and verify, that a hash that is not the pack's is
              refused, that a review of a row this ledger does not hold is refused (with or
              without a verdict), that a row whose pack is not stored is refused, that the anchor
              is the REVIEWED row's pack never the record's (review finding 5, 2026-09-14), that
              an explicit ``pack`` is only a self-certifying copy of the row's, the filters, that
              the table is append-only, and that a tampered row breaks verify.
How:          ``conftest_store`` backends with a ``DbLedger`` holding a clean row and its pack.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/ledger.py (``DbReviewLedger`` under test), src/crb/core/review.py
              (the record and refusal codes), tests/test_review.py (the JSONL twin),
              tests/test_server_routes_reviews.py (the write as HTTP), tests/conftest_store.py
Tested by:    tests/test_store_reviews.py
Touch when:   the anchor rule changes (both ledgers and the route together); a review column is
              added (a migration and the parity case).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from crb.core.grade import Belts, GradeResult
from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.core.review import (
    REFUSAL_NO_DIFF_IN_PACK,
    REFUSAL_PACK_MISMATCH,
    REFUSAL_PATCH_HASH_MISMATCH,
    REFUSAL_ROW_NOT_FOUND,
    Finding,
    ReviewRecord,
    ReviewRefused,
    verify_review_chain,
)
from crb.core.workspace import DiffStats
from crb.store.db import init_db
from crb.store.ledger import DbLedger, DbReviewLedger

try:
    from tests.conftest_store import Backend, backend, evidence_pack, grade_row, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, evidence_pack, grade_row, pg_schema  # noqa: F401


@pytest.fixture
def store(backend: Backend) -> tuple[DbLedger, DbReviewLedger]:
    """``(DbLedger, DbReviewLedger)`` over an initialised backend."""
    init_db(backend.engine)
    return DbLedger(backend.factory), DbReviewLedger(backend.factory)


def _review(row_hash: str, pack_hash: str, diff_sha: str, **kw: Any) -> ReviewRecord:
    base: dict[str, Any] = {
        "grade_row_hash": row_hash,
        "repo": "r",
        "task_id": "x" * 40,
        "reviewer": "reviewer@example.org",
        "statement": "read every hunk",
        "patch_sha256_reviewed": diff_sha,
        "evidence_pack_hash": pack_hash,
    }
    base.update(kw)
    return ReviewRecord(**base)


def _graded(store: tuple[DbLedger, DbReviewLedger]) -> tuple[str, str, str]:
    """A stored pack WITH a diff, and a clean row pointing at it → (row_hash, pack_hash, diff_sha)."""
    ledger, _ = store
    diff_sha = "d" * 64
    result = GradeResult(
        "x" * 40,
        "r",
        "sighted",
        clean=True,
        belts=Belts(True, True, True, True),
        diff=DiffStats(files=("src/a.py",), additions=3, deletions=1, diff_sha256=diff_sha),
    )
    pack = evidence_pack(grade=result)
    ledger.store_pack(pack)
    row = ledger.append(grade_row(evidence_pack_hash=pack.pack_hash))
    return row.row_hash, pack.pack_hash, diff_sha


def test_append_chains_anchors_and_verifies(store: tuple[DbLedger, DbReviewLedger]) -> None:
    _ledger, reviews = store
    row_hash, pack_hash, diff_sha = _graded(store)
    assert reviews.count() == 0 and reviews.verify() == 0
    r1 = reviews.append(_review(row_hash, pack_hash, diff_sha))
    r2 = reviews.append(
        _review(
            row_hash,
            pack_hash,
            diff_sha,
            verdict="defect",
            findings=(Finding("defect", "flag ignored", file="a.py", line=3),),
            mergeable=False,
        )
    )
    assert r1.prev_hash == GENESIS_HASH and r2.prev_hash == r1.row_hash
    assert r1.verify_hash() and r2.verify_hash()
    assert reviews.count() == 2 and reviews.verify() == 2
    got = list(reviews.records())
    assert [g.review_id for g in got] == [r1.review_id, r2.review_id]
    assert got[1].findings[0].file == "a.py" and got[1].mergeable is False
    assert got[1] == r2  # round-trips through the columns byte-for-byte
    assert verify_review_chain(got) == 2
    assert reviews.get(r2.review_id) == r2 and reviews.get("nope") is None


def test_append_refuses_a_hash_that_is_not_the_packs(
    store: tuple[DbLedger, DbReviewLedger],
) -> None:
    _ledger, reviews = store
    row_hash, pack_hash, _diff_sha = _graded(store)
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(row_hash, pack_hash, "e" * 64))
    assert ei.value.code == REFUSAL_PATCH_HASH_MISMATCH
    assert reviews.count() == 0


def test_append_refuses_a_row_this_ledger_does_not_hold(
    store: tuple[DbLedger, DbReviewLedger],
) -> None:
    """A review is a verdict on a row THIS ledger holds — with or without a verdict."""
    _ledger, reviews = store
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review("a" * 64, "z" * 64, "d" * 64))
    assert ei.value.code == REFUSAL_ROW_NOT_FOUND
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(
            _review("a" * 64, "z" * 64, "", verdict="not_reviewed", statement="nothing to read")
        )
    assert ei.value.code == REFUSAL_ROW_NOT_FOUND
    assert reviews.count() == 0


def test_append_refuses_when_the_rows_pack_is_not_stored(
    store: tuple[DbLedger, DbReviewLedger],
) -> None:
    ledger, reviews = store
    row = ledger.append(grade_row(clean=False, target_green=False, evidence_pack_hash=""))
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(row.row_hash, "", "d" * 64))
    assert ei.value.code == REFUSAL_NO_DIFF_IN_PACK
    # a not_reviewed record attests to nothing and needs no pack — but its pack field
    # must still be the row's
    nr = reviews.append(
        _review(row.row_hash, "", "", verdict="not_reviewed", statement="nothing to read")
    )
    assert nr.verify_hash() and reviews.count() == 1
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(
            _review(row.row_hash, "z" * 64, "", verdict="not_reviewed", statement="nothing")
        )
    assert ei.value.code == REFUSAL_PACK_MISMATCH


def test_append_anchors_to_the_reviewed_rows_pack_never_the_records(
    store: tuple[DbLedger, DbReviewLedger],
) -> None:
    """Independent review pass (2026-09-14), finding 5: two clean rows A (diff 1…) and
    B (diff 2…); a review of A carrying B's pack hash and B's diff hash was ACCEPTED —
    the store looked the pack up by the record's own field. The pack is resolved
    through the row now, and a record whose pack field is not the row's is refused."""
    ledger, reviews = store
    a_row, a_pack, a_diff = _graded(store)
    b_result = GradeResult(
        "y" * 40,
        "r",
        "sighted",
        clean=True,
        belts=Belts(True, True, True, True),
        diff=DiffStats(files=("src/b.py",), additions=1, deletions=0, diff_sha256="2" * 64),
    )
    b_pack = evidence_pack(grade=b_result)
    ledger.store_pack(b_pack)
    b_row = ledger.append(grade_row(task_id="y" * 40, evidence_pack_hash=b_pack.pack_hash))
    assert a_pack != b_pack.pack_hash and a_diff != "2" * 64
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(a_row, b_pack.pack_hash, "2" * 64))
    assert ei.value.code == REFUSAL_PACK_MISMATCH
    assert ei.value.expected == a_pack and ei.value.observed == b_pack.pack_hash
    # the same with the caller handing B's pack in explicitly
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(a_row, b_pack.pack_hash, "2" * 64), pack=b_pack.to_dict())
    assert ei.value.code == REFUSAL_PACK_MISMATCH
    # a record naming A's pack but attesting to B's bytes: the patch anchor refuses
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(a_row, a_pack, "2" * 64))
    assert ei.value.code == REFUSAL_PATCH_HASH_MISMATCH
    assert reviews.count() == 0
    # each row reviewed against its own pack: chained
    assert reviews.append(_review(a_row, a_pack, a_diff)).verify_hash()
    assert reviews.append(_review(b_row.row_hash, b_pack.pack_hash, "2" * 64)).verify_hash()
    assert reviews.verify() == 2


def test_an_explicit_pack_is_only_a_self_certifying_copy_of_the_rows(
    store: tuple[DbLedger, DbReviewLedger],
) -> None:
    """The caller's ``pack`` never replaces the lookup: it must BE the row's pack (its
    hash recomputes to the row's ``evidence_pack_hash``) — a forged body, or another
    pack, is refused even when the row's own pack is not stored."""
    ledger, reviews = store
    result = GradeResult(
        "x" * 40,
        "r",
        "sighted",
        clean=True,
        belts=Belts(True, True, True, True),
        diff=DiffStats(files=("src/a.py",), additions=3, deletions=1, diff_sha256="c" * 64),
    )
    real = evidence_pack(grade=result)
    row = ledger.append(grade_row(evidence_pack_hash=real.pack_hash))  # pack NOT stored
    forged = {"grade": {"diff": {"diff_sha256": "d" * 64}}, "pack_hash": real.pack_hash}
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(row.row_hash, real.pack_hash, "d" * 64), pack=forged)
    assert ei.value.code == REFUSAL_PACK_MISMATCH
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(row.row_hash, real.pack_hash, "c" * 64))
    assert ei.value.code == REFUSAL_NO_DIFF_IN_PACK
    # the genuine pack, handed in by the caller, anchors the review
    rec = reviews.append(_review(row.row_hash, real.pack_hash, "c" * 64), pack=real.to_dict())
    assert rec.verify_hash()
    with pytest.raises(ReviewRefused) as ei:
        reviews.append(_review(row.row_hash, real.pack_hash, "d" * 64), pack=real.to_dict())
    assert ei.value.code == REFUSAL_PATCH_HASH_MISMATCH


def test_filters(store: tuple[DbLedger, DbReviewLedger]) -> None:
    _ledger, reviews = store
    row_hash, pack_hash, diff_sha = _graded(store)
    reviews.append(_review(row_hash, pack_hash, diff_sha))
    reviews.append(_review(row_hash, pack_hash, diff_sha, repo="other", task_id="y" * 40))
    assert len(list(reviews.records(repo="r"))) == 1
    assert len(list(reviews.records(task_id="y" * 40))) == 1
    assert len(list(reviews.records(grade_row_hash=row_hash))) == 2
    assert len(list(reviews.records(grade_row_hash="0" * 64))) == 0


def test_reviews_table_is_append_only(
    backend: Backend, store: tuple[DbLedger, DbReviewLedger]
) -> None:
    _ledger, reviews = store
    row_hash, pack_hash, diff_sha = _graded(store)
    rec = reviews.append(_review(row_hash, pack_hash, diff_sha))
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(
            text("UPDATE reviews SET verdict = 'ok' WHERE review_id = :id"), {"id": rec.review_id}
        )
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("DELETE FROM reviews"))
    assert reviews.count() == 1


def test_a_tampered_row_breaks_verify(
    backend: Backend, store: tuple[DbLedger, DbReviewLedger]
) -> None:
    _ledger, reviews = store
    row_hash, pack_hash, diff_sha = _graded(store)
    reviews.append(_review(row_hash, pack_hash, diff_sha))
    reviews.append(_review(row_hash, pack_hash, diff_sha))
    with backend.engine.begin() as c:
        if backend.dialect == "sqlite":
            c.execute(text("DROP TRIGGER reviews_no_update"))
        else:
            c.execute(text("DROP TRIGGER reviews_no_update ON reviews"))
        c.execute(text("UPDATE reviews SET statement = 'edited' WHERE seq = 1"))
    with pytest.raises(LedgerIntegrityError, match="review 1"):
        reviews.verify()
