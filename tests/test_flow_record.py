"""The flow recorder — the moments the flow reading needs, written once when they happen.

Navigation
----------
What it is:   The unit suite of ``crb.server.flow_record`` (ADR-0029) over a real SQLite store.
What it does: Pins that the recorder's first look at a repository stamps no cell and records
              the cells already at deliver as inherited (their moment is unknown, so never
              timed); that a later cell reaching deliver is stamped once per scope, at the run
              that tipped it, and never again when it leaves and returns; that a new scope (an
              apparatus bump) starts afresh; that the install is ``observed`` only on a
              database that held nothing and ``unknown`` otherwise, written once; and that the
              first green ``/health`` is stamped once while a degraded one writes nothing —
              both through the real server start and the real ``/health`` route.
How:          ``make_factory`` for the schema; the recorder writes into a session the test
              commits, as its callers do; the readers fold the events back.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-moments-flow-needs-are-recorded.md
Works with:   src/crb/server/flow_record.py (under test), src/crb/server/flow.py (the reader
              of these moments), tests/test_server_routes_flow.py (the same moments seen
              through ``GET /flow``), tests/fixtures/server_seed.py (``make_factory``)
Tested by:    tests/test_flow_record.py
Touch when:   a recorded moment is added or its once-only rule changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.server.app import API_PREFIX, create_app
from crb.server.flow_record import (
    DELIVER_ROUTED,
    FIRST_HEALTHY,
    INSTALLED,
    RECORDER_STARTED,
    database_is_fresh,
    deliver_moments,
    inherited_cells,
    install_moments,
    record_deliver_transitions,
    record_first_healthy,
    record_install,
)
from crb.server.routes import system as system_routes
from crb.store.models import Event
from fixtures.server_seed import make_factory, make_settings

SCOPE = {"apparatus": "2.3", "posture_class": "local/inplace/host-env", "checks_arm": "off"}
A = ("bug.fix", "S")
B = ("feature.add", "XS")


def _record(factory: sessionmaker[Session], cells: list[tuple[str, str]], **kw: object) -> list:
    with factory() as s:
        out = record_deliver_transitions(
            s,
            repo="alpha",
            deliver_cells=cells,
            scope=kw.get("scope", SCOPE),
            run_id=str(kw.get("run_id", "")),
        )
        s.commit()
    return out


def _actions(factory: sessionmaker[Session]) -> list[str]:
    with factory() as s:
        return [e.action for e in s.execute(select(Event).order_by(Event.id)).scalars()]


def test_the_first_look_stamps_nothing_and_marks_what_was_already_at_deliver(
    tmp_path: Path,
) -> None:
    f = make_factory(tmp_path)
    assert _record(f, [A], run_id="r1") == []
    assert _actions(f) == [RECORDER_STARTED]
    with f() as s:
        assert deliver_moments(s, "alpha") == {}
        assert inherited_cells(s, "alpha") == 1


def test_a_cell_reaching_deliver_later_is_stamped_once_at_the_run_that_tipped_it(
    tmp_path: Path,
) -> None:
    f = make_factory(tmp_path)
    _record(f, [A], run_id="r1")
    assert _record(f, [A, B], run_id="r2") == [B]
    # B leaves deliver, then returns: its first moment does not move; A stays inherited
    assert _record(f, [A], run_id="r3") == []
    assert _record(f, [A, B], run_id="r4") == []
    with f() as s:
        moments = deliver_moments(s, "alpha")
        (ev,) = s.execute(select(Event).where(Event.action == DELIVER_ROUTED)).scalars()
    assert list(moments) == [B] and len(moments[B]) == 1
    assert ev.payload_json["run_id"] == "r2" and ev.payload_json["moment"] == "observed"
    assert ev.actor == "system:flow-recorder"


def test_a_new_scope_starts_afresh(tmp_path: Path) -> None:
    f = make_factory(tmp_path)
    _record(f, [], run_id="r1")
    assert _record(f, [A], run_id="r2") == [A]
    bumped = {**SCOPE, "apparatus": "2.4"}
    # the first look in the new scope inherits what is at deliver there: nothing is timed
    assert _record(f, [A], scope=bumped, run_id="r3") == []
    assert _record(f, [A, B], scope=bumped, run_id="r4") == [B]
    with f() as s:
        assert sorted(deliver_moments(s, "alpha")) == [A, B]


def test_the_install_is_observed_only_on_a_database_that_held_nothing(tmp_path: Path) -> None:
    f = make_factory(tmp_path)
    with f() as s:
        assert database_is_fresh(s)
        assert record_install(s, fresh=database_is_fresh(s))
        s.commit()
    with f() as s:
        # written once: the next start writes nothing
        assert not record_install(s, fresh=database_is_fresh(s))
        s.commit()
        at, moment, healthy = install_moments(s)
    assert at and moment == "observed" and healthy == ""
    assert _actions(f) == [INSTALLED]


def test_an_existing_deployment_is_never_dated_from_its_upgrade(tmp_path: Path) -> None:
    f = make_factory(tmp_path)
    with f() as s:
        s.add(
            Event(
                event_id="e" * 32,
                trace_id="t" * 32,
                seq=1,
                timestamp="2026-01-01T00:00:00+00:00",
                stage="system",
                action="repo.created",
                status="ok",
            )
        )
        s.commit()
    with f() as s:
        assert not database_is_fresh(s)
        record_install(s, fresh=database_is_fresh(s))
        s.commit()
        assert install_moments(s)[1] == "unknown"


def test_the_first_green_health_is_stamped_once_and_degraded_is_not_green(tmp_path: Path) -> None:
    f = make_factory(tmp_path)
    with f() as s:
        assert not record_first_healthy(s, status="degraded")
        assert record_first_healthy(s, status="ok")
        s.commit()
    with f() as s:
        assert not record_first_healthy(s, status="ok")
        s.commit()
    assert _actions(f) == [FIRST_HEALTHY]


def test_a_server_started_on_an_empty_database_records_its_install_once(tmp_path: Path) -> None:
    f = make_factory(tmp_path)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, f)):
        pass
    with TestClient(create_app(settings, f)):  # a restart writes nothing more
        pass
    with f() as s:
        installed = s.execute(select(Event).where(Event.action == INSTALLED)).scalars().all()
    # stamped before the bootstrap admin wrote the first row: this start was the install
    assert [e.payload_json["moment"] for e in installed] == ["observed"]


def test_the_first_green_health_read_is_stamped_and_a_degraded_one_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = make_factory(tmp_path)
    status = {"now": "degraded"}
    monkeypatch.setattr(
        system_routes, "collect_health", lambda *a, **kw: {"status": status["now"], "probes": []}
    )
    with TestClient(create_app(make_settings(tmp_path), f)) as client:
        assert client.get(f"{API_PREFIX}/health").status_code == 200
        assert FIRST_HEALTHY not in _actions(f)
        status["now"] = "ok"
        client.get(f"{API_PREFIX}/health")
        client.get(f"{API_PREFIX}/health")
    assert _actions(f).count(FIRST_HEALTHY) == 1
    with f() as s:
        at, moment, healthy = install_moments(s)
    assert moment == "observed" and healthy >= at
