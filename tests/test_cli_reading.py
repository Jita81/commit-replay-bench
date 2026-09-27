"""``crb reading register | list``: the file workdir's registration, refused as the core refuses it.

Navigation
----------
What it is:   CLI tests of ``crb reading``.
What it does: Registers a reading over the gold-checked tasks of a cell on file, appends it to
              the workdir's ``readings.jsonl`` and lists it; refuses an unsealed posture, a
              pool commit that is not a qualified task of the cell, a pool already graded
              under an arm of the hierarchy (``pool_seen``) and a registration beyond the
              cell's budget (``budget_spent``).
How:          ``crb.cli.main.main`` with ``--workdir`` in ``tmp_path``; tasks written to the
              workdir's task file; rows from ``tests.fixtures.readings``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 2 to 5)
Works with:   src/crb/cli/commands/reading.py (the command under test),
              src/crb/core/reading.py (the rules it applies unchanged),
              tests/fixtures/readings.py (the cell, the sealed rows and the shas)
Tested by:    this file
Touch when:   ``crb reading``'s flags change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.cli.commands import Workdir
from crb.cli.main import main
from crb.core.ledger import JsonlLedger
from crb.core.spec import TaskSpec
from fixtures.readings import AUTHOR, CELL, REPO, S1, SEALED, commits, sealed_row


def _tasks(wd: Path, shas: list[str]) -> None:
    f = Workdir(wd).task_file(REPO)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("w", encoding="utf-8") as fh:
        for i, sha in enumerate(shas):
            spec = TaskSpec(
                task_id=sha,
                repo=REPO,
                subject=f"fix {i}",
                authored="2026-08-01T00:00:00+00:00",
                test_files=("x_test.go",),
                src_files=("x.go",),
                target_tests=("./...",),
                belt_scope=("./...",),
                capability_class=CELL["capability_class"],
                size=CELL["size"],
                language=CELL["language"],
                gold_clean=True,
                labels={"change_id": f"change-{sha}"},
            )
            fh.write(json.dumps(spec.to_dict()) + "\n")


def _argv(wd: Path, *extra: str) -> list[str]:
    return [
        "reading",
        "register",
        "--repo",
        REPO,
        "--class",
        CELL["capability_class"],
        "--size",
        CELL["size"],
        "--language",
        CELL["language"],
        "--builder",
        CELL["builder"],
        "--model",
        CELL["model"],
        "--provider",
        CELL["provider"],
        "--hierarchy",
        f"S3,{S1}",
        "--author-model",
        AUTHOR,
        "--posture-class",
        SEALED,
        "--workdir",
        str(wd),
        *extra,
    ]


def test_register_appends_a_reading_the_route_reads_and_list_shows_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wd = tmp_path / ".crb"
    shas = commits(40)
    _tasks(wd, shas)
    assert main([*_argv(wd), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["hierarchy"] == ["S3", S1] and len(body["pool"]) == 40
    assert (wd / "readings.jsonl").is_file()
    assert main(["reading", "list", "--workdir", str(wd), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)["readings"]
    assert [r["reading_id"] for r in listed] == [body["reading_id"]]


def test_register_refuses_what_the_rules_forbid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wd = tmp_path / ".crb"
    shas = commits(40)
    _tasks(wd, shas)
    assert (
        main([*_argv(wd)[:-4], "--posture-class", "local/inplace/host-env", "--workdir", str(wd)])
        == 2
    )
    assert "sealed posture" in capsys.readouterr().err
    assert main([*_argv(wd), "--pool", "f" * 40]) == 2
    assert "not gold-checked tasks" in capsys.readouterr().err
    ledger = wd / "ledger.jsonl"
    JsonlLedger(ledger).append(sealed_row(shas[3], created="2026-09-01T00:00:00+00:00"))
    assert main(_argv(wd)) == 2
    assert "pool_seen" in capsys.readouterr().err
    fresh = [s for s in shas if s != shas[3]]
    for i in range(2):
        assert main([*_argv(wd), "--pool", ",".join(fresh[i * 12 : i * 12 + 12])]) == 0
    capsys.readouterr()
    assert main([*_argv(wd), "--pool", ",".join(fresh[24:36])]) == 2
    assert "budget_spent" in capsys.readouterr().err
