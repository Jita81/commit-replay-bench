"""Two processes that start at once under the unsealed production override both record it.

Parametrised over SQLite and (when ``CRB_TEST_POSTGRES_URL`` is set) PostgreSQL.

Navigation
----------
What it is:   The concurrency suite for ``crb.server.unsealed_override.record_unsealed_override``.
What it does: Pins that the API and a worker (or two workers, or two API processes) starting
              at the same moment each write their ``posture.unsealed_override`` event on the
              one shared trace, with dense ``seq`` values and an intact chain — neither start
              crashes on the unique ``(trace_id, seq)`` (P-118, P-083's class on a trace every
              process start writes).
How:          Two threads call ``record_unsealed_override`` over one store; a barrier placed
              after the event is built (its ``seq`` read) and before the commit makes the two
              interleave where a writer without the events lock would collide. A writer that
              holds the lock keeps the other out, the barrier times out, and both commit.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0023-production-refuses-the-unsealed-posture.md,
              docs/adr/0041-the-audit-trail-is-hash-chained.md
Works with:   src/crb/server/unsealed_override.py (under test), src/crb/store/events.py
              (``lock_events``, ``verify_events``), tests/conftest_store.py (the backends)
Tested by:    tests/test_unsealed_override_race.py
Touch when:   the override's event moves to another writer, or the events write lock changes.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.server import unsealed_override
from crb.server.auth import create_local_user
from crb.store.db import init_db
from crb.store.events import verify_events
from crb.store.models import Event

try:
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401

REASON = "evaluation on a host without docker, not evidence"


def test_two_processes_starting_under_the_override_at_once_both_record(
    backend: Backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_db(backend.engine)
    with backend.factory() as db:
        create_local_user(db, username="root", password="p" * 16, role="admin")
        db.commit()

    barrier = threading.Barrier(2)
    real = unsealed_override.append_system_event

    def staged(db: Session, **kw: Any) -> Any:
        ev = real(db, **kw)  # the trace's seq is read and the event built, not yet flushed
        # the other start reaches the same point if it can; a broken barrier means it could
        # not — it is waiting for this start's lock
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=1.5)
        return ev

    monkeypatch.setattr(unsealed_override, "append_system_event", staged)
    errors: list[BaseException] = []

    def start(process: str) -> None:
        try:
            unsealed_override.record_unsealed_override(
                backend.factory, by="root", reason=REASON, process=process, posture={}
            )
        except BaseException as exc:  # a crashed start is the failure under test
            errors.append(exc)

    threads = [threading.Thread(target=start, args=(p,)) for p in ("api", "worker")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    with backend.factory() as db:
        rows = list(
            db.execute(
                select(Event).where(Event.action == unsealed_override.ACTION).order_by(Event.seq)
            ).scalars()
        )
    assert [r.seq for r in rows] == [1, 2]
    assert sorted(r.payload_json["process"] for r in rows) == ["api", "worker"]
    report = verify_events(backend.factory)
    assert report.ok and report.rows == 2, report.detail
