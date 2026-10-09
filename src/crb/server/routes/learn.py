"""``/learn/*`` — the learning half of the loop: three derivations, and the three writes
a named person authorises from the report that computed them.

Each read reduces the repo's ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load) with the
matching :mod:`crb.core.learn` derivation and returns its ``to_dict()``:

* ``/learn/refusals`` — protocol rows → candidate guard-corpus lines, every verdict
  ``unsure``; the decisions a named person has already made are served beside them
  (``decisions``, folded from the ``learn.refusal.accepted`` events), and the guard's
  false-positive rate those decisions give, per apparatus and month (``false_positives``);
* ``/learn/strengthen`` — oracle-held cells of the class × size map (routed under the
  repo's latest controls verdict, as ``/capability-map`` does) joined to the latest
  ``oracle.score`` events → ``test.add`` items in the frozen-backlog shape. The
  per-task scores are read from the store's **events** (one ``oracle.score`` per task
  per oracle run; an oracle run's ``counts_json`` keeps only the per-cell roll-up, and
  there is no per-task score table) — the same reader ``/oracle/{repo}`` uses, so the
  two screens can never disagree about a task's strength. Every score carries the
  repo, so the item ids equal what ``crb learn strengthen --oracle <GET /oracle/{repo}>
  --controls <GET /oracle/{repo}/controls>`` derives from the exports;
* ``/learn/remeasure`` — read from the repository's registered readings (ADR-0026 item 2):
  each reading waiting on its look → the commits it still needs in its seeded order, the
  ``POST /runs`` body an operator can queue for them (gold-clean, in this deployment's
  posture, with its test author) and what it costs; each cell with rows and no reading →
  register one first, never a replay.

The three reads are viewer-readable and pure. The three writes (G-532) are
operator-gated and each one carries the **same named-person decision the CLI already
requires** — and carries it as the signed-in operator's identity, never as a field of
the request body, so a decision cannot be filed under somebody else's name:

* ``POST /learn/refusals/accept`` — one group's verdict (``honest`` / ``refuse``)
  appended to this deployment's guard corpus by the same
  :func:`~crb.core.learn.apply_triage` the CLI calls, with provenance; event
  ``learn.refusal.accepted``;
* ``POST /learn/strengthen/register`` — the chosen items registered onto the repo's
  frozen backlog through :class:`~crb.server.factory_state.FactoryHome` (freeze the
  first, **evolve** the rest, so a re-registered item supersedes rather than
  overwrites); event ``learn.strengthen.registered``;
* ``POST /learn/remeasure/queue`` — the plan's own ``POST /runs`` body enqueued for one
  cell whose registered reading waits on its look, through the submit gate ``POST /runs``
  applies (``submit_refusals``) before it is enqueued; refused ``reading_unregistered`` for
  a cell with no such reading, and never for a what-if plan; event ``learn.remeasure.queued``.

Nothing about *which* decision is right moves into the product: the item bodies and the
run bodies are re-derived here from the ledger, never taken from the caller, so a write
can only carry what the report itself computed. See ``docs/LEARNING-LOOP.md``.

Navigation
----------
What it is:   The ``/learn/*`` route module — the learning loop's three reads and the three
              operator-gated writes they hand off to.
What it does: Reduces the repo's rows with the matching ``crb.core.learn`` derivation and
              returns its ``to_dict``; joins the latest ``oracle.score`` event per task so
              the strengthening items carry the same strengths ``/oracle/{repo}`` shows;
              and writes what a named operator accepts — a corpus line, the strengthening
              items, the re-measurement runs — re-deriving each body here so the caller
              can choose but never compose; a cell whose queued runs are unfinished is
              refused and served with those runs, so money is never spent twice (P-182); a
              cell with no request (no commit left it has not graded) is refused with the
              plan's own reason, so nothing is queued that would repeat a commit.
How:          ``DbLedger.rows(repo)`` → ``triage_refusals`` | ``build_capability_map`` +
              ``strengthening_backlog`` (scores from the events table) | ``remeasure_plan``;
              the writes go through ``apply_triage`` / ``FactoryHome.register_*`` (under
              ``FactoryHome.registration``) / ``new_run`` + ``stage_queued``, each inside
              ``_learn_step``: the lock (which fails closed), the side effect once, and the
              event on the repo's ``learn:<repo>`` trace, retried on a lost ``seq`` race
              (P-420, P-429, P-431); the queue's in-flight guard is read under the events
              write lock too (``lock_event_writes``), so the check and the act are one step.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/learn.py (the three derivations and ``apply_triage`` — the same
              writer the CLI uses), src/crb/server/routes/oracle.py (``SCORE_ACTIONS``,
              ``latest_controls_verdict``), src/crb/server/routes/capability.py
              (``rows_for_arm`` — a report and its write read one checks arm, ADR-0024),
              src/crb/server/app.py (``CsrfMiddleware`` — every write is bound to the
              session's CSRF token before it reaches a route), src/crb/server/factory_state.py
              (``FactoryHome.register_backlog`` / ``register_evolution`` — the one
              registration path), src/crb/server/routes/runs.py (``new_run``,
              ``submit_refusals``, ``require_jobs``, ``append_system_event`` — how a run is
              built, refused at submit, queued, and how an event is chained),
              src/crb/store/events.py (``lock_event_writes``), src/crb/store/jobs.py
              (``stage_queued``), src/crb/server/routes/factory.py
              (``_refuse_if_run_active``, ``_next_item_id`` — the backlog write's own
              guards, shared rather than copied), src/crb/cli/commands/learn.py (the CLI
              twin), docs/LEARNING-LOOP.md (what loops mechanically, what a human decides),
              ui/src/screens/Learn (the screen that offers the three actions)
Tested by:    tests/test_server_routes_learn.py, tests/test_cli_learn.py
Touch when:   never for a new repository — its rows and tasks are read as they are; adding a
              derivation means a function in src/crb/core/learn.py, a route here, a CLI verb,
              and a section in
              docs/LEARNING-LOOP.md; a new event action needs its row in
              docs/API.md#event-vocabulary first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from crb.core.capability import PROJECTIONS, build_capability_map
from crb.core.learn import (
    REASON_PENDING,
    LearnError,
    RefusalDecision,
    RefusalReport,
    RemeasurePlan,
    StrengthenBacklog,
    StrengthenItem,
    TriageApplied,
    apply_triage,
    guard_false_positives,
    has_line_break,
    load_oracle_scores,
    remeasure_plan,
    strengthening_backlog,
    triage_refusals,
)
from crb.core.routing import DEFAULT_POLICY
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.core.version import APPARATUS_VERSION
from crb.factory.backlog import Backlog, BacklogError, BacklogItem
from crb.factory.readiness import ROUTE_BUILD, assess
from crb.factory.testfirst import canonical_model
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.posture_view import deployment_posture_class
from crb.server.prevention_state import current_checks_arm
from crb.server.routes.capability import (
    CHECKS_CURRENT,
    POSTURE_DEPLOYMENT,
    filter_posture,
    rows_for_apparatus,
    rows_for_arm,
    rows_for_mode,
)
from crb.server.routes.factory import _next_item_id, _refuse_if_run_active
from crb.server.routes.oracle import SCORE_ACTIONS, latest_controls_verdict, oracle_by_task
from crb.server.routes.readings import reading_book, rows_on_standard_arms
from crb.server.routes.repos import get_repo_or_404
from crb.server.routes.runs import (
    append_system_event,
    new_run,
    require_jobs,
    submit_refusals,
    system_trace_id,
)
from crb.server.schemas import TERMINAL_STATUSES, RunCreateRequest
from crb.store.events import lock_event_writes
from crb.store.jobs import stage_queued
from crb.store.ledger import DbLedger
from crb.store.models import Event, Repo, Run, Task

router = APIRouter(tags=["learn"])
_ERR = {"model": ErrorEnvelope}


def _scores(session: Session, repo: str) -> list[dict[str, Any]]:
    """The latest ``oracle.score`` payload per task, from the store's events (the
    per-task scores live nowhere else: ``runs.counts_json`` is the cell roll-up).
    Events are in insertion order, so the last one per task is the latest oracle
    run's. ``repo`` is stamped on every payload — the item id is
    ``sha(cell, repo, task)`` and must equal the CLI's over the same export."""
    latest: dict[str, dict[str, Any]] = {}
    for ev in session.execute(
        select(Event)
        .where(Event.repo == repo, Event.stage == "oracle", Event.action.in_(SCORE_ACTIONS))
        .order_by(Event.id)
    ).scalars():
        payload = dict(ev.payload_json or {})
        tid = str(ev.task_id or payload.get("task_id") or "")
        if tid:
            payload["task_id"] = tid
            payload.setdefault("repo", repo)
            latest[tid] = payload
    return [latest[k] for k in sorted(latest)]


def _subjects(session: Session, repo: str) -> dict[str, str]:
    """``task_id → commit subject`` so a strengthening item reads as a sentence."""
    return {
        t.task_id: t.subject
        for t in session.execute(select(Task).where(Task.repo == repo)).scalars()
    }


#: The event actions the three writes record. Every one is a row in
#: ``docs/API.md#event-vocabulary`` (``tests/test_event_vocabulary.py`` fails otherwise).
#:
#: The emit call sites below write these as LITERALS rather than as these names. The
#: vocabulary walker reads ``action=`` at the call site and cannot follow a constant, so a
#: name there would hide the action from the table's ratchet — and a documented action
#: nothing emits is a consumer waiting for an event that never comes. The pair is pinned
#: end to end instead: ``tests/test_server_routes_learn.py`` posts each write and reads the
#: event back by the literal, through the readers below, which use these names.
ACTION_REFUSAL_ACCEPTED = "learn.refusal.accepted"
ACTION_STRENGTHEN_REGISTERED = "learn.strengthen.registered"
ACTION_REMEASURE_QUEUED = "learn.remeasure.queued"


def learn_trace_id(repo: str) -> str:
    """The deterministic system trace every ``learn.*`` event of a repository chains on,
    so the decisions read back in the order they were made (``sha256("learn:<repo>")``)."""
    return system_trace_id("learn", repo)


def corpus_dir(settings: Any) -> Path:
    """Where an accepted guard-corpus line is appended: ``CRB_LEARN_CORPUS_DIR`` when the
    deployment sets one (a source checkout points it at its own ``tests/fixtures``, so the
    line binds ``tests/test_builders_guard_corpus.py`` directly), else
    ``<home>/learn/corpus`` — this deployment's own record of what its operators decided,
    served back by ``GET /learn/refusals``'s ``decisions``."""
    raw = str(getattr(settings, "learn_corpus_dir", "") or "").strip()
    return Path(raw).expanduser() if raw else Path(settings.home) / "learn" / "corpus"


def accepted_decisions(session: Session, repo: str) -> list[dict[str, Any]]:
    """Every refusal decision a named person has made for this repo, oldest first, folded
    from the ``learn.refusal.accepted`` events — no second ledger: the event IS the record,
    and the actor on it is who decided."""
    out: list[dict[str, Any]] = []
    for ev in session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == ACTION_REFUSAL_ACCEPTED)
        .order_by(Event.id)
    ).scalars():
        p = dict(ev.payload_json or {})
        out.append(
            {
                "group_id": str(p.get("group_id", "")),
                "verdict": str(p.get("verdict", "")),
                # the name that went into the corpus comment, and the account behind it
                "decided_by": str(p.get("decided_by") or ev.actor or ""),
                "decided_by_id": str(ev.actor or ""),
                "decided_at": str(ev.timestamp or ""),
                "note": str(p.get("note", "")),
                "lines": [str(x) for x in (p.get("lines") or [])],
                "already_present": bool(p.get("already_present", False)),
            }
        )
    return out


# ---------------------------------------------------------------------------
# The derivations, shared by the read and the write of each report: a write can only
# carry what the report itself computed, so there is exactly one place each is derived.
# ---------------------------------------------------------------------------


def derive_refusals(factory: SessionFactoryDep, repo: str) -> RefusalReport:
    """The repo's refusal triage — every verdict ``unsure``."""
    return triage_refusals(list(DbLedger(factory).rows(repo=repo)))


def derive_strengthen(
    db: Session, factory: SessionFactoryDep, repo: str, *, by: str, since: str, settings: object
) -> StrengthenBacklog:
    """The repo's strengthening backlog (``StrengthenBacklog``) under the projection ``by``,
    routed on the same policy, latest controls verdict, per-task oracle scores and
    deployment posture class the capability map and the delivery gate read."""
    if by not in PROJECTIONS:
        raise ApiError(
            422,
            "validation_error",
            f"unknown projection {by!r}",
            detail={"allowed": sorted(PROJECTIONS)},
        )
    # the repository's own checks arm: a cell never pools two arms (ADR-0024)
    every = list(DbLedger(factory).rows(repo=repo))
    # the map's and the delivery gate's own reading: sighted rows and every certifying arm's
    # (P-338), on the current apparatus, measured HERE — never an imported row (EI-2; P-728)
    current = rows_for_apparatus(rows_for_mode(every, "sighted"), "current")
    rows = rows_for_arm(factory, repo, current, CHECKS_CURRENT)
    # the deployment's posture class: a reading licenses only the rows it counted on (P-319)
    rows = filter_posture(db, repo, rows, POSTURE_DEPLOYMENT, settings).rows
    # one reading: the global class set, each cell on its standard arm (ADR-0025 item 1,
    # ADR-0026) — never two pooled
    book = reading_book(db, repo, every)
    rows = rows_on_standard_arms(
        [r for r in rows if r.taxonomy in ("", GLOBAL_CLASS_SET)],
        PROJECTIONS[by],
        book,
    )
    cmap = build_capability_map(
        rows,
        projection=PROJECTIONS[by],
        policy=DEFAULT_POLICY,
        controls=latest_controls_verdict(db, repo),
        # the strength the map routes under — each task's oracle score — so Learn and the
        # map never disagree about why a cell is held (P-426)
        oracle_by_task=oracle_by_task(db, repo),
        readings=book,
    )
    return strengthening_backlog(
        cmap,
        load_oracle_scores(_scores(db, repo)),
        policy=DEFAULT_POLICY,
        subjects=_subjects(db, repo),
        since=since,
    )


def deployment_author_model(settings: object) -> str:
    """The canonical model of this deployment's test author (``CRB_FACTORY__TEST_AUTHOR``,
    ``builder:model[:provider]``) — the author a queued ``S1`` replay's rows name — or ``""``
    when none is configured. The worker stamps the same (``canonical_model``)."""
    factory_cfg = getattr(settings, "factory", None)
    raw = str(getattr(factory_cfg, "test_author", "") or "").strip()
    parts = raw.split(":")
    if not raw or raw.lower() == "none" or len(parts) < 2 or not parts[1]:
        return ""
    return canonical_model(parts[1]) or parts[1]


def derive_remeasure(
    db: Session,
    factory: SessionFactoryDep,
    repo: str,
    *,
    apparatus: str,
    settings: object,
    posture_class: str | None = None,
) -> RemeasurePlan:
    """The repo's re-measurement plan (``RemeasurePlan``) against ``apparatus``, read from its
    registered readings (ADR-0026 item 2): a top-up names only the commits a reading still
    needs; a cell with no reading is offered registration, never a replay (P-602).
    ``posture_class`` is the caller's own when its settings are not the API's (the worker's
    idle pass, ``Worker._deployment_posture_class``); else the API settings decide (P-672)."""
    every = list(DbLedger(factory).rows(repo=repo))
    # the arm the repository grades under now: a cell never pools two arms (ADR-0024)
    rows = rows_for_arm(factory, repo, every, CHECKS_CURRENT)
    checks = current_checks_arm(factory, repo)
    # every reading evaluated over every row (the hierarchy reads its arms together); the
    # plan reads those of this checks arm and the global class set — the rows it plans on
    book = reading_book(db, repo, every)
    outcomes = [
        o
        for o in book.outcomes
        if o.reading.checks_arm == checks and o.reading.taxonomy in ("", GLOBAL_CLASS_SET)
    ]
    # each task's CURRENT label and whether it is gold-clean: a pending commit relabelled
    # out of the cell, or no longer gold-clean (the worker skips it), is left out and named
    tasks = list(db.execute(select(Task).where(Task.repo == repo)).scalars())
    labels = {str(t.task_id): (str(t.capability_class or ""), str(t.size or "")) for t in tasks}
    gold = [str(t.task_id) for t in tasks if t.gold_clean]
    return remeasure_plan(
        rows,
        readings=outcomes,
        current_apparatus=apparatus,
        policy=DEFAULT_POLICY,
        task_labels=labels,
        gold_clean_tasks=gold,
        # a replay writes the arm the reading reads only with its test author, in its posture
        s1_author_model=deployment_author_model(settings),
        deployment_posture=(
            posture_class
            if posture_class is not None
            else deployment_posture_class(settings, db.get(Repo, repo))
        ),
    )


#: Attempts at a Learn write's one serialised step before a ``seq`` conflict on the shared
#: ``learn:<repo>`` trace is answered 409 (P-420, P-431).
_QUEUE_ATTEMPTS = 3


class LearnLockNotHeld(RuntimeError):
    """The Learn write lock could not be taken because a transaction was already open on
    the session: the write is refused rather than run unserialised (P-429)."""


def _lock_learn_trace(db: Session) -> None:
    """Serialise a Learn write's check, side effect and event for the rest of this
    transaction (P-420, P-431): SQLite takes its write lock now (``BEGIN IMMEDIATE`` —
    pysqlite defers BEGIN until the first write, so this is safe after the route's reads),
    PostgreSQL a transaction-scoped advisory lock (id 7337 — one id per purpose, see
    ``crb.store.jobs``). A rollback or commit releases it.

    Fails closed (P-429): when a transaction is already open, ``BEGIN IMMEDIATE`` cannot
    run, and its error is no documented proof that this session holds the write lock (a
    deferred ``BEGIN`` holds none). SQLite does take the lock before it raises — its
    ``OP_Transaction`` step runs before ``OP_AutoCommit``'s error — so the old helper held
    it by accident; failing closed removes the dependence on that order.
    :class:`LearnLockNotHeld` is raised and nothing is written."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        try:
            db.execute(text("BEGIN IMMEDIATE"))
        except OperationalError as exc:
            if "within a transaction" not in str(exc):
                raise
            raise LearnLockNotHeld(
                "the Learn write lock was not taken: a transaction was already open on this "
                "session, so the write would run unserialised — nothing was written"
            ) from exc
    elif dialect == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(7337)"))


def _learn_step(
    db: Session,
    repo: str,
    *,
    action: str,
    actor: str,
    stage: Callable[[], dict[str, Any]],
    exhausted: Callable[[], ApiError],
) -> dict[str, Any]:
    """The ONE way an event reaches the shared ``learn:<repo>`` trace from a Learn write:
    take the lock, ``stage`` the write (its check and its side effect; it returns the
    event's payload), append the event and commit — as one serialised step (P-420, P-431).

    Every Learn write appends on the same trace, and ``append_system_event`` reads the last
    ``seq`` before it inserts the next, so a write can lose that race and its commit is
    refused by the unique index. The step is then rolled back and taken again, up to
    :data:`_QUEUE_ATTEMPTS` times, and ``exhausted()`` is raised after the last. ``stage``
    runs on every attempt: a write whose side effect lives outside the database (a corpus
    line, a backlog file) memoises it, so a retry re-appends the event and never repeats
    the file write; a write whose side effect is in the transaction (the queued runs)
    stages it again. An error ``stage`` raises rolls the attempt back and propagates."""
    for _attempt in range(_QUEUE_ATTEMPTS):
        _lock_learn_trace(db)
        try:
            payload = stage()
        except BaseException:
            db.rollback()
            raise
        append_system_event(
            db,
            trace_id=learn_trace_id(repo),
            action=action,
            repo=repo,
            actor=actor,
            payload=payload,
        )
        try:
            db.commit()
            return payload
        except IntegrityError:
            # another Learn write took this ``seq`` on the shared trace: nothing of this
            # attempt's transaction was written, so it is taken again on fresh rows
            db.rollback()
    raise exhausted() from None


def in_flight_runs(db: Session, repo: str, *, cell: str, mode: str, apparatus: str) -> list[str]:
    """The runs an earlier ``learn.remeasure.queued`` queued for this (cell, mode, apparatus)
    that have not finished. The plan is derived from graded rows only, so it still holds a
    cell whose runs are queued or running; this is what keeps the one write that spends
    money from spending the same estimate twice (a double click, or two operators)."""
    queued: list[str] = []
    for ev in db.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == ACTION_REMEASURE_QUEUED)
        .order_by(Event.id)
    ).scalars():
        p = dict(ev.payload_json or {})
        if (p.get("cell"), p.get("mode"), p.get("apparatus")) == (cell, mode, apparatus):
            queued.extend(str(x) for x in (p.get("run_ids") or []))
    if not queued:
        return []
    return sorted(
        db.execute(
            select(Run.id).where(Run.id.in_(queued), Run.status.not_in(TERMINAL_STATUSES))
        ).scalars()
    )


@router.get(
    "/learn/refusals",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="Protocol rows triaged into candidate guard-corpus lines (every verdict 'unsure')",
)
def learn_refusals(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    # Every verdict comes back "unsure" by design: the API proposes, a human decides. What
    # a person HAS decided is served beside the groups, with their name and the line.
    report = derive_refusals(factory, repo)
    decisions = accepted_decisions(db, repo)
    return {
        "repo": repo,
        **report.to_dict(),
        "decisions": decisions,
        # the guard's false-positive rate per apparatus and month, from those decisions: a
        # bound while any row is undecided, never a verdict nobody gave (G-536)
        "false_positives": guard_false_positives(report, decisions).to_dict(),
    }


@router.get(
    "/learn/strengthen",
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Oracle-held cells → 'strengthen the target tests' items (frozen-backlog shape)",
)
def learn_strengthen(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    *,
    repo: str = Query(min_length=1, max_length=64),
    by: str = Query(default="class_size", max_length=32),
    since: str = Query(default="", max_length=32),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    backlog = derive_strengthen(db, factory, repo, by=by, since=since, settings=settings)
    return {"repo": repo, "projection": by, **backlog.to_dict()}


@router.get(
    "/learn/remeasure",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="Cells short of the first look, stale or thin → n needed, cost, POST /runs bodies (nothing queued)",
)
def learn_remeasure(  # noqa: PLR0917 — FastAPI dependencies + query
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
    apparatus: str = Query(default=APPARATUS_VERSION, max_length=32),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    body = derive_remeasure(db, factory, repo, apparatus=apparatus, settings=settings).to_dict()
    # beside each cell, the runs already queued for it and not finished: the page shows them
    # in place of the Queue control. A what-if plan queues nothing, so it has none.
    for c in body["cells"]:
        c["in_flight_run_ids"] = (
            in_flight_runs(db, repo, cell=str(c["label"]), mode=str(c["mode"]), apparatus=apparatus)
            if apparatus == APPARATUS_VERSION
            else []
        )
    return {"repo": repo, **body}


# ===========================================================================
# The three writes (G-532) — each one a named operator's decision, recorded
# ===========================================================================
#
# Two rules hold across all three, and both are enforced by construction rather than by
# review. (1) **The decider is the session, not the body.** ``decided_by`` is not a field
# any request carries; it is ``operator.id``, so a decision can never be filed under
# somebody else's name — the poka-yoke the CLI can only ask for (``--apply`` needs
# ``decided_by`` in the file, and a file can say anything). (2) **The caller chooses, the
# product composes.** Every body the write acts on — the corpus line, the backlog item,
# the ``POST /runs`` request — is re-derived here from the ledger by the same function the
# read uses, so a request can only name what the report computed, never supply it. The one
# free text that reaches a corpus line, a ``command`` completing an example the recorder
# cut, is refused unless the class is truncated and the command continues that example.


class RefusalAcceptIn(BaseModel):
    """One refusal class's verdict. ``command`` completes a class whose every recorded
    example was cut by the recorder's cap, and must continue that cut example —
    ``apply_triage`` refuses it for any other class, so it can never replace the line the
    report computed; ``prefix`` labels a refusal whose own guard
    family the refused corpus does not take (a ``tamper`` is belt 1's, never a shell
    line). There is deliberately no ``decided_by``: the signed-in operator is the decider."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=64)
    verdict: Literal["honest", "refuse"]
    note: str = Field(default="", max_length=400)
    command: str = Field(default="", max_length=2000)
    prefix: str = Field(default="", max_length=32)

    @field_validator("note")
    @classmethod
    def _note_is_one_line(cls, v: str) -> str:
        """The note becomes a provenance COMMENT in a line-oriented corpus file: a line break
        would end the comment and write the rest as a corpus line nobody decided (P-161)."""
        if has_line_break(v):
            raise ValueError("a note is one line: it is written into the corpus as a comment")
        return v


class RefusalAcceptOut(BaseModel):
    """What was written, in the words the screen repeats back: who decided, which lines
    landed in which corpus file, and what was already there."""

    repo: str
    group_id: str
    verdict: str
    decided_by: str
    honest_added: list[str]
    refused_added: list[str]
    skipped: list[str]
    already_present: bool
    corpus_dir: str
    honest_path: str
    refused_path: str


class RegisteredItemOut(BaseModel):
    """One strengthening item as it landed: its id (a fresh one when the item was
    registered before), the item it supersedes, and whether it froze the first backlog
    or evolved the frozen one."""

    item_id: str
    supersedes: str
    how: Literal["frozen", "evolved"]


class StrengthenRegisterIn(BaseModel):
    """Which strengthening items to register. ``by`` / ``since`` must match the report the
    ids were read from, because the ids are ``sha(cell, repo, task)`` over that projection."""

    model_config = ConfigDict(extra="forbid")

    item_ids: list[str] = Field(min_length=1, max_length=50)
    by: str = Field(default="class_size", max_length=32)
    since: str = Field(default="", max_length=32)


class StrengthenRegisterOut(BaseModel):
    """The registration, and the backlog record it moved."""

    repo: str
    registered: list[RegisteredItemOut]
    backlog_hash: str
    evolutions_hash: str


class RemeasureQueueIn(BaseModel):
    """Which cell of the plan to queue. The plan holds one entry per (cell, mode) — sighted
    and blind are never pooled — so ``mode`` is required when a label carries both."""

    model_config = ConfigDict(extra="forbid")

    cell: str = Field(min_length=1, max_length=128)
    mode: str = Field(default="", max_length=16)
    apparatus: str = Field(default=APPARATUS_VERSION, max_length=32)


class RemeasureQueueOut(BaseModel):
    """The runs that were queued and what the plan said they would cost. ``cost_known``
    false means no row of the cell recorded a cost: the estimate is not a number to trust,
    and it is never shown as zero."""

    repo: str
    cell: str
    mode: str
    run_ids: list[str]
    n_needed: int
    est_cost_usd: float
    cost_known: bool


def _backlog_item(item: StrengthenItem) -> BacklogItem:
    """A derived strengthening item as the factory's own ``BacklogItem``, gated by the
    Definition-of-Ready exactly as ``crb learn strengthen`` gates its file output: an item
    that would not reach ``build`` is our defect, never the operator's, so it is refused
    here rather than registered and then blocked."""
    try:
        out = BacklogItem.from_dict(item.to_dict())
    except (BacklogError, ValueError) as exc:  # pragma: no cover - a derivation defect
        raise ApiError(
            422, "validation_error", f"item {item.id!r} does not validate: {exc}"
        ) from exc
    ready = assess(out)
    if not ready.ready or ready.route_hint != ROUTE_BUILD:
        raise ApiError(
            422,
            "validation_error",
            f"strengthening item {out.id!r} would not pass the Definition of Ready "
            f"({ready.route_hint}) — it is not registered",
        )
    return out


def _latest_in_lineage(backlog: Backlog, item_id: str) -> str:
    """The id at the END of ``item_id``'s supersession chain. An evolution must supersede
    the latest item, never one already superseded, so re-registering a strengthening item
    for the third time chains onto the second."""
    superseded_by = backlog.superseded_by()
    seen: set[str] = set()
    current = item_id
    while current in superseded_by and current not in seen:
        seen.add(current)
        current = superseded_by[current]
    return current


_How = Literal["frozen", "evolved"]


def _plan_registration(
    home: FactoryHome, items: list[BacklogItem]
) -> list[tuple[BacklogItem, _How]]:
    """Try every item on the backlog IN MEMORY, in order, before any is written (P-432):
    freeze the first when there is none, evolve the rest, and give an id already on the
    record a NEW id superseding the latest of its lineage. The record's own rules run on
    each step (:meth:`Backlog.freeze`, :meth:`Backlog.evolve`), so an item the record would
    refuse is refused here — **409 ``register_refused``** with nothing registered — and a
    refusal can never leave the items before it on the backlog with no Learn event."""
    planned: list[tuple[BacklogItem, _How]] = []
    trying = items[0].id if items else ""
    try:
        current = home.load_backlog()
        for item in items:
            trying = item.id
            if current is None:
                current = Backlog(items=(item,), repo=home.repo).freeze()
                planned.append((item, "frozen"))
                continue
            to_register = item
            if current.get(item.id) is not None:
                to_register = replace(
                    item,
                    id=_next_item_id(item.id, [i.id for i in current.all_items()]),
                    supersedes=_latest_in_lineage(current, item.id),
                )
            current = current.evolve(to_register)
            planned.append((to_register, "evolved"))
    except (BacklogError, ValueError) as exc:
        raise ApiError(
            409,
            "register_refused",
            f"item {trying!r} would not be accepted by the backlog record: {exc} — nothing "
            "was registered",
            detail={"registered": []},
        ) from exc
    return planned


def _register_items(
    home: FactoryHome,
    planned: list[tuple[BacklogItem, _How]],
    registered: list[RegisteredItemOut],
    *,
    actor: str,
) -> tuple[Backlog | None, dict[str, str] | None]:
    """Write the items :func:`_plan_registration` tried, in order, appending each to
    ``registered`` as it lands. Returns the backlog after the last write and, when the
    record refused an item part way, ``{item_id, reason}`` for it: the trial passed, and the
    caller holds the registration lock (EI-7) from the trial to here, so only a write the
    record itself refuses, or a path outside that lock, can refuse an item part way. The
    caller records what landed on the Learn trace before it answers 409 (P-432). A freeze
    never replaces a backlog another path froze in the meantime. The lock is re-entrant, so
    taking it here again costs nothing under the caller's and keeps every load and write of
    this function inside it."""
    backlog: Backlog | None = None
    with home.registration():
        for item, how in planned:
            try:
                if how == "frozen":
                    if home.load_backlog() is not None:
                        raise BacklogError(
                            "another path froze a backlog for this repository after this "
                            "request read the record"
                        )
                    backlog = home.register_backlog([item], actor=actor)
                else:
                    backlog = home.register_evolution(item, actor=actor)
            except (BacklogError, ValueError, LookupError) as exc:
                return backlog, {"item_id": item.id, "reason": str(exc)}
            registered.append(
                RegisteredItemOut(item_id=item.id, supersedes=item.supersedes, how=how)
            )
    return backlog, None


@router.post(
    "/learn/refusals/accept",
    response_model=RefusalAcceptOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Accept one refusal class as honest or refused: the line is appended to the guard corpus with the operator's name",
)
def accept_refusal(  # noqa: PLR0917 — FastAPI dependencies + body + query
    body: RefusalAcceptIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> RefusalAcceptOut:
    """The write behind the verdict the report never makes (G-532).

    The decision is applied by :func:`crb.core.learn.apply_triage` — the same writer
    ``crb learn refusals --apply`` calls — so the line, its provenance comment and every
    refusal it validates (an unknown class, a class whose examples were all truncated and
    no ``command`` supplied, a line that contradicts the other corpus, a ``tamper``
    offered as a shell refusal) are identical from the API and from the host. **404** for
    a class that is not in the current report (re-read ``GET /learn/refusals``), **422
    ``refusal_refused``** for a decision the writer declines, **409
    ``corpus_not_writable``** when the corpus directory cannot be appended to.

    The file is appended BEFORE the event is recorded, and ``apply_triage`` is idempotent,
    so a crash between the two leaves a written line that the next attempt reports as
    ``already_present`` — never an event claiming a line nothing wrote. The append and its
    event are one serialised step (:func:`_learn_step`, P-431): a lost race for the trace's
    next ``seq`` records the event again without appending the line again, and **409
    ``learn_concurrent_write``** (``detail.lines``) says what was written when other Learn
    writes won that race three times.
    """
    get_repo_or_404(db, repo)
    report = derive_refusals(factory, repo)
    group = report.get(body.group_id)
    if group is None:
        raise ApiError(
            404,
            "not_found",
            f"no refusal class {body.group_id!r} in {repo!r}'s current report — re-read "
            "GET /learn/refusals (a class's id is (guard, reason, command shape))",
        )
    try:
        decision = RefusalDecision(
            group_id=body.group_id,
            verdict=body.verdict,
            note=body.note,
            command=body.command,
            prefix=body.prefix,
        )
    except LearnError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    directory = corpus_dir(settings)
    # The corpus line leaves the product: it is appended to a text file that lives in a
    # repository, where nobody can resolve an account id. So the provenance comment names
    # the person (their display name) and the EVENT carries the account id as its actor —
    # the pair is what makes a line attributable without putting an id in somebody's diff.
    decider = (operator.display_name or operator.id).strip()
    written: list[TriageApplied] = []

    def stage() -> dict[str, Any]:
        # the corpus line is appended ONCE, under the lock; a retry after a lost ``seq``
        # race records the same decision again and never re-appends the line (P-431)
        if not written:
            try:
                written.append(
                    apply_triage([decision], report, corpus_dir=directory, decided_by=decider)
                )
            except LearnError as exc:
                raise ApiError(
                    422, "refusal_refused", str(exc), detail={"group_id": body.group_id}
                ) from exc
            except OSError as exc:
                raise ApiError(
                    409,
                    "corpus_not_writable",
                    f"the guard corpus at {directory} could not be written "
                    f"({exc.strerror or exc}); set CRB_LEARN_CORPUS_DIR to a directory this "
                    "deployment may append to",
                ) from exc
        done = written[0]
        lines = [*done.honest_added, *done.refused_added]
        return {
            "group_id": body.group_id,
            "verdict": body.verdict,
            "decided_by": decider,
            "note": body.note,
            "guard": group.prefix,
            "reason": group.reason,
            "shape": group.shape,
            "rows": group.n,
            "lines": lines,
            "already_present": not lines and bool(done.skipped),
            "corpus_dir": str(directory),
        }

    payload = _learn_step(
        db,
        repo,
        action="learn.refusal.accepted",  # a literal on purpose: see the constants above
        actor=operator.id,
        stage=stage,
        exhausted=lambda: ApiError(
            409,
            "learn_concurrent_write",
            "other Learn writes kept moving this repository's trace through "
            f"{_QUEUE_ATTEMPTS} attempts: the line was appended to the corpus but the "
            "decision was not recorded — decide again to record it",
            detail={"lines": [*written[0].honest_added, *written[0].refused_added]},
        ),
    )
    applied = written[0]
    already = bool(payload["already_present"])
    return RefusalAcceptOut(
        repo=repo,
        group_id=body.group_id,
        verdict=body.verdict,
        decided_by=decider,
        honest_added=list(applied.honest_added),
        refused_added=list(applied.refused_added),
        skipped=list(applied.skipped),
        already_present=already,
        corpus_dir=str(directory),
        honest_path=applied.honest_path,
        refused_path=applied.refused_path,
    )


@router.post(
    "/learn/strengthen/register",
    response_model=StrengthenRegisterOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register chosen strengthening items onto the repo's frozen backlog (an evolution supersedes; nothing is overwritten)",
)
def register_strengthening(  # noqa: PLR0917 — FastAPI dependencies + body + query
    body: StrengthenRegisterIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> StrengthenRegisterOut:
    """The hand-off the operator used to make by pasting JSON into
    ``POST /factory/{repo}/backlog`` (G-532).

    The items are re-derived from the ledger, so the body names ids and nothing else. They
    are registered through the one registration path the API and the intake listener
    already use (:class:`~crb.server.factory_state.FactoryHome`): the first item freezes a
    backlog, the rest are **evolutions**, and an item id already on the record is
    registered as a NEW id superseding the latest of its lineage — a frozen record never
    mutates (F32), so re-registering after a re-score chains rather than overwrites. Every
    item lands on the factory's own item chain as ``backlog.frozen`` / ``backlog.evolved``
    besides the ``learn.strengthen.registered`` event this route records.

    **409 ``factory_run_active``** while a run is queued or running (the backlog it
    verifies against cannot change under it), **422** for an unknown id or an item that
    would not pass the Definition of Ready. The registration and its event are one
    serialised step (:func:`_learn_step`, P-431): a lost race for the trace's next ``seq``
    records the event again without registering again, and **409
    ``learn_concurrent_write``** (``detail.registered``) names what landed when other Learn
    writes won that race three times.

    **409 ``register_refused``** (``detail.registered``) when the backlog record refuses an
    item (P-432). Every item is tried on the record in memory before any is written, so a
    refusal there registers nothing (``registered`` is empty). The trial and the writes are
    one step under the registration lock (EI-7), so only the record refusing a write itself
    can refuse an item part way:
    the items before it are then on the backlog, and the ``learn.strengthen.registered``
    event names exactly those, with ``refused`` ``{item_id, reason}``, before the 409.
    """
    get_repo_or_404(db, repo)
    _refuse_if_run_active(db, repo)  # early, before the derivation; again under the lock
    derived = derive_strengthen(db, factory, repo, by=body.by, since=body.since, settings=settings)
    by_id = {i.id: i for i in derived.items}
    chosen = list(dict.fromkeys(body.item_ids))  # the caller's order, each id once
    unknown = [i for i in chosen if i not in by_id]
    if unknown:
        raise ApiError(
            422,
            "validation_error",
            f"{len(unknown)} item id(s) are not in this repository's current strengthening "
            "report — re-read GET /learn/strengthen with the same by / since",
            detail={"unknown": unknown, "available": sorted(by_id)},
        )
    # every item is validated and DoR-gated BEFORE anything is registered, so the only
    # failure left in the loop is the record's own (and it names what already landed)
    items = [_backlog_item(by_id[i]) for i in chosen]
    home = FactoryHome(settings.home, repo)
    registered: list[RegisteredItemOut] = []
    done: list[tuple[Backlog | None, dict[str, str] | None]] = []

    def stage() -> dict[str, Any]:
        # the backlog is frozen or evolved ONCE, under the lock; a retry after a lost
        # ``seq`` race records the same registration again and never registers a second
        # item superseding the first (P-431). Every item is tried in memory first, so the
        # record refuses before anything is written (P-432)
        if not done:
            _refuse_if_run_active(db, repo)
            # one locked read-modify-write from the trial's load to the last pointer write
            # (EI-7): a second registration waits, then sees this one's freeze and evolves
            # onto it — never a second freeze that replaces the first
            with home.registration():
                planned = _plan_registration(home, items)
                done.append(_register_items(home, planned, registered, actor=operator.id))
        backlog, refused = done[0]
        if backlog is None:  # the record refused the first write: nothing landed
            assert refused is not None
            raise ApiError(
                409,
                "register_refused",
                f"item {refused['item_id']!r} was not registered: {refused['reason']} — "
                "nothing was registered",
                detail={"registered": []},
            )
        payload: dict[str, Any] = {
            "projection": body.by,
            "since": body.since,
            "items": [r.model_dump() for r in registered],
            "backlog_hash": backlog.backlog_hash,
            "evolutions_hash": backlog.evolutions_hash,
        }
        if refused is not None:
            payload["refused"] = refused
        return payload

    _learn_step(
        db,
        repo,
        action="learn.strengthen.registered",  # a literal on purpose: see the constants above
        actor=operator.id,
        stage=stage,
        exhausted=lambda: ApiError(
            409,
            "learn_concurrent_write",
            "other Learn writes kept moving this repository's trace through "
            f"{_QUEUE_ATTEMPTS} attempts: the items are on the backlog but the registration "
            "was not recorded on the Learn trace — the backlog's own chain records them",
            detail={"registered": [r.item_id for r in registered]},
        ),
    )
    final, refused = done[0]
    assert final is not None  # a write that landed nothing raised inside the step
    if refused is not None:
        raise ApiError(
            409,
            "register_refused",
            f"item {refused['item_id']!r} was not registered: {refused['reason']} — the "
            "items before it are on the backlog and recorded on the Learn trace",
            detail={"registered": [r.item_id for r in registered]},
        )
    return StrengthenRegisterOut(
        repo=repo,
        registered=registered,
        backlog_hash=final.backlog_hash,
        evolutions_hash=final.evolutions_hash,
    )


@router.post(
    "/learn/remeasure/queue",
    response_model=RemeasureQueueOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 503: _ERR},
    summary="Queue the re-measurement runs the plan computed for ONE cell (the bodies are the plan's, never the caller's)",
)
def queue_remeasurement(  # noqa: PLR0917 — FastAPI dependencies + body + query
    body: RemeasureQueueIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
) -> RemeasureQueueOut:
    """The hand-off the operator used to make by posting the plan's JSON by hand (G-532).

    This spends money, so it is deliberately narrow: one cell per call, the bodies are the
    plan's own ``POST /runs`` requests (each re-validated as a
    :class:`~crb.server.schemas.RunCreateRequest` before it is enqueued — a body the plan
    could not build is our defect), and the response repeats what the plan said it would
    cost with ``cost_known`` honoured. **422** for a cell that is not in the plan, for a
    label the plan holds in both modes with no ``mode`` given, and for a what-if plan (an
    ``apparatus`` other than the running one: its runs would grade under the running
    apparatus and could never clear the plan they were queued from); **422
    ``builder_credential_missing``** (and every other submit refusal ``POST /runs`` makes)
    when any run of the cell would meet it — checked for every run before any is enqueued,
    through the same :func:`~crb.server.routes.runs.submit_refusals`, so the whole cell is
    refused with nothing queued; **409 ``remeasure_already_queued``** while any run an earlier
    queue of this cell (same mode and apparatus) put on the queue has not finished, naming
    those runs — the plan is derived from graded rows only, so without this a double click
    or a second operator would spend the estimate twice. The guard, the runs and the
    ``learn.remeasure.queued`` event that names them are one locked transaction under the
    events write lock too (EI-1, P-420): two concurrent queues cannot both pass the check,
    and a failed insert or a lost ``seq`` race leaves no run on the queue that no event
    names, and a transaction already open when the lock is taken refuses the queue rather
    than run it unlocked (P-429); **409 ``remeasure_concurrent_write``** when other Learn
    writes won that race three times, with nothing queued; **503 ``queue_unavailable``**
    when this server has no queue.
    """
    get_repo_or_404(db, repo)
    if body.apparatus != APPARATUS_VERSION:
        raise ApiError(
            422,
            "validation_error",
            f"a what-if plan queues nothing: apparatus {body.apparatus!r} is not the running "
            f"apparatus {APPARATUS_VERSION!r}, so its runs would grade under "
            f"{APPARATUS_VERSION!r} and could never clear the plan they were queued from",
            detail={"apparatus": body.apparatus, "running": APPARATUS_VERSION},
        )
    plan = derive_remeasure(db, factory, repo, apparatus=body.apparatus, settings=settings)
    matches = [
        c
        for c in plan.cells
        if c.cell.label == body.cell and (not body.mode or c.mode == body.mode)
    ]
    if not matches:
        raise ApiError(
            422,
            "validation_error",
            f"cell {body.cell!r} is not in this repository's re-measurement plan for "
            f"apparatus {body.apparatus!r} — re-read GET /learn/remeasure",
            detail={"available": sorted({f"{c.cell.label} ({c.mode})" for c in plan.cells})},
        )
    pending = [c for c in matches if c.reason == REASON_PENDING]
    if not pending:
        # no registered reading waits on this cell: a replay's rows could never count, and
        # they would make its commits unusable in the reading that could (ADR-0026 item 2)
        first = matches[0]
        raise ApiError(
            422,
            "reading_unregistered",
            f"cell {body.cell!r} has no registered reading at apparatus {body.apparatus} "
            f"waiting on its look, so there is nothing to queue: {first.note}",
            detail={"next_act": first.next_act, "arms": sorted(c.arm for c in matches)},
        )
    if len(pending) > 1:
        raise ApiError(
            422,
            "validation_error",
            f"cell {body.cell!r} is planned in {len(pending)} modes — name one: sighted and "
            "blind are never pooled, so they are re-measured as separate runs",
            detail={"modes": sorted(c.mode for c in pending)},
        )
    cell = pending[0]
    if not cell.requests:
        # the reading waits, but nothing this plan may compose can write rows it counts
        # (another arm, another author or posture, or its commits are not buildable)
        raise ApiError(
            422,
            "validation_error",
            f"cell {body.cell!r} ({cell.mode}) has no run to queue: {cell.note}",
            detail={"n_needed": cell.n_needed, "short_by": cell.short_by},
        )
    require_jobs()  # 503 before anything is read under the lock
    # every run is built and put to the submit gate BEFORE any is enqueued: a cell is queued
    # whole or not at all (P-160 — the gate is the one POST /runs applies)
    validated_runs: list[RunCreateRequest] = []
    for request in cell.requests:
        payload = {k: v for k, v in request.to_dict().items() if k != "note"}
        try:
            validated = RunCreateRequest(**payload)
        except ValueError as exc:  # pragma: no cover - a derivation defect, not a caller's
            raise ApiError(
                422, "validation_error", f"the plan's run body does not validate: {exc}"
            ) from exc
        submit_refusals(db, settings, validated, new_run(validated, actor=operator.id))
        validated_runs.append(validated)

    # P-420: the guard, the runs and the event that names them are ONE serialised
    # transaction (EI-1, DL-080). The lock makes a concurrent queue of any cell wait for this
    # one to commit (so it sees these runs and is refused); the runs are staged on the
    # request's own session (``stage_queued``), in the same transaction as the event, so a
    # lost ``seq`` race or a failed insert rolls every run back with it, and a retry never
    # finds runs on the queue that no event names.
    def stage() -> dict[str, Any]:
        # the check and the runs are staged again on every attempt: they are in the
        # transaction, so a lost race rolled them back with the event; each run meets the
        # submit gate again under the lock, where nothing can change before it is staged.
        # The guard is read under the events write lock as well (EI-1): a second request
        # waits here and then reads the first one's event, so it is refused
        lock_event_writes(db)
        in_flight = in_flight_runs(
            db, repo, cell=cell.cell.label, mode=cell.mode, apparatus=body.apparatus
        )
        if in_flight:
            raise ApiError(
                409,
                "remeasure_already_queued",
                f"{len(in_flight)} run(s) queued for {cell.cell.label!r} ({cell.mode}) have "
                "not finished — nothing was queued; the plan is re-read once they have graded",
                detail={"run_ids": in_flight},
            )
        runs = []
        for v in validated_runs:
            run = new_run(v, actor=operator.id)
            # every refusal again but the login check, which ran above, outside the lock:
            # it may write on a second connection, which would wait on this lock (P-729)
            submit_refusals(db, settings, v, run, login=False)
            runs.append(stage_queued(db, run))
        return {
            "cell": cell.cell.label,
            "mode": cell.mode,
            "apparatus": body.apparatus,
            "run_ids": [run.id for run in runs],
            "n_needed": cell.n_needed,
            "arm": cell.arm,
            "reading_id": cell.reading_id,
            "est_cost_usd": round(cell.est_cost_usd, 4),
            "cost_known": cell.cost_known,
        }

    payload = _learn_step(
        db,
        repo,
        action="learn.remeasure.queued",  # a literal on purpose: see the constants above
        actor=operator.id,
        stage=stage,
        exhausted=lambda: ApiError(
            409,
            "remeasure_concurrent_write",
            "other Learn writes kept moving this repository's trace through "
            f"{_QUEUE_ATTEMPTS} attempts — nothing was queued; retry",
        ),
    )
    run_ids = list(payload["run_ids"])
    return RemeasureQueueOut(
        repo=repo,
        cell=cell.cell.label,
        mode=cell.mode,
        run_ids=run_ids,
        n_needed=cell.n_needed,
        est_cost_usd=round(cell.est_cost_usd, 4),
        cost_known=cell.cost_known,
    )


__all__ = [
    "ACTION_REFUSAL_ACCEPTED",
    "ACTION_REMEASURE_QUEUED",
    "ACTION_STRENGTHEN_REGISTERED",
    "accept_refusal",
    "accepted_decisions",
    "corpus_dir",
    "learn_refusals",
    "learn_remeasure",
    "learn_strengthen",
    "learn_trace_id",
    "queue_remeasurement",
    "register_strengthening",
    "router",
]
