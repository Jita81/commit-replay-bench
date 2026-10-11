"""The repository's registered readings, as every reader of them reads them (ADR-0026 item 2).

``load_readings`` lived in the readings route module; the run submit gate and the worker now
read it too (a run filed under a reading, P-789), and ``crb.server.routes.runs`` sits under
that module's own imports, so the reader lives here, below both, and the route module
re-exports it for its existing callers.

Navigation
----------
What it is:   The one reader of ``reading.registered`` events: the verified readings of a
              repository, in registration order, a forward reading's pool enrolled.
What it does: Reads the repository's reading events; keeps a record only when its id and pool
              hash re-hash and it names this repository; fills a forward reading's pool from the
              held-out records written after it (``with_enrolment``, DL-334).
How:          ``Event`` rows (``action == reading.registered``) → ``Reading.from_dict`` →
              ``Reading.verify`` → ``with_enrolment`` over ``load_held_out``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 2)
Works with:   src/crb/server/routes/readings.py (registers readings; re-exports this reader),
              src/crb/server/routes/runs.py (``reading_refusal``: a run filed under a reading),
              src/crb/server/worker.py (``_reading_unsealed``, ``_reading_posture_mismatch``:
              the same rules at claim),
              src/crb/core/reading.py (the record, its hash and the enrolment rule),
              src/crb/server/acceptance.py (``load_held_out``: a forward reading's records)
Tested by:    tests/test_server_readings.py, tests/test_server_routes_runs.py,
              tests/test_worker.py
Touch when:   never for a new repository; a reading's verified set changes (an ADR amending
              ADR-0026 first).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.acceptance import HeldOutTests
from crb.core.reading import READING_EVENT_ACTION, Reading, with_enrolment
from crb.server.acceptance import load_held_out
from crb.store.models import Event


def load_readings(session: Session, repo: str) -> list[Reading]:
    """The repository's registered readings, in registration order. A record whose id or pool
    hash does not re-hash licenses nothing and is left out (the verified set is what counts).
    A forward reading's pool is filled here, once, from the held-out records written after it
    (``crb.core.reading.with_enrolment``, DL-334) — so every reader of readings, the factory's
    gate included, reads the same enrolled pool."""
    out: list[Reading] = []
    records: list[HeldOutTests] | None = None
    for ev in session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == READING_EVENT_ACTION)
        .order_by(Event.id)
    ).scalars():
        reading = Reading.from_dict(dict(ev.payload_json or {}))
        if reading.verify() and reading.repo == repo:
            if reading.prospective:
                if records is None:
                    records = load_held_out(session, repo)
                reading = with_enrolment(reading, records)
            out.append(reading)
    return out


__all__ = ["load_readings"]
