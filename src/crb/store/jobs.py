"""The job queue: the ``runs`` table as a durable, crash-safe work queue.

One table, one state machine::

    queued ──claim──▶ running ──finish──▶ succeeded | failed | cancelled
      ▲                 │
      └───reclaim───────┘   (stale heartbeat; recorded as an event, never silent)

Guarantees
----------
* **One claim wins.** :meth:`JobQueue.claim_next` flips ``queued → running`` in a
  single write transaction — ``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE
  SKIP LOCKED`` on PostgreSQL — so two workers polling the same queue never both
  execute one run.
* **Liveness is measured, not assumed.** A running run carries the claiming
  ``worker_id`` and a ``heartbeat`` the worker refreshes; :meth:`reclaim_stale`
  re-queues runs whose heartbeat is older than a threshold and writes a
  ``system/run.reclaimed`` event with the previous worker and the staleness. After
  ``max_reclaims`` a run is ``failed`` (a poison-pill run never loops forever).
* **A zombie cannot overwrite.** ``progress`` / ``finish`` may be scoped to the
  claiming ``worker_id``; a worker whose claim was reclaimed gets
  :class:`StaleClaim` instead of clobbering the new owner's state.
* **Cancellation is cooperative, and recorded.** :meth:`request_cancel` on a
  queued run cancels it outright; on a running run it sets ``cancel_requested`` and
  the worker stops between tasks (counts so far are kept). Both cases write a
  ``system/run.cancel_requested`` event naming the ACTOR who asked (the operator,
  not the run's creator) and the status the run was in (J-TEL-7).
* **Counts survive.** ``counts_json`` is the run's summary; ``finish`` replaces it
  but keeps the ``reclaims`` counter the queue itself maintains.

Timestamps are ISO-8601 UTC strings (second precision) as in
:mod:`crb.store.models`; staleness is computed from them in Python so SQLite and
PostgreSQL behave identically.

Navigation
----------
What it is:   The job queue — the ``runs`` table driven as a durable, crash-safe work queue.
What it does: Enqueues runs, hands each to exactly one worker, measures liveness by
              heartbeat, re-queues (then abandons) runs whose worker died, refuses a stale
              worker's writes, and supports cooperative cancellation. Every reclaim and
              abandonment is recorded as a ``system`` event, never silently.
How:          ``claim_next`` flips ``queued → running`` in one locked transaction (``BEGIN
              IMMEDIATE`` / ``FOR UPDATE SKIP LOCKED``); ``heartbeat`` / ``progress`` refresh
              the stamp; ``reclaim_stale`` compares stamps to a threshold in Python;
              ``finish`` is idempotent on a terminal run.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         none
Works with:   src/crb/store/models.py (the ``Run`` row and its liveness columns),
              src/crb/server/worker.py (the consumer: claim → execute → heartbeat → finish),
              src/crb/store/events.py (``append_event`` for the reclaim / cancel notes),
              src/crb/server/routes/runs.py (enqueues, lists and cancels over HTTP),
              src/crb/server/worker_main.py (the process that polls this queue)
Tested by:    tests/test_store_jobs.py, tests/test_server_routes_runs.py
Touch when:   never for a new repository; adding a run kind means extending ``RUN_KINDS``
              here and the executor table in src/crb/server/worker.py together (and
              docs/API.md); changing the reclaim threshold or ``max_reclaims`` default is an
              operator-visible behaviour — note it in docs/OPERATOR.md.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import utc_now_iso
from crb.core.grade import MODE_BLIND, MODE_SIGHTED
from crb.observability.events import StepStatus
from crb.store.events import append_event
from crb.store.models import Run

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUSES: tuple[str, ...] = (
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)
TERMINAL_STATUSES: frozenset[str] = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED})
ACTIVE_STATUSES: frozenset[str] = frozenset({STATUS_QUEUED, STATUS_RUNNING})

KIND_SETUP = "setup"
KIND_PROBE = "probe"
KIND_MINE = "mine"
KIND_REPLAY = "replay"
KIND_BLIND = "blind"
KIND_ORACLE = "oracle"
KIND_CONTROLS = "controls"
KIND_LABEL = "label"
KIND_FACTORY = "factory"
#: ADR-0019: measure the repository's tasks in the posture that will grade them — no
#: builder is constructed and no model is called.
KIND_QUALIFY = "qualify"
RUN_KINDS: tuple[str, ...] = (
    KIND_SETUP,
    KIND_PROBE,
    KIND_MINE,
    KIND_REPLAY,
    KIND_BLIND,
    KIND_ORACLE,
    KIND_CONTROLS,
    KIND_LABEL,
    KIND_FACTORY,
    KIND_QUALIFY,
)

DEFAULT_MAX_RECLAIMS = 3
RECLAIMS_KEY = "reclaims"


class StaleClaim(RuntimeError):
    """The run is no longer owned by this worker (reclaimed or finished elsewhere)."""


def new_run_id() -> str:
    """A fresh 32-hex run id (also the run's ``trace_id`` in the event stream)."""
    return uuid.uuid4().hex


def _created_now() -> str:
    """Microsecond-precision creation stamp so claim order is genuinely FIFO (the
    second-precision stamps elsewhere would make same-second runs tie on their id)."""
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="microseconds")


def parse_ts(value: str) -> _dt.datetime | None:
    """ISO-8601 → aware UTC datetime; ``None`` for blank/unparseable."""
    if not value:
        return None
    try:
        d = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.UTC)
    return d.astimezone(_dt.UTC)


def age_s(value: str, now: _dt.datetime) -> float | None:
    """Seconds between the stamp ``value`` and ``now``; ``None`` when unparseable."""
    d = parse_ts(value)
    return None if d is None else (now - d).total_seconds()


def _cancelled(run: Run, now: str) -> None:
    """Move ``run`` to ``cancelled`` in place (the caller commits)."""
    run.status = STATUS_CANCELLED
    run.finished = now
    run.heartbeat = ""


class JobQueue:
    """The queue API over the ``runs`` table — see the module docstring for the state
    machine and the guarantees each method upholds."""

    def __init__(
        self, factory: sessionmaker[Session], *, max_reclaims: int = DEFAULT_MAX_RECLAIMS
    ) -> None:
        self._factory = factory
        self.max_reclaims = max(0, int(max_reclaims))

    # --- plumbing -----------------------------------------------------------------
    def _lock(self, s: Session) -> None:
        # Serialises claim and reclaim so two workers cannot both take one run.
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            s.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            s.execute(text("SELECT pg_advisory_xact_lock(7334)"))  # runs (jobs) — one id per table

    def _get_owned(self, s: Session, run_id: str, worker_id: str) -> Run:
        """The run, or ``StaleClaim`` when ``worker_id`` is given and no longer owns it."""
        run = s.get(Run, run_id)
        if run is None:
            raise LookupError(f"run {run_id!r} does not exist")
        if worker_id and run.worker_id != worker_id:
            raise StaleClaim(
                f"run {run_id[:8]} is owned by {run.worker_id or '(nobody)'!r}, not {worker_id!r}"
            )
        return run

    # --- enqueue / read ----------------------------------------------------------
    def enqueue(self, run: Run) -> Run:
        """Insert a run in ``queued`` state (id/mode/created filled in when blank)."""
        if run.kind not in RUN_KINDS:
            raise ValueError(f"unknown run kind {run.kind!r}; expected one of {RUN_KINDS}")
        if not run.repo:
            raise ValueError("a run needs a repo")
        if not run.id:
            run.id = new_run_id()
        if not run.mode:
            run.mode = MODE_BLIND if run.kind == KIND_BLIND else MODE_SIGHTED
        run.status = STATUS_QUEUED
        run.worker_id = ""
        run.heartbeat = ""
        run.started = ""
        run.finished = ""
        run.cancel_requested = False
        if not run.created:
            run.created = _created_now()
        for attr in ("ladder_json", "params_json", "apparatus_json", "counts_json"):
            if getattr(run, attr) is None:
                setattr(run, attr, [] if attr == "ladder_json" else {})
        with self._factory() as s:
            s.add(run)
            s.commit()
        return run

    def get(self, run_id: str) -> Run | None:
        """One run by id, or ``None``."""
        with self._factory() as s:
            return s.get(Run, run_id)

    def list_runs(
        self,
        *,
        repo: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Run], int]:
        """Newest first. Returns ``(items, total)`` for the API's pagination envelope."""
        lim = max(1, min(int(limit), 500))
        off = max(0, int(offset))
        with self._factory() as s:
            q = select(Run)
            c = select(func.count(Run.id))
            if repo:
                q, c = q.where(Run.repo == repo), c.where(Run.repo == repo)
            if kind:
                q, c = q.where(Run.kind == kind), c.where(Run.kind == kind)
            if status:
                q, c = q.where(Run.status == status), c.where(Run.status == status)
            total = int(s.execute(c).scalar_one())
            items = list(
                s.execute(q.order_by(Run.created.desc(), Run.id.desc()).limit(lim).offset(off))
                .scalars()
                .all()
            )
        return items, total

    # --- claim / liveness --------------------------------------------------------
    def claim_next(
        self,
        worker_id: str,
        *,
        kinds: Sequence[str] | None = None,
        repo: str | None = None,
    ) -> Run | None:
        """Atomically take the oldest queued run (optionally by kind / repo).

        A queued run whose cancel was requested is finalised ``cancelled`` here
        (nobody else will) and the next one is tried.
        """
        if not worker_id:
            raise ValueError("claim_next needs a worker_id")
        while True:
            with self._factory() as s:
                self._lock(s)
                q = select(Run).where(Run.status == STATUS_QUEUED)
                if kinds:
                    q = q.where(Run.kind.in_(list(kinds)))
                if repo:
                    q = q.where(Run.repo == repo)
                q = q.order_by(Run.created, Run.id).limit(1)
                if s.get_bind().dialect.name == "postgresql":
                    # SKIP LOCKED: a second worker sees the next queued run, not a wait.
                    q = q.with_for_update(skip_locked=True)
                run = s.execute(q).scalar_one_or_none()
                if run is None:
                    s.rollback()
                    return None
                now = utc_now_iso()
                if run.cancel_requested:
                    _cancelled(run, now)
                    s.commit()
                    continue
                run.status = STATUS_RUNNING
                run.worker_id = worker_id
                run.started = now
                run.heartbeat = now
                run.finished = ""
                s.commit()
                return run

    def heartbeat(self, run_id: str, *, worker_id: str = "") -> bool:
        """Refresh the heartbeat of a running run. ``False`` if it is not running
        (finished, reclaimed) or, when ``worker_id`` is given, not owned by it."""
        with self._factory() as s:
            run = s.get(Run, run_id)
            if run is None or run.status != STATUS_RUNNING:
                return False
            if worker_id and run.worker_id != worker_id:
                return False
            run.heartbeat = utc_now_iso()
            s.commit()
            return True

    def progress(
        self,
        run_id: str,
        done: int,
        total: int,
        counts: Mapping[str, Any] | None = None,
        *,
        worker_id: str = "",
    ) -> None:
        """Record progress (and optionally interim counts); also a heartbeat."""
        with self._factory() as s:
            run = self._get_owned(s, run_id, worker_id)
            run.progress_done = max(0, int(done))
            run.progress_total = max(0, int(total))
            if counts is not None:
                run.counts_json = self._merge_counts(run.counts_json, counts)
            if run.status == STATUS_RUNNING:
                run.heartbeat = utc_now_iso()
            s.commit()

    def set_apparatus(
        self, run_id: str, apparatus: Mapping[str, Any], *, worker_id: str = ""
    ) -> None:
        """Record the apparatus stamp the run's ledger rows will carry (owner-scoped)."""
        with self._factory() as s:
            run = self._get_owned(s, run_id, worker_id)
            run.apparatus_json = dict(apparatus)
            s.commit()

    @staticmethod
    def _merge_counts(existing: Mapping[str, Any] | None, new: Mapping[str, Any]) -> dict[str, Any]:
        """``new`` replaces ``existing`` wholesale, except the queue-owned ``reclaims``
        counter, which a worker's summary must not be able to erase."""
        out = dict(new)
        old = dict(existing or {})
        if RECLAIMS_KEY in old and RECLAIMS_KEY not in out:
            out[RECLAIMS_KEY] = old[RECLAIMS_KEY]
        return out

    def finish(
        self,
        run_id: str,
        status: str,
        *,
        counts: Mapping[str, Any] | None = None,
        error: str = "",
        worker_id: str = "",
    ) -> Run:
        """Move a run to a terminal status. Idempotent on an already-terminal run
        (returns it unchanged) so a late duplicate finish cannot rewrite history."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"finish needs a terminal status, got {status!r}")
        with self._factory() as s:
            run = self._get_owned(s, run_id, worker_id)
            if run.status in TERMINAL_STATUSES:
                return run
            run.status = status
            run.error = error or ""
            run.finished = utc_now_iso()
            run.heartbeat = ""
            if counts is not None:
                run.counts_json = self._merge_counts(run.counts_json, counts)
            s.commit()
            return run

    # --- cancellation ------------------------------------------------------------
    def request_cancel(self, run_id: str, *, actor: str) -> Run | None:
        """Queued → ``cancelled`` immediately; running → flag for the worker. A
        terminal run is returned unchanged (no event). ``None`` if the run does not
        exist. ``actor`` is who asked — the route passes the operator's id, the CLI its
        principal — and is what the audit event names; the run's creator is not."""
        if not actor:
            raise ValueError("request_cancel needs the actor who asked")
        with self._factory() as s:
            run = s.get(Run, run_id)
            if run is None:
                return None
            status_at_request = run.status
            if run.status == STATUS_QUEUED:
                run.cancel_requested = True
                _cancelled(run, utc_now_iso())
            elif run.status == STATUS_RUNNING:
                run.cancel_requested = True
            s.commit()
        # The event is written after the commit: the flag is the mechanism, the event is the
        # record — a dropped event must not undo a cancel.
        if status_at_request in (STATUS_QUEUED, STATUS_RUNNING):
            append_event(
                self._factory,
                trace_id=run_id,
                stage="system",
                action="run.cancel_requested",
                repo=run.repo,
                actor=actor,
                payload={"status_at_request": status_at_request},
            )
        return run

    def is_cancel_requested(self, run_id: str) -> bool:
        """The worker's between-tasks poll: has someone asked this run to stop?"""
        with self._factory() as s:
            v = s.execute(select(Run.cancel_requested).where(Run.id == run_id)).scalar_one_or_none()
            return bool(v)

    # --- stale reclaim -----------------------------------------------------------
    def reclaim_stale(self, older_than_s: float, *, now: _dt.datetime | None = None) -> list[Run]:
        """Re-queue running runs whose heartbeat is older than ``older_than_s``.

        Never silent: each reclaim writes a ``system/run.reclaimed`` event carrying
        the previous worker and how stale it was. A run reclaimed more than
        ``max_reclaims`` times is ``failed`` instead (``system/run.abandoned``).
        Returns the affected runs.
        """
        ref_now = now or _dt.datetime.now(_dt.UTC)
        touched: list[tuple[Run, str, float, int]] = []
        with self._factory() as s:
            self._lock(s)
            running = s.execute(select(Run).where(Run.status == STATUS_RUNNING)).scalars().all()
            stamp = utc_now_iso()
            for run in running:
                stale = age_s(run.heartbeat or run.started or run.created, ref_now)
                if stale is None:
                    stale = float("inf")  # no parseable liveness at all: treat as dead
                if stale < older_than_s:
                    continue
                prev_worker = run.worker_id
                reclaims = int((run.counts_json or {}).get(RECLAIMS_KEY, 0)) + 1
                run.counts_json = {**(run.counts_json or {}), RECLAIMS_KEY: reclaims}
                if reclaims > self.max_reclaims:
                    run.status = STATUS_FAILED
                    run.finished = stamp
                    run.error = (
                        f"abandoned: reclaimed {reclaims} time(s) after stale heartbeats "
                        f"(max {self.max_reclaims}); last worker {prev_worker!r}"
                    )
                else:
                    run.status = STATUS_QUEUED
                    run.started = ""
                run.worker_id = ""
                run.heartbeat = ""
                touched.append((run, prev_worker, stale, reclaims))
            s.commit()
        # Events after the commit and outside the lock, for the same reason as in
        # request_cancel: the state change must not depend on the event write.
        for run, prev_worker, stale, reclaims in touched:
            abandoned = run.status == STATUS_FAILED
            append_event(
                self._factory,
                trace_id=run.id,
                stage="system",
                action="run.abandoned" if abandoned else "run.reclaimed",
                status=StepStatus.ERROR if abandoned else StepStatus.OK,
                repo=run.repo,
                actor=run.actor,
                error=run.error if abandoned else "",
                payload={
                    "previous_worker": prev_worker,
                    "stale_s": None if stale == float("inf") else round(stale, 1),
                    "threshold_s": older_than_s,
                    "reclaims": reclaims,
                    "max_reclaims": self.max_reclaims,
                    "status": run.status,
                },
            )
        return [t[0] for t in touched]


__all__ = [
    "ACTIVE_STATUSES",
    "DEFAULT_MAX_RECLAIMS",
    "KIND_BLIND",
    "KIND_CONTROLS",
    "KIND_LABEL",
    "KIND_MINE",
    "KIND_ORACLE",
    "KIND_PROBE",
    "KIND_QUALIFY",
    "KIND_REPLAY",
    "KIND_SETUP",
    "RECLAIMS_KEY",
    "RUN_KINDS",
    "STATUSES",
    "STATUS_CANCELLED",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "STATUS_SUCCEEDED",
    "TERMINAL_STATUSES",
    "JobQueue",
    "StaleClaim",
    "age_s",
    "new_run_id",
    "parse_ts",
]
