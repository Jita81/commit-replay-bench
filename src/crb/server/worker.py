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
``label``   intent-label every task of the repo that lacks one (or ``relabel``)
            through :func:`crb.builders.labeller.make_labeller` — the run's
            ``builder``/``model``/``provider`` + ``builder_config`` — re-writing
            ``tasks.spec_json`` / ``capability_class`` (the RESOLVED class) via the
            same upsert as ``mine``; a ``label.task`` event per task; the per-class
            summary, mean confidence and cost in ``counts_json``. Human labels are
            never overwritten. Never touches the diff body.
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
* **Clone once, by policy.** A repo registered by URL only is cloned on its first
  run (:meth:`Worker._load_repo`): https/ssh only, credentials redacted from every
  event and error, ``repo.clone.start`` / ``repo.clone.done`` on the run's trace,
  the path persisted so no later run clones again.
* **Builder config is recorded.** ``params.builder_config`` (from ``POST /runs``)
  is passed to every builder as constructor overrides AND stamped into the run's
  apparatus (``extra.builder_config``) so a row's method can be read back.
* **The budget is a measured variable, not a fixed cap.** A ladder entry may be an
  object rung ``{builder, model, provider?, budget?}``; its budget overrides the
  run's ``params.budget``, which overrides the builder's defaults (rung > run >
  default, per field). Every ledger row is stamped ``labels.budget_tier``
  (``<max_tool_calls>/<max_turns>/<wall_clock_s>``, see :func:`budget_tier`) and
  ``labels.rung_index`` so a sweep over budgets can be split after the fact — a
  blind rate quoted without its budget tier is not a claim.
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

from crb.builders import builder_for_rung
from crb.builders.adapter import (
    Preflight,
    as_run_ledger,
    build_fn_for,
    container_settings_from_env,
    ladder_labels,
    parse_rung_label,
)
from crb.builders.base import Budget, Builder, EscalationLadder, Rung
from crb.builders.budget import budget_for_rung
from crb.builders.labeller import make_labeller
from crb.core.classify import DEFAULT_MIN_CONFIDENCE, commit_evidence, label_summary
from crb.core.execution import DockerSettings, Executor, SandboxUnavailable, make_executor
from crb.core.git import (
    DEFAULT_CLONE_TIMEOUT_S,
    CloneUrlError,
    GitError,
    GitRepo,
    clone_repo,
    redact_url,
)
from crb.core.grade import MODE_BLIND, MODE_SIGHTED
from crb.core.ledger import GradeRow, false_q1_total, is_outage_error
from crb.core.mine import MineOutcome, mine
from crb.core.oracle.controls import (
    CONTROLS,
    CONTROLS_VERSION,
    ControlRow,
    ControlsReport,
    controls_for_task,
    transform_stamp,
)
from crb.core.oracle.mutation import (
    DEFAULT_MAX_MUTANTS,
    CommitOracleScore,
    aggregate_by_cell,
    score_task,
)
from crb.core.redact import redact_and_cap
from crb.core.run import BuildAttempt, RunSpec, RunSummary
from crb.core.run import run as core_run
from crb.core.runners import get_runner
from crb.core.runners.base import BARE, BaseRunner, SetupResult, SetupStep
from crb.core.spec import POOL_HARD, POOL_STANDARD, RepoConfig, TaskSpec
from crb.core.stats import mean
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace
from crb.factory.backlog import BacklogItem
from crb.factory.loop import FactoryLoop, FactorySpec, ItemOutcome
from crb.factory.testfirst import AuthoredTest
from crb.observability import metrics
from crb.observability.events import Emitter, JsonlSink, MultiSink, StepStatus
from crb.server.factory_state import FactoryHome
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.events import DbEventSink, last_seq
from crb.store.jobs import (
    KIND_BLIND,
    KIND_CONTROLS,
    KIND_FACTORY,
    KIND_LABEL,
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

#: Stop a build run after this many consecutive attempts the provider refused
#: (``failure_kind == outage``); ``params.outage_stop`` overrides, 0 disables.
DEFAULT_OUTAGE_STOP = 3

_LOG = logging.getLogger(__name__)

PROBE_OK = "ok"
PROBE_FAILED = "failed"

#: action prefix → StepEvent stage, for the core's plain ``on_event`` callbacks.
_STAGE_FOR_PREFIX: dict[str, str] = {
    "mine": "mine",
    "label": "mine",
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


#: Row labels the worker stamps per rung (``_RunLedger``). Hashed like every label.
LABEL_BUDGET_TIER = "budget_tier"
LABEL_RUNG_INDEX = "rung_index"


def budget_tier(budget: Budget) -> str:
    """The compact canonical tier of a budget: ``<max_tool_calls>/<max_turns>/<wall_clock_s>``
    (``25/25/900`` is the builder default). When a token or dollar cap is ALSO engaged it
    is appended (``…/tok=<n>`` / ``…/usd=<x>``) — two attempts that differ only in a cost
    cap were not the same experiment, and the label must not say they were."""
    tier = f"{budget.max_tool_calls}/{budget.max_turns}/{budget.wall_clock_s}"
    if budget.max_tokens:
        tier += f"/tok={budget.max_tokens}"
    if budget.max_cost_usd:
        tier += f"/usd={budget.max_cost_usd:g}"
    return tier


def rung_from_object(entry: Mapping[str, Any], *, default_provider: str = "") -> Rung:
    """An object rung ``{builder, model, provider?, budget?}`` → :class:`Rung` whose
    ``config`` carries ONLY the budget fields the rung set. ``builder_for_rung`` strips
    those before constructing the builder and :func:`budget_for_rung` overlays them on the
    run's budget — so a rung's budget overrides the run's, field by field, and nothing else
    on the rung reaches a builder constructor (the API refuses other keys; the worker
    refuses them again here because ``ladder_json`` is a stored document, not a request)."""
    unknown = set(entry) - {"builder", "model", "provider", "budget"}
    if unknown:
        raise ValueError(f"object rung carries unknown field(s) {sorted(unknown)}")
    budget = dict(entry.get("budget") or {})
    foreign = set(budget) - set(Budget.__dataclass_fields__)
    if foreign:
        raise ValueError(f"rung budget carries unknown field(s) {sorted(foreign)}")
    return Rung(
        builder=str(entry.get("builder") or ""),
        model=str(entry.get("model") or ""),
        provider=str(entry.get("provider") or "") or default_provider,
        config=budget,
    )


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
        *,
        trial_labels: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._ledger = ledger
        self._factory = factory
        self._evidence_dir = evidence_dir
        self._ctx = ctx
        self._runner_name = runner_name
        self._trial_labels = {k: dict(v) for k, v in (trial_labels or {}).items()}

    def _stamp(self, row: GradeRow) -> GradeRow:
        """Add the run-declared labels for this row's trial (``budget_tier``,
        ``rung_index`` — see :func:`trial_labels_for`) BEFORE the row is chained, so the
        hash commits to them. Only labels change: the verdict fields are copied verbatim
        and :class:`GradeRow` re-runs its invariants on the copy, so a stamp can never
        turn a red row clean. A trial the ladder does not know is left untouched."""
        extra = self._trial_labels.get(row.trial)
        if not extra:
            return row
        return GradeRow(**{**row.fields(), "labels": {**row.labels, **extra}})

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
        row = self._stamp(row)
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
            KIND_LABEL: self._run_label,
            KIND_FACTORY: self._run_factory,
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
                config, git = self._load_repo(run.repo, emitter)
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
    def _load_repo(self, name: str, emitter: Emitter | None = None) -> tuple[RepoConfig, GitRepo]:
        """The repo's config and clone. A row with a ``url`` but no usable clone
        (``clone_path`` empty or not a git repository) is cloned once into
        ``<home>/repos/<name>`` — full history, ``--no-tags``, 30-minute wall clock,
        URL policy-checked and redacted — and the path is persisted on the row and
        in ``config_json["path"]`` so every later run finds it. ``repo.clone.start`` /
        ``repo.clone.done`` (stage ``system``) carry the redacted URL, the duration and
        the head sha on the run's trace when ``emitter`` is given."""
        with self.factory() as s:
            row = s.get(Repo, name)
        if row is None:
            raise LookupError(f"repo {name!r} is not configured")
        cfg = dict(row.config_json or {})
        cfg.setdefault("language", row.language)
        cfg.setdefault("runner", row.runner)
        config = RepoConfig.from_dict(row.name, cfg)
        clone = row.clone_path or config.path
        url = str(row.url or config.url or "").strip()
        if clone and GitRepo(clone).is_repo():
            return config, GitRepo(clone)
        if not url:
            if not clone:
                raise LookupError(f"repo {name!r} has no clone path")
            raise LookupError(f"repo {name!r}: {clone!r} is not a git repository")
        dest = self.home / "repos" / name
        safe_url = redact_url(url)
        started = time.monotonic()
        if emitter is not None:
            emitter.emit("system", "repo.clone.start", url=safe_url, dest=str(dest))
        try:
            head = clone_repo(url, dest, timeout=DEFAULT_CLONE_TIMEOUT_S)
        except (CloneUrlError, GitError) as exc:
            if emitter is not None:
                emitter.error("system", "repo.clone.done", exc, url=safe_url, dest=str(dest))
            raise LookupError(
                f"repo {name!r}: clone of {safe_url} failed: {redact_and_cap(str(exc), max_chars=500)}"
            ) from exc
        with self.factory() as s:
            fresh = s.get(Repo, name)
            if fresh is not None:
                fresh.clone_path = str(dest)
                fresh.config_json = {**dict(fresh.config_json or {}), "path": str(dest)}
                s.commit()
        if emitter is not None:
            emitter.emit(
                "system",
                "repo.clone.done",
                duration_ms=int((time.monotonic() - started) * 1000),
                url=safe_url,
                dest=str(dest),
                head=head,
            )
        return RepoConfig.from_dict(row.name, {**cfg, "path": str(dest)}), GitRepo(dest)

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
        # The cancel token: a requested cancel kills the running test process (local) or
        # container (docker) instead of waiting for the wall-clock timeout.
        ctx._executor = make_executor(kind, docker=docker, cancel=lambda: self._cancelled(ctx))
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
        # `limit` is the API/UI's generic bound (POST /runs.limit); `target` is the CLI's name.
        target = int(p.get("target") or p.get("limit") or 0)
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
        # `task_ids` = RE-QUALIFY these commits (the miner changed: a new rule, a fixed
        # runner). They are walked again whether or not they are known, and `_upsert_task`
        # replaces the stored spec; a sha that no longer qualifies stays as it was and the
        # run's `mine.skip` event says why. Grade rows are never touched.
        ids = [str(i) for i in (p.get("task_ids") or [])]
        # one walk per pool: a re-qualified task keeps the pool it was mined under (the
        # pool's shape caps decide what the walk yields), unknown ids take the run's
        jobs: list[tuple[str, frozenset[str] | None]] = [(pool, None)]
        if ids:
            known = frozenset()
            want = target or len(ids)
            by_pool: dict[str, set[str]] = {}
            stored = self._task_pools(ctx.run.repo, ids)
            for tid in ids:
                by_pool.setdefault(stored.get(tid, pool), set()).add(tid)
            jobs = [(pl, frozenset(tids)) for pl, tids in sorted(by_pool.items())]
        counts: dict[str, Any] = {
            "examined": 0,
            "found": 0,
            "gold_clean": 0,
            "gold_dirty": 0,
            "skipped": 0,
            "known": len(known),
            "pool": pool if not ids else ",".join(pl for pl, _ in jobs),
        }
        ctx.counts.update(counts)
        self._progress(ctx, 0, want)
        cancelled = False
        for job_pool, only in jobs:
            outcomes: Iterator[MineOutcome] = mine(
                ctx.git,
                ctx.config,
                runner=runner,
                executor=executor,
                scratch=self.scratch_dir,
                pool=job_pool,
                target_count=target,
                max_candidates=max_candidates,
                known=known,
                only=only,
                gold=gold,
                timeout=ctx.timeout,
                ref=ref,
                on_event=ctx.on_event,
            )
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
                break
        if cancelled:
            ctx.emit("mine", "mine.cancelled", **counts)
            return STATUS_CANCELLED, counts, ""
        return STATUS_SUCCEEDED, counts, ""

    def _task_pools(self, repo: str, task_ids: Sequence[str]) -> dict[str, str]:
        with self.factory() as s:
            q = select(Task.task_id, Task.pool).where(Task.repo == repo, Task.task_id.in_(task_ids))
            return {str(tid): str(pl) for tid, pl in s.execute(q)}

    def _ladder(self, ctx: RunContext) -> EscalationLadder:
        """The run's escalation ladder. Each entry of ``params.ladder`` / ``ladder_json`` is
        one of:

        * a bare rung label (``r1``, ``r2`` … — no ``:``; the API's default ladder is
          ``["r1"]``): one attempt with the run's own ``builder:model[@provider]``;
        * a ``builder:model[:provider]`` label: a rung as written;
        * an object rung ``{builder, model, provider?, budget?}``: a rung whose ``budget``
          fields override the run's ``params.budget`` for that rung only
          (:func:`rung_from_object`; the same model at 25 → 50 → 100 tool calls is a
          budget ladder).

        Every rung's effective budget is validated HERE, before any task runs, so a bad
        cap fails the run closed with its reason instead of erroring every attempt. The
        stored ``ladder_json`` stays what the operator declared."""
        run = ctx.run
        entries: list[Any] = list(ctx.params.get("ladder") or run.ladder_json or [])
        own = ""
        if run.builder and run.model:
            own = f"{run.builder}:{run.model}" + (f"@{run.provider}" if run.provider else "")
        if not entries and own:
            entries = [own]
        if not entries:
            raise ValueError("a replay run needs a ladder (rung labels) or builder + model")
        provider = str(run.provider or ctx.params.get("provider") or "")
        rungs: list[Rung] = []
        for entry in entries:
            if isinstance(entry, Mapping):
                rungs.append(rung_from_object(entry, default_provider=provider))
                continue
            label = str(entry)
            if not label.strip():
                continue
            if ":" not in label:
                if not own:
                    raise ValueError(
                        "a replay run with bare rung labels (r1, r2 …) needs builder + model "
                        "on the run"
                    )
                label = own
            rungs.append(parse_rung_label(label, default_provider=provider))
        if not rungs:
            raise ValueError("a replay run needs at least one rung")
        ladder = EscalationLadder(tuple(rungs))
        try:
            base = self._budget(ctx)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"the run's budget is invalid: {exc}") from exc
        for i, rung in enumerate(ladder):
            try:
                budget_for_rung(rung, base)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"rung {i} ({rung.label}) has an invalid budget: {exc}") from exc
        return ladder

    @staticmethod
    def _budget(ctx: RunContext) -> Budget:
        """The run-level budget: the builder's defaults overlaid with ``params.budget``."""
        return Budget.from_dict(dict(ctx.params.get("budget") or {}))

    def _run_replay(self, ctx: RunContext, *, mode: str) -> tuple[str, dict[str, Any], str]:
        run = ctx.run
        p = ctx.params
        tasks = self._select_tasks(ctx)
        total = len(tasks)
        ctx.counts.update({"tasks": 0, "total": total, "rows": 0, "clean": 0})
        ladder = self._ladder(ctx)
        budget = self._budget(ctx)
        rungs = trial_labels_for(ladder, budget)
        retain = dict(p.get("retain") or {})
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        run_ledger = _RunLedger(
            self.ledger,
            self.factory,
            self.evidence_dir,
            ctx,
            runner.name,
            trial_labels=rungs,
        )
        # belt-5 pre-flight (adapter.Preflight): OFF unless the run asks; a run with it on is
        # a different arm (builder '<name>+preflight') and the apparatus stamp says so
        preflight = Preflight.from_params(p.get("preflight"))
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
            keep_worktrees=bool(
                p.get("keep_worktrees", retain.get("worktrees", self.settings.keep_worktrees))
            ),
            extra={
                "worker": self.worker_id,
                "budget": budget.to_dict(),
                "builder_config": dict(p.get("builder_config") or {}),
                **(
                    {"preflight": {"fix": preflight.fix, "repair_turns": preflight.repair_turns}}
                    if preflight is not None
                    else {}
                ),
                # one entry per rung, in order: what climbed, under which tier
                "ladder": [
                    {
                        "builder": r.builder,
                        "model": r.model,
                        "provider": r.provider,
                        LABEL_BUDGET_TIER: rungs[f"r{i + 1}"][LABEL_BUDGET_TIER],
                    }
                    for i, r in enumerate(ladder)
                ],
            },
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
            transcript_dir=(
                self.transcripts_dir(run.id)
                if p.get("keep_transcripts") or retain.get("transcripts")
                else None
            ),
            builder_overrides=dict(p.get("builder_config") or {}),
            container=container_settings_from_env(),  # CRB_BUILDER__EXECUTOR=docker (ADR-0012)
            preflight=preflight,
        )
        self._progress(ctx, 0, total)

        def tracked() -> Iterator[TaskSpec]:
            for i, t in enumerate(tasks):
                ctx.counts["tasks"] = i
                self._progress(ctx, i, total)
                yield t

        # Circuit breaker: a provider that refuses the call (usage limit, 429, dead
        # credential) refuses every call; 263 of the first 534 rows on the dev stack were
        # such `outage` rows written in seconds (2026-09-15). After `outage_stop` consecutive
        # refused attempts the run stops with the reason instead of burning the queue.
        outage_stop = int(p.get("outage_stop", DEFAULT_OUTAGE_STOP) or 0)
        streak: dict[str, Any] = {"n": 0, "last": ""}
        inner_build = build_fn

        def metered_build(ws: Workspace, task: TaskSpec, mode_: str, rung: str) -> BuildAttempt:
            attempt = inner_build(ws, task, mode_, rung)
            if is_outage_error(attempt.error):
                streak["n"] += 1
                streak["last"] = attempt.error
            else:
                streak["n"] = 0
            return attempt

        def tripped() -> bool:
            return outage_stop > 0 and streak["n"] >= outage_stop

        summary: RunSummary = core_run(
            spec,
            ctx.git,
            tracked(),
            metered_build,
            on_event=ctx.on_event,
            stop=lambda: self._cancelled(ctx) or tripped(),
        )
        counts = summary.to_dict()
        counts["total"] = total
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._progress(ctx, summary.tasks, total)
        self._ledger_health()
        if tripped() and not self._cancelled(ctx):
            reason = (
                f"provider outage: {streak['n']} consecutive attempts refused; "
                f"last: {str(streak['last'])[:200]}"
            )
            counts["stopped_reason"] = reason
            ctx.emit("system", "run.outage_stop", status=StepStatus.ERROR, reason=reason)
            return STATUS_FAILED, counts, reason
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

    def _run_factory(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        """Forward mode (P6): run the repo's FROZEN backlog through the governed loop
        (:class:`crb.factory.loop.FactoryLoop`) — readiness gate, RED proof, build ladder
        under the belts, opt-in delivery, independent review — with every step in the
        factory evidence chain under ``CRB_HOME/factory/<repo>/`` and every graded attempt
        a ``process_step=factory`` ledger row. The backlog is registered through
        ``POST /factory/{repo}/backlog``; the run verifies it against its hash first.

        ``params``: the ladder / budget / builder_config of a replay; ``deliver`` (default
        False — a PR needs a credentials provider, absent here, so delivery fails closed
        as ``delivery_failed`` when asked for); ``max_rework`` (default 1)."""
        run = ctx.run
        p = ctx.params
        home = FactoryHome(self.home, run.repo)
        backlog = home.load_backlog()
        if backlog is None or not backlog.frozen:
            raise ValueError(
                f"no frozen backlog registered for {run.repo!r}: POST /factory/{run.repo}/backlog first"
            )
        ladder = self._ladder(ctx)
        budget = self._budget(ctx)
        rungs = trial_labels_for(ladder, budget)
        retain = dict(p.get("retain") or {})
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        overrides = dict(p.get("builder_config") or {})
        builders: dict[str, Builder] = {}

        def builder_for(rung: Rung) -> Builder:
            b = builders.get(rung.label)
            if b is None:
                b = builder_for_rung(rung, **overrides)
                builders[rung.label] = b
            return b

        run_ledger = _RunLedger(
            self.ledger,
            self.factory,
            self.evidence_dir,
            ctx,
            runner.name,
            trial_labels=rungs,
        )
        self._stamp(
            ctx,
            backlog_hash=backlog.backlog_hash,
            items=len(backlog.items),
            deliver=bool(p.get("deliver", False)),
            budget=budget.to_dict(),
            ladder=[r.label for r in ladder.rungs],
        )
        spec = FactorySpec(
            config=ctx.config,
            runner=runner,
            executor=executor,
            scratch=self.scratch_dir,
            evidence_dir=self.evidence_dir,
            evidence=home.evidence(actor=run.actor),
            ladder=ladder.rungs,
            builder_for=builder_for,
            ledger=as_run_ledger(run_ledger),
            budget=budget,
            gap_ledger=home.gap_ledger(),
            deliver=bool(p.get("deliver", False)),
            run_id=run.id,
            actor=run.actor,
            timeout=ctx.timeout,
            max_rework=int(p.get("max_rework", 1)),
            keep_workspaces=bool(retain.get("worktrees", False)),
        )
        loop = FactoryLoop(spec, ctx.git, emitter=ctx.emitter)
        total = len(backlog.items)
        counts: dict[str, Any] = {"items": total, "done": 0, "accepted": 0, "by_status": {}}
        ctx.counts.update(counts)
        self._progress(ctx, 0, total)
        original_run_item = loop.run_item

        def run_item(item: BacklogItem, *, authored: AuthoredTest | None = None) -> ItemOutcome:
            out = original_run_item(item, authored=authored)
            counts["done"] += 1
            counts["accepted"] += int(out.accepted)
            counts["by_status"][out.status] = counts["by_status"].get(out.status, 0) + 1
            ctx.counts.update(counts)
            self._progress(ctx, counts["done"], total)
            return out

        loop.run_item = run_item  # type: ignore[method-assign]
        outcomes = loop.run_backlog(
            backlog,
            authored=home.authored(),
            expected_hash=backlog.backlog_hash,
            stop=lambda: self._cancelled(ctx),
        )
        counts["outcomes"] = [o.to_dict() for o in outcomes]
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._ledger_health()
        if self._cancelled(ctx):
            return STATUS_CANCELLED, counts, ""
        return STATUS_SUCCEEDED, counts, ""

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
                "transform": transform_stamp(ctx.config),
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
                "(an instrument or belt-scope defect, never a model result)",
            )
        return STATUS_SUCCEEDED, counts, ""

    # --- label -------------------------------------------------------------------
    def _label_candidates(self, ctx: RunContext, *, relabel: bool) -> list[TaskSpec]:
        """Every task of the repo (gold-clean or not — a class is a property of the
        commit, not of the oracle), oldest first; ``params.task_ids`` / ``pool`` narrow
        it. Tasks already carrying a model label are skipped unless ``relabel``; tasks
        carrying a HUMAN label are always kept as they are (highest precedence)."""
        p = ctx.params
        ids = [str(i) for i in (p.get("task_ids") or [])]
        pool = str(p.get("pool") or "")
        with self.factory() as s:
            q = select(Task).where(Task.repo == ctx.run.repo)
            if ids:
                q = q.where(Task.task_id.in_(ids))
            if pool:
                q = q.where(Task.pool == pool)
            rows = s.execute(q.order_by(Task.authored, Task.task_id)).scalars().all()
        specs = [TaskSpec.from_dict(r.spec_json) for r in rows]
        kept: list[TaskSpec] = []
        for t in specs:
            if t.intent is not None and t.intent.is_human:
                ctx.counts["kept_human"] = int(ctx.counts.get("kept_human", 0)) + 1
                continue
            if (
                t.intent is not None
                and not relabel
                and not t.intent.rationale.startswith("model_error")  # an outage is not a label
            ):
                ctx.counts["kept_labelled"] = int(ctx.counts.get("kept_labelled", 0)) + 1
                continue
            kept.append(t)
        limit = int(p.get("limit") or 0)
        return kept[:limit] if limit > 0 else kept

    def _run_label(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        run = ctx.run
        p = ctx.params
        builder = str(run.builder or p.get("builder") or "")
        model = str(run.model or p.get("model") or "")
        provider = str(run.provider or p.get("provider") or "")
        if not builder:
            raise ValueError("a label run needs a builder (and a model)")
        relabel = bool(p.get("relabel", False))
        labeller = make_labeller(
            builder,
            model=model,
            provider=provider,
            builder_config=dict(p.get("builder_config") or {}),
        )
        # No runner / executor is involved: the apparatus is the labeller itself.
        self.queue.set_apparatus(
            run.id,
            {
                "apparatus_version": APPARATUS_VERSION,
                "worker": self.worker_id,
                "labeller": labeller.name,
                "min_confidence": DEFAULT_MIN_CONFIDENCE,
                "relabel": relabel,
                "builder_config": dict(p.get("builder_config") or {}),
            },
            worker_id=self.worker_id,
        )
        ctx.counts.update({"tasks": 0, "labelled": 0, "labeller": labeller.name})
        tasks = self._label_candidates(ctx, relabel=relabel)
        total = len(tasks)
        ctx.counts["total"] = total
        self._progress(ctx, 0, total)
        labels = []
        sources: dict[str, int] = {}
        resolved: dict[str, int] = {}
        cancelled = False
        for i, task in enumerate(tasks):
            if self._cancelled(ctx):
                cancelled = True
                break
            ev = commit_evidence(ctx.git, task.task_id, path_class=task.path_class)
            label = labeller.label(
                subject=ev.subject,
                message=ev.message,
                diff_stats=ev.diff_stats,
                changed_paths=ev.changed_paths,
                path_class=ev.path_class,
            )
            new = task.with_(intent=label)
            self._upsert_task(new)
            labels.append(label)
            sources[new.class_source] = sources.get(new.class_source, 0) + 1
            resolved[new.capability_class] = resolved.get(new.capability_class, 0) + 1
            ctx.emit(
                "mine",
                "label.task",
                status=StepStatus.ERROR
                if label.rationale.startswith("model_error")
                else StepStatus.OK,
                task_id=task.task_id,
                path_class=new.path_class,
                intent_class=label.intent_class,
                confidence=label.confidence,
                rationale=label.rationale,
                labeller=label.labeller,
                evidence_hash=label.evidence_hash,
                capability_class=new.capability_class,
                class_source=new.class_source,
                previous_class=task.capability_class,
                changed=new.capability_class != task.capability_class,
                cost_usd=labeller.usage.last.get("cost_usd"),
                latency_ms=int(float(labeller.usage.last.get("latency_s") or 0.0) * 1000),
            )
            ctx.counts.update({"tasks": i + 1, "labelled": len(labels)})
            self._progress(ctx, i + 1, total)
        counts: dict[str, Any] = {
            "tasks": len(labels),
            "total": total,
            "labelled": len(labels),
            "kept_human": int(ctx.counts.get("kept_human", 0)),
            "kept_labelled": int(ctx.counts.get("kept_labelled", 0)),
            "labeller": labeller.name,
            "min_confidence": DEFAULT_MIN_CONFIDENCE,
            "labels": label_summary(labels),
            "resolved_sources": dict(sorted(sources.items())),
            "resolved_classes": dict(sorted(resolved.items())),
            "usage": labeller.usage.to_dict(),
            "complete": not cancelled,
        }
        ctx.counts.clear()
        ctx.counts.update(counts)
        self._progress(ctx, len(labels), total)
        if cancelled:
            return STATUS_CANCELLED, counts, ""
        errored = sum(1 for lab in labels if lab.rationale.startswith("model_error"))
        counts["errors"] = errored
        if labels and errored == len(labels):
            # every label was a model error (an outage, a dead credential): the run did not
            # measure anything — fail it, like a replay whose every attempt errored
            return (
                STATUS_FAILED,
                counts,
                f"all {errored} label call(s) errored: {labels[0].rationale[:200]}",
            )
        usage = labeller.usage
        if labels and usage.errors >= usage.calls:
            # Every call failed on infrastructure (no credential, auth, timeout…): the
            # labels are honest (unclassified, confidence 0) but nothing was measured.
            first = next((x.rationale for x in labels if x.rationale), "")
            return STATUS_FAILED, counts, f"all {len(labels)} label call(s) errored: {first}"[:1000]
        return STATUS_SUCCEEDED, counts, ""


def trial_labels_for(ladder: EscalationLadder, base: Budget) -> dict[str, dict[str, str]]:
    """``trial → labels`` for every rung of ``ladder``: the core names attempts ``r1``,
    ``r2`` … positionally (:func:`crb.core.run.run_task`), so trial ``r<i+1>`` is rung
    ``i``. Each gets ``rung_index`` (0-based, the ladder array index) and ``budget_tier``
    of its EFFECTIVE budget — :func:`budget_for_rung` over the run's ``base``, the same
    call the build adapter makes, so the label and the cap the builder ran under cannot
    disagree."""
    return {
        f"r{i + 1}": {
            LABEL_RUNG_INDEX: str(i),
            LABEL_BUDGET_TIER: budget_tier(budget_for_rung(rung, base)),
        }
        for i, rung in enumerate(ladder)
    }


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
