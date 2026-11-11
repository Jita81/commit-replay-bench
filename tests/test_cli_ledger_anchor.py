"""``crb ledger anchor`` and ``crb ledger verify --anchor`` — anchors that leave the machine.

Navigation
----------
What it is:   The CLI tests for writing and checking ledger anchors.
What it does: Pins the round trip on a JSONL ledger and on a SQLite store (both chains);
              that a rewritten or truncated ledger fails ``verify --anchor`` loudly, naming
              the first anchor that no longer holds; that ``--out`` inside the ledger's data
              directory is refused; that an anchor is never overwritten; that two anchors
              chain and a directory is checked as a whole; that a new anchor is refused when
              the ledger no longer extends the directory's last one; and that the command
              writes nothing to the ledger and no URL to the file; that the store reader
              returns the same hashes as a per-row read in one ordered pass per chain,
              however many anchors, and still checks anchors when a chain is broken; and
              that a malformed predecessor link is an anchor-chain fault; and that a ledger
              line that is not a readable row is a broken chain, never a parse error; that an
              anchor attesting no row is refused, an empty ledger is not anchored and a store
              with events but no grade is.
How:          ``main(argv)`` in-process on ``tmp_path``: a JSONL ledger built with
              ``JsonlLedger``; a SQLite store built with ``crb migrate`` and ``DbLedger``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/cli/commands/ledger.py (under test), src/crb/core/anchor.py (the format
              and checks), tests/test_cli_ledger_store.py (the store fixture idiom),
              docs/LEDGER-ANCHORS.md (the custody the refusals enforce)
Tested by:    tests/test_cli_ledger_anchor.py
Touch when:   never for a new repository; the verbs' flags or their JSON shape change.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from crb.cli.main import main
from crb.core.ledger import JsonlLedger
from crb.observability.events import StepEvent
from crb.store import DbLedger, make_engine, make_session_factory
from crb.store.events import DbEventSink

try:
    from tests.conftest_store import grade_row
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import grade_row

T1 = "2026-11-11T12:00:00Z"
T2 = "2026-11-12T12:00:00Z"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def _run(argv: Sequence[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(argv))
    return code, capsys.readouterr().out


def _jsonl(path: Path, n: int, start: int = 0) -> Path:
    ledger = JsonlLedger(path)
    for i in range(start, start + n):
        ledger.append(grade_row(trial=str(i)))
    return path


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    return _jsonl(tmp_path / "data" / "ledger.jsonl", 3)


def _anchor(ledger: Path, out: Path, capsys, at: str = T1) -> tuple[int, dict]:  # type: ignore[no-untyped-def]
    code, text = _run(
        [
            "ledger",
            "anchor",
            "--path",
            str(ledger),
            "--out",
            str(out),
            "--created-at",
            at,
            "--json",
        ],
        capsys,
    )
    return code, json.loads(text)


def _verify(ledger: Path, anchor: Path, capsys) -> tuple[int, dict]:  # type: ignore[no-untyped-def]
    code, text = _run(
        ["ledger", "verify", "--path", str(ledger), "--anchor", str(anchor), "--json"], capsys
    )
    return code, json.loads(text)


def test_round_trip_on_a_jsonl_ledger(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = ledger.read_bytes()
    code, d = _anchor(ledger, tmp_path / "anchors", capsys)
    assert code == 0 and d["written"] is True and d["chains"]["grades"]["rows"] == 3
    path = Path(d["anchor"])
    a = json.loads(path.read_text())
    assert a["created_at"] == T1 and a["source"] == "jsonl" and a["previous_anchor"] is None
    assert a["chains"]["grades"]["head_row_hash"] == list(JsonlLedger(ledger).rows())[-1].row_hash
    assert ledger.read_bytes() == before  # read-only
    _jsonl(ledger, 2, start=3)  # the ledger grows: the anchor still holds
    code, v = _verify(ledger, path, capsys)
    assert code == 0 and v["ok"] is True and v["anchors"]["ok"] is True
    code, text = _run(["ledger", "verify", "--path", str(ledger), "--anchor", str(path)], capsys)
    assert code == 0 and "every one still holds" in text


def test_a_rewritten_ledger_fails_loudly_naming_the_first_anchor(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "anchors"
    _, first = _anchor(ledger, out, capsys)
    _jsonl(ledger, 1, start=3)
    _anchor(ledger, out, capsys, at=T2)
    # rebuild the whole ledger from a new genesis: its own chain verifies, but it is not
    # the history that was anchored
    ledger.unlink()
    _jsonl(ledger, 5, start=100)
    assert JsonlLedger(ledger).verify() == 5
    code, v = _verify(ledger, out, capsys)
    assert code == 1 and v["ok"] is False and v["chain_ok"] is True
    assert v["anchors"]["first_broken"] == Path(first["anchor"]).name
    assert [r["holds"] for r in v["anchors"]["results"]] == [False, False]
    code, text = _run(["ledger", "verify", "--path", str(ledger), "--anchor", str(out)], capsys)
    assert code == 1 and "ANCHOR BROKEN" in text and Path(first["anchor"]).name in text
    assert "rewritten" in text


def test_a_truncated_ledger_fails(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, d = _anchor(ledger, tmp_path / "anchors", capsys)
    lines = ledger.read_text().splitlines(keepends=True)
    ledger.write_text("".join(lines[:2]))  # cut from the end: the chain still verifies
    code, v = _verify(ledger, Path(d["anchor"]), capsys)
    assert code == 1 and v["chain_ok"] is True and "fewer than 3 rows" in str(v["anchors"])


def test_out_inside_the_data_directory_is_refused(
    ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outs = (ledger.parent, ledger.parent / "anchors", ledger.parent / "x" / ".." / "y")
    for out in outs:
        code = main(["ledger", "anchor", "--path", str(ledger), "--out", str(out)])
        err = capsys.readouterr().err
        assert code == 2 and "inside the ledger's data directory" in err
    assert not list(ledger.parent.rglob("anchor-*.json"))
    assert not (ledger.parent / "anchors").exists() and not (ledger.parent / "y").exists()


def test_out_beside_a_symlinked_ledger_is_refused(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The folder that holds a link to the ledger is its data directory too, as is the
    folder of the link's target."""
    wd = tmp_path / "wd"
    wd.mkdir()
    link = wd / "ledger.jsonl"
    link.symlink_to(ledger)
    for out in (wd / "anchors", ledger.parent / "anchors"):
        code = main(["ledger", "anchor", "--path", str(link), "--out", str(out)])
        assert code == 2 and "inside the ledger's data directory" in capsys.readouterr().err
        assert not out.exists()


def test_deleting_the_newest_anchor_is_not_seen_from_the_directory(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The limit docs/LEDGER-ANCHORS.md states: the newest anchor has no successor to name
    it, so only the directory's own custody protects it."""
    out = tmp_path / "anchors"
    _anchor(ledger, out, capsys)
    kept = ledger.read_text()
    _jsonl(ledger, 2, start=3)
    _, second = _anchor(ledger, out, capsys, at=T2)
    Path(second["anchor"]).unlink()
    ledger.write_text(kept)
    code, v = _verify(ledger, out, capsys)
    assert code == 0 and v["ok"] is True


def test_same_filesystem_is_a_warning_not_a_refusal(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["ledger", "anchor", "--path", str(ledger), "--out", str(tmp_path / "a")])
    captured = capsys.readouterr()
    assert code == 0 and "anchor written" in captured.out
    assert "warning:" in captured.err and "same filesystem" in captured.err


def test_an_anchor_is_never_overwritten(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "anchors"
    _, d = _anchor(ledger, out, capsys)
    path = Path(d["anchor"])
    before = path.read_bytes()
    code, again = _anchor(ledger, out, capsys, at=T2)  # same state, later time
    assert code == 0 and again["written"] is False and again["anchor"] == str(path)
    assert path.read_bytes() == before
    forged = json.loads(before)
    forged["chains"]["grades"]["head_row_hash"] = "0" * 64
    path.write_text(json.dumps(forged))  # a different state under the same name
    code = main(["ledger", "anchor", "--path", str(ledger), "--out", str(out), "--created-at", T2])
    # refused before any write: the ledger does not extend the forged anchor (the write's
    # own no-overwrite refusal is pinned in tests/test_anchor.py)
    assert code == 1 and "no longer extends" in capsys.readouterr().out
    assert json.loads(path.read_text()) == forged


def test_two_anchors_chain_and_a_directory_is_checked_whole(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "anchors"
    _, first = _anchor(ledger, out, capsys)
    _jsonl(ledger, 2, start=3)
    _, second = _anchor(ledger, out, capsys, at=T2)
    p1, p2 = Path(first["anchor"]), Path(second["anchor"])
    link = json.loads(p2.read_text())["previous_anchor"]
    assert link["file"] == p1.name and len(link["sha256"]) == 64
    code, v = _verify(ledger, out, capsys)
    assert code == 0 and v["anchors"]["checked"] == 2 and v["anchors"]["anchor_chain_faults"] == []
    p1.unlink()  # an anchor removed from the directory is a finding
    code, v = _verify(ledger, out, capsys)
    assert code == 1 and p1.name in v["anchors"]["anchor_chain_faults"][0]


def test_a_damaged_predecessor_link_is_reported_as_an_anchor_chain_fault(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A first anchor whose ``previous_anchor`` is not an object is a damaged anchor-chain
    link: ``verify --anchor`` names it (exit 1, not a CLI error) and ``anchor`` refuses to
    extend the directory."""
    out = tmp_path / "anchors"
    _, d = _anchor(ledger, out, capsys)
    path = Path(d["anchor"])
    damaged = json.loads(path.read_text())
    damaged["previous_anchor"] = "damaged"
    path.write_text(json.dumps(damaged))
    code, v = _verify(ledger, out, capsys)
    [fault] = v["anchors"]["anchor_chain_faults"]
    assert code == 1 and v["anchors"]["ok"] is False and path.name in fault
    code, text = _run(["ledger", "verify", "--path", str(ledger), "--anchor", str(out)], capsys)
    assert code == 1 and "ANCHOR CHAIN BROKEN" in text and path.name in text
    _jsonl(ledger, 1, start=3)
    code, a = _anchor(ledger, out, capsys, at=T2)
    assert code == 1 and a["written"] is False and "anchor chain" in a["faults"][0]


def test_a_new_anchor_is_refused_when_the_ledger_no_longer_extends_the_last(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "anchors"
    _anchor(ledger, out, capsys)
    ledger.unlink()
    _jsonl(ledger, 4, start=50)
    code, d = _anchor(ledger, out, capsys, at=T2)
    assert code == 1 and d["written"] is False and "no longer extends" in d["faults"][0]
    assert len(list(out.glob("anchor-*.json"))) == 1


def test_a_broken_chain_writes_no_anchor(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [json.loads(ln) for ln in ledger.read_text().splitlines()]
    rows[1]["model"] = "edited"
    ledger.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    code, d = _anchor(ledger, tmp_path / "anchors", capsys)
    assert code == 1 and "CHAIN BROKEN" in d["faults"][0]
    assert not (tmp_path / "anchors").exists()


UNREADABLE_LINES = (b"{not json", b"[1, 2]", b"\xff\xfe not utf-8", b"{}")


@pytest.mark.parametrize("bad", UNREADABLE_LINES)
def test_an_unreadable_row_is_a_chain_fault_not_an_error(
    bad: bytes, ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A line that is not a readable row is ``grades: CHAIN BROKEN`` (exit 1, the structured
    result) for ``anchor``, and a broken chain for ``verify --anchor`` — never a parse error."""
    _, d = _anchor(ledger, tmp_path / "anchors", capsys)
    lines = ledger.read_bytes().splitlines(keepends=True)
    ledger.write_bytes(lines[0] + bad + b"\n" + b"".join(lines[1:]))
    code, a = _anchor(ledger, tmp_path / "again", capsys)
    assert code == 1 and a["ok"] is False and a["written"] is False
    assert a["faults"][0].startswith("grades: CHAIN BROKEN") and "row 2" in a["faults"][0]
    assert not (tmp_path / "again").exists()
    code, v = _verify(ledger, Path(d["anchor"]), capsys)
    assert code == 1 and v["ok"] is False and v["chain_ok"] is False and "row 2" in v["error"]
    # the anchored row 3 is now line 4's row and line 3 holds the old row 2: the anchor fails
    assert v["anchors"]["ok"] is False
    ledger.write_bytes(b"".join(lines[:2]) + bad + b"\n")  # the anchored row itself unreadable
    code, v = _verify(ledger, Path(d["anchor"]), capsys)
    assert code == 1 and v["chain_ok"] is False and v["anchors"]["first_broken"]


def test_an_anchor_that_attests_no_jsonl_row_is_refused_not_passed(
    ledger: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``jsonl`` anchor holding only an empty ``events`` chain used to be skipped chain by
    chain and pass ``verify --anchor`` whatever the grade ledger held."""
    _, d = _anchor(ledger, tmp_path / "anchors", capsys)
    forged = json.loads(Path(d["anchor"]).read_text())
    forged["chains"] = {"events": {"rows": 0, "head_row_hash": ""}}
    path = tmp_path / "forged" / "anchor-forged.json"
    path.parent.mkdir()
    path.write_text(json.dumps(forged))
    code = main(["ledger", "verify", "--path", str(ledger), "--anchor", str(path), "--json"])
    assert code == 2 and "records the chains ['grades']" in capsys.readouterr().err
    forged["chains"] = {"grades": {"rows": 0, "head_row_hash": ""}}
    path.write_text(json.dumps(forged))
    code = main(["ledger", "verify", "--path", str(ledger), "--anchor", str(path)])
    assert code == 2 and "attests nothing" in capsys.readouterr().err


def test_an_empty_ledger_is_not_anchored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty JSONL ledger, absent or blank, writes no anchor (exit 2): an anchor of no
    row would attest nothing, and the reader refuses one."""
    path = tmp_path / "data" / "ledger.jsonl"
    path.parent.mkdir()
    for content in (None, "\n"):
        if content is not None:
            path.write_text(content)
        code = main(["ledger", "anchor", "--path", str(path), "--out", str(tmp_path / "a")])
        assert code == 2 and "nothing to anchor" in capsys.readouterr().err
        assert not (tmp_path / "a").exists()


def test_verify_without_anchor_is_unchanged(
    ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = _run(["ledger", "verify", "--path", str(ledger), "--json"], capsys)
    assert code == 0 and "anchors" not in json.loads(text)


# --- the store: both chains ---------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> tuple[str, Path]:
    db_path = tmp_path / "home" / "crb.db"
    url = f"sqlite:///{db_path}"
    assert main(["migrate", "--database-url", url]) == 0
    factory = make_session_factory(make_engine(url))
    for i in range(3):
        DbLedger(factory).append(grade_row(trial=str(i)))
    sink = DbEventSink(factory)
    for i in range(1, 6):
        sink.emit(StepEvent(trace_id="t", stage="system", action="user.login", seq=i))
    return url, db_path


def test_round_trip_on_the_store_anchors_both_chains(
    db: tuple[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url, db_path = db
    out = tmp_path / "anchors"
    code, text = _run(["ledger", "verify", "--store", "--database-url", url, "--json"], capsys)
    v0 = json.loads(text)
    code, text = _run(
        [
            "ledger",
            "anchor",
            "--store",
            "--database-url",
            url,
            "--out",
            str(out),
            "--created-at",
            T1,
            "--json",
        ],
        capsys,
    )
    d = json.loads(text)
    assert code == 0 and d["source"] == "sqlite" and d["written"] is True
    assert d["chains"]["grades"] == {"rows": 3, "head_row_hash": v0["head_row_hash"]}
    assert d["chains"]["events"] == {"rows": 5, "head_row_hash": v0["events"]["head_row_hash"]}
    body = Path(d["anchor"]).read_text()
    assert str(db_path) not in body and "sqlite:" not in body  # never the URL
    code, text = _run(["ledger", "verify", "--store", "--database-url", url, "--json"], capsys)
    v1 = json.loads(text)
    assert {k: v1[k] for k in ("rows", "head_row_hash")} == {
        k: v0[k] for k in ("rows", "head_row_hash")
    }
    assert v1["events"]["head_row_hash"] == v0["events"]["head_row_hash"]  # nothing written
    code, text = _run(
        ["ledger", "verify", "--store", "--database-url", url, "--anchor", str(out), "--json"],
        capsys,
    )
    assert code == 0 and json.loads(text)["anchors"]["ok"] is True
    code = main(
        [
            "ledger",
            "anchor",
            "--store",
            "--database-url",
            url,
            "--out",
            str(db_path.parent / "anchors"),
        ]
    )
    assert code == 2 and "inside the ledger's data directory" in capsys.readouterr().err


def test_a_store_with_events_and_no_grade_is_anchored_and_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A store with an audit trail but no grade yet writes an anchor of its events, with
    ``grades`` at 0 rows, and the reader accepts it."""
    url = f"sqlite:///{tmp_path / 'home' / 'crb.db'}"
    assert main(["migrate", "--database-url", url]) == 0
    sink = DbEventSink(make_session_factory(make_engine(url)))
    sink.emit(StepEvent(trace_id="t", stage="system", action="user.login", seq=1))
    out = tmp_path / "anchors"
    code, text = _run(
        ["ledger", "anchor", "--store", "--database-url", url, "--out", str(out), "--json"],
        capsys,
    )
    d = json.loads(text)
    assert code == 0 and d["written"] is True and d["chains"]["grades"]["rows"] == 0
    assert d["chains"]["events"]["rows"] >= 1
    code, text = _run(
        ["ledger", "verify", "--store", "--database-url", url, "--anchor", str(out), "--json"],
        capsys,
    )
    assert code == 0 and json.loads(text)["anchors"]["ok"] is True


def test_a_store_whose_events_were_cut_fails_its_anchor(
    db: tuple[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy import text as sql

    url, _ = db
    out = tmp_path / "anchors"
    assert main(["ledger", "anchor", "--store", "--database-url", url, "--out", str(out)]) == 0
    engine = make_engine(url)
    with engine.begin() as c:  # the operator who can write the database cuts the tail
        c.execute(sql("DROP TRIGGER IF EXISTS events_no_delete"))
        c.execute(sql("DELETE FROM events WHERE id = (SELECT MAX(id) FROM events)"))
    engine.dispose()
    code, text = _run(
        ["ledger", "verify", "--store", "--database-url", url, "--anchor", str(out), "--json"],
        capsys,
    )
    d = json.loads(text)
    assert code == 1 and d["events"]["chain_ok"] is True  # the chain alone cannot see it
    assert d["anchors"]["ok"] is False and "events" in d["anchors"]["results"][0]["faults"][0]


def test_a_missing_sqlite_file_is_refused_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "none" / "crb.db"
    code = main(
        [
            "ledger",
            "anchor",
            "--store",
            "--database-url",
            f"sqlite:///{db_path}",
            "--out",
            str(tmp_path / "a"),
        ]
    )
    assert code == 2 and "no SQLite database" in capsys.readouterr().err
    assert not db_path.parent.exists()


# --- the store reader: one ordered pass per chain, however many anchors ------------------


def _store_hashes(url: str) -> tuple[list[str], list[str]]:
    from sqlalchemy import text as sql

    engine = make_engine(url)
    with engine.connect() as c:
        grades = [r[0] for r in c.execute(sql("SELECT row_hash FROM grades ORDER BY seq"))]
        events = [r[0] for r in c.execute(sql("SELECT row_hash FROM events ORDER BY id"))]
    engine.dispose()
    return grades, events


def _anchor_dir(out: Path, heads: Sequence[tuple[int, str, int, str]]) -> None:
    """Chained anchors of a SQLite store, one per ``(grades rows, head, events rows, head)``."""
    from crb.core.anchor import ChainHead, build_anchor, load_anchor, write_anchor

    previous = None
    for g, gh, e, eh in heads:
        a = build_anchor(
            source="sqlite",
            chains={"grades": ChainHead(g, gh), "events": ChainHead(e, eh)},
            apparatus="2.5",
            crb_version="x",
            created_at=T1,
            previous=previous,
        )
        path, _ = write_anchor(out, a)
        previous = (path.name, load_anchor(path).sha256)


def test_the_store_reader_matches_a_per_row_read_at_every_position(
    db: tuple[str, Path], tmp_path: Path
) -> None:
    """Prefetched or read on first use, the reader returns the hash at each position, and
    ``None`` at 0, past the end and on an empty chain."""
    from crb.cli.commands.ledger import _store_hash_at

    url, _ = db
    grades, events = _store_hashes(url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    expected = {
        (chain, n): (hashes[n - 1] if 0 < n <= len(hashes) else None)
        for chain, hashes in (("grades", grades), ("events", events))
        for n in range(0, len(hashes) + 3)
    }
    lazy = _store_hash_at(factory)
    assert {k: lazy(*k) for k in expected} == expected
    eager = _store_hash_at(factory)
    eager.prefetch({"grades": range(0, 6), "events": range(0, 8), "other": [1]})
    assert {k: eager(*k) for k in expected} == expected
    assert eager("other", 1) is None
    engine.dispose()
    empty_url = f"sqlite:///{tmp_path / 'empty' / 'crb.db'}"
    assert main(["migrate", "--database-url", empty_url]) == 0
    engine = make_engine(empty_url)
    reader = _store_hash_at(make_session_factory(engine))
    reader.prefetch({"grades": [1, 2], "events": [1]})
    assert [reader("grades", 1), reader("grades", 2), reader("events", 1)] == [None] * 3
    engine.dispose()


def test_checking_more_anchors_does_not_issue_more_queries(
    db: tuple[str, Path], tmp_path: Path
) -> None:
    from sqlalchemy import event

    from crb.cli.commands.ledger import _anchor_report, _store_hash_at

    url, _ = db
    g, e = _store_hashes(url)
    few, many = tmp_path / "few", tmp_path / "many"
    _anchor_dir(few, [(3, g[2], 5, e[4])])
    _anchor_dir(
        many,
        [(1, g[0], 1, e[0]), (2, g[1], 3, e[2]), (3, g[2], 4, e[3]), (3, g[2], 5, e[4])],
    )
    engine = make_engine(url)
    factory = make_session_factory(engine)
    selects: list[str] = []

    def count(conn, cursor, statement, *rest) -> None:  # type: ignore[no-untyped-def]
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    reports = {}
    queries = {}
    for name, d in (("few", few), ("many", many)):
        selects.clear()
        reader = _store_hash_at(factory)
        reports[name] = _anchor_report(str(d), "sqlite", reader, reader.prefetch)
        queries[name] = len(selects)
    engine.dispose()
    assert reports["few"]["ok"] and reports["many"]["ok"] and reports["many"]["checked"] == 4
    assert queries["few"] == queries["many"] == 2  # one ordered pass per chain


def test_store_anchors_are_still_checked_when_a_chain_is_broken(
    db: tuple[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Several anchors, one past the end of the grades chain, against a store whose events
    chain was edited: the chain fault and every anchor's result are both reported."""
    from sqlalchemy import text as sql

    url, _ = db
    g, e = _store_hashes(url)
    out = tmp_path / "anchors"
    _anchor_dir(out, [(1, g[0], 2, e[1]), (3, g[2], 5, e[4]), (9, "f" * 64, 5, e[4])])
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(sql("DROP TRIGGER IF EXISTS events_no_update"))
        c.execute(
            sql("UPDATE events SET action = 'edited' WHERE id = (SELECT MIN(id) FROM events)")
        )
    engine.dispose()
    code, text = _run(
        ["ledger", "verify", "--store", "--database-url", url, "--anchor", str(out), "--json"],
        capsys,
    )
    d = json.loads(text)
    assert code == 1 and d["events"]["chain_ok"] is False
    rep = d["anchors"]
    assert rep["checked"] == 3 and [r["holds"] for r in rep["results"]] == [True, True, False]
    assert "fewer than 9 rows" in rep["results"][2]["faults"][0]
    assert rep["first_broken"] == rep["results"][2]["file"]
