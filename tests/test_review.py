"""crb.core.review — ReviewRecord invariants, the patch-hash anchor, the JSONL chain,
tamper detection, and the per-cell join onto graded rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import GENESIS_HASH, GradeRow, LedgerIntegrityError
from crb.core.review import (
    DEFECT_VERDICTS,
    FINDING_KINDS,
    REFUSAL_NO_DIFF_IN_PACK,
    REFUSAL_PATCH_HASH_MISMATCH,
    REFUSAL_PATCH_HASH_MISSING,
    REFUSAL_ROW_HASH_MISSING,
    REVIEW_SCHEMA,
    VERDICTS,
    Finding,
    JsonlReviewLedger,
    ReviewCellStats,
    ReviewRecord,
    ReviewRefused,
    check_patch_anchor,
    derive_verdict,
    is_sha256,
    latest_reviews,
    pack_diff_sha256,
    review_cell_stats,
    verify_review_chain,
)

DIFF_SHA = "d" * 64
ROW_HASH = "a" * 64
PACK_HASH = "p" * 64


def pack(diff_sha: str | None = DIFF_SHA) -> dict[str, Any]:
    """A serialised evidence pack with (or without) a recorded diff."""
    grade: dict[str, Any] = {"clean": True}
    if diff_sha is not None:
        grade["diff"] = {
            "files": ["src/a.py"],
            "additions": 3,
            "deletions": 1,
            "diff_sha256": diff_sha,
        }
    return {"schema": "crb.evidence.v1", "grade": grade, "pack_hash": PACK_HASH}


def record(**kw: Any) -> ReviewRecord:
    base: dict[str, Any] = {
        "grade_row_hash": ROW_HASH,
        "repo": "alpha",
        "task_id": "t" * 40,
        "reviewer": "reviewer@example.org",
        "statement": "read the diff line by line",
        "patch_sha256_reviewed": DIFF_SHA,
        "evidence_pack_hash": PACK_HASH,
    }
    base.update(kw)
    return ReviewRecord(**base)


def grade_row(**kw: Any) -> GradeRow:
    base: dict[str, Any] = {
        "repo": "alpha",
        "task_id": "t" * 40,
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "capability_class": "bug.fix",
        "size": "S",
        "language": "python",
        "builder": "editblock",
        "model": "m",
        "provider": "p",
        "evidence_pack_hash": PACK_HASH,
    }
    base.update(kw)
    return GradeRow(**base)


# ---------------------------------------------------------------------------
# vocabulary + findings
# ---------------------------------------------------------------------------


def test_vocabulary_is_closed_and_findings_are_never_headlines() -> None:
    assert set(FINDING_KINDS) < set(VERDICTS)
    assert "ok" not in FINDING_KINDS and "not_reviewed" not in FINDING_KINDS
    assert set(DEFECT_VERDICTS) == {"defect", "regression"}
    with pytest.raises(ValueError, match="finding kind"):
        Finding(kind="ok", note="x")
    with pytest.raises(ValueError, match="needs a note"):
        Finding(kind="defect", note="   ")
    with pytest.raises(ValueError, match="positive integer"):
        Finding(kind="defect", note="x", line=0)


def test_finding_redacts_and_round_trips() -> None:
    f = Finding(kind="style", note="token=abcdefghijk in helper", file="src/x.py", line=12)
    assert "abcdefghijk" not in f.note and "[REDACTED]" in f.note
    assert Finding.from_dict(f.to_dict()) == f
    assert Finding.from_dict({"kind": "defect", "note": "n", "line": ""}).line is None


def test_derive_verdict_is_the_most_severe_finding() -> None:
    assert derive_verdict([]) == "ok"
    assert derive_verdict([Finding("style", "s")]) == "style"
    assert derive_verdict([Finding("style", "s"), Finding("api_change", "a")]) == "api_change"
    assert derive_verdict([Finding("defect", "d"), Finding("api_change", "a")]) == "defect"
    assert derive_verdict([Finding("defect", "d"), Finding("regression", "r")]) == "regression"


# ---------------------------------------------------------------------------
# ReviewRecord invariants
# ---------------------------------------------------------------------------


def test_record_defaults_and_derived_fields() -> None:
    r = record()
    assert r.verdict == "ok" and r.findings == () and r.mergeable is None
    assert r.schema == REVIEW_SCHEMA and len(r.review_id) == 32
    assert r.reviewed and not r.is_defect
    assert r.row_hash == "" and r.prev_hash == ""


def test_verdict_must_agree_with_the_findings() -> None:
    fs = [Finding("defect", "the flag is ignored", file="cmd/root.go", line=40)]
    assert record(verdict="defect", findings=tuple(fs)).is_defect
    with pytest.raises(ValueError, match="contradicts the findings"):
        record(verdict="ok", findings=tuple(fs))
    with pytest.raises(ValueError, match="contradicts the findings"):
        record(verdict="defect")  # a defect verdict needs a defect finding
    with pytest.raises(ValueError, match="verdict must be one of"):
        record(verdict="great")


def test_findings_accept_dicts_and_are_normalised_to_findings() -> None:
    r = record(verdict="style", findings=({"kind": "style", "note": "naming"},))
    assert isinstance(r.findings[0], Finding) and r.findings[0].note == "naming"


def test_regression_is_never_mergeable() -> None:
    fs = (Finding("regression", "breaks --help"),)
    assert record(verdict="regression", findings=fs, mergeable=False).mergeable is False
    with pytest.raises(ValueError, match="cannot be mergeable"):
        record(verdict="regression", findings=fs, mergeable=True)
    # a defect may still be judged mergeable-with-follow-up: that is the reviewer's call
    assert record(verdict="defect", findings=(Finding("defect", "d"),), mergeable=True).mergeable


def test_not_reviewed_carries_nothing() -> None:
    r = record(verdict="not_reviewed", patch_sha256_reviewed="", statement="worktree gone")
    assert not r.reviewed and r.patch_sha256_reviewed == ""
    with pytest.raises(ValueError, match="no findings"):
        record(verdict="not_reviewed", patch_sha256_reviewed="", findings=(Finding("style", "s"),))
    with pytest.raises(ValueError, match="cannot answer mergeable"):
        record(verdict="not_reviewed", patch_sha256_reviewed="", mergeable=True)
    with pytest.raises(ValueError, match="names no patch hash"):
        record(verdict="not_reviewed")


def test_required_fields() -> None:
    with pytest.raises(ReviewRefused) as ei:
        record(grade_row_hash="")
    assert ei.value.code == REFUSAL_ROW_HASH_MISSING
    for missing in ("repo", "task_id", "reviewer"):
        with pytest.raises(ValueError, match=missing):
            record(**{missing: ""})
    with pytest.raises(ValueError, match="statement is required"):
        record(statement="  ")
    with pytest.raises(ReviewRefused) as ei:
        record(patch_sha256_reviewed="")
    assert ei.value.code == REFUSAL_PATCH_HASH_MISSING
    with pytest.raises(ValueError, match="64-character"):
        record(patch_sha256_reviewed="abc")
    assert is_sha256(DIFF_SHA) and not is_sha256("D" * 64) and not is_sha256("d" * 63)


def test_statement_is_redacted() -> None:
    r = record(statement="looked fine; password=hunter2xyz leaked in a fixture")
    assert "hunter2xyz" not in r.statement and "[REDACTED]" in r.statement


def test_to_dict_from_dict_round_trip_and_hash() -> None:
    r = record(
        verdict="api_change",
        findings=(Finding("api_change", "renamed public fn", file="a.py", line=3),),
        mergeable=False,
    ).chained(GENESIS_HASH)
    d = r.to_dict()
    assert d["findings"] == [
        {"kind": "api_change", "note": "renamed public fn", "file": "a.py", "line": 3}
    ]
    assert d["row_hash"] == r.row_hash and r.verify_hash()
    back = ReviewRecord.from_dict(json.loads(json.dumps(d)))
    assert back == r and back.verify_hash()
    # unknown keys are ignored; the hash covers every field but row_hash
    assert ReviewRecord.from_dict({**d, "extra": 1}) == r
    assert "row_hash" not in r.body() and "prev_hash" in r.body()


# ---------------------------------------------------------------------------
# the anchor
# ---------------------------------------------------------------------------


def test_pack_diff_sha256_reads_the_pack_shape() -> None:
    assert pack_diff_sha256(pack()) == DIFF_SHA
    assert pack_diff_sha256(pack(None)) == ""
    assert pack_diff_sha256({"grade": None}) == ""
    assert pack_diff_sha256({}) == ""


def test_anchor_holds_only_when_the_hashes_are_equal() -> None:
    check_patch_anchor(record(), pack())  # equal → fine
    with pytest.raises(ReviewRefused) as ei:
        check_patch_anchor(record(patch_sha256_reviewed="e" * 64), pack())
    assert ei.value.code == REFUSAL_PATCH_HASH_MISMATCH
    assert ei.value.expected == DIFF_SHA and ei.value.observed == "e" * 64
    with pytest.raises(ReviewRefused) as ei:
        check_patch_anchor(record(), pack(None))
    assert ei.value.code == REFUSAL_NO_DIFF_IN_PACK
    # not_reviewed attests to nothing and passes against any pack
    nr = record(verdict="not_reviewed", patch_sha256_reviewed="")
    check_patch_anchor(nr, pack(None))
    check_patch_anchor(nr, pack())


# ---------------------------------------------------------------------------
# JSONL ledger: chain, verify, tamper
# ---------------------------------------------------------------------------


def test_jsonl_ledger_chains_verifies_and_anchors(tmp_path: Path) -> None:
    led = JsonlReviewLedger(tmp_path / "reviews.jsonl")
    assert led.verify() == 0
    r1 = led.append(record(), pack=pack())
    r2 = led.append(record(verdict="style", findings=(Finding("style", "s"),)), pack=pack())
    assert r1.prev_hash == GENESIS_HASH and r2.prev_hash == r1.row_hash
    assert r1.verify_hash() and r2.verify_hash()
    assert led.verify() == 2
    assert [r.review_id for r in led.records()] == [r1.review_id, r2.review_id]
    with pytest.raises(ReviewRefused, match="does not match"):
        led.append(record(patch_sha256_reviewed="e" * 64), pack=pack())
    assert led.verify() == 2  # nothing was written


def test_jsonl_ledger_detects_edit_reorder_and_removal(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    led = JsonlReviewLedger(path)
    for i in range(3):
        led.append(record(statement=f"review {i}"))
    lines = path.read_text(encoding="utf-8").splitlines()

    edited = json.loads(lines[1])
    edited["statement"] = "review 1 (edited)"
    path.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match=r"review 2 .* row_hash mismatch"):
        led.verify()

    path.write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match=r"review 2 .* prev_hash mismatch"):
        led.verify()

    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match=r"review 2 .* prev_hash mismatch"):
        led.verify()

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert led.verify() == 3


def test_verify_review_chain_over_records() -> None:
    a = record().chained(GENESIS_HASH)
    b = record().chained(a.row_hash)
    assert verify_review_chain([a, b]) == 2
    with pytest.raises(LedgerIntegrityError):
        verify_review_chain([b, a])


# ---------------------------------------------------------------------------
# per-cell statistics
# ---------------------------------------------------------------------------


def test_latest_review_per_row_is_the_standing_verdict() -> None:
    first = record().chained(GENESIS_HASH)
    second = record(verdict="defect", findings=(Finding("defect", "d"),)).chained(first.row_hash)
    other = record(grade_row_hash="b" * 64).chained(second.row_hash)
    standing = latest_reviews([first, second, other])
    assert standing[ROW_HASH] is second and standing["b" * 64] is other


def test_review_cell_stats_joins_reviews_onto_rows_by_row_hash() -> None:
    rows: list[GradeRow] = []
    prev = GENESIS_HASH
    for i in range(5):
        rows.append(grade_row(trial=f"r{i}").chained(prev))
        prev = rows[-1].row_hash
    other_cell = grade_row(trial="x", capability_class="test.add", size="XS").chained(prev)
    dq = grade_row(
        trial="dq", clean=False, target_green=False, disqualified=True, dq_reason="tamper"
    ).chained(other_cell.row_hash)
    rows += [other_cell, dq]

    def rev(row: GradeRow, verdict: str = "ok", **kw: Any) -> ReviewRecord:
        findings = () if verdict in ("ok", "not_reviewed") else (Finding(verdict, "n"),)
        sha = "" if verdict == "not_reviewed" else DIFF_SHA
        return record(
            grade_row_hash=row.row_hash,
            verdict=verdict,
            findings=findings,
            patch_sha256_reviewed=sha,
            **kw,
        )

    reviews = [
        rev(rows[0], "ok", mergeable=True),
        rev(rows[1], "defect", mergeable=False),
        rev(rows[1], "regression", mergeable=False),  # supersedes the defect
        rev(rows[2], "style", mergeable=True),
        rev(rows[3], "not_reviewed", statement="worktree gone"),
        rev(other_cell, "api_change"),
        rev(dq, "ok"),  # a review of a disqualified row is not counted (row not eligible)
        record(grade_row_hash="f" * 64),  # a review of a row we do not have: ignored
    ]
    stats = review_cell_stats(rows, reviews)
    assert [s.cell.label for s in stats] == [rows[0].cell.label, other_cell.cell.label]
    main = stats[0]
    assert main.n_rows == 5 and main.n_reviewed == 3 and main.n_review_defects == 1
    assert (main.n_ok, main.n_defect, main.n_regression, main.n_style, main.n_api_change) == (
        1,
        0,
        1,
        1,
        0,
    )
    assert main.n_not_reviewed == 1 and main.n_mergeable == 2 and main.n_not_mergeable == 1
    assert main.reviewed_share == pytest.approx(0.6)
    assert (
        main.to_dict()["n_review_defects"] == 1 and main.to_dict()["capability_class"] == "bug.fix"
    )
    assert stats[1].n_rows == 1 and stats[1].n_reviewed == 1 and stats[1].n_api_change == 1

    # projected to (class): the two cells collapse into their classes, '*' elsewhere
    by_class = review_cell_stats(rows, reviews, projection=("capability_class",))
    assert [s.cell.label for s in by_class] == ["*|bug.fix|*|*|*|*|*", "*|test.add|*|*|*|*|*"]
    assert by_class[0].n_reviewed == 3
    with pytest.raises(ValueError, match="projection"):
        review_cell_stats(rows, reviews, projection=("nope",))
    assert review_cell_stats([], reviews) == []


def test_review_cell_stats_invariants() -> None:
    from crb.core.ledger import CellKey

    key = CellKey("replay", "bug.fix", "S", "python", "b", "m", "p")
    with pytest.raises(ValueError, match="n_reviewed"):
        ReviewCellStats(cell=key, n_rows=1, n_reviewed=1, n_review_defects=0)
    with pytest.raises(ValueError, match="n_review_defects"):
        ReviewCellStats(cell=key, n_rows=1, n_reviewed=1, n_review_defects=1, n_ok=1)
    s = ReviewCellStats(cell=key, n_rows=0, n_reviewed=0, n_review_defects=0)
    assert s.reviewed_share == 0.0
