"""The census-ledger invariant gate (runs in CI on every PR).

Re-derives all 1,071 census verdicts through the current importer and ledger:

* every row passes ``GradeRow.assert_invariants`` — **false-Q1 = 0**;
* the chained ledger verifies end to end;
* the known counts hold (so a silent change in the importer or the data is caught);
* the MANIFEST hashes match the files on disk.

If this test ever fails, do not "fix the test": either the data changed (it must
not — it is evidence) or the invariant logic changed (bump the apparatus version
and record an ADR).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from crb.core.capability import PROJECTION_CLASS_SIZE, build_capability_map
from crb.core.ledger import (
    BELT_SET_V3_LEGACY,
    BELT_SET_V4,
    JsonlLedger,
    false_q1_total,
)
from crb.core.legacy import import_census
from crb.core.routing import ROUTE_DELIVER

DATA = Path(__file__).resolve().parents[1] / "data" / "census-2026-07-08"

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="census data not vendored")


def test_manifest_matches_files() -> None:
    manifest = (DATA / "MANIFEST.sha256").read_text().splitlines()
    assert manifest, "empty manifest"
    for line in manifest:
        digest, _, rel = line.partition("  ")
        p = DATA / rel.strip()
        assert p.is_file(), rel
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, f"{rel} changed"


@pytest.fixture(scope="module")
def census_ledger(tmp_path_factory: pytest.TempPathFactory) -> JsonlLedger:
    led = JsonlLedger(tmp_path_factory.mktemp("census") / "ledger.jsonl")
    imported = list(import_census(DATA / "grades.jsonl", DATA / "tasks", DATA / "configs.json"))
    led.append_many(g.row for g in imported)
    return led


def test_every_row_imports_and_false_q1_is_zero(census_ledger: JsonlLedger) -> None:
    rows = list(census_ledger.rows())
    raw = [
        json.loads(line)
        for line in (DATA / "grades.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(rows) == len(raw) == 1071
    assert false_q1_total(rows) == 0
    assert census_ledger.verify() == 1071


def test_known_counts_hold(census_ledger: JsonlLedger) -> None:
    rows = list(census_ledger.rows())
    assert sum(r.belt_set == BELT_SET_V3_LEGACY for r in rows) == 706
    assert sum(r.belt_set == BELT_SET_V4 for r in rows) == 365
    assert sum(r.clean for r in rows) == 962
    assert sum(r.disqualified for r in rows) == 8
    assert sum(bool(r.error) for r in rows) == 12
    assert sum(r.mode == "blind" for r in rows) == 144
    assert all(r.evidence_pack_hash for r in rows)  # no pack ⇒ no Q1, even for history
    assert all(r.apparatus_version == "1.0-census" for r in rows)
    assert all(r.provenance.startswith("imported:") for r in rows)


def test_no_cell_delivers_below_min_n(census_ledger: JsonlLedger) -> None:
    cmap = build_capability_map(list(census_ledger.rows()), projection=PROJECTION_CLASS_SIZE)
    for cell in cmap.cells:
        if cell.decision is not None and cell.decision.route == ROUTE_DELIVER:
            assert cell.stats is not None and cell.stats.n >= 10
            assert cell.stats.false_q1 == 0
