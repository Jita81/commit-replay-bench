"""The database holds one reading reservation per (reading, arm, commit) — P-792, C19 and C1.

A reserved reading spends one commit per arm once: the reserver checks under the events lock
that no reservation exists for (reading, arm, commit) before it writes one. This suite pins
the backstop behind that check — revision 0018's partial unique index
``uq_events_reading_reserved`` on ``events(trace_id, step_id, task_id) WHERE action =
'reading.reserved'`` — and the one place its refusal is named: ``append_event_checked``
raises :class:`crb.store.events.ReservationExists` for that violation and re-raises every
other ``IntegrityError`` unchanged.

Navigation
----------
What it is:   The store suite for a reading's reservations: the partial unique index, the
              error the locked writer maps its violation to, and revision 0018's up and down.
What it does: Pins that a second ``reading.reserved`` row for one (trace, arm, commit) is
              refused by the database, for any writer, while another arm, another commit,
              another reading or another action with the same triple is stored (the index is
              partial, so a trace's ordinary events never collide on it); that
              ``append_event_checked`` turns that refusal into ``ReservationExists`` and leaves
              one row, an intact chain and the next ``seq`` free, while an ``IntegrityError``
              on any other constraint reaches the caller unchanged; and that revision 0018
              creates the index from 0017, drops it on downgrade and creates it again.
How:          The shared ``backend`` fixture (SQLite always, PostgreSQL when
              ``CRB_TEST_POSTGRES_URL`` is set); plain ORM adds for the raw duplicates (the
              flush hook chains them); Alembic ``upgrade`` / ``downgrade`` on the backend's
              URL for the revision.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (the ``Event`` index),
              src/crb/store/migrations/versions/v0018_reading_reservations.py (the revision),
              src/crb/store/events.py (``append_event_checked``, ``ReservationExists``),
              src/crb/core/reading.py (``READING_RESERVED_ACTION``),
              tests/test_store_migrate.py (head parity and drift with the partial index),
              tests/conftest_store.py (the backends)
Tested by:    tests/test_p792_reserved_store.py
Touch when:   never for a new repository; the reservation's key or action changes (a new
              revision, never an edit of 0018), or the locked writer's error mapping changes.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from crb.core.reading import READING_RESERVED_ACTION
from crb.store import init_db, migrate
from crb.store.events import ReservationExists, append_event_checked, verify_events
from crb.store.models import Event

try:
    from tests.conftest_store import SHA, Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import SHA, Backend, backend, pg_schema  # noqa: F401

#: The index revision 0018 adds and the predicate each dialect reflects it with.
INDEX = "uq_events_reading_reserved"
WHERE = {
    "sqlite": "action = 'reading.reserved'",
    "postgresql": "((action)::text = 'reading.reserved'::text)",
}
READING = "rdg_" + "a" * 24  # a reading id: 28 characters, inside ``trace_id``'s 32
OTHER_SHA = "b" * 40


@pytest.fixture
def db(backend: Backend) -> Backend:
    init_db(backend.engine)
    return backend


def _add(
    b: Backend,
    *,
    seq: int,
    step_id: str = "S1",
    task_id: str = SHA,
    action: str = READING_RESERVED_ACTION,
    trace_id: str = READING,
) -> None:
    """One event row through a plain ORM add — the writer that knows nothing of the
    reservation check, so only the database can refuse its duplicate."""
    with b.factory() as s:
        s.add(
            Event(
                event_id=uuid.uuid4().hex,
                trace_id=trace_id,
                seq=seq,
                timestamp="2026-10-11T10:00:00+00:00",
                stage="system",
                action=action,
                status="ok",
                step_id=step_id,
                task_id=task_id,
            )
        )
        s.commit()


def _rows(b: Backend, action: str = READING_RESERVED_ACTION) -> list[tuple[str, str, str]]:
    with b.factory() as s:
        return [
            (r.trace_id, r.step_id, r.task_id)
            for r in s.execute(
                select(Event).where(Event.action == action).order_by(Event.id)
            ).scalars()
        ]


def _violated(exc: IntegrityError) -> str:
    """What the driver says was violated: PostgreSQL names the constraint, SQLite the
    columns."""
    name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return str(name) if name else str(exc.orig)


def test_p792_index_refuses_duplicate_insert(db: Backend) -> None:
    """C19 / C1 (P-792): a second reservation of one commit on one arm of one reading is
    refused by the database itself — the backstop for a writer that never ran the in-lock
    check — and the refusal names the reservation index. The index is PARTIAL: another
    arm, another commit, another reading, and any other action on the same triple (a
    trace's ordinary events, which share ``step_id`` and ``task_id`` all the time) are
    stored, so a full unique index in its place would be a defect, not a stricter one."""
    _add(db, seq=1)
    with pytest.raises(IntegrityError) as caught:
        _add(db, seq=2)  # same (reading, arm, commit), a fresh seq: only the index refuses it
    expected = (
        INDEX
        if db.dialect == "postgresql"
        else "UNIQUE constraint failed: events.trace_id, events.step_id, events.task_id"
    )
    assert _violated(caught.value) == expected
    assert _rows(db) == [(READING, "S1", SHA)]

    _add(db, seq=3, step_id="A0+L")  # another arm of the same commit
    _add(db, seq=4, task_id=OTHER_SHA)  # another commit on the same arm
    _add(db, seq=1, trace_id="rdg_" + "c" * 24)  # another reading's reservation of it
    _add(db, seq=5, action="reading.registered")  # another action on the same triple...
    _add(db, seq=6, action="reading.registered")  # ...twice: the predicate leaves it free
    assert _rows(db) == [
        (READING, "S1", SHA),
        (READING, "A0+L", SHA),
        (READING, "S1", OTHER_SHA),
        ("rdg_" + "c" * 24, "S1", SHA),
    ]
    assert len(_rows(db, "reading.registered")) == 2
    report = verify_events(db.factory)  # the refused insert left no gap in the chain
    assert report.ok and report.rows == 6, report.detail


def _reserve(
    b: Backend,
    built: list[str],
    *,
    step_id: str = "S1",
    task_id: str = SHA,
    action: str = READING_RESERVED_ACTION,
) -> Any:
    def build(_s: object) -> dict[str, Any]:
        built.append(step_id)
        return {"arm": step_id}

    return append_event_checked(
        b.factory,
        trace_id=READING,
        stage="system",
        action=action,
        build=build,
        actor="worker-1",
        repo="r1",
        task_id=task_id,
        step_id=step_id,
    )


def test_p792_reservation_exists_maps_the_index_violation(db: Backend) -> None:
    """C1 (P-792): the locked writer names the backstop's refusal. A duplicate reservation
    that got past ``build`` (here ``build`` checks nothing, as a reserver with a defect in
    its check would) raises ``ReservationExists`` naming the reading, arm and commit —
    never a bare ``IntegrityError`` a caller would have to parse — and the database is left
    with one reservation, an intact chain and the next ``seq`` unspent. Every other
    integrity failure is not a reservation and is re-raised unchanged: an ordinary action,
    and a reservation that broke a different constraint."""
    built: list[str] = []
    first = _reserve(db, built)
    assert (first.seq, first.step_id, first.task_id) == (1, "S1", SHA)
    with pytest.raises(ReservationExists) as caught:
        _reserve(db, built)
    exc = caught.value
    assert (exc.trace_id, exc.step_id, exc.task_id) == (READING, "S1", SHA)
    assert isinstance(exc.__cause__, IntegrityError)
    assert READING in str(exc) and "S1" in str(exc) and SHA in str(exc)
    assert built == ["S1", "S1"]  # the duplicate reached the database: the index refused it
    assert _rows(db) == [(READING, "S1", SHA)]
    assert _reserve(db, built, step_id="A0+L").seq == 2  # the refused write spent no seq
    report = verify_events(db.factory)
    assert report.ok and report.rows == 2, report.detail

    # another constraint, on any action: an IntegrityError the caller sees as it was raised.
    # The probe index refuses a second (repo, actor, arm); neither write below is a second
    # reservation of (reading, arm, commit), so only the probe index can refuse it
    with db.engine.begin() as c:
        c.execute(text("CREATE UNIQUE INDEX uq_probe_events_arm ON events (repo, actor, step_id)"))
    probe = (
        "uq_probe_events_arm"
        if db.dialect == "postgresql"
        else "UNIQUE constraint failed: events.repo, events.actor, events.step_id"
    )
    for action, task_id in (("reading.note", SHA), (READING_RESERVED_ACTION, OTHER_SHA)):
        with pytest.raises(IntegrityError) as other:
            _reserve(db, built, task_id=task_id, action=action)
        assert type(other.value) is IntegrityError and _violated(other.value) == probe
    assert _rows(db) == [(READING, "S1", SHA), (READING, "A0+L", SHA)]
    assert _rows(db, "reading.note") == []


def _reserved_index(engine: Engine) -> dict[str, Any] | None:
    for ix in inspect(engine).get_indexes("events"):
        if ix["name"] == INDEX:
            return dict(ix)
    return None


def _downgrade(b: Backend, revision: str) -> None:
    cfg = migrate.alembic_config(b.url)
    with b.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, revision)


def test_v0018_upgrade_and_downgrade(backend: Backend) -> None:
    """Revision 0018 adds the reservation index to a 0017 store — unique, on (trace, arm,
    commit), partial on the reserved action, on SQLite and PostgreSQL alike — drops it on
    downgrade without touching a row, and adds it again on a second upgrade over the rows
    the first one let in."""
    migrate.upgrade(backend.url, revision="0017")
    assert migrate.current(backend.url) == "0017"
    assert _reserved_index(backend.engine) is None

    migrate.upgrade(backend.url, revision="0018")
    assert migrate.current(backend.url) == "0018"
    ix = _reserved_index(backend.engine)
    assert ix is not None
    assert ix["column_names"] == ["trace_id", "step_id", "task_id"] and bool(ix["unique"])
    where = ix["dialect_options"][f"{backend.dialect}_where"]
    assert str(where) == WHERE[backend.dialect]
    _add(backend, seq=1)
    with pytest.raises(IntegrityError):
        _add(backend, seq=2)

    _downgrade(backend, "0017")
    assert migrate.current(backend.url) == "0017"
    assert _reserved_index(backend.engine) is None
    assert _rows(backend) == [(READING, "S1", SHA)]  # a downgrade drops the index, no row

    migrate.upgrade(backend.url, revision="0018")
    assert migrate.current(backend.url) == "0018"
    again = _reserved_index(backend.engine)
    assert again is not None
    assert str(again["dialect_options"][f"{backend.dialect}_where"]) == WHERE[backend.dialect]
    assert _rows(backend) == [(READING, "S1", SHA)]
