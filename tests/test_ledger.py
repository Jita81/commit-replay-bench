"""crb.core.ledger — GradeRow invariants, the hash chain, cell statistics."""

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
    return lg.GradeRow(**base)


# ---------------------------------------------------------------------------
# GradeRow invariants (enforced at write time)
# ---------------------------------------------------------------------------


def test_clean_row_with_full_evidence_is_accepted() -> None:
    r = row()
    assert r.clean and r.eligible and r.belts_all_true()
    assert r.row_id and len(r.row_id) == 32
    assert r.created and r.schema == lg.GRADE_SCHEMA and r.apparatus_version == APPARATUS_VERSION
    assert r.belt_set == lg.BELT_SET_V4 and r.provenance == "measured"
    assert r.recorded_belts() == (
        "tests_unmodified",
        "target_green",
        "no_new_failures",
        "source_changed",
    )


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
        row(belt_set="v5")


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
        row(apparatus_version="1.9"),
    ]


def test_cell_stats_numbers() -> None:
    s = lg.cell_stats(_cell_rows())
    # 14 rows: DQ (1) and gold_clean=False (1) are excluded → n=12; clean = 8 + 1 (v1.9) = 9
    assert s.n == 12
    assert s.clean == 9
    assert s.disqualified == 1
    assert s.errors == 1
    assert s.false_q1 == 0
    assert s.point == pytest.approx(9 / 12)
    assert s.ci == wilson_interval(9, 12)
    assert s.cost_usd_mean == pytest.approx((0.02 * 8 + 0.04) / 9)
    assert s.latency_s_mean == pytest.approx((10.0 * 8 + 20.0) / 9)
    assert s.oracle_strength_mean == pytest.approx((0.9 * 8 + 0.7) / 9)
    assert s.apparatus_versions == ("1.9", APPARATUS_VERSION)
    d = s.to_dict()
    assert d["process_step"] == "replay" and d["n"] == 12 and d["point"] == round(9 / 12, 4)
    assert d["ci_low"] == round(s.ci.low, 4) and d["oracle_strength_mean"] == round(
        s.oracle_strength_mean, 4
    )


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
