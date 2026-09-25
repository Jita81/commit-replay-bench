"""scripts/spend_from_export.py — the export's spend numbers, by the product's own rules.

Navigation
----------
What it is:   The suite for the export analysis stream K's numbers were computed with.
What it does: Pins that each export line is re-classified by the product's failure rule
              (``errclass`` → outage / harness / protocol; the export's budget and lint flags),
              that outage and harness rows leave the denominator, that budget-stop spend and
              the escalation rungs' yield and cost per clean are summed over valid rows only,
              and that the calibrated caps and escalation decision per cell come from the
              product's functions.
How:          A synthetic export written under ``tmp_path``; the script loaded by path.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   scripts/spend_from_export.py (under test), src/crb/core/spend.py,
              src/crb/core/ledger.py (``derive_failure_kind``)
Tested by:    tests/test_spend_from_export.py
Touch when:   the export's columns change.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
HEADER = (
    "seq|created|repo|class|size|mode|step|clean|dq|failure_kind|trial|run|task|cost|latency|"
    "apparatus|gold_clean|oracle|rung|tests_unmod|target_green|no_new|lint|errclass"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "spend_from_export", ROOT / "scripts" / "spend_from_export.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spend_from_export"] = mod
    spec.loader.exec_module(mod)
    return mod


def _line(
    *,
    mode: str = "blind",
    size: str = "M",
    clean: str = "0",
    kind: str = "",
    trial: str = "r1",
    cost: str = "1.0",
    latency: str = "100",
    err: str = "",
) -> str:
    return (
        f"|t|cobra|bug.fix|{size}|{mode}|replay|{clean}|0|{kind}|{trial}|run|task|{cost}|"
        f"{latency}|2.2|1||{trial}|1|0|||{err}"
    )


def test_the_failure_rule_and_the_denominator(tmp_path: Path) -> None:
    mod = _load()
    lines = [
        _line(err="U"),  # outage — not an observation
        _line(err="EJ"),  # harness — not an observation
        _line(err="PN"),  # protocol — valid, non-clean
        _line(kind="budget", latency="900", cost="2.5"),  # budget stop at the wall clock
        _line(kind="lint"),
        _line(clean="1", cost="0.5"),
        _line(trial="r2", cost="3.0"),
        _line(trial="r3", clean="1", cost="1.0"),
    ]
    path = tmp_path / "ledger.psv"
    path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    s = mod.summarise(mod.read_export(path))
    assert (s["rows"], s["valid"], s["clean"]) == (8, 6, 2)
    assert s["non_clean_by_kind"] == {"budget": 1, "builder_red": 1, "lint": 1, "protocol": 1}
    assert s["cost_usd_budget_stops"] == 2.5
    assert s["escalation"] == {"n": 2, "clean": 1, "cost_usd": 4.0, "cost_per_clean_usd": 4.0}
    (cell,) = [c for c in s["cells"] if (c["mode"], c["size"]) == ("blind", "M")]
    assert cell["budget_stops"] == {
        "n": 1,
        "latency_s_p50": 900.0,
        "at_wall_clock": 1,
        "cost_usd": 2.5,
    }
    assert cell["calibrated"]["applied"] is False  # 2 clean < 8
    assert cell["escalation"]["escalation_rule"].startswith("measured:insufficient:n=2<10")
    assert "| blind | M |" in mod.to_markdown(s)


def test_a_cell_with_enough_history_is_calibrated_and_its_escalation_stopped(
    tmp_path: Path,
) -> None:
    mod = _load()
    lines = [_line(clean="1", latency="800") for _ in range(8)]
    lines += [_line(trial="r2", cost="2.0") for _ in range(10)]
    path = tmp_path / "ledger.psv"
    path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    s = mod.summarise(mod.read_export(path))
    (cell,) = [c for c in s["cells"] if (c["mode"], c["size"]) == ("blind", "M")]
    assert cell["calibrated"]["caps"]["wall_clock_s"] == 1200  # p90 800 × 1.5
    assert cell["escalation"]["escalation"] == "stopped"
    # the other blind sizes have no escalations of their own: the mode level decides them
    assert s["escalation_withheld_in_sample"] == {
        "cells": ["blind|L", "blind|M", "blind|S", "blind|XS"],
        "n": 10,
        "clean_forgone": 0,
        "cost_usd_saved": 20.0,
    }
