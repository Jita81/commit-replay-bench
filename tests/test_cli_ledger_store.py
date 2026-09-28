"""``crb ledger verify --store`` — the database's grade ledger and audit trail, verified from
the command line (F51, G-601).

Navigation
----------
What it is:   The test suite for ``crb ledger verify --store``.
What it does: Pins that the verb walks the database's grade ledger and its ``events`` chain,
              prints both heads (the values an operator records outside the store), exits 0
              when both are intact, and exits 1 naming the event id when an audit event was
              edited, deleted or reordered underneath its triggers.
How:          ``crb migrate`` on a temp SQLite URL; rows through ``DbLedger`` and the event
              sink; ``main(argv)`` in-process with ``CRB_DATABASE_URL`` set; tampering by raw
              SQL after the ``events`` triggers are dropped.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/cli/commands/ledger.py (under test), src/crb/store/events.py
              (``verify_events`` / ``events_head``), src/crb/store/ledger.py (``DbLedger``)
Tested by:    tests/test_cli_ledger_store.py
Touch when:   the verb's flags or its JSON shape change (docs/OPERATOR.md names them).
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import text

from crb.cli.main import main
from crb.observability.events import StepEvent
from crb.store import DbLedger, make_engine, make_session_factory
from crb.store.events import DbEventSink

try:
    from tests.conftest_store import grade_row
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import grade_row


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'crb.db'}"
    assert main(["migrate", "--database-url", url]) == 0
    factory = make_session_factory(make_engine(url))
    ledger = DbLedger(factory)
    for i in range(3):
        ledger.append(grade_row(trial=str(i)))
    sink = DbEventSink(factory)
    for i in range(1, 6):
        sink.emit(StepEvent(trace_id="t", stage="system", action="user.login", seq=i))
    monkeypatch.setenv("CRB_DATABASE_URL", url)
    return url


def _run(argv: Sequence[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_an_intact_store_verifies_and_prints_both_heads(
    db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(["ledger", "verify", "--store", "--json"], capsys)
    d = json.loads(out)
    assert code == 0 and d["ok"] is True and d["chain_ok"] is True and d["rows"] == 3
    assert d["false_q1"] == 0 and len(d["head_row_hash"]) == 64
    assert d["events"]["chain_ok"] is True and d["events"]["rows"] == 5
    assert len(d["events"]["head_row_hash"]) == 64
    code, out = _run(["ledger", "verify", "--store"], capsys)
    assert code == 0 and "events chain OK" in out
    assert d["head_row_hash"] in out and d["events"]["head_row_hash"] in out


@pytest.mark.parametrize(
    ("tamper", "broken_at"),
    [
        ("UPDATE events SET actor = 'mallory' WHERE id = 2", 2),
        ("DELETE FROM events WHERE id = 2", 3),
        (
            "UPDATE events SET id = 100 WHERE id = 2; UPDATE events SET id = 2 WHERE id = 3; "
            "UPDATE events SET id = 3 WHERE id = 100",
            2,
        ),
    ],
    ids=["edited", "deleted", "reordered"],
)
def test_a_tampered_audit_event_fails_the_verb(
    db_url: str, capsys: pytest.CaptureFixture[str], tamper: str, broken_at: int
) -> None:
    engine = make_engine(db_url)
    with engine.begin() as c:
        c.execute(text("DROP TRIGGER events_no_update"))
        c.execute(text("DROP TRIGGER events_no_delete"))
        for stmt in tamper.split("; "):
            c.execute(text(stmt))
    code, out = _run(["ledger", "verify", "--store", "--json"], capsys)
    d = json.loads(out)
    assert code == 1 and d["ok"] is False and d["chain_ok"] is True
    assert d["events"]["chain_ok"] is False and d["events"]["broken_at"] == broken_at
    code, out = _run(["ledger", "verify", "--store"], capsys)
    assert code == 1 and "events chain BROKEN" in out
