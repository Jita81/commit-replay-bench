"""The prevention loop on a live stack — its chain in the events table, the per-run snapshot
and the tick the worker runs after every build run (ADR-0020 §3, §10).

The loop's only state is its hash-chained record. On a stack each record is ONE
``learn.prevention.recorded`` system event on the repository's ``learn:<repo>`` trace: the
``events`` table's triggers make it append-only, the chain inside the payload
(``prev_hash`` → ``row_hash``, :class:`~crb.core.prevention.PreventionRecord`) makes it
tamper-evident — a system trace alone is only *sequenced* — and the database backup already
covers it. No new table, no migration.

Two appenders on one trace (the worker's tick and an operator's route) can both read the same
head; the second insert then collides on ``uq_events_trace_seq``. :func:`learning_tick` re-reads
and recomputes up to three times (optimistic concurrency on the trace); a route call retries
once. A tick never raises into a run: it logs.

Navigation
----------
What it is:   The server half of the prevention loop — the events-table store of the
              prevention chain, the register as served, the per-run snapshot and the tick.
What it does: Reads and appends ``learn.prevention.recorded`` events as a verified chain;
              builds a repository's register from its ledger rows, standing reviews, factory
              outcome events and (for belt-5 rows) evidence packs; gives a run the snapshot the
              switch allows under the team's own configuration; runs one tick and commits what
              it appends, retrying on a concurrent append, never raising.
How:          ``EventsPreventionStore`` (select by trace + action, ordered by ``seq`` →
              ``PreventionRecord.from_dict`` → ``verify_records``; append = chain on the head →
              ``append_system_event``) → ``register_for`` → ``learning_snapshot`` /
              ``learning_tick``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/prevention.py (the engine: register, rule, tick, snapshot),
              src/crb/server/routes/runs.py (``append_system_event``, ``system_trace_id``),
              src/crb/server/worker.py (takes the snapshot when a run starts and ticks when it
              ends), src/crb/server/routes/prevention.py (the routes that read and write the
              chain), src/crb/store/ledger.py (the rows, reviews and packs), src/crb/server/
              factory_state.py (the factory's outcome events)
Tested by:    tests/test_worker_learning.py, tests/test_server_routes_prevention.py
Touch when:   never for a new repository; stream W or K merges (``mechanisms`` is THE seam —
              add their shipped mechanisms, the calibration check and the repository's
              commands); a new source of classes (bind it into ``register_for``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import GENESIS_HASH
from crb.core.playbook import RepoFacts
from crb.core.prevention import (
    AUTO_OFF,
    K_SECTION,
    W_SECTION,
    LearningSnapshot,
    Mechanisms,
    PreventionRecord,
    Register,
    build_register,
    empty_snapshot,
    snapshot,
    switch_state,
    tick,
    verify_records,
)
from crb.server.factory_state import FactoryHome
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.store.ledger import DbLedger, DbReviewLedger
from crb.store.models import Event, Repo

log = logging.getLogger(__name__)

#: The one event action the chain is carried in (a row in docs/API.md#event-vocabulary).
ACTION = "learn.prevention.recorded"
#: How often a tick re-reads and recomputes after a concurrent append on the trace.
TICK_RETRIES = 3


def learn_trace_id(repo: str) -> str:
    """The deterministic system trace every ``learn.*`` event of a repository chains on
    (``sha256("learn:<repo>")[:32]``), so the loop's acts read back in the order they were
    made."""
    return system_trace_id("learn", repo)


class ConcurrentAppend(RuntimeError):
    """Another writer appended to the trace between this store's read of the head and its
    insert: the record would fork the chain (two records on one ``prev_hash``). Roll back
    and re-read — :func:`learning_tick` and the routes retry."""


class EventsPreventionStore:
    """The prevention chain of one repository, in the ``events`` table. ``append`` adds the
    event to the session; the caller commits it with whatever it records."""

    def __init__(self, session: Session, repo: str) -> None:
        self.session = session
        self.repo = repo

    def _last_seq(self) -> int:
        last = self.session.execute(
            select(func.max(Event.seq)).where(Event.trace_id == learn_trace_id(self.repo))
        ).scalar_one_or_none()
        return int(last or 0)

    def records(self) -> list[PreventionRecord]:
        """Every record in ``seq`` order, verified as a chain (``LedgerIntegrityError`` on a
        break or an edited payload)."""
        evs = self.session.execute(
            select(Event)
            .where(Event.trace_id == learn_trace_id(self.repo), Event.action == ACTION)
            .order_by(Event.seq)
        ).scalars()
        out = [PreventionRecord.from_dict(dict(ev.payload_json or {})) for ev in evs]
        verify_records(out)
        return out

    def append(self, record: PreventionRecord) -> PreventionRecord:
        """Chain ``record`` on the head and add its event (not committed here). The event's
        ``seq`` must follow the head this store read; if another writer got there first the
        append is refused with :class:`ConcurrentAppend` (or, if both are in flight, the
        second commit collides on ``uq_events_trace_seq``) — never a forked chain."""
        last_seq = self._last_seq()
        recs = self.records()
        rec = record.chained(recs[-1].row_hash if recs else GENESIS_HASH)
        ev = append_system_event(
            self.session,
            trace_id=learn_trace_id(self.repo),
            action="learn.prevention.recorded",  # a literal: the vocabulary ratchet reads it
            repo=self.repo,
            actor=rec.actor,
            payload=rec.to_dict(),
        )
        if ev.seq != last_seq + 1:
            raise ConcurrentAppend(
                f"the learn trace of {self.repo!r} moved from seq {last_seq} to {ev.seq - 1} "
                "while a record was being chained"
            )
        self.session.flush()
        return rec


def all_prevention_records(session: Session) -> list[PreventionRecord]:
    """Every repository's chain (each verified), for stream S's pooled report."""
    repos = sorted(
        {
            str(r)
            for r in session.execute(select(Event.repo).where(Event.action == ACTION)).scalars()
        }
    )
    out: list[PreventionRecord] = []
    for repo in repos:
        out.extend(EventsPreventionStore(session, repo).records())
    return out


def mechanisms(settings: Any = None, *, rows: Any = (), repo: str = "") -> Mechanisms:
    """THE merge seam for streams W and K: which process mechanisms this build ships. Nothing
    ships on this branch, so the loop can only file items and apply lines until W's formatter
    step and finish gate and K's calibrated budget merge (docs/LEARNING-LOOP.md §7)."""
    del settings, rows, repo
    return Mechanisms()


def base_config(repo_row: Repo | None) -> dict[str, dict[str, Any]]:
    """The team's own explicit keys in the sections the loop may overlay (stream W's
    ``checks``, stream K's ``spend``) — the keys that always win."""
    cfg = dict((repo_row.config_json if repo_row is not None else None) or {})
    out: dict[str, dict[str, Any]] = {}
    for section in (W_SECTION, K_SECTION):
        sec = cfg.get(section)
        if isinstance(sec, Mapping):
            out[section] = dict(sec)
    return out


def repo_facts(config: Mapping[str, Any] | None) -> RepoFacts:
    """What a line may recommend, from configuration only: before stream W merges, the
    declared lint command and its name."""
    cfg = dict(config or {})
    lint = cfg.get("lint")
    lint_cmd = ""
    tools: tuple[str, ...] = ()
    if isinstance(lint, Mapping):
        cmd = lint.get("command")
        if isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd):
            lint_cmd = " ".join(cmd)
        if isinstance(lint.get("name"), str):
            tools = (str(lint["name"]),)
    return RepoFacts(lint_cmd=lint_cmd, tools=tools)


def register_for(
    session: Session,
    factory: sessionmaker[Session],
    home: str | Path,
    repo: str,
    *,
    records: list[PreventionRecord] | None = None,
    repo_row: Repo | None = None,
    settings: Any = None,
) -> Register:
    """The register of ``repo`` from what the store holds: every ledger row, every review,
    the factory's outcome events, and the pack of each belt-5 row."""
    recs = records if records is not None else EventsPreventionStore(session, repo).records()
    row = repo_row if repo_row is not None else session.get(Repo, repo)
    ledger = DbLedger(factory)
    rows = list(ledger.rows(repo=repo))
    reviews = list(DbReviewLedger(factory).records(repo=repo))
    try:
        events = [e.to_dict() for e in FactoryHome(home, repo).events()]
    except Exception as exc:  # an unreadable factory chain must not hide the register
        log.warning("prevention: factory events for %s unreadable: %s", repo, exc)
        events = []
    return build_register(
        rows,
        reviews,
        events,
        recs,
        repo=repo,
        mechanisms=mechanisms(settings, rows=rows, repo=repo),
        base_config=base_config(row),
        packs=ledger.get_pack,
    )


def learning_snapshot(
    factory: sessionmaker[Session], repo: str, params: Mapping[str, Any] | None = None
) -> LearningSnapshot:
    """What one run is given (taken once when it starts): the switch after any opt-out, the
    changes in force, the overlay under the team's keys and the lines."""
    with factory() as s:
        recs = EventsPreventionStore(s, repo).records()
        return snapshot(
            recs, repo=repo, params=params or {}, base_config=base_config(s.get(Repo, repo))
        )


def learning_tick(
    factory: sessionmaker[Session],
    home: str | Path,
    repo: str,
    *,
    settings: Any = None,
    now: str = "",
) -> list[PreventionRecord]:
    """One tick of ``repo``'s loop, committed: nothing when the switch is off; on a
    concurrent append (``uq_events_trace_seq``) re-read and recompute, up to
    :data:`TICK_RETRIES` times. Never raises — a tick that fails is logged, and the run it
    followed keeps its status."""
    for attempt in range(TICK_RETRIES):
        try:
            with factory() as s:
                store = EventsPreventionStore(s, repo)
                recs = store.records()
                if switch_state(recs).auto_apply == AUTO_OFF:
                    return []
                row = s.get(Repo, repo)
                if row is None:
                    return []
                reg = register_for(
                    s, factory, home, repo, records=recs, repo_row=row, settings=settings
                )
                out = tick(
                    reg,
                    recs,
                    now=now,
                    mechanisms=mechanisms(settings, rows=reg.index.rows, repo=repo),
                    base_config=base_config(row),
                    facts=repo_facts(row.config_json),
                )
                appended = [store.append(r) for r in out]
                s.commit()
                return appended
        except (IntegrityError, ConcurrentAppend):
            log.info("prevention: concurrent append on %s; re-reading (%d)", repo, attempt + 1)
            continue
        except Exception as exc:
            log.warning("prevention: tick for %s failed: %s", repo, exc, exc_info=True)
            return []
    log.warning("prevention: tick for %s gave up after %d concurrent appends", repo, TICK_RETRIES)
    return []


def empty_for(repo: str) -> LearningSnapshot:
    """The snapshot a run gets when the chain cannot be read: ``learn: off`` — true."""
    return empty_snapshot(repo)


__all__ = [
    "ACTION",
    "TICK_RETRIES",
    "ConcurrentAppend",
    "EventsPreventionStore",
    "all_prevention_records",
    "base_config",
    "empty_for",
    "learn_trace_id",
    "learning_snapshot",
    "learning_tick",
    "mechanisms",
    "register_for",
    "repo_facts",
]
