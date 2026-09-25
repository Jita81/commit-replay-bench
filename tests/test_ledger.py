"""crb.core.ledger — GradeRow invariants, the hash chain, cell statistics.

Navigation
----------
What it is:   The ledger's test suite — ``GradeRow`` invariants, the hash chain and cell
              statistics.
What it does: Pins that a clean row must carry every belt ``True`` and an evidence-pack hash
              (anything else is ``FalseQ1Violation``), the belt-set ⇄ apparatus coupling
              (a measured 2.2 row cannot claim ``v3-legacy`` — the sign-off's reproduction; belt 5
              is unrecorded on v4 and census rows, and a v4 body hashes byte-identically to the
              four-belt apparatus), the JSONL chain's detection of an edited, deleted, reordered
              or truncated line, that a forged false-Q1 row is counted at read time, the
              failure-kind and cost-known derivations and their labels, the failure split, that
              the mirrored builder constants cannot drift, and that outage rows (237 usage-limit
              refusals in one evening) are not observations.
How:          In-memory rows and a temp JSONL file; nothing runs a test or a model.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md,
              docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/ledger.py (under test), src/crb/core/grade.py (``FalseQ1Violation``
              and the result rows derive from), src/crb/core/stats.py (the Wilson bound in
              ``cell_stats``), src/crb/builders/base.py (the constants the core mirrors),
              tests/test_store_ledger.py (the same chain in the database),
              docs/EVIDENCE-AND-CLAIMS.md (the apparatus stamp rule the coupling enforces)
Tested by:    tests/test_ledger.py
Touch when:   a field is added to ``GradeRow`` (it is hashed: pin the old rows still verify and
              the new ones commit to it); a belt set or apparatus version is introduced (extend
              ``expected_belt_sets`` and its table here); a failure kind is added.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from crb.core import ledger as lg
from crb.core.grade import FalseQ1Violation
from crb.core.stats import wilson_interval
from crb.core.version import APPARATUS_VERSION

SHA = "b7c6251293a287542ac8568cad7505b710fa3532"
PACK = "c" * 64


def row(**kw: Any) -> lg.GradeRow:
    """A clean, fully-evidenced row unless overridden."""
    base: dict[str, Any] = {
        "repo": "sqlalchemy",
        "task_id": SHA,
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "python",
        "builder": "agentic",
        "model": "gpt-oss-120b",
        "provider": "cerebras",
        "evidence_pack_hash": PACK,
        "gold_clean": True,
    }
    base.update(kw)
    # a belt set implies the apparatus that recorded it (review finding 4): a test that
    # names v4 / v3-legacy without a stamp gets the consistent one, never a contradiction
    if "apparatus_version" not in kw:
        if base.get("belt_set") == lg.BELT_SET_V4:
            base["apparatus_version"] = "2.1"
        elif base.get("belt_set") == lg.BELT_SET_V3_LEGACY:
            base["apparatus_version"] = "1.0-census"
            base.setdefault("provenance", "imported:census")
    return lg.GradeRow(**base)


# ---------------------------------------------------------------------------
# GradeRow invariants (enforced at write time)
# ---------------------------------------------------------------------------


def test_clean_row_with_full_evidence_is_accepted() -> None:
    r = row()
    assert r.clean and r.eligible and r.belts_all_true()
    assert r.row_id and len(r.row_id) == 32
    assert r.created and r.schema == lg.GRADE_SCHEMA and r.apparatus_version == APPARATUS_VERSION
    assert r.belt_set == lg.BELT_SET_V5 and r.provenance == "measured"
    assert r.recorded_belts() == (
        "tests_unmodified",
        "target_green",
        "no_new_failures",
        "source_changed",
        "repo_lint_clean",
    )
    assert r.repo_lint_clean is None  # a v5 row with no linter: belt 5 not evaluated


@pytest.mark.parametrize(
    "belt", ["tests_unmodified", "target_green", "no_new_failures", "source_changed"]
)
@pytest.mark.parametrize("value", [False, None])
def test_clean_with_any_belt_not_true_is_a_false_q1_violation(
    belt: str, value: bool | None
) -> None:
    with pytest.raises(FalseQ1Violation, match="refuses clean row"):
        row(**{belt: value})


def test_clean_without_evidence_pack_hash_is_a_false_q1_violation() -> None:
    with pytest.raises(FalseQ1Violation, match="no pack"):
        row(evidence_pack_hash="")


def test_clean_with_disqualification_or_error_is_a_false_q1_violation() -> None:
    with pytest.raises(FalseQ1Violation, match="disqualified"):
        row(disqualified=True)
    with pytest.raises(FalseQ1Violation, match="error"):
        row(error="harness crashed")


def test_not_clean_rows_may_carry_anything() -> None:
    r = row(
        clean=False,
        target_green=False,
        no_new_failures=None,
        source_changed=None,
        evidence_pack_hash="",
    )
    assert not r.clean and r.eligible
    dq = row(clean=False, disqualified=True, dq_reason="tamper", tests_unmodified=False)
    assert not dq.eligible
    weak = row(clean=False, gold_clean=False)
    assert not weak.eligible  # the oracle could not be satisfied by the humans' own patch
    assert row(clean=False, gold_clean=None).eligible  # unknown gold ≠ known-bad


def test_v3_legacy_belt_set_ignores_source_changed() -> None:
    legacy = row(belt_set=lg.BELT_SET_V3_LEGACY, source_changed=None, provenance="imported:census")
    assert legacy.clean and legacy.belts_all_true()
    assert legacy.recorded_belts() == ("tests_unmodified", "target_green", "no_new_failures")
    with pytest.raises(FalseQ1Violation):
        row(belt_set=lg.BELT_SET_V3_LEGACY, no_new_failures=False)
    with pytest.raises(ValueError, match="belt_set"):
        row(belt_set="v6")


# ---------------------------------------------------------------------------
# belt_set must agree with the apparatus (independent review pass 2026-09-14, finding 4)
# ---------------------------------------------------------------------------


def test_measured_row_cannot_claim_a_belt_set_older_than_its_apparatus(tmp_path: Path) -> None:
    """The sign-off's reproduction: a MEASURED 2.2 row claiming ``v3-legacy`` so that
    ``source_changed=False`` is not a recorded belt — constructed, appended, and
    ``false_q1_total == 0`` on 842875b. Refused at construction now, so at write and
    on read alike."""
    fields: dict[str, Any] = {
        "repo": "demo",
        "task_id": "deadbeef",
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": False,
        "evidence_pack_hash": "x" * 64,
        "belt_set": lg.BELT_SET_V3_LEGACY,
    }
    with pytest.raises(lg.LedgerIntegrityError, match="belt_set='v3-legacy' is not what"):
        lg.GradeRow(**fields)
    with pytest.raises(lg.LedgerIntegrityError):
        lg.GradeRow(**{**fields, "source_changed": None})  # still measured 2.2
    with pytest.raises(lg.LedgerIntegrityError):
        lg.GradeRow.from_dict({**fields, "apparatus_version": "2.2", "provenance": "measured"})
    # on read: a hand-written ledger line with the contradiction does not verify
    honest = lg.JsonlLedger(tmp_path / "g.jsonl").append(row())
    forged = {**honest.to_dict(), "belt_set": "v3-legacy", "source_changed": None}
    (tmp_path / "forged.jsonl").write_text(json.dumps(forged) + "\n")
    with pytest.raises(lg.LedgerIntegrityError, match="v3-legacy"):
        lg.JsonlLedger(tmp_path / "forged.jsonl").verify()


@pytest.mark.parametrize(
    ("apparatus", "provenance", "expected"),
    [
        ("1.0-census", "imported:expansion-bench-census-2026-07-08", ("v3-legacy", "v4")),
        ("1.0-census", "measured", ()),
        ("2.0", "measured", ("v4",)),
        ("2.1", "measured", ("v4",)),
        ("2.1.3", "measured", ("v4",)),
        ("2.2", "measured", ("v5",)),
        ("2.10", "measured", ("v5",)),
        ("3.0", "measured", ("v5",)),
        ("2.2", "imported:other-crb", ("v5",)),  # a federated import keeps its meaning
        ("2.0", "imported:other-crb", ("v4",)),
        ("1.9", "measured", ()),
        ("v3-legacy", "measured", ()),
        ("", "measured", ()),
        ("2.2-rc1", "measured", ()),
    ],
)
def test_expected_belt_sets_table(
    apparatus: str, provenance: str, expected: tuple[str, ...]
) -> None:
    assert lg.expected_belt_sets(apparatus, provenance) == expected
    assert lg.parse_apparatus_version("2.2") == (2, 2)
    assert lg.parse_apparatus_version("1.0-census") is None
    assert frozenset({"1.0-census"}) == lg.LEGACY_APPARATUS_VERSIONS


@pytest.mark.parametrize(
    ("apparatus", "provenance", "belt_set", "ok"),
    [
        ("2.2", "measured", "v5", True),
        ("2.2", "measured", "v4", False),
        ("2.2", "measured", "v3-legacy", False),
        ("2.1", "measured", "v4", True),
        ("2.1", "measured", "v5", False),
        ("2.0", "measured", "v3-legacy", False),
        ("1.0-census", "imported:census", "v4", True),
        ("1.0-census", "imported:census", "v3-legacy", True),
        ("1.0-census", "imported:census", "v5", False),
        ("1.0-census", "measured", "v4", False),
        ("1.0-census", "measured", "v3-legacy", False),
        ("2.5", "measured", "v4", False),
    ],
)
def test_belt_set_apparatus_coupling_at_construction(
    apparatus: str, provenance: str, belt_set: str, ok: bool
) -> None:
    kw: dict[str, Any] = {
        "apparatus_version": apparatus,
        "provenance": provenance,
        "belt_set": belt_set,
    }
    if belt_set == lg.BELT_SET_V3_LEGACY:
        kw["source_changed"] = None
    if ok:
        r = row(**kw)
        assert r.belt_set == belt_set
        assert lg.GradeRow.from_dict(r.chained(lg.GENESIS_HASH).to_dict()).belt_set == belt_set
    else:
        with pytest.raises(lg.LedgerIntegrityError, match="is not what apparatus"):
            row(**kw)


def test_v3_legacy_row_records_no_belt_four() -> None:
    with pytest.raises(lg.LedgerIntegrityError, match="records no belt 4"):
        row(belt_set=lg.BELT_SET_V3_LEGACY, source_changed=True)
    with pytest.raises(lg.LedgerIntegrityError, match="records no belt 4"):
        row(belt_set=lg.BELT_SET_V3_LEGACY, source_changed=False, clean=False)
    assert row(belt_set=lg.BELT_SET_V3_LEGACY, source_changed=None).recorded_belts() == (
        "tests_unmodified",
        "target_green",
        "no_new_failures",
    )


def test_grade_row_from_result_stamps_the_current_apparatus_as_v5() -> None:
    """The product's own write path is consistent with the coupling by construction."""
    from crb.core.grade import Belts, GradeResult
    from crb.core.spec import TaskSpec

    task = TaskSpec(
        task_id=SHA,
        repo="r",
        subject="s",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_a.py",),
        src_files=("src/a.py",),
        target_tests=("tests/test_a.py",),
        belt_scope=("tests/",),
    )
    res = GradeResult(SHA, "r", "sighted", clean=True, belts=Belts(True, True, True, True))
    r = lg.grade_row_from_result(res, task, pack_hash=PACK)
    assert (r.belt_set, r.apparatus_version, r.provenance) == ("v5", APPARATUS_VERSION, "measured")
    assert lg.expected_belt_sets(APPARATUS_VERSION, "measured") == ("v5",)


# ---------------------------------------------------------------------------
# belt 5 (ADR-0011): recorded on v5 only; None = not evaluated; False never clean
# ---------------------------------------------------------------------------


def test_v5_row_belt_five_none_is_not_evaluated_and_false_is_a_false_q1() -> None:
    assert lg.BELT_SETS == ("v5", "v4", "v3-legacy")
    assert row(repo_lint_clean=None).clean
    assert row(repo_lint_clean=True).clean and row(repo_lint_clean=True).belts_all_true()
    with pytest.raises(FalseQ1Violation, match="refuses clean row"):
        row(repo_lint_clean=False)
    failed = row(clean=False, repo_lint_clean=False)
    assert not failed.belts_all_true() and failed.eligible and failed.lint_only()
    assert failed.failure_kind == lg.FAILURE_LINT
    # lint is named only when the code otherwise works
    red = row(clean=False, target_green=False, repo_lint_clean=False)
    assert not red.lint_only() and red.failure_kind == lg.FAILURE_BUILDER_RED
    assert lg.lint_only_failure({"repo_lint_clean": False}) is False


@pytest.mark.parametrize("belt_set", [lg.BELT_SET_V4, lg.BELT_SET_V3_LEGACY])
@pytest.mark.parametrize("value", [True, False])
def test_pre_belt_five_rows_never_carry_belt_five(belt_set: str, value: bool) -> None:
    """A census / v4 row is never re-interpreted: belt 5 is unrecorded there."""
    kw: dict[str, Any] = {"belt_set": belt_set, "repo_lint_clean": value}
    if belt_set == lg.BELT_SET_V3_LEGACY:
        kw["source_changed"] = None
    with pytest.raises(ValueError, match="unrecorded"):
        row(**kw)
    r = row(**{**kw, "repo_lint_clean": None})
    assert "repo_lint_clean" not in r.recorded_belts() and not r.lint_only()
    assert "repo_lint_clean" not in r.body()  # not hashed: pre-belt-5 rows verify as before
    assert r.to_dict()["repo_lint_clean"] is None  # but written honestly as null


def test_pre_belt_five_hashes_are_byte_identical_to_the_four_belt_apparatus() -> None:
    """The load-bearing compatibility fact: a v4 body is exactly the pre-belt-5 body, so
    a ledger written before ADR-0011 verifies unchanged after the upgrade."""
    r = row(belt_set=lg.BELT_SET_V4).chained(lg.GENESIS_HASH)
    body = r.body()
    assert set(body) == set(lg.GradeRow.__dataclass_fields__) - {"row_hash", "repo_lint_clean"}
    assert r.verify_hash()
    v5 = row(belt_set=lg.BELT_SET_V5).chained(lg.GENESIS_HASH)
    assert "repo_lint_clean" in v5.body() and v5.body()["repo_lint_clean"] is None
    # the same facts under v4 and v5 hash differently: the belt set is part of the body
    assert v5.row_hash != r.row_hash
    # v5 commits to "not evaluated": flipping it to True changes the hash
    flipped = lg.GradeRow(**{**v5.fields(), "repo_lint_clean": True})
    assert flipped.compute_hash() != v5.row_hash


def test_v5_rows_round_trip_through_jsonl_with_belt_five(tmp_path: Path) -> None:
    led = lg.JsonlLedger(tmp_path / "g.jsonl")
    led.append(row(repo_lint_clean=True))
    led.append(row(clean=False, repo_lint_clean=False))
    led.append(row(repo_lint_clean=None))
    led.append(row(belt_set=lg.BELT_SET_V4))
    rows = list(led.rows())
    assert [r.repo_lint_clean for r in rows] == [True, False, None, None]
    assert [r.belt_set for r in rows] == ["v5", "v5", "v5", "v4"]
    assert [r.failure_kind for r in rows] == ["", "lint", "", ""]
    assert led.verify() == 4
    assert lg.false_q1_total(rows) == 0
    lines = [json.loads(line) for line in led.path.read_text().splitlines()]
    assert lines[1]["failure_kind"] == "lint" and lines[1]["labels"] == {}
    assert lines[3]["repo_lint_clean"] is None and lines[3]["belt_set"] == "v4"


def test_labels_are_copied_and_cell_key() -> None:
    labels = {"k": "v"}
    r = row(labels=labels)
    labels["k"] = "changed"
    assert r.labels == {"k": "v"}
    assert r.cell == lg.CellKey(
        "replay", "bug.fix", "XS", "python", "agentic", "gpt-oss-120b", "cerebras"
    )
    assert r.cell.to_tuple() == (
        "replay",
        "bug.fix",
        "XS",
        "python",
        "agentic",
        "gpt-oss-120b",
        "cerebras",
    )
    assert r.cell.label == "replay|bug.fix|XS|python|agentic|gpt-oss-120b|cerebras"
    assert r.cell.to_dict() == dict(zip(lg.CELL_FIELDS, r.cell.to_tuple(), strict=True))


# ---------------------------------------------------------------------------
# hashing + chaining
# ---------------------------------------------------------------------------


def test_chained_and_verify_hash() -> None:
    r = row()
    assert r.row_hash == "" and not r.verify_hash()
    c = r.chained(lg.GENESIS_HASH)
    assert c.prev_hash == lg.GENESIS_HASH
    assert len(c.row_hash) == 64 and c.verify_hash()
    assert c.row_id == r.row_id and c.created == r.created  # same observation
    assert c.compute_hash() == c.row_hash
    assert "row_hash" not in c.body()
    tampered = lg.GradeRow.from_dict({**c.to_dict(), "cost_usd": 99.0})
    assert not tampered.verify_hash()


def test_to_dict_from_dict_round_trip_and_unknown_keys_ignored() -> None:
    c = row(labels={"a": "b"}, cost_usd=0.01, oracle_strength=0.9).chained("f" * 64)
    d = c.to_dict()
    json.dumps(d)
    assert lg.GradeRow.from_dict({**d, "unknown_future_field": 1}) == c


def test_verify_chain_empty_and_genesis() -> None:
    assert lg.verify_chain([]) == 0
    assert lg.GENESIS_HASH == "0" * 64
    with pytest.raises(lg.LedgerIntegrityError, match="prev_hash"):
        lg.verify_chain([row().chained("1" * 64)])


# ---------------------------------------------------------------------------
# JsonlLedger
# ---------------------------------------------------------------------------


def _fill(path: Path, n: int = 4) -> tuple[lg.JsonlLedger, list[lg.GradeRow]]:
    led = lg.JsonlLedger(path)
    rows = led.append_many(
        row(clean=bool(i % 2), target_green=bool(i % 2), evidence_pack_hash=PACK if i % 2 else "")
        for i in range(n)
    )
    return led, rows


def test_ledger_append_rows_verify(tmp_path: Path) -> None:
    led, rows = _fill(tmp_path / "nested" / "grades.jsonl")
    assert led.path.exists()
    assert rows[0].prev_hash == lg.GENESIS_HASH
    for a, b in itertools.pairwise(rows):
        assert b.prev_hash == a.row_hash
    assert [r.row_hash for r in led.rows()] == [r.row_hash for r in rows]
    assert led.verify() == 4
    assert lg.JsonlLedger(tmp_path / "absent.jsonl").verify() == 0
    assert list(lg.JsonlLedger(tmp_path / "absent.jsonl").rows()) == []


def test_ledger_refuses_a_false_q1_row_before_writing(tmp_path: Path) -> None:
    """Constructing a false-Q1 row through the API is impossible; a row forged after
    construction (frozen-dataclass bypass) is still refused by the ledger's re-check."""
    led = lg.JsonlLedger(tmp_path / "g.jsonl")
    with pytest.raises(FalseQ1Violation):
        lg.GradeRow.from_dict({**row(clean=False).to_dict(), "clean": True, "target_green": False})
    forged = row(clean=False)
    object.__setattr__(forged, "clean", True)
    object.__setattr__(forged, "target_green", False)
    with pytest.raises(FalseQ1Violation):
        led.append(forged)
    assert not led.path.exists()


def test_ledger_detects_an_edited_middle_line(tmp_path: Path) -> None:
    led, _ = _fill(tmp_path / "g.jsonl")
    lines = led.path.read_text().splitlines()
    d = json.loads(lines[1])
    d["cost_usd"] = 12.5
    lines[1] = json.dumps(d, sort_keys=True)
    led.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(lg.LedgerIntegrityError, match=r"row 2 .* row_hash mismatch"):
        led.verify()


def test_ledger_detects_a_deleted_line(tmp_path: Path) -> None:
    led, _ = _fill(tmp_path / "g.jsonl")
    lines = led.path.read_text().splitlines()
    del lines[1]
    led.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(lg.LedgerIntegrityError, match=r"row 2 .* prev_hash mismatch"):
        led.verify()


def test_ledger_detects_reordering(tmp_path: Path) -> None:
    led, _ = _fill(tmp_path / "g.jsonl")
    lines = led.path.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    led.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(lg.LedgerIntegrityError, match=r"row 2 .* prev_hash mismatch"):
        led.verify()


def test_ledger_detects_a_truncated_tail_via_next_append(tmp_path: Path) -> None:
    """Deleting the LAST line breaks nothing until the next append re-chains from the
    new last row — the next verify still proves the row count; the ledger stays consistent."""
    led, rows = _fill(tmp_path / "g.jsonl")
    lines = led.path.read_text().splitlines()
    led.path.write_text("\n".join(lines[:-1]) + "\n")
    assert led.verify() == 3
    new = led.append(row(clean=False))
    assert new.prev_hash == rows[2].row_hash
    assert led.verify() == 4


def test_ledger_last_hash_handles_blank_trailing_lines_and_missing_hash(tmp_path: Path) -> None:
    led, rows = _fill(tmp_path / "g.jsonl", 2)
    with led.path.open("a") as f:
        f.write("\n\n")
    assert led.append(row(clean=False)).prev_hash == rows[-1].row_hash
    broken = lg.JsonlLedger(tmp_path / "b.jsonl")
    broken.path.write_text(json.dumps({"task_id": SHA}) + "\n")
    with pytest.raises(lg.LedgerIntegrityError, match="no row_hash"):
        broken.append(row(clean=False))
    empty = lg.JsonlLedger(tmp_path / "e.jsonl")
    empty.path.write_text("")
    assert empty.append(row(clean=False)).prev_hash == lg.GENESIS_HASH
    blank = lg.JsonlLedger(tmp_path / "w.jsonl")
    blank.path.write_text("\n \n")  # non-empty file, no rows
    assert blank.append(row(clean=False)).prev_hash == lg.GENESIS_HASH


# ---------------------------------------------------------------------------
# Cell statistics
# ---------------------------------------------------------------------------


def _cell_rows() -> list[lg.GradeRow]:
    return [
        *(row(cost_usd=0.02, latency_s=10.0, oracle_strength=0.9) for _ in range(8)),
        row(clean=False, target_green=False, cost_usd=0.04, latency_s=20.0),
        row(clean=False, no_new_failures=False, oracle_strength=0.7),
        row(clean=False, disqualified=True, dq_reason="tamper", tests_unmodified=False),
        row(clean=False, error="sandbox", target_green=None),
        row(clean=True, gold_clean=False),  # judged on a weak oracle: excluded from n
        row(apparatus_version="2.1", belt_set=lg.BELT_SET_V4),  # an older-apparatus row
    ]


def test_cell_stats_numbers() -> None:
    s = lg.cell_stats(_cell_rows())
    # 14 rows: DQ (1) and gold_clean=False (1) are excluded → n=12; clean = 8 + 1 (v2.1) = 9
    assert s.n == 12
    assert s.clean == 9
    assert s.disqualified == 1
    assert s.errors == 1
    assert s.false_q1 == 0
    assert s.point == pytest.approx(9 / 12)
    assert s.ci == wilson_interval(9, 12)
    # cost is a row fact (F35): every eligible row here names a builder that reported
    # through the ledger, so a $0 is a KNOWN $0 and counts; latency 0 s is "not recorded"
    assert all(r.cost_known for r in _cell_rows())
    assert s.cost_usd_mean == pytest.approx((0.02 * 8 + 0.04) / 12)
    assert s.latency_s_mean == pytest.approx((10.0 * 8 + 20.0) / 9)
    assert s.oracle_strength_mean == pytest.approx((0.9 * 8 + 0.7) / 9)
    assert s.apparatus_versions == ("2.1", APPARATUS_VERSION)
    d = s.to_dict()
    assert d["process_step"] == "replay" and d["n"] == 12 and d["point"] == round(9 / 12, 4)
    assert d["ci_low"] == round(s.ci.low, 4) and d["oracle_strength_mean"] == round(
        s.oracle_strength_mean, 4
    )


def test_cell_stats_cost_mean_leaves_out_unknown_costs_and_keeps_a_known_zero() -> None:
    # F35: an unknown cost (imported, or pinned cost_known=false) is left out of the mean;
    # a known $0 stays in it. Before F35 the fold dropped every $0 and kept every unknown.
    rs = [
        row(cost_usd=0.10),
        row(cost_usd=0.0),  # a builder reported $0: known
        row(cost_usd=0.0, provenance="imported:census"),  # never reported: unknown
        row(cost_usd=0.50, labels={lg.LABEL_COST_KNOWN: "false"}),  # pinned unknown
    ]
    assert [r.cost_known for r in rs] == [True, True, False, False]
    assert lg.cell_stats(rs).cost_usd_mean == pytest.approx(0.05)


def test_cell_stats_without_oracle_strength_and_empty() -> None:
    s = lg.cell_stats([row(clean=False, target_green=False)])
    assert s.oracle_strength_mean is None and s.point == 0.0 and s.n == 1
    assert lg.cell_stats([row(clean=False, disqualified=True)]).n == 0
    assert lg.cell_stats([row(clean=False, disqualified=True)]).ci == wilson_interval(0, 0)
    with pytest.raises(ValueError, match="at least one row"):
        lg.cell_stats([])


def test_false_q1_is_counted_at_read_time_for_forged_rows() -> None:
    """The write-time invariant makes this impossible through the API; the read-time
    count exists so an imported/forged ledger still cannot hide one."""
    r = row()
    object.__setattr__(r, "target_green", False)
    assert lg.false_q1_total([r, row()]) == 1
    assert lg.cell_stats([r, row()]).false_q1 == 1
    assert lg.false_q1_total([row(), row(clean=False, target_green=False)]) == 0


def test_group_by_cell_and_projections() -> None:
    rows = [
        row(model="a"),
        row(model="a", size="S"),
        row(model="b"),
        row(model="b", capability_class="test.add"),
    ]
    full = lg.group_by_cell(rows)
    assert len(full) == 4
    by_class_size = lg.group_by_cell(rows, key_fields=("capability_class", "size"))
    assert {k: len(v) for k, v in by_class_size.items()} == {
        ("bug.fix", "XS"): 2,
        ("bug.fix", "S"): 1,
        ("test.add", "XS"): 1,
    }
    stats = lg.all_cell_stats(rows)
    assert len(stats) == 4
    assert {s.cell.model for s in stats} == {"a", "b"}
    assert all(s.n == 1 and s.clean == 1 for s in stats)


# ---------------------------------------------------------------------------
# failure_kind — THE derivation rule, one case per branch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"clean": True}, lg.FAILURE_CLEAN),
        ({"clean": False, "disqualified": True}, lg.FAILURE_DISQUALIFIED),
        # a DQ with an error is still a DQ (rule 2 before rule 3/4)
        ({"clean": False, "disqualified": True, "error": "Boom: x"}, lg.FAILURE_DISQUALIFIED),
        ({"clean": False, "error": "protocol violation: network: curl"}, lg.FAILURE_PROTOCOL),
        # the refusal recorded only on the label still names the row protocol
        (
            {
                "clean": False,
                "error": "RuntimeError: grader",
                "builder_error": "protocol violation: tamper: t.py",
            },
            lg.FAILURE_PROTOCOL,
        ),
        ({"clean": False, "error": "SandboxUnavailable: docker"}, lg.FAILURE_HARNESS),
        ({"clean": False, "error": "model_error: no credential"}, lg.FAILURE_HARNESS),
        ({"clean": False, "error": "TimeoutError: belt run"}, lg.FAILURE_HARNESS),
        ({"clean": False, "stop_reason": "wall_clock"}, lg.FAILURE_BUDGET),
        ({"clean": False, "stop_reason": "max_turns"}, lg.FAILURE_BUDGET),
        ({"clean": False, "stop_reason": "max_tool_calls"}, lg.FAILURE_BUDGET),
        ({"clean": False, "stop_reason": "max_tokens"}, lg.FAILURE_BUDGET),
        ({"clean": False, "stop_reason": "max_cost_usd"}, lg.FAILURE_BUDGET),
        # an errored grade is not an observation of the patch: harness beats budget
        ({"clean": False, "stop_reason": "wall_clock", "error": "OSError: x"}, lg.FAILURE_HARNESS),
        ({"clean": False, "stop_reason": "done"}, lg.FAILURE_BUILDER_RED),
        ({"clean": False, "stop_reason": "no_tool_call"}, lg.FAILURE_BUILDER_RED),
        ({"clean": False}, lg.FAILURE_BUILDER_RED),
        # belt 5: working but non-conforming code is its own kind …
        ({"clean": False, "lint_only": True}, lg.FAILURE_LINT),
        ({"clean": False, "lint_only": True, "stop_reason": "done"}, lg.FAILURE_LINT),
        # … unless the attempt was cut short or the instrument failed
        ({"clean": False, "lint_only": True, "stop_reason": "wall_clock"}, lg.FAILURE_BUDGET),
        (
            {"clean": False, "lint_only": True, "error": "lint: ruff: not runnable"},
            lg.FAILURE_HARNESS,
        ),
        ({"clean": False, "lint_only": True, "disqualified": True}, lg.FAILURE_DISQUALIFIED),
    ],
)
def test_derive_failure_kind_each_branch(kw: dict[str, Any], expected: str) -> None:
    args: dict[str, Any] = {"disqualified": False, **kw}
    assert lg.derive_failure_kind(**args) == expected
    assert expected in lg.FAILURE_KINDS


def test_budget_stop_reasons_mirror_the_builders_vocabulary() -> None:
    """The core cannot import crb.builders; this pins the mirrored constants."""
    from crb.builders import base as bb

    assert set(lg.BUDGET_STOP_REASONS) == {
        bb.STOP_MAX_TURNS,
        bb.STOP_MAX_TOOL_CALLS,
        bb.STOP_MAX_TOKENS,
        bb.STOP_MAX_COST,
        bb.STOP_WALL_CLOCK,
    }
    assert set(lg.BUDGET_STOP_REASONS) < set(bb.STOP_REASONS)
    assert bb.STOP_DONE not in lg.BUDGET_STOP_REASONS
    assert bb.STOP_MODEL_ERROR not in lg.BUDGET_STOP_REASONS
    assert bb.STOP_NO_TOOL_CALL not in lg.BUDGET_STOP_REASONS


def test_protocol_prefix_and_cost_mark_match_the_builders() -> None:
    from crb.builders import adapter
    from crb.builders.base import BuildOutcome

    out = BuildOutcome("b", "m", "p", "sighted", errors=("network: curl example.com",))
    assert adapter.attempt_error(out).startswith(lg.PROTOCOL_VIOLATION_PREFIX)
    unpriced = BuildOutcome("b", "m", "p", "sighted", stop_reason="done", cost_known=False)
    assert lg.COST_UNKNOWN_MARK in unpriced.builder_ref().note
    assert lg.builder_stop_reason(unpriced.builder_ref()) == "done"
    capped = BuildOutcome("b", "m", "p", "sighted", stop_reason="wall_clock", errors=("x",))
    assert lg.builder_stop_reason(capped.builder_ref()) == "wall_clock"
    assert lg.builder_stop_reason(None) == ""


def test_failure_kind_property_derives_for_rows_without_a_label() -> None:
    """Rows written before the label existed derive on read — from the same rule."""
    assert row().failure_kind == lg.FAILURE_CLEAN
    assert row(clean=False, target_green=False).failure_kind == lg.FAILURE_BUILDER_RED
    assert (
        row(clean=False, error="OSError: x", target_green=None).failure_kind == lg.FAILURE_HARNESS
    )
    assert (
        row(clean=False, error="protocol violation: archaeology: git log").failure_kind
        == lg.FAILURE_PROTOCOL
    )
    assert (
        row(
            clean=False, target_green=False, labels={"builder_error": "protocol violation: x"}
        ).failure_kind
        == lg.FAILURE_PROTOCOL
    )
    assert (
        row(clean=False, disqualified=True, tests_unmodified=False).failure_kind
        == lg.FAILURE_DISQUALIFIED
    )
    # an old row never recorded its stop reason: it cannot read budget
    assert row(clean=False, target_green=False).stop_reason == ""
    assert (
        row(clean=False, target_green=False, labels={"stop_reason": "wall_clock"}).failure_kind
        == lg.FAILURE_BUDGET
    )


def test_failure_kind_label_is_the_record_and_must_not_contradict_the_row() -> None:
    pinned = row(clean=False, target_green=False, labels={"failure_kind": "budget"})
    assert pinned.failure_kind == lg.FAILURE_BUDGET
    with pytest.raises(FalseQ1Violation, match="contradicts clean"):
        row(labels={"failure_kind": "harness"})  # a clean row cannot carry a failure
    with pytest.raises(FalseQ1Violation, match="contradicts clean"):
        row(clean=False, target_green=False, labels={"failure_kind": ""})
    with pytest.raises(ValueError, match="not in"):
        row(clean=False, target_green=False, labels={"failure_kind": "gremlins"})
    with pytest.raises(ValueError, match="contradicts disqualified"):
        row(clean=False, target_green=False, labels={"failure_kind": "disqualified"})
    with pytest.raises(ValueError, match="contradicts disqualified"):
        row(
            clean=False,
            disqualified=True,
            tests_unmodified=False,
            labels={"failure_kind": "harness"},
        )
    with pytest.raises(ValueError, match="cost_known label"):
        row(labels={"cost_known": "maybe"})


def test_to_dict_carries_the_derived_fields_and_from_dict_drops_them() -> None:
    c = row(clean=False, target_green=False, builder="").chained(lg.GENESIS_HASH)
    d = c.to_dict()
    assert d["failure_kind"] == lg.FAILURE_BUILDER_RED and d["cost_known"] is False
    assert "failure_kind" not in c.body() and "cost_known" not in c.body()
    # a stored copy that disagrees with the derivation is ignored, never trusted
    back = lg.GradeRow.from_dict({**d, "failure_kind": "harness", "cost_known": True})
    assert back == c and back.failure_kind == lg.FAILURE_BUILDER_RED and back.cost_known is False
    assert back.verify_hash()


# ---------------------------------------------------------------------------
# cost_known
# ---------------------------------------------------------------------------


def test_derive_cost_known_rule() -> None:
    dk = lg.derive_cost_known
    assert dk(cost_usd=0.2, tokens_in=0, tokens_out=0, builder_reported=False) is True
    assert dk(cost_usd=0.0, tokens_in=10, tokens_out=0, builder_reported=False) is True
    assert dk(cost_usd=0.0, tokens_in=0, tokens_out=3, builder_reported=False) is True
    # a fixture's $0 is a known zero; a row with no builder record reported nothing
    assert dk(cost_usd=0.0, tokens_in=0, tokens_out=0, builder_reported=True) is True
    assert dk(cost_usd=0.0, tokens_in=0, tokens_out=0, builder_reported=False) is False
    # tokens metered, no price for the model: the dollars are unknown
    assert (
        dk(cost_usd=0.0, tokens_in=500, tokens_out=50, builder_reported=True, pricing_known=False)
        is False
    )


def test_cost_known_property_label_or_derivation() -> None:
    assert row(cost_usd=0.01).cost_known is True
    assert row(tokens_in=10, cost_usd=0.0).cost_known is True
    assert row(builder="fixture_gold", cost_usd=0.0).cost_known is True  # identified builder
    assert row(builder="", cost_usd=0.0).cost_known is False
    assert row(builder="x", cost_usd=0.0, labels={"cost_known": "false"}).cost_known is False
    assert row(builder="", cost_usd=0.0, labels={"cost_known": "true"}).cost_known is True


# ---------------------------------------------------------------------------
# grade_row_from_result pins the classification into the hashed labels
# ---------------------------------------------------------------------------


def _result(*, clean: bool, error: str = "", disqualified: bool = False) -> Any:
    from crb.core.grade import Belts, GradeResult

    if error:
        belts = Belts()
    elif disqualified:
        belts = Belts(tests_unmodified=False)
    elif clean:
        belts = Belts(True, True, True, True)
    else:
        belts = Belts(True, False, True, True)
    return GradeResult(
        task_id=SHA,
        repo="r",
        mode="sighted",
        clean=clean,
        belts=belts,
        error=error,
        disqualified=disqualified,
        dq_reason="tamper" if disqualified else "",
    )


def _task() -> Any:
    from crb.core.spec import TaskSpec

    return TaskSpec(
        task_id=SHA,
        repo="r",
        subject="s",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_a.py",),
        src_files=("src/a.py",),
        target_tests=("tests/test_a.py",),
        belt_scope=("tests/",),
        size="XS",
        capability_class="bug.fix",
        language="python",
        baseline_failing=("tests/test_a.py::test_x",),
        red_checked=True,
        gold_clean=True,
    )


def _from_result(result: Any, builder: Any = None, **kw: Any) -> lg.GradeRow:
    return lg.grade_row_from_result(result, _task(), pack_hash=PACK, builder=builder, **kw)


def test_grade_row_from_result_pins_failure_kind_and_cost_known() -> None:
    from crb.core.evidence import BuilderRef

    priced = BuilderRef(
        name="claude_code", model="m", provider="p", cost_usd=0.2, tokens_in=100, note="done"
    )
    r = _from_result(_result(clean=True), priced)
    # a clean row pins nothing it does not need: no failure_kind label, no cost_known
    # label (the priced row already says so) — byte-identical to a pre-A2 clean row
    assert r.failure_kind == "" and "failure_kind" not in r.labels and r.cost_known is True
    assert "cost_known" not in r.labels and r.labels["stop_reason"] == "done"

    red = _from_result(_result(clean=False), priced)
    assert red.failure_kind == lg.FAILURE_BUILDER_RED
    assert red.labels["failure_kind"] == "builder_red"

    # the live click blind row: 900 s wall clock, target not green → budget, not the model
    capped = BuilderRef(
        name="claude_code",
        model="m",
        provider="p",
        cost_usd=0.4,
        latency_s=900.0,
        note="wall_clock; 1 error(s)",
    )
    b = _from_result(_result(clean=False), capped)
    assert b.failure_kind == lg.FAILURE_BUDGET and b.labels["stop_reason"] == "wall_clock"
    assert b.error == ""  # a budget stop is not an error; the row still fails closed
    assert not b.clean

    guard = _from_result(
        _result(clean=False), priced, builder_error="protocol violation: archaeology: git log"
    )
    assert guard.failure_kind == lg.FAILURE_PROTOCOL
    assert guard.error.startswith("protocol violation:")
    assert guard.labels["builder_error"].startswith("protocol")

    harness = _from_result(_result(clean=False, error="SandboxUnavailable: docker"), priced)
    assert harness.failure_kind == lg.FAILURE_HARNESS

    api = _from_result(_result(clean=False), priced, builder_error="model_error: 401 unauthorized")
    assert api.failure_kind == lg.FAILURE_HARNESS and api.error == "model_error: 401 unauthorized"

    dq = _from_result(_result(clean=False, disqualified=True), priced)
    assert dq.failure_kind == lg.FAILURE_DISQUALIFIED and not dq.eligible

    # the builder's OWN error on a CLEAN row never changes the verdict or the kind
    ok_with_note = _from_result(_result(clean=True), priced, builder_error="model_error: retry")
    assert ok_with_note.clean and ok_with_note.failure_kind == "" and ok_with_note.error == ""


def test_grade_row_from_result_cost_known_cases() -> None:
    from crb.core.evidence import BuilderRef

    fixture = BuilderRef(name="fixture_gold", model="gold", provider="fixture", note="done")
    assert _from_result(_result(clean=True), fixture).cost_known is True  # a known zero
    unpriced = BuilderRef(
        name="claude_code",
        model="new",
        provider="p",
        tokens_in=900,
        note="done; cost unknown (no pricing for model)",
    )
    assert _from_result(_result(clean=True), unpriced).cost_known is False
    assert _from_result(_result(clean=True), unpriced).labels["cost_known"] == "false"
    nothing = _from_result(_result(clean=True), None)
    assert nothing.cost_known is False and "cost_known" not in nothing.labels  # derivable
    assert nothing.stop_reason == "" and "stop_reason" not in nothing.labels


def test_new_rows_hash_the_classification_old_rows_still_verify(tmp_path: Path) -> None:
    """The labels are part of the hashed body: a new row's chain commits to its
    failure_kind; a row written without the labels verifies exactly as before."""
    from crb.core.evidence import BuilderRef

    led = lg.JsonlLedger(tmp_path / "g.jsonl")
    old = led.append(row(clean=False, target_green=False))  # no labels: pre-change shape
    new = led.append(_from_result(_result(clean=False), BuilderRef(name="b", note="wall_clock")))
    assert "failure_kind" not in old.labels and new.labels["failure_kind"] == "budget"
    assert led.verify() == 2
    # flipping the pinned kind breaks the new row's hash
    lines = led.path.read_text().splitlines()
    d = json.loads(lines[1])
    d["labels"]["failure_kind"] = "builder_red"
    d["labels"]["stop_reason"] = "done"
    lines[1] = json.dumps(d, sort_keys=True)
    led.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(lg.LedgerIntegrityError, match=r"row 2 .* row_hash mismatch"):
        led.verify()


# ---------------------------------------------------------------------------
# the split + model point
# ---------------------------------------------------------------------------


def _split_rows() -> list[lg.GradeRow]:
    return [
        *(row(cost_usd=0.02) for _ in range(6)),  # clean, cost known
        row(clean=False, target_green=False, tokens_in=5),  # builder_red
        row(
            clean=False,
            target_green=False,
            labels={"failure_kind": "budget", "stop_reason": "wall_clock"},
        ),
        # instrument rows: the builder never metered anything (no price → cost unknown)
        row(
            clean=False,
            error="protocol violation: network: curl",
            target_green=None,
            labels={"cost_known": "false"},
        ),
        row(
            clean=False,
            error="SandboxUnavailable: docker",
            target_green=None,
            labels={"cost_known": "false"},
        ),
        row(
            clean=False,
            error="TimeoutError: belt",
            target_green=None,
            labels={"cost_known": "false"},
        ),
        row(clean=False, disqualified=True, dq_reason="tamper", tests_unmodified=False),
        row(clean=True, gold_clean=False),  # excluded from n (weak oracle)
    ]


def test_failure_split_counts_and_two_rates() -> None:
    s = lg.failure_split(_split_rows())
    assert s.rows == 13 and s.n == 11 and s.disqualified == 1
    assert (s.clean, s.builder_red, s.budget, s.protocol, s.harness) == (6, 1, 1, 1, 2)
    assert s.lint == 0 and s.lint_evaluated == 0  # no row here carried belt 5
    assert s.instrument == 3
    assert s.point == pytest.approx(6 / 11) and s.ci == wilson_interval(6, 11)
    assert s.model_n == 7 and s.model_point == pytest.approx(6 / 7)
    assert s.model_ci == wilson_interval(6, 7)
    # cost: 6 priced + 1 metered + 1 identified-builder $0 = known; 3 instrument rows unknown
    assert s.cost_known == 8 and s.cost_unknown == 3
    d = s.to_dict()
    assert d["n"] == 11 and d["model_n"] == 7 and d["model_point"] == round(6 / 7, 4)
    assert d["model_ci_low"] == round(s.model_ci.low, 4) and d["harness"] == 2
    assert d["lint"] == 0 and d["lint_evaluated"] == 0
    assert lg.failure_split([]).n == 0 and lg.failure_split([]).model_point == 0.0
    with pytest.raises(ValueError, match="sum of its eligible kinds"):
        lg.FailureSplit(
            n=3,
            clean=1,
            builder_red=0,
            budget=0,
            protocol=0,
            harness=0,
            disqualified=0,
            rows=3,
            cost_known=0,
            cost_unknown=0,
        )


def test_failure_split_names_lint_and_counts_belt_five_coverage() -> None:
    """``lint`` is a model kind (the code worked, the repo rejected it): it sits in
    ``model_n``; ``lint_evaluated`` says how many rows carried belt 5 at all."""
    rows = [
        row(repo_lint_clean=True),
        row(repo_lint_clean=True),
        row(clean=False, repo_lint_clean=False),  # lint
        row(clean=False, target_green=False, repo_lint_clean=None),  # builder_red, no linter
        row(repo_lint_clean=None),  # clean, no linter
        row(belt_set=lg.BELT_SET_V4),  # clean, belt 5 unrecorded
        row(clean=False, error="lint: ruff: not runnable (rc=127)", repo_lint_clean=False),
    ]
    s = lg.failure_split(rows)
    assert s.n == 7 and s.clean == 4 and s.lint == 1 and s.builder_red == 1 and s.harness == 1
    assert s.lint_evaluated == 4  # True, True, False(lint), False(harness) — not the Nones
    assert s.model_n == 6 and s.model_point == pytest.approx(4 / 6)
    assert s.to_dict()["lint"] == 1 and s.to_dict()["lint_evaluated"] == 4
    c = lg.cell_stats(rows)
    assert c.n_lint == 1 and c.n_lint_evaluated == 4 and c.model_n == 6
    assert c.to_dict()["n_lint"] == 1 and c.to_dict()["n_lint_evaluated"] == 4
    with pytest.raises(ValueError, match="sum of its eligible kinds"):
        lg.FailureSplit(
            n=2,
            clean=1,
            builder_red=0,
            budget=0,
            protocol=0,
            harness=0,
            disqualified=0,
            rows=2,
            cost_known=0,
            cost_unknown=0,
            lint=0,
        )


def test_cell_stats_carries_the_split_next_to_the_point() -> None:
    s = lg.cell_stats(_split_rows())
    assert s.n == 11 and s.clean == 6 and s.point == pytest.approx(6 / 11)
    assert (s.n_builder_red, s.n_budget, s.n_protocol, s.n_harness, s.n_disqualified) == (
        1,
        1,
        1,
        2,
        1,
    )
    assert s.n_instrument == 3
    assert s.model_n == 7 and s.model_point == pytest.approx(6 / 7)
    assert s.model_ci == wilson_interval(6, 7)
    # the all-rows point stays the routing input: it is strictly lower than the model point here
    assert s.point < s.model_point
    d = s.to_dict()
    assert d["n_builder_red"] == 1 and d["n_budget"] == 1 and d["n_protocol"] == 1
    assert d["n_harness"] == 2 and d["n_disqualified"] == 1
    assert d["model_n"] == 7 and d["model_point"] == round(6 / 7, 4)
    assert d["model_ci_low"] == round(s.model_ci.low, 4)
    assert d["model_ci_high"] == round(s.model_ci.high, 4)
    # a cell of nothing but instrument errors: n counts them (fail closed), model_n = 0
    only_harness = lg.cell_stats([row(clean=False, error="OSError: x", target_green=None)] * 3)
    assert only_harness.n == 3 and only_harness.point == 0.0
    assert only_harness.model_n == 0 and only_harness.model_point == 0.0
    assert only_harness.model_ci == wilson_interval(0, 0)


def test_outage_rows_are_not_observations() -> None:
    """237 rows landed in one evening reading 'model_error: … You've hit your limit' and
    were counted as harness failures — a harness that worked. A provider refusing the
    CALL is `outage`: outside n, reported separately; a pinned `harness` row with
    outage text re-reads as `outage` (the text is hashed into the row)."""
    limit = "model_error: success: You've hit your limit · resets 9:10pm"
    assert lg.derive_failure_kind(clean=False, disqualified=False, error=limit) == lg.FAILURE_OUTAGE
    assert (
        lg.derive_failure_kind(
            clean=False, disqualified=False, error="model_error: HTTP 429 rate_limit"
        )
        == lg.FAILURE_OUTAGE
    )
    assert (
        lg.derive_failure_kind(clean=False, disqualified=False, error="model_error: something else")
        == lg.FAILURE_HARNESS
    )
    assert (
        lg.derive_failure_kind(
            clean=False, disqualified=False, error="pytest: collection timed out after 429s"
        )
        == lg.FAILURE_HARNESS
    )
    assert not lg.is_outage_error("FileNotFoundError: 429")
    outage = row(
        clean=False,
        target_green=False,
        no_new_failures=None,
        source_changed=None,
        error=limit,
        labels={"failure_kind": "harness"},
    )
    assert outage.failure_kind == lg.FAILURE_OUTAGE and outage.eligible is False
    split = lg.failure_split([outage, row()])
    assert split.n == 1 and split.outage == 1 and split.rows == 2


def test_jsonl_append_survives_a_last_row_longer_than_the_tail_window(tmp_path: Path) -> None:
    """_last_hash read only the final 64 KiB; a last row longer than that (labels are
    unbounded) was parsed from its middle and every later append failed (CodeRabbit on
    PR #3, 2026-09-15). The window now grows to a line boundary."""
    ledger = lg.JsonlLedger(tmp_path / "ledger.jsonl")
    big = ledger.append(row(task_id="a" * 40, labels={"note": "x" * 70_000}))
    small = ledger.append(row(task_id="b" * 40))
    assert small.prev_hash == big.row_hash
    assert ledger.verify() == 2
