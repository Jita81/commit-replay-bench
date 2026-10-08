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
Touch when:   never for a new repository; ``crb reading``'s flags change.
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
    # the pool is frozen by rule (DL-097): there is no list to name, only a date
    assert main([*_argv(wd), "--pool", "f" * 40]) == 2
    assert "--pool" in capsys.readouterr().err
    assert main([*_argv(wd), "--since", "last tuesday"]) == 2
    assert "invalid_reading" in capsys.readouterr().err
    assert main([*_argv(wd), "--since", "2026-09-01T00:00:00+00:00"]) == 2
    assert "no gold-checked task" in capsys.readouterr().err
    for _ in range(2):
        assert main(_argv(wd)) == 0
    capsys.readouterr()
    assert main(_argv(wd)) == 2
    assert "budget_spent" in capsys.readouterr().err
    ledger = wd / "ledger.jsonl"
    JsonlLedger(ledger).append(sealed_row(shas[3], created="2026-09-01T00:00:00+00:00"))
    assert main(_argv(wd)) == 2
    assert "pool_seen" in capsys.readouterr().err


def test_two_overlapping_registrations_never_overspend_the_cells_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """P-722 (ADR-0026 item 5): the read of the readings on file, the budget check and the
    append are one step under the file's lock. The budget holds two readings; one is on
    file. A second registration starts a third from inside its own check: without the lock
    both read one reading, both pass and both append — three on file, the budget overspent.
    With it the third waits, then reads two and is refused ``budget_spent``."""
    import threading

    from crb.cli.commands import reading as cli_reading

    wd = tmp_path / ".crb"
    _tasks(wd, commits(40))
    assert main(_argv(wd)) == 0
    real = cli_reading.register_reading
    third: dict[str, int] = {}
    threads: list[threading.Thread] = []

    def overlapping(**kw: object) -> object:
        if not threads:
            t = threading.Thread(target=lambda: third.setdefault("rc", main(_argv(wd))))
            threads.append(t)
            t.start()
            t.join(timeout=3)  # it finishes here only when nothing serialises the two
        return real(**kw)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_reading, "register_reading", overlapping)
    rc = main(_argv(wd))
    threads[0].join(timeout=30)
    capsys.readouterr()
    on_file = (wd / "readings.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted([rc, third["rc"]]) == [0, 2]
    assert len(on_file) == 2


def test_ledger_stats_names_the_arm_and_class_set_of_each_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """P-727: ``crb ledger stats`` splits one cell by apparatus, context arm and class-set
    version, so its table names each — two lines of one cell (``S3`` and ``A0`` here) are
    otherwise identical to a reader."""
    ledger = tmp_path / "ledger.jsonl"
    book = JsonlLedger(ledger)
    shas = commits(4)
    book.append(sealed_row(shas[0], arm="S3"))
    book.append(sealed_row(shas[1], arm="A0"))
    assert main(["ledger", "stats", "--path", str(ledger)]) == 0
    header, *lines = capsys.readouterr().out.splitlines()
    assert "arm" in header.split() and "class_set" in header.split()
    body = [ln for ln in lines if ln.strip() and not set(ln.strip()) <= {"-", " "}][:2]
    assert len(body) == 2 and body[0] != body[1]
    assert {"S3", "A0"} <= {tok for ln in body for tok in ln.split()}
