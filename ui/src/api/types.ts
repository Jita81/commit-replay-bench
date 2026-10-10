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
 * Touch when:   never for a new repository; docs/API.md changes a response (a new field, a new run
 *               kind, a fifth belt set) — change this file first, then the hook and the screen; a
 *               new `Runner` or `Language` value here must match src/crb/core/spec.py.
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
  /** The schema was compared with the current models and equals them — a store at head (versioned or not); `false` when a difference was found or nothing at head was compared (pilot D7). */
  matches_models: boolean
  /** Up to five differences the comparison found, as `<op> <names>` (`remove_index ix_runs_status`); `[]` when it matched or was not compared. */
  drift?: string[]
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
  /** What this worker's metrics listener did at start (pilot D5): `listening` on `addr:port` (the port `auto` chose included), `off` by choice, or `degraded` with the reason; `null` when it recorded nothing. */
  metrics?: { state: 'listening' | 'off' | 'degraded'; addr: string; port: number; requested: string; reason: string } | null
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

/**
 * Where tests and the builder run, as the API reads the deployment's environment (ADR-0023):
 * production refuses an unsealed posture unless `CRB_ALLOW_UNSEALED_PROD=1`, and then says so.
 */
export interface DeploymentPosture {
  env: 'dev' | 'prod'
  /** `docker` (sealed) or `local`. */
  sandbox_executor: string
  /** `docker` (sealed) or `host`. */
  builder_executor: string
  sealed: boolean
  /** Production running unsealed under `CRB_ALLOW_UNSEALED_PROD=1`; every run's apparatus carries it. */
  unsealed_prod_override: boolean
  /**
   * The factory's own posture: a factory build hands the builder a host worktree, never a
   * container. `refused` in prod without the override (the worker refuses the run); `host`
   * otherwise (in prod every factory run's apparatus then carries the override). Absent on an
   * older server.
   */
  factory_builds?: 'refused' | 'host'
}

/** `GET /health` — overall status is the worst probe. */
export interface Health {
  status: ProbeStatus
  probes: Probe[]
  /** The deployment's posture (ADR-0023). Absent on an older server. */
  posture?: DeploymentPosture
}

/** `GET /version` — the package, the apparatus (the instrument's version, ADR-0001) and the routing policy. */
export interface Version {
  crb: string
  apparatus: string
  policy: string
  /** An organisation (OpenID Connect) sign-in is configured; unauthenticated, names nothing. */
  oidc_enabled: boolean
  /** The belt set grade rows are written under now (G-212: read, never stated by the page). */
  belt_set?: string
  /** The sign-off policy the write boundary enforces now. */
  signoff_policy?: string
  /** The package's licence (pyproject.toml's `license`). */
  licence?: string
}

// ---------------------------------------------------------------------------
// Go-live (docs/DEPLOYMENT.md §8, ADR-0031)
// ---------------------------------------------------------------------------

/** Who recorded an operator act, the day it was done, when it was recorded, and what was done. */
export interface Attestation {
  by: string
  actor: string
  performed_on: string
  recorded_at: string
  statement: string
}

/** Who can make a go-live line true: the product by its own check, or the operator by an act. */
export type GoLiveProves = 'product' | 'operator'
/** proven — the product's check passed now; attested — an admin's record is in force; unproven — neither. */
export type GoLiveState = 'proven' | 'attested' | 'unproven'

export interface GoLiveLine {
  id: string
  title: string
  proves: GoLiveProves
  /** Where the state comes from, in words. */
  source: string
  /** The guide anchor, `DEPLOYMENT#8-go-live-checklist` style. */
  doc: string
  state: GoLiveState
  /** Why the line reads as it does: what passed, what failed, or who recorded it. */
  detail: string
  attestation: Attestation | null
}

/** `GET /golive`. */
export interface GoLive {
  lines: GoLiveLine[]
  counts: { lines: number; proven: number; attested: number; unproven: number }
  checked_at: string
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
  /** Chain the £0 stages (DL-315): present, and true, only once an operator switched it on. */
  auto_stages?: boolean
}

/**
 * @contract API.md "GET /repos/{name}/config-candidates" — one config change the mine's gold
 * notes and skips imply (DL-316): `field` is the dotted config path (`runner_opts.timeout`,
 * `lint.timeout`) or, for a `deployment` scope, the variable an operator sets; `observed` is
 * the configured limit that was hit; `proposed` what Accept applies.
 */
export interface ConfigCandidate {
  id: string
  kind: 'raise_test_timeout' | 'raise_lint_timeout' | 'provisioning_on' | string
  scope: 'repo' | 'deployment'
  field: string
  observed: number | boolean | null
  proposed: number | boolean | null
  reason: string
  sources: string[]
}

export interface ConfigCandidates {
  repo: string
  items: ConfigCandidate[]
}

/** @contract API.md "POST /repos/{name}/config-candidates/{id}/accept|reject". */
export interface CandidateDecision {
  repo: string
  id: string
  decision: 'accepted' | 'rejected'
  candidate: ConfigCandidate
  config: RepoConfig
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

/**
 * The server's record that a person opened the baseline of a repository with rows
 * (`POST /repos/{name}/baseline-read`, the `repo.baseline_read` event): the first read,
 * who made it and when. Home task 6 "Read the baseline" completes on it (DL-074).
 */
export interface BaselineRead {
  at: string
  by: string
}

/** `GET /repos/{name}` — repo + config, and the first read of its baseline (`null` until one). */
export interface RepoDetail extends RepoSummary {
  config: RepoConfig
  baseline_read?: BaselineRead | null
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

/**
 * `GET /repos/{name}/pool` — which stretch of history the mined tasks come from. The miner
 * takes the newest non-merge commits that touch both source and tests, so this is the pool's
 * recency bias, shown. The history fields and `share` are `null` when the clone cannot be read
 * on the API host, and `history_unavailable` says why.
 */
export interface RepoPool {
  repo: string
  n_tasks: number
  oldest_authored: string | null
  newest_authored: string | null
  history_commits: number | null
  history_first_authored: string | null
  window_commits: number | null
  share: number | null
  history_unavailable: '' | 'no_clone_path' | 'clone_path_escapes' | 'clone_unavailable' | 'git_failed'
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/** What a run does; `probe` is queued from the repo page, the rest from the run dialog. */
export type RunKind = 'mine' | 'replay' | 'blind' | 'oracle' | 'controls' | 'probe' | 'label' | 'factory' | 'qualify'
/** The kinds an operator can start from the run dialog (a probe has its own button). */
export const RUN_KINDS: readonly RunKind[] = ['mine', 'qualify', 'replay', 'blind', 'oracle', 'controls']

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
  /** Why the run ended before its tasks did (`""` when it did not). */
  stopped_reason?: string
  /** The same as a code: `spend_cap` when the run stopped itself before an attempt or item
   *  that could pass its `max_cost_usd` (F5b); `""` otherwise, absent on an older server. */
  stopped_code?: string
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
 * delivery was on, who lifted its sign-off clause (id and display name) and the frozen
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
  /** The run's spend cap in USD (`params.max_cost_usd`, F5b): the most its attempts may cost
   *  together; `null` without one, absent on an older server. */
  max_cost_usd?: number | null
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
  /**
   * Build kinds (F5b): the most the run's attempts may cost together, in USD. The worker stops
   * the run before an attempt (a factory run: an item) that could pass it. Refused 422
   * `spend_cap_unpriced` when a rung's model has no known price. @contract API.md "POST /runs".
   */
  max_cost_usd?: number
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
  /** factory runs only — delivery is route-gated (ADR-0003 amendment 2026-09-16); `deliver_override` is refused 409 `same_actor` at enqueue — a second approver grants it with `POST /runs/{id}/deliver-override` (amendment 2026-09-27). */
  /** Per-run raw-retention switches (both default off — ADR-0006). */
  retain?: { worktrees?: boolean; transcripts?: boolean }
  deliver?: boolean
  deliver_override?: boolean
  max_rework?: number
  /**
   * ADR-0019 — qualify every task with no record in the posture that will grade it before
   * any builder call (no model spend). On by default; `false` makes the submit refuse a run
   * with nothing qualified (409 `posture_unqualified`).
   */
  qualify_first?: boolean
  /** ADR-0019 — stop after this many consecutive environment rows (default 2; 0 = off). */
  env_stop?: number
  /**
   * The belt-5 pre-flight: after an honest build the repository's own formatter and linter
   * plan runs on the changed files, fixes what it can and gives the builder ONE bounded repair
   * call. The rows record the builder as `<name>+preflight` — a separate arm, never pooled
   * with plain rows — and the repair call is the attempt's spend. Sent only when `true`
   * (the Measure page's switch, off by default). @contract API.md "POST /runs".
   */
  preflight?: boolean
}

/** One refusal code of a repository's posture, with what to do (ADR-0019 §9). */
export interface PostureRefusal {
  code: string
  n: number
  message: string
  fix: string
  doc: string
}

/** How one task's record differs from its record in another posture. */
export interface PostureDelta {
  task_id: string
  reference_posture_id: string
  reference_posture_class: string
  same_fingerprint: boolean
  only_here: string[]
  only_there: string[]
}

/** `GET /repos/{name}/posture` — the posture most recently recorded for the repository. */
export interface RepoPosture {
  repo: string
  executor: string
  image_ref: string
  posture_id: string
  posture_class: string
  posture: Record<string, string>
  provisioning: { enabled?: boolean }
  qualified: number
  total: number
  refusals_by_code: PostureRefusal[]
  delta: PostureDelta[]
  stale_reason: string
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

/**
 * One economics figure (`crb.core.economics.Estimate`, F35). `n` is its denominator (the
 * attempts — or clean attempts — with a KNOWN value). `value` is `null` when nothing is
 * known, never `0`; `ci_low` / `ci_high` are `null` whenever no interval is served, and
 * `reason` then says why (`''` only when the value and its interval are both served).
 */
export interface EconomicsEstimate {
  n: number
  value: number | null
  ci_low: number | null
  ci_high: number | null
  method: string
  reason: string
}

/** `crb.core.economics.Economics` — cost and latency with their denominators, intervals and apparatus. `pooled` = the rows span more than one apparatus version, posture class or checks arm, so every estimate is withheld and `pooled_reason` names what they span. */
export interface Economics {
  n_attempts: number
  n_clean: number
  cost_known: number
  cost_known_clean: number
  latency_known: number
  latency_known_clean: number
  apparatus_versions: string[]
  /** The labelled posture classes of the rows (ADR-0019); empty for rows graded before 2.3. */
  posture_classes: string[]
  /** The checks arms of the rows (ADR-0024); one, unless the fold was refused. */
  checks_arms: string[]
  pooled: boolean
  pooled_reason: string
  cost_per_attempt: EconomicsEstimate
  cost_per_clean: EconomicsEstimate
  latency_per_attempt: EconomicsEstimate
}

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
  /** Flat means over the known rows; they follow the map's filters, so `posture=all` / `apparatus=all` pools them (G-990). Quote `economics`, never these. */
  cost_usd_mean: number
  latency_s_mean: number
  /** Did any eligible row record a known cost (a known $0 counts) / a latency? */
  cost_known?: boolean
  latency_known?: boolean
  /** F35 — the cell's cost and latency with known counts, t intervals and apparatus. */
  economics?: Economics
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
  // --- routing.v2 (ADR-0025, ADR-0026) ------------------------------------------------
  /** The one context arm and class-set version the cell reads (never pooled). */
  context_arm?: string
  taxonomy?: string
  apparatus_version?: string
  /** What the cell's reading says about its arm, and the counts it read at. */
  look_state?: string
  reading_id?: string
  counted?: number
  counted_clean?: number
  counted_ci_low?: number
  counted_ci_high?: number
  needed?: number
  next_look?: number | null
  shortfalls?: Shortfall[]
  /** Every arm of the reading that speaks for the cell; `null` — none registered. */
  reading?: ReadingOutcome | null
  standard?: CellStandard | null
  /** The entry gate's own reading of the (class × size) cell's proven standard: an active sign-off it reads, on the repository's checks arm and this deployment's posture class, whatever the view's filters. The ONE reading of "signed" (P-411) — `verification_tier` is the overlay's record, a second rule. `null` for a cell pooling classes or sizes, and on an organisation's class-set view (G-763). */
  signed?: boolean | null
  /** What the briefs carried beyond their arm (label → distinct values) — never a split. */
  provenance?: Record<string, string[]>
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
  /** ADR-0019 §8 — the posture class the map reads (the deployment's by default). */
  posture_class?: string
  /** Rows `posture=all` left out because the task's oracle differs between classes. */
  excluded_posture_divergent?: number
  /** Pre-2.3 docker rows graded against a baseline measured elsewhere — excluded. */
  unqualified_posture?: number
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
  /** F35 — the economics of every row behind the map, folded from the rows (the Baseline's tiles). */
  economics?: Economics
  /** The one context arm the map reads (`standard` = each cell on its own) and the arms present. */
  arm?: string
  arms?: string[]
  taxonomy?: string
  /** ADR-0025 item 1: the apparatus in force, the one read, and what earlier ones hold as history. */
  apparatus?: { current: string; read: string; superseded_rows: number; superseded_versions: string[] }
}

/** `crb.core.routing.RoutingPolicy.to_dict()` — routing.v2 (ADR-0025 as ADR-0026 amends it): the look rule replaces routing.v1's `min_n`, point and Wilson bars. */
export interface RoutingPolicy {
  /** The look rule a reading is read under (`look.v1`, `look.v1-strict`, `look.v1-late`). */
  rule: string
  /** Look size → the misses allowed at that look (`{"20": 0, "30": 1, "40": 2}`). */
  looks: Record<string, number>
  /** The rule's exact chance of delivering a cell whose true first-attempt rate is 0.80. */
  p_deliver_at_0_80: number
  /** One error budget per cell (ADR-0026 item 5). */
  cell_error_budget: number
  min_oracle_strength: number
  min_oracle_share: number
  granularize_sizes: string[]
  version: string
  /** The published bar as one sentence — README carries it byte for byte (ADR-0025 item 10). */
  description: string
}

/** One clause a cell fails, with what to measure next (ADR-0025 item 8). */
export interface Shortfall {
  code: string
  route: string
  observed: unknown
  threshold: unknown
  /** `register`, `replay`, `qualify`, `mine`, `oracle`, `controls`, `seal`, `config`, `strengthen`, `new_reading`, `calibration_builds`, `build_on_standard`, `split`, `audit`, `none`. */
  next: string
  count: number
  model_money: boolean
}

/** One arm of a registered reading (`crb.core.reading.ArmReading.to_dict`). */
export interface ArmReading {
  arm: string
  /** `deliver`, `insufficient`, `undecided`, `look_pending`, `descriptive`, `stopped`. */
  state: string
  descriptive: boolean
  stopped_by: string
  counted: number
  clean: number
  misses: number
  ci_low: number
  ci_high: number
  next_look: number | null
  needed: number
}

/** A registered reading evaluated (`crb.core.reading.ReadingOutcome.to_dict`). */
export interface ReadingOutcome {
  reading_id: string
  rule: string
  hierarchy: string[]
  /** `standard`, `ceiling`, `look_pending`, `insufficient`, `undecided`. */
  state: string
  standard: string | null
  ceiling: boolean
  chain: string[]
  stopped_at: string | null
  needed: number
  spend: number
  registered_at: string
  pool: number
  pool_sha256: string
  arms: ArmReading[]
}

/** A cell's proven context: its standard arm, or `standard: null` — "no proven standard". */
export interface CellStandard {
  standard: string | null
  ceiling: boolean
  label: string
  next: string
  next_count: number
  budget: number
  spent: number
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
  /** Made on an earlier apparatus than the one the deployment reads at now, or carrying no apparatus stamp (ADR-0015): kept, verifying, lifting nothing until re-signed or revoked. */
  stale: boolean
  /** Why `stale` (first match): `verifier_deactivated` — the approver's account was deactivated since, and a leaver's sign-off lifts nothing (DL-120); `no_apparatus_stamp` — signed before the stamp existed, so it covers no rows (GOV-6); `apparatus_moved`; `checks_arm_moved`; `posture_moved`; `""` when not stale. */
  stale_reason?: '' | 'verifier_deactivated' | 'no_apparatus_stamp' | 'apparatus_moved' | 'checks_arm_moved' | 'posture_moved'
  /** The deployment's current apparatus, for comparison with `evidence.apparatus_versions`. */
  apparatus_current: string
  /** This stored row no longer hashes to its own `row_hash` — altered under the append-only triggers (EI-6). */
  tampered?: boolean
  /** The whole sign-off chain verifies. `false` = some row was altered, removed or re-ordered: every record is served inactive and none lifts a cell (EI-6). */
  chain_ok?: boolean
  /** The checks arm the evidence was signed on (ADR-0024) — `off` for a record from before the switchboard. A record signed on another arm than `checks_arm_current` is stale too. */
  checks_arm?: string
  /** The checks arm the repository's cells are read on now; `""` for a record not tied to one repository. */
  checks_arm_current?: string
  /** The posture class(es) the evidence was graded in (ADR-0019) — `""` for evidence from before apparatus 2.3. A record signed in another class than `posture_class_current` is stale too. */
  posture_class?: string
  /** The posture class the deployment grades the repository in now; `""` for a record not tied to one repository. */
  posture_class_current?: string
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

/**
 * Why a stale sign-off is stale, in the words both screens that list one use (the Sign-off
 * table's status pill and the Decisions page), so a reason explained on one is never "signed
 * at apparatus ?" on the other (P-232). `current` stands in when the record names no current
 * apparatus.
 */
export function signoffStaleWhy(
  s: Pick<Signoff, 'stale_reason' | 'checks_arm' | 'checks_arm_current' | 'apparatus_current' | 'evidence'>,
  current = '',
): string {
  const now = s.apparatus_current || current || '?'
  if (s.stale_reason === 'verifier_deactivated') return 'signed by an account that has since been deactivated, and a leaver’s sign-off licenses nothing'
  if (s.stale_reason === 'no_apparatus_stamp') return `signed before the apparatus stamp, now reading at ${now}`
  if (s.checks_arm && s.checks_arm_current && s.checks_arm !== s.checks_arm_current) {
    return `signed on the ${s.checks_arm} checks arm, now reading the ${s.checks_arm_current} arm`
  }
  return `signed at apparatus ${s.evidence.apparatus_versions.join(', ') || '?'}, now reading at ${now}`
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
/** The audit trail's chain inside `GET /ledger/verify` (`events`, ADR-0029): `broken_at` is an event id. */
export interface EventsVerify {
  rows: number
  chain_ok: boolean
  broken_at: number | null
  detail: string
  /** The last event's `row_hash` (`""` when there is none), to record outside the store. */
  head_row_hash: string
  /** `full` re-hashed every event; `tail` only those appended since the last clean walk (P-257). */
  walk: 'full' | 'tail'
  /** When the last full walk behind this answer ran (ISO 8601, UTC). */
  full_walk_at: string
}

/** One hash-chained table walked from its stored columns (``ChainVerifyOut``). */
export interface ChainVerify {
  rows: number
  chain_ok: boolean
  broken_at: number | null
  detail: string
}

/** One builder's disqualified rows in the window — mirrors `DisqualifiedBuilderOut`. */
export interface LedgerDisqualifiedBuilder {
  builder: string
  n: number
}

/** The `disqualified` block of `GET /ledger/verify` (G-400, DL-312): rows graded
 *  `disqualified` in the last `window_days`, per builder; `over` = the builders at or past
 *  `threshold`. Mirrors `DisqualifiedOut`; read by the Ledger's disqualified tile (stream pgs). */
export interface LedgerDisqualified {
  window_days: number
  threshold: number
  by_builder: LedgerDisqualifiedBuilder[]
  over: string[]
}

/**
 * `GET /ledger/verify` — mirrors `LedgerVerifyOut`. `ok` holds only when the grade chain, the
 * audit trail's chain, false-Q1 = 0 and every clean row's pack all hold; `chain_ok` and
 * `broken_at` are the grade chain's alone, so a reader is told WHICH part failed.
 */
export interface LedgerVerify {
  rows: number
  ok: boolean
  false_q1_total: number
  chain_ok: boolean
  broken_at: number | null
  detail: string
  clean_without_pack: number
  /** The sign-off and review chains, walked the same way (EI-6). */
  signoffs: ChainVerify
  reviews: ChainVerify
  verified_at: string
  /** The grade ledger's last `row_hash` (`""` when empty), to record outside the store. */
  head_row_hash: string
  events: EventsVerify
  disqualified: LedgerDisqualified
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
  /** G-952 (controls.v3): the gold graded beside a catch in the same posture (`clean`, or what it read instead); null or absent when the row is not a catch or predates witnesses. */
  witness?: string | null
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
  /** G-952 (controls.v3): caught rows with a gold witness, and those whose witness was not clean; absent before v3. */
  witnessed?: number
  witness_failures?: number
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
  /**
   * B-9 / F30 — the pull requests the factory delivered on this repository and how they
   * ended, as COUNTS (a merge is a human act, never a rate — DL-049); `last_synced` is the
   * newest outcome's record time, `''` when none was ever read. Optional for a mock built
   * before G-368; the server always sends it.
   */
  outcomes?: FactoryOutcomesSummary
}

/** `FactoryBacklogOut.outcomes` (`OutcomesSummaryOut`): delivered / merged / closed / open, by count. */
export interface FactoryOutcomesSummary {
  delivered: number
  merged: number
  closed: number
  open: number
  last_synced: string
}

/** The newest delivered pull request's fate (`DeliveryOutcomeOut`): `open` = delivered and no
 *  outcome recorded yet (the other fields `''`); `merged` / `closed` from the newest
 *  `delivery.merged` / `delivery.closed` event, `synced_at` its record time. */
export interface FactoryDeliveryOutcome {
  state: 'open' | 'merged' | 'closed' | string
  pr_number: number
  pr_url: string
  merged_at: string
  merged_by: string
  merge_sha: string
  closed_at: string
  synced_at: string
}

/** `POST /factory/{repo}/outcomes/sync` (`OutcomeSyncOut`): what one sync did, and the summary after it. */
export interface FactoryOutcomeSync {
  checked: number
  merged: number
  closed: number
  open: number
  errors: string[]
  outcomes: FactoryOutcomesSummary
}

/** The body `POST /factory/{repo}/backlog/evolutions` takes (`EvolutionRegisterIn`, F32): the
 *  superseding item — a backlog item plus `supersedes` — and, when the stop was about the test,
 *  the operator-authored failing test that goes with it. */
export interface FactoryEvolutionBody {
  item: {
    id: string
    title: string
    kind: string
    description: string
    capability_class: string
    size_estimate: string
    structural_facts: string[]
    acceptance_criteria: string[]
    depends_on: string[]
    level: string
    supersedes: string
  }
  authored?: { path: string; content: string }
}

/** J-FAC-4 — why the loop stopped an item, as recorded on the chain; `step` names where. */
export interface FactoryRefusal {
  /** `review` = the rule-3 stop (DL-045): routed human AFTER a verdict, never a readiness refusal;
   *  `entry` = the entry gate stopped the item before any spend (ADR-0026 item 8). */
  step: 'readiness' | 'red' | 'delivery' | 'review' | 'dependency' | 'entry'
  reason: string
  reason_code: string
  measured_route: string
}

/** The superseding item the API drafts for a stopped one (G-904): the body an operator POSTs to
 *  `FactoryWayForward.route`, every field but `id` and `description` taken from the item that
 *  stopped. `description` is that item's own words plus the stop's reason — for a weak-oracle
 *  stop, the reviewer's finding. */
export interface FactoryEvolutionPrefill {
  id: string
  title: string
  kind: string
  description: string
  capability_class: string
  size_estimate: string
  structural_facts: string[]
  acceptance_criteria: string[]
  depends_on: string[]
  level: string
  supersedes: string
}

/** The stopped item's next action: the evolutions route, one sentence saying what must be
 *  different, whether the POST should carry a stronger oracle, and the draft itself. */
export interface FactoryWayForward {
  /** `register_evolution`: POST the superseding item to `route`; `fund_calibration`: an approver POSTs a
   *  reason to `route` (ADR-0026 item 8 — one calibration build, never a pull request); `sign_off_cell`:
   *  a second person signs the cell (`/signoffs`). */
  action: 'register_evolution' | 'fund_calibration' | 'sign_off_cell'
  route: string
  supersedes: string
  /** One sentence: what must be different about the superseding item. `''` on an older server. */
  what_to_change?: string
  /** True when the stop was about the test: the POST should carry an `authored` oracle. */
  needs_authored_test?: boolean
  /** The draft; `null` when the item is not in a backlog the API can read. */
  prefill?: FactoryEvolutionPrefill | null
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
  /** The next action the API serves for a stopped item (a readiness / red / review stop, a rejected or
   *  rework-exhausted verdict, no oracle): `POST` an evolution to `route` with `supersedes` = this item.
   *  `null` while the item is not stopped or is already superseded. */
  way_forward?: FactoryWayForward | null
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
  /** `deliverable` is the whole licence under this deployment's posture (ADR-0018 as amended by ADR-0026 item 8): the route says `deliver` and, while `require_signed_cell` is on, `signed` is true — the cell's proven standard carries an active sign-off; an item whose cell's standard is unsigned is not built at all. `verification_tier` is the map's tier, for the record. */
  cell_route: { route: string; reason_code: string; reason: string; n: number; point: number; ci_low: number; ci_high: number; apparatus_versions: string[]; verification_tier?: string; signed?: boolean; deliverable: boolean }
  /** ADR-0026 item 8 — the entry gate's stop since the last readiness pass: the item was NOT BUILT.
   *  `code`: `no_proven_standard` · `needs_context` · `unsigned_cell` · `granularize` · `not_licensed` ·
   *  `unsized`; `needs` is what the ticket must carry. `null` = the item entered (optional for older mocks). */
  entry?: FactoryEntryStop | null
  /** An approver's calibration grant no run has spent yet; `null` = none. */
  calibration?: FactoryCalibrationGrant | null
  /** The SHA-256 of the test the newest RED proof carries — what a strength-probe waiver names. */
  test_sha256?: string
  /** B-9 / F30 — the newest delivered pull request's fate; `null` until a delivery (optional for older mocks). */
  outcome?: FactoryDeliveryOutcome | null
  /** F32 — the supersession chain: the id this item replaced, and the evolution that replaced it (`''` = neither). */
  supersedes?: string
  superseded_by?: string
}

/** Why the entry gate stopped an item before any spend (ADR-0026 item 8). */
export interface FactoryEntryStop {
  code: string
  reason: string
  /** `no_proven_standard`: `none` or `ceiling`; `needs_context`: the arm's base (`S1`, `S2`). */
  reason_code: string
  needs: string[]
}

/** An approver's funded calibration build, not yet built by a run (never a pull request). */
export interface FactoryCalibrationGrant {
  approver: string
  reason: string
  created: string
  event: string
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

// ---------------------------------------------------------------------------
// Invitations and two-person readiness — `src/crb/server/routes/invitations.py` (G-518)
// ---------------------------------------------------------------------------

/** The state an invitation is in, as the server decides it (accepted wins over expired). */
export type InvitationState = 'pending' | 'accepted' | 'expired' | 'revoked'

/** One invitation as the API reports it — never the token and never its hash. */
export interface Invitation {
  id: string
  user_id: string
  username: string
  display_name: string
  email: string
  role: Role
  state: InvitationState
  created: string
  expires: string
  accepted: string
  revoked: string
  created_by: string
  revoked_reason: string
  /** ISO time of the invited account's last sign-in; empty while it has never arrived. */
  last_login: string
}

/** `POST /invitations` body. */
export interface InviteRequest {
  username: string
  role: Role
  display_name: string
  email: string
  expires_hours: number
}

/**
 * `POST /invitations` response — the ONE place the token appears. It is not stored anywhere
 * else, so a lost link is re-invited, never recovered.
 */
export interface InvitationCreated {
  invitation: Invitation
  accept_url: string
  token: string
  /** True when the deployment has no public URL, so `accept_url` is a path, not a link. */
  public_url_missing: boolean
}

/** `POST /invitations/accept` response: the account is live and the next step is to sign in. */
export interface InvitationAccepted {
  username: string
  display_name: string
  role: Role
  accepted: string
}

/**
 * `GET /two-person-readiness` — can this deployment produce a sign-off the two-person rule
 * accepts? It counts ACCOUNTS, not people, and its `reason` says so.
 */
export interface TwoPersonReadiness {
  ready: boolean
  reason_code: 'ready' | 'no_approver' | 'approver_never_signed_in' | 'single_person' | 'runner_is_the_only_signer'
  reason: string
  approvers_active: number
  approvers_signed_in: number
  other_active_accounts: number
  accounts_signed_in: number
  invitations_pending: number
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
    /** Dependency provisioning for the sealed sandbox (ADR-0019; `CRB_PROVISION__*`). */
    provision?: { enabled?: boolean }
    /** `FactorySettings.redacted()`: the test author and the delivery licence posture (ADR-0018). */
    factory?: { test_author: string; require_signed_cell: boolean }
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


// --- intake: the enterprise's own board (ADR-0017) ------------------------------------

/** One repository's intake listener. `enabled` is false until an operator switches it on. */
export interface IntakeListener {
  enabled: boolean
  /** An override for the deployment's watched column; '' means "the deployment's". */
  column: string
  switched_by: string
  switched_at: string
  /** The newest change watermark a poll saw; the next poll asks from here. */
  since: string
}

/** The deployment-wide tracker connection. Never carries the credential — only whether
 *  one is stored and its fingerprint. */
export interface IntakeConnection {
  tracker: string
  url: string
  project: string
  column: string
  poll_s: number
  outcome_map: Record<string, string>
  configured: boolean
  credential_set: boolean
  credential_fingerprint: string
  /** ADR-0022 — a ready ticket waits for an operator's Register act (default true). */
  require_approval?: boolean
  /** Tracker authors whose ready tickets skip the Register act (default empty). */
  approve_authors?: string[]
}

/** One ticket in the watched column, exactly as the last read saw it. */
export interface IntakeRow {
  key: string
  title: string
  url: string
  revision: string
  /** One of `crb:needs-info` · `crb:ready` · `crb:not-deliverable` · `crb:queued`, or ''. */
  label: string
  /** The ticket's own state on the board. */
  state: string
  item_id: string
  item_url: string
  /** The comment the product posted, verbatim — the row and the ticket never disagree. */
  feedback: string
  open_questions: Array<{ ref: string; severity: string; reason: string }>
  capability_class: string
  confidence: number
  size: string
  registered: boolean
  is_evolution: boolean
  supersedes: string
  cell_route: FactoryTask['cell_route'] | null
  read_at: string
  /** A published stop reason when this ticket's own step stopped; '' otherwise. */
  stopped: string
  stopped_advice: string
  /** ADR-0022 — a ready draft waiting for an operator's Register act. */
  awaiting_approval?: boolean
  /** Who created the ticket, as the tracker names them (the allowlist's input). */
  author?: string
  /** ADR-0026 item 8 — the entry gate's stop for this ticket (`no_proven_standard`, `needs_context`,
   *  `unsigned_cell`, `granularize`, `unsized`); `''` = it enters. The item is NOT BUILT while it stands. */
  entry_stop?: string
  entry_reason?: string
  /** What the ticket must carry: the missing slots, or `a failing test`. */
  entry_needs?: string[]
  /** The cell's standard arm (`S1@<author>`, `S2`), `''` when none is proven. */
  standard?: string
}

/** What the last poll did, and why it stopped if it did. */
export interface IntakePoll {
  repo: string
  column: string
  seen: number
  read: number
  skipped: number
  commented: number
  registered: number
  queued: number
  /** Ready drafts left waiting for an operator's Register act (ADR-0022). */
  awaiting?: number
  stopped: string
  detail: string
  advice: string
  at: string
  /** Another pass held the repository's lease; this one did nothing. */
  busy?: boolean
}

/** `GET /factory/{repo}/intake` — the listener, the connection, the last poll, the column. */
/** A held-out acceptance-test record as a page may show it: never the tests themselves. */
export interface HeldOutRecord {
  record_id: string
  item_id: string
  grant: string
  author: string
  written_at: string
  sha256: string
  paths: string[]
}

/** One ticket whose calibration build needs, or has, a second person's held-out acceptance
 *  tests (`GET /factory/{repo}/acceptance`, ADR-0026 item 8). Never the ticket's own failing
 *  test and never a build. */
export interface AcceptanceAssignment {
  item_id: string
  title: string
  description: string
  acceptance_criteria: string[]
  capability_class: string
  size: string
  grant: string
  funded_by: string
  /** The approver's display name; empty when the store does not know them. */
  funded_by_name: string
  funded_at: string
  /** `open` (tests needed), `written`, `building` (the grant is claimed), `graded`,
   *  `not_graded` (built without them — `why_not` says why) or `cannot_grade` (the ticket was
   *  attempted before this build). */
  status: 'open' | 'written' | 'building' | 'graded' | 'not_graded' | 'cannot_grade'
  can_write: boolean
  /** Why the signed-in person may not write them; empty when they may. */
  why_not: string
  record: HeldOutRecord | null
  /** The display name of the person who wrote the record; empty with no record. */
  author_name: string
  /** `pass`, `fail` or `error` once the first attempt is graded; else empty. */
  result: string
  /** The latest forward reading registered on this ticket's kind, size and language; empty for none. */
  forward_reading: string
  /** The forward reading whose pool enrols this ticket (its tests were written after it was
   *  registered); empty when none does — the ticket is then graded but never counted. */
  counted_by: string
  /** A test path this repository's runner accepts for the ticket; empty when none is known. */
  suggested_path: string
}

export interface AcceptanceAssignments {
  repo: string
  assignments: AcceptanceAssignment[]
}

export interface Intake {
  repo: string
  listener: IntakeListener
  connection: IntakeConnection
  last_poll: IntakePoll | null
  rows: IntakeRow[]
}

// ---------------------------------------------------------------------------
// The prevention loop (ADR-0020) — `GET /learn/register` (crb.prevention.register.v1)
// ---------------------------------------------------------------------------

/** One of stream S's five: where a bug class stands in the prevention loop. */
export type PreventionStatus = 'open' | 'applied' | 'closed' | 'retired' | 'escalated'

/** The repository's learning switch, folded from the chain: the last `switched` record. */
export interface PreventionSwitch {
  auto_apply: 'off' | 'context' | 'config'
  switched_by: string
  switched_at: string
  reason: string
  record_id: string
}

/** The lever the loop would apply, the levers it passed over and why, and what it would file. */
export interface PreventionLeverChoice {
  lever_id: string
  level: string
  family: string
  why: string
  allowed: boolean
  passed_over: Array<{ lever_id: string; level: string; why_not: string }>
  propose: string[]
}

/** One applied change (or a person's link) as the chain records it. */
export interface PreventionChange {
  change_id: string
  lever_id: string
  family: string
  level: string
  targets: string[]
  stratum_mode: string
  key: string
  what: Record<string, unknown>
  applied_at: string
  applied_by: string
  on_behalf_of: string
  before: Record<string, Record<string, unknown>>
  state: 'in_force' | 'retired' | 'reverted'
  record_hash: string
}

/** A filed item for a person: the class, the lever, its level, and where it went once registered. */
export interface PreventionProposal {
  item_id: string
  targets: string[]
  lever_id: string
  level: string
  scope: string
  kind: string
  title: string
  description: string
  expected_effect: string
  evidence_refs: string[]
  evidence_total: number
  proposed_at: string
  record_hash: string
  registered: Record<string, unknown> | null
}

/** Before → after for one class under the change in force, with the bar the rule decides at. */
export interface PreventionMeasurement {
  signature: string
  stratum_mode: string
  key: string
  before: { k: number; n: number; p0: number; digest: string; clean_rate: number }
  exposed: { k: number; n: number; clean_k: number; clean_ci_low: number; clean_ci_high: number }
  unexposed_n: number
  concurrent: { k: number; n: number }
  /** Attempts the change never reached, on tasks no exposed attempt ran: while the class recurs there at or above p0, it is never kept or closed. */
  withheld?: { k: number; n: number }
  not_comparable: number
  decisive_n: number
  looks: number[]
  closing_window: number
  closing_zero_run: number
  bar: string
  deterministic: boolean
}

/** One bug class of one repository (ADR-0020 §3). */
export interface PreventionEntry {
  repo: string
  signature: string
  family: string
  sub: string
  detail: string
  first_seen: string
  first_ref: string
  last_seen: string
  occurrences: number
  first_attempts: number
  blocked: number
  tasks: number
  runs: number
  cost_usd: number
  refs: string[]
  refs_total: number
  by_mode: Record<string, number>
  by_apparatus: Record<string, number>
  not_comparable: number
  stratum: { mode: string; key: string; n: number; k: number; tasks: number }
  actionable: boolean
  why_not: string
  capability: boolean
  recommendation: PreventionLeverChoice
  change: PreventionChange | null
  proposals: PreventionProposal[]
  measurement: PreventionMeasurement | null
  status: PreventionStatus
  qualifiers: string[]
  lever_kind: 'process' | 'context' | ''
  next: string
  history: Array<{ kind: string; record_id: string; row_hash: string; created: string; actor: string; on_behalf_of: string; summary: string }>
}

/** `GET /learn/register?repo=` — the prevention register of one repository. */
export interface PreventionRegister {
  schema: string
  repo: string
  rules: Record<string, string>
  apparatus: string
  switch: PreventionSwitch
  attempts: Record<string, number>
  counts: Record<PreventionStatus, number>
  share_closed: number | null
  share_closed_by_process: number | null
  overlay: Record<string, Record<string, unknown>>
  playbook: { lines: Array<{ line_id: string; template_id: string; signature: string; text: string }>; chars: number; max_lines: number; max_chars: number; sha256: string }
  entries: PreventionEntry[]
  proposals: PreventionProposal[]
  links: Array<{ record_id: string; targets: string[]; ref: string; note: string; linked_at: string; actor: string }>
  chain: { records: number; head: string; verified: boolean; error?: string }
  decisions_verified: string[]
}

/** One record a prevention write appended, as the chain holds it. */
export interface PreventionRecordOut {
  kind: string
  repo: string
  record_id: string
  created: string
  actor: string
  on_behalf_of: string
  reason: string
  payload: Record<string, unknown>
  row_hash: string
}

// ---------------------------------------------------------------------------
// Value — the scorecard (`GET /value`, crb.core.value.ValueReport.to_dict)
// ---------------------------------------------------------------------------

/** A rate as the scorecard serves it: `null` point and interval when `n = 0`, never zero. */
export interface ValueRate {
  k: number
  n: number
  point: number | null
  ci_low: number | null
  ci_high: number | null
  /** Distinct tasks under `n` and `k` — `n` counts attempts, and repeats on a task are not independent. */
  n_tasks?: number
  k_tasks?: number
}

/** `north_star` — working changes per pound, blind: an estimate (clean rate × precision). */
export interface ValueNorthStar {
  label: string
  per_pound: number | null
  per_pound_low: number | null
  per_pound_high: number | null
  pounds_per_working: number | null
  pounds_per_working_low: number | null
  pounds_per_working_high: number | null
  working_rate: number | null
  working_rate_low: number | null
  working_rate_high: number | null
  working_estimate: number | null
  n_attempts: number
  n_valid: number
  /** Distinct tasks under `n_valid` (attempts): the independence the intervals assume is at most this. */
  n_tasks?: number | null
  clean: number
  clean_tasks?: number | null
  clean_rate: ValueRate
  precision_basis: 'review' | 'review_pooled' | 'proxy' | 'none'
  precision: ValueRate
  /** The priced blind spend; `null` when no blind attempt is priced — unmeasured, never $0. */
  spend_usd: number | null
  spend_gbp: number | null
  /** Blind attempts whose cost is a measurement, and those with no price (never summed as zero). */
  spend_rows_priced?: number
  spend_rows_unpriced?: number
  /** Why the per-pound figures are null although the rate is measured ('' when they are served). */
  per_pound_withheld?: string
  usd_per_gbp: number
  method: string
}

/** `GET /value` — only the fields a screen reads are typed; the rest is in docs/API.md. */
export interface ValueReport {
  schema: 'crb.value.v1'
  repo: string | null
  apparatus: string
  apparatus_versions: string[]
  pooled: boolean
  /** The one checks arm the headline reads (ADR-0024): the repository's own, or `off` across repositories. */
  checks?: string
  rows: number
  usd_per_gbp: number
  north_star: ValueNorthStar
  learning_curve: { source: string; attempts: number; register: { source: string; n_classes: number; closed: number; closed_share: number | null } }
}

// ---------------------------------------------------------------------------
// Flow (docs/API.md "Flow (how long each stream takes, and what it spent)")
// ---------------------------------------------------------------------------

/**
 * One milestone pair's duration. `median_s` / `min_s` / `max_s` are `null` when `n` is 0 —
 * unmeasured, not zero — and `reason` then says why in one sentence. `dropped` counts the pairs
 * the server refused (an unreadable stamp, or an end before its start).
 */
export interface LeadTime {
  key: string
  label: string
  n: number
  median_s: number | null
  min_s: number | null
  max_s: number | null
  dropped: number
  reason: string
}

/**
 * What a stream spent. `usd` sums only the rows whose cost is a measurement and is `null` when
 * there are none; `rows_unpriced` is how many rows the sum leaves out, so the total is read as
 * a floor and never as the whole bill.
 */
export interface Spend {
  usd: number | null
  rows_priced: number
  rows_unpriced: number
  /** The apparatus versions of the rows the reading covers, priced or not. */
  apparatus_versions: string[]
}

/** A figure a stream's definition of done asks for that nothing in the product records. */
export interface NotCaptured {
  figure: string
  why: string
  gap: string
}

/** One value stream's own numbers. */
export interface StreamFlow {
  stream: string
  name: string
  lead_times: LeadTime[]
  spend: Spend
  /** Which rows the spend covers, in words — the streams do not all buy the same thing. */
  spend_label: string
  /**
   * `per_unit_spend` divided by `per_unit_units` (the things the stream delivers), or `null` when
   * either side is unmeasured or the spend is a floor; `per_unit_reason` then says which.
   */
  per_unit: number | null
  per_unit_label: string
  /** What `per_unit` divided: the spend of the rows it covers. */
  per_unit_spend: Spend
  per_unit_units: number
  per_unit_reason: string
  counts: Record<string, number>
  not_captured: NotCaptured[]
}

/** `GET /flow?repo=` — every stream's lead time, spend and counts, derived from stored records. */
export interface Flow {
  repo: string
  apparatus: string
  generated: string
  /** How the figures were produced — a fold over stored records, not a live probe. */
  method: string
  /** The repository's cumulative spend — every graded row once; the streams' spends partition it. */
  spend: Spend
  streams: StreamFlow[]
}

// ---------------------------------------------------------------------------
// Library (the context library — ADR-0026 item 10; docs/API.md#library)
// ---------------------------------------------------------------------------

/** The six kinds of entry, in the order the nomenclature index lists them. */
export type LibraryKind = 'component' | 'work-type' | 'decision' | 'convention' | 'pattern' | 'standard'
export type LibraryStatus = 'proposed' | 'signed' | 'stale' | 'retired' | 'revoked'

/** Where an entry came from (`crb.core.library.Provenance.to_dict`). */
export interface LibraryProvenance {
  kind: 'person' | 'file' | 'rows'
  path: string
  commit: string
  digest: string
  rows: string[]
  person: string
}

/** One version of one entry (`LibraryEntry.content()`). */
export interface LibraryRecord {
  repo: string
  kind: LibraryKind
  slug: string
  title: string
  statement: string
  provenance: LibraryProvenance
  /** A person's account id, `mined:<miner version>` or `drafted:<model>`. */
  proposed_by: string
  components: string[]
  work_types: string[]
  characteristic: string
  check: string
  parent_class: string
  examples: string[]
  slots: string[]
}

/** An entry as it stands (`EntryState.to_dict()` plus names and evidence). */
export interface LibraryEntry {
  entry_id: string
  version: string
  entry: LibraryRecord
  status: LibraryStatus
  proposed_at: string
  sponsor: string
  sponsor_name: string
  sponsored_at: string
  approver: string
  approver_name: string
  signed_at: string
  stale: { head_commit: string; path: string; digest: string; at: string } | null
  retired: { actor: string; by: 'person' | 'measurement'; reason: string; reading_id: string; at: string } | null
  revoked: { actor: string; reason: string; at: string } | null
  /** `unmeasured` until a measured arm serves an effect (Wave 5). */
  effect: string
  /** For a standard or convention: `check` when the repository runs it, else `advisory`. */
  evidence: '' | 'check' | 'advisory'
  acts: number
}

export interface LibraryWorkType {
  slug: string
  title: string
  parent_class: string
  /** `global` for a class of the global vocabulary; otherwise the work-type entry's status. */
  status: 'global' | LibraryStatus
  tasks: number
}

/** `GET /library/{repo}`. */
export interface LibraryIndex {
  repo: string
  entries: LibraryEntry[]
  work_types: LibraryWorkType[]
  kinds: LibraryKind[]
  characteristics: string[]
  statement_max: number
  /** Always `false`: no entry reaches a builder's brief outside a measured arm. */
  reaches_briefs: boolean
}

export interface LibraryContextRow {
  entry_id: string
  kind: LibraryKind
  title: string
  statement: string
  sponsor: string
  sponsor_name: string
  approver: string
  approver_name: string
  signed_at: string
  provenance: LibraryProvenance
  provenance_label: string
  proposed_by: string
  effect: string
  characteristic: string
  check: string
  evidence: '' | 'check' | 'advisory'
}

/** A cell's proven standard as stream R's reading serves it (`ProvenStandard.to_dict()`). */
export interface LibraryStandard {
  arm: string
  n: number
  clean: number
  ci_low: number
  ci_high: number
  apparatus: string
  state: string
  ceiling: boolean
  reading_id: string
  /** For a ceiling: the forward (`S2`) reading registered to promote it, or null when none is
   *  (ADR-0026 items 4 and 8). Absent on a server from before stream FWD. */
  forward?: ForwardReadingState | null
}

/** `POST /readings/forward` — register the forward (`S2`) reading of a ceiling (operator). */
export interface ForwardReadingRequest {
  repo: string
  /** The ceiling's reading id. */
  promotes: string
  builder: string
  model: string
  provider: string
}

/** A ceiling's forward reading, as the work type's page serves it. */
export interface ForwardReadingState {
  reading_id: string
  rule: string
  registered_at: string
  /** The `S2` arm's look state: `look_pending`, `deliver`, `insufficient`. */
  state: string
  /** Tickets whose first attempt was graded on held-out tests and read, and the clean ones. */
  counted: number
  clean: number
  /** Tickets enrolled: their held-out tests were written after the reading was registered. */
  enrolled: number
  next_look: number | null
  /** Tickets still needed before that look can be read. */
  needed: number
}

export interface LibrarySizeRow {
  size: string
  tasks: number
  standard: LibraryStandard | null
  /** What would prove the cell, when nothing does — or, for a ceiling, what a calibration
   *  build needs; empty for a proven standard. */
  next: string
}

export interface LibraryQualityRow {
  characteristic: string
  checks: Array<{ check: string; label: string; sub: string; runs: string; on: boolean }>
  evidenced: boolean
  note: string
}

/** `GET /library/{repo}/work-types/{slug}` — the page per work type. */
export interface WorkTypePage {
  repo: string
  slug: string
  title: string
  definition: string
  definition_source: string
  parent_class: string
  examples: Array<{ sha: string; subject: string; size: string }>
  ticket_slots: Array<{ name: string; question: string; kind: string }>
  signed_slots: string[]
  context: LibraryContextRow[]
  sizes: LibrarySizeRow[]
  quality: { served: boolean; rows: LibraryQualityRow[]; switched_on: string[]; standards: LibraryContextRow[] }
  reaches_briefs: boolean
}

/** One outcome of a miner run: what it did with one draft or note. */
export type LibraryMineOutcomeKind = 'proposed' | 'unchanged' | 'held' | 'refused' | 'noted' | 'failed'
export interface LibraryMineOutcome {
  miner: string
  subject: string
  outcome: LibraryMineOutcomeKind
  reason: string
  version: string
  counts: Record<string, number>
}

/** `POST /library/{repo}/mine` — the miners over the clone at one pinned commit (G-677). */
export interface LibraryMineRun {
  repo: string
  commit: string
  miners: string[]
  counts: Record<LibraryMineOutcomeKind, number>
  proposed: LibraryEntry[]
  outcomes: LibraryMineOutcome[]
  files_read: number
  reaches_briefs: boolean
}

/** `POST /library/{repo}/entries`. */
export interface LibraryProposeRequest {
  kind: LibraryKind
  slug: string
  title: string
  statement: string
  work_types?: string[]
  components?: string[]
  characteristic?: string
  check?: string
  parent_class?: string
}

/**
 * One row of `GET /decisions` (F6): a due decision as the person reading it may act on it, with the
 * server's clock. `act` is the row's verb when `can_act`, else `Read`; `signoff` rides on a
 * `signoff_stale` row. src/crb/server/routes/decisions.py `DecisionOut`.
 */
export interface DecisionRowOut {
  repo: string
  kind: string
  key: string
  title: string
  role: 'approver' | 'operator' | 'viewer'
  evidence: string
  reason_code: string
  act: string
  href: string
  can_act: boolean
  signoff: Signoff | null
  due_since: string
  age_s: number
}

/** A repository whose inbox inputs could not be read: the count is incomplete while one is listed. */
export interface DecisionReadError {
  repo: string
  status: number
  code: string
  message: string
}

/** `GET /decisions[?repo=]`. `measured` = the repositories with at least one measured cell. */
export interface DecisionList {
  items: DecisionRowOut[]
  total: number
  as_of: string
  repos: string[]
  measured: string[]
  errors: DecisionReadError[]
}

/** `GET /decisions?count=1` — the nav badge's reading; it never writes the clock. */
export interface DecisionCount {
  total: number
  by_role: Record<string, number>
  errors: string[]
}

// ─── /classes — an organisation's own classes of work (ADR-0026 item 9) ──────────────────

/** What puts a ticket in a class — ticket-time fields only. */
export interface ClassRuleWire {
  words: string[]
  work_item_types: string[]
  components: string[]
  labels: string[]
}

/** One class of an organisation's set (`crb.core.class_sets.OrgClass.to_dict()`). */
export interface OrgClassWire {
  slug: string
  title: string
  definition: string
  parent: string
  rule: ClassRuleWire
  entry_id: string
  entry_repo: string
}

export type ClassSetStatus = 'proposed' | 'signed' | 'revoked'

/** Whether a version routes, the reason code and the reason in words. */
export interface ClassSetRoute {
  routes: boolean
  code: string
  words: string
}

/** A version as `GET /classes` and the acts serve it. */
export interface ClassSetVersionSummary {
  version_id: string
  org: string
  n: number
  digest: string
  version: {
    org: string
    n: number
    classes: OrgClassWire[]
    repos: string[]
    proposed_by: string
    derivation_share: number
    split_seed: string
    based_on: string
  }
  status: ClassSetStatus
  sponsor: string
  sponsor_name: string
  proposed_at: string
  approver: string
  approver_name: string
  signed_at: string
  revoked: { actor: string; reason: string; at: string } | null
  route: ClassSetRoute
  passes?: boolean
}

export interface ClassSetThresholds {
  coverage_min: number
  kappa_min: number
  sample_min: number
  per_class_min: number
  measurable_min: number
  override_rate_max: number
  derivation_share: number
  split_seed: string
}

/** `GET /classes`. */
export interface ClassSetIndex {
  orgs: Array<{ org: string; versions: ClassSetVersionSummary[] }>
  repos: string[]
  thresholds: ClassSetThresholds
  /** The global classes a class may name as its parent, with what each means. */
  global_classes: Array<{ slug: string; definition: string }>
}

/** One line of the validity report. */
export interface ClassSetMeasure {
  name: 'coverage' | 'agreement' | 'stability' | 'ticket_consistency' | 'size_agreement' | 'measurability' | 'override_rate'
  value: number | null
  threshold: string
  n: number
  /** `withheld`: the agreement, from a person part-way through labelling the sample (P-686). */
  state: 'pass' | 'fail' | 'not_applicable' | 'withheld'
  words: string
  detail: Record<string, unknown>
}

/** `GET /classes/{org}/v/{n}`. */
export interface ClassSetVersionDetail extends ClassSetVersionSummary {
  report: {
    version_id: string
    passes: boolean
    size_from_points: boolean
    measures: ClassSetMeasure[]
    routable_cells: Array<{ class: string; size: string }>
    commits: number
    derivation: number
    confirmation: number
  }
  split: Array<{ repo: string; derivation: number; confirmation: number }>
  class_counts: Array<{ class: string; derivation: number; confirmation: number }>
  thresholds: ClassSetThresholds
}

/** `GET /classes/{org}/v/{n}/classes/{slug}` — the page per class. */
export interface ClassPage {
  org: string
  version_id: string
  status: ClassSetStatus
  route: ClassSetRoute
  slug: string
  title: string
  definition: string
  parent: string
  /** What the global parent means (the vocabulary's own definition). */
  parent_definition: string
  rule: ClassRuleWire
  rule_words: string
  entry_id: string
  entry_repo: string
  examples: Array<{ repo: string; sha: string; subject: string; size: string; proxy: boolean }>
  ticket_slots: Array<{ name: string; question: string; kind: string }>
  signed_slots: string[]
  context: Array<{
    repo: string
    entry_id: string
    title: string
    statement: string
    sponsor: string
    sponsor_name: string
    approver: string
    approver_name: string
    signed_at: string
    effect: string
  }>
  library: Array<{ repo: string; work_type: string }>
  sizes: Array<{
    repo: string
    size: string
    confirmation: number
    standard: { arm: string; reading_id: string; signed: boolean; ceiling: boolean } | null
    next: string
  }>
}

/** `GET /classes/{org}/v/{n}/label-queue` — derivation commits, blind to the rule and to others. */
export interface ClassLabelQueue {
  version_id: string
  classes: Array<{ slug: string; title: string; definition: string }>
  items: Array<{
    repo: string
    task_id: string
    message: string
    ticket: { text: string; work_item_type: string; component: string; labels: string[]; points: number | null; source: string } | null
    diff: { source_files: number; test_files: number; churn: number }
    my_label: string
  }>
  labelled_by_me: number
  sample_min: number
  per_class_min: number
  /** The person asking sponsored the version: they are offered nothing to label (P-684). */
  sponsor: boolean
}

/** `POST /classes/{org}/versions`. */
export interface ClassSetProposal {
  repos: string[]
  classes: Array<{ slug: string; title: string; definition: string; parent: string; rule: Partial<ClassRuleWire> }>
}
