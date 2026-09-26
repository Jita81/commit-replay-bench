"""``crb learn prevention`` — the JSONL twin of ``GET /learn/register`` and ``POST /learn/tick``.

Navigation
----------
What it is:   The CLI prevention verb's test.
What it does: Pins that the verb prints the register of one repository from a JSONL ledger
              and a JSONL chain (text and ``--json``), that ``--tick`` appends what one tick
              writes — nothing while the switch is off — and that the chain it wrote verifies.
How:          The fixture ledger written through ``JsonlLedger``; the switch thrown through
              ``JsonlPreventionStore``; ``crb.cli.main.main`` with captured output.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/cli/commands/learn.py (under test), src/crb/core/prevention.py (the
              register and the tick), tests/prevention_fixtures.py (the ladder's rows)
Tested by:    tests/test_cli_learn_prevention.py
Touch when:   the verb gains an option or the register's text rendering changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.cli.main import main
from crb.core.ledger import JsonlLedger
from crb.core.prevention import AUTO_CONTEXT, JsonlPreventionStore
from prevention_fixtures import NET_SIG, REPO, ladder_before, switched


def test_prevention_verb_prints_the_register_from_jsonl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    JsonlLedger(ledger).append_many(ladder_before())
    store = tmp_path / "prevention.jsonl"
    base = ["learn", "prevention", "--repo", REPO, "--ledger", str(ledger), "--store", str(store)]

    assert main(base) == 0
    text = capsys.readouterr().out
    assert f"{REPO}: switch off" in text and NET_SIG in text
    assert "lever line:T-NET (advisory)" in text and "the switch is off" in text

    assert main([*base, "--tick"]) == 0  # off: nothing is written
    assert "tick: 0 record(s) appended" in capsys.readouterr().out
    assert JsonlPreventionStore(store).records() == []

    JsonlPreventionStore(store).append(switched(AUTO_CONTEXT, i=40))
    assert main([*base, "--tick", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    kinds = [(r["kind"], r["payload"].get("lever_id")) for r in body["appended"]]
    assert ("applied", "line:T-NET") in kinds and ("proposed", "item:refused-call") in kinds
    entry = next(e for e in body["entries"] if e["signature"] == NET_SIG)
    assert entry["status"] == "applied" and entry["change"]["lever_id"] == "line:T-NET"
    assert len(JsonlPreventionStore(store).records()) == 1 + len(body["appended"])
