"""``crb route`` under routing.v2: one reading, the bar in its help, nothing unmeasured delivers.

Navigation
----------
What it is:   CLI tests of ``crb route`` over a JSONL ledger of sealed 2.4 rows.
What it does: Shows that without the controls report, the oracle export and the registered
              readings every cell reads unmeasured and never ``deliver``; that with all three
              the standard arm delivers and the ``S3`` arm is a ceiling; that ``--apparatus
              all`` and an arm outside the grammar are refused; that two posture classes exit
              2; and that ``--help`` quotes ``RoutingPolicy.describe()``.
How:          ``crb.cli.main.main`` with ``--workdir`` in ``tmp_path``; rows from
              ``tests.fixtures.readings``; exports written as JSON files.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/cli/commands/route.py (the command under test),
              src/crb/cli/commands/reading.py (writes the readings file route reads),
              src/crb/core/routing.py (``describe`` — the bar ``--help`` quotes),
              tests/fixtures/readings.py (the sealed rows and the reading)
Tested by:    this file
Touch when:   never for a new repository; ``crb route``'s flags or output change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from crb.cli.main import main
from crb.core.ledger import JsonlLedger
from crb.core.routing import DEFAULT_POLICY
from fixtures.readings import S1, commits, register_reading, rows_for, sealed_row


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        code = main(argv)
    except SystemExit as exc:  # argparse --help
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def _ledger(tmp_path: Path, rows: list[Any]) -> Path:
    path = tmp_path / "ledger.jsonl"
    JsonlLedger(path).append_many(rows)
    return path


def _exports(tmp_path: Path, commits_: list[str]) -> tuple[Path, Path]:
    oracle = tmp_path / "oracle.json"
    oracle.write_text(
        json.dumps(
            {
                "repo": "cobra",
                "tasks": [
                    {
                        "task_id": c,
                        "strength": 0.9,
                        "total": 10,
                        "killed": 9,
                        "apparatus_version": "2.4",
                    }
                    for c in commits_
                ],
            }
        ),
        encoding="utf-8",
    )
    controls = tmp_path / "controls.json"
    controls.write_text(
        json.dumps(
            {
                "passed": True,
                "n_rows": 7,
                "skipped": 0,
                "not_constructible": 1,
                "escapes": 0,
                "apparatus": {"apparatus_version": "2.4", "complete": True},
            }
        ),
        encoding="utf-8",
    )
    return oracle, controls


def test_nothing_unmeasured_delivers_and_the_standard_arm_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reading = register_reading(commits(40))
    first = list(reading.pool[:20])
    path = _ledger(
        tmp_path,
        [*rows_for([True] * 20, reading.pool), *rows_for([True] * 20, reading.pool, arm=S1)],
    )
    wd = ["--workdir", str(tmp_path / ".crb"), "--path", str(path), "--json"]
    code, out, _ = _run(["route", "--arm", S1, *wd], capsys)
    bare = json.loads(out)
    assert (
        code == 0 and bare["decisions"] and all(d["route"] != "deliver" for d in bare["decisions"])
    )
    assert bare["decisions"][0]["reason_code"] == "reading_unregistered"
    readings = tmp_path / "readings.jsonl"
    readings.write_text(json.dumps(reading.to_dict()) + "\n", encoding="utf-8")
    oracle, controls = _exports(tmp_path, first)
    full = [*wd, "--readings", str(readings), "--oracle", str(oracle), "--controls", str(controls)]
    code, out, _ = _run(["route", "--arm", S1, *full], capsys)
    (s1,) = json.loads(out)["decisions"]
    assert s1["route"] == "deliver" and s1["standard"] == S1, s1["reason"]
    code, out, _ = _run(["route", "--arm", "S3", *full], capsys)
    (s3,) = json.loads(out)["decisions"]
    assert s3["route"] == "calibrate" and s3["reason_code"] == "ceiling"


def test_a_pooled_reading_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _ledger(
        tmp_path,
        [
            sealed_row(commits(1)[0]),
            sealed_row(commits(2, "h")[1], posture_class="docker/readonly/sealed"),
        ],
    )
    wd = ["--workdir", str(tmp_path / ".crb"), "--path", str(path)]
    code, _, err = _run(["route", "--apparatus", "all", *wd], capsys)
    assert code == 2 and "one apparatus" in err
    code, _, err = _run(["route", "--arm", "S9", *wd], capsys)
    assert code == 2 and "grammar" in err
    code, _, err = _run(["route", *wd], capsys)
    assert code == 2 and "posture classes" in err


def test_route_help_quotes_the_published_bar(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["route", "--help"], capsys)
    assert code == 0
    assert " ".join(DEFAULT_POLICY.describe().split()) in " ".join(out.split())
