/**
 * Wire types for the crb HTTP API v1 (docs/API.md).
 *
 * Hand-written and exact. Where API.md names a field, the name here is that
 * field. Where API.md describes a payload in prose ("run + counts + progress",
 * "list with probe status, task counts, last run"), the shape follows the
 * core's `to_dict()` output (`crb.core.*`) so the server can serialise the
 * dataclasses verbatim. Every such prose-derived field is marked `@contract`
 * with the API.md line it came from, so drift is a diff, not a surprise.
 *
 * Invariants that the types encode on purpose:
 *   - a belt is `true | false | null` (null = not recorded, e.g. legacy v3 rows);
 *   - a capability cell is either measured (numbers + `n`) or `NOT_YET_MEASURED`;
 *     there is no third state and no "empty row";
 *   - `false_q1` is a count that must read 0 — the UI renders it red otherwise.
 *
 * Navigation
 * ----------
 * What it is:   The UI's reading of docs/API.md — every response and request type, the closed
 *               vocabularies (roles, run kinds, belts, routes, oracle bands) and the few pure
 *               helpers on them (`roleAtLeast`, `isRunTerminal`, `beltNamesFor`,
 *               `ladderEntryLabel`, `beltsOf`).
 * What it does: Names each field exactly as the server serialises it (`to_dict()` of the core
 *               dataclass, cited above each interface) so drift is a type error, not a runtime
 *               surprise; encodes the invariants the screens rely on — a belt is
 *               `true | false | null`, a cell is measured or `NOT_YET_MEASURED`, `false_q1` is
 *               a count that must read 0.
 * How:          Hand-written interfaces grouped by API.md section; `@contract` marks a shape
 *               derived from prose rather than a named field.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md
 * Works with:   docs/API.md (the contract this file mirrors), ui/src/api/hooks.ts (types every
 *               hook), src/crb/core/ledger.py (`GradeRow` — the flat belts on a row),
 *               src/crb/core/evidence.py (`EvidencePack`, `ApparatusStamp`, `BuilderRef`),
 *               src/crb/core/spec.py (`RepoConfig`, `TaskSpec`), src/crb/core/routing.py
 *               (`RoutingPolicy`, `RouteDecision`), src/crb/server/schemas.py (the server's
 *               Pydantic side of the same shapes)
 * Tested by:    ui/src/api/types.test.ts (`ladderEntryLabel`), ui/src/components/BeltPills.test.tsx
 *               (`beltNamesFor`), and every screen test through the fixtures it types
 * Touch when:   docs/API.md changes a response (a new field, a new run kind, a fifth belt set)
 *               — change this file first, then the hook and the screen; a new `Runner` or
 *               `Language` value here must match src/crb/core/spec.py; never for a new
 *               repository.
 */

// ---------------------------------------------------------------------------
// Conventions
// ---------------------------------------------------------------------------

/** The error envelope: `{"error": {"code", "message", "detail"}}`. */
export interface ApiErrorEnvelope {
  error: {
    code: string
    message: string
    detail?: Record<string, unknown>
  }
}

/** Reserved codes the UI branches on. */
export const ERROR_FALSE_Q1_REFUSED = 'false_q1_refused'
export const ERROR_SANDBOX_UNAVAILABLE = 'sandbox_unavailable'

/** Pagination: `?limit=&offset=` → `{items, total, limit, offset}`. */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** `?limit=&offset=` (server default 50, max 500). */
export interface PageParams {
  limit?: number
  offset?: number
}

// ---------------------------------------------------------------------------
// Health / metrics / version
// ---------------------------------------------------------------------------

/** A health probe's verdict; `skipped` = not applicable in this deployment (e.g. no docker configured). */
export type ProbeStatus = 'ok' | 'degraded' | 'down' | 'skipped'

/** `crb.observability.probes.ProbeResult.to_dict()`; `data` is per probe — the `migrations` probe's is a {@link MigrationsHeadStatus}. */
export interface Probe {
  name: string
  status: ProbeStatus
  detail: string
  data: Record<string, unknown>
}

/** `crb.store.migrate.HeadStatus.to_dict()` — the `migrations` probe's `data` (a type alias, not an interface: only a type literal is assignable to `Probe.data`'s `Record<string, unknown>`) (docs/API.md#health): where the store stands against the packaged revision chain. */
export type MigrationsHeadStatus = {
  /** The applied Alembic revision (comma-joined when the store reports several heads); `null` = no `alembic_version` row (empty or `create_all` store). */
  database: string | null
  /** The code's single head revision. */
  head: string
  /** True only when `database` IS `head`. */
  at_head: boolean
  /** For an unversioned store with crb tables: the revision its fingerprints correspond to; `null` otherwise. */
  unversioned_at: string | null
  /** Unversioned store whose schema equals the current models at head — `crb migrate` would only stamp it. */
  matches_models: boolean
}

/** The `migrations` probe as served: `Probe` with its `data` typed. */
export interface MigrationsProbe extends Probe {
  name: 'migrations'
  data: MigrationsHeadStatus
}

/** One worker in the `worker` probe's `data.workers[]` (docs/API.md#health): its check-in age against the staleness it promised. */
export interface WorkerProbeWorker {
  worker_id: string
  hostname: string
  executor: string
  kinds: string[]
  started: string | null
  heartbeat: string | null
  /** Seconds since `heartbeat`; `null` when it has never checked in. */
  heartbeat_age_s: number | null
  /** `3 × this worker's own heartbeat_s` — the bound `alive` is judged against. */
  stale_after_s: number
  current_run_id: string | null
  version: string
  stopped: string | null
  alive: boolean
  /** Containers whose `docker kill` the daemon never confirmed and this worker is still reaping (0 on an older server). */
  unconfirmed_containers?: number
}

/**
 * The `worker` probe's `data` (docs/API.md#health). `stale_after_s` here is the RUN threshold
 * (`worker_heartbeat_stale_s`): a running run whose heartbeat is older is listed in `stale`.
 * Each worker's own `stale_after_s` is a different number — `3 × its heartbeat_s`.
 */
export interface WorkerProbeData {
  workers: WorkerProbeWorker[]
  /** Workers alive now. */
  alive: number
  /** Running runs. */
  running: number
  /** Queued runs. */
  queued: number
  /** Ids of running runs whose heartbeat is older than `stale_after_s`. */
  stale: string[]
  stale_after_s: number
  /** Sum over the listed workers of the containers still being reaped; the probe is `degraded` while > 0. Absent on an older server. */
  unconfirmed_containers?: number
}

/** `GET /health` — overall status is the worst probe. */
export interface Health {
  status: ProbeStatus
  probes: Probe[]
}

/** `GET /version` — the package, the apparatus (the instrument's version, ADR-0001) and the routing policy. */
export interface Version {
  crb: string
  apparatus: string
  policy: string
  /** An organisation (OpenID Connect) sign-in is configured; unauthenticated, names nothing. */
  oidc_enabled: boolean
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** The RBAC ladder, ascending (docs/API.md "Conventions"). */
export type Role = 'viewer' | 'operator' | 'approver' | 'admin'

/** Ascending order, so `roleAtLeast` is an index comparison. */
export const ROLE_ORDER: readonly Role[] = ['viewer', 'operator', 'approver', 'admin']

/** `true` when `role` is `min` or higher; `undefined` (not logged in) is never enough. */
export function roleAtLeast(role: Role | undefined, min: Role): boolean {
  if (!role) return false
  return ROLE_ORDER.indexOf(role) >= ROLE_ORDER.indexOf(min)
}

/** `GET /auth/me` — who is logged in; `issuer` names the OIDC provider or the local bootstrap. */
export interface Principal {
  id: string
  display_name: string
  email: string
  role: Role
  issuer: string
}

/** `POST /auth/login` body (the local bootstrap account; OIDC goes through a redirect). */
export interface LoginRequest {
  username: string
  password: string
}

/** `GET /auth/csrf`. */
export interface CsrfToken {
  token: string
}

// ---------------------------------------------------------------------------
// Repos
// ---------------------------------------------------------------------------

/** The languages the miner and runners know (`crb.core.spec`); must match the server's set. */
export type Language = 'python' | 'go' | 'javascript' | 'jvm' | 'rust'
export const LANGUAGES: readonly Language[] = ['python', 'go', 'javascript', 'jvm', 'rust']

/** The test runners (`crb.core.runners`); `''` on a repo = not yet chosen. */
export type Runner = 'pytest' | 'go' | 'node' | 'vitest' | 'jest' | 'mocha' | 'maven' | 'cargo'
export const RUNNERS: readonly Runner[] = ['pytest', 'go', 'node', 'vitest', 'jest', 'mocha', 'maven', 'cargo']

/** Regression-belt scope policy (`crb.core.spec`). A list = explicit runner scopes. */
export type BeltScope = 'TARGET_ONLY' | 'AFFECTED_DIRS' | 'BARE' | string[]

/** The miner's shape caps for one repo (`crb.core.mine`). */
export interface MiningConfig {
  log_n: number
  max_candidates: number
  target_valid: number
  hard_target: number
}

/** `crb.core.spec.RepoConfig.to_dict()` */
export interface RepoConfig {
  name: string
  language: Language
  runner: Runner | ''
  src_prefix: string
  test_prefix: string
  ext: string
  test_mode: 'prefix' | 'suffix'
  test_suffix: string
  belt_scope: BeltScope
  probe: string
  url: string
  layer: string
  runner_opts: Record<string, unknown>
  sandbox_image: string
  mining: MiningConfig
}

/** @contract API.md "Repos: list with probe status, task counts, last run". */
export interface RepoProbe {
  status: ProbeStatus | 'not_probed'
  run_id: string | null
  checked: string | null
  detail: string
}

export interface RepoTaskCounts {
  total: number
  standard: number
  hard: number
  gold_clean: number
  gold_failed: number
  unchecked: number
}

export interface RepoLastRun {
  id: string
  kind: RunKind
  status: RunStatus
  finished: string | null
}

export interface RepoSummary {
  name: string
  language: Language
  runner: Runner | ''
  url: string
  /** Empty for a URL-only registration until the worker's first run clones it (W3-B). */
  clone_path: string
  probe: RepoProbe
  task_counts: RepoTaskCounts
  last_run: RepoLastRun | null
  created: string
  updated: string
  /**
   * `owner/name` (lower-cased) of the GitHub repository the row is linked to through the
   * GitHub App; `null` for a repository registered by URL. The Connect dialog's "link to an
   * existing repository" select lists the rows where this is `null`.
   */
  github_full_name: string | null
}

/** `GET /repos/{name}` — repo + config. */
export interface RepoDetail extends RepoSummary {
  config: RepoConfig
}

/**
 * `POST /repos` body (API.md). One of `clone_path` / `url` is required. A URL-only
 * registration is policy-checked at write (https/ssh only) and cloned by the worker on
 * the repo's first run (`repo.clone.start` / `repo.clone.done` events).
 */
export interface RepoCreateRequest {
  name: string
  language: Language
  clone_path?: string
  url?: string
  runner?: Runner
  src_prefix?: string
  test_prefix?: string
  ext?: string
  test_mode?: 'prefix' | 'suffix'
  test_suffix?: string
  belt_scope?: BeltScope
  probe?: string
  layer?: string
  runner_opts?: Record<string, unknown>
  sandbox_image?: string
  mining?: Partial<MiningConfig>
}

/** `GET /repos/{name}/profile` — the change profile (class × size histogram). */
export interface ProfileCell {
  capability_class: string
  size: string
  count: number
  share: number
}

/** `GET /repos/{name}/profile` — how the repo's real commits distribute over (class × size); the denominator of coverage. */
export interface RepoProfile {
  repo: string
  n_commits: number
  classes: string[]
  sizes: string[]
  cells: ProfileCell[]
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/** What a run does; `probe` is queued from the repo page, the rest from the run dialog. */
export type RunKind = 'mine' | 'replay' | 'blind' | 'oracle' | 'controls' | 'probe' | 'label' | 'factory'
/** The kinds an operator can start from the run dialog (a probe has its own button). */
export const RUN_KINDS: readonly RunKind[] = ['mine', 'replay', 'blind', 'oracle', 'controls']

/** Queue lifecycle; the three in `RUN_TERMINAL` are final. */
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export const RUN_TERMINAL: readonly RunStatus[] = ['succeeded', 'failed', 'cancelled']

/** `true` once a run can no longer change — polling and the SSE stream stop on it. */
export function isRunTerminal(status: RunStatus | undefined): boolean {
  return status !== undefined && RUN_TERMINAL.includes(status)
}

/** `sighted` = the builder saw the target tests; `blind` = it did not (ADR-0004). */
export type GradeMode = 'sighted' | 'blind'

/** `crb.core.run.RunSummary.to_dict()` (live counts while running). */
export interface RunCounts {
  tasks: number
  clean: number
  disqualified: number
  errors: number
  first_pass_clean: number
  rows: number
  /** A non-build kind's own counters, verbatim (a mine run's examined / found /
   *  gold_clean / gold_dirty / skipped / known / pool; an oracle, controls or label
   *  run's raw counts object, which may nest); `{}` for build kinds, absent on an
   *  older server. */
  detail?: Record<string, unknown>
}

/** Tasks done of total, and the task in flight (the run page's progress bar). */
export interface RunProgress {
  done: number
  total: number
  current_task_id: string | null
}

/**
 * Per-attempt caps (`crb.builders.base.Budget`). Every field optional: an absent field keeps
 * the next level's value (rung → run → the builder's defaults 25 turns / 25 tool calls /
 * 0 tokens = no cap / $0 = no cap / 900 s). @contract API.md "POST /runs: budget".
 */
export interface RunBudget {
  max_turns?: number
  max_tool_calls?: number
  max_tokens?: number
  max_cost_usd?: number
  wall_clock_s?: number
}

/**
 * An object rung of a ladder: the identity the ledger row will name plus a budget that
 * overrides the run's for THIS rung only. Nothing else is accepted on a rung.
 * @contract API.md "POST /runs: ladder".
 */
export interface LadderRung {
  builder: string
  model: string
  provider?: string
  budget?: RunBudget
}

/** A ladder entry: a rung label (`r1`, `builder:model[:provider]`) or an object rung. */
export type LadderEntry = string | LadderRung

/** One line for a ladder entry: a label as written; an object rung as `builder:model[@provider] [cap=n …]`. */
export function ladderEntryLabel(entry: LadderEntry): string {
  if (typeof entry === 'string') return entry
  const caps = Object.entries(entry.budget ?? {})
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${v}`)
  return `${entry.builder}:${entry.model}${entry.provider ? `@${entry.provider}` : ''}${caps.length ? ` [${caps.join(' ')}]` : ''}`
}

/**
 * A factory run's delivery switch as the worker read it (`RunOut.factory`): whether
 * delivery was on, who overrode the route gate (id and display name) and the frozen
 * backlog's hash. `null` for every other kind; absent on an older server.
 */
export interface RunFactory {
  deliver: boolean
  deliver_override_by: string | null
  deliver_override_by_name: string | null
  backlog_hash: string | null
}

/** @contract API.md "GET /runs/{id}: run + counts + progress". */
export interface Run {
  id: string
  repo: string
  kind: RunKind
  status: RunStatus
  mode: GradeMode
  builder: string
  model: string
  provider: string
  /** The ladder as declared — labels and/or object rungs (`ladder_json`). */
  ladder: LadderEntry[]
  /** Run-level budget overrides (`params.budget`; `{}` when the defaults apply). */
  budget?: RunBudget
  executor: string
  timeout: number
  pool: string
  limit: number | null
  task_ids: string[]
  /** Constructor overrides applied to every builder on the ladder (`{}` when none). */
  builder_config: Record<string, unknown>
  actor: string
  created: string
  started: string | null
  finished: string | null
  cancel_requested: boolean
  error: string
  cost_usd: number
  apparatus_version: string
  /** The worker that claimed the run and its last heartbeat (`null` until claimed); absent on an older server. */
  worker_id?: string
  heartbeat?: string | null
  /** 1-based place in the FIFO queue while `queued`; `null` once claimed; absent on an older server. */
  queue_position?: number | null
  /** The kinds of the runs ahead in the queue, in order; absent on an older server. */
  queue_kinds_ahead?: string[]
  /** The factory's delivery switch (kind `factory` only, else `null`); absent on an older server. */
  factory?: RunFactory | null
  counts: RunCounts
  progress: RunProgress
}

export interface RunCreateRequest {
  repo: string
  kind: RunKind
  mode?: GradeMode
  builder?: string
  model?: string
  provider?: string
  /**
   * One attempt per rung until clean. A string is a rung label (`r1` = the run's own
   * builder:model, or `builder:model[:provider]`); an object rung carries its own budget —
   * the same model at 25 → 50 → 100 tool calls is a budget ladder.
   */
  ladder?: LadderEntry[]
  /** Run-level caps; only the fields set are sent, a rung's own budget overrides them. */
  budget?: RunBudget
  task_ids?: string[]
  limit?: number
  pool?: string
  executor?: string
  timeout?: number
  /**
   * Builder constructor keyword arguments applied to every rung (e.g.
   * `{"auth": "cli", "effort": "high"}` for `claude_code`). The server refuses
   * `model` / `provider` / `name` (the recorded identity) and credential-shaped keys.
   */
  builder_config?: Record<string, unknown>
  /** factory runs only — delivery is route-gated (ADR-0003 amendment 2026-09-16); `deliver_override` needs approver. */
  /** Per-run raw-retention switches (both default off — ADR-0006). */
  retain?: { worktrees?: boolean; transcripts?: boolean }
  deliver?: boolean
  deliver_override?: boolean
  max_rework?: number
}

/** `GET /runs` filters. */
export interface RunListParams extends PageParams {
  repo?: string
  kind?: RunKind
  status?: RunStatus
}

/**
 * The belts. `null` = not recorded / not evaluated: a legacy v3 row has no belt 4; belt 5
 * (`repo_lint_clean`, ADR-0011) is recorded only under `belt_set = 'v5'` and is `null`
 * there when the repository configures no linter — never a pass, never a fail.
 */
export interface Belts {
  tests_unmodified: boolean | null
  target_green: boolean | null
  no_new_failures: boolean | null
  source_changed: boolean | null
  repo_lint_clean?: boolean | null
}

/** The four core belts every apparatus since 2.0 recorded. */
export const CORE_BELT_NAMES = ['tests_unmodified', 'target_green', 'no_new_failures', 'source_changed'] as const
/** Every belt, in belt order; belt 5 is shown only when the row's belt set records it. */
export const ALL_BELT_NAMES = [...CORE_BELT_NAMES, 'repo_lint_clean'] as const
/** @deprecated use CORE_BELT_NAMES / beltNamesFor — kept as the four-belt alias. */
export const BELT_NAMES = CORE_BELT_NAMES
export type BeltName = (typeof ALL_BELT_NAMES)[number]
export type BeltSet = 'v5' | 'v4' | 'v3-legacy'
export const BELT_SET_V5: BeltSet = 'v5'

/**
 * Which belts a row shows: five under `v5`, four otherwise. With no belt set (a
 * `GradeResult` inside an evidence pack) the presence of the `repo_lint_clean` key
 * says whether the apparatus that wrote it had belt 5. A missing belt is never
 * rendered — and never rendered as failed.
 */
export function beltNamesFor(beltSet: string | null | undefined, belts?: Belts): readonly BeltName[] {
  if (beltSet) return beltSet === BELT_SET_V5 ? ALL_BELT_NAMES : CORE_BELT_NAMES
  return belts && 'repo_lint_clean' in belts ? ALL_BELT_NAMES : CORE_BELT_NAMES
}

/** @contract API.md "GET /runs/{id}/tasks: task, trials, clean, belts, cost, latency, pack hashes". */
export interface RunTaskRow {
  task_id: string
  capability_class: string
  size: string
  pool: string
  trials: number
  clean: boolean
  disqualified: boolean
  error: string
  /** The decisive attempt's belt set (`v5` = five belts, else four). */
  belt_set?: BeltSet | string
  belts: Belts
  cost_usd: number
  latency_s: number
  pack_hashes: string[]
  row_ids: string[]
  /** The decisive attempt's `labels.budget_tier` (`<tool calls>/<turns>/<wall clock s>`; `""` before the label). */
  budget_tier?: string
  /** One tier per attempt, aligned with `row_ids` — a blind rate quoted without its tier is not a claim. */
  budget_tiers?: string[]
}

// ---------------------------------------------------------------------------
// Step events (SSE) — crb.observability.events.StepEvent.to_dict()
// ---------------------------------------------------------------------------

/** Where in the pipeline a StepEvent was emitted (`crb.observability.events`). */
export type Stage = 'mine' | 'prep' | 'build' | 'grade' | 'ledger' | 'oracle' | 'factory' | 'system'
/** The event's own verdict; `error` / `invalid` are rendered red in the live log. */
export type StepStatus = 'ok' | 'error' | 'invalid' | 'skipped' | 'in_progress'

/** `crb.observability.events.StepEvent.to_dict()` — one line of the live log / audit trail. */
export interface StepEvent {
  event_id: string
  seq: number
  timestamp: string
  trace_id: string
  step_id: string
  parent_step_id: string
  stage: Stage
  action: string
  status: StepStatus
  actor: string
  repo: string
  task_id: string
  input_ref: string
  output_ref: string
  error_code: string
  error_message: string
  duration_ms: number | null
  cost_usd: number | null
  payload: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Tasks / grades / evidence
// ---------------------------------------------------------------------------

/** `crb.core.spec.TaskSpec.to_dict()` */
export interface TaskSpec {
  task_id: string
  repo: string
  subject: string
  authored: string
  test_files: string[]
  src_files: string[]
  target_tests: string[]
  belt_scope: string[]
  pool: 'standard' | 'hard'
  src_churn: number
  size: string
  capability_class: string
  language: string
  baseline_failing: string[]
  red_checked: boolean
  gold_clean: boolean | null
  gold_note: string
  labels: Record<string, string>
}

/** `crb.core.ledger.GradeRow.to_dict()` — belts are flat on the row. */
export interface GradeRow extends Belts {
  repo: string
  task_id: string
  clean: boolean
  capability_class: string
  size: string
  language: string
  pool: string
  mode: GradeMode
  process_step: string
  builder: string
  model: string
  provider: string
  run_id: string
  trial: string
  actor: string
  created: string
  disqualified: boolean
  dq_reason: string
  error: string
  new_failures_count: number
  attempts: number
  cost_usd: number
  tokens_in: number
  tokens_out: number
  latency_s: number
  oracle_strength: number | null
  gold_clean: boolean | null
  evidence_pack_hash: string
  apparatus_version: string
  belt_set: BeltSet
  provenance: string
  labels: Record<string, string>
  schema: string
  row_id: string
  prev_hash: string
  row_hash: string
}

/** The belts of a flat `GradeRow` as a `Belts` object (for `BeltPills`); belt 5 defaults to `null` = not recorded. */
export function beltsOf(row: Belts): Belts {
  return {
    tests_unmodified: row.tests_unmodified,
    target_green: row.target_green,
    no_new_failures: row.no_new_failures,
    source_changed: row.source_changed,
    repo_lint_clean: row.repo_lint_clean ?? null,
  }
}

/** `crb.core.lint.LintStep.to_dict()` — one linter command as it ran (tail redacted). */
export interface LintStep {
  tool: string
  argv: string[]
  files: string[]
  rc: number
  verdict: boolean | null
  tail: string
  timed_out: boolean
  duration_s: number
  error: string
}

/** `crb.core.lint.LintRun.to_dict()` — belt 5's record: which linter, what it said. */
export interface LintRun {
  detected: string
  steps: LintStep[]
  ok: boolean | null
  note: string
  error: string
  duration_s: number
}

/** `GET /tasks/{repo}/{task_id}` — spec + all grade rows for it. */
export interface TaskDetail {
  spec: TaskSpec
  grades: GradeRow[]
}

/** `GET /grades` filters (the ledger screen's). */
export interface GradeListParams extends PageParams {
  repo?: string
  run_id?: string
  task_id?: string
  clean?: boolean
  mode?: GradeMode
  builder?: string
  model?: string
  capability_class?: string
  size?: string
  language?: string
}

/** `crb.core.runners.base.TestRun.to_dict()` — `tail` is redacted server-side. */
export interface TestRun {
  returncode: number
  failing: string[]
  tail: string
  timed_out: boolean
  duration_s: number
  parse_error: string
}

/** `crb.core.workspace.DiffStats.to_dict()` — hash + counts, never the raw diff. */
export interface DiffStats {
  files: string[]
  additions: number
  deletions: number
  diff_sha256: string
}

/** `crb.core.grade.GradeResult.to_dict()` */
export interface GradeResult extends Belts {
  task_id: string
  repo: string
  mode: GradeMode
  clean: boolean
  disqualified: boolean
  dq_reason: string
  error: string
  note: string
  new_failures: string[]
  tamper_files: string[]
  changed_files: string[]
  diff: DiffStats | null
  target_run: TestRun | null
  belt_run: TestRun | null
  /** Absent on packs written before apparatus 2.2; `null` when belt 5 was not evaluated. */
  lint_run?: LintRun | null
  duration_s: number
  extra: Record<string, unknown>
}

/** `crb.core.evidence.ApparatusStamp.to_dict()` */
export interface ApparatusStamp {
  apparatus_version: string
  crb_version: string
  grader: string
  runner: string
  executor: Record<string, unknown>
  corpus_sha: string
  policy_version: string
  extra: Record<string, unknown>
}

/** `crb.core.evidence.BuilderRef.to_dict()` */
export interface BuilderRef {
  name: string
  model: string
  provider: string
  mode: GradeMode
  attempts: number
  turns: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
  latency_s: number
  transcript_ref: string
  budget: Record<string, unknown>
  note: string
}

/** `crb.core.evidence.EvidencePack.to_dict()` */
export interface EvidencePack {
  schema: string
  task: TaskSpec
  grade: GradeResult
  apparatus: ApparatusStamp
  builder: BuilderRef | null
  run_id: string
  trial: string
  actor: string
  created: string
  notes: Record<string, unknown>
  pack_hash: string
}

/** `GET /evidence/{pack_hash}` — the pack (redacted) + `verified`. */
export interface EvidenceResponse {
  pack: EvidencePack
  verified: boolean
}

// ---------------------------------------------------------------------------
// Capability, routing, forecast, sign-off
// ---------------------------------------------------------------------------

/** The five routes the ONE routing rule can return (ADR-0003); `deliver` is the only one that licenses autonomy. */
export type Route = 'deliver' | 'calibrate' | 'granularize' | 'human' | 'do_not_ship'
/** Display order on the routing screen. */
export const ROUTES: readonly Route[] = ['deliver', 'calibrate', 'granularize', 'human', 'do_not_ship']

/** What the UI renders for a cell absent from the map — never a zero-filled row. */
export const NOT_YET_MEASURED = 'NOT_YET_MEASURED'
/** A cell's route, or `NOT_YET_MEASURED` when it has no rows. */
export type CellVerdict = Route | typeof NOT_YET_MEASURED

/** How far a cell's evidence has been checked by a person; a sign-off lifts the tier, never the route. */
export type VerificationTier = 'automated-pass' | 'human-verified' | 'ab-confirmed' | 'untrusted' | ''

/** Cell-key projection fields (`crb.core.ledger.CELL_FIELDS`). */
export type CellField =
  | 'process_step'
  | 'capability_class'
  | 'size'
  | 'language'
  | 'builder'
  | 'model'
  | 'provider'

/** One cell of `GET /capability-map` (API.md lists these fields). */
export interface CapabilityCell {
  capability_class: string
  size: string
  language?: string
  model?: string
  provider?: string
  builder?: string
  n: number
  /** Distinct tasks behind `n` (attempts): 16 rows on 4 commits is a statement about 4 commits. */
  n_tasks?: number
  clean: number
  point: number
  ci_low: number
  ci_high: number
  false_q1: number
  cost_usd_mean: number
  latency_s_mean: number
  oracle_strength_mean: number | null
  route: CellVerdict
  reason: string
  /** The rule's stable reason code (`deliver`, `n_below_min`, `oracle_weak`, `controls_failed`, …). */
  reason_code?: string
  verification_tier: VerificationTier
  apparatus_versions: string[]
  belt_set?: string
  /** Every belt set behind `n` (`v4`, `v5`…) — with `apparatus_versions`, the provenance a rate keeps. */
  belt_sets?: string[]
}

/** Headline numbers of one map; `false_q1_total` must read 0. */
export interface CapabilitySummary {
  trusted_autonomy_coverage: number
  total_cells: number
  measured_cells: number
  deliver_cells: number
  n_total: number
  false_q1_total: number
  apparatus_versions: string[]
}

/** `GET /capability-map` — only MEASURED cells are listed; absence is `NOT_YET_MEASURED`. */
export interface CapabilityMap {
  repo: string
  by: CellField[]
  classes: string[]
  sizes: string[]
  languages: string[]
  models: string[]
  cells: CapabilityCell[]
  summary: CapabilitySummary
  policy: RoutingPolicy
}

/** `crb.core.routing.RoutingPolicy.to_dict()` */
export interface RoutingPolicy {
  min_n: number
  min_point: number
  min_ci_low: number
  min_oracle_strength: number
  granularize_sizes: string[]
  version: string
}

/** `crb.core.routing.RouteDecision.to_dict()` */
export interface RouteDecision {
  route: Route
  reason: string
  reason_code?: string
  cell: Record<string, string>
  n: number
  point: number
  ci_low: number
  /** The upper Wilson bound — served so the UI never mirrors an asymmetric interval. */
  ci_high: number
  false_q1: number
  oracle_strength: number | null
  policy_version: string
  /** The bar as numbers beside its name (ADR-0003 amendment 2026-09-16). */
  policy_thresholds?: Record<string, unknown>
  verification_tier: string
  apparatus_versions: string[]
  /** The belt sets behind `n` (`v4`, `v5`…) — provenance every rendered rate keeps. */
  belt_sets: string[]
}

/** `GET /routes?repo=` — one decision per cell. */
export interface RoutesResponse {
  repo: string
  policy: RoutingPolicy
  decisions: RouteDecision[]
}

/** One `class:size:count` term of a forecast mix. */
export interface ForecastMixItem {
  capability_class: string
  size: string
  count: number
}

/** `GET /forecast/build` (API.md). */
export interface ForecastBuild {
  repo: string
  mix: ForecastMixItem[]
  cost_usd_mean: number
  cost_usd_std: number
  minutes: number
  deliver: number
  human: number
  calibrate: number
  buildable_p: number
  unmeasured: string[]
}

/** `GET /forecast/readiness` — ok + gaps punch-list. */
export interface ForecastReadiness {
  repo: string
  ok: boolean
  gaps: string[]
}

/** `GET /signoffs` item — an attestation with the evidence snapshot stamped at write time. */
export interface Signoff {
  id: string
  repo: string
  cell: Record<string, string>
  note: string
  /** The stable user id the hash chain covers. Show `approverName(s)`, not this. */
  approver: string
  /** Resolved from the users table at read; empty when the account is gone. */
  approver_name?: string
  /** The kind of account that signed (F34, hash-covered): `oidc` | `local` | `service` (reserved — a delegated signature, never a person's); `""` on a row written before the field existed. */
  verifier_kind?: '' | 'oidc' | 'local' | 'service'
  created: string
  revoked: boolean
  /** Live: not revoked, not superseded, the cell still false-Q1-free and the apparatus unchanged. */
  active: boolean
  /** Made on an earlier apparatus than the one the deployment reads at now (ADR-0015): kept, verifying, lifting nothing until re-signed or revoked. */
  stale: boolean
  /** The deployment's current apparatus, for comparison with `evidence.apparatus_versions`. */
  apparatus_current: string
  revoked_by: string | null
  revoked_by_name?: string | null
  revoked_at: string | null
  /** The snapshot stamped at signing (hash-covered): what the approver saw, not the cell now. */
  evidence: {
    n: number
    point: number
    ci_low: number
    ci_high: number
    false_q1: number
    apparatus_versions: string[]
  }
}

/**
 * Does a sign-off's scope cover a cell, the way the server's `key_matches` reads it: a `*`
 * on the sign-off matches anything; a concrete value must equal the cell's value, and a cell
 * that aggregates a dimension (`*`, or the key absent) is NOT covered by a sign-off narrower
 * on that dimension.
 */
export function signoffScopeMatches(scope: Record<string, string>, cell: Record<string, string | undefined>): boolean {
  return Object.entries(scope).every(([key, want]) => {
    if (want === '*' || want === undefined || want === '') return true
    const have = cell[key] ?? '*'
    return have === want
  })
}

/** Who signed, as a person reads it: the resolved name, else the id the ledger holds. */
export function approverName(s: Pick<Signoff, 'approver' | 'approver_name'>): string {
  return s.approver_name || s.approver
}

/** `POST /signoffs` body (the older shape; the Sign-off screen's fuller request lives in ui/src/screens/Signoff/contract.ts). */
export interface SignoffCreateRequest {
  repo: string
  cell: Record<string, string>
  note: string
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

/** `GET /ledger/verify` — chain walk result; `broken_at` is the first bad seq. */
export interface LedgerVerify {
  rows: number
  ok: boolean
  false_q1_total: number
  broken_at?: number | null
}

/** `GET /ledger/export?format=`. */
export type ExportFormat = 'jsonl' | 'csv'

// ---------------------------------------------------------------------------
// Oracle adequacy
// ---------------------------------------------------------------------------

/** Mutation-strength band per the adequacy policy; `unscoreable` oracles are never averaged in. */
export type OracleBand = 'strong' | 'adequate' | 'weak' | 'unscoreable'
/** What a CLEAN grade on that oracle licenses. */
export type OracleGate = 'auto_ship' | 'human_review' | 'needs_human'

/** `crb.core.oracle.adequacy.AdequacyPolicy.to_dict()` */
export interface AdequacyPolicy {
  autoship_floor: number
  adequate_floor: number
  version: string
}

/** One task's latest mutation score (`GET /oracle/{repo}`). */
export interface OracleTask {
  task_id: string
  capability_class: string
  size: string
  strength: number | null
  band: OracleBand
  mutants: number
  killed: number
  gate: OracleGate
}

/** The per-cell reduction of task scores. */
export interface OracleCell {
  capability_class: string
  size: string
  n: number
  strength_mean: number | null
  band: OracleBand
  gate: OracleGate
}

/** `GET /oracle/{repo}`. */
export interface OracleReport {
  repo: string
  policy: AdequacyPolicy
  tasks: OracleTask[]
  cells: OracleCell[]
  apparatus_versions: string[]
}

/** The seven negative controls (ADR-0010) — each is a known-bad patch the grader must refuse. */
export type ControlName =
  | 'gold'
  | 'noop'
  | 'test_tamper'
  | 'stub'
  | 'regression'
  | 'hardcode_cheat'
  | 'env_poison'
/** `VIOLATION` = the instrument passed a control it must refuse (a bug in the grader); `ESCAPE` = the repo's own tests could not tell (a weak oracle, not an instrument bug). */
export type ControlVerdict = 'ok' | 'VIOLATION' | 'ESCAPE' | 'not_constructible' | 'skip'

/** `crb.core.oracle.controls.ControlRow.to_dict()` (grade omitted from the list view). */
export interface ControlRow {
  task_id: string
  repo: string
  control: ControlName
  expected: string
  observed: string
  verdict: ControlVerdict
  note: string
  duration_s: number
}

/** `crb.core.oracle.controls.ControlsReport.to_dict()` */
export interface ControlsReport {
  schema: string
  apparatus: Record<string, unknown>
  n_tasks: number
  n_rows: number
  violations: number
  escapes: number
  not_constructible: number
  skipped: number
  passed: boolean
  escape_rows: ControlRow[]
  rows: ControlRow[]
  /** When the report came from a run (the server sets both); absent on a bare `to_dict`. */
  run_id?: string
  reported_at?: string
  /**
   * The routing-reduced verdict of THIS report — the same reduction `/capability-map` and
   * `/routes` gate on (`state`: passed | failed | thin | escaped | unmeasured). The gate
   * renders this, never a verdict it derives from the counts (CodeRabbit on PR #6).
   */
  verdict?: {
    measured: boolean
    passed: boolean
    complete: boolean
    constructible: number
    total: number
    share: number
    escapes: number
    run_id: string
    created: string
    state: 'passed' | 'failed' | 'thin' | 'escaped' | 'unmeasured'
  }
}

// ---------------------------------------------------------------------------
// Factory — `src/crb/server/routes/factory.py` (`FactoryBacklogOut`, `FactoryTaskOut`)
// ---------------------------------------------------------------------------

/** One frozen backlog item (`BacklogItemOut`). */
export interface FactoryBacklogItem {
  id: string
  title: string
  kind: string
  capability_class: string
  size: string
  level: string
  depends_on: string[]
  structural_facts: string[]
  has_authored_test: boolean
  /** What and why, as the operator wrote it (J-FAC-15: a revised backlog starts from it). */
  description: string
}

/**
 * J-FAC-3 — whether a factory run could open a pull request for this repository, by the
 * worker's own credentials rule, answered from the record BEFORE any build is paid for.
 * `reason` is the sentence to show (with the next step) when it cannot.
 */
export interface FactoryDeliveryPreflight {
  can_deliver: boolean
  reason_code: 'ok' | 'not_linked' | 'app_not_configured' | 'host_mismatch' | 'installation_missing' | 'installation_suspended' | 'read_only'
  reason: string
  full_name: string
  default_branch: string
  installation_id: number | null
  account_login: string
}

/** `GET /factory/{repo}/backlog` — the ACTIVE frozen backlog; 404 `not_found` when none is registered. */
export interface FactoryBacklog {
  repo: string
  hash: string
  frozen_at: string | null
  items: FactoryBacklogItem[]
  /**
   * The delivery pre-flight (J-FAC-3). The current server always sends it; an API older
   * than J-FAC-3 does not, and `FactoryPage` then says so (delivery off, "update the API")
   * rather than guess — the field is optional so that fallback stays type-checked.
   */
  delivery?: FactoryDeliveryPreflight
}

/** J-FAC-4 — why the loop stopped an item, as recorded on the chain; `step` names where. */
export interface FactoryRefusal {
  /** `review` = the rule-3 stop (DL-045): routed human AFTER a verdict, never a readiness refusal. */
  step: 'readiness' | 'red' | 'delivery' | 'review' | 'dependency'
  reason: string
  reason_code: string
  measured_route: string
}

/** `GET /factory/{repo}/tasks` — a bare list (not a `Page`): the latest state of every active item, folded from the evidence chain. */
export interface FactoryTask {
  id: string
  title: string
  capability_class: string
  size: string
  kind: string
  status: string
  /** Why a governed stop stopped (the chain's `item.outcome.error`): `not_red`'s refusal,
   * `delivery_failed`'s error, `oracle_needs_strengthening`'s finding and way forward
   * (DL-045 rule 3); `''` when accepted or not yet run. */
  outcome_reason: string
  /** The unsigned STRUCTURAL slots: what blocks the build and what an approver can sign. */
  dor_gaps: string[]
  /** The open VALUE slots: they route the item test-first and are never signable
   * (optional so a mock built before the field still types; the server always sends it). */
  value_gaps?: string[]
  route_hint: string
  red_proof: boolean | null
  build_status: string
  pr_url: string | null
  review_verdict: string | null
  last_event: string
  /** The newest refusal since the item's last readiness pass; `null` = not refused. (The
   * server always sends these five; optional so a mock built before J-FAC-4 still types.) */
  refusal?: FactoryRefusal | null
  /** The outcome's error (a harness failure, a refused push); `''` when none. */
  error?: string
  /** F15 — the newest build's ledger task (the oracle commit), run, pack and row; `''` before a build. */
  task_id?: string
  run_id?: string
  pack_hash?: string
  row_hash?: string
  /** F28 — the capability map's route for the item's (class × size) cell, from the same
   * signed map the delivery gate reads; `route: ''` = nobody has measured the cell. */
  cell_route: { route: string; reason_code: string; reason: string; n: number; point: number; ci_low: number; ci_high: number; apparatus_versions: string[]; deliverable: boolean }
}

/** `GET /factory/catalogue` — what a backlog item may be made of (F24: the freeze form asks these). */
export interface FactoryCatalogue {
  classes: Array<{ capability_class: string; slots: Array<{ name: string; question: string; kind: 'structural' | 'value' }> }>
  sizes: string[]
  kinds: string[]
  levels: string[]
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

/** `GET /users` item (admin). */
export interface User {
  id: string
  /** What a local account types at login; an OIDC account's provider subject. */
  username: string
  /** The namespaced identity (`local:<name>` or the OIDC `sub`). */
  subject?: string
  display_name: string
  email: string
  role: Role
  issuer: string
  /** Served by every current API; a deactivated account cannot sign in (F23). */
  active: boolean
  created: string
  /** ISO time of the last successful sign-in; empty before the first (UserOut serves a string). */
  last_login: string
}

/** `POST /users` body — a local account; the password never comes back. */
export interface UserCreateRequest {
  username: string
  display_name: string
  email: string
  role: Role
  password: string
}

/** Whether a builder's credential is present — never its value. */
export interface BuilderConfigured {
  name: string
  configured: boolean
}

/** `GET /settings` — non-secret settings only. */
export interface Settings {
  builders: BuilderConfigured[]
  /** The TEST executor (`raw.sandbox.executor`): `docker` (sealed) or `local`. */
  sandbox_mode: string
  retention: Record<string, unknown>
  oidc_enabled: boolean
  ledger_backend: string
  apparatus_version: string
  policy_version: string
  /** The full redacted settings; only the parts a screen reads are typed here. */
  raw?: {
    /** The BUILDER posture (`BuilderSettings.redacted()`): where the model-driven builder runs. */
    builder?: { executor: string; image?: string; egress_network?: string; allow_hosts?: string[] }
    sandbox?: { executor: string; image?: string }
  }
}

// ---------------------------------------------------------------------------
// GitHub App — `src/crb/server/routes/github.py` (the enterprise connection, ADR-0014)
// ---------------------------------------------------------------------------

/** One installation of the deployment's GitHub App (`InstallationOut`). */
export interface GitHubInstallation {
  id: number
  account_login: string
  account_type: string
  repository_selection: string
  html_url: string
  suspended: boolean
  permissions: Record<string, string>
  /** `contents: write` + `pull_requests: write` — what factory delivery needs. */
  can_deliver: boolean
  recorded_by: string
  updated: string
}

/** `GET /github/app` — never 404s: `configured: false` is a state the Connect screen renders. */
export interface GitHubAppInfo {
  configured: boolean
  app_slug: string
  install_url: string
  api_url: string
  installations: GitHubInstallation[]
}

/** One repository an installation may see, with what the connect form pre-fills (`PickerRepoOut`). */
export interface GitHubPickerRepo {
  full_name: string
  name: string
  html_url: string
  clone_url: string
  default_branch: string
  private: boolean
  language: string
  archived: boolean
  suggested: { name: string; language: string; runner: string }
  connected_as: string | null
}

export interface GitHubPickerPage {
  items: GitHubPickerRepo[]
  total: number
  page: number
  per_page: number
  has_more: boolean
}

/** `POST /github/installations/{id}/connect` (`ConnectRequest`). */
export interface GitHubConnectRequest {
  full_name: string
  name?: string
  language?: string
  runner?: string
  src_prefix?: string
  test_prefix?: string
  ext?: string
  test_mode?: 'prefix' | 'suffix'
  test_suffix?: string
  belt_scope?: string | string[]
}

