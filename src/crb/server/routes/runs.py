"""``/runs`` — create, list, inspect, cancel; per-task outcomes; the StepEvent stream.

The server never executes a run. ``POST /runs`` validates the request and hands a
``queued`` :class:`~crb.store.models.Run` to the job queue; the worker claims it,
executes it and writes grades (append-only) and events (append-only). Everything
this module serves is a READ of those tables, plus two writes that go through the
queue: ``enqueue`` and ``request_cancel``.

Queue seam
----------
The queue lives in ``crb.store.jobs`` and the event sink in ``crb.store.events``
(sibling workstream). They are imported LAZILY inside :func:`_jobs_api` /
:func:`read_events` — this module imports (and every read route works) even when
those modules are absent; the two write routes then answer ``503 queue_unavailable``
rather than pretending. Tests inject a fake module under the same import name.

SSE
---
``GET /runs/{id}/events`` is a plain ``text/event-stream`` over the ``events`` table
(no broker): replay every stored event with ``seq > after`` (``id:`` = seq so a
browser ``EventSource`` resumes by itself), then poll the table every
:data:`SSE_POLL_S` seconds; a ``: keepalive`` comment every :data:`SSE_KEEPALIVE_S`
seconds keeps proxies from closing an idle stream; ``event: done`` closes the
stream once the run is terminal; a client disconnect stops the poll loop.

Navigation
----------
What it is:   The ``/runs`` API — create, list, inspect, cancel a run; its per-task table;
              its stored and streamed StepEvents.
What it does: Validates a ``RunCreateRequest`` (kind, ladder, budget, builder_config, retain,
              outage_stop, preflight) into a queued ``Run`` row; serves run views with
              counts re-derived from the ledger when the worker wrote none; streams events
              as SSE with resume-by-seq; cancellation is a flag the worker honours.
How:          FastAPI handlers over ``JobQueue`` (queue writes) and read-only SQLAlchemy
              queries; ``run_out`` is the one place a ``Run`` row becomes a ``RunOut``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md, docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/server/schemas.py (RunCreateRequest, RunOut, RunCounts, RunFactoryOut —
              mirrored by ui/src/api/types.ts), src/crb/store/jobs.py (enqueue; cancel with
              the operator as actor), src/crb/server/worker.py (what a queued run becomes;
              the counts shapes per kind), src/crb/store/models.py (Run, Grade, Event, User —
              the override's display name resolved at read), docs/API.md#runs (the
              ``counts`` shapes per kind, queue position, the factory posture),
              ui/src/screens/Runs/RunsPage.tsx and ui/src/screens/Runs/RunDetailPage.tsx (the screens)
Tested by:    tests/test_server_routes_runs.py, tests/test_server_app.py
Touch when:   a run parameter is added (schema field → ``params`` here → the worker reads it →
              docs/API.md → the UI type); a field is added to ``RunOut`` (the UI type first);
              a run kind is added (decide in ``_counts`` whether it is a build kind).

"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import time
import types
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from crb.builders.claude_code import default_model as claude_code_default_model
from crb.core.evidence import sha256_text
from crb.core.grade import BELT_NAMES
from crb.observability.events import StepEvent, StepStatus
from crb.server.auth import OperatorDep, ViewerDep, require_role_now
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.posture_view import deployment_executor, deployment_image, refuse_unqualified
from crb.server.schemas import (
    BUILD_KINDS,
    TERMINAL_STATUSES,
    Belts,
    LadderRung,
    Page,
    PageDep,
    PageQuery,
    PreflightIn,
    RunCounts,
    RunCreateRequest,
    RunFactoryOut,
    RunOut,
    RunProgress,
    RunRetention,
    RunTaskRow,
    StepEventOut,
)
from crb.store.jobs import KIND_FACTORY, STATUS_QUEUED
from crb.store.models import Event, Grade, Repo, Run, Task, User

log = logging.getLogger("crb.server.runs")

router = APIRouter(tags=["runs"])
_ERR = {"model": ErrorEnvelope}

JOBS_MODULE = "crb.store.jobs"
EVENTS_MODULE = "crb.store.events"

#: SSE timings (module-level so tests can shrink them).
SSE_POLL_S = 1.0
SSE_KEEPALIVE_S = 15.0
SSE_PAGE = 500


# ---------------------------------------------------------------------------
# Queue seam (lazy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobsApi:
    """The three queue operations this module needs, resolved at call time."""

    enqueue: Callable[[sessionmaker[Session], Run], Run]
    #: ``(factory, run_id, actor)`` — the actor is the operator who asked (J-TEL-7).
    request_cancel: Callable[[sessionmaker[Session], str, str], bool]
    list_runs: (
        Callable[..., tuple[list[Run], int]] | None
    )  # (factory, *, repo, kind, status, limit, offset)


def _import_optional(name: str) -> types.ModuleType | None:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name in (name, name.rsplit(".", 1)[0]):
            return None
        raise


def _jobs_api() -> JobsApi | None:
    """Resolve ``crb.store.jobs``: module-level functions first, a ``JobQueue`` class second."""
    mod = _import_optional(JOBS_MODULE)
    if mod is None:
        return None
    enqueue = getattr(mod, "enqueue", None)
    cancel = getattr(mod, "request_cancel", None)
    lister = getattr(mod, "list_runs", None)
    if callable(enqueue) and callable(cancel):
        return JobsApi(
            enqueue=enqueue,
            request_cancel=lambda f, rid, actor: bool(cancel(f, rid, actor=actor)),
            list_runs=lister if callable(lister) else None,
        )
    queue_cls = getattr(mod, "JobQueue", None)
    if queue_cls is None:
        return None

    def _enqueue(factory: sessionmaker[Session], run: Run) -> Run:
        out: Run = queue_cls(factory).enqueue(run)
        return out

    def _cancel(factory: sessionmaker[Session], run_id: str, actor: str) -> bool:
        return queue_cls(factory).request_cancel(run_id, actor=actor) is not None

    def _list(factory: sessionmaker[Session], **kw: Any) -> tuple[list[Run], int]:
        out: tuple[list[Run], int] = queue_cls(factory).list_runs(**kw)
        return out

    return JobsApi(enqueue=_enqueue, request_cancel=_cancel, list_runs=_list)


def require_jobs() -> JobsApi:
    api = _jobs_api()
    if api is None:
        raise ApiError(
            503,
            "queue_unavailable",
            f"the job queue ({JOBS_MODULE}) is not available on this server",
            detail={"module": JOBS_MODULE},
        )
    return api


# ---------------------------------------------------------------------------
# Events: read + append helpers shared by the domain routes
# ---------------------------------------------------------------------------

EVENT_KEYS: tuple[str, ...] = (
    "event_id",
    "seq",
    "timestamp",
    "trace_id",
    "step_id",
    "parent_step_id",
    "stage",
    "action",
    "status",
    "actor",
    "repo",
    "task_id",
    "input_ref",
    "output_ref",
    "error_code",
    "error_message",
    "duration_ms",
    "cost_usd",
)


def event_to_dict(m: Event) -> dict[str, Any]:
    """An ``events`` row in :meth:`StepEvent.to_dict` shape."""
    d: dict[str, Any] = {k: getattr(m, k) for k in EVENT_KEYS}
    d["payload"] = dict(m.payload_json or {})
    return d


def event_to_model(e: StepEvent) -> Event:
    d = e.to_dict()
    payload = d.pop("payload")
    return Event(**d, payload_json=payload)


def system_trace_id(*parts: str) -> str:
    """A deterministic 32-char trace id for out-of-band system events (``repo:<name>`` …)."""
    return sha256_text(":".join(parts))[:32]


def append_system_event(
    session: Session,
    *,
    trace_id: str,
    action: str,
    repo: str = "",
    actor: str = "",
    task_id: str = "",
    status: StepStatus = StepStatus.OK,
    error: str = "",
    payload: Mapping[str, Any] | None = None,
) -> StepEvent:
    """Add one ``system`` StepEvent to ``session`` with the trace's next ``seq``.

    Not committed here: the caller commits it together with the state change it
    records, so an audit event and its cause are one transaction. The payload is
    redacted by :class:`StepEvent` at construction.
    """
    last = session.execute(
        select(func.max(Event.seq)).where(Event.trace_id == trace_id)
    ).scalar_one_or_none()
    ev = StepEvent(
        trace_id=trace_id,
        stage="system",
        action=action,
        status=status,
        step_id=task_id,
        actor=actor,
        repo=repo,
        task_id=task_id,
        error_message=error,
        payload=dict(payload or {}),
        seq=int(last or 0) + 1,
    )
    session.add(event_to_model(ev))
    return ev


def _read_events_local(
    factory: sessionmaker[Session], trace_id: str, after_seq: int, limit: int
) -> list[dict[str, Any]]:
    with factory() as s:
        q = (
            select(Event)
            .where(Event.trace_id == trace_id, Event.seq > int(after_seq))
            .order_by(Event.seq, Event.id)
            .limit(limit)
        )
        return [event_to_dict(m) for m in s.execute(q).scalars()]


def read_events(
    factory: sessionmaker[Session], trace_id: str, *, after_seq: int = 0, limit: int = SSE_PAGE
) -> list[dict[str, Any]]:
    """Events of a trace with ``seq > after_seq`` (ascending), as dicts. Prefers the
    store's reader (``crb.store.events.read_events``) when present."""
    mod = _import_optional(EVENTS_MODULE)
    reader = getattr(mod, "read_events", None) if mod is not None else None
    if callable(reader):
        evs = reader(factory, trace_id, after_seq=after_seq, limit=limit)
        return [e.to_dict() if isinstance(e, StepEvent) else dict(e) for e in evs]
    return _read_events_local(factory, trace_id, after_seq, limit)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _opt(s: str | None) -> str | None:
    return s or None


def derive_counts(session: Session, run_id: str) -> RunCounts:
    """``RunSummary``-shaped counts re-derived from the run's ledger rows (one row per
    attempt). Used when the worker has not written ``counts_json`` yet."""
    rows = list(
        session.execute(
            select(Grade.task_id, Grade.trial, Grade.clean, Grade.disqualified, Grade.error)
            .where(Grade.run_id == run_id)
            .order_by(Grade.seq)
        ).all()
    )
    by_task: dict[str, list[Any]] = {}
    for r in rows:
        by_task.setdefault(str(r.task_id), []).append(r)
    clean = sum(1 for rs in by_task.values() if any(r.clean for r in rs))
    dq = sum(1 for rs in by_task.values() if any(r.disqualified for r in rs))
    first_pass = sum(1 for rs in by_task.values() if rs and rs[0].clean)
    return RunCounts(
        tasks=len(by_task),
        clean=clean,
        disqualified=dq,
        errors=sum(1 for r in rows if r.error),
        first_pass_clean=first_pass,
        rows=len(rows),
    )


def _counts(session: Session, run: Run) -> RunCounts:
    """``counts`` by KIND (J-TEL-5): a build kind (replay / blind / factory) is the
    ``RunSummary`` mapping — the worker's, or re-derived from its ledger rows. Every other
    kind serves its ``counts_json`` verbatim under ``detail``: an oracle run's ``tasks``
    are scored tasks and its ``errors`` harness-errored mutants, a label run's cost is in
    ``usage`` — read as a build summary they rendered ``Clean 0.0 %`` with the wrong n."""
    cj = dict(run.counts_json or {})
    if run.kind not in BUILD_KINDS and run.kind != KIND_FACTORY:
        return RunCounts(detail={k: v for k, v in cj.items() if k != "current_task_id"})
    if "tasks" in cj or "rows" in cj:
        known = {k: cj[k] for k in RunCounts.model_fields if k in cj and k != "detail"}
        return RunCounts(**known)
    derived = derive_counts(session, run.id)
    # a factory run keeps its own counters (items, done, accepted, by_status, outcomes) next
    # to the RunSummary derived from its graded attempts
    derived.detail = {k: v for k, v in cj.items() if k != "current_task_id"}
    return derived


def _queue_position(session: Session, run: Run) -> tuple[int | None, list[str]]:
    """J-TEL-3: the run's 1-based place in the FIFO queue and the kinds ahead of it —
    the claim order is ``(created, id)`` (``JobQueue.claim_next``), so this is the order a
    worker will take them in. ``(None, [])`` unless the run is queued."""
    if run.status != STATUS_QUEUED:
        return None, []
    ahead = session.execute(
        select(Run.kind)
        .where(
            Run.status == STATUS_QUEUED,
            (Run.created < run.created) | ((Run.created == run.created) & (Run.id < run.id)),
        )
        .order_by(Run.created, Run.id)
    ).all()
    kinds = [str(k) for (k,) in ahead]
    return len(kinds) + 1, kinds


def _display_name(session: Session, user_id: str) -> str | None:
    """The name a reader sees for a principal id, resolved at read time (the same rule as
    sign-offs: the row keeps the id, a name may change); ``None`` when the account is gone."""
    user = session.get(User, user_id)
    if user is None:
        return None
    return user.display_name or user.subject.removeprefix("local:")


def _factory_out(session: Session, run: Run, params: Mapping[str, Any]) -> RunFactoryOut | None:
    """J-FAC-6: what a factory run was allowed to do, from its params; ``None`` otherwise."""
    if run.kind != KIND_FACTORY:
        return None
    override = str(params.get("deliver_override_by", "") or "") or None
    return RunFactoryOut(
        deliver=bool(params.get("deliver", False)),
        deliver_override_by=override,
        deliver_override_by_name=_display_name(session, override) if override else None,
        backlog_hash=str(params.get("backlog_hash", "") or ""),
    )


def _current_task(session: Session, run: Run) -> str | None:
    cj = dict(run.counts_json or {})
    current = cj.get("current_task_id")
    if current:
        return str(current)
    if run.status != "running":
        return None
    last = session.execute(
        select(Event.task_id)
        .where(Event.trace_id == run.id, Event.task_id != "")
        .order_by(Event.seq.desc(), Event.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return str(last) if last else None


def run_out(session: Session, run: Run) -> RunOut:
    """The API's view of a run: the row + ``counts`` + ``progress`` + the params it was
    created with (``executor``, ``timeout``, ``pool``, ``limit``, ``task_ids``,
    ``builder_config``, ``budget``), its place in the queue while queued, and a factory
    run's delivery posture. ``ladder`` is ``ladder_json`` as declared — labels and/or
    object rungs."""
    params = dict(run.params_json or {})
    apparatus = dict(run.apparatus_json or {})
    cost = session.execute(
        select(func.coalesce(func.sum(Grade.cost_usd), 0.0)).where(Grade.run_id == run.id)
    ).scalar_one()
    limit = params.get("limit")
    position, kinds_ahead = _queue_position(session, run)
    return RunOut(
        id=run.id,
        repo=run.repo,
        kind=run.kind,
        status=run.status,
        mode=run.mode,
        builder=run.builder,
        model=run.model,
        provider=run.provider,
        ladder=list(run.ladder_json or []),
        budget=dict(params.get("budget") or {}),
        executor=str(params.get("executor", "") or ""),
        timeout=int(params.get("timeout", 0) or 0),
        pool=str(params.get("pool", "") or ""),
        limit=int(limit) if limit else None,
        task_ids=[str(t) for t in params.get("task_ids", []) or []],
        builder_config=dict(params.get("builder_config") or {}),
        retain=RunRetention(**dict(params.get("retain") or {})),
        actor=run.actor,
        created=run.created,
        started=_opt(run.started),
        finished=_opt(run.finished),
        cancel_requested=bool(run.cancel_requested),
        error=run.error,
        cost_usd=round(float(cost or 0.0), 6),
        apparatus_version=str(apparatus.get("apparatus_version", "") or ""),
        apparatus=apparatus,
        worker_id=run.worker_id,
        heartbeat=_opt(run.heartbeat),
        counts=_counts(session, run),
        progress=RunProgress(
            done=run.progress_done,
            total=run.progress_total,
            current_task_id=_current_task(session, run),
        ),
        queue_position=position,
        queue_kinds_ahead=kinds_ahead,
        factory=_factory_out(session, run, params),
    )


def _get_run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", f"no run {run_id!r}")
    return run


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _list_local(
    session: Session, *, repo: str | None, kind: str | None, status_: str | None, page: PageQuery
) -> tuple[list[Run], int]:
    q = select(Run)
    c = select(func.count(Run.id))
    if repo:
        q, c = q.where(Run.repo == repo), c.where(Run.repo == repo)
    if kind:
        q, c = q.where(Run.kind == kind), c.where(Run.kind == kind)
    if status_:
        q, c = q.where(Run.status == status_), c.where(Run.status == status_)
    total = int(session.execute(c).scalar_one())
    items = list(
        session.execute(
            q.order_by(Run.created.desc(), Run.id.desc()).limit(page.limit).offset(page.offset)
        ).scalars()
    )
    return items, total


@router.get("/runs", response_model=Page[RunOut], responses={401: _ERR})
def list_runs(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    page: PageDep,
    *,
    repo: str | None = Query(default=None, max_length=64),
    kind: str | None = Query(default=None, max_length=16),
    status_: str | None = Query(default=None, alias="status", max_length=16),
) -> Page[RunOut]:
    del viewer
    api = _jobs_api()
    if api is not None and api.list_runs is not None:
        items, total = api.list_runs(
            factory, repo=repo, kind=kind, status=status_, limit=page.limit, offset=page.offset
        )
    else:
        items, total = _list_local(db, repo=repo, kind=kind, status_=status_, page=page)
    return Page[RunOut](
        items=[run_out(db, r) for r in items], total=total, limit=page.limit, offset=page.offset
    )


def default_model_for(builder: str) -> str:
    """The model a build run gets when the request names none. Only ``claude_code`` has
    a default (``CRB_CLAUDE_CODE_MODEL`` on the API host, else the adapter's
    ``DEFAULT_MODEL``); every other builder needs an explicit model."""
    if builder == "claude_code":
        return claude_code_default_model()
    return ""


def active_backlog_hash(settings: Any, repo: str, expected: str | None) -> tuple[str, str]:
    """``(backlog_hash, evolutions_hash)`` of ``repo``'s active frozen backlog — the pair
    the run is pinned to at enqueue (an evolution moves only the second; the worker
    compares both on claim). 409 ``no_frozen_backlog`` when there is none, 409
    ``backlog_hash_mismatch`` when the caller named a different frozen hash."""
    backlog = FactoryHome(settings.home, repo).load_backlog()
    if backlog is None or not backlog.frozen:
        raise ApiError(
            409,
            "no_frozen_backlog",
            f"no frozen backlog registered for {repo!r}: POST /factory/{repo}/backlog first",
        )
    if expected is not None and expected != backlog.backlog_hash:
        raise ApiError(
            409,
            "backlog_hash_mismatch",
            "the active backlog is not the one this run names — re-read it and re-submit",
            detail={"active": backlog.backlog_hash, "requested": expected},
        )
    return str(backlog.backlog_hash), str(backlog.evolutions_hash)


def new_run(body: RunCreateRequest, *, actor: str) -> Run:
    """A ``queued`` Run row from a validated request (id assigned here so the response
    can name it even if the queue does not). A build kind without a model gets the
    builder's default (see :func:`default_model_for`) so the stored row — and every
    ledger row it produces — names the model that actually ran. A ladder made only of
    object rungs may omit the run's ``builder``/``model``: the FIRST rung fills them, so
    the run listing names what climbed first (each ledger row names its own rung).

    ``ladder_json`` keeps the ladder as declared (labels as written, object rungs as
    ``{builder, model, provider?, budget?}`` with only the budget fields that were set);
    ``params.budget`` keeps only the run-level caps the request set — the worker overlays
    them on the builder's defaults, and a rung's own budget on top of those."""
    builder, model, provider = body.builder, body.model, body.provider
    if body.kind in BUILD_KINDS and not builder:
        first = next(e for e in body.ladder if isinstance(e, LadderRung))
        builder, model, provider = first.builder, first.model, first.provider
    if body.kind in BUILD_KINDS and builder and not model:
        model = default_model_for(builder)
    params: dict[str, Any] = {
        "task_ids": list(body.task_ids),
        "limit": body.limit,
        "pool": body.pool,
        "executor": body.executor,
        "timeout": body.timeout or 0,
    }
    if body.builder_config:
        params["builder_config"] = dict(body.builder_config)
    if body.budget is not None and body.budget.overrides():
        params["budget"] = body.budget.overrides()
    if body.retain.worktrees or body.retain.transcripts:
        params["retain"] = body.retain.model_dump()
    if body.outage_stop is not None:
        params["outage_stop"] = body.outage_stop
    if body.qualify_first is not None:
        params["qualify_first"] = bool(body.qualify_first)
    if body.env_stop is not None:
        params["env_stop"] = body.env_stop
    if body.preflight is True:
        params["preflight"] = True
    elif isinstance(body.preflight, PreflightIn):
        params["preflight"] = body.preflight.model_dump()
    ladder: list[Any] = body.stored_ladder()
    return Run(
        id=uuid.uuid4().hex,
        repo=body.repo,
        kind=body.kind,
        mode=body.mode or "sighted",
        status="queued",
        builder=builder,
        model=model,
        provider=provider,
        ladder_json=ladder or ["r1"],
        params_json=params,
        actor=actor,
    )


@router.post(
    "/runs",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 503: _ERR},
    summary="Enqueue a run (status queued); the worker executes it",
)
def create_run(
    body: RunCreateRequest,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> RunOut:
    if db.get(Repo, body.repo) is None:
        raise ApiError(404, "not_found", f"no repo {body.repo!r}")
    factory_only = {
        "backlog_hash": body.backlog_hash,
        "deliver": body.deliver,
        "deliver_override": body.deliver_override,
        "max_rework": body.max_rework,
        "test_author": body.test_author,
    }
    if body.kind != KIND_FACTORY and any(v is not None for v in factory_only.values()):
        named = sorted(k for k, v in factory_only.items() if v is not None)
        raise ApiError(422, "validation_error", f"{named} apply to factory runs only")
    api = require_jobs()
    run = new_run(body, actor=operator.id)
    if body.kind == KIND_FACTORY:
        # Pin the backlog the run will work at ENQUEUE time — the frozen hash AND the
        # evolutions chain, since an evolution registered in the same window changes what
        # is worked without moving the frozen hash; the worker re-verifies both on claim.
        # Closes the window between the register / evolutions routes' "no active run"
        # check and this enqueue (CodeRabbit on PR #4, 2026-09-15; verifier 2026-09-22).
        pinned, pinned_evolutions = active_backlog_hash(settings, body.repo, body.backlog_hash)
        params = {
            **dict(run.params_json or {}),
            "backlog_hash": pinned,
            "evolutions_hash": pinned_evolutions,
        }
        if body.deliver is not None:
            params["deliver"] = bool(body.deliver)
        if body.max_rework is not None:
            params["max_rework"] = int(body.max_rework)
        if body.test_author is not None:
            # G-904 — this run's test-author rung (or ``none``); the worker refuses one
            # that is also a rung on the ladder before anything is built
            params["test_author"] = body.test_author.strip()
        if body.deliver_override:
            # the route gate's override is an APPROVER's act, stamped with their identity
            # (external review 2026-09-16 point 36 → DL-038)
            require_role_now(operator, "approver")
            params["deliver_override_by"] = operator.id
        run.params_json = params
    if body.qualify_first is False:
        # ADR-0019 §3: a build run with nothing qualified where it would be graded can only
        # fail POSTURE_UNQUALIFIED on the worker — refuse it here, with the fix
        repo_row = db.get(Repo, body.repo)
        if repo_row is None:  # pragma: no cover — refused 404 above
            raise ApiError(404, "not_found", f"no repo {body.repo!r}")
        executor = deployment_executor(settings, body.executor)
        refuse_unqualified(
            db,
            repo_row,
            kind=body.kind,
            task_ids=list(body.task_ids),
            executor=executor,
            image_ref=deployment_image(settings, repo_row),
        )
    run = api.enqueue(factory, run)
    stored = db.get(Run, run.id)
    return run_out(db, stored if stored is not None else run)


@router.get("/runs/{run_id}", response_model=RunOut, responses={401: _ERR, 404: _ERR})
def get_run(run_id: str, viewer: ViewerDep, db: DbDep) -> RunOut:
    del viewer
    return run_out(db, _get_run(db, run_id))


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 503: _ERR},
    summary="Request cancellation; the worker stops between tasks",
)
def cancel_run(run_id: str, operator: OperatorDep, db: DbDep, factory: SessionFactoryDep) -> RunOut:
    """A queued run is cancelled outright, a running one is flagged; either way the
    queue writes ``run.cancel_requested`` naming THIS operator (J-TEL-7)."""
    run = _get_run(db, run_id)
    if run.status in TERMINAL_STATUSES:
        raise ApiError(
            409, "run_terminal", f"run is already {run.status}", detail={"status": run.status}
        )
    api = require_jobs()
    if not api.request_cancel(factory, run_id, operator.id):
        raise ApiError(404, "not_found", f"no run {run_id!r}")
    db.expire_all()
    return run_out(db, _get_run(db, run_id))


def _belts_of(g: Grade) -> Belts:
    return Belts(**{b: getattr(g, b) for b in BELT_NAMES})


def run_task_rows(session: Session, run_id: str) -> list[RunTaskRow]:
    """Grade rows of a run collapsed per task (chain order preserved).

    ``clean`` is "any attempt clean"; ``first_pass_clean`` is the first attempt only;
    ``belts`` are those of the decisive attempt — the clean one when there is one,
    otherwise the last. Cost and latency are summed over attempts.
    """
    grades = list(
        session.execute(select(Grade).where(Grade.run_id == run_id).order_by(Grade.seq)).scalars()
    )
    by_task: dict[str, list[Grade]] = {}
    for g in grades:
        by_task.setdefault(g.task_id, []).append(g)
    if not by_task:
        return []
    repo = grades[0].repo
    specs = {
        t.task_id: t
        for t in session.execute(
            select(Task).where(Task.repo == repo, Task.task_id.in_(list(by_task)))
        ).scalars()
    }
    out: list[RunTaskRow] = []
    for task_id, rs in by_task.items():
        decisive = next((g for g in rs if g.clean), rs[-1])
        spec = specs.get(task_id)
        out.append(
            RunTaskRow(
                task_id=task_id,
                capability_class=spec.capability_class if spec else rs[0].capability_class,
                size=spec.size if spec else rs[0].size,
                pool=spec.pool if spec else rs[0].pool,
                language=spec.language if spec else rs[0].language,
                trials=len(rs),
                clean=any(g.clean for g in rs),
                first_pass_clean=bool(rs[0].clean),
                disqualified=any(g.disqualified for g in rs),
                error=next((g.error for g in reversed(rs) if g.error), ""),
                belt_set=decisive.belt_set,
                belts=_belts_of(decisive),
                cost_usd=round(sum(g.cost_usd for g in rs), 6),
                latency_s=round(sum(g.latency_s for g in rs), 3),
                pack_hashes=[g.evidence_pack_hash for g in rs if g.evidence_pack_hash],
                row_ids=[g.row_id for g in rs],
                budget_tier=_budget_tier(decisive),
                budget_tiers=[_budget_tier(g) for g in rs],
            )
        )
    return out


def _budget_tier(g: Grade) -> str:
    """``labels.budget_tier`` as the worker stamped it (``""`` on rows without one)."""
    return str((g.labels_json or {}).get("budget_tier", "") or "")


@router.get(
    "/runs/{run_id}/tasks",
    response_model=Page[RunTaskRow],
    responses={401: _ERR, 404: _ERR},
    summary="Per-task outcome table (trials, clean, belts, cost, latency, pack hashes)",
)
def get_run_tasks(run_id: str, viewer: ViewerDep, db: DbDep, page: PageDep) -> Page[RunTaskRow]:
    del viewer
    _get_run(db, run_id)
    rows = run_task_rows(db, run_id)
    return Page[RunTaskRow](
        items=rows[page.offset : page.offset + page.limit],
        total=len(rows),
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/runs/{run_id}/events/log",
    response_model=Page[StepEventOut],
    responses={401: _ERR, 404: _ERR},
    summary="Stored StepEvents of a run, oldest first (non-streaming)",
)
def get_run_events_log(
    run_id: str, viewer: ViewerDep, db: DbDep, page: PageDep
) -> Page[StepEventOut]:
    del viewer
    _get_run(db, run_id)
    total = int(
        db.execute(select(func.count(Event.id)).where(Event.trace_id == run_id)).scalar_one()
    )
    items = list(
        db.execute(
            select(Event)
            .where(Event.trace_id == run_id)
            .order_by(Event.seq, Event.id)
            .limit(page.limit)
            .offset(page.offset)
        ).scalars()
    )
    return Page[StepEventOut](
        items=[StepEventOut(**event_to_dict(m)) for m in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# --- SSE ----------------------------------------------------------------------------


def sse_frame(event: str, data: Any, *, event_id: int | None = None) -> str:
    """One SSE frame. ``data`` is JSON-encoded on a single line (no bare newlines)."""
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    head = f"event: {event}\n"
    if event_id is not None:
        head += f"id: {event_id}\n"
    return f"{head}data: {body}\n\n"


def _run_status(factory: sessionmaker[Session], run_id: str) -> str | None:
    with factory() as s:
        return s.execute(select(Run.status).where(Run.id == run_id)).scalar_one_or_none()


async def event_stream(
    request: Request, factory: sessionmaker[Session], run_id: str, after: int
) -> AsyncIterator[str]:
    """Replay-then-poll generator behind ``GET /runs/{id}/events``.

    The run status is read BEFORE the events on every pass, so when a pass sees a
    terminal status the events it drains include everything written before the
    status flipped — nothing between "last event" and "done" is lost.
    """
    cursor = int(after)
    last_activity = time.monotonic()
    while True:
        status_now = await run_in_threadpool(_run_status, factory, run_id)
        drained = False
        while not drained:
            batch = await run_in_threadpool(
                read_events, factory, run_id, after_seq=cursor, limit=SSE_PAGE
            )
            for ev in batch:
                cursor = max(cursor, int(ev["seq"]))
                last_activity = time.monotonic()
                yield sse_frame("step", ev, event_id=int(ev["seq"]))
            drained = len(batch) < SSE_PAGE
        if status_now is None or status_now in TERMINAL_STATUSES:
            yield sse_frame(
                "done", {"run_id": run_id, "status": status_now or "unknown", "last_seq": cursor}
            )
            return
        if await request.is_disconnected():
            return
        if time.monotonic() - last_activity >= SSE_KEEPALIVE_S:
            last_activity = time.monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(SSE_POLL_S)


@router.get(
    "/runs/{run_id}/events",
    responses={401: _ERR, 404: _ERR},
    summary="SSE stream of StepEvents (event: step / done); ?after=<seq> resumes",
    response_class=StreamingResponse,
)
async def stream_run_events(
    run_id: str,
    request: Request,
    viewer: ViewerDep,
    factory: SessionFactoryDep,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    del viewer
    if await run_in_threadpool(_run_status, factory, run_id) is None:
        raise ApiError(404, "not_found", f"no run {run_id!r}")
    return StreamingResponse(
        event_stream(request, factory, run_id, after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


__all__ = [
    "EVENTS_MODULE",
    "JOBS_MODULE",
    "SSE_KEEPALIVE_S",
    "SSE_PAGE",
    "SSE_POLL_S",
    "JobsApi",
    "append_system_event",
    "derive_counts",
    "event_stream",
    "event_to_dict",
    "event_to_model",
    "new_run",
    "read_events",
    "require_jobs",
    "router",
    "run_out",
    "run_task_rows",
    "sse_frame",
    "system_trace_id",
]
