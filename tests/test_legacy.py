"""crb.core.legacy — census + benchmark-ledger importers.

Two layers:

* an inline synthetic census (always runs) with one row per shape the real census
  contains — legacy v3, v4, blind, disqualified, error — plus a duplicate line;
* the REAL census under ``~/.expansion-bench`` (skipped when absent), asserting
  the headline facts the product boots with: 1,071 rows, 0 rejections,
  false-Q1 = 0, 706 v3-legacy / 365 v4.

Navigation
----------
What it is:   The importers' test suite — the census and the benchmark ledger.
What it does: Pins, on an inline synthetic census with one row per shape (legacy v3, v4, blind,
              disqualified, error, a duplicate line), that every shape imports and passes the
              invariants, that a v3 row never invents belt 4, that the pack hash is the canonical
              hash of the imported envelope, determinism, chaining, that an unknown task is
              skipped with an event and a false-Q1 census row cannot be imported; that an
              ``AggregateRow`` is not a ``GradeRow``; and, on the real census when present, the
              headline facts (1,071 rows, 0 rejections, false-Q1 = 0, 706 v3 / 365 v4).
How:          ``write_census`` writes the three census files under ``tmp_path``; the real-census
              cases skip unless ``~/.expansion-bench`` exists.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/legacy.py (under test), src/crb/core/ledger.py (the rows and the
              belt sets), tests/test_census_gate.py (the same importer over the shipped census
              in CI), docs/EVIDENCE-AND-CLAIMS.md (the legacy-belt caveat, §5),
              docs/REPRODUCING-THE-CENSUS.md
Tested by:    tests/test_legacy.py
Touch when:   the census format gains a field (a synthetic row per shape here — the real data
              must not change); never to make an import more lenient.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from crb.core.evidence import canonical_json, sha256_text
from crb.core.ledger import (
    BELT_SET_V3_LEGACY,
    BELT_SET_V4,
    GradeRow,
    JsonlLedger,
    all_cell_stats,
    false_q1_total,
    verify_chain,
)
from crb.core.legacy import (
    AGGREGATE_SCHEMA,
    BENCHMARK_LEDGER_PROVENANCE,
    CENSUS_APPARATUS_VERSION,
    CENSUS_BUILDER,
    CENSUS_DEFAULT_MODEL,
    CENSUS_IMPORT_CREATED,
    CENSUS_PROVENANCE,
    CENSUS_PROVIDER,
    IMPORTED_EVIDENCE_SCHEMA,
    AggregateRow,
    LegacyImportError,
    canonical_size,
    import_benchmark_ledger,
    import_census,
    import_census_grades,
    import_census_tasks,
    import_repo_configs,
    imported_pack_hash,
)
from crb.core.spec import BELT_TARGET_ONLY, Language

# ---------------------------------------------------------------------------
# Synthetic census fixture (5 shapes + 1 duplicate line)
# ---------------------------------------------------------------------------

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40  # graded but not in the task file → skipped

CONFIGS = {
    "demo": {
        "lang": "py",
        "url": "https://example.invalid/demo",
        "src_prefix": "demo/",
        "test_prefix": "tests/",
        "ext": ".py",
        "belt_scope": ["tests/"],
        "probe": "tests/test_ok.py",
        "target_valid": 5,
    },
    "gopkg": {"lang": "go", "belt_scope": ["./..."]},
}

TASKS_DEMO = {
    SHA_A: {
        "task": SHA_A,
        "target_tests": ["tests/test_a.py"],
        "test_files": ["tests/test_a.py"],
        "src_files": ["demo/api/routes.py"],
        "pool": "standard",
        "authored": "2026-06-01T00:00:00+00:00",
        "subject": "route add",
        "src_churn": 12,
        "size": "S",
        "baseline_failing": [],
        "gold_clean": True,
    },
    SHA_B: {
        "task": SHA_B,
        "target_tests": ["tests/test_b.py"],
        "test_files": ["tests/test_b.py"],
        "src_files": ["demo/core.py"],
        "authored": "2026-06-02T00:00:00+00:00",
        "subject": "fix",
        "src_churn": 3,
        "size": "",
        "gold_clean": False,
        "oracle_invalid": True,
    },
}
TASKS_GO = {
    SHA_C: {
        "task": SHA_C,
        "target_tests": ["./"],
        "test_files": ["mux_test.go"],
        "src_files": ["mux.go"],
        "pool": "hard",
        "authored": "2026-06-03T00:00:00+00:00",
        "subject": "fix mux",
        "src_churn": 55,
        "size": "M",
        "baseline_failing": ["./::TestFlaky"],
        "gold_clean": True,
    },
}

ROW_V3 = {  # legacy: no source_changed key, no model/pool
    "repo": "demo",
    "task": SHA_A,
    "wt": "/tmp/wt/run-demo-aaaaaaaaaa-r1",
    "clean": True,
    "tests_unmodified": True,
    "target_green": True,
    "no_new_failures": True,
    "new_failures": [],
    "trial": "r1",
    "wave": "w1",
    "size": "S",
}
ROW_V4 = {
    "repo": "demo",
    "task": SHA_A,
    "wt": "/tmp/wt/run-demo-aaaaaaaaaa-r2",
    "clean": True,
    "tests_unmodified": True,
    "target_green": True,
    "no_new_failures": True,
    "new_failures": [],
    "source_changed": True,
    "trial": "r2",
    "wave": "w2",
    "size": "",
    "model": "sonnet",
    "pool": "standard",
    "regraded_calm": True,
}
ROW_BLIND = {
    "repo": "gopkg",
    "task": SHA_C,
    "wt": "/tmp/wt/run-gopkg-cccccccccc-b1",
    "clean": False,
    "tests_unmodified": True,
    "target_green": True,
    "no_new_failures": False,
    "new_failures": ["./::TestX", "./::TestY"],
    "source_changed": True,
    "blind_mode": True,
    "wave": "b1",
    "trial": "b1",
    "pool": "hard",
    "size": "M",
    "model": "sonnet",
    "operation": "fix.conditional_logic",
}
ROW_DQ = {
    "repo": "demo",
    "task": SHA_B,
    "wt": "/tmp/wt/run-demo-bbbbbbbbbb-r1",
    "clean": False,
    "tests_unmodified": True,
    "target_green": True,
    "no_new_failures": True,
    "new_failures": [],
    "source_changed": True,
    "trial": "r1",
    "wave": "w3",
    "size": "XS",
    "model": "sonnet",
    "pool": "standard",
    "disqualified": True,
    "dq_reason": "malformed oracle: target not red on parent in isolated build",
}
ROW_ERR = {
    "repo": "demo",
    "task": SHA_B,
    "wt": "/tmp/wt/run-demo-bbbbbbbbbb-r2",
    "clean": False,
    "tests_unmodified": False,
    "target_green": False,
    "no_new_failures": False,
    "error": "missing worktree",
    "trial": "r2",
    "wave": "w3",
    "size": "XS",
    "model": "sonnet",
    "pool": "standard",
}
ROWS = (ROW_V3, ROW_V4, ROW_BLIND, ROW_DQ, ROW_ERR)


def write_census(root: Path, rows: tuple[dict[str, object], ...] = ROWS) -> tuple[Path, Path, Path]:
    """Write ``configs.json``, ``<repo>_tasks.json`` and ``grades.jsonl`` under ``root``."""
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    configs = root / "configs.json"
    configs.write_text(json.dumps(CONFIGS), encoding="utf-8")
    (state / "demo_tasks.json").write_text(json.dumps(TASKS_DEMO), encoding="utf-8")
    (state / "gopkg_tasks.json").write_text(json.dumps(TASKS_GO), encoding="utf-8")
    (state / "banked_tasks.json").write_text(json.dumps({"demo": [SHA_A]}), encoding="utf-8")
    grades = state / "grades.jsonl"
    grades.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return grades, state, configs


@pytest.fixture
def census(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The synthetic census files (``configs.json``, ``<repo>_tasks.json``, ``grades.jsonl``)."""
    return write_census(tmp_path)


# ---------------------------------------------------------------------------
# configs + tasks
# ---------------------------------------------------------------------------


def test_import_repo_configs_loads_census_shape(census: tuple[Path, Path, Path]) -> None:
    _, _, configs = census
    cfgs = import_repo_configs(configs)
    assert set(cfgs) == {"demo", "gopkg"}
    assert cfgs["demo"].language is Language.PYTHON
    assert cfgs["demo"].runner == "pytest"
    assert cfgs["demo"].belt_scope == ("tests/",)
    assert cfgs["demo"].probe == "tests/test_ok.py"
    assert cfgs["demo"].mining["target_valid"] == 5
    assert cfgs["gopkg"].language is Language.GO
    assert cfgs["gopkg"].runner == "go"


def test_import_repo_configs_rejects_non_object(tmp_path: Path) -> None:
    p = tmp_path / "configs.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(LegacyImportError):
        import_repo_configs(p)


def test_import_census_tasks_maps_records(census: tuple[Path, Path, Path]) -> None:
    _, state, configs = census
    tasks = {t.task_id: t for t in import_census_tasks(state, configs)}
    assert set(tasks) == {SHA_A, SHA_B, SHA_C}  # banked_tasks.json is not a task file
    a, b, c = tasks[SHA_A], tasks[SHA_B], tasks[SHA_C]
    assert a.repo == "demo" and a.language == "python"
    assert a.capability_class == "backend.route.add"  # from src_files, not guessed
    assert a.size == "S" and a.gold_clean is True and a.red_checked is True
    assert a.belt_scope == ("tests/",)  # resolved through the repo's runner policy
    assert a.labels["provenance"] == CENSUS_PROVENANCE
    assert b.pool == "standard"  # missing pool → standard
    assert b.size == "XS"  # blank size → derived from churn 3
    assert b.gold_clean is False
    assert b.red_checked is False  # no baseline_failing recorded → not claimed
    assert b.labels["oracle_invalid"] == "true"
    assert c.pool == "hard" and c.language == "go"
    assert c.belt_scope == ("./...",)
    assert c.baseline_failing == ("./::TestFlaky",)


def test_import_census_tasks_requires_config(tmp_path: Path) -> None:
    _, state, configs = write_census(tmp_path)
    (state / "orphan_tasks.json").write_text(json.dumps(TASKS_DEMO), encoding="utf-8")
    with pytest.raises(LegacyImportError, match="orphan"):
        list(import_census_tasks(state, configs))


# ---------------------------------------------------------------------------
# grades — the five shapes
# ---------------------------------------------------------------------------


def _rows(census: tuple[Path, Path, Path]) -> dict[str, GradeRow]:
    grades, state, configs = census
    rows = list(import_census_grades(grades, state, configs))
    assert len(rows) == 5
    return {f"{r.task_id[0]}:{r.trial}": r for r in rows}


def test_every_shape_imports_and_passes_invariants(census: tuple[Path, Path, Path]) -> None:
    rows = list(_rows(census).values())
    assert false_q1_total(rows) == 0
    for r in rows:
        r.assert_invariants()
        assert r.provenance == CENSUS_PROVENANCE
        assert r.apparatus_version == CENSUS_APPARATUS_VERSION
        assert r.created == CENSUS_IMPORT_CREATED
        assert r.builder == CENSUS_BUILDER and r.provider == CENSUS_PROVIDER
        assert r.actor == "import" and r.process_step == "replay"
        assert r.evidence_pack_hash and len(r.evidence_pack_hash) == 64
        assert r.row_id and r.prev_hash == "" and r.row_hash == ""


def test_v3_legacy_row_never_invents_belt_four(census: tuple[Path, Path, Path]) -> None:
    r = _rows(census)["a:r1"]
    assert r.belt_set == BELT_SET_V3_LEGACY
    assert r.source_changed is None
    assert r.clean is True and r.belts_all_true()  # invariant over the three recorded belts
    assert r.model == CENSUS_DEFAULT_MODEL  # absent model → sonnet (documented default)
    assert r.pool == "standard"
    assert r.mode == "sighted"
    assert r.run_id == "w1" and r.trial == "r1"
    assert r.size == "S" and r.language == "python"
    assert r.capability_class == "backend.route.add"
    assert r.gold_clean is True


def test_v4_row_records_belt_four_and_falls_back_to_task_size(
    census: tuple[Path, Path, Path],
) -> None:
    r = _rows(census)["a:r2"]
    assert r.belt_set == BELT_SET_V4
    assert r.source_changed is True
    assert r.size == "S"  # row size "" → task size
    assert r.labels == {"regraded_calm": "true"}


def test_blind_row_maps_mode_operation_and_failures(census: tuple[Path, Path, Path]) -> None:
    r = _rows(census)["c:b1"]
    assert r.mode == "blind"
    assert r.clean is False and r.no_new_failures is False
    assert r.new_failures_count == 2
    assert r.labels["operation"] == "fix.conditional_logic"
    assert r.pool == "hard" and r.language == "go" and r.size == "M"


def test_dq_row_is_disqualified_not_clean(census: tuple[Path, Path, Path]) -> None:
    r = _rows(census)["b:r1"]
    assert r.disqualified is True and r.clean is False
    assert r.dq_reason.startswith("malformed oracle")
    assert r.eligible is False
    assert r.gold_clean is False


def test_error_row_fails_closed(census: tuple[Path, Path, Path]) -> None:
    r = _rows(census)["b:r2"]
    assert r.error == "missing worktree" and r.clean is False
    assert r.tests_unmodified is False and r.target_green is False
    assert r.new_failures_count == 0  # new_failures absent → 0, not invented


def test_pack_hash_is_canonical_hash_of_imported_envelope(
    census: tuple[Path, Path, Path],
) -> None:
    grades, state, configs = census
    igs = list(import_census(grades, state, configs))
    first = igs[0]
    assert first.pack["schema"] == IMPORTED_EVIDENCE_SCHEMA
    assert first.pack["row"] == ROW_V3
    assert first.pack["source"]["file"] == "grades.jsonl" and first.pack["source"]["line"] == 1
    assert first.pack_hash == sha256_text(canonical_json(first.pack))
    assert first.pack_hash == imported_pack_hash(first.pack)
    assert len({ig.pack_hash for ig in igs}) == 5
    assert [ig.line for ig in igs] == [1, 2, 3, 4, 5]


def test_import_is_deterministic(census: tuple[Path, Path, Path]) -> None:
    grades, state, configs = census
    a = [r.to_dict() for r in import_census_grades(grades, state, configs)]
    b = [r.to_dict() for r in import_census_grades(grades, state, configs)]
    assert a == b  # fixed timestamp + content-derived row ids


def test_rows_chain_into_a_ledger_and_verify(
    census: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    grades, state, configs = census
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    chained = ledger.append_many(import_census_grades(grades, state, configs))
    assert len(chained) == 5
    assert ledger.verify() == 5
    assert verify_chain(ledger.rows()) == 5
    stats = all_cell_stats(ledger.rows())
    assert sum(s.n for s in stats) == 3  # DQ + error(gold_clean False) rows are not eligible
    assert all(s.false_q1 == 0 for s in stats)
    assert {s.apparatus_versions for s in stats} == {(CENSUS_APPARATUS_VERSION,)}


def test_unknown_task_is_skipped_with_event_never_guessed(tmp_path: Path) -> None:
    orphan = {**ROW_V4, "task": SHA_D, "trial": "r9"}
    grades, state, configs = write_census(tmp_path, (*ROWS, orphan))
    events: list[tuple[str, dict[str, object]]] = []
    rows = list(
        import_census_grades(
            grades, state, configs, on_event=lambda a, p: events.append((a, dict(p)))
        )
    )
    assert len(rows) == 5
    skips = [p for a, p in events if a == "legacy.skip"]
    assert skips == [{"line": 6, "repo": "demo", "task": SHA_D, "reason": "no census task record"}]
    assert sum(1 for a, _ in events if a == "legacy.grade") == 5


def test_duplicate_line_is_imported_and_labelled(tmp_path: Path) -> None:
    grades, state, configs = write_census(tmp_path, (*ROWS, ROW_V3))
    rows = list(import_census_grades(grades, state, configs))
    assert len(rows) == 6
    assert rows[0].labels == {} and rows[5].labels == {"duplicate_of_line": "1"}
    assert rows[0].evidence_pack_hash != rows[5].evidence_pack_hash  # line is in the source
    assert rows[0].row_id != rows[5].row_id


def test_non_boolean_belt_is_rejected(tmp_path: Path) -> None:
    bad = {**ROW_V4, "target_green": "yes"}
    grades, state, configs = write_census(tmp_path, (bad,))
    with pytest.raises(LegacyImportError, match="target_green"):
        list(import_census_grades(grades, state, configs))


def test_missing_required_key_is_rejected(tmp_path: Path) -> None:
    bad = {k: v for k, v in ROW_V4.items() if k != "clean"}
    grades, state, configs = write_census(tmp_path, (bad,))
    with pytest.raises(LegacyImportError, match="clean"):
        list(import_census_grades(grades, state, configs))


def test_a_false_q1_census_row_cannot_be_imported(tmp_path: Path) -> None:
    """The write-time invariant holds for imports too: clean with a failed belt is refused."""
    from crb.core.grade import FalseQ1Violation

    liar = {**ROW_V4, "no_new_failures": False, "trial": "liar"}
    grades, state, configs = write_census(tmp_path, (liar,))
    with pytest.raises(FalseQ1Violation):
        list(import_census_grades(grades, state, configs))


# ---------------------------------------------------------------------------
# Athena benchmark ledger → AggregateRow (reference only)
# ---------------------------------------------------------------------------

BENCH_ROWS = [
    {
        "created": "2026-06-04T21:59:39+00:00",
        "ground": "comments",
        "capability_class": "frontend.component.add",
        "model": "gpt-oss-120b",
        "harness": "cerebras",
        "n_samples": 2,
        "quality_mean": 0.364865,
        "quality_stddev": 0.337838,
        "quality_samples": [0.702703, 0.027027],
        "false_q1_total": 0,
        "provenance": "slice1-live-comments-2x2-396b8bac",
        "token_cost_usd_mean": 0.836023,
        "catalog_classification": "M/Low/Feature",
    },
    {
        "created": "2026-06-12T00:50:00+00:00",
        "ground": "backend.route.add",
        "capability_class": "backend.route.add",
        "model": "gpt-oss-120b+zai-glm-4.7",
        "harness": "cerebras-native-chain",
        "provider": "cerebras",
        "process_step": "generate",
        "n_samples": 4,
        "quality_mean": 0.5,
        "quality_stddev": 0.5,
        "false_q1_total": 1,
        "provenance": "tuned arm",
        "catalog_classification": "xl/L/change",
        "earned_q1": 2,
        "q1_band_count": 1,
        "latency_s_mean": 12.5,
        "human_verified": True,
        "human_corrections": 0,
    },
]


def test_aggregate_row_maps_benchmark_row() -> None:
    a = AggregateRow.from_benchmark_row(BENCH_ROWS[0])
    assert a.schema == AGGREGATE_SCHEMA and a.provenance == BENCHMARK_LEDGER_PROVENANCE
    assert a.source_provenance == "slice1-live-comments-2x2-396b8bac"
    assert a.size == "M" and a.complexity == ""  # "Low" is not a canonical tier
    assert a.n_samples == 2 and a.quality_mean == pytest.approx(0.364865)
    assert a.trusted is True and a.provider == "" and a.process_step == ""
    assert a.raw_hash == sha256_text(canonical_json(BENCH_ROWS[0]))
    b = AggregateRow.from_benchmark_row(BENCH_ROWS[1])
    assert b.size == "XL" and b.complexity == "L"
    assert b.trusted is False and b.false_q1_total == 1
    assert b.provider == "cerebras" and b.process_step == "generate"
    assert b.earned_q1 == 2 and b.q1_band_count == 1 and b.latency_s_mean == 12.5
    assert b.human_verified is True and b.human_corrections == 0
    d = b.to_dict()
    assert d["trusted"] is False and d["catalog_classification"] == "xl/L/change"


def test_aggregate_row_is_not_a_grade_row() -> None:
    """The documented boundary: no belts, no pack hash, no ``clean`` — nothing a
    GradeRow could be built from without inventing per-trial verdicts."""
    a = AggregateRow.from_benchmark_row(BENCH_ROWS[0])
    for attr in ("clean", "tests_unmodified", "target_green", "evidence_pack_hash", "belt_set"):
        assert not hasattr(a, attr)
    assert not isinstance(a, GradeRow)


def test_aggregate_row_validates() -> None:
    with pytest.raises(LegacyImportError):
        AggregateRow.from_benchmark_row({**BENCH_ROWS[0], "quality_mean": 1.5})
    with pytest.raises(LegacyImportError):
        AggregateRow.from_benchmark_row({**BENCH_ROWS[0], "n_samples": -1})
    with pytest.raises(LegacyImportError, match="ground"):
        AggregateRow.from_benchmark_row({"created": "x", "model": "m"})


def test_import_benchmark_ledger_reads_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "benchmark_ledger.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in BENCH_ROWS) + "\n", encoding="utf-8")
    events: list[str] = []
    rows = list(import_benchmark_ledger(p, on_event=lambda a, _p: events.append(a)))
    assert [r.model for r in rows] == ["gpt-oss-120b", "gpt-oss-120b+zai-glm-4.7"]
    assert events == ["legacy.aggregate", "legacy.aggregate"]


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("XS", "XS"),
        ("small", "S"),
        (" m ", "M"),
        ("Large", "L"),
        ("xxl", "XL"),
        ("Low", ""),
        (3, ""),
    ],
)
def test_canonical_size(raw: object, want: str) -> None:
    assert canonical_size(raw) == want


# ---------------------------------------------------------------------------
# The REAL census (skipped when the wipe-proof directory is absent)
# ---------------------------------------------------------------------------

CENSUS_HOME = Path("~/.expansion-bench").expanduser()
REAL_GRADES = CENSUS_HOME / "state" / "grades.jsonl"
REAL_STATE = CENSUS_HOME / "state"
REAL_CONFIGS = CENSUS_HOME / "configs.json"

needs_census = pytest.mark.skipif(
    not (REAL_GRADES.is_file() and REAL_CONFIGS.is_file()),
    reason="real expansion-bench census not present under ~/.expansion-bench",
)


@needs_census
def test_real_census_imports_completely_with_zero_false_q1() -> None:
    events: Counter[str] = Counter()
    rows = list(
        import_census_grades(
            REAL_GRADES, REAL_STATE, REAL_CONFIGS, on_event=lambda a, _p: events.update([a])
        )
    )
    raw_lines = sum(1 for ln in REAL_GRADES.read_text(encoding="utf-8").splitlines() if ln.strip())
    assert len(rows) == raw_lines == 1071
    assert events["legacy.skip"] == 0
    assert false_q1_total(rows) == 0
    assert Counter(r.belt_set for r in rows) == {BELT_SET_V3_LEGACY: 706, BELT_SET_V4: 365}
    assert Counter(r.mode for r in rows)["blind"] == 144
    assert sum(1 for r in rows if r.error) == 12
    assert sum(1 for r in rows if r.disqualified) == 8
    assert len({r.evidence_pack_hash for r in rows}) == 1071
    assert {r.model for r in rows} == {CENSUS_DEFAULT_MODEL}
    assert {r.apparatus_version for r in rows} == {CENSUS_APPARATUS_VERSION}
    assert all(r.size in {"XS", "S", "M", "L", "XL"} for r in rows)  # no blank sizes survive
    assert all(r.capability_class and r.language for r in rows)
    assert sum(1 for r in rows if "duplicate_of_line" in r.labels) == 3


@needs_census
def test_real_census_tasks_and_configs_load() -> None:
    cfgs = import_repo_configs(REAL_CONFIGS)
    assert len(cfgs) == 24
    tasks = list(import_census_tasks(REAL_STATE, REAL_CONFIGS))
    assert len(tasks) == 2097
    assert {t.repo for t in tasks} <= set(cfgs)
    assert all(t.language == cfgs[t.repo].language.value for t in tasks)
    assert all(BELT_TARGET_ONLY not in t.belt_scope for t in tasks)  # policies resolved
    assert Counter(t.gold_clean for t in tasks) == {True: 1212, False: 885}


@needs_census
def test_real_census_chains_into_a_verifiable_ledger(tmp_path: Path) -> None:
    ledger = JsonlLedger(tmp_path / "census.jsonl")
    ledger.append_many(import_census_grades(REAL_GRADES, REAL_STATE, REAL_CONFIGS))
    assert ledger.verify() == 1071
    stats = all_cell_stats(ledger.rows())
    assert len(stats) == 33
    assert all(s.false_q1 == 0 for s in stats)
    # 8 DQ rows; the 7 gold_clean=False oracles are among them (malformed-oracle DQs)
    assert sum(s.n for s in stats) == 1071 - 8
