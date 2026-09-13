"""The worker: turns a queued ``runs`` row into measured evidence.

A :class:`Worker` polls the :class:`~crb.store.jobs.JobQueue`, claims one run at
a time and executes it by ``kind``:

=========== ====================================================================
``setup``   the environment phase — install the repo's test dependencies under
            ``<home>/envs/<repo>`` via the runner's ``setup`` (the ONLY network
            phase); ``counts_json`` is the :class:`~crb.core.runners.SetupResult`
``probe``   run the repo's known-green probe scope; write ``repos.probe_status``;
            runs ``setup`` first when the environment is not ready (``setup.auto``)
``mine``    :func:`crb.core.mine.mine` → upsert ``tasks`` rows (RED / baseline / gold)
``replay``  :func:`crb.core.run.run` in *sighted* mode over the ladder → grade rows,
            evidence packs (file + DB), events
``blind``   the same in *blind* mode (held-out tests; the brief carries none)
``oracle``  :func:`crb.core.oracle.mutation.score_task` per task → ``oracle.score``
            events, mean strength in ``counts_json``
``controls`` the negative-controls gate → one ``controls.report`` event
=========== ====================================================================

Every step event goes through one :class:`~crb.observability.events.Emitter`
bound to ``trace_id = run.id`` into a :class:`~crb.observability.events.MultiSink`
of :class:`~crb.store.events.DbEventSink` (the API's SSE source) and a
:class:`~crb.observability.events.JsonlSink` under ``<home>/events/<run_id>.jsonl``
(the operator's local copy). A heartbeat thread refreshes the run's liveness
while it executes; a stale heartbeat lets another worker reclaim it.

Honesty properties
------------------
* **Fail closed.** A sandbox that cannot be provided
  (:class:`~crb.core.execution.SandboxUnavailable`) ends the run ``failed`` with
  ``sandbox unavailable: …`` and whatever counts were measured — never a local
  fallback, never a pass. Any other exception ends the run ``failed`` with the
  (redacted) error.
* **Verdicts come from the core.** The worker never grades; it wires the
  orchestrator, the builders and the ledger together and records what they say.
  ``runs.counts_json`` for a replay is exactly :class:`~crb.core.run.RunSummary`.
* **Packs before rows.** The DB ledger wrapper stores the evidence pack the core
  wrote to disk *before* appending the row that references it, so a clean row in
  the DB always has its pack in the DB ("no pack ⇒ no Q1").
* **Cancellation is cooperative and recorded.** ``stop`` is polled between
  tasks; a cancelled run ends ``cancelled`` with its partial counts.
* **Resumable event cursors.** A reclaimed run's emitter resumes ``seq`` after
  the last stored event so ``?after=<seq>`` never replays or skips.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from crb.builders.adapter import (
    as_run_ledger,
    build_fn_for,
    ladder_from_spec,
    ladder_labels,
)
from crb.builders.base import Budget, EscalationLadder
from crb.core.execution import DockerSettings, Executor, SandboxUnavailable, make_executor
from crb.core.git import GitRepo
from crb.core.grade import MODE_BLIND, MODE_SIGHTED
from crb.core.ledger import GradeRow, false_q1_total
from crb.core.mine import MineOutcome, mine
from crb.core.oracle.controls import (
    CONTROLS,
    CONTROLS_VERSION,
    ControlRow,
    ControlsReport,
    controls_for_task,
)
from crb.core.oracle.mutation import (
    DEFAULT_MAX_MUTANTS,
    CommitOracleScore,
    aggregate_by_cell,
    score_task,
)
from crb.core.redact import redact_and_cap
from crb.core.run import RunSpec, RunSummary
from crb.core.run import run as core_run
from crb.core.runners import get_runner
from crb.core.runners.base import BARE, BaseRunner, SetupResult, SetupStep
from crb.core.spec import POOL_HARD, POOL_STANDARD, RepoConfig, TaskSpec
from crb.core.stats import mean
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace
from crb.observability import metrics
from crb.observability.events import Emitter, JsonlSink, MultiSink, StepStatus
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.events import DbEventSink, last_seq
from crb.store.jobs import (
    KIND_BLIND,
    KIND_CONTROLS,
    KIND_MINE,
    KIND_ORACLE,
    KIND_PROBE,
    KIND_REPLAY,
    KIND_SETUP,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    JobQueue,
    StaleClaim,
)
from crb.store.ledger import DbLedger
from crb.store.models import EvidencePackRow, Repo, Run, Task

_LOG = logging.getLogger(__name__)

PROBE_OK = "ok"
PROBE_FAILED = "failed"

#: action prefix → StepEvent stage, for the core's plain ``on_event`` callbacks.
_STAGE_FOR_PREFIX: dict[str, str] = {
    "mine": "mine",
    "prep": "prep",
    "build": "build",
    "builder": "build",
    "grade": "grade",
    "ledger": "ledger",
    "oracle": "oracle",
    "controls": "oracle",
    "run": "system",
    "probe": "system",
    "setup": "prep",
}


def stage_for(action: str) -> str:
    """``grade.belt`` → ``grade``; unknown prefixes land in ``system``."""
    return _STAGE_FOR_PREFIX.get(action.split(".", 1)[0], "system")


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerSettings:
    """Everything a worker needs, resolved once by the entrypoint.

    ``executor`` is the default kind (``local`` | ``docker``); a run may override
    it in ``params.executor``. ``docker`` carries the sandbox image and caps; when
    it is ``None`` and a docker run names no image (``params.image`` or the repo's
    ``sandbox_image``), the run fails closed.
    """

    database_url: str = ""
    home: Path = Path(".crb")
    executor: str = "local"
    docker: DockerSettings | None = None
    worker_id: str = ""
    poll_s: float = 2.0
    heartbeat_s: float = 10.0
    stale_after_s: float = 120.0
    kinds: tuple[str, ...] = ()
    keep_worktrees: bool = False
    max_reclaims: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "home", Path(self.home).expanduser())
        object.__setattr__(self, "worker_id", self.worker_id or default_worker_id())
        object.__setattr__(self, "kinds", tuple(self.kinds))
        if self.poll_s <= 0 or self.heartbeat_s <= 0 or self.stale_after_s <= 0:
            raise ValueError("poll_s, heartbeat_s and stale_after_s must be positive")


# ---------------------------------------------------------------------------
# Per-run context
# ---------------------------------------------------------------------------


class _ResumingEmitter(Emitter):
    """An emitter whose ``seq`` continues after the last stored event of the trace."""

    def __init__(
        self, sink: MultiSink, *, trace_id: str, actor: str, repo: str, start: int
    ) -> None:
        super().__init__(sink, trace_id=trace_id, actor=actor, repo=repo)
        self._seq = max(0, int(start))


@dataclass
class RunContext:
    """What one run's executor carries: the run, its repo, its harness, its stream,
    and the interim ``counts`` kept in step with the queue (so a failure keeps them)."""

    run: Run
    emitter: Emitter
    config: RepoConfig
    git: GitRepo
    counts: dict[str, Any] = field(default_factory=dict)
    _runner: BaseRunner | None = None
    _executor: Executor | None = None

    @property
    def params(self) -> Mapping[str, Any]:
        return dict(self.run.params_json or {})

    @property
    def timeout(self) -> int:
        return int(self.params.get("timeout") or 0)

    def on_event(self, action: str, payload: Mapping[str, Any]) -> None:
        """The core's ``on_event(action, payload)`` callback, routed by stage."""
        self.emitter.on_event(stage_for(action))(action, payload)

    def emit(self, stage: str, action: str, **payload: Any) -> None:
        self.emitter.emit(stage, action, **payload)


class _RunLedger:
    """``RunSpec.ledger`` for a DB run: mirror the pack, record metrics, append.

    The core writes ``<evidence_dir>/<pack_hash>.json`` before it appends the
    row; this wrapper stores that pack in the DB **before** the row so the DB
    can never hold a clean row whose pack it lacks.
    """

    def __init__(
        self,
        ledger: DbLedger,
        factory: sessionmaker[Session],
        evidence_dir: Path,
        ctx: RunContext,
        runner_name: str,
    ) -> None:
        self._ledger = ledger
        self._factory = factory
        self._evidence_dir = evidence_dir
        self._ctx = ctx
        self._runner_name = runner_name

    def _pack_body(self, pack_hash: str) -> dict[str, Any] | None:
        try:
            body = evidence_pack_from_file(self._evidence_dir, pack_hash)
        except (OSError, ValueError) as exc:
            body = None
            note = f"{type(exc).__name__}: {exc}"
        else:
            note = "" if body is not None else "pack file not found"
        if body is None:
            self._ctx.emit(
                "ledger",
                "ledger.pack_missing",
                status=StepStatus.ERROR,
                error=note,
                pack=pack_hash,
            )
        return body

    def _store_pack(self, row: GradeRow, body: Mapping[str, Any]) -> None:
        try:
            with self._factory() as s:
                if s.get(EvidencePackRow, row.evidence_pack_hash) is None:
                    s.add(
                        EvidencePackRow(
                            pack_hash=row.evidence_pack_hash,
                            repo=row.repo,
                            task_id=row.task_id,
                            run_id=row.run_id,
                            body_json=dict(body),
                        )
                    )
                    s.commit()
        except Exception as exc:  # the file on disk remains the evidence; record it
            self._ctx.emit(
                "ledger",
                "ledger.pack_store_error",
                status=StepStatus.ERROR,
                error=f"{type(exc).__name__}: {exc}",
                pack=row.evidence_pack_hash,
            )

    def append(self, row: GradeRow) -> GradeRow:
        body = self._pack_body(row.evidence_pack_hash) if row.evidence_pack_hash else None
        if body is not None:
            self._store_pack(row, body)
        chained = self._ledger.append(row)
        grade = dict(body.get("grade") or {}) if body else {}
        metrics.record_grade(
            repo=row.repo,
            runner=self._runner_name,
            clean=row.clean,
            disqualified=row.disqualified,
            error=row.error,
            belts={
                b: getattr(row, b)
                for b in ("tests_unmodified", "target_green", "no_new_failures", "source_changed")
            },
            duration_s=float(grade.get("duration_s") or 0.0),
        )
        metrics.record_build(
            builder=row.builder,
            model=row.model,
            tokens_in=row.tokens_in,
            tokens_out=row.tokens_out,
            cost_usd=row.cost_usd,
            latency_s=row.latency_s,
        )
        c = self._ctx.counts
        c["rows"] = int(c.get("rows", 0)) + 1
        if row.clean:
            c["clean"] = int(c.get("clean", 0)) + 1
        if row.disqualified:
            c["disqualified"] = int(c.get("disqualified", 0)) + 1
        if row.error:
            c["errors"] = int(c.get("errors", 0)) + 1
        return chained


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

Handler = Callable[[RunContext], tuple[str, dict[str, Any], str]]


class Worker:
    def __init__(self, settings: WorkerSettings, *, engine: Engine | None = None) -> None:
        self.settings = settings
        self.engine = engine or make_engine(settings.database_url or None)
        init_db(self.engine)
        self.factory = make_session_factory(self.engine)
        self.queue = JobQueue(self.factory, max_reclaims=settings.max_reclaims)
        self.ledger = DbLedger(self.factory)
        self.worker_id = settings.worker_id
        self._handlers: dict[str, Handler] = {
            KIND_SETUP: self._run_setup,
            KIND_PROBE: self._run_probe,
            KIND_MINE: self._run_mine,
            KIND_REPLAY: lambda ctx: self._run_replay(ctx, mode=MODE_SIGHTED),
            KIND_BLIND: lambda ctx: self._run_replay(ctx, mode=MODE_BLIND),
            KIND_ORACLE: self._run_oracle,
            KIND_CONTROLS: self._run_controls,
        }

    # --- layout ---------------------------------------------------------------
    @property
    def home(self) -> Path:
        return self.settings.home

    def events_path(self, run_id: str) -> Path:
        return self.home / "events" / f"{run_id}.jsonl"

    @property
    def evidence_dir(self) -> Path:
        return self.home / "evidence"

    @property
    def scratch_dir(self) -> Path:
        return self.home / "scratch"

    def transcripts_dir(self, run_id: str) -> Path:
        return self.home / "transcripts" / run_id

    def env_dir(self, repo: str) -> Path:
        """Where a repo's runner keeps environment state that must not live in the
        clone (the Python venv): ``<home>/envs/<repo>``."""
        return self.home / "envs" / repo

    # --- loop -----------------------------------------------------------------
    def run_once(self) -> Run | None:
        """Reclaim stale runs, claim one, execute it to a terminal status."""
        for r in self.queue.reclaim_stale(self.settings.stale_after_s):
            _LOG.warning("run %s reclaimed → %s", r.id[:8], r.status)
        run = self.queue.claim_next(self.worker_id, kinds=self.settings.kinds or None)
        if run is None:
            return None
        self.execute(run)
        return self.queue.get(run.id)

    def run_forever(self, stop: threading.Event) -> None:
        """Poll until ``stop`` is set. One run at a time; never raises."""
        _LOG.info("worker %s started (executor=%s)", self.worker_id, self.settings.executor)
        while not stop.is_set():
            try:
                run = self.run_once()
            except Exception:  # the loop must survive anything a run throws
                _LOG.exception("worker loop error")
                run = None
            if run is None:
                stop.wait(self.settings.poll_s)
        _LOG.info("worker %s stopped", self.worker_id)

    # --- execution ------------------------------------------------------------
    def _emitter(self, run: Run) -> Emitter:
        sink = MultiSink(DbEventSink(self.factory), JsonlSink(self.events_path(run.id)))
        return _ResumingEmitter(
            sink,
            trace_id=run.id,
            actor=run.actor,
            repo=run.repo,
            start=last_seq(self.factory, run.id),
        )

    def _heartbeat_thread(self, run: Run, stop: threading.Event) -> threading.Thread:
        def loop() -> None:
            while not stop.wait(self.settings.heartbeat_s):
                try:
                    if not self.queue.heartbeat(run.id, worker_id=self.worker_id):
                        _LOG.warning("heartbeat refused for run %s (reclaimed?)", run.id[:8])
                        return
                except Exception:
                    _LOG.exception("heartbeat failed for run %s", run.id[:8])

        t = threading.Thread(target=loop, name=f"crb-heartbeat-{run.id[:8]}", daemon=True)
        t.start()
        return t

    def execute(self, run: Run) -> None:
        """Execute a *claimed* run and finish it. Never raises."""
        emitter = self._emitter(run)
        emitter.emit("system", "run.claimed", worker=self.worker_id, kind=run.kind, mode=run.mode)
        hb_stop = threading.Event()
        hb = self._heartbeat_thread(run, hb_stop)
        ctx: RunContext | None = None
        status, error = STATUS_FAILED, ""
        counts: dict[str, Any] = {}
        started = time.monotonic()
        try:
            if self.queue.is_cancel_requested(run.id):
                status, error = STATUS_CANCELLED, ""
            else:
                handler = self._handlers.get(run.kind)
                if handler is None:
                    raise ValueError(f"unknown run kind {run.kind!r}")
                config, git = self._load_repo(run.repo)
                ctx = RunContext(run=run, emitter=emitter, config=config, git=git)
                status, counts, error = handler(ctx)
        except SandboxUnavailable as exc:
            status = STATUS_FAILED
            error = redact_and_cap(f"sandbox unavailable: {exc}", max_chars=1000)
            counts = dict(ctx.counts) if ctx else {}
            metrics.sandbox_unavailable_total.inc()
            emitter.error("system", "run.error", exc)
            if run.kind == KIND_PROBE:
                self._set_probe(run.repo, PROBE_FAILED, error)
        except Exception as exc:
            status = STATUS_FAILED
            error = redact_and_cap(f"{type(exc).__name__}: {exc}", max_chars=1000)
            counts = dict(ctx.counts) if ctx else {}
            _LOG.exception("run %s failed", run.id[:8])
            emitter.error("system", "run.error", exc)
        finally:
            hb_stop.set()
            hb.join(timeout=5)
        try:
            self.queue.finish(run.id, status, counts=counts, error=error, worker_id=self.worker_id)
        except StaleClaim as exc:  # reclaimed underneath us: the new owner's record stands
            _LOG.warning("run %s finish refused: %s", run.id[:8], exc)
            emitter.emit("system", "run.finish_refused", status=StepStatus.ERROR, error=str(exc))
            return
        metrics.runs_total.labels(run.kind, status).inc()
        emitter.emit(
            "system",
            "run.finished",
            status=StepStatus.ERROR if status == STATUS_FAILED else StepStatus.OK,
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
            final_status=status,
            counts=counts,
        )

    # --- repo / harness ----------------------------------------------------------
    def _load_repo(self, name: str) -> tuple[RepoConfig, GitRepo]:
        with self.factory() as s:
            row = s.get(Repo, name)
        if row is None:
            raise LookupError(f"repo {name!r} is not configured")
        cfg = dict(row.config_json or {})
        cfg.setdefault("language", row.language)
        cfg.setdefault("runner", row.runner)
        config = RepoConfig.from_dict(row.name, cfg)
        clone = row.clone_path or config.path
        if not clone:
            raise LookupError(f"repo {name!r} has no clone path")
        git = GitRepo(clone)
        if not git.is_repo():
            raise LookupError(f"repo {name!r}: {clone!r} is not a git repository")
        return config, git

    def _set_probe(self, name: str, status: str, detail: str) -> None:
        with self.factory() as s:
            row = s.get(Repo, name)
            if row is not None:
                row.probe_status = status
                row.probe_detail = redact_and_cap(detail, max_chars=4000)
                s.commit()

    def _runner(self, ctx: RunContext) -> BaseRunner:
        """The run's runner, bound to the repo's ``env_dir`` so a pytest runner
        without ``runner_opts.python`` resolves the interpreter setup built."""
        if ctx._runner is None:
            ctx._runner = get_runner(ctx.config)
            ctx._runner.env_dir = self.env_dir(ctx.run.repo)
        return ctx._runner

    def _executor(self, ctx: RunContext) -> Executor:
        """The run's executor. Docker is fail-closed: no image / no daemon → the
        run fails with ``sandbox unavailable``; there is no local fallback."""
        if ctx._executor is not None:
            return ctx._executor
        kind = str(ctx.params.get("executor") or self.settings.executor or "local")
        docker: DockerSettings | None = None
        if kind == "docker":
            docker = docker_settings_for(ctx.config, self.settings.docker, ctx.params)
        ctx._executor = make_executor(kind, docker=docker)
        ctx.emit("system", "run.executor", **ctx._executor.describe())
        return ctx._executor

    def _stamp(self, ctx: RunContext, **extra: Any) -> None:
        apparatus = {
            "apparatus_version": APPARATUS_VERSION,
            "runner": self._runner(ctx).name,
            "executor": self._executor(ctx).describe(),
            "worker": self.worker_id,
            **extra,
        }
        self.queue.set_apparatus(ctx.run.id, apparatus, worker_id=self.worker_id)

    def _progress(self, ctx: RunContext, done: int, total: int) -> None:
        self.queue.progress(ctx.run.id, done, total, ctx.counts, worker_id=self.worker_id)

    def _cancelled(self, ctx: RunContext) -> bool:
        return self.queue.is_cancel_requested(ctx.run.id)

    # --- tasks -------------------------------------------------------------------
    def _select_tasks(self, ctx: RunContext) -> list[TaskSpec]:
        """``params.task_ids`` in the order given (the core skips any that are not
        gold-clean, with an event), else every GOLD-CLEAN task of the repo; optionally
        filtered by ``params.pool`` and capped by ``params.limit``. Oldest-authored
        first so a capped run is deterministic."""
        p = ctx.params
        ids = [str(i) for i in (p.get("task_ids") or [])]
        pool = str(p.get("pool") or "")
        limit = int(p.get("limit") or 0)
        with self.factory() as s:
            q = select(Task).where(Task.repo == ctx.run.repo)
            q = q.where(Task.task_id.in_(ids)) if ids else q.where(Task.gold_clean.is_(True))
            if pool:
                q = q.where(Task.pool == pool)
            rows = s.execute(q.order_by(Task.authored, Task.task_id)).scalars().all()
        specs = [TaskSpec.from_dict(r.spec_json) for r in rows]
        if ids:
            by_id = {t.task_id: t for t in specs}
            missing = [i for i in ids if i not in by_id]
            if missing:
                ctx.emit(
                    "system",
                    "run.skip",
                    status=StepStatus.SKIPPED,
                    reason="unknown task ids",
                    task_ids=missing,
                )
            specs = [by_id[i] for i in ids if i in by_id]
        if limit > 0:
            specs = specs[:limit]
        return specs

    def _upsert_task(self, task: TaskSpec) -> None:
        with self.factory() as s:
            s.merge(
                Task(
                    repo=task.repo,
                    task_id=task.task_id,
                    pool=task.pool,
                    size=task.size,
                    capability_class=task.capability_class,
                    language=task.language,
                    authored=task.authored,
                    subject=task.subject,
                    red_checked=task.red_checked,
                    gold_clean=task.gold_clean,
                    spec_json=task.to_dict(),
                )
            )
            s.commit()

    def _known_task_ids(self, repo: str) -> frozenset[str]:
        with self.factory() as s:
            return frozenset(
                s.execute(select(Task.task_id).where(Task.repo == repo)).scalars().all()
            )

    # --- kinds ---------------------------------------------------------------------
    def _setup(self, ctx: RunContext) -> SetupResult:
        """Run the runner's setup for the run's repo, streaming ``setup.step`` events.

        Every step is emitted as it finishes (its tail is already redacted by the
        core) and the interim ``counts`` carry the steps so far, so a run that
        dies mid-install still shows what ran.
        """
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        env_dir = self.env_dir(ctx.run.repo)
        steps: list[SetupStep] = []

        def on_step(step: SetupStep) -> None:
            steps.append(step)
            how = "timed out" if step.timed_out else f"rc={step.rc}"
            ctx.emit(
                "prep",
                "setup.step",
                status=StepStatus.OK if step.ok else StepStatus.ERROR,
                error="" if step.ok else f"step {len(steps)} failed ({how})",
                n=len(steps),
                duration_ms=int(step.duration_s * 1000),
                **step.to_dict(),
            )
            ctx.counts["steps"] = [s.to_dict() for s in steps]
            self._progress(ctx, len(steps), len(steps))

        ctx.emit(
            "prep",
            "setup.start",
            env_dir=str(env_dir),
            path=str(ctx.git.path),
            runner=runner.name,
        )
        result = runner.setup(
            executor, ctx.git.path, env_dir=env_dir, timeout=ctx.timeout, on_step=on_step
        )
        ctx.emit(
            "prep",
            "setup.done",
            status=StepStatus.OK if result.ok else StepStatus.ERROR,
            error="" if result.ok else result.note,
            duration_ms=int(result.duration_s * 1000),
            ok=result.ok,
            note=result.note,
            steps=len(result.steps),
        )
        return result

    def _run_setup(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        self._stamp(ctx, env_dir=str(self.env_dir(ctx.run.repo)))
        result = self._setup(ctx)
        counts: dict[str, Any] = {**result.to_dict(), "env_dir": str(self.env_dir(ctx.run.repo))}
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._progress(ctx, len(result.steps), len(result.steps))
        if result.ok:
            return STATUS_SUCCEEDED, counts, ""
        error = f"setup failed: {result.note}"
        if result.last_tail:
            error += "\n" + result.last_tail
        return STATUS_FAILED, counts, redact_and_cap(error, max_chars=1000)

    def _run_probe(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        self._stamp(ctx)
        env_dir = self.env_dir(ctx.run.repo)
        # The environment phase runs itself when needed. A sandbox image is its own
        # environment, so the host-side readiness question does not apply there.
        if executor.name != "docker" and not runner.environment_ready(ctx.git.path, env_dir):
            ctx.emit("prep", "setup.auto", reason="environment not ready", env_dir=str(env_dir))
            setup = self._setup(ctx)
            ctx.counts.pop("steps", None)  # interim progress only; the record is below
            ctx.counts["setup"] = setup.to_dict()
            if not setup.ok:
                why = f"setup failed: {setup.note}"
                detail = why + ("\n" + setup.last_tail if setup.last_tail else "")
                self._set_probe(ctx.run.repo, PROBE_FAILED, detail)
                ctx.emit("system", "probe.done", status=StepStatus.ERROR, error=why, green=False)
                return STATUS_FAILED, dict(ctx.counts), redact_and_cap(detail, max_chars=1000)
        scope: tuple[str, ...] = tuple(ctx.config.probe.split()) if ctx.config.probe else BARE
        ctx.emit("system", "probe.start", scope=list(scope), path=str(ctx.git.path))
        try:
            result = runner.run(executor, ctx.git.path, scope, timeout=ctx.timeout)
        except SandboxUnavailable:
            raise
        except Exception as exc:
            detail = f"probe error: {type(exc).__name__}: {exc}"
            self._set_probe(ctx.run.repo, PROBE_FAILED, detail)
            raise
        ok = result.green
        why = (
            "timed out"
            if result.timed_out
            else result.parse_error or (f"rc={result.returncode}" if not ok else "")
        )
        detail = (f"{why}\n" if why else "") + result.tail
        self._set_probe(ctx.run.repo, PROBE_OK if ok else PROBE_FAILED, detail)
        counts = {
            "green": ok,
            "returncode": result.returncode,
            "failing": len(result.failing),
            "timed_out": result.timed_out,
            "parse_error": result.parse_error,
            "duration_s": round(result.duration_s, 3),
            "scope": list(scope),
        }
        if "setup" in ctx.counts:
            counts["setup"] = ctx.counts["setup"]
        ctx.counts.update(counts)
        ctx.emit(
            "system",
            "probe.done",
            status=StepStatus.OK if ok else StepStatus.ERROR,
            error="" if ok else f"probe not green: {why}",
            **counts,
        )
        self._progress(ctx, 1, 1)
        if ok:
            return STATUS_SUCCEEDED, counts, ""
        return STATUS_FAILED, counts, f"probe not green: {why}"

    def _run_mine(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        p = ctx.params
        pool = str(p.get("pool") or POOL_STANDARD)
        if pool not in {POOL_STANDARD, POOL_HARD}:
            raise ValueError(f"pool must be {POOL_STANDARD!r} or {POOL_HARD!r}")
        target = int(p.get("target") or 0)
        max_candidates = int(p.get("max_candidates") or 0)
        gold = bool(p.get("gold", True))
        ref = str(p.get("ref") or "HEAD")
        want = target or int(
            ctx.config.mining.get("target_valid" if pool == POOL_STANDARD else "hard_target", 25)
        )
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        self._stamp(ctx, pool=pool, gold=gold, ref=ref)
        known = self._known_task_ids(ctx.run.repo)
        counts: dict[str, Any] = {
            "examined": 0,
            "found": 0,
            "gold_clean": 0,
            "gold_dirty": 0,
            "skipped": 0,
            "known": len(known),
            "pool": pool,
        }
        ctx.counts.update(counts)
        self._progress(ctx, 0, want)
        outcomes: Iterator[MineOutcome] = mine(
            ctx.git,
            ctx.config,
            runner=runner,
            executor=executor,
            scratch=self.scratch_dir,
            pool=pool,
            target_count=target,
            max_candidates=max_candidates,
            known=known,
            gold=gold,
            timeout=ctx.timeout,
            ref=ref,
            on_event=ctx.on_event,
        )
        cancelled = False
        while True:
            if self._cancelled(ctx):
                cancelled = True
                break
            try:
                out = next(outcomes)
            except StopIteration:
                break
            counts["examined"] += 1
            if out.task is None:
                counts["skipped"] += 1
            else:
                counts["found"] += 1
                if out.task.gold_clean is False:
                    counts["gold_dirty"] += 1
                elif out.task.gold_clean is True:
                    counts["gold_clean"] += 1
                self._upsert_task(out.task)
                ctx.emit(
                    "mine",
                    "mine.task",
                    task_id=out.task.task_id,
                    size=out.task.size,
                    capability_class=out.task.capability_class,
                    gold_clean=out.task.gold_clean,
                    duration_ms=int(out.duration_s * 1000),
                )
            ctx.counts.update(counts)
            self._progress(ctx, counts["found"], want)
        if cancelled:
            ctx.emit("mine", "mine.cancelled", **counts)
            return STATUS_CANCELLED, counts, ""
        return STATUS_SUCCEEDED, counts, ""

    def _ladder(self, ctx: RunContext) -> EscalationLadder:
        run = ctx.run
        labels: list[str] = [str(x) for x in (ctx.params.get("ladder") or run.ladder_json or [])]
        if not labels and run.builder and run.model:
            labels = [f"{run.builder}:{run.model}" + (f"@{run.provider}" if run.provider else "")]
        if not labels:
            raise ValueError("a replay run needs a ladder (rung labels) or builder + model")
        provider = str(run.provider or ctx.params.get("provider") or "")
        return ladder_from_spec(labels, default_provider=provider)

    def _run_replay(self, ctx: RunContext, *, mode: str) -> tuple[str, dict[str, Any], str]:
        run = ctx.run
        p = ctx.params
        tasks = self._select_tasks(ctx)
        total = len(tasks)
        ctx.counts.update({"tasks": 0, "total": total, "rows": 0, "clean": 0})
        ladder = self._ladder(ctx)
        budget = Budget.from_dict(dict(p.get("budget") or {}))
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        run_ledger = _RunLedger(self.ledger, self.factory, self.evidence_dir, ctx, runner.name)
        spec = RunSpec(
            run_id=run.id,
            config=ctx.config,
            runner=runner,
            executor=executor,
            scratch=self.scratch_dir,
            ledger=as_run_ledger(run_ledger),
            evidence_dir=self.evidence_dir,
            mode=mode,
            ladder=ladder_labels(ladder),
            actor=run.actor,
            timeout=ctx.timeout,
            corpus_sha=str(p.get("corpus_sha") or ""),
            policy_version=str(p.get("policy_version") or ""),
            keep_worktrees=bool(p.get("keep_worktrees", self.settings.keep_worktrees)),
            extra={"worker": self.worker_id, "budget": budget.to_dict()},
        )
        self.queue.set_apparatus(run.id, spec.apparatus().to_dict(), worker_id=self.worker_id)
        build_fn = build_fn_for(
            ladder,
            budget=budget,
            runner=runner,
            executor=executor,
            config=ctx.config,
            on_event=ctx.on_event,
            message_for=lambda t: ctx.git.message(t.task_id),
            transcript_dir=self.transcripts_dir(run.id) if p.get("keep_transcripts") else None,
        )
        self._progress(ctx, 0, total)

        def tracked() -> Iterator[TaskSpec]:
            for i, t in enumerate(tasks):
                ctx.counts["tasks"] = i
                self._progress(ctx, i, total)
                yield t

        summary: RunSummary = core_run(
            spec,
            ctx.git,
            tracked(),
            build_fn,
            on_event=ctx.on_event,
            stop=lambda: self._cancelled(ctx),
        )
        counts = summary.to_dict()
        counts["total"] = total
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._progress(ctx, summary.tasks, total)
        self._ledger_health()
        if summary.stopped_reason == "cancelled":
            return STATUS_CANCELLED, counts, ""
        if summary.stopped_reason:
            return STATUS_FAILED, counts, summary.stopped_reason
        if summary.tasks and summary.errors >= summary.rows:
            # Every attempt failed on infrastructure (no credential, provider 402, sandbox…):
            # the rows are honest (never clean) but the run did not measure anything, so it
            # must not read as a success. The first error is surfaced as the run's error.
            first = next((r.error for r in self.ledger.rows(run_id=spec.run_id) if r.error), "")
            return STATUS_FAILED, counts, f"all {summary.rows} attempt(s) errored: {first}"[:1000]
        return STATUS_SUCCEEDED, counts, ""

    def _ledger_health(self) -> None:
        try:
            rows = list(self.ledger.rows())
            metrics.set_ledger_health(rows=len(rows), false_q1=false_q1_total(rows))
        except Exception:  # metrics are observability, never a verdict
            _LOG.exception("ledger health metric failed")

    def _run_oracle(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        run = ctx.run
        tasks = self._select_tasks(ctx)
        max_mutants = int(ctx.params.get("max_mutants") or DEFAULT_MAX_MUTANTS)
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        self._stamp(ctx, max_mutants=max_mutants)
        total = len(tasks)
        scores: list[CommitOracleScore] = []
        ctx.counts.update({"tasks": 0, "total": total, "scoreable": 0})
        self._progress(ctx, 0, total)
        cancelled = False
        for i, task in enumerate(tasks):
            if self._cancelled(ctx):
                cancelled = True
                break
            dest = self.scratch_dir / f"oracle-{ctx.config.name}-{task.short_id}-{run.id[:8]}"
            with Workspace.create(ctx.git, task.task_id, dest, config=ctx.config) as ws:
                ws.overlay_tests(task.test_files)
                ws.overlay_sources(task.src_files)  # the GOLD state: target GREEN
                score = score_task(
                    ws,
                    task,
                    config=ctx.config,
                    runner=runner,
                    executor=executor,
                    max_mutants=max_mutants,
                    timeout=ctx.timeout,
                    on_event=ctx.on_event,
                )
            scores.append(score)
            body = score.to_dict()
            body.pop("task_id", None)  # lifted to the event envelope
            ctx.emit("oracle", "oracle.score", task_id=task.task_id, **body)
            ctx.counts["tasks"] = i + 1
            ctx.counts["scoreable"] = sum(1 for s in scores if s.scoreable)
            self._progress(ctx, i + 1, total)
        counts = _oracle_counts(scores, total=total)
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._progress(ctx, len(scores), total)
        return (STATUS_CANCELLED if cancelled else STATUS_SUCCEEDED), counts, ""

    def _run_controls(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        tasks = self._select_tasks(ctx)
        controls: Sequence[str] = tuple(str(c) for c in (ctx.params.get("controls") or CONTROLS))
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        self._stamp(ctx, controls=list(controls))
        total = len(tasks)
        rows: list[ControlRow] = []
        ctx.counts.update({"tasks": 0, "total": total, "rows": 0})
        self._progress(ctx, 0, total)
        cancelled = False
        for i, task in enumerate(tasks):
            if self._cancelled(ctx):
                cancelled = True
                break
            rows.extend(
                controls_for_task(
                    ctx.git,
                    task,
                    config=ctx.config,
                    runner=runner,
                    executor=executor,
                    scratch=self.scratch_dir,
                    controls=controls,
                    timeout=ctx.timeout,
                    on_event=ctx.on_event,
                )
            )
            ctx.counts.update({"tasks": i + 1, "rows": len(rows)})
            self._progress(ctx, i + 1, total)
        report = ControlsReport(
            tuple(rows),
            {
                "apparatus_version": APPARATUS_VERSION,
                "controls_version": CONTROLS_VERSION,
                "controls": list(controls),
                "repo": ctx.config.name,
                "runner": runner.name,
                "executor": executor.describe(),
                "worker": self.worker_id,
                "complete": not cancelled,
            },
        )
        ctx.emit("oracle", "controls.report", **report.to_dict())
        counts = {
            "tasks": len(report.task_ids),
            "total": total,
            "rows": len(report.rows),
            "violations": len(report.violations),
            "escapes": len(report.escapes),
            "not_constructible": len(report.not_constructible),
            "skipped": len(report.skipped),
            "passed": report.passed,
            "complete": not cancelled,
        }
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._progress(ctx, counts["tasks"], total)
        if cancelled:
            return STATUS_CANCELLED, counts, ""
        if not report.passed:
            return (
                STATUS_FAILED,
                counts,
                f"negative-controls gate FAILED: {len(report.violations)} violation(s) "
                "(an instrument bug, never a model result)",
            )
        return STATUS_SUCCEEDED, counts, ""


def docker_settings_for(
    config: RepoConfig, base: DockerSettings | None, params: Mapping[str, Any]
) -> DockerSettings:
    """The sandbox settings for one run: ``params.image`` > the worker's configured
    image > the repo's ``sandbox_image``; caps come from the worker's settings.
    No image anywhere → :class:`SandboxUnavailable` (raised by ``DockerSettings``)."""
    image = str(params.get("image") or "") or (base.image if base else "") or config.sandbox_image
    if base is not None and image == base.image:
        return base
    if base is None:
        return DockerSettings(image=image)
    return DockerSettings(
        image=image,
        memory=base.memory,
        cpus=base.cpus,
        pids_limit=base.pids_limit,
        user=base.user,
        workdir=base.workdir,
        tmp_size=base.tmp_size,
        extra_ro_mounts=dict(base.extra_ro_mounts),
        docker_binary=base.docker_binary,
    )


def _oracle_counts(scores: Sequence[CommitOracleScore], *, total: int) -> dict[str, Any]:
    """The run summary for an oracle run: pooled AND per-task mean strength, each
    with its denominator, plus the per-cell roll-up."""
    scoreable = [s for s in scores if s.scoreable]
    mutants = sum(s.total for s in scoreable)
    killed = sum(s.killed for s in scoreable)
    strengths = [s.oracle_strength for s in scoreable if s.oracle_strength is not None]
    return {
        "tasks": len(scores),
        "total": total,
        "scoreable": len(scoreable),
        "unscoreable": len(scores) - len(scoreable),
        "mutants": mutants,
        "killed": killed,
        "escaped": mutants - killed,
        "errors": sum(s.errors for s in scores),
        "oracle_strength": round(killed / mutants, 4) if mutants else None,
        "oracle_strength_mean": round(mean(strengths), 4) if strengths else None,
        "cells": aggregate_by_cell(scores),
    }


def evidence_pack_from_file(evidence_dir: Path, pack_hash: str) -> dict[str, Any] | None:
    """Read a pack the core wrote (``<evidence_dir>/<pack_hash>.json``)."""
    p = evidence_dir / f"{pack_hash}.json"
    if not p.exists():
        return None
    body = json.loads(p.read_text(encoding="utf-8"))
    return dict(body) if isinstance(body, dict) else None


__all__ = [
    "PROBE_FAILED",
    "PROBE_OK",
    "RunContext",
    "Worker",
    "WorkerSettings",
    "default_worker_id",
    "docker_settings_for",
    "evidence_pack_from_file",
    "stage_for",
]
