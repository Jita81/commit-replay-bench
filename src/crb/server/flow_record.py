"""The moments the flow reading cannot derive, recorded when they happen (ADR-0029).

The flow reading (:mod:`crb.server.flow`) is a fold over stored records, and three of the
moments its streams' MEASURE criteria name were never stored: the route is recomputed on every
read, so *the moment a cell first routed deliver* existed only for as long as a page was open;
and nothing stamped *the install* or *the first green* ``/health``. This module writes each of
them once, as a system event, at the moment the product itself observes it — and no earlier
moment is ever guessed.

* **A cell first routes deliver** — after every finished run the worker hands this module the
  cells of the map it serves that route ``deliver``. The first time the recorder runs for a
  repository in a scope (apparatus version × posture class × checks arm) it writes
  ``flow.recorder_started`` listing the cells ALREADY at deliver: their first moment is
  unknown (it passed before anything recorded it) and they are never timed. From then on a
  cell at deliver that is neither inherited nor stamped is stamped ``cell.routed_deliver`` —
  at the end of the run after which the map first routed it, which is the moment the product
  first knew. A cell is stamped once per scope; leaving deliver and returning does not move it.
* **The install** — at every server start, when no ``deployment.installed`` event exists, one
  is written: ``moment: observed`` when the database held nothing before this start (no
  account, no event, no repository — this start IS the install), else ``moment: unknown``
  (an existing deployment upgraded to this release: its install passed unrecorded, and the
  reading says so rather than date it from today).
* **The first green /health** — the first ``/health`` read whose status is ``ok`` writes
  ``deployment.first_healthy``. Two concurrent first reads may both write; every reader takes
  the earliest.

Navigation
----------
What it is:   The recorder of the three moments the flow reading needs and could not derive:
              ``cell.routed_deliver`` (with ``flow.recorder_started``), ``deployment.installed``
              and ``deployment.first_healthy`` — and the readers that fold them back.
What it does: Writes each moment once as a system event in the caller's session (the caller
              commits), never back-dates one, marks a moment that passed before recording as
              unknown, and reads them back for ``crb.server.flow`` — a deliver stamp with the
              scope it was recorded in, so a reader pairs it only within that scope.
How:          ``append_system_event`` on a deterministic trace per repository (or per
              deployment); the "already written?" checks are single ``select``s on
              ``Event.action``; the readers return plain stamps and cell keys.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-moments-flow-needs-are-recorded.md
Works with:   src/crb/server/worker.py (stamps deliver transitions after every finished run),
              src/crb/server/app.py (stamps the install at startup, before the bootstrap
              admin), src/crb/server/routes/system.py (stamps the first green ``/health``),
              src/crb/server/flow.py (reads the moments into the decide and platform streams),
              src/crb/server/routes/runs.py (``append_system_event`` — the one event writer)
Tested by:    tests/test_flow_record.py, tests/test_server_routes_flow.py, tests/test_worker.py
Touch when:   a stream's MEASURE criterion needs a moment the store does not keep (add its
              writer here, its reader beside it, and an ADR-0029 amendment); never to derive a
              moment from a neighbouring one.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from crb.server.routes.runs import append_system_event, system_trace_id
from crb.store.models import Event, Repo, User

# Every writer below names its action as a literal (the event-vocabulary ratchet,
# tests/test_event_vocabulary.py, reads literals); these constants are what readers match.
#: A cell of a repository first routed ``deliver`` in a scope (written once per cell and scope).
DELIVER_ROUTED = "cell.routed_deliver"
#: The recorder's first look at a repository in a scope, naming the cells already at deliver.
RECORDER_STARTED = "flow.recorder_started"
#: The deployment's install moment (``moment``: ``observed`` or ``unknown``).
INSTALLED = "deployment.installed"
#: The first ``/health`` read whose status was ``ok``.
FIRST_HEALTHY = "deployment.first_healthy"
#: The two ``moment`` words: seen as it happened, or passed before anything recorded it.
MOMENT_OBSERVED = "observed"
MOMENT_UNKNOWN = "unknown"
#: The actor the recorder writes as — the product itself, never a person.
ACTOR = "system:flow-recorder"

Cell = tuple[str, str]

_LOG = logging.getLogger(__name__)


def scope_key(scope: Mapping[str, str]) -> str:
    """One scope as a stable string: apparatus version × posture class × checks arm."""
    return "|".join(str(scope.get(k, "")) for k in ("apparatus", "posture_class", "checks_arm"))


def _cell_of(payload: Mapping[str, Any]) -> Cell:
    return (str(payload.get("capability_class", "")), str(payload.get("size", "")))


def _events(session: Session, action: str, repo: str | None = None) -> list[Event]:
    q = select(Event).where(Event.action == action)
    if repo is not None:
        q = q.where(Event.repo == repo)
    return list(session.execute(q.order_by(Event.id.asc())).scalars())


def record_deliver_transitions(
    session: Session,
    *,
    repo: str,
    deliver_cells: Iterable[Cell],
    scope: Mapping[str, str],
    run_id: str = "",
) -> list[Cell]:
    """Stamp every cell of ``repo`` that routes ``deliver`` now and never did before in this
    scope; returns the cells stamped. The first call for a repository and scope stamps none:
    it records the cells already at deliver as inherited (their moment is unknown)."""
    key = scope_key(scope)
    now = sorted(set(deliver_cells))
    started = [
        ev
        for ev in _events(session, RECORDER_STARTED, repo)
        if (ev.payload_json or {}).get("scope") == key
    ]
    trace = system_trace_id("flow", repo)
    if not started:
        append_system_event(
            session,
            trace_id=trace,
            action="flow.recorder_started",  # RECORDER_STARTED, as a literal
            repo=repo,
            actor=ACTOR,
            payload={
                "scope": key,
                **dict(scope),
                "run_id": run_id,
                "inherited": [{"capability_class": c, "size": s} for c, s in now],
            },
        )
        return []
    inherited = {
        _cell_of(c) for ev in started for c in (ev.payload_json or {}).get("inherited", [])
    }
    stamped = {
        _cell_of(ev.payload_json or {})
        for ev in _events(session, DELIVER_ROUTED, repo)
        if (ev.payload_json or {}).get("scope") == key
    }
    new = [c for c in now if c not in inherited and c not in stamped]
    for cls, size in new:
        append_system_event(
            session,
            trace_id=trace,
            action="cell.routed_deliver",  # DELIVER_ROUTED, as a literal
            repo=repo,
            actor=ACTOR,
            payload={
                "scope": key,
                **dict(scope),
                "capability_class": cls,
                "size": size,
                "moment": MOMENT_OBSERVED,
                "run_id": run_id,
            },
        )
    return new


def deliver_moments(session: Session, repo: str) -> dict[Cell, list[str]]:
    """Every observed first-deliver stamp of ``repo``, per cell, oldest first (one per scope)."""
    out: dict[Cell, list[str]] = {}
    for ev in _events(session, DELIVER_ROUTED, repo):
        out.setdefault(_cell_of(ev.payload_json or {}), []).append(ev.timestamp)
    return out


@dataclass(frozen=True)
class DeliverStamp:
    """One ``cell.routed_deliver`` stamp as written: the cell, when, and the scope it was
    recorded in (``""`` for a field the stamp does not carry)."""

    capability_class: str
    size: str
    timestamp: str
    apparatus: str
    posture_class: str
    checks_arm: str


def deliver_stamps(session: Session, repo: str) -> list[DeliverStamp]:
    """Every observed first-deliver stamp of ``repo`` with its scope, oldest first — what a
    reader needs to pair a stamp only with a decision of the same scope."""
    out: list[DeliverStamp] = []
    for ev in _events(session, DELIVER_ROUTED, repo):
        p = ev.payload_json or {}
        cls, size = _cell_of(p)
        out.append(
            DeliverStamp(
                capability_class=cls,
                size=size,
                timestamp=ev.timestamp,
                apparatus=str(p.get("apparatus", "") or ""),
                posture_class=str(p.get("posture_class", "") or ""),
                checks_arm=str(p.get("checks_arm", "") or ""),
            )
        )
    return out


def inherited_cells(session: Session, repo: str) -> int:
    """How many cells of ``repo`` were already at deliver when the recorder first looked —
    counted, never timed."""
    return sum(
        len((ev.payload_json or {}).get("inherited", []))
        for ev in _events(session, RECORDER_STARTED, repo)
    )


def database_is_fresh(session: Session) -> bool:
    """Nothing written yet: no account, no event, no repository. A start on such a database
    is the install; a start on any other is an upgrade or a restart."""
    for model in (User, Event, Repo):
        if session.execute(select(func.count()).select_from(model)).scalar_one():
            return False
    return True


def record_install(session: Session, *, fresh: bool) -> bool:
    """Write ``deployment.installed`` once; ``fresh`` says whether this start is the install
    (observed) or the first start of this release on an existing deployment (unknown).
    Returns whether it wrote."""
    if _events(session, INSTALLED):
        return False
    append_system_event(
        session,
        trace_id=system_trace_id("flow", "deployment"),
        action="deployment.installed",  # INSTALLED, as a literal
        actor=ACTOR,
        payload={"moment": MOMENT_OBSERVED if fresh else MOMENT_UNKNOWN},
    )
    return True


def record_first_healthy(session: Session, *, status: str) -> bool:
    """Write ``deployment.first_healthy`` the first time ``/health`` reads ``ok``; returns
    whether it wrote. ``degraded`` and ``down`` are not green and write nothing."""
    if status != "ok" or _events(session, FIRST_HEALTHY):
        return False
    append_system_event(
        session,
        trace_id=system_trace_id("flow", "deployment"),
        action="deployment.first_healthy",  # FIRST_HEALTHY, as a literal
        actor=ACTOR,
        payload={"status": status},
    )
    return True


def stamp_install(factory: sessionmaker[Session]) -> None:
    """At server start, before anything else writes: :func:`record_install` in its own
    transaction. Observability, never a start condition — a failure is logged."""
    try:
        with factory() as s:
            record_install(s, fresh=database_is_fresh(s))
            s.commit()
    except Exception:
        _LOG.exception("flow: recording the install moment failed")


def stamp_first_healthy(factory: sessionmaker[Session], status: str) -> None:
    """After a ``/health`` read: :func:`record_first_healthy` in its own transaction, only
    for a green read. A failure is logged and the health answer stands."""
    if status != "ok":
        return
    # /health is polled (the chart's readiness probe, every 10 s): once this process has seen
    # the stamp on record, it never reads the events table for it again
    key = _database_key(factory)
    if key in _HEALTHY_ON_RECORD:
        return
    try:
        with factory() as s:
            record_first_healthy(s, status=status)
            s.commit()
        _HEALTHY_ON_RECORD.add(key)
    except Exception:
        _LOG.exception("flow: recording the first green /health failed")


#: The databases (by URL) this process knows already hold ``deployment.first_healthy``.
_HEALTHY_ON_RECORD: set[str] = set()


def _database_key(factory: sessionmaker[Session]) -> str:
    bind = factory.kw.get("bind")
    return str(getattr(bind, "url", id(factory)))


def install_moments(session: Session) -> tuple[str, str, str]:
    """``(installed_at, moment, first_healthy_at)`` — ``""`` for a moment not on record; the
    earliest of each when two were written."""
    installed = _events(session, INSTALLED)
    healthy = _events(session, FIRST_HEALTHY)
    at = min((e.timestamp for e in installed), default="")
    moment = str((installed[0].payload_json or {}).get("moment", "")) if installed else ""
    return at, moment, min((e.timestamp for e in healthy), default="")
