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

export interface PageParams {
  limit?: number
  offset?: number
}

// ---------------------------------------------------------------------------
// Health / metrics / version
// ---------------------------------------------------------------------------

export type ProbeStatus = 'ok' | 'degraded' | 'down'

/** `crb.observability.probes.ProbeResult.to_dict()` */
export interface Probe {
  name: string
  status: ProbeStatus
  detail: string
  data: Record<string, unknown>
}

export interface Health {
  status: ProbeStatus
  probes: Probe[]
}

export interface Version {
  crb: string
  apparatus: string
  policy: string
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export type Role = 'viewer' | 'operator' | 'approver' | 'admin'

export const ROLE_ORDER: readonly Role[] = ['viewer', 'operator', 'approver', 'admin']

export function roleAtLeast(role: Role | undefined, min: Role): boolean {
  if (!role) return false
  return ROLE_ORDER.indexOf(role) >= ROLE_ORDER.indexOf(min)
}

export interface Principal {
  id: string
  display_name: string
  email: string
  role: Role
  issuer: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface CsrfToken {
  token: string
}

// ---------------------------------------------------------------------------
// Repos
// ---------------------------------------------------------------------------

export type Language = 'python' | 'go' | 'javascript' | 'jvm' | 'rust'
export const LANGUAGES: readonly Language[] = ['python', 'go', 'javascript', 'jvm', 'rust']

export type Runner = 'pytest' | 'go' | 'node' | 'vitest' | 'jest' | 'mocha' | 'maven' | 'cargo'
export const RUNNERS: readonly Runner[] = ['pytest', 'go', 'node', 'vitest', 'jest', 'mocha', 'maven', 'cargo']

/** Regression-belt scope policy (`crb.core.spec`). A list = explicit runner scopes. */
export type BeltScope = 'TARGET_ONLY' | 'AFFECTED_DIRS' | 'BARE' | string[]

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

export type RunKind = 'mine' | 'replay' | 'blind' | 'oracle' | 'controls' | 'probe'
export const RUN_KINDS: readonly RunKind[] = ['mine', 'replay', 'blind', 'oracle', 'controls']

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export const RUN_TERMINAL: readonly RunStatus[] = ['succeeded', 'failed', 'cancelled']

export function isRunTerminal(status: RunStatus | undefined): boolean {
  return status !== undefined && RUN_TERMINAL.includes(status)
}

export type GradeMode = 'sighted' | 'blind'

/** `crb.core.run.RunSummary.to_dict()` (live counts while running). */
export interface RunCounts {
  tasks: number
  clean: number
  disqualified: number
  errors: number
  first_pass_clean: number
  rows: number
}

export interface RunProgress {
  done: number
  total: number
  current_task_id: string | null
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
  ladder: string[]
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
  ladder?: string[]
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
}

export interface RunListParams extends PageParams {
  repo?: string
  kind?: RunKind
  status?: RunStatus
}

/** The four belts. `null` = not recorded (legacy v3 rows have no belt 4). */
export interface Belts {
  tests_unmodified: boolean | null
  target_green: boolean | null
  no_new_failures: boolean | null
  source_changed: boolean | null
}

export const BELT_NAMES = ['tests_unmodified', 'target_green', 'no_new_failures', 'source_changed'] as const
export type BeltName = (typeof BELT_NAMES)[number]

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
  belts: Belts
  cost_usd: number
  latency_s: number
  pack_hashes: string[]
  row_ids: string[]
}

// ---------------------------------------------------------------------------
// Step events (SSE) — crb.observability.events.StepEvent.to_dict()
// ---------------------------------------------------------------------------

export type Stage = 'mine' | 'prep' | 'build' | 'grade' | 'ledger' | 'oracle' | 'factory' | 'system'
export type StepStatus = 'ok' | 'error' | 'invalid' | 'skipped' | 'in_progress'

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
  belt_set: 'v4' | 'v3-legacy'
  provenance: string
  labels: Record<string, string>
  schema: string
  row_id: string
  prev_hash: string
  row_hash: string
}

export function beltsOf(row: Belts): Belts {
  return {
    tests_unmodified: row.tests_unmodified,
    target_green: row.target_green,
    no_new_failures: row.no_new_failures,
    source_changed: row.source_changed,
  }
}

/** `GET /tasks/{repo}/{task_id}` — spec + all grade rows for it. */
export interface TaskDetail {
  spec: TaskSpec
  grades: GradeRow[]
}

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

export type Route = 'deliver' | 'calibrate' | 'granularize' | 'human' | 'do_not_ship'
export const ROUTES: readonly Route[] = ['deliver', 'calibrate', 'granularize', 'human', 'do_not_ship']

export const NOT_YET_MEASURED = 'NOT_YET_MEASURED'
export type CellVerdict = Route | typeof NOT_YET_MEASURED

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
  verification_tier: VerificationTier
  apparatus_versions: string[]
  belt_set?: string
}

export interface CapabilitySummary {
  trusted_autonomy_coverage: number
  total_cells: number
  measured_cells: number
  deliver_cells: number
  n_total: number
  false_q1_total: number
  apparatus_versions: string[]
}

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
  cell: Record<string, string>
  n: number
  point: number
  ci_low: number
  false_q1: number
  oracle_strength: number | null
  policy_version: string
}

export interface RoutesResponse {
  repo: string
  policy: RoutingPolicy
  decisions: RouteDecision[]
}

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

export interface Signoff {
  id: string
  repo: string
  cell: Record<string, string>
  note: string
  approver: string
  created: string
  revoked: boolean
  revoked_by: string | null
  revoked_at: string | null
  evidence: {
    n: number
    point: number
    ci_low: number
    false_q1: number
    apparatus_versions: string[]
  }
}

export interface SignoffCreateRequest {
  repo: string
  cell: Record<string, string>
  note: string
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

export interface LedgerVerify {
  rows: number
  ok: boolean
  false_q1_total: number
  broken_at?: number | null
}

export type ExportFormat = 'jsonl' | 'csv'

// ---------------------------------------------------------------------------
// Oracle adequacy
// ---------------------------------------------------------------------------

export type OracleBand = 'strong' | 'adequate' | 'weak' | 'unscoreable'
export type OracleGate = 'auto_ship' | 'human_review' | 'needs_human'

/** `crb.core.oracle.adequacy.AdequacyPolicy.to_dict()` */
export interface AdequacyPolicy {
  autoship_floor: number
  adequate_floor: number
  version: string
}

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

export interface OracleCell {
  capability_class: string
  size: string
  n: number
  strength_mean: number | null
  band: OracleBand
  gate: OracleGate
}

export interface OracleReport {
  repo: string
  policy: AdequacyPolicy
  tasks: OracleTask[]
  cells: OracleCell[]
  apparatus_versions: string[]
}

export type ControlName =
  | 'gold'
  | 'noop'
  | 'test_tamper'
  | 'stub'
  | 'regression'
  | 'hardcode_cheat'
  | 'env_poison'
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
}

// ---------------------------------------------------------------------------
// Factory (phase P6) — shapes are provisional; the UI only renders lists.
// ---------------------------------------------------------------------------

export interface FactoryBacklog {
  repo: string
  hash: string
  frozen_at: string | null
  items: Array<{ id: string; title: string; capability_class: string; size: string }>
}

export interface FactoryTask {
  id: string
  title: string
  dor_gaps: string[]
  red_proof: boolean | null
  build_status: string
  pr_url: string | null
  review_verdict: string | null
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export interface User {
  id: string
  username: string
  display_name: string
  email: string
  role: Role
  issuer: string
  created: string
}

export interface UserCreateRequest {
  username: string
  display_name: string
  email: string
  role: Role
  password: string
}

export interface BuilderConfigured {
  name: string
  configured: boolean
}

/** `GET /settings` — non-secret settings only. */
export interface Settings {
  builders: BuilderConfigured[]
  sandbox_mode: string
  retention: Record<string, unknown>
  oidc_enabled: boolean
  ledger_backend: string
  apparatus_version: string
  policy_version: string
}
