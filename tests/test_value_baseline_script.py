"""The export reader behind the value baseline — the product's failure rule, not the export's.

Navigation
----------
What it is:   The test suite for ``scripts/value_baseline.py``, the reader that turns an exported
              ledger (pipe-separated, or the product's own JSONL) and an exported review file
              into the scorecard.
What it does: Pins that every row's failure kind is recomputed with the product's rule from the
              error class — a usage limit is an outage, a missing key or a missing runner tool is
              harness, a network or archaeology refusal is protocol — and never read from the
              export's crude column; that a budget stop and a lint-only failure survive; that a
              review whose statement the operator marked as a flag defect is corrected in the
              reader and counted as corrected; that the critical-friend cobra reviews can be
              left out; and that the JSONL export reads through ``GradeRow`` unchanged.
How:          Small export files written to ``tmp_path``; the script loaded as a module.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/value_baseline.py (under test), src/crb/core/value.py (the report it
              feeds), src/crb/core/ledger.py (``derive_failure_kind`` — the rule it applies),
              docs/reviews/2026-09-25-value-baseline.md (the page it regenerates)
Tested by:    tests/test_value_baseline_script.py
Touch when:   the export's columns or error classes change (add the class to ``ERRCLASS`` and a
              case here), or the review export gains a column.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from crb.core.ledger import GradeRow

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "seq|created|repo|class|size|mode|step|clean|dq|failure_kind|trial|run|task|cost|latency|"
    "apparatus|gold_clean|oracle|rung|tests_unmod|target_green|no_new|lint|errclass"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "value_baseline", ROOT / "scripts" / "value_baseline.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["value_baseline"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(
    n: int,
    *,
    mode: str = "blind",
    clean: str = "0",
    kind: str = "",
    err: str = "",
    lint: str = "",
    latency: str = "60",
    cost: str = "1.0",
    dq: str = "0",
) -> str:
    return (
        f"|2026-09-14T00:{n:02d}:00+00:00|cobra|bug.fix|XS|{mode}|replay|{clean}|{dq}|{kind}|r1|run1|"
        f"task{n:08d}|{cost}|{latency}|2.2|1||r1|1|{'1' if clean == '1' or kind == 'lint' else '0'}|1|"
        f"{lint}|{err}"
    )


@pytest.fixture
def vb() -> ModuleType:
    return _load()


def test_the_failure_kind_is_the_products_rule_not_the_exports(
    vb: ModuleType, tmp_path: Path
) -> None:
    lines = [
        HEADER,
        _row(1, err="U", kind="harness"),
        _row(2, err="K", kind="harness"),
        _row(3, err="PN", kind="protocol"),
        _row(4, err="PA"),
        _row(5, err="EJ"),
        _row(6, kind="budget", latency="900"),
        _row(7, kind="budget", latency="120"),
        _row(8, kind="lint", lint="0"),
        _row(9, clean="1", lint="1"),
        _row(10),
        _row(11, dq="1"),
    ]
    p = tmp_path / "ledger.psv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = vb.read_ledger(p)
    got = [(r.failure_kind, r.detail) for r in rows]
    assert got == [
        ("outage", "usage-limit"),
        ("harness", "api-key-missing"),
        ("protocol", "network"),
        ("protocol", "archaeology"),
        ("harness", "runner-tool-missing:jest"),
        ("budget", "wall_clock"),
        ("budget", "other_cap"),
        ("lint", ""),
        ("", ""),
        ("builder_red", ""),
        ("disqualified", ""),
    ]
    assert rows[8].clean and rows[8].repo_lint_clean is True and rows[0].cost_usd == 1.0


def test_an_unknown_error_class_is_refused(vb: ModuleType, tmp_path: Path) -> None:
    p = tmp_path / "ledger.psv"
    p.write_text(HEADER + "\n" + _row(1, err="ZZ") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ZZ"):
        vb.read_ledger(p)


def test_reviews_correct_the_flag_defect_and_can_drop_the_critical_friend_three(
    vb: ModuleType, tmp_path: Path
) -> None:
    p = tmp_path / "reviews.psv"
    p.write_text(
        "repo|task|grade_clean|verdict|mergeable_flag|finding_kinds|statement_head\n"
        "mesh-client|0b0457d694|true|ok|true||XS sighted. Mergeable as-is.\n"
        "nhsuk-frontend|fd45bdd8be|true|ok|false||XS sighted. Mergeable. (FLAG DEFECT: statement says mergeable, stored flag false)\n"
        "nhsuk-frontend|c11684dd28|true|style|false|style|XS sighted. Not mergeable.\n",
        encoding="utf-8",
    )
    verdicts, corrected = vb.read_reviews(p, critical_friend=False)
    assert corrected == 1
    assert [v.mergeable for v in verdicts] == [True, True, False]
    assert verdicts[2].finding_kinds == ("style",) and verdicts[0].grade_row_hash == ""
    with_cf, _ = vb.read_reviews(p, critical_friend=True)
    assert len(with_cf) == 6 and all(v.mergeable is False for v in with_cf[3:])


def test_a_jsonl_export_reads_through_the_grade_row(vb: ModuleType, tmp_path: Path) -> None:
    row = GradeRow(
        repo="alpha",
        task_id="a" * 40,
        clean=False,
        tests_unmodified=True,
        target_green=False,
        no_new_failures=None,
        source_changed=None,
        mode="blind",
        labels={"stop_reason": "max_turns"},
    ).chained("0" * 64)
    p = tmp_path / "ledger.jsonl"
    p.write_text(json.dumps(row.to_dict()) + "\n", encoding="utf-8")
    (v,) = vb.read_ledger(p)
    assert v.failure_kind == "budget" and v.row_hash == row.row_hash and v.detail == "max_turns"


def test_the_markdown_carries_n_method_and_apparatus_on_every_figure(
    vb: ModuleType, tmp_path: Path
) -> None:
    p = tmp_path / "ledger.psv"
    p.write_text(
        "\n".join([HEADER, _row(1, clean="1", lint="1"), _row(2)]) + "\n", encoding="utf-8"
    )
    out = vb.render_markdown(vb.read_ledger(p), [], apparatus="all")
    assert "| measure |" in out and "n = 2" in out and "apparatus" in out
