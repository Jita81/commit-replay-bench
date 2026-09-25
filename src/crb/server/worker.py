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
* **An unconfirmed container kill is visible and reaped, never a silent terminal
  state.** A ``docker kill`` (cancel or wall clock) that the daemon did not confirm
  within ``KILL_CONFIRM_S`` reaches the worker as ``on_kill_unconfirmed`` — from a
  sealed attempt (its build stream or its tool-loop executor, via the session's
  ``unconfirmed_kills`` and the adapter) or from the run's own docker executor (the
  grade stage's belt / oracle test run, via ``DockerExecutor.on_kill_unconfirmed``): it
  writes a system ``run.kill_unconfirmed`` (status error) on the run's trace, appends
  "container <name> may still be running — it will be reaped by the worker; ``docker
  rm -f <name>`` reaps it by hand" to the run's error, and queues the name in the
  reaper's durable file ``<home>/unconfirmed-containers.json`` (:mod:`crb.server.reaper`).
  The run still ends ``cancelled`` / timed out (it did stop building) and a sealed
  attempt's pack notes carry ``kill_confirmed: false``. Every poll of
  :meth:`Worker.run_forever` makes one reap pass — ``docker inspect``, ``docker rm -f``,
  ``inspect`` — under a TIME BUDGET of ``heartbeat_s / 2`` (each docker call capped to
  the remainder; entries the budget did not reach wait for the next poll) so the pass
  can never hold the loop past the worker's own liveness bound; it writes
  ``run.kill_reaped`` or, at the bound (20 passes), ``run.kill_reap_failed`` (status
  error) on that run's trace; the check-in row carries the pending count
  (``unconfirmed_containers``) so ``/health`` reads ``degraded`` until the queue is empty.
* **Resumable event cursors.** A reclaimed run's emitter resumes ``seq`` after
  the last stored event so ``?after=<seq>`` never replays or skips.
* **Liveness is a fact, not an inference.** The worker upserts its ``workers`` row
  every ``heartbeat_s`` whether or not it holds a run (:meth:`Worker.checkin`), names
  the run it holds, and stamps ``stopped`` on a clean exit — so ``/health`` can say
  "no worker has checked in for 6 minutes" instead of "idle, 3 queued" (J-TEL-2).
* **Measured in this process.** Every build / grade / cost / delivery / token-mint
  series is recorded here and served on the worker's own ``/metrics`` port
  (``CRB_METRICS_PORT``); the API's ``/metrics`` never carries them (J-TEL-1).
* **Clone once, by policy.** A repo registered by URL only is cloned on its first
  run (:meth:`Worker._load_repo`): https/ssh only, credentials redacted from every
  event and error, ``repo.clone.start`` / ``repo.clone.done`` on the run's trace,
  the path persisted so no later run clones again.
* **Fetch before a build on the base (F39).** Before a ``factory`` run on a repository
  with a URL — and before a ``replay`` / ``blind`` / ``mine`` on one linked through the
  GitHub App — the worker fetches the row's URL and fast-forwards the clone's default
  branch to the remote's (:meth:`Worker._fetch_default_branch`): ``repo.fetch.start`` /
  ``repo.fetch.done`` carry the before / after shas. A fetch that fails, or a local
  default branch that cannot fast-forward, REFUSES the run (``FetchRefused``, the run
  ends ``failed`` with the reason) rather than build on a stale base; the RED proof and
  the build base are then the remote's current default branch, and a factory run's
  apparatus carries ``base_sha``.
* **The merge outcome comes back as evidence (B-9 / F30).** A factory run on a linked
  repository first reads every delivered pull request's state through the installation
  token and records ``delivery.merged`` / ``delivery.closed`` (at most closed then merged
  per PR) on the item's chain (``factory.outcomes.synced`` on the trace); a sync that cannot read never fails
  the run.
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

Navigation
----------
What it is:   The worker process — the only thing that executes a run (the API never does).
What it does: Polls the job queue, claims one run, dispatches by kind (setup, probe, mine,
              label, replay, blind, oracle, controls, factory), streams StepEvents, writes
              grade rows through the append-only ledger with the run's labels stamped,
              records the apparatus, and marks the run succeeded / failed / cancelled
              honestly (all-attempts-errored is a failure; a provider outage streak stops
              the run; a harness error on one mined candidate skips it). Fetches and
              fast-forwards the clone's default branch before a factory run (refusing the
              run when it cannot) and syncs delivered pull requests' outcomes first. Checks in to the
              ``workers`` table every ``heartbeat_s`` (idle or not, with the reaper's
              pending count) and records every worker-side metric, including deliveries
              by outcome and real installation-token mints. Reaps a container whose kill
              went unconfirmed on every poll and puts the outcome on the run's trace.
How:          ``Worker.run_once`` → ``JobQueue.claim`` → a ``RunContext`` (git, config,
              emitter) → the kind's ``_run_*`` method → core functions (``mine``, ``run``,
              ``score_task``, ``run_controls``, ``FactoryLoop``) → ``_RunLedger`` wraps every
              row with trial labels before it is chained → ``JobQueue.finish``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/store/jobs.py (the queue: claim, heartbeat, reclaim, finish; the
              check-in row the health probe reads is ``WorkerRow`` in src/crb/store/models.py),
              src/crb/observability/metrics.py (the recorders, ``record_event`` on
              the emitter's metering sink, ``crb_queue_depth`` on check-in),
              src/crb/core/run.py (a replay's task loop), src/crb/builders/adapter.py (the
              build function, ladder, pre-flight), src/crb/factory/author.py (the factory
              run's test-author rung, from ``CRB_FACTORY__TEST_AUTHOR`` or
              ``params.test_author``), src/crb/core/mine.py (mining; the oracle
              and controls kinds call their core modules the same way),
              src/crb/server/factory_state.py (forward mode's files and ``sync_outcomes``,
              which runs first; the loop itself is src/crb/factory/loop.py),
              src/crb/server/intake.py (the idle loop's tracker poll — the watched column
              of every repository whose listener an operator switched on, ADR-0017),
              src/crb/server/github_app.py (installation tokens for clone, fetch,
              delivery and the pull-request read), src/crb/server/reaper.py (the durable
              queue and the bounded pass behind ``run.kill_reaped`` / ``run.kill_reap_failed``)
Tested by:    tests/test_worker.py, tests/test_worker_budget_ladder.py, tests/test_worker_label.py,
              tests/test_worker_spend.py,
              tests/test_worker_clone.py, tests/test_worker_fetch.py, tests/test_store_jobs.py,
              tests/test_worker_test_author.py, tests/test_intake_worker.py,
              tests/test_observability_metrics.py
Touch when:   a run kind is added (register it in ``_handlers``, ``RUN_KINDS`` in
              src/crb/store/jobs.py and src/crb/server/schemas.py, docs/API.md); a row label
              every run must carry is added (``_RunLedger._stamp``); never for a new
              repository — repository behaviour lives in the runner and the repo config.
Claims:       Nothing here decides a verdict: the grader does; the worker only sequences,
              stamps and records (docs/EVIDENCE-AND-CLAIMS.md).

"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, func, select
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
from crb.builders.container import UnconfirmedKill
from crb.builders.labeller import make_labeller
from crb.core.capability import PROJECTION_CLASS_SIZE
from crb.core.classify import DEFAULT_MIN_CONFIDENCE, commit_evidence, label_summary
from crb.core.evidence import utc_now_iso
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
from crb.core.patches import PatchStore
from crb.core.redact import redact_and_cap
from crb.core.run import BuildAttempt, RunSpec, RunSummary
from crb.core.run import run as core_run
from crb.core.runners import get_runner
from crb.core.runners.base import BARE, BaseRunner, SetupResult, SetupStep
from crb.core.secrets_file import SecretsStore
from crb.core.spec import POOL_HARD, POOL_STANDARD, RepoConfig, TaskSpec
from crb.core.stats import mean
from crb.core.version import APPARATUS_VERSION, __version__
from crb.core.workspace import Workspace
from crb.factory.author import author_from_label
from crb.factory.backlog import BacklogItem
from crb.factory.delivery import (
    GitCredentials,
    GitCredentialsProvider,
    github_comment_pr_fn,
    github_open_pr_fn,
)
from crb.factory.loop import FactoryLoop, FactorySpec, ItemOutcome
from crb.factory.testfirst import AuthoredTest, TestAuthor, author_label
from crb.intake.client import TRACKER_TOKEN_SECRET, TrackerError
from crb.observability import metrics
from crb.observability.events import CallbackSink, Emitter, JsonlSink, MultiSink, StepStatus
from crb.server.factory_state import FactoryHome, outcomes_pending, sync_outcomes
from crb.server.github_app import GitHubApp, GitHubAppError
from crb.server.intake import (
    ListenerState,
    apply_outcome_map,
    build_tracker,
    item_url_for,
    poll_repository,
    post_outcomes_to_tickets,
)
from crb.server.reaper import STATE_FILENAME, ContainerReaper, ReapResult, by_hand
from crb.server.routes.capability import rows_for_apparatus, rows_for_mode, signed_map
from crb.server.routes.oracle import latest_controls_verdict
from crb.server.settings import FactorySettings, GitHubAppSettings, IntakeSettings
from crb.server.spend import SpendHooks, build_spend_hooks, pack_turns
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
    STATUS_QUEUED,
    STATUS_SUCCEEDED,
    JobQueue,
    StaleClaim,
)
from crb.store.ledger import DbLedger
from crb.store.models import EvidencePackRow, Repo, Run, Task, WorkerRow

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


#: Wall clock for one ``git fetch`` of the default branch before a run.
DEFAULT_FETCH_TIMEOUT_S = 10 * 60
#: Run kinds that fetch the default branch first on a repository LINKED through the
#: GitHub App (a ``factory`` run fetches on any repository with a URL).
FETCH_KINDS_LINKED: frozenset[str] = frozenset({KIND_REPLAY, KIND_BLIND, KIND_MINE})


class FetchRefused(RuntimeError):
    """The clone could not be brought up to date with the remote's default branch, so the
    run is refused rather than built on a stale base (F39)."""


def stage_for(action: str) -> str:
    """``grade.belt`` → ``grade``; unknown prefixes land in ``system``."""
    return _STAGE_FOR_PREFIX.get(action.split(".", 1)[0], "system")


def unconfirmed_note(container: str) -> str:
    """The sentence a run's ``error`` carries for a container whose kill went unconfirmed —
    what the reaper will do and what the operator can do now."""
    return (
        f"container {container} may still be running — it will be reaped by the worker; "
        f"`{by_hand(container)}` reaps it by hand"
    )


def _reaper_docker() -> str:
    """The docker binary the reaper calls: the builder posture's (``CRB_BUILDER__DOCKER_BINARY``)
    when one is set, else ``docker`` on PATH. A posture that fails closed is not this
    function's concern (the run reports it); the reaper still gets a binary name."""
    try:
        settings = container_settings_from_env()
    except SandboxUnavailable:
        return "docker"
    return (settings.docker_binary if settings is not None else "") or "docker"


#: Row labels the worker stamps per rung (``_RunLedger``). Hashed like every label.
LABEL_BUDGET_TIER = "budget_tier"
LABEL_RUNG_INDEX = "rung_index"
#: An attempt that ran under a calibrated budget carries this (crb.core.spend) — its own
#: ``budget_tier`` is then the record, not the rung's declared one.
LABEL_BUDGET_PROFILE = "budget_profile"


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


class _MeteredGitHubApp(GitHubApp):
    """The app client with ``crb_github_tokens_minted_total{installation}`` on every REAL
    mint (J-TEL-13). A cache hit returns the token the last call returned; a mint returns
    a new one — so a token that differs from the last one seen for that installation is a
    mint. Only a truncated digest is kept for the comparison, never the token, and the
    label is the installation id, never the token (the cheapest abuse detector that can
    never log a credential)."""

    def __init__(self, settings: GitHubAppSettings) -> None:
        super().__init__(settings)
        self._seen_digest: dict[int, str] = {}

    def installation_token(self, installation_id: int, *, now: float | None = None) -> str:
        token = super().installation_token(installation_id, now=now)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        if self._seen_digest.get(installation_id) != digest:
            self._seen_digest[installation_id] = digest
            metrics.github_tokens_minted_total.labels(str(installation_id)).inc()
        return token


class _InstallationProvider:
    """A ``GitCredentialsProvider`` over one GitHub App installation: every ``resolve``
    mints (or reuses, until near expiry) the installation's token — never stored."""

    def __init__(self, app: GitHubApp, installation_id: int, remote: str) -> None:
        self._app = app
        self._installation = installation_id
        self._remote = remote

    def resolve(self, repo: str) -> GitCredentials:
        del repo
        return GitCredentials(
            remote=self._remote, token=self._app.installation_token(self._installation)
        )


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
    #: Keep every graded attempt's patch, redacted and content-addressed, under
    #: ``<home>/evidence/patches`` (crb.core.patches) — ``CRB_RETENTION__PATCHES``.
    store_patches: bool = True
    max_reclaims: int = 3
    #: The worker's own Prometheus exposition (J-TEL-1): every build / grade / cost series
    #: is recorded in THIS process, so the API's ``/metrics`` never carries them. Served by
    #: ``prometheus_client.start_http_server`` on ``metrics_host:metrics_port``
    #: (``CRB_METRICS_HOST``, default loopback like the API's bind — a container sets
    #: ``0.0.0.0``; ``CRB_METRICS_PORT``, default 9464; ``0`` = off) when ``metrics_enabled``
    #: (``CRB_METRICS_ENABLED``, the same switch the API reads) and the client is installed.
    metrics_enabled: bool = True
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9464
    #: The GitHub App this deployment is registered as (``CRB_GITHUB__*``): the worker
    #: mints installation tokens to clone and deliver linked repositories (ADR-0014).
    github: GitHubAppSettings = field(default_factory=GitHubAppSettings)
    #: The served factory's defaults (``CRB_FACTORY__*``) — today the test-author rung a
    #: factory run uses when nobody authored an oracle for an item. Empty = no author,
    #: which is why such an item stops ``no_oracle``.
    factory: FactorySettings = field(default_factory=FactorySettings)
    #: Where work arrives from (``CRB_INTAKE__*``, ADR-0017): the worker reads the watched
    #: column of every repository whose listener an operator switched on. ``tracker: none``
    #: (the default) means the idle loop never polls anything.
    intake: IntakeSettings = field(default_factory=IntakeSettings)
    #: This deployment's own public address (``CRB_PUBLIC_URL``), read the way the API reads
    #: it. Every link the intake listener writes on somebody's ticket is built from it, and a
    #: pass that starts without one stops with ``no_public_url`` rather than writing a
    #: relative path a reader on the tracker's site cannot open.
    public_url: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "home", Path(self.home).expanduser())
        object.__setattr__(self, "worker_id", self.worker_id or default_worker_id())
        object.__setattr__(self, "kinds", tuple(self.kinds))
        if self.poll_s <= 0 or self.heartbeat_s <= 0 or self.stale_after_s <= 0:
            raise ValueError("poll_s, heartbeat_s and stale_after_s must be positive")
        if not 0 <= int(self.metrics_port) <= 65535:
            raise ValueError("CRB_METRICS_PORT must be 0 (off) or a port 1-65535")
        if not str(self.metrics_host).strip():
            raise ValueError("CRB_METRICS_HOST must name an address to bind (127.0.0.1, 0.0.0.0)")


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
    #: Sentences appended to the run's ``error`` whatever its final status (an
    #: unconfirmed container kill) — a cancelled run is still cancelled, but never quietly.
    notes: list[str] = field(default_factory=list)
    #: The task the run is on (set by each kind's task loop) — the ``task_id`` an
    #: executor-level report (``run.kill_unconfirmed`` from the grade stage) is filed under.
    task_id: str = ""
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
        labels = {**row.labels, **extra}
        if LABEL_BUDGET_PROFILE in row.labels and LABEL_BUDGET_TIER in row.labels:
            # a calibrated attempt ran under its own caps: its tier is the record
            labels[LABEL_BUDGET_TIER] = row.labels[LABEL_BUDGET_TIER]
        return GradeRow(**{**row.fields(), "labels": labels})

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
            repo=row.repo,
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
        self._github_app_client: GitHubApp | None = None
        self.engine = engine or make_engine(settings.database_url or None)
        init_db(self.engine)
        self.factory = make_session_factory(self.engine)
        self.queue = JobQueue(self.factory, max_reclaims=settings.max_reclaims)
        self.ledger = DbLedger(self.factory)
        self.worker_id = settings.worker_id
        self._checkin_lock = threading.Lock()
        self._last_checkin = 0.0
        # the intake listener's own timer (ADR-0017): the first idle pass polls, then
        # every CRB_INTAKE__POLL_S. Zero means "due now".
        self._intake_last = 0.0
        self.reaper = ContainerReaper(self.home / STATE_FILENAME, docker=_reaper_docker())
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
        """Poll until ``stop`` is set. One run at a time; never raises. The worker checks
        in (:meth:`checkin`) every ``heartbeat_s`` whether or not it holds a run, and stamps
        its row ``stopped`` on the way out."""
        _LOG.info("worker %s started (executor=%s)", self.worker_id, self.settings.executor)
        while not stop.is_set():
            self._checkin_if_due()
            self.reap()
            try:
                run = self.run_once()
            except Exception:  # the loop must survive anything a run throws
                _LOG.exception("worker loop error")
                run = None
            if run is None:
                self.poll_intake()
                stop.wait(self.settings.poll_s)
        self.checkin(stopped=True)
        _LOG.info("worker %s stopped", self.worker_id)

    # --- intake: the enterprise's own board ----------------------------------------
    def intake_due(self, now: float | None = None) -> bool:
        """Is a poll due? ``CRB_INTAKE__POLL_S`` since the last one. A deployment with no
        tracker configured is never due, so the idle loop costs nothing."""
        if not self.settings.intake.enabled:
            return False
        t = time.time() if now is None else now
        return (t - self._intake_last) >= float(self.settings.intake.poll_s)

    def intake_repos(self) -> list[tuple[str, ListenerState]]:
        """Every repository whose listener an operator switched ON, with its state.

        Default OFF is enforced here as well as at the API: a repository row with no
        ``intake`` key in its config is simply not in this list, so a deployment that has
        configured a tracker still polls nothing until somebody consents.
        """
        out: list[tuple[str, ListenerState]] = []
        with self.factory() as s:
            for row in s.execute(select(Repo)).scalars().all():
                state = ListenerState.from_config(dict(row.config_json or {}))
                if state.enabled:
                    out.append((str(row.name), state))
        return out

    def poll_intake(self, now: float | None = None) -> int:
        """One pass of the intake listener over every switched-on repository.

        Returns how many repositories were polled. Never raises: a tracker that cannot be
        built or reached is an ``intake.stopped`` event on each repository's chain and the
        next pass retries. Called from the idle loop only, so a poll never competes with a
        run for this worker.

        The pass keeps its own check-in running for as long as it lasts. The idle loop's
        throttled check-in only happens BETWEEN passes, and one ticket costs about eleven
        synchronous tracker calls, so a slow board could hold the loop past the liveness
        window — and the health probe then called this worker stale, and told an operator
        queued runs would not start, while it was working.
        """
        if not self.intake_due(now):
            return 0
        self._intake_last = time.time() if now is None else now
        repos = self.intake_repos()
        if not repos:
            return 0
        try:
            tracker = build_tracker(
                self.settings.intake, self._tracker_token(), home=self.settings.home
            )
        except TrackerError as exc:
            for repo, _state in repos:
                FactoryHome(self.home, repo).evidence(actor="worker").append(
                    "intake.stopped", "", step="connect", reason=exc.reason, detail=exc.detail
                )
            _LOG.warning("intake not polled: %s", exc.reason)
            return 0
        stop_checkin = threading.Event()
        checkin = self._checkin_thread(stop_checkin, name="intake")
        try:
            for repo, state in repos:
                try:
                    self._poll_one(repo, tracker, state)
                except Exception:  # the idle loop must survive anything a tracker does
                    _LOG.exception("intake poll failed for %s", repo)
        finally:
            stop_checkin.set()
            checkin.join(timeout=5)
        return len(repos)

    def _tracker_token(self) -> str:
        """The stored tracker credential, read at poll time and never held on the worker.
        Missing or unreadable is an empty string, which ``build_tracker`` turns into the
        ``no_secret`` stop an operator can act on."""
        try:
            return SecretsStore.from_env().get(TRACKER_TOKEN_SECRET) or ""
        except Exception:  # an insecure or absent store is "no secret", never a crash
            return ""

    def _poll_one(self, repo: str, tracker: Any, state: ListenerState) -> None:
        """Read one repository's column, then apply the outcome map to its merged items."""
        home = FactoryHome(self.home, repo)
        lookup = self._route_lookup(repo)
        # ONE builder for every link this pass writes on a ticket, and it is absolute: a
        # relative path in somebody else's comment resolves against THEIR host
        item_url = item_url_for(self.settings.public_url, repo)
        # poll_repository writes the view the screen reads, so nothing is returned that this
        # caller has to remember to persist
        poll_repository(
            repo,
            tracker=tracker,
            listener=state,
            column=state.column or self.settings.intake.column,
            home=home,
            route_for=lookup,
            item_url=item_url,
            run_active=lambda: self._factory_run_active(repo),
            actor="worker",
            max_tickets=self.settings.intake.max_per_poll,
            budget_s=float(self.settings.intake.poll_budget_s),
        )
        # what the loop did with the items this column produced, told to the tickets that
        # produced them: the pull request link when one opened, the refusal and its way
        # forward when the loop stopped. Read from the chain, posted once per marker.
        post_outcomes_to_tickets(
            tracker,
            home=home,
            item_url=item_url,
            evidence=home.evidence(actor="worker"),
        )
        apply_outcome_map(
            tracker,
            home=home,
            outcome_map=dict(self.settings.intake.outcome_map),
            evidence=home.evidence(actor="worker"),
        )

    def _factory_run_active(self, repo: str) -> bool:
        """Is a factory run queued or running for ``repo``? A registration that arrives now
        is queued rather than refused — the backlog hash a run verifies against must not
        move under it."""
        with self.factory() as s:
            row = (
                s.execute(
                    select(Run.id)
                    .where(
                        Run.repo == repo,
                        Run.kind == KIND_FACTORY,
                        Run.status.in_(("queued", "running")),
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )
        return row is not None

    # --- the reaper ---------------------------------------------------------------
    @property
    def reap_budget_s(self) -> float:
        """The time one reap pass may hold the idle loop: half the heartbeat, so the
        check-in that follows the pass is never later than the worker's own liveness
        bound (``3 × heartbeat_s``) — even when the daemon answers nothing."""
        return float(self.settings.heartbeat_s) / 2

    def reap(self) -> int:
        """One bounded pass of the container reaper (every poll), under
        :attr:`reap_budget_s`: each container that ended this pass gets ``run.kill_reaped``
        (ok) or ``run.kill_reap_failed`` (error, with the by-hand command) on its run's
        trace. Returns how many ended. Never raises."""
        try:
            ended = self.reaper.reap_once(budget_s=self.reap_budget_s)
        except Exception:  # the loop must survive the reaper too
            _LOG.exception("container reaper pass failed")
            return 0
        for res in ended:
            self._record_reap(res)
        return len(ended)

    def _record_reap(self, res: ReapResult) -> None:
        run = self.queue.get(res.entry.run_id)
        if run is None:  # the run row is gone; the log is all that is left
            _LOG.warning(
                "reaper: run %s not found for container %s (%s)",
                res.entry.run_id[:8],
                res.entry.container,
                "reaped" if res.reaped else res.detail,
            )
            return
        try:
            emitter = self._emitter(run)
            if res.reaped:
                emitter.emit(
                    "system",
                    "run.kill_reaped",
                    task_id=res.entry.task_id,
                    container=res.entry.container,
                    attempts=res.attempts,
                )
            else:
                emitter.emit(
                    "system",
                    "run.kill_reap_failed",
                    status=StepStatus.ERROR,
                    task_id=res.entry.task_id,
                    error=f"container {res.entry.container} not reaped: {res.detail}",
                    container=res.entry.container,
                    attempts=res.attempts,
                )
        except Exception:
            _LOG.exception("reaper: could not record %s on run %s", res.entry.container, run.id[:8])

    def _kill_unconfirmed(self, ctx: RunContext, task_id: str, kill: UnconfirmedKill) -> None:
        """``on_kill_unconfirmed`` for the run's build function AND its docker executor
        (module docstring): the event, the note on the run's error, the reaper's queue.
        Never raises."""
        note = unconfirmed_note(kill.container)
        try:
            ctx.emit(
                "system",
                "run.kill_unconfirmed",
                status=StepStatus.ERROR,
                task_id=task_id,
                error=note,
                container=kill.container,
                run_id=ctx.run.id,
                bound_s=float(kill.bound_s),
            )
        except Exception:
            _LOG.exception("could not record run.kill_unconfirmed for %s", kill.container)
        if note not in ctx.notes:
            ctx.notes.append(note)
        try:
            self.reaper.add(kill.container, run_id=ctx.run.id, task_id=task_id)
        except Exception:
            _LOG.exception("could not queue %s for the reaper", kill.container)

    # --- liveness ---------------------------------------------------------------
    def _checkin_if_due(self) -> None:
        """Idle-loop check-in, throttled to ``heartbeat_s`` (the loop wakes every ``poll_s``)."""
        if time.monotonic() - self._last_checkin >= self.settings.heartbeat_s:
            self.checkin()

    def _checkin_thread(self, stop: threading.Event, *, name: str) -> threading.Thread:
        """A check-in every ``heartbeat_s`` until ``stop`` is set — for work the idle loop
        cannot interrupt, such as one intake pass over somebody's board.

        It carries no run id: this is the worker saying it is alive while holding nothing, and
        a run's own liveness is :meth:`_heartbeat_thread`'s (which also renews the claim).
        """

        def loop() -> None:
            while not stop.wait(self.settings.heartbeat_s):
                self.checkin()  # never raises: liveness must not take the pass down

        t = threading.Thread(target=loop, name=f"crb-checkin-{name}-{self.worker_id}", daemon=True)
        t.start()
        return t

    def checkin(self, *, current_run_id: str = "", stopped: bool = False) -> None:
        """Upsert this worker's ``workers`` row (J-TEL-2): hostname, executor, kinds,
        ``heartbeat`` = now, its own ``heartbeat_s`` (what the health probe judges staleness
        against), the run it holds, the package version, and ``stopped`` on a clean exit.
        Also sets ``crb_queue_depth``. Never raises — liveness must not take a run down."""
        now = utc_now_iso()
        with self._checkin_lock:
            self._last_checkin = time.monotonic()
            try:
                with self.factory() as s:
                    row = s.get(WorkerRow, self.worker_id)
                    if row is None:
                        row = WorkerRow(worker_id=self.worker_id, started=now)
                        s.add(row)
                    row.hostname = socket.gethostname()
                    row.executor = self.settings.executor
                    row.kinds = list(self.settings.kinds)
                    row.heartbeat = now
                    row.heartbeat_s = float(self.settings.heartbeat_s)
                    row.current_run_id = current_run_id
                    row.version = __version__
                    row.stopped = now if stopped else ""
                    row.unconfirmed_containers = self.reaper.pending_count()
                    queued = int(
                        s.execute(
                            select(func.count(Run.id)).where(Run.status == STATUS_QUEUED)
                        ).scalar_one()
                    )
                    s.commit()
                metrics.queue_depth.set(queued)
            except Exception:
                _LOG.exception("worker %s check-in failed", self.worker_id)

    # --- execution ------------------------------------------------------------
    def _emitter(self, run: Run) -> Emitter:
        # the third sink meters delivery outcomes (``crb_deliveries_total``, J-TEL-13) from
        # the same events the log shows — one vocabulary, no second code path
        sink = MultiSink(
            DbEventSink(self.factory),
            JsonlSink(self.events_path(run.id)),
            CallbackSink(metrics.record_event),
        )
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
                self.checkin(current_run_id=run.id)

        t = threading.Thread(target=loop, name=f"crb-heartbeat-{run.id[:8]}", daemon=True)
        t.start()
        return t

    def execute(self, run: Run) -> None:
        """Execute a *claimed* run and finish it. Never raises."""
        emitter = self._emitter(run)
        emitter.emit("system", "run.claimed", worker=self.worker_id, kind=run.kind, mode=run.mode)
        self.checkin(current_run_id=run.id)
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
                config, git = self._load_repo(run.repo, emitter, kind=run.kind)
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
            self.checkin()
        if ctx is not None and ctx.notes:  # whatever the status: never a quiet unconfirmed kill
            error = "; ".join([error, *ctx.notes] if error else ctx.notes)[:2000]
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
    def _github_installation(self, cfg: Mapping[str, Any]) -> int | None:
        """The installation a repository is linked to (``config_json.github``), when the
        GitHub App is configured on this deployment."""
        if not self.settings.github.enabled:
            return None
        link = dict(cfg.get("github") or {})
        try:
            return int(link.get("installation_id") or 0) or None
        except (TypeError, ValueError):
            return None

    def _github_app(self) -> GitHubApp:
        """The app client, built once per worker (its token cache is per installation)."""
        if self._github_app_client is None:
            self._github_app_client = _MeteredGitHubApp(self.settings.github)
        return self._github_app_client

    def _github_host_ok(self, url: str) -> bool:
        """True when ``url`` is an https URL on the GitHub host the app is registered with:
        an installation token is only ever sent there (CWE-201 — a repository whose URL was
        edited to another host gets no token, whatever its link says)."""
        try:
            u = urlsplit(url)
            app_host = urlsplit(self.settings.github.web_url).hostname or ""
        except ValueError:
            return False
        return u.scheme == "https" and bool(u.hostname) and u.hostname == app_host

    def _github_auth_header(self, cfg: Mapping[str, Any], url: str = "") -> str | None:
        """``Authorization: Basic …`` for a clone of a GitHub-App-linked repository, or None
        — also None when ``url`` (given) is not on the app's own GitHub host."""
        installation = self._github_installation(cfg)
        if installation is None:
            return None
        if url and not self._github_host_ok(url):
            return None
        token = self._github_app().installation_token(installation)
        return GitCredentials(remote="https://github.invalid/x", token=token).basic_auth_header()

    def _delivery_credentials(
        self, cfg: Mapping[str, Any], remote: str
    ) -> GitCredentialsProvider | None:
        """Delivery credentials for a factory run: the GitHub App's installation token when
        the repository is linked, the remote is on the app's host, and the installation may
        write — ``Contents: write`` AND ``Pull requests: write``, read from GitHub now (the
        org admin may have narrowed them since the record); otherwise None — the loop fails
        closed (no branch, no PR: a push with a read-only PR permission would leave a branch
        behind before the PR call failed)."""
        installation = self._github_installation(cfg)
        if installation is None or not self._github_host_ok(remote):
            return None
        try:
            inst = self._github_app().installation(installation)
        except GitHubAppError:
            return None
        if not inst.can_deliver:
            return None
        return _InstallationProvider(self._github_app(), installation, remote)

    def _fetch_before(self, kind: str, cfg: Mapping[str, Any], url: str) -> bool:
        """Whether a run of ``kind`` fetches first (F39): a factory run on any repository
        with a URL; a replay / blind / mine on one linked through the GitHub App."""
        if not url:
            return False
        if kind == KIND_FACTORY:
            return True
        return kind in FETCH_KINDS_LINKED and self._github_installation(cfg) is not None

    def _load_repo(
        self, name: str, emitter: Emitter | None = None, *, kind: str = ""
    ) -> tuple[RepoConfig, GitRepo]:
        """The repo's config and clone. A row with a ``url`` but no usable clone
        (``clone_path`` empty or not a git repository) is cloned once into
        ``<home>/repos/<name>`` — full history, ``--no-tags``, 30-minute wall clock,
        URL policy-checked and redacted — and the path is persisted on the row and
        in ``config_json["path"]`` so every later run finds it. ``repo.clone.start`` /
        ``repo.clone.done`` (stage ``system``) carry the redacted URL, the duration and
        the head sha on the run's trace when ``emitter`` is given. An EXISTING clone is
        fetched and fast-forwarded first when ``kind`` asks for it
        (:meth:`_fetch_before`); a fresh clone is already at the remote's head."""
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
            git = GitRepo(clone)
            if self._fetch_before(kind, cfg, url):
                self._fetch_default_branch(name, cfg, git, url, emitter)
            return config, git
        if not url:
            if not clone:
                raise LookupError(f"repo {name!r} has no clone path")
            raise LookupError(f"repo {name!r}: {clone!r} is not a git repository")
        dest = self.home / "repos" / name
        safe_url = redact_url(url)
        started = time.monotonic()
        # a repository connected through the GitHub App clones with a short-lived
        # installation token (never argv, never on disk — ADR-0014); any other URL clones
        # as the worker's own git can
        auth_header = self._github_auth_header(cfg, url)
        if emitter is not None:
            emitter.emit(
                "system",
                "repo.clone.start",
                url=safe_url,
                dest=str(dest),
                github_app=bool(auth_header),
            )
        try:
            head = clone_repo(url, dest, timeout=DEFAULT_CLONE_TIMEOUT_S, auth_header=auth_header)
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

    def _fetch_default_branch(
        self,
        name: str,
        cfg: Mapping[str, Any],
        git: GitRepo,
        url: str,
        emitter: Emitter | None = None,
    ) -> str:
        """F39: ``git fetch`` the row's URL into ``refs/remotes/origin/<default>`` and
        fast-forward the clone's default branch to it; returns the sha the branch is now
        at. The default branch is the link's (``config_json.github.default_branch``), else
        the clone's ``origin/HEAD``, else the branch the clone is on. A linked repository
        fetches with the installation token in the environment (never argv, never on
        disk — as the clone does). ``repo.fetch.start`` / ``repo.fetch.done`` carry the
        redacted URL, the branch and the before / after shas. Any failure — the remote
        unreachable, the branch gone, a local default branch that has commits the remote
        does not (no fast-forward) — is a :class:`FetchRefused`: the run must not build,
        prove RED or open a pull request on a base the remote has moved past."""
        safe_url = redact_url(url)
        started = time.monotonic()
        link = dict(cfg.get("github") or {})
        branch = str(link.get("default_branch") or "").strip()
        if not branch:
            head = git.run("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
            branch = head.stdout.strip().removeprefix("origin/") if head.ok else ""
        if not branch:
            cur = git.run("rev-parse", "--abbrev-ref", "HEAD")
            branch = cur.stdout.strip() if cur.ok and cur.stdout.strip() != "HEAD" else ""
        auth_header = self._github_auth_header(cfg, url)
        if emitter is not None:
            emitter.emit(
                "system",
                "repo.fetch.start",
                url=safe_url,
                branch=branch,
                dest=str(git.path),
                github_app=bool(auth_header),
            )

        def refuse(why: str) -> FetchRefused:
            exc = FetchRefused(
                f"repo {name!r}: the clone could not be brought up to date with {safe_url} "
                f"({why}) — the run is refused so it does not build on a stale base. "
                f"Bring the clone's {branch or 'default'} branch back onto the remote's "
                "history by hand, or clear the repository's clone path in its configuration "
                "so the next run clones afresh"
            )
            if emitter is not None:
                emitter.error(
                    "system",
                    "repo.fetch.done",
                    exc,
                    url=safe_url,
                    branch=branch,
                    dest=str(git.path),
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            return exc

        if not branch:
            raise refuse("no default branch is known for the clone")
        before_res = git.run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
        before = before_res.stdout.strip() if before_res.ok else ""
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
        if auth_header:
            env.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraheader",
                    "GIT_CONFIG_VALUE_0": auth_header,
                }
            )
        argv = [
            git.git_binary,
            "-C",
            str(git.path),
            "fetch",
            "--quiet",
            "--no-tags",
            "--prune",
            url,
            f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
        ]
        try:
            p = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=DEFAULT_FETCH_TIMEOUT_S,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise refuse(f"fetch timed out after {DEFAULT_FETCH_TIMEOUT_S}s") from exc
        if p.returncode != 0:
            stderr = redact_and_cap((p.stderr or "").replace(url, safe_url), max_chars=300)
            raise refuse(f"git fetch failed rc={p.returncode}: {stderr}")
        after_res = git.run(
            "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}^{{commit}}"
        )
        if not after_res.ok:
            raise refuse(f"the remote has no branch {branch!r}")
        after = after_res.stdout.strip()
        cur = git.run("rev-parse", "--abbrev-ref", "HEAD")
        on_branch = cur.ok and cur.stdout.strip() == branch
        fast_forwarded = False
        if not before:
            # the clone has no local default branch (it was cloned on another one, or the
            # link's default branch was renamed): create it at the remote's head
            co = git.run("checkout", "--quiet", "-B", branch, f"refs/remotes/origin/{branch}")
            if not co.ok:
                raise refuse(
                    f"cannot create {branch!r}: {redact_and_cap(co.stderr, max_chars=200)}"
                )
            fast_forwarded = True
        else:
            if not on_branch:
                co = git.run("checkout", "--quiet", branch)
                if not co.ok:
                    raise refuse(
                        f"cannot check out {branch!r}: {redact_and_cap(co.stderr, max_chars=200)}"
                    )
            if before != after:
                # fast-forward ONLY: a local commit the remote lacks is a refusal, never a
                # merge or a reset the product did on its own
                ff = git.run("merge", "--ff-only", "--quiet", f"refs/remotes/origin/{branch}")
                if not ff.ok:
                    raise refuse(
                        f"local {branch!r} at {before[:12]} cannot fast-forward to the remote's "
                        f"{after[:12]}: {redact_and_cap(ff.stderr, max_chars=200)}"
                    )
                fast_forwarded = True
        if emitter is not None:
            emitter.emit(
                "system",
                "repo.fetch.done",
                url=safe_url,
                branch=branch,
                dest=str(git.path),
                before=before,
                after=after,
                fast_forwarded=fast_forwarded,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return after

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
        # container (docker) instead of waiting for the wall-clock timeout. A docker kill
        # the daemon never confirms is reported the same way a sealed attempt's is.
        ctx._executor = make_executor(
            kind,
            docker=docker,
            cancel=lambda: self._cancelled(ctx),
            on_kill_unconfirmed=lambda kill: self._kill_unconfirmed(ctx, ctx.task_id, kill),
        )
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

    def _spend_hooks(self, ctx: RunContext, ladder: EscalationLadder, *, mode: str) -> SpendHooks:
        """The spend rules bound to this run from the ledger as it stands now (prior rows
        only): the escalation gate and, when the run or the repository asks for
        ``budget_profile: calibrated``, the per-attempt budget (crb.server.spend). A ledger
        that cannot be read (a tampered row the core refuses to construct) measures
        nothing: the rules then see no history — the ladder climbs as before and a
        calibrated attempt keeps its floor — and the trace says why."""
        try:
            rows = list(self.ledger.rows())
        except Exception as exc:  # the rules are advisory spend, never a reason to fail a run
            rows = []
            ctx.emit(
                "system",
                "run.spend_history_unreadable",
                status=StepStatus.ERROR,
                error=f"{type(exc).__name__}: {exc}"[:300],
            )
        return build_spend_hooks(
            rows=rows,
            repo=ctx.run.repo,
            mode=mode,
            ladder=ladder,
            params=ctx.params,
            repo_spend=dict(ctx.config.spend),
            tier_fn=budget_tier,
            turns_for=lambda hashes: pack_turns(self.factory, hashes),
        )

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
        spend = self._spend_hooks(ctx, ladder, mode=mode)
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
                "spend": spend.apparatus(),
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
            patch_store=PatchStore.under(self.evidence_dir)
            if self.settings.store_patches
            else None,
            escalation_gate=spend.escalation_gate,
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
            on_kill_unconfirmed=lambda task_id, kill: self._kill_unconfirmed(ctx, task_id, kill),
            budget_for_task=spend.budget_for_task,
        )
        self._progress(ctx, 0, total)

        def tracked() -> Iterator[TaskSpec]:
            for i, t in enumerate(tasks):
                ctx.counts["tasks"] = i
                ctx.task_id = t.task_id
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
            ctx.task_id = task.task_id
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

    def _route_lookup(
        self, repo: str, run_id: str = ""
    ) -> Callable[[BacklogItem], dict[str, Any] | None]:
        """The capability map's decision for an item's (class × size) cell — computed once,
        lazily, from the same signed map ``GET /capability-map`` serves (sighted rows,
        current apparatus, the repo's latest controls verdict, sign-offs overlaid). ``None``
        for a cell nobody has measured: the loop withholds delivery on it (DL-038).

        Rows of ``run_id`` — THIS run's own graded builds — are excluded: the map that
        licenses a delivery is the map as it stood before the run, never one the run's own
        clean rows have nudged (B-1b finding 2: PR bodies said ``n=27`` where the freeze saw
        26 → DL-045). Each decision also carries ``apparatus_versions`` for the record."""
        cache: dict[str, dict[str, Any] | None] = {}
        computed: dict[str, bool] = {}

        def compute() -> None:
            before = (r for r in self.ledger.rows(repo=repo) if not run_id or r.run_id != run_id)
            rows = rows_for_apparatus(rows_for_mode(before, "sighted"), "current")
            with self.factory() as s:
                cmap, _ = signed_map(
                    rows, PROJECTION_CLASS_SIZE, s, repo, controls=latest_controls_verdict(s, repo)
                )
            for c in cmap.cells:
                if c.decision is not None:
                    st = c.stats
                    cache[f"{c.key.capability_class}|{c.key.size}"] = {
                        **c.decision.to_dict(),
                        "apparatus_versions": list(st.apparatus_versions) if st else [],
                    }
            computed["done"] = True

        def lookup(item: BacklogItem) -> dict[str, Any] | None:
            if not computed:
                compute()
            return cache.get(f"{item.capability_class}|{item.size_estimate}")

        return lookup

    def _run_factory(self, ctx: RunContext) -> tuple[str, dict[str, Any], str]:
        """Forward mode (P6): run the repo's FROZEN backlog through the governed loop
        (:class:`crb.factory.loop.FactoryLoop`) — readiness gate, RED proof, build ladder
        under the belts, opt-in delivery, independent review — with every step in the
        factory evidence chain under ``CRB_HOME/factory/<repo>/`` and every graded attempt
        a ``process_step=factory`` ledger row. The backlog is registered through
        ``POST /factory/{repo}/backlog``; the run verifies it against its hash first.

        ``params``: the ladder / budget / builder_config of a replay; ``deliver`` (default
        False — a PR needs a credentials provider, absent here, so delivery fails closed
        as ``delivery_failed`` when asked for); ``max_rework`` (default 1); ``test_author``
        (a rung label, or ``none``; default the deployment's ``CRB_FACTORY__TEST_AUTHOR``)
        — the rung that writes the failing test for an item nobody authored an oracle for,
        refused when it is a rung on this run's own ladder."""
        run = ctx.run
        p = ctx.params
        home = FactoryHome(self.home, run.repo)
        backlog = home.load_backlog()
        if backlog is None or not backlog.frozen:
            raise ValueError(
                f"no frozen backlog registered for {run.repo!r}: POST /factory/{run.repo}/backlog first"
            )
        pinned = str(p.get("backlog_hash") or "")
        if pinned and pinned != backlog.backlog_hash:
            # The API stamped the active hash at enqueue; a backlog re-registered since
            # (the register route's active-run check has a window) must not be worked
            # under the old run's evidence (CodeRabbit on PR #4, 2026-09-15).
            raise ValueError(
                f"backlog changed since this run was queued: pinned {pinned[:16]}…, "
                f"active {backlog.backlog_hash[:16]}… — re-queue against the active backlog"
            )
        # An evolution moves only the evolutions chain (the frozen hash stays), so the
        # same window admits an item the person who queued the run never saw: the API
        # stamps that chain too and the pin is checked on both (a run queued before the
        # stamp existed carries no key and is not held to it).
        if "evolutions_hash" in p and str(p["evolutions_hash"] or "") != backlog.evolutions_hash:
            pinned_ev = str(p["evolutions_hash"] or "")
            raise ValueError(
                "backlog evolved since this run was queued: pinned evolutions chain "
                f"{pinned_ev[:16] or '(none)'}…, active {backlog.evolutions_hash[:16] or '(none)'}… "
                "— re-queue so the run works the items you can see"
            )
        ladder = self._ladder(ctx)
        budget = self._budget(ctx)
        rungs = trial_labels_for(ladder, budget)
        retain = dict(p.get("retain") or {})
        runner = self._runner(ctx)
        executor = self._executor(ctx)
        # G-904 — the served worker's test author. Resolved here, BEFORE anything is
        # stamped or spent, so a rung that is also on the build ladder is refused by
        # ``FactorySpec``'s existing identity check rather than found half-way through.
        test_author = self._test_author(ctx, ladder)
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
            items=len(backlog.ordered()),
            deliver=bool(p.get("deliver", False)),
            budget=budget.to_dict(),
            ladder=[r.label for r in ladder.rungs],
            # the author rung, on the run's apparatus stamp: "" reads "no test author",
            # which is why an item with no operator-authored oracle stops ``no_oracle``
            test_author=author_label(test_author) if test_author is not None else "",
            # F39 — the base every RED proof and build of this run starts from (the
            # default branch as fetched, or the clone's head when nothing was fetched)
            base_sha=ctx.git.rev_parse("HEAD"),
        )
        # delivery through the GitHub App: the linked installation's token pushes the branch
        # and opens the pull request against the repository's default branch (ADR-0014);
        # an unlinked repository has no credentials and the loop fails closed on delivery
        with self.factory() as s:
            row = s.get(Repo, run.repo)
            cfg_json = dict(row.config_json or {}) if row is not None else {}
        link = dict(cfg_json.get("github") or {})
        remote = str(ctx.config.url or "")
        # B-9 / F30 — before any build: each delivered pull request's fate, read through
        # the installation token, onto the item's chain (at most closed then merged per
        # PR); never fails the run
        self._sync_outcomes(ctx, home, cfg_json, remote)
        creds = self._delivery_credentials(cfg_json, remote) if remote else None
        api_base = self.settings.github.api_url if creds is not None else "https://api.github.com"

        def open_pr(**kw: Any) -> tuple[str, int]:
            return github_open_pr_fn(api_base=api_base, **kw)

        def comment_pr(**kw: Any) -> None:
            github_comment_pr_fn(api_base=api_base, **kw)

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
            test_author=test_author,
            deliver=bool(p.get("deliver", False)),
            creds=creds,
            open_pr_fn=open_pr if creds is not None else None,
            comment_pr_fn=comment_pr if creds is not None else None,
            target_default_branch=str(link.get("default_branch") or "main"),
            # the route gate: the same signed (class × size) map the API serves, under the
            # repo's latest controls verdict, sighted rows of the current apparatus — minus
            # this run's own rows (DL-045); the loop reads it once per item, at readiness
            route_decision_for=self._route_lookup(run.repo, run.id),
            deliver_override_by=str(p.get("deliver_override_by", "") or ""),
            run_id=run.id,
            actor=run.actor,
            timeout=ctx.timeout,
            max_rework=int(p.get("max_rework", 1)),
            keep_workspaces=bool(retain.get("worktrees", False)),
            keep_patches=self.settings.store_patches,
        )
        loop = FactoryLoop(spec, ctx.git, emitter=ctx.emitter)
        total = len(backlog.ordered())
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

    def _test_author(self, ctx: RunContext, ladder: EscalationLadder) -> TestAuthor | None:
        """The run's test author, or ``None`` when this deployment has none.

        The run's ``params.test_author`` wins over the deployment's
        ``CRB_FACTORY__TEST_AUTHOR``; ``none`` in either place means no author, so a run
        can decline one a deployment configures. The label is a rung
        (``builder:model[:provider]``) and its builder must be a registered builder name,
        because the invariant the loop enforces — **the author rung and the build rung are
        never the same rung** — is a comparison of rung labels
        (:func:`crb.factory.testfirst.assert_distinct_identity`, applied to every rung by
        :class:`~crb.factory.loop.FactorySpec`). Nothing is enforced twice here; this only
        builds the author so the refusal has a label to compare, and names the ladder in the
        message when an operator has to choose another rung.
        """
        raw = str(ctx.params.get("test_author", "") or "").strip()
        if not raw:
            raw = self.settings.factory.test_author.strip()
        default_provider = str(ctx.run.provider or ctx.params.get("provider") or "")
        try:
            author = author_from_label(raw, default_provider=default_provider)
        except ValueError as exc:
            raise ValueError(
                f"test author {raw!r} cannot be used: {exc} "
                f"(this run's ladder is {[r.label for r in ladder.rungs]})"
            ) from exc
        if author is not None:
            ctx.emit("factory", "author.configured", author=author_label(author))
        return author

    def _sync_outcomes(
        self, ctx: RunContext, home: FactoryHome, cfg: Mapping[str, Any], remote: str
    ) -> None:
        """The outcome sync at the start of a factory run (B-9 / F30): for a repository
        linked through the GitHub App on the app's own host, read every delivered pull
        request whose fate can still change (``outcomes_pending`` — no outcome yet, or
        closed; a merge is terminal) and record ``delivery.merged`` / ``delivery.closed``
        (at most closed then merged per PR). No token is minted when nothing is pending.
        ``factory.outcomes.synced`` carries the report (``skipped`` with the reason when
        the repository cannot be read; ``status: error`` when the token could not be
        minted). Nothing here can fail the run."""
        installation = self._github_installation(cfg)
        full_name = str(dict(cfg.get("github") or {}).get("full_name") or "")
        if installation is None or not full_name or not self._github_host_ok(remote):
            ctx.emit(
                "factory",
                "outcomes.synced",
                status=StepStatus.SKIPPED,
                reason="not linked through the GitHub App on its own host",
            )
            return
        if not outcomes_pending(home):
            ctx.emit("factory", "outcomes.synced", checked=0, merged=0, closed=0, open=0, errors=[])
            return
        app = self._github_app()
        try:
            app.installation_token(installation)
        except GitHubAppError as exc:
            ctx.emitter.error("factory", "outcomes.synced", exc, checked=0)
            return
        report = sync_outcomes(
            home, lambda n: app.pull_request(installation, full_name, n), actor=ctx.run.actor
        )
        ctx.emit(
            "factory",
            "outcomes.synced",
            status=StepStatus.ERROR if report.errors else StepStatus.OK,
            **report.to_dict(),
        )

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
            ctx.task_id = task.task_id
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
    """The sandbox settings for one run: ``params.image`` > the repo's ``sandbox_image``
    > the worker's configured image (``CRB_SANDBOX__IMAGE`` — the DEFAULT for a repository
    that names none, as docs/DEPLOYMENT.md §2.1 says; until 2026-09-21 it silently overrode
    every repository's own image, which is wrong the moment two toolchains share a worker);
    caps come from the worker's settings. No image anywhere → :class:`SandboxUnavailable`
    (raised by ``DockerSettings``)."""
    image = str(params.get("image") or "") or config.sandbox_image or (base.image if base else "")
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
