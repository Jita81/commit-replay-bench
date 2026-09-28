"""What a worker does when it starts, before it takes a run: it writes the heads of both chains
to its log (G-601) and, under the unsealed production override, an audit event naming the
admin who set it (G-663).

Navigation
----------
What it is:   The suite for ``crb.server.worker_main.announce_start`` and the entry point
              that calls it.
What it does: Pins that a starting worker logs the grade ledger's and the audit trail's
              head ``row_hash`` (and their row counts) so the log store holds a copy outside
              the database; that a production worker under ``CRB_ALLOW_UNSEALED_PROD`` writes
              a ``posture.unsealed_override`` event whose actor is the named admin and whose
              payload carries the name, the reason and ``process: worker``; that an
              unknown or non-admin name refuses the start with nothing written; and that
              ``crb worker`` itself (``worker_main.main``) does all of it at every start, and
              turns a store error while the start is recorded into its JSON error and exit 2
              (P-244, P-241).
How:          A ``Worker`` over a temp SQLite store (``init_db``), rows through ``DbLedger``
              and the event sink, accounts through ``create_local_user``; ``caplog`` reads
              the log line, rendered again through the deployed redacting JSON handler.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md,
              docs/adr/0023-production-refuses-the-unsealed-posture.md
Works with:   src/crb/server/worker_main.py (under test), src/crb/server/unsealed_override.py
              (the event), src/crb/store/events.py (``events_head``)
Tested by:    tests/test_worker_start.py
Touch when:   the start-up line or the override event changes shape (docs/DEPLOYMENT.md §8
              and §9.4 name them).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.observability.events import StepEvent
from crb.observability.logging import JsonFormatter, RedactingFilter
from crb.server import unsealed_override, worker_main
from crb.server.auth import create_local_user
from crb.server.worker import Worker, WorkerSettings
from crb.store import DbLedger, make_engine
from crb.store.events import DbEventSink
from crb.store.models import Event, User

try:
    from tests.conftest_store import grade_row
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import grade_row

REASON = "evaluation on a host without docker, not evidence"


def _worker(tmp_path: Path, **kw: Any) -> Worker:
    engine = make_engine(f"sqlite:///{tmp_path / 'crb.db'}")
    settings = WorkerSettings(home=tmp_path / "home", worker_id="w1", **kw)
    return Worker(settings, engine=engine)


def test_a_starting_worker_logs_both_heads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    w = _worker(tmp_path)
    ledger = DbLedger(w.factory)
    rows = [ledger.append(grade_row(trial=str(i))) for i in range(2)]
    DbEventSink(w.factory).emit(StepEvent(trace_id="t", stage="system", action="a", seq=1))
    with w.factory() as s:
        events_head = s.execute(select(Event.row_hash).order_by(Event.id.desc())).scalars().first()
    with caplog.at_level(logging.INFO, logger="crb.server.worker_main"):
        heads = worker_main.announce_start(w)
    assert heads == {
        "grades_rows": 2,
        "grades_head": rows[-1].row_hash,
        "events_rows": 1,
        "events_head": events_head,
    }
    (line,) = [r for r in caplog.records if "ledger heads" in r.getMessage()]
    assert rows[-1].row_hash in line.getMessage() and str(events_head) in line.getMessage()
    # the log store's copy: the line as the deployed handler writes it (the redacting filter,
    # then the JSON form) still carries both heads whole, as fields an operator can query
    assert RedactingFilter().filter(line)
    shipped = json.loads(JsonFormatter().format(line))
    assert shipped["grades_head"] == rows[-1].row_hash
    assert shipped["events_head"] == events_head
    assert rows[-1].row_hash in shipped["msg"] and str(events_head) in shipped["msg"]


def _accounts(w: Worker) -> str:
    with w.factory() as db:
        root = create_local_user(db, username="root", password="p" * 16, role="admin")
        create_local_user(db, username="olive", password="p" * 16, role="operator")
        db.commit()
        return root.id


def test_a_prod_worker_under_the_override_writes_an_event_naming_who_set_it(
    tmp_path: Path,
) -> None:
    w = _worker(
        tmp_path,
        env="prod",
        executor="local",
        builder_executor="host",
        unsealed_override_ack={"by": "root", "reason": REASON},
    )
    root_id = _accounts(w)
    worker_main.announce_start(w)
    with w.factory() as db:
        (ev,) = db.execute(select(Event).where(Event.action == unsealed_override.ACTION)).scalars()
    assert ev.actor == root_id and ev.payload_json["username"] == "root"
    assert ev.payload_json["reason"] == REASON and ev.payload_json["process"] == "worker"
    assert ev.payload_json["worker_id"] == "w1"


@pytest.mark.parametrize(
    ("name", "why"), [("nobody", "names no account"), ("olive", "only an admin")]
)
def test_a_prod_worker_naming_an_unknown_or_non_admin_account_refuses_to_start(
    tmp_path: Path, name: str, why: str
) -> None:
    w = _worker(
        tmp_path,
        env="prod",
        executor="local",
        builder_executor="host",
        unsealed_override_ack={"by": name, "reason": REASON},
    )
    _accounts(w)
    with pytest.raises(unsealed_override.OverrideRefused, match=why):
        worker_main.announce_start(w)
    with w.factory() as db:
        assert (
            db.execute(select(Event).where(Event.action == unsealed_override.ACTION)).first()
            is None
        )
        assert len(list(db.execute(select(User)).scalars())) == 2


# --- the entry point: `crb worker` itself does both at every start --------------------------
# The tests above call announce_start directly; these drive worker_main.main, so a main()
# that stopped calling it (no override event, no refusal, no heads) fails here (P-241).


def _prod_override_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, by: str) -> list[str]:
    for key, value in {
        "CRB_ENV": "prod",
        "CRB_HOME": str(tmp_path / "home"),
        "CRB_SANDBOX__EXECUTOR": "local",
        "CRB_BUILDER__EXECUTOR": "host",
        "CRB_ALLOW_UNSEALED_PROD": "1",
        "CRB_ALLOW_UNSEALED_PROD_BY": by,
        "CRB_ALLOW_UNSEALED_PROD_REASON": REASON,
    }.items():
        monkeypatch.setenv(key, value)
    return [
        "--database-url",
        f"sqlite:///{tmp_path / 'crb.db'}",
        "--home",
        str(tmp_path / "home"),
        "--worker-id",
        "w-main",
        "--metrics-port",
        "0",
        "--once",
        "--log-format",
        "json",
    ]


def _override_events(w: Worker) -> list[Event]:
    with w.factory() as db:
        return list(
            db.execute(select(Event).where(Event.action == unsealed_override.ACTION)).scalars()
        )


def test_crb_worker_under_the_override_writes_the_event_and_logs_both_heads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _prod_override_env(monkeypatch, tmp_path, "root")
    w = _worker(tmp_path)  # the same store main() opens: create the accounts in it first
    root_id = _accounts(w)
    assert worker_main.main(argv) == worker_main.EXIT_IDLE  # started, found no run, left
    (ev,) = _override_events(w)
    assert ev.actor == root_id and ev.payload_json["username"] == "root"
    assert ev.payload_json["process"] == "worker" and ev.payload_json["worker_id"] == "w-main"
    lines = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.startswith("{")]
    (heads,) = [x for x in lines if "ledger heads at worker start" in x.get("msg", "")]
    # the override's own event is on the trail before the heads are read, so its hash is the head
    assert heads["events_rows"] == 1 and heads["events_head"] == ev.row_hash
    assert heads["grades_rows"] == 0


@pytest.mark.parametrize(
    ("name", "why"), [("nobody", "names no account"), ("olive", "only an admin")]
)
def test_crb_worker_naming_an_unknown_or_non_admin_account_exits_2_with_nothing_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    why: str,
) -> None:
    argv = _prod_override_env(monkeypatch, tmp_path, name)
    w = _worker(tmp_path)
    _accounts(w)
    assert worker_main.main(argv) == worker_main.EXIT_ERROR
    err = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.startswith("{")]
    assert any("OverrideRefused" in x.get("error", "") and why in x["error"] for x in err)
    assert _override_events(w) == []
    assert not any("ledger heads" in x.get("msg", "") for x in err)  # it never started


def test_crb_worker_whose_start_cannot_be_recorded_exits_2_with_the_error_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A store error while the start is recorded (a lost connection, a lock timeout) is the
    worker's JSON error and ``EXIT_ERROR``, never a traceback with exit 1 — and it never
    takes a run unrecorded (P-241)."""
    from sqlalchemy.exc import OperationalError

    argv = _prod_override_env(monkeypatch, tmp_path, "root")
    _accounts(_worker(tmp_path))

    def lost(*_a: Any, **_k: Any) -> Any:
        raise OperationalError("INSERT INTO events", {}, Exception("database is locked"))

    monkeypatch.setattr(worker_main, "record_unsealed_override", lost)
    assert worker_main.main(argv) == worker_main.EXIT_ERROR
    err = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.startswith("{")]
    assert any("OperationalError" in x.get("error", "") for x in err)
    assert not any("ledger heads" in x.get("msg", "") for x in err)
