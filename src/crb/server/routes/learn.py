"""``/learn/*`` — the learning half of the loop: three derivations, and the three writes
a named person authorises from the report that computed them.

Each read reduces the repo's ledger rows (out of the store as
:class:`~crb.core.ledger.GradeRow`, so an untrusted row refuses to load) with the
matching :mod:`crb.core.learn` derivation and returns its ``to_dict()``:

* ``/learn/refusals`` — protocol rows → candidate guard-corpus lines, every verdict
  ``unsure``; the decisions a named person has already made are served beside them
  (``decisions``, folded from the ``learn.refusal.accepted`` events);
* ``/learn/strengthen`` — oracle-held cells of the class × size map (routed under the
  repo's latest controls verdict, as ``/capability-map`` does) joined to the latest
  ``oracle.score`` events → ``test.add`` items in the frozen-backlog shape. The
  per-task scores are read from the store's **events** (one ``oracle.score`` per task
  per oracle run; an oracle run's ``counts_json`` keeps only the per-cell roll-up, and
  there is no per-task score table) — the same reader ``/oracle/{repo}`` uses, so the
  two screens can never disagree about a task's strength. Every score carries the
  repo, so the item ids equal what ``crb learn strengthen --oracle <GET /oracle/{repo}>
  --controls <GET /oracle/{repo}/controls>`` derives from the exports;
* ``/learn/remeasure`` — cells stamped with an older apparatus → ``n`` needed, cost and
  the ``POST /runs`` bodies an operator can queue.

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
* ``POST /learn/remeasure/queue`` — the plan's own ``POST /runs`` bodies enqueued for
  one cell; event ``learn.remeasure.queued``.

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
              can choose but never compose.
How:          ``DbLedger.rows(repo)`` → ``triage_refusals`` | ``build_capability_map`` +
              ``strengthening_backlog`` (scores from the events table) | ``remeasure_plan``;
              the writes go through ``apply_triage`` / ``FactoryHome.register_*`` /
              ``new_run`` + the job queue, each with an ``append_system_event`` on the
              repo's ``learn:<repo>`` trace in the same transaction.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/learn.py (the three derivations and ``apply_triage`` — the same
              writer the CLI uses), src/crb/server/routes/oracle.py (``SCORE_ACTIONS``,
              ``latest_controls_verdict``), src/crb/server/factory_state.py
              (``FactoryHome.register_backlog`` / ``register_evolution`` — the one
              registration path), src/crb/server/routes/runs.py (``new_run``,
              ``require_jobs``, ``append_system_event`` — how a run is queued and how an
              event is chained), src/crb/server/routes/factory.py
              (``_refuse_if_run_active``, ``_next_item_id`` — the backlog write's own
              guards, shared rather than copied), src/crb/cli/commands/learn.py (the CLI
              twin), docs/LEARNING-LOOP.md (what loops mechanically, what a human decides),
              ui/src/screens/Learn (the screen that offers the three actions)
Tested by:    tests/test_server_routes_learn.py, tests/test_cli_learn.py
Touch when:   never for a new repository; adding a derivation means a function in
              src/crb/core/learn.py, a route here, a CLI verb, and a section in
              docs/LEARNING-LOOP.md; a new event action needs its row in
              docs/API.md#event-vocabulary first.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.capability import PROJECTIONS, build_capability_map
from crb.core.learn import (
    LearnError,
    RefusalDecision,
    RefusalReport,
    RemeasurePlan,
    StrengthenBacklog,
    StrengthenItem,
    apply_triage,
    load_oracle_scores,
    remeasure_plan,
    strengthening_backlog,
    triage_refusals,
)
from crb.core.routing import DEFAULT_POLICY
from crb.core.version import APPARATUS_VERSION
from crb.factory.backlog import Backlog, BacklogError, BacklogItem
from crb.factory.readiness import ROUTE_BUILD, assess
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.routes.factory import _next_item_id, _refuse_if_run_active
from crb.server.routes.oracle import SCORE_ACTIONS, latest_controls_verdict
from crb.server.routes.repos import get_repo_or_404
from crb.server.routes.runs import append_system_event, new_run, require_jobs, system_trace_id
from crb.server.schemas import RunCreateRequest
from crb.store.ledger import DbLedger
from crb.store.models import Event, Task

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
    db: Session, factory: SessionFactoryDep, repo: str, *, by: str, since: str
) -> StrengthenBacklog:
    """The repo's strengthening backlog (``StrengthenBacklog``) under the projection ``by``,
    routed on the same policy and latest controls verdict the delivery gate reads."""
    if by not in PROJECTIONS:
        raise ApiError(
            422,
            "validation_error",
            f"unknown projection {by!r}",
            detail={"allowed": sorted(PROJECTIONS)},
        )
    rows = list(DbLedger(factory).rows(repo=repo))
    cmap = build_capability_map(
        rows,
        projection=PROJECTIONS[by],
        policy=DEFAULT_POLICY,
        controls=latest_controls_verdict(db, repo),
    )
    return strengthening_backlog(
        cmap,
        load_oracle_scores(_scores(db, repo)),
        policy=DEFAULT_POLICY,
        subjects=_subjects(db, repo),
        since=since,
    )


def derive_remeasure(
    db: Session, factory: SessionFactoryDep, repo: str, *, apparatus: str
) -> RemeasurePlan:
    """The repo's re-measurement plan (``RemeasurePlan``) against ``apparatus``."""
    rows = list(DbLedger(factory).rows(repo=repo))
    # each task's CURRENT label: a stale task that was relabelled since would put its new
    # rows in another cell, so the plan leaves it out and names it (decider pass 2, §3)
    labels = {
        str(t.task_id): (str(t.capability_class or ""), str(t.size or ""))
        for t in db.execute(select(Task).where(Task.repo == repo)).scalars()
    }
    return remeasure_plan(
        rows, current_apparatus=apparatus, policy=DEFAULT_POLICY, task_labels=labels
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
    return {
        "repo": repo,
        **derive_refusals(factory, repo).to_dict(),
        "decisions": accepted_decisions(db, repo),
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
    *,
    repo: str = Query(min_length=1, max_length=64),
    by: str = Query(default="class_size", max_length=32),
    since: str = Query(default="", max_length=32),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    backlog = derive_strengthen(db, factory, repo, by=by, since=since)
    return {"repo": repo, "projection": by, **backlog.to_dict()}


@router.get(
    "/learn/remeasure",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="Cells stamped with an older apparatus → n needed, cost, POST /runs bodies (nothing queued)",
)
def learn_remeasure(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    apparatus: str = Query(default=APPARATUS_VERSION, max_length=32),
) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    return {"repo": repo, **derive_remeasure(db, factory, repo, apparatus=apparatus).to_dict()}


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
# read uses, so a request can only name what the report computed, never supply it.


class RefusalAcceptIn(BaseModel):
    """One refusal class's verdict. ``command`` completes a class whose every recorded
    example was cut by the recorder's cap; ``prefix`` labels a refusal whose own guard
    family the refused corpus does not take (a ``tamper`` is belt 1's, never a shell
    line). There is deliberately no ``decided_by``: the signed-in operator is the decider."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=64)
    verdict: Literal["honest", "refuse"]
    note: str = Field(default="", max_length=400)
    command: str = Field(default="", max_length=2000)
    prefix: str = Field(default="", max_length=32)


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
    ``already_present`` — never an event claiming a line nothing wrote.
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
    try:
        applied = apply_triage([decision], report, corpus_dir=directory, decided_by=decider)
    except LearnError as exc:
        raise ApiError(
            422, "refusal_refused", str(exc), detail={"group_id": body.group_id}
        ) from exc
    except OSError as exc:
        raise ApiError(
            409,
            "corpus_not_writable",
            f"the guard corpus at {directory} could not be written ({exc.strerror or exc}); "
            "set CRB_LEARN_CORPUS_DIR to a directory this deployment may append to",
        ) from exc
    lines = [*applied.honest_added, *applied.refused_added]
    already = not lines and bool(applied.skipped)
    append_system_event(
        db,
        trace_id=learn_trace_id(repo),
        action="learn.refusal.accepted",  # a literal on purpose: see the constants above
        repo=repo,
        actor=operator.id,
        payload={
            "group_id": body.group_id,
            "verdict": body.verdict,
            "decided_by": decider,
            "note": body.note,
            "guard": group.prefix,
            "reason": group.reason,
            "shape": group.shape,
            "rows": group.n,
            "lines": lines,
            "already_present": already,
            "corpus_dir": str(directory),
        },
    )
    db.commit()
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
    would not pass the Definition of Ready.
    """
    get_repo_or_404(db, repo)
    _refuse_if_run_active(db, repo)
    derived = derive_strengthen(db, factory, repo, by=body.by, since=body.since)
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
    for item in items:
        active = home.load_backlog()
        try:
            if active is None:
                home.register_backlog([item], actor=operator.id)
                registered.append(RegisteredItemOut(item_id=item.id, supersedes="", how="frozen"))
                continue
            to_register = item
            if active.get(item.id) is not None:
                to_register = replace(
                    item,
                    id=_next_item_id(item.id, [i.id for i in active.all_items()]),
                    supersedes=_latest_in_lineage(active, item.id),
                )
            home.register_evolution(to_register, actor=operator.id)
        except (BacklogError, ValueError) as exc:
            raise ApiError(
                409,
                "register_refused",
                f"item {item.id!r} was not registered: {exc}",
                detail={"registered": [r.item_id for r in registered]},
            ) from exc
        registered.append(
            RegisteredItemOut(
                item_id=to_register.id, supersedes=to_register.supersedes, how="evolved"
            )
        )
    final = home.load_backlog()
    assert final is not None  # something was registered above, or a 409 was raised
    append_system_event(
        db,
        trace_id=learn_trace_id(repo),
        action="learn.strengthen.registered",  # a literal on purpose: see the constants above
        repo=repo,
        actor=operator.id,
        payload={
            "projection": body.by,
            "since": body.since,
            "items": [r.model_dump() for r in registered],
            "backlog_hash": final.backlog_hash,
            "evolutions_hash": final.evolutions_hash,
        },
    )
    db.commit()
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
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR, 503: _ERR},
    summary="Queue the re-measurement runs the plan computed for ONE cell (the bodies are the plan's, never the caller's)",
)
def queue_remeasurement(
    body: RemeasureQueueIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
) -> RemeasureQueueOut:
    """The hand-off the operator used to make by posting the plan's JSON by hand (G-532).

    This spends money, so it is deliberately narrow: one cell per call, the bodies are the
    plan's own ``POST /runs`` requests (each re-validated as a
    :class:`~crb.server.schemas.RunCreateRequest` before it is enqueued — a body the plan
    could not build is our defect), and the response repeats what the plan said it would
    cost with ``cost_known`` honoured. **422** for a cell that is not in the plan, or for a
    label the plan holds in both modes with no ``mode`` given; **503
    ``queue_unavailable``** when this server has no queue.
    """
    get_repo_or_404(db, repo)
    plan = derive_remeasure(db, factory, repo, apparatus=body.apparatus)
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
            detail={"available": [f"{c.cell.label} ({c.mode})" for c in plan.cells]},
        )
    if len(matches) > 1:
        raise ApiError(
            422,
            "validation_error",
            f"cell {body.cell!r} is planned in {len(matches)} modes — name one: sighted and "
            "blind are never pooled, so they are re-measured as separate runs",
            detail={"modes": sorted(c.mode for c in matches)},
        )
    cell = matches[0]
    api = require_jobs()
    run_ids: list[str] = []
    for request in cell.requests:
        payload = {k: v for k, v in request.to_dict().items() if k != "note"}
        try:
            validated = RunCreateRequest(**payload)
        except ValueError as exc:  # pragma: no cover - a derivation defect, not a caller's
            raise ApiError(
                422, "validation_error", f"the plan's run body does not validate: {exc}"
            ) from exc
        run_ids.append(api.enqueue(factory, new_run(validated, actor=operator.id)).id)
    append_system_event(
        db,
        trace_id=learn_trace_id(repo),
        action="learn.remeasure.queued",  # a literal on purpose: see the constants above
        repo=repo,
        actor=operator.id,
        payload={
            "cell": cell.cell.label,
            "mode": cell.mode,
            "apparatus": body.apparatus,
            "run_ids": run_ids,
            "n_needed": cell.n_needed,
            "est_cost_usd": round(cell.est_cost_usd, 4),
            "cost_known": cell.cost_known,
        },
    )
    db.commit()
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
