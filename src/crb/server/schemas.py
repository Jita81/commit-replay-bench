"""Request / response models for the domain routes (docs/API.md + ``ui/src/api/types.ts``).

Field names are the contract: the UI marks every field it reads with ``@contract``
in ``types.ts`` and this module mirrors those shapes one to one. Where a core
dataclass already has a ``to_dict()`` (``GradeRow``, ``TaskSpec``, ``StepEvent``,
``RouteDecision`` …) the model here lists the same keys so the OpenAPI document
is honest and a drift is a diff, not a surprise.

Invariants encoded on purpose:

* a belt is ``true | false | null`` (``null`` = never recorded, e.g. legacy v3 rows);
* a capability cell in a response is always MEASURED — an unmeasured cell is simply
  absent (the UI renders absence as ``NOT_YET_MEASURED``); nothing is zero-filled;
* every rate travels with its ``n`` and its interval (``ci_low`` / ``ci_high``);
* ``false_q1`` is a count that must read 0.

Navigation
----------
What it is:   The Pydantic request/response models of the domain routes — the API contract
              ``ui/src/api/types.ts`` mirrors field for field.
What it does: Validates every write (``RunCreateRequest`` with its ladder / budget /
              builder_config rules, repo config, sign-off bodies) and shapes every read
              (runs, tasks, grades, events, oracle, learn); a field here is a field the UI
              may rely on, nothing else is.
How:          ``BaseModel`` classes with ``extra="forbid"`` on requests, validators that
              refuse identity/credential-shaped builder kwargs and malformed ladders; the
              route modules import from here, never the reverse.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   docs/API.md (the human-readable contract), ui/src/api/types.ts (the mirror),
              src/crb/server/routes/runs.py (RunCreateRequest → Run), src/crb/server/routes/repos.py
              (repo config), src/crb/server/schemas_capability.py and
              src/crb/server/schemas_signoff.py (the map and sign-off shapes)
Tested by:    tests/test_server_routes_runs.py, tests/test_server_routes_repos.py, tests/test_server_app.py
Touch when:   any API field changes — update docs/API.md and ui/src/api/types.ts in the
              same change; never for a new repository.

"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_serializer,
    model_validator,
)

from crb.builders.base import Budget
from crb.core.capability import TIERS
from crb.core.checks import RepoChecks
from crb.core.git import CloneUrlError, validate_clone_url
from crb.core.grade import MODES
from crb.core.ledger import CELL_FIELDS
from crb.core.spec import POOL_HARD, POOL_STANDARD, RUNNERS, SIZE_TIER_NAMES
from crb.core.spend import BUDGET_PROFILES, ESCALATION_POLICIES, validate_spend_config

PAGE_DEFAULT = 50
PAGE_MAX = 500

#: Run kinds a client may create. ``probe`` is also reachable via ``POST /repos/{name}/probe``;
#: ``setup`` is the environment phase (dependency install — the only network phase).
RUN_KINDS: tuple[str, ...] = (
    "setup",
    "mine",
    "label",
    "replay",
    "blind",
    "oracle",
    "controls",
    "probe",
    "factory",
)
#: Kinds that need a builder (they produce graded attempts).
BUILD_KINDS: frozenset[str] = frozenset({"replay", "blind", "factory"})
RUN_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed", "cancelled")
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
EXECUTORS: tuple[str, ...] = ("local", "docker")

_LADDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_KWARG_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")

#: ``builder_config`` keys that would rewrite the run's recorded identity (the ledger row
#: names the rung's ``model``/``provider``; an override would make the row lie).
BUILDER_CONFIG_IDENTITY_KEYS: frozenset[str] = frozenset({"model", "provider", "name"})
#: ``builder_config`` keys that look like credentials. Secrets come from the worker's
#: environment (or the vault), never from a request body that is persisted and served.
BUILDER_CONFIG_SECRET_MARKERS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
)
BUILDER_CONFIG_MAX_KEYS = 32
BUILDER_CONFIG_MAX_BYTES = 8192

#: Upper bounds on a request's :class:`RunBudget`. A run is one operator's click; a cap
#: that would let a single attempt run for a day, or spend four figures, is a typo.
#: ``max_tokens`` / ``max_cost_usd`` accept ``0`` = "no cap" (the builder's own meaning).
BUDGET_MAX_TURNS = 1000
BUDGET_MAX_TOOL_CALLS = 5000
BUDGET_MAX_TOKENS = 50_000_000
BUDGET_MAX_COST_USD = 1000.0
BUDGET_MAX_WALL_CLOCK_S = 24 * 3600
#: The builder's defaults (``crb.builders.base.Budget``) — what a run gets when the request
#: names no ``budget``; served so the UI shows the same numbers the worker applies.
BUDGET_DEFAULTS: dict[str, Any] = Budget().to_dict()
#: The rung fields a ladder object may carry. Anything else — a builder kwarg, an identity
#: override, a credential — is refused: a rung IS the recorded identity plus its budget.
LADDER_RUNG_FIELDS: frozenset[str] = frozenset({"builder", "model", "provider", "budget"})


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageQuery:
    """``?limit=`` (default 50, max 500) ``&offset=``."""

    limit: int
    offset: int


def page_query(
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageQuery:
    return PageQuery(limit=limit, offset=offset)


PageDep = Annotated[PageQuery, Depends(page_query)]


class Page[T](BaseModel):
    """``{"items": [...], "total": n, "limit": l, "offset": o}``."""

    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------


class RepoProbe(BaseModel):
    """Probe state: ``ok | degraded | down`` once probed, ``not_probed`` before, or the
    probe run's own status while it is queued/running."""

    status: str
    run_id: str | None
    checked: str | None
    detail: str


class RepoTaskCounts(BaseModel):
    total: int
    standard: int
    hard: int
    gold_clean: int
    gold_failed: int
    unchecked: int


class RepoLastRun(BaseModel):
    id: str
    kind: str
    status: str
    finished: str | None


class RepoSummary(BaseModel):
    name: str
    language: str
    runner: str
    url: str
    clone_path: str
    probe: RepoProbe
    task_counts: RepoTaskCounts
    last_run: RepoLastRun | None
    created: str
    updated: str
    #: ``owner/name`` (lower-cased) of the GitHub repository the row is linked to through
    #: the GitHub App (``repos.github_full_name``); ``None`` for a repository registered by
    #: URL — what the Connect dialog's "link to an existing repository" select filters on.
    github_full_name: str | None = None


class RepoDetail(RepoSummary):
    config: dict[str, Any]
    profile_computed_at: str | None = None


class _RepoConfigFields(BaseModel):
    """Every :class:`~crb.core.spec.RepoConfig` field a client may set. All optional so the
    same shape serves create (with defaults) and update (partial)."""

    model_config = ConfigDict(extra="forbid")

    clone_path: str | None = Field(default=None, max_length=4096)
    url: str | None = Field(default=None, max_length=2048)
    runner: str | None = None
    src_prefix: str | None = Field(default=None, max_length=512)
    test_prefix: str | None = Field(default=None, max_length=512)
    ext: str | None = Field(default=None, max_length=32)
    test_mode: str | None = None
    test_suffix: str | None = Field(default=None, max_length=128)
    belt_scope: str | list[str] | None = None
    probe: str | None = Field(default=None, max_length=1024)
    layer: str | None = Field(default=None, max_length=64)
    runner_opts: dict[str, Any] | None = None
    sandbox_image: str | None = Field(default=None, max_length=512)
    mining: dict[str, int] | None = None
    #: The repository's spend switches (``RepoConfig.spend``, crb.core.spend):
    #: ``{"budget_profile": "default"|"calibrated", "escalation": "measured"|"always"}``.
    #: A run's own ``budget_profile`` / ``escalation`` wins.
    spend: dict[str, str] | None = None

    @field_validator("spend")
    @classmethod
    def _spend_known(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return None if v is None else validate_spend_config(v)

    #: "Clean means working" switches for the repository (ADR-0024) — the one surface the
    #: prevention loop writes: ``format_step``, ``finish_gate``, ``api_stable``, declared
    #: ``commands`` / ``formatter``. Validated by ``crb.core.checks.RepoChecks``; a
    #: change is a ``repo.updated`` event with its diff, like every config change.
    checks: dict[str, Any] | None = None

    @field_validator("checks")
    @classmethod
    def _checks_shape(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None:
            RepoChecks.from_config(v)  # ValueError → 422 with the reason
        return v

    @field_validator("runner")
    @classmethod
    def _runner_known(cls, v: str | None) -> str | None:
        if v is not None and v and v not in RUNNERS:
            raise ValueError(f"runner must be one of {RUNNERS}")
        return v

    def config_updates(self) -> dict[str, Any]:
        """The fields that were actually supplied, in ``RepoConfig.from_dict`` vocabulary."""
        out: dict[str, Any] = {}
        for name, value in self.model_dump(exclude_unset=True).items():
            if value is None:
                continue
            out["path" if name == "clone_path" else name] = value
        return out


class RepoCreateRequest(_RepoConfigFields):
    """``POST /repos``. One of ``clone_path`` / ``url`` is required.

    With ``clone_path`` the URL is informational. Without it the worker clones the
    URL on the repo's first run, so the URL is policy-checked here
    (:func:`crb.core.git.validate_clone_url`: https/ssh only, no local sources) — a
    repo that could never be cloned is refused at registration, not at first run.
    """

    name: str = Field(min_length=1, max_length=64)
    language: str = Field(min_length=1, max_length=32)

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("name must be lowercase [a-z0-9._-], at most 64 characters")
        return v

    @model_validator(mode="after")
    def _needs_location(self) -> RepoCreateRequest:
        if not (self.clone_path or self.url):
            raise ValueError("one of clone_path or url is required")
        if not self.clone_path and self.url:
            try:
                self.url = validate_clone_url(self.url)
            except CloneUrlError as exc:
                raise ValueError(f"url: {exc}") from exc
        return self


class RepoUpdateRequest(_RepoConfigFields):
    """``PUT /repos/{name}`` — a partial update; ``name`` cannot change."""

    language: str | None = Field(default=None, min_length=1, max_length=32)


class ProfileCell(BaseModel):
    capability_class: str
    size: str
    count: int
    share: float


class RepoProfile(BaseModel):
    repo: str
    ref: str
    n_commits: int
    examined: int
    skipped: int
    classes: list[str]
    sizes: list[str]
    cells: list[ProfileCell]
    class_totals: dict[str, int]
    size_totals: dict[str, int]
    computed_at: str


class TaskSpecOut(BaseModel):
    """:meth:`crb.core.spec.TaskSpec.to_dict`."""

    task_id: str
    repo: str
    subject: str
    authored: str
    test_files: list[str]
    src_files: list[str]
    target_tests: list[str]
    belt_scope: list[str]
    pool: str
    src_churn: int
    size: str
    capability_class: str
    language: str
    baseline_failing: list[str]
    red_checked: bool
    gold_clean: bool | None
    gold_note: str
    labels: dict[str, str]
    #: The two class axes (A4): ``capability_class`` is the RESOLVED class; these say how.
    path_class: str = ""
    intent: dict[str, Any] | None = None
    class_source: str = "path"


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunCounts(BaseModel):
    """:meth:`crb.core.run.RunSummary.to_dict` — live while running, final when terminal."""

    tasks: int = 0
    clean: int = 0
    disqualified: int = 0
    errors: int = 0
    first_pass_clean: int = 0
    rows: int = 0
    duration_s: float = 0.0
    stopped_reason: str = ""
    #: The run kind's OWN counters when the kind is not a build (replay / blind / factory
    #: keep the RunSummary above): served VERBATIM from the worker's ``counts_json`` —
    #: a mine run's ``{examined, found, gold_clean, gold_dirty, skipped, known, pool}``, a
    #: setup run's steps, an oracle run's ``{scoreable, mutants, killed, escaped, errors,
    #: oracle_strength, …}``, a controls run's ``{rows, violations, escapes, …}``, a label
    #: run's ``{labelled, labels, usage: {calls, cost_usd, cost_known, …}}``
    #: (docs/API.md#runs). ``{}`` for a replay / blind run; a FACTORY run is the one build
    #: kind that fills it — its own ``{items, done, accepted, by_status, outcomes}`` sit
    #: here next to the RunSummary derived from its graded attempts (``_counts``).
    detail: dict[str, Any] = Field(default_factory=dict)


class RunFactoryOut(BaseModel):
    """What a factory run was allowed to do (J-FAC-6), from its ``params``: delivery on or
    off, the approver who overrode the route gate (id, and the display name resolved at
    read time as sign-offs do — the row keeps the id), and the backlog hash it worked."""

    deliver: bool
    deliver_override_by: str | None
    deliver_override_by_name: str | None
    backlog_hash: str


class RunProgress(BaseModel):
    done: int
    total: int
    current_task_id: str | None


class RunBudget(BaseModel):
    """Per-attempt caps (``crb.builders.base.Budget``): turns, tool calls, tokens, dollars,
    wall clock. Every field is optional — an absent field keeps the next level's value
    (rung → run → the builder's default), so ``{"max_tool_calls": 50}`` on a rung changes
    ONE cap and inherits the rest. ``max_tokens`` / ``max_cost_usd`` accept ``0`` = no cap;
    turns, tool calls and wall clock are always bounded (a loop with no bound is a bug)."""

    model_config = ConfigDict(extra="forbid")

    max_turns: int | None = Field(default=None, ge=1, le=BUDGET_MAX_TURNS)
    max_tool_calls: int | None = Field(default=None, ge=1, le=BUDGET_MAX_TOOL_CALLS)
    max_tokens: int | None = Field(default=None, ge=0, le=BUDGET_MAX_TOKENS)
    max_cost_usd: float | None = Field(default=None, ge=0.0, le=BUDGET_MAX_COST_USD)
    wall_clock_s: int | None = Field(default=None, ge=1, le=BUDGET_MAX_WALL_CLOCK_S)

    def overrides(self) -> dict[str, Any]:
        """Only the fields the request set — what is stored and what overrides."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        """Serialised as :meth:`overrides` — a response echoes what was declared, not a
        ``null`` for every cap the rung inherits."""
        return self.overrides()


class LadderRung(BaseModel):
    """An object rung of a ladder: ``{builder, model, provider?, budget?}``. The identity
    (``builder:model[:provider]``) is what the ledger row will name; ``budget`` overrides
    the run's ``budget`` for THIS rung only. Nothing else is accepted on a rung — builder
    kwargs go in ``builder_config`` (every rung), identity is the rung itself, and a
    credential is never a request field."""

    model_config = ConfigDict(extra="forbid")

    builder: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="", max_length=64)
    budget: RunBudget | None = None

    @model_validator(mode="before")
    @classmethod
    def _refuse_foreign_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in data:
                k = str(key)
                if k in LADDER_RUNG_FIELDS:
                    continue
                if any(marker in k for marker in BUILDER_CONFIG_SECRET_MARKERS):
                    raise ValueError(
                        f"a ladder rung must not carry credentials ({k!r}); "
                        "provider keys come from the worker's environment"
                    )
                if k in BUILDER_CONFIG_IDENTITY_KEYS or k == "config":
                    raise ValueError(
                        f"a ladder rung must not set {k!r}: the rung's builder/model/provider "
                        "IS the recorded identity; builder kwargs go in builder_config"
                    )
                raise ValueError(
                    f"unknown rung field {k!r} (a rung is {{builder, model, provider?, budget?}})"
                )
        return data

    @field_validator("builder")
    @classmethod
    def _builder_name(cls, v: str) -> str:
        if not _KWARG_RE.match(v):
            raise ValueError(f"rung builder {v!r} is not a builder name (lowercase identifier)")
        return v

    @field_validator("model", "provider")
    @classmethod
    def _identity_chars(cls, v: str) -> str:
        if v and not _LADDER_RE.match(v):
            raise ValueError(f"rung identity {v!r} must match {_LADDER_RE.pattern}")
        return v

    def stored(self) -> dict[str, Any]:
        """The shape ``ladder_json`` keeps: identity + only the budget fields that were set."""
        d: dict[str, Any] = {"builder": self.builder, "model": self.model}
        if self.provider:
            d["provider"] = self.provider
        if self.budget is not None and self.budget.overrides():
            d["budget"] = self.budget.overrides()
        return d

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        """Serialised as :meth:`stored`, so ``GET /runs/{id}.ladder`` is ``ladder_json``."""
        return self.stored()


def _ladder_entry_kind(value: Any) -> str:
    """Route a ladder entry to ONE branch by shape, so a malformed object rung reports the
    rung's own error (``a ladder rung must not carry credentials …``) instead of pydantic's
    "not a string / not a rung" pair."""
    return "rung" if isinstance(value, dict | LadderRung) else "label"


#: A ladder entry: a rung label (``r1``, ``builder:model[:provider]``) or an object rung.
LadderEntry = Annotated[
    Annotated[str, Tag("label")] | Annotated[LadderRung, Tag("rung")],
    Discriminator(_ladder_entry_kind),
]


class RunOut(BaseModel):
    id: str
    repo: str
    kind: str
    status: str
    mode: str
    builder: str
    model: str
    provider: str
    #: What was declared: rung labels and/or object rungs, as sent (``ladder_json``).
    ladder: list[LadderEntry]
    #: Run-level budget overrides (``params.budget``; ``{}`` when the defaults apply).
    budget: dict[str, Any]
    executor: str
    timeout: int
    pool: str
    limit: int | None
    task_ids: list[str]
    builder_config: dict[str, Any]
    retain: RunRetention
    actor: str
    created: str
    started: str | None
    finished: str | None
    cancel_requested: bool
    error: str
    cost_usd: float
    apparatus_version: str
    apparatus: dict[str, Any]
    worker_id: str
    heartbeat: str | None
    counts: RunCounts
    progress: RunProgress
    #: 1-based place in the FIFO queue (queued runs created before this one + 1); ``null``
    #: unless the run is queued (J-TEL-3).
    queue_position: int | None = None
    #: The kinds of the queued runs ahead of this one, oldest first (``[]`` unless queued).
    queue_kinds_ahead: list[str] = Field(default_factory=list)
    #: A factory run's delivery posture; ``null`` for every other kind (J-FAC-6).
    factory: RunFactoryOut | None = None


class RunRetention(BaseModel):
    """Per-run raw-retention switches (both default off)."""

    model_config = ConfigDict(extra="forbid")

    worktrees: bool = False
    transcripts: bool = False


class RunChecksIn(BaseModel):
    """``params.checks`` — this run's override of the repository's switches (ADR-0024).
    ``null`` / absent = the repository's value (itself OFF by default)."""

    model_config = ConfigDict(extra="forbid")

    format_step: bool | None = None
    finish_gate: bool | None = None
    api_stable: bool | None = None

    def overrides(self) -> dict[str, bool]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class PreflightIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fix: bool = True
    repair_turns: int = Field(default=1, ge=0, le=3)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1, max_length=64)
    kind: str
    mode: str | None = None
    builder: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    provider: str = Field(default="", max_length=64)
    #: The escalation ladder — one attempt per rung until an attempt grades clean. Each
    #: entry is a rung LABEL (``r1`` = the run's own builder:model, or
    #: ``builder:model[:provider]``) or a rung OBJECT ``{builder, model, provider?, budget?}``
    #: whose ``budget`` overrides the run's for that rung. The same model at an escalating
    #: budget (25 → 50 → 100 tool calls) is a ladder; so is a cheap model then a strong one.
    ladder: list[LadderEntry] = Field(default_factory=list, max_length=16)
    #: Run-level per-attempt caps. Absent fields keep the builder's defaults
    #: (:data:`BUDGET_DEFAULTS`); a rung's own ``budget`` overrides these for that rung.
    #: Stored as ``params.budget`` (only the fields set) and stamped into the apparatus.
    budget: RunBudget | None = None
    task_ids: list[str] = Field(default_factory=list, max_length=5000)
    limit: int | None = Field(default=None, ge=1)
    pool: str = ""
    executor: str = ""
    timeout: int | None = Field(default=None, ge=1, le=24 * 3600)
    #: Constructor keyword arguments applied to EVERY builder on the ladder (e.g.
    #: ``{"auth": "cli", "effort": "high"}`` for ``claude_code``). Stored in
    #: ``params.builder_config``, passed as ``builder_overrides`` by the worker and
    #: stamped into the run's apparatus. Identity and credential keys are refused.
    builder_config: dict[str, Any] = Field(default_factory=dict)
    #: Retention for THIS run, decided by the operator who queues it (ADR-0006 keeps the
    #: default at zero raw retention): ``worktrees`` keeps every attempt's worktree under
    #: the worker's scratch so a human can read the accepted patch; ``transcripts`` keeps
    #: the builder transcript (redacted, referenced from the evidence pack). Stored under
    #: ``params.retain`` and served on the run.
    retain: RunRetention = Field(default_factory=RunRetention)
    #: Provider circuit breaker for build kinds: stop the run after this many consecutive
    #: attempts the provider refused (``failure_kind: outage``); ``0`` disables; ``None`` =
    #: the worker's default (3). Stored as ``params.outage_stop`` only when set.
    outage_stop: int | None = Field(default=None, ge=0, le=1000)
    #: Belt-5 pre-flight for build kinds (``crb.builders.adapter.Preflight``): ``true`` =
    #: apply the repository's own fixers then one bounded repair turn; an object sets
    #: ``{fix, repair_turns}``. OFF when absent. A run with it on is recorded as the
    #: builder ``<name>+preflight`` — a different arm, never pooled with plain rows.
    preflight: bool | PreflightIn | None = None
    #: Build kinds: ``calibrated`` runs each attempt under caps taken from the ledger's own
    #: clean completions in its cell (p90 × 1.5, never below the run's caps, never above
    #: twice them, only with ≥ 8 clean rows; crb.core.spend). Changes what the builder is
    #: given, so OFF (``default``) unless asked; recorded on every row (``budget_profile``,
    #: ``budget_calibration``, ``budget_tier``). ``None`` = the repository's ``spend`` setting.
    budget_profile: str | None = None
    #: Build kinds: ``measured`` (the default) stops a task climbing to the next rung where
    #: that rung's prior escalations in the cell yielded under 10% clean (with ≥ 10 of them);
    #: ``always`` climbs every rung. The decision and the rule are on the row.
    #: ``None`` = the repository's ``spend`` setting, else ``measured``.
    escalation: str | None = None
    #: "Clean means working" for THIS run (ADR-0024): ``format_step`` (the repository's own
    #: formatter before grading), ``finish_gate`` (the repository's checks as the brief's
    #: checklist, verified, one repair turn) and ``api_stable`` (belt 6). Each overrides the
    #: repository's ``checks`` block; absent = the repository's (OFF by default). Stored as
    #: ``params.checks`` and every row records the resolved switches (``labels.checks``).
    checks: RunChecksIn | None = None
    #: The prevention loop (ADR-0020): ``"off"`` opts THIS run out of the repository's
    #: learning switch — no playbook line, no overlay, rows stamped ``learn: off``. A run may
    #: opt out, never in (the switch is the repository's, thrown by an operator). Stored as
    #: ``params.learning`` only when set; the Phase B campaign's off arm uses it.
    learning: Literal["off"] | None = None
    #: ``factory`` runs only: the frozen backlog this run is meant to work. When set it
    #: must equal the repo's ACTIVE backlog hash or the request is refused (409
    #: ``backlog_hash_mismatch``); the active hash is always stamped into
    #: ``params.backlog_hash`` at enqueue and re-verified by the worker on claim, so a
    #: backlog re-registered between the two fails the run instead of being worked.
    backlog_hash: str | None = Field(default=None, min_length=8, max_length=64)
    #: ``factory`` runs only. ``deliver``: open a branch + pull request for a clean build
    #: (OFF by default; needs a credentials provider on the worker). Delivery is ROUTE-GATED:
    #: it happens only when the item's (class × size) cell routes ``deliver`` on the
    #: capability map; otherwise it is withheld and recorded (DL-038). ``deliver_override``:
    #: an APPROVER's one-run override of that gate — the caller's identity is stamped into
    #: ``params.deliver_override_by`` and onto the evidence chain. ``max_rework``: how many
    #: review-driven rework cycles an item may take (default 1).
    deliver: bool | None = None
    deliver_override: bool | None = None
    max_rework: int | None = Field(default=None, ge=0, le=5)
    #: ``factory`` runs only. The rung that writes the failing test for an item nobody
    #: authored an oracle for — ``builder:model[:provider]``, the same spelling as a build
    #: rung, or ``none`` for no author. Absent = the deployment's ``CRB_FACTORY__TEST_AUTHOR``.
    #: The author rung and the build rung are never the same rung: a label that is also on
    #: this run's ladder is refused before anything is built.
    test_author: str | None = Field(default=None, max_length=200)

    @field_validator("kind")
    @classmethod
    def _kind_known(cls, v: str) -> str:
        if v not in RUN_KINDS:
            raise ValueError(f"kind must be one of {RUN_KINDS}")
        return v

    @field_validator("builder_config")
    @classmethod
    def _builder_config_shape(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > BUILDER_CONFIG_MAX_KEYS:
            raise ValueError(f"builder_config has more than {BUILDER_CONFIG_MAX_KEYS} keys")
        for key in v:
            if not _KWARG_RE.match(key):
                raise ValueError(
                    f"builder_config key {key!r} is not a builder keyword (lowercase identifier)"
                )
            if key in BUILDER_CONFIG_IDENTITY_KEYS:
                raise ValueError(
                    f"builder_config must not set {key!r}: the rung's builder:model[:provider] "
                    "is the recorded identity"
                )
            if any(marker in key for marker in BUILDER_CONFIG_SECRET_MARKERS):
                raise ValueError(
                    f"builder_config must not carry credentials ({key!r}); "
                    "provider keys come from the worker's environment"
                )
        if len(json.dumps(v, ensure_ascii=False)) > BUILDER_CONFIG_MAX_BYTES:
            raise ValueError(f"builder_config exceeds {BUILDER_CONFIG_MAX_BYTES} bytes")
        return v

    @field_validator("budget_profile")
    @classmethod
    def _profile_known(cls, v: str | None) -> str | None:
        if v is not None and v not in BUDGET_PROFILES:
            raise ValueError(f"budget_profile must be one of {BUDGET_PROFILES}")
        return v

    @field_validator("escalation")
    @classmethod
    def _escalation_known(cls, v: str | None) -> str | None:
        if v is not None and v not in ESCALATION_POLICIES:
            raise ValueError(f"escalation must be one of {ESCALATION_POLICIES}")
        return v

    @field_validator("mode")
    @classmethod
    def _mode_known(cls, v: str | None) -> str | None:
        if v is not None and v not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        return v

    @field_validator("ladder")
    @classmethod
    def _ladder_rungs(cls, v: list[LadderEntry]) -> list[LadderEntry]:
        """Labels must be well-formed and unique; object rungs must not repeat exactly
        (the same identity at DIFFERENT budgets is the point of a budget ladder; the
        same identity at the same budget twice is a repeated label by another name)."""
        seen: set[str] = set()
        for entry in v:
            if isinstance(entry, LadderRung):
                key = json.dumps(entry.stored(), sort_keys=True)
                if key in seen:
                    raise ValueError(f"ladder rung {entry.stored()} repeated")
                seen.add(key)
                continue
            if not _LADDER_RE.match(entry):
                raise ValueError(
                    f"ladder label {entry!r} must match {_LADDER_RE.pattern} "
                    "(a rung label like 'r1' or 'builder:model[:provider]')"
                )
            if entry in seen:
                raise ValueError(f"ladder label {entry!r} repeated")
            seen.add(entry)
        return v

    def stored_ladder(self) -> list[Any]:
        """``ladder_json``: labels as written, object rungs as :meth:`LadderRung.stored`."""
        return [e.stored() if isinstance(e, LadderRung) else e for e in self.ladder]

    @field_validator("task_ids")
    @classmethod
    def _task_ids_are_shas(cls, v: list[str]) -> list[str]:
        for tid in v:
            if not _SHA_RE.match(tid):
                raise ValueError(f"task id {tid!r} is not a git sha")
        return v

    @field_validator("pool")
    @classmethod
    def _pool_known(cls, v: str) -> str:
        if v and v not in (POOL_STANDARD, POOL_HARD):
            raise ValueError(f"pool must be {POOL_STANDARD!r} or {POOL_HARD!r}")
        return v

    @field_validator("executor")
    @classmethod
    def _executor_known(cls, v: str) -> str:
        if v and v not in EXECUTORS:
            raise ValueError(f"executor must be one of {EXECUTORS}")
        return v

    @model_validator(mode="after")
    def _kind_consistency(self) -> RunCreateRequest:
        if self.kind == "blind":
            if self.mode is None:
                self.mode = "blind"
            elif self.mode != "blind":
                raise ValueError("kind 'blind' implies mode 'blind'")
        elif self.mode is None:
            self.mode = "sighted"
        if self.kind in BUILD_KINDS and not self.builder and not self.object_rungs_only:
            raise ValueError(
                f"kind {self.kind!r} needs a builder (or a ladder of object rungs "
                "{builder, model, …}, whose first rung names the run's builder)"
            )
        return self

    @property
    def object_rungs_only(self) -> bool:
        """Every ladder entry is an object rung — the ladder carries the identity itself."""
        return bool(self.ladder) and all(isinstance(e, LadderRung) for e in self.ladder)


class Belts(BaseModel):
    """Belt values; ``repo_lint_clean`` (belt 5, ADR-0011) is ``null`` when not
    evaluated — the row's ``belt_set`` says whether it was recorded at all."""

    tests_unmodified: bool | None
    target_green: bool | None
    no_new_failures: bool | None
    source_changed: bool | None
    repo_lint_clean: bool | None = None


class RunTaskRow(BaseModel):
    """One task of a run: its trials collapsed, the belts of the decisive attempt."""

    task_id: str
    capability_class: str
    size: str
    pool: str
    language: str
    trials: int
    clean: bool
    first_pass_clean: bool
    #: The decisive attempt's belt set (``v5`` = five belts shown, else four).
    belt_set: str = ""
    disqualified: bool
    error: str
    belts: Belts
    cost_usd: float
    latency_s: float
    pack_hashes: list[str]
    row_ids: list[str]
    #: The decisive attempt's budget tier (``labels.budget_tier``, e.g. ``25/25/900`` =
    #: tool calls / turns / wall-clock seconds); ``""`` on rows written before the label.
    budget_tier: str = ""
    #: One tier per attempt, aligned with ``row_ids`` — how far up the budget ladder the
    #: task went. A blind rate quoted without its tier is not a claim.
    budget_tiers: list[str] = Field(default_factory=list)


class StepEventOut(BaseModel):
    """:meth:`crb.observability.events.StepEvent.to_dict`."""

    event_id: str
    seq: int
    timestamp: str
    trace_id: str
    step_id: str
    parent_step_id: str
    stage: str
    action: str
    status: str
    actor: str
    repo: str
    task_id: str
    input_ref: str
    output_ref: str
    error_code: str
    error_message: str
    duration_ms: int | None
    cost_usd: float | None
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Grades / tasks / evidence
# ---------------------------------------------------------------------------


class GradeRowOut(BaseModel):
    """:meth:`crb.core.ledger.GradeRow.to_dict` — belts flat on the row, chain fields included.

    ``seq`` is the store's insertion order (the chain order); it is not part of the
    hashed body."""

    seq: int
    repo: str
    task_id: str
    clean: bool
    tests_unmodified: bool | None
    target_green: bool | None
    no_new_failures: bool | None
    source_changed: bool | None
    repo_lint_clean: bool | None = None
    capability_class: str
    size: str
    language: str
    pool: str
    mode: str
    process_step: str
    builder: str
    model: str
    provider: str
    run_id: str
    trial: str
    actor: str
    created: str
    disqualified: bool
    dq_reason: str
    error: str
    new_failures_count: int
    attempts: int
    cost_usd: float
    tokens_in: int
    tokens_out: int
    latency_s: float
    oracle_strength: float | None
    gold_clean: bool | None
    evidence_pack_hash: str
    apparatus_version: str
    belt_set: str
    provenance: str
    labels: dict[str, str]
    schema_: str = Field(alias="schema")
    row_id: str
    prev_hash: str
    row_hash: str

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class TaskDetail(BaseModel):
    spec: TaskSpecOut
    grades: list[GradeRowOut]


class EvidenceResponse(BaseModel):
    """``{pack, verified}`` — ``verified`` is the recomputed canonical hash matching the key."""

    pack: dict[str, Any]
    verified: bool
    pack_hash: str
    schema_: str = Field(alias="schema")
    repo: str
    task_id: str
    run_id: str
    created: str

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


# ---------------------------------------------------------------------------
# Capability / routing
# ---------------------------------------------------------------------------


class RoutingPolicyOut(BaseModel):
    min_n: int
    min_point: float
    min_ci_low: float
    min_oracle_strength: float
    granularize_sizes: list[str]
    version: str


class CapabilityCellOut(BaseModel):
    """A MEASURED cell. Non-projected key fields read ``"*"``."""

    process_step: str
    capability_class: str
    size: str
    language: str
    builder: str
    model: str
    provider: str
    label: str
    n: int
    clean: int
    disqualified: int
    errors: int
    rows: int
    repos: int
    point: float
    ci_low: float
    ci_high: float
    sigma: float | None
    false_q1: int
    cost_usd_mean: float
    latency_s_mean: float
    cost_known: bool
    latency_known: bool
    oracle_strength_mean: float | None
    route: str
    reason: str
    verification_tier: str
    apparatus_versions: list[str]
    belt_set: str
    belt_sets: list[str]
    #: B-9 / F30 — pull requests the factory opened from items in this cell, and how many
    #: of them a person merged. COUNTS from the factory evidence chain (no rate, no
    #: interval: a merge is a human decision, not a measurement of the builder); a key
    #: field that is not projected sums over its values.
    n_delivered: int = 0
    n_merged: int = 0

    @field_validator("verification_tier")
    @classmethod
    def _tier_known(cls, v: str) -> str:
        if v not in TIERS:
            raise ValueError(f"verification_tier {v!r} not in {TIERS}")
        return v


class CapabilitySummary(BaseModel):
    """``trusted_autonomy_coverage`` is ``null`` until the repo has a change profile —
    a coverage number without a profile would be fabricated."""

    trusted_autonomy_coverage: float | None
    earned_coverage: float | None
    profile_commits: int | None
    total_cells: int
    measured_cells: int
    deliver_cells: int
    cells_by_route: dict[str, int]
    n_total: int
    rows: int
    false_q1_total: int
    apparatus_versions: list[str]
    signoffs_applied: int


class CapabilityMapOut(BaseModel):
    repo: str
    by: list[str]
    classes: list[str]
    sizes: list[str]
    languages: list[str]
    models: list[str]
    cells: list[CapabilityCellOut]
    summary: CapabilitySummary
    policy: RoutingPolicyOut

    @field_validator("by")
    @classmethod
    def _by_fields(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in CELL_FIELDS]
        if unknown:
            raise ValueError(f"unknown cell-key field(s) {unknown}")
        return v


class RouteDecisionOut(BaseModel):
    """:meth:`crb.core.routing.RouteDecision.to_dict` + the cell's tier and label."""

    route: str
    reason: str
    cell: dict[str, str]
    label: str
    n: int
    point: float
    ci_low: float
    #: The upper Wilson bound — not an input to the rule (``ci_low`` routes) but served so a
    #: client never mirrors an asymmetric interval from its lower bound (CodeRabbit on PR #6).
    ci_high: float = 1.0
    false_q1: int
    oracle_strength: float | None
    policy_version: str
    #: The bar as numbers beside its name (ADR-0003 amendment 2026-09-16) — a client never
    #: has to look a version up, and a tightened deployment policy is visible per decision.
    policy_thresholds: dict[str, Any] = {}
    verification_tier: str
    apparatus_versions: list[str]
    #: The belt sets behind ``n`` (``v4`` / ``v5``…), the provenance every rendered rate keeps.
    belt_sets: list[str] = []


class RoutesResponse(BaseModel):
    repo: str
    by: list[str]
    policy: RoutingPolicyOut
    decisions: list[RouteDecisionOut]


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


class ForecastMixItem(BaseModel):
    capability_class: str
    size: str
    count: int


class ComponentForecastOut(BaseModel):
    component: str
    capability_class: str
    size: str
    count: int
    route: str
    n: int
    point: float | None
    ci_low: float | None
    verification_tier: str | None
    config: str
    unit_cost_usd: float | None
    unit_cost_sigma: float | None
    unit_minutes: float | None
    p_clean: float | None
    why: str


class ForecastBuildOut(BaseModel):
    """:meth:`crb.core.forecast.Forecast.to_dict` with the UI's short names alongside:
    ``cost_usd_mean`` / ``cost_usd_std`` / ``minutes`` / ``buildable_p`` (= ``p_clean_mean``,
    the expected per-unit clean probability over measured units)."""

    repo: str
    mix: list[ForecastMixItem]
    cost_usd_mean: float
    cost_usd_std: float
    minutes: float
    deliver: int
    human: int
    calibrate: int
    buildable_p: float
    buildable_p_stddev: float
    unmeasured: list[str]
    components: int
    measured_components: int
    coverage: float
    costed_components: int
    timed_components: int
    units_by_route: dict[str, int]
    expected_clean_units: float
    single_rep_band: bool
    per_component: list[ComponentForecastOut]
    policy_version: str


class ReadinessThresholdsOut(BaseModel):
    min_coverage: float
    min_reps: int
    require_earned_tier: bool
    max_false_q1: int
    min_buildable: float
    version: str


class ForecastReadinessOut(BaseModel):
    repo: str
    ok: bool
    gaps: list[str]
    mix: list[ForecastMixItem]
    mix_source: str
    total: int
    measured: int
    coverage: float
    min_reps_seen: int
    earned_units: int
    buildable_units: int
    buildable_frac: float
    false_q1_total: int
    thresholds: ReadinessThresholdsOut
    policy_version: str


# ---------------------------------------------------------------------------
# Sign-offs
# ---------------------------------------------------------------------------


class SignoffEvidence(BaseModel):
    """What the approver saw when signing (stamped at write time, hash-covered)."""

    n: int
    point: float
    ci_low: float
    ci_high: float
    false_q1: int
    apparatus_versions: list[str]


class SignoffOut(BaseModel):
    id: str
    repo: str
    cell: dict[str, str]
    tier: str
    note: str
    approver: str
    #: The approver's display name resolved from the users table at READ time; ``approver``
    #: stays the stable user id the hash chain covers (a name may change, an id may not).
    #: Empty when the account no longer exists.
    approver_name: str = ""
    #: The kind of account that signed (F34): ``oidc`` | ``local`` | ``service`` (reserved —
    #: a delegated signature, never minted by this API); ``""`` on a row written before the
    #: field existed. Hash-covered on new rows; a service signature can never read as a person's.
    verifier_kind: str = ""
    created: str
    revoked: bool
    revoked_by: str | None
    revoked_by_name: str | None = None
    revoked_at: str | None
    active: bool
    current_false_q1: int
    #: The attestation was made on an earlier apparatus than the one this deployment reads
    #: at now: it stays on the record but lifts nothing (evidence expires when the
    #: apparatus changes — EVIDENCE-AND-CLAIMS §4); the Decisions inbox offers re-sign or
    #: revoke. ``apparatus_current`` is the deployment's apparatus for comparison. A record
    #: signed on a ``checks`` arm other than the one the repository's cells are read on now
    #: is stale too (ADR-0024): ``checks_arm`` is the arm it was signed on (``off`` for a
    #: record from before the switchboard) and ``checks_arm_current`` the repository's arm
    #: now (``""`` for a record not tied to one repository).
    stale: bool = False
    apparatus_current: str = ""
    checks_arm: str = ""
    checks_arm_current: str = ""
    evidence: SignoffEvidence
    prev_hash: str
    row_hash: str


class SignoffCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1, max_length=64)
    cell: dict[str, str]
    note: str = Field(default="", max_length=4000)
    tier: str = "human-verified"

    @field_validator("cell")
    @classmethod
    def _cell_fields(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = sorted(k for k in v if k not in CELL_FIELDS)
        if unknown:
            raise ValueError(f"unknown cell field(s) {unknown}; expected a subset of {CELL_FIELDS}")
        cls_ = str(v.get("capability_class", "")).strip()
        if not cls_ or cls_ == "*":
            raise ValueError("cell.capability_class is required")
        size = str(v.get("size", "")).strip()
        if size and size != "*" and size not in SIZE_TIER_NAMES:
            raise ValueError(f"cell.size {size!r} not in {SIZE_TIER_NAMES}")
        return {k: str(x).strip() for k, x in v.items() if str(x).strip()}


class SignoffRevokeRequest(BaseModel):
    """``POST /signoffs/{id}/revoke`` body. The reason is REQUIRED (DL-043): a revocation
    withdraws a human attestation from the record, and an auditor reads why next to it —
    the API refuses a blank one, not just the UI."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=4000)

    @field_validator("note")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a revocation needs a reason")
        return v.strip()


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class LedgerVerifyOut(BaseModel):
    rows: int
    ok: bool
    false_q1_total: int
    chain_ok: bool
    broken_at: int | None
    detail: str
    clean_without_pack: int
    verified_at: str


class LedgerImportOut(BaseModel):
    imported: int
    skipped: int
    read: int
    rows: int
    source_chain_ok: bool | None


# ---------------------------------------------------------------------------
# Oracle adequacy
# ---------------------------------------------------------------------------


class AdequacyPolicyOut(BaseModel):
    autoship_floor: float
    adequate_floor: float
    version: str


class OracleTaskOut(BaseModel):
    task_id: str
    capability_class: str
    size: str
    strength: float | None
    band: str
    mutants: int
    killed: int
    errors: int
    gate: str
    run_id: str
    scored_at: str
    note: str


class OracleCellOut(BaseModel):
    capability_class: str
    size: str
    n: int
    tasks: int
    strength_mean: float | None
    strength_min: float | None
    band: str
    gate: str


class OracleReportOut(BaseModel):
    repo: str
    policy: AdequacyPolicyOut
    tasks: list[OracleTaskOut]
    cells: list[OracleCellOut]
    apparatus_versions: list[str]
    runs: list[str]


__all__ = [
    "BUDGET_DEFAULTS",
    "BUDGET_MAX_COST_USD",
    "BUDGET_MAX_TOKENS",
    "BUDGET_MAX_TOOL_CALLS",
    "BUDGET_MAX_TURNS",
    "BUDGET_MAX_WALL_CLOCK_S",
    "BUILDER_CONFIG_IDENTITY_KEYS",
    "BUILDER_CONFIG_MAX_BYTES",
    "BUILDER_CONFIG_MAX_KEYS",
    "BUILDER_CONFIG_SECRET_MARKERS",
    "BUILD_KINDS",
    "EXECUTORS",
    "LADDER_RUNG_FIELDS",
    "PAGE_DEFAULT",
    "PAGE_MAX",
    "RUN_KINDS",
    "RUN_STATUSES",
    "TERMINAL_STATUSES",
    "AdequacyPolicyOut",
    "Belts",
    "CapabilityCellOut",
    "CapabilityMapOut",
    "CapabilitySummary",
    "ComponentForecastOut",
    "EvidenceResponse",
    "ForecastBuildOut",
    "ForecastMixItem",
    "ForecastReadinessOut",
    "GradeRowOut",
    "LadderEntry",
    "LadderRung",
    "LedgerImportOut",
    "LedgerVerifyOut",
    "OracleCellOut",
    "OracleReportOut",
    "OracleTaskOut",
    "Page",
    "PageDep",
    "PageQuery",
    "ProfileCell",
    "ReadinessThresholdsOut",
    "RepoCreateRequest",
    "RepoDetail",
    "RepoLastRun",
    "RepoProbe",
    "RepoProfile",
    "RepoSummary",
    "RepoTaskCounts",
    "RepoUpdateRequest",
    "RouteDecisionOut",
    "RoutesResponse",
    "RoutingPolicyOut",
    "RunBudget",
    "RunCounts",
    "RunCreateRequest",
    "RunOut",
    "RunProgress",
    "RunTaskRow",
    "SignoffCreateRequest",
    "SignoffEvidence",
    "SignoffOut",
    "SignoffRevokeRequest",
    "StepEventOut",
    "TaskDetail",
    "TaskSpecOut",
    "page_query",
]
