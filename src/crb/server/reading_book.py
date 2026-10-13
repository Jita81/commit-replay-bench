"""The repository's registered readings, as every reader of them reads them (ADR-0026 item 2).

``load_readings`` lived in the readings route module; the run submit gate and the worker now
read it too (a run filed under a reading, P-789), and ``crb.server.routes.runs`` sits under
that module's own imports, so the reader lives here, below both, and the route module
re-exports it for its existing callers.

Navigation
----------
What it is:   The one reader of ``reading.registered`` events: the verified readings of a
              repository, in registration order, each ``reading_id`` once, a forward
              reading's pool enrolled, a campaign-named reading's admitted runs read and a
              reserved.v1 reading's reservations read.
What it does: Reads the repository's reading events; keeps a record only when its id and pool
              hash re-hash and it names this repository, and only the first record of each
              ``reading_id`` (``first_per_id``, P-793 — a retried registration stored twice
              before the ``reading_exists`` refusal reads, lists and spends once); fills a
              forward reading's pool from the held-out records written after it
              (``with_enrolment``, DL-334); fills a reading that names a campaign with the runs
              admitted under it (``with_admissions``, DL-382), so every server reader counts
              only those runs' rows; fills a reserved.v1 reading with its reservations and its
              first registration's ``Event.id`` (``with_reservations``, P-792). Reads a
              reserved.v1 reading's treatment pins (``treatment_pins``, trust on first use):
              the campaign's first reservation on the repository and each arm's first.
              Reads a repository's lint configuration (``repo_lint``, P-796) for the one
              ``lint_disabled`` refusal at registration, submit and claim. Reads a
              reserved.v1 reading's pool drift (``pool_drift``, P-797) for the one
              ``pool_drift`` state and refusal at ``GET /readings``, submit and claim: a pool
              commit's live class or size no longer the cell's, or a pinned qualification
              record missing, misbound or not qualified (a newer record — a requalification
              or a revocation — is never drift; admission reads that).
How:          ``Event`` rows (``action == reading.registered``) → ``Reading.from_dict`` →
              ``Reading.verify`` → ``with_enrolment`` over ``load_held_out`` →
              ``with_admissions`` over ``admitted_runs`` (one read per campaign) →
              ``with_reservations`` over ``reservations_of`` (one read per reserved reading);
              ``treatment_pins``: the repository's ``reading.reserved`` events in ``Event.id``
              order; ``repo_lint``: the ``Repo`` row's ``config_json["lint"]``;
              ``pool_drift``: the pool's ``Task`` rows (column and ``spec_json``) and its
              pinned records (``crb.store.qualifications.by_ids``).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 2)
Works with:   src/crb/server/routes/readings.py (registers readings; re-exports this reader;
              serves the pins as ``pinned_treatment``),
              src/crb/server/routes/runs.py (``reading_refusal``: a run filed under a reading;
              ``reading_lint_refusal``; ``reading_pool_drift_refusal``),
              src/crb/server/worker.py (``_reading_unsealed``,
              ``_reading_posture_mismatch``, ``_reading_lint_disabled``,
              ``_reading_pool_drift``: the same rules at claim; ``_treatment_pins``: the
              reserver halts on a moved pin),
              src/crb/store/qualifications.py (``by_ids``: the records a pool pinned),
              src/crb/core/reading.py (the record, its hash and the enrolment rule),
              src/crb/server/acceptance.py (``load_held_out``: a forward reading's records),
              src/crb/server/campaigns.py (``admitted_runs``: the runs a campaign admitted;
              ``reservations_of``: a reserved reading's reservations)
Tested by:    tests/test_server_readings.py, tests/test_server_routes_runs.py,
              tests/test_worker.py, tests/test_server_campaigns.py, tests/test_p792_reserved.py,
              tests/test_p792_reserved_reservation.py, tests/test_p792_pool.py
Touch when:   never for a new repository; a reading's verified set changes (an ADR amending
              ADR-0026 first).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.acceptance import HeldOutTests
from crb.core.reading import (
    READING_EVENT_ACTION,
    READING_RESERVED_ACTION,
    Reading,
    first_per_id,
    with_admissions,
    with_enrolment,
    with_reservations,
)
from crb.core.spec import TaskSpec
from crb.server.acceptance import load_held_out
from crb.server.campaigns import admitted_runs, reservations_of
from crb.store import qualifications as store_q
from crb.store.models import Event, Repo, Task


def load_readings(session: Session, repo: str) -> list[Reading]:
    """The repository's registered readings, in registration order. A record whose id or pool
    hash does not re-hash licenses nothing and is left out (the verified set is what counts),
    and a ``reading_id`` stored twice is read once, by its first record (``first_per_id``,
    P-793). A forward reading's pool is filled here, once, from the held-out records written after it
    (``crb.core.reading.with_enrolment``, DL-334) — so every reader of readings, the factory's
    gate included, reads the same enrolled pool. A reading that names a campaign is filled with
    the runs admitted under it (``with_admissions``, DL-382): it counts only their rows. A
    reserved.v1 reading is filled with its reservations and the ``Event.id`` of its first
    registration (``with_reservations``, P-792): a reservation written before that never
    decides a commit."""
    out: list[Reading] = []
    records: list[HeldOutTests] | None = None
    admissions: dict[str, frozenset[str]] = {}
    first_ev: dict[str, int] = {}
    for ev in session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == READING_EVENT_ACTION)
        .order_by(Event.id)
    ).scalars():
        reading = Reading.from_dict(dict(ev.payload_json or {}))
        if reading.verify() and reading.repo == repo:
            first_ev.setdefault(reading.reading_id, int(ev.id))
            if reading.prospective:
                if records is None:
                    records = load_held_out(session, repo)
                reading = with_enrolment(reading, records)
            if reading.campaign_id:
                if reading.campaign_id not in admissions:
                    admissions[reading.campaign_id] = admitted_runs(session, reading.campaign_id)
                reading = with_admissions(reading, admissions[reading.campaign_id])
            out.append(reading)
    return [
        with_reservations(r, reservations_of(session, [r.reading_id]), first_ev[r.reading_id])
        if r.reserved
        else r
        for r in first_per_id(out)
    ]


def treatment_pins(session: Session, reading: Reading) -> tuple[Event | None, dict[str, Event]]:
    """The reservations that pin a reserved.v1 reading's treatment (P-792, trust on first
    use), as ``(deployment, {arm: event})``: the deployment half is the first
    ``reading.reserved`` event on the reading's repository under its campaign (under the
    reading itself when it names none), and each arm's half the reading's first reservation on
    that arm. The deployment half is ``None``, and an arm absent, before its first reservation.
    One rule for the worker, which halts a run whose treatment moved from these pins, and for
    ``GET /readings``, which serves them."""
    deployment: Event | None = None
    arms: dict[str, Event] = {}
    for ev in session.execute(
        select(Event)
        .where(Event.action == READING_RESERVED_ACTION, Event.repo == reading.repo)
        .order_by(Event.id)
    ).scalars():
        same_campaign = str((ev.payload_json or {}).get("campaign_id") or "") == (
            reading.campaign_id
        )
        if (
            deployment is None
            and same_campaign
            and (reading.campaign_id or ev.trace_id == reading.reading_id)
        ):
            deployment = ev
        if ev.trace_id == reading.reading_id:
            arms.setdefault(ev.step_id, ev)
    return deployment, arms


def repo_lint(session: Session, repo: str) -> dict[str, Any]:
    """The repository's lint configuration as ``RepoConfig.from_dict`` reads it (``{}`` when the
    row names none, or there is no row) — what ``crb.core.reading.lint_refusal`` and
    ``lint_config_digest`` read (P-796)."""
    row = session.get(Repo, repo)
    config = dict((row.config_json if row is not None else None) or {})
    return dict(config.get("lint") or {})


#: What a pool drift row's ``now`` says of a task or a pinned record the store does not hold.
DRIFT_MISSING = "missing"


def _drift(task_id: str, field: str, registered: str, now: str) -> dict[str, str]:
    return {"task_id": task_id, "field": field, "registered": registered, "now": now}


def pool_drift(session: Session, reading: Reading) -> list[dict[str, str]]:
    """How a reserved.v1 reading's pool moved since registration (P-797), as
    ``{task_id, field, registered, now}`` rows in the seeded order — ``[]`` when it has not,
    and for a legacy or forward reading (``Reading.pins_pool``), whose pools pin nothing.

    A row is a pool commit whose live task (its ``Task`` column or its ``spec_json``) reads a
    ``capability_class`` or ``size`` other than the cell's, a pool commit the store no longer
    holds (``task``), or a pinned record (``qualification``) that is missing, not
    ``qualified``, or of another repository, task or posture; a reading pinned to no posture is
    one ``pool_posture_id`` row (fail closed). A NEWER record for the pinned posture — a
    requalification, or a revocation — is never drift: the pinned record is append-only and
    still says what admitted the commit, and a revoked record in force is refused at admission,
    so that commit stays pending (a stall, never a skip)."""
    if not reading.pins_pool:
        return []
    if not reading.pool_posture_id:
        return [_drift("", "pool_posture_id", "", DRIFT_MISSING)]
    pool = list(reading.pool)
    tasks = {
        t.task_id: t
        for t in session.execute(
            select(Task).where(Task.repo == reading.repo, Task.task_id.in_(pool))
        ).scalars()
    }
    records = store_q.by_ids(session, reading.pool_qualifications.values())
    out: list[dict[str, str]] = []
    for commit in pool:
        task = tasks.get(commit)
        if task is None:
            out.append(_drift(commit, "task", commit, DRIFT_MISSING))
        else:
            spec = TaskSpec.from_dict(dict(task.spec_json or {}))
            for name in ("capability_class", "size"):
                want = str(reading.cell.get(name, ""))
                live = [str(getattr(task, name)), str(getattr(spec, name))]
                moved = next((v for v in live if v != want), None)
                if moved is not None:
                    out.append(_drift(commit, name, want, moved))
        pin = reading.pool_qualifications.get(commit, "")
        record = records.get(pin) if pin else None
        if record is None:
            out.append(_drift(commit, "qualification", pin, DRIFT_MISSING))
        elif not record.is_qualified:
            out.append(_drift(commit, "qualification", pin, record.state))
        elif (record.repo, record.task_id, record.posture_id) != (
            reading.repo,
            commit,
            reading.pool_posture_id,
        ):
            out.append(
                _drift(commit, "qualification", pin, f"{record.task_id} in {record.posture_id}")
            )
    return out


__all__ = ["DRIFT_MISSING", "load_readings", "pool_drift", "repo_lint", "treatment_pins"]
