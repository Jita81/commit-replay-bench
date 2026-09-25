"""scripts/prevention_from_export.py — the register over an exported ledger, on a synthetic export.

Navigation
----------
What it is:   The export script's test, over a synthetic PSV (the operator's export is never
              committed).
What it does: Pins that the script rebuilds rows by the product's failure rule (an outage is
              never a class; protocol, harness and budget resolve at family level), prints each
              repository's register with its lever and level, emits the same as JSON, and names
              each repository's largest blind class from the data — on first attempts and on
              every rung, which can differ.
How:          A PSV written under ``tmp_path`` in the export's columns; the script loaded with
              ``importlib`` and its ``main`` called with captured output.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   scripts/prevention_from_export.py (under test), src/crb/core/prevention.py (the
              register it builds), src/crb/core/ledger.py (the failure rule)
Tested by:    tests/test_prevention_from_export.py
Touch when:   the export's columns or the product's error classes change.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "prevention_from_export", ROOT / "scripts" / "prevention_from_export.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prevention_from_export"] = mod
    spec.loader.exec_module(mod)
    return mod


pfe = _load()


def _row(repo: str, i: int, *, mode: str, kind: str, rung: str = "r1", task: str = "") -> str:
    """One export line: ``kind`` is clean / budget / builder_red / PN / U / K."""
    clean = "1" if kind == "clean" else "0"
    fk = kind if kind in ("budget", "builder_red") else ""
    err = kind if kind in ("PN", "U", "K", "EJ") else ""
    belts = "1|1|1|1" if kind == "clean" else "1|0|1|"
    cells = [
        "",
        f"2026-09-20T{i // 60:02d}:{i % 60:02d}:00+00:00",
        repo,
        "bug.fix",
        "S",
        mode,
        "replay",
        clean,
        "0",
        fk,
        rung,
        "run1",
        task or f"{i:012x}",
        "0.10",
        "30",
        "2.2",
        "1",
        "",
        rung,
        belts,
        err,
    ]
    return "|".join(cells)


def _export(tmp_path: Path) -> Path:
    lines = ["|".join(pfe.COLUMNS)]
    i = 0
    # alpha: blind first attempts mostly target red; budget only on retries
    for k in range(12):
        lines.append(_row("alpha", i, mode="blind", kind="builder_red" if k < 5 else "clean"))
        i += 1
    for k in range(8):
        lines.append(_row("alpha", i, mode="blind", kind="budget", rung="r2", task=f"{k:012x}"))
        i += 1
    for _ in range(3):
        lines.append(_row("alpha", i, mode="blind", kind="U"))
        i += 1
    # beta: sighted network refusals and one blind budget stop
    for k in range(12):
        lines.append(_row("beta", i, mode="sighted", kind="PN" if k < 3 else "clean"))
        i += 1
    lines.append(_row("beta", i, mode="blind", kind="budget"))
    path = tmp_path / "ledger.psv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_script_reads_a_fixture_export_and_prints_the_register(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path)
    assert pfe.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "alpha: 12 first attempts (12 blind, 0 sighted)" in out  # the outages are not attempts
    assert "protocol:network:-: 3 first attempts" in out
    assert "lever line:T-NET (advisory); would file item:refused-call" in out
    assert "outage" not in out
    assert pfe.main([str(path), "--json", "--assume-shipped", "finish_gate"]) == 0
    body = json.loads(capsys.readouterr().out)
    beta = next(r for r in body["repositories"] if r["repo"] == "beta")
    net = next(c for c in beta["classes"] if c["signature"] == "protocol:network:-")
    assert (net["lever"], net["level"], net["actionable"]) == (
        "finish_gate",
        "mistake-proofing",
        True,
    )
    assert net["first_attempts_by_mode"] == {"sighted": 3}


def test_the_script_names_the_largest_blind_class_per_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert pfe.main([str(_export(tmp_path)), "--json"]) == 0
    body = {r["repo"]: r for r in json.loads(capsys.readouterr().out)["repositories"]}
    # read from the data, not remembered: on first attempts alpha's is the red target, but on
    # every rung it is the budget stop — the two readings can differ, so both are served
    assert body["alpha"]["largest_blind_class"] == {
        "signature": "builder_red:target_red",
        "first_attempts": 5,
    }
    assert body["alpha"]["largest_blind_class_all_rungs"] == {
        "signature": "budget:unrecorded",
        "rows": 8,
    }
    assert body["beta"]["largest_blind_class"] == {
        "signature": "budget:unrecorded",
        "first_attempts": 1,
    }
