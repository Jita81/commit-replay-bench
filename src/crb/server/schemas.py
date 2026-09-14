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
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crb.core.capability import TIERS
from crb.core.git import CloneUrlError, validate_clone_url
from crb.core.grade import MODES
from crb.core.ledger import CELL_FIELDS
from crb.core.spec import POOL_HARD, POOL_STANDARD, RUNNERS, SIZE_TIER_NAMES

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
)
#: Kinds that need a builder (they produce graded attempts).
BUILD_KINDS: frozenset[str] = frozenset({"replay", "blind"})
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


class RunProgress(BaseModel):
    done: int
    total: int
    current_task_id: str | None


class RunOut(BaseModel):
    id: str
    repo: str
    kind: str
    status: str
    mode: str
    builder: str
    model: str
    provider: str
    ladder: list[str]
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


class RunRetention(BaseModel):
    """Per-run raw-retention switches (both default off)."""

    model_config = ConfigDict(extra="forbid")

    worktrees: bool = False
    transcripts: bool = False


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1, max_length=64)
    kind: str
    mode: str | None = None
    builder: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    provider: str = Field(default="", max_length=64)
    ladder: list[str] = Field(default_factory=list, max_length=16)
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

    @field_validator("mode")
    @classmethod
    def _mode_known(cls, v: str | None) -> str | None:
        if v is not None and v not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        return v

    @field_validator("ladder")
    @classmethod
    def _ladder_labels(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for label in v:
            if not _LADDER_RE.match(label):
                raise ValueError(
                    f"ladder label {label!r} must match {_LADDER_RE.pattern} "
                    "(a rung label like 'r1' or 'builder:model[:provider]')"
                )
            if label in seen:
                raise ValueError(f"ladder label {label!r} repeated")
            seen.add(label)
        return v

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
        if self.kind in BUILD_KINDS and not self.builder:
            raise ValueError(f"kind {self.kind!r} needs a builder")
        return self


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
    false_q1: int
    oracle_strength: float | None
    policy_version: str
    verification_tier: str
    apparatus_versions: list[str]


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
    created: str
    revoked: bool
    revoked_by: str | None
    revoked_at: str | None
    active: bool
    current_false_q1: int
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
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=4000)


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
    "BUILDER_CONFIG_IDENTITY_KEYS",
    "BUILDER_CONFIG_MAX_BYTES",
    "BUILDER_CONFIG_MAX_KEYS",
    "BUILDER_CONFIG_SECRET_MARKERS",
    "BUILD_KINDS",
    "EXECUTORS",
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
