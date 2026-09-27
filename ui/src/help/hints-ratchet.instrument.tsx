/**
 * The ratchet's fixtures for the factory, deployment and instrument screens — every route the
 * operator's row and the two later journey steps render, with the API each needs to show data.
 *
 * Navigation
 * ----------
 * What it is:   `INSTRUMENT_SCREENS`: the `SCREENS` entries (route, path, element, api, roles)
 *               for /factory, /posture, /repos, /repos/:name, /runs, /runs/:id,
 *               /tasks/:repo/:taskId, /capability, /routing, /oracle, /learn, /ledger and
 *               /settings, spread into the ratchet's table.
 * What it does: Keeps each screen's fixtures beside the others of its stream rather than in
 *               the ratchet file, so the ratchet stays the mechanism and this file the data.
 *               Every fixture is a populated state (rows, cells, tiles), never an empty or
 *               not-found one: the ratchet must see the elements a reader meets.
 * How:          Plain objects in the shapes the screens' own tests use (`mockApi` keys →
 *               bodies); the roles listed are the ones that change what renders.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints-ratchet.test.tsx (spreads this table into `SCREENS`),
 *               ui/src/test/utils.tsx (`mockApi` reads these keys), ui/src/api/types.ts (the
 *               shapes), ui/src/screens/Factory/FactoryPage.tsx, ui/src/screens/Runs/RunDetailPage.tsx,
 *               ui/src/screens/Capability/CapabilityPage.tsx (the screens rendered)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx
 * Touch when:   a screen of these routes gains a state that renders new elements — add the
 *               fixture that shows it; a route is added to the instrument row — add its entry.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import type { EventSourceLike } from '../api/sse'
import type { Role } from '../api/types'
import { CapabilityPage } from '../screens/Capability/CapabilityPage'
import { FactoryPage } from '../screens/Factory/FactoryPage'
import { IntakePage } from '../screens/Factory/IntakePage'
import { LearnPage } from '../screens/Learn/LearnPage'
import { REGISTER } from '../screens/Learn/register.fixture'
import { LedgerPage } from '../screens/Ledger/LedgerPage'
import { OraclePage } from '../screens/Oracle/OraclePage'
import { PosturePage } from '../screens/Posture/PosturePage'
import { RepoDetail } from '../screens/Repos/RepoDetail'
import { ReposPage } from '../screens/Repos/ReposPage'
import { RoutingPage } from '../screens/Routing/RoutingPage'
import { RunDetailPage } from '../screens/Runs/RunDetailPage'
import { RunsPage } from '../screens/Runs/RunsPage'
import { TaskDetailPage } from '../screens/Runs/TaskDetailPage'
import { SettingsPage } from '../screens/Settings/SettingsPage'

export interface InstrumentScreen {
  route: string
  path: string
  element: ReactElement
  api: Record<string, unknown>
  roles: Role[]
}

// ─── shared fixtures ─────────────────────────────────────────────────────────────────────

/** ADR-0019 — the Posture panel's reading: one task qualified, one refused with its fix. */
const REPO_POSTURE = {
  repo: 'alpha',
  executor: 'docker',
  image_ref: 'crb-sandbox-go:main',
  posture_id: 'pst_' + '1'.repeat(24),
  posture_class: 'docker/readonly/sealed',
  posture: { toolchain: 'go version go1.26.8 linux/arm64' },
  provisioning: { enabled: false },
  qualified: 1,
  total: 2,
  refusals_by_code: [{ code: 'QUAL_ENV_UNLOADABLE', n: 1, message: '', fix: 'the parent cannot load its dependencies offline: switch provisioning on if it is off; if it is on, run crb deps verify and delete any set it names (the next run fetches it again); otherwise fix the module named', doc: 'docs/OPERATOR.md#7a-when-a-posture-is-unqualified' }],
  delta: [],
  stale_reason: '',
}

const REPO = {
  name: 'alpha',
  language: 'python',
  runner: 'pytest',
  url: 'https://github.com/acme/alpha.git',
  clone_path: '/srv/repos/alpha',
  probe: { status: 'ok', run_id: 'a'.repeat(32), checked: '2026-09-13T10:00:00+00:00', detail: '.....\n5 passed in 0.02s' },
  task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 9, gold_failed: 1, unchecked: 2 },
  last_run: { id: 'r'.repeat(32), kind: 'replay', status: 'succeeded', finished: '2026-09-15T10:31:00+00:00' },
  created: '2026-09-13T09:00:00+00:00',
  updated: '2026-09-13T09:00:00+00:00',
  github_full_name: 'acme/alpha',
  config: {
    name: 'alpha',
    language: 'python',
    runner: 'pytest',
    src_prefix: 'src/',
    test_prefix: 'tests/',
    ext: '.py',
    test_mode: 'prefix',
    test_suffix: '',
    belt_scope: 'AFFECTED_DIRS',
    probe: 'tests/test_calc.py',
    url: 'https://github.com/acme/alpha.git',
    layer: '',
    runner_opts: { pythonpath_suffix: '/src', pip: ['pytest'] },
    sandbox_image: '',
    mining: { log_n: 50 },
  },
}
const REPOS = { items: [REPO], total: 1, limit: 50, offset: 0 }
const PROFILE = { repo: 'alpha', n_commits: 20, cells: [{ capability_class: 'bug.fix', size: 'XS', count: 12 }, { capability_class: 'feature.add', size: 'S', count: 8 }], classes: ['bug.fix', 'feature.add'], sizes: ['XS', 'S'] }
const REPO_EVENTS = { items: [{ event_id: 'e1', seq: 1, action: 'repo.updated', actor: 'admin', timestamp: '2026-09-14T10:00:00+00:00', payload: { fields: ['probe'], diff: { probe: ['', 'tests/test_calc.py'] } } }], total: 1, limit: 50, offset: 0 }

const HEALTH = {
  status: 'ok',
  probes: [
    { name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } },
    { name: 'builders', status: 'ok', detail: 'configured: claude_code_cli', data: { anthropic: false, claude_code_cli: true } },
    { name: 'ledger', status: 'ok', detail: 'sqlite', data: { false_q1: 0 } },
  ],
}

const VERSION = { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false }

const INSTALLATION = { id: 77, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: 'https://github.com/organizations/acme/settings/installations/77', suspended: false, permissions: { contents: 'read', metadata: 'read' }, can_deliver: false, recorded_by: 'admin', updated: '2026-09-15T10:00:00+00:00' }
const GITHUB_APP = { configured: true, app_slug: 'crb', api_url: 'https://api.github.com', install_url: 'https://github.com/apps/crb/installations/new', installations: [INSTALLATION, { ...INSTALLATION, id: 78, account_login: 'beta', permissions: { contents: 'write', pull_requests: 'write', metadata: 'read' }, can_deliver: true }] }
const SETTINGS = { sandbox_mode: 'local', ledger_backend: 'sqlite', builders: [{ name: 'claude_code_cli', configured: true }], retention: { worktrees: false, transcripts: false }, oidc_enabled: false, apparatus_version: '2.2', policy_version: 'routing.v1', raw: { builder: { executor: 'docker', egress_network: 'none' }, sandbox: { executor: 'local' } } }
const LEDGER_VERIFY = { rows: 3, ok: true, false_q1_total: 0, broken_at: null }

const CELL = { capability_class: 'bug.fix', size: 'XS', n: 40, clean: 38, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, route: 'deliver', reason: 'n=40 point=0.95 ci_low=0.835 false_q1=0 oracle=0.9', reason_code: 'deliver', cost_usd_mean: 0.34, latency_s_mean: 200, verification_tier: 'automated-pass', apparatus_versions: ['2.2'], belt_set: 'v5', oracle_strength_mean: 0.9, n_tasks: 12, n_builder_red: 2, n_budget: 0, n_protocol: 0, n_harness: 0, n_disqualified: 0, failure_split: { builder_red: 2, lint: 0, budget: 0, protocol: 0, harness: 0, disqualified: 0 }, model_point: 0.95, model_n: 40, model_ci_low: 0.835, model_ci_high: 0.985 }
const MAP = {
  repo: 'alpha',
  by: ['capability_class', 'size'],
  classes: ['bug.fix', 'feature.add'],
  sizes: ['XS', 'S'],
  languages: ['python'],
  models: ['claude-sonnet'],
  cells: [CELL, { ...CELL, capability_class: 'feature.add', size: 'S', n: 12, clean: 9, point: 0.75, ci_low: 0.47, ci_high: 0.91, route: 'calibrate', reason: 'the lower bound sits under the bar', reason_code: 'ci_low_below_bar', verification_tier: 'automated-pass' }],
  summary: { trusted_autonomy_coverage: 0.5, total_cells: 4, measured_cells: 2, deliver_cells: 1, n_total: 52, false_q1_total: 0, apparatus_versions: ['2.2'] },
  policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], min_controls_constructible_share: 0.5, max_controls_escapes: 0, version: 'routing.v1' },
  controls: { measured: true, passed: true, complete: true, constructible: 5, total: 7, share: 0.71, escapes: 0, run_id: 'r'.repeat(32), created: '2026-09-15T10:00:00+00:00', state: 'passed' },
}

const RUN = {
  id: 'r'.repeat(32),
  repo: 'alpha',
  kind: 'replay',
  status: 'running',
  mode: 'sighted',
  builder: 'claude_code_cli',
  model: 'claude-sonnet',
  provider: 'anthropic',
  ladder: ['r1'],
  executor: 'docker',
  timeout: 900,
  pool: 'standard',
  limit: null,
  task_ids: [],
  builder_config: {},
  actor: 'ada',
  created: '2026-09-15T10:00:00+00:00',
  started: '2026-09-15T10:01:00+00:00',
  finished: null,
  cancel_requested: true,
  error: '',
  cost_usd: 1.25,
  apparatus_version: '2.2',
  worker_id: 'worker-1',
  heartbeat: '2026-09-15T10:30:00+00:00',
  counts: { tasks: 10, clean: 8, disqualified: 1, errors: 0, first_pass_clean: 7, rows: 11 },
  progress: { done: 3, total: 10, current_task_id: 'c'.repeat(40) },
}
const RUNS = { items: [RUN, { ...RUN, id: 's'.repeat(32), kind: 'mine', status: 'succeeded', finished: '2026-09-15T10:31:00+00:00', cancel_requested: false }], total: 2, limit: 200, offset: 0 }
const RUN_TASKS = {
  items: [
    { task_id: 'c'.repeat(40), capability_class: 'bug.fix', size: 'XS', pool: 'standard', trials: 1, clean: true, disqualified: false, error: '', belt_set: 'v5', belts: { tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true, repo_lint_clean: null }, cost_usd: 0.4, latency_s: 180, pack_hashes: ['p'.repeat(64)], row_ids: ['row-1'] },
    { task_id: 'd'.repeat(40), capability_class: 'feature.add', size: 'S', pool: 'hard', trials: 2, clean: false, disqualified: false, error: '', belt_set: 'v5', belts: { tests_unmodified: true, target_green: false, no_new_failures: true, source_changed: true, repo_lint_clean: true }, cost_usd: 0.9, latency_s: 260, pack_hashes: ['q'.repeat(64), 'p'.repeat(64)], row_ids: ['row-2', 'row-3'] },
  ],
  total: 2,
  limit: 500,
  offset: 0,
}
const FAILURE_SPLIT = { repo: 'alpha', run_id: 'r'.repeat(32), n: 11, clean: 6, builder_red: 1, budget: 1, protocol: 1, harness: 2, disqualified: 1, outage: 0, lint: 0, rows: 12, point: 0.5455, ci_low: 0.28, ci_high: 0.787, model_n: 7, model_point: 0.8571, model_ci_low: 0.487, model_ci_high: 0.974, cost_known: 8, cost_unknown: 3 }

const ROW = {
  repo: 'alpha',
  task_id: 'c'.repeat(40),
  clean: true,
  capability_class: 'bug.fix',
  size: 'XS',
  language: 'python',
  pool: 'standard',
  mode: 'sighted',
  process_step: 'build',
  builder: 'claude_code_cli',
  model: 'claude-sonnet',
  provider: 'anthropic',
  run_id: 'r'.repeat(32),
  trial: 'r1',
  actor: 'worker-1',
  created: '2026-09-15T10:20:00+00:00',
  tests_unmodified: true,
  target_green: true,
  no_new_failures: true,
  source_changed: true,
  repo_lint_clean: null,
  disqualified: false,
  dq_reason: '',
  error: '',
  new_failures_count: 0,
  attempts: 1,
  cost_usd: 0.4,
  tokens_in: 100,
  tokens_out: 50,
  latency_s: 180,
  oracle_strength: 0.9,
  gold_clean: true,
  evidence_pack_hash: 'p'.repeat(64),
  apparatus_version: '2.2',
  belt_set: 'v5',
  provenance: 'measured',
  labels: {},
  schema: 'crb.grade.v1',
  row_id: 'row-1',
  prev_hash: '0'.repeat(64),
  row_hash: 'h'.repeat(64),
}

const PACK = {
  schema: 'crb.evidence.v1',
  task: { task_id: 'c'.repeat(40), repo: 'alpha', subject: 'Fix the divide-by-zero in calc', authored: '2026-09-01T10:00:00+00:00', test_files: ['tests/test_calc.py'], src_files: ['src/calc.py'], target_tests: ['tests/test_calc.py::test_divide'], belt_scope: ['tests/'], pool: 'standard', src_churn: 4, size: 'XS', capability_class: 'bug.fix', language: 'python', baseline_failing: ['tests/test_calc.py::test_divide'], red_checked: true, gold_clean: true, gold_note: '', labels: {} },
  grade: {
    task_id: 'c'.repeat(40),
    repo: 'alpha',
    mode: 'sighted',
    clean: true,
    tests_unmodified: true,
    target_green: true,
    no_new_failures: true,
    source_changed: true,
    repo_lint_clean: true,
    disqualified: false,
    dq_reason: '',
    error: '',
    note: '',
    new_failures: [],
    tamper_files: [],
    changed_files: ['src/calc.py'],
    diff: { files: ['src/calc.py'], additions: 4, deletions: 0, diff_sha256: 'e'.repeat(64) },
    target_run: { returncode: 0, timed_out: false, parse_error: '', failing: [], duration_s: 1.2, tail: '1 passed' },
    belt_run: { returncode: 0, timed_out: false, parse_error: '', failing: [], duration_s: 3.4, tail: '12 passed' },
    lint_run: { ok: true, detected: 'ruff', steps: [{ tool: 'ruff', rc: 0, timed_out: false, files: ['src/calc.py'], argv: ['ruff', 'check'], tail: 'All checks passed' }], duration_s: 0.3, error: '', note: '' },
    duration_s: 1.5,
    extra: {},
  },
  apparatus: { apparatus_version: '2.2', crb_version: '2.0.0a1', grader: 'crb.core.grade', runner: 'pytest', executor: { kind: 'docker' }, corpus_sha: 'f'.repeat(40), policy_version: 'routing.v1', extra: {} },
  builder: { name: 'claude_code_cli', model: 'claude-sonnet', provider: 'anthropic', mode: 'sighted', attempts: 1, turns: 3, tokens_in: 100, tokens_out: 50, cost_usd: 0.4, latency_s: 180, transcript_ref: '', budget: {}, note: '' },
  run_id: 'r'.repeat(32),
  trial: 'r1',
  actor: 'worker-1',
  created: '2026-09-15T10:20:00+00:00',
  notes: {},
  pack_hash: 'p'.repeat(64),
}
const RETAINED = { row_hash: 'h'.repeat(64), run_id: 'r'.repeat(32), retain_worktrees: false, retain_transcripts: false, patch_available: false, patch_reason: 'the run did not retain worktrees', transcript_available: false, transcript_reason: 'the builder transcript was not retained', diff_sha256: 'e'.repeat(64), extra: {} }
const REVIEW = { review_id: 'rev-1', schema: 'crb.review.v1', grade_row_hash: 'h'.repeat(64), repo: 'alpha', task_id: 'c'.repeat(40), subject: 'Fix the divide-by-zero in calc', grade_clean: true, reviewer: 'ada', verdict: 'ok', findings: [], mergeable: true, statement: 'Read the diff; the fix is minimal.', patch_sha256_reviewed: 'e'.repeat(64), evidence_pack_hash: 'p'.repeat(64), apparatus_version: '2.2', created: '2026-09-15T11:00:00+00:00' }
const REVIEWS = { items: [REVIEW], total: 1, limit: 200, offset: 0 }

const TASK = {
  task_id: 'c'.repeat(40),
  repo: 'alpha',
  subject: 'Fix the divide-by-zero in calc',
  authored: '2026-09-01T10:00:00+00:00',
  test_files: ['tests/test_calc.py'],
  src_files: ['src/calc.py'],
  target_tests: ['tests/test_calc.py::test_divide'],
  belt_scope: ['tests/test_calc.py'],
  pool: 'standard',
  src_churn: 12,
  size: 'XS',
  capability_class: 'bug.fix',
  language: 'python',
  baseline_failing: [],
  red_checked: true,
  gold_clean: true,
  gold_note: '',
  labels: {},
}
const TASKS = { items: [TASK, { ...TASK, task_id: 'd'.repeat(40), subject: 'Add multiply', capability_class: 'feature.add', size: 'S', pool: 'hard', gold_clean: null }], total: 2, limit: 500, offset: 0 }

// ─── /factory ────────────────────────────────────────────────────────────────────────────

const NO_ROUTE = { route: '', reason_code: '', reason: '', n: 0, point: 0, ci_low: 0, ci_high: 0, apparatus_versions: [], deliverable: false }
const DELIVER = { route: 'deliver', reason_code: 'deliver', reason: 'ok', n: 40, point: 0.95, ci_low: 0.835, ci_high: 0.985, apparatus_versions: ['2.2'], deliverable: true }
const LINKED = { can_deliver: true, reason_code: 'ok' as const, reason: '', full_name: 'acme/alpha', default_branch: 'main', installation_id: 77, account_login: 'acme' }
const UNTOUCHED = { outcome_reason: '', refusal: null, error: '', task_id: '', run_id: '', pack_hash: '', row_hash: '' }
const BACKLOG = {
  repo: 'alpha',
  hash: 'a'.repeat(64),
  frozen_at: '2026-09-15T10:00:00+00:00',
  delivery: LINKED,
  items: [
    { id: 'I-1', title: 'Multiply', kind: 'code', capability_class: 'bug.fix', size: 'XS', level: 'L1', depends_on: [], structural_facts: ['reproduction: x'], has_authored_test: true, description: 'calc needs multiply' },
    { id: 'I-2', title: 'Divide', kind: 'code', capability_class: 'feature.add', size: 'S', level: 'L1', depends_on: ['I-1'], structural_facts: [], has_authored_test: false, description: '' },
  ],
}
const FACTORY_TASKS = [
  { id: 'I-1', title: 'Multiply', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'accepted', dor_gaps: [], route_hint: 'build', red_proof: true, build_status: 'clean', pr_url: 'https://github.invalid/acme/alpha/pull/7', review_verdict: 'accept', last_event: 'item.outcome', cell_route: DELIVER, ...UNTOUCHED, task_id: 'c'.repeat(40), run_id: 'r'.repeat(32), pack_hash: 'p'.repeat(64), row_hash: 'h'.repeat(64) },
  { id: 'I-2', title: 'Divide', capability_class: 'feature.add', size: 'S', kind: 'code', status: 'not_ready', dor_gaps: ['method_path', 'response_shape'], route_hint: 'human', red_proof: null, build_status: 'not_started', pr_url: null, review_verdict: null, last_event: 'readiness.blocked', cell_route: NO_ROUTE, ...UNTOUCHED, refusal: { step: 'readiness', reason: 'two structural gaps are unsigned', reason_code: '', measured_route: '' } },
]
const INTAKE = {
  repo: 'alpha',
  listener: { enabled: true, column: 'Ready for manufacture', switched_by: 'Ada', switched_at: '2026-09-22T09:00:00Z', since: '2026-09-22T09:00:00Z' },
  connection: { tracker: 'ado', url: 'https://dev.azure.invalid/contoso', project: 'Widgets', column: 'Ready for manufacture', poll_s: 300, outcome_map: { merged: 'Done' }, configured: true, credential_set: true, credential_fingerprint: 'AB12' },
  last_poll: { repo: 'alpha', column: 'Ready for manufacture', seen: 2, read: 2, skipped: 0, commented: 2, registered: 1, queued: 0, stopped: '', detail: '', advice: '', at: '2026-09-22T09:05:00Z' },
  rows: [
    {
      key: '4711', title: 'Fix the crash when the cart is empty', url: 'https://dev.azure.invalid/contoso/Widgets/_workitems/edit/4711', revision: '3',
      label: 'crb:queued', state: 'Ready for manufacture', item_id: 'ado-4711', item_url: '/factory?repo=alpha&item=ado-4711',
      feedback: 'Commit Replay Bench: this ticket is ready to manufacture.', open_questions: [],
      capability_class: 'bug.fix', confidence: 0.67, size: 'S', registered: true, is_evolution: false, supersedes: '',
      cell_route: DELIVER, read_at: '2026-09-22T09:05:00Z', stopped: '', stopped_advice: '',
    },
    {
      key: '4712', title: 'Add a POST /health route', url: 'https://dev.azure.invalid/contoso/Widgets/_workitems/edit/4712', revision: '1',
      label: 'crb:needs-info', state: 'Ready for manufacture', item_id: 'ado-4712', item_url: '/factory?repo=alpha&item=ado-4712',
      feedback: 'Commit Replay Bench: this ticket needs more information before anything is built.',
      open_questions: [{ ref: 'ado-4712::backend.route.add::response_shape', severity: 'blocking', reason: 'What is the response shape (status code, body fields and types)?' }],
      capability_class: 'backend.route.add', confidence: 0.5, size: 'M', registered: false, is_evolution: false, supersedes: '',
      cell_route: NO_ROUTE, read_at: '2026-09-22T09:05:00Z', stopped: '', stopped_advice: '',
    },
    {
      // ADR-0022 — a ready draft waiting for an operator: the Register act and its author line
      key: '4714', title: 'Fix the rounding on the invoice total', url: 'https://dev.azure.invalid/contoso/Widgets/_workitems/edit/4714', revision: '5',
      label: 'crb:ready', state: 'Ready for manufacture', item_id: 'ado-4714', item_url: '/factory?repo=alpha&item=ado-4714',
      feedback: 'Commit Replay Bench: this ticket is ready to manufacture.', open_questions: [],
      capability_class: 'bug.fix', confidence: 0.67, size: 'S', registered: false, is_evolution: false, supersedes: '',
      cell_route: DELIVER, read_at: '2026-09-22T09:05:00Z', stopped: '', stopped_advice: '',
      awaiting_approval: true, author: 'ada@contoso.invalid',
    },
  ],
}

const CATALOGUE = {
  classes: [
    { capability_class: 'feature.add', slots: [{ name: 'method_path', question: 'Which HTTP method and path does the change add?', kind: 'structural' }, { name: 'response_shape', question: 'What shape does the response have?', kind: 'structural' }] },
    { capability_class: 'bug.fix', slots: [{ name: 'reproduction', question: 'How is the bug reproduced?', kind: 'structural' }] },
  ],
  sizes: ['XS', 'S', 'M', 'L', 'XL'],
  kinds: ['code', 'infra', 'operator'],
  levels: ['L1', 'L2', 'L3'],
}
const FACTORY_RUNS = { items: [{ ...RUN, kind: 'factory', counts: { ...RUN.counts, detail: { items: 2, accepted: 1, by_status: { accepted: 1, not_ready: 1 } } } }], total: 1, limit: 10, offset: 0 }

// ─── routing / oracle / learn / ledger / settings ─────────────────────────────────────────

const CONTROLS_VERDICT = { measured: true, passed: false, complete: true, constructible: 5, total: 7, share: 0.71, escapes: 1, run_id: 'c0ffee0000000000000000000000cafe', created: '2026-08-26T09:20:00Z', state: 'escaped' }
const DECISION = {
  route: 'human',
  reason: 'controls_escapes: 1 measurement control(s) graded clean on this repo',
  reason_code: 'controls_escapes',
  cell: { process_step: 'replay', capability_class: 'bug.fix', size: 'S', language: 'python', builder: 'claude_code_cli', model: 'claude-sonnet', provider: 'anthropic' },
  n: 40,
  point: 0.95,
  ci_low: 0.835,
  ci_high: 0.987,
  false_q1: 0,
  oracle_strength: 0.9,
  policy_version: 'routing.v1',
  verification_tier: 'automated-pass',
  apparatus_versions: ['2.2'],
  belt_sets: ['v5'],
  controls_policy: 'controls-gate.v1',
  controls: CONTROLS_VERDICT,
  model_n: 40,
  model_point: 0.95,
  model_ci_low: 0.835,
  model_ci_high: 0.987,
  failure_split: { builder_red: 2, budget: 0, protocol: 0, harness: 0, disqualified: 0 },
}
const ROUTES = {
  repo: 'alpha',
  policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1', min_controls_share: 0.5, max_controls_escapes: 0, controls_version: 'controls-gate.v1' },
  controls: CONTROLS_VERDICT,
  decisions: [DECISION, { ...DECISION, route: 'calibrate', reason: 'n=4 < 10', reason_code: 'n_below_min', cell: { ...DECISION.cell, capability_class: 'feature.add', size: 'M' }, n: 4, point: 0.5, ci_low: 0.15 }],
}

const ORACLE = {
  repo: 'alpha',
  policy: { autoship_floor: 0.8, adequate_floor: 0.5, version: 'adequacy.v1' },
  tasks: [
    { task_id: 'c'.repeat(40), capability_class: 'bug.fix', size: 'S', strength: 0.9, band: 'strong', mutants: 10, killed: 9, gate: 'auto_ship' },
    { task_id: 'd'.repeat(40), capability_class: 'feature.add', size: 'M', strength: 0.4, band: 'weak', mutants: 10, killed: 4, gate: 'needs_human' },
  ],
  cells: [{ capability_class: 'bug.fix', size: 'S', n: 1, strength_mean: 0.9, band: 'strong', gate: 'auto_ship' }],
  apparatus_versions: ['2.2'],
}
const CONTROL_ROW = { task_id: 'c'.repeat(40), repo: 'alpha', control: 'noop', expected: 'red', observed: 'red', verdict: 'ok', note: '', duration_s: 3.2 }
const CONTROLS_REPORT = {
  schema: 'crb.controls.v1',
  apparatus: {},
  n_tasks: 2,
  n_rows: 3,
  violations: 0,
  escapes: 1,
  not_constructible: 0,
  skipped: 0,
  passed: false,
  escape_rows: [{ ...CONTROL_ROW, control: 'stub', observed: 'green', verdict: 'ESCAPE', note: 'the tests could not tell a stub from the fix' }],
  rows: [CONTROL_ROW, { ...CONTROL_ROW, control: 'stub', observed: 'green', verdict: 'ESCAPE', note: 'the tests could not tell a stub from the fix' }, { ...CONTROL_ROW, control: 'gold', verdict: 'VIOLATION', note: 'gold graded red' }],
  run_id: 'c0ffee0000000000000000000000cafe',
  reported_at: '2026-08-26T09:20:00Z',
  verdict: CONTROLS_VERDICT,
}

const REFUSALS = {
  repo: 'alpha',
  rows_total: 40,
  rows_protocol: 3,
  protocol_share: 0.075,
  share: { rows_total: 40, rows_protocol: 3, share: 0.075, ci_low: 0.026, ci_high: 0.2 },
  by_apparatus: [{ apparatus_version: '2.2', rows_total: 40, rows_protocol: 3, share: 0.075, ci_low: 0.026, ci_high: 0.2 }],
  cost_usd: 1.2,
  minutes: 14,
  unparsed: 0,
  apparatus_versions: ['2.2'],
  groups: [{ group_id: 'g1', prefix: 'network', reason: 'egress refused', shape: 'curl https://…', truncated: false, n: 3, cost_usd: 1.2, verdict: 'unsure' }],
  note: '',
}
const STRENGTHEN = {
  repo: 'alpha',
  threshold: 0.8,
  cells_flagged: [{ capability_class: 'feature.add', size: 'M' }],
  cells_without_scores: [{ capability_class: 'bug.fix', size: 'L' }],
  items: [{ id: 'S-1', title: 'Strengthen the divide tests', description: 'kill the surviving mutants', capability_class: 'test.add', size: 'S', labels: { cell: 'feature.add · M', reason_code: 'oracle_weak', oracle_strength: '0.40', threshold: '0.80', escaped: '1' } }],
  note: '',
}
const REMEASURE = {
  repo: 'alpha',
  current_apparatus: '2.2',
  min_n: 10,
  rows_total: 40,
  rows_stale: 12,
  cells: [{ label: 'bug.fix · XS', capability_class: 'bug.fix', size: 'XS', n_stale: 12, stale_versions: ['2.1'], n_current: 4, n_needed: 6, est_cost_usd: 2.4, cost_known: true, requests: [{ kind: 'replay', limit: 6 }] }],
  up_to_date: [],
  summary: { cells_stale: 1, n_needed_total: 6, est_cost_usd_total: 2.4, est_minutes_total: 20, cost_known_cells: 1 },
  note: '',
}

const GRADES = { items: [ROW, { ...ROW, row_id: 'row-2', row_hash: 'i'.repeat(64), clean: false, target_green: false, provenance: 'imported:census' }], total: 2, limit: 100, offset: 0 }

const USERS = { items: [{ id: 'u1', username: 'ada', display_name: 'Ada', email: 'ada@example.org', role: 'admin', issuer: 'local', active: true, created: '2026-09-01T10:00:00+00:00' }], total: 1, limit: 50, offset: 0 }
const SECRETS = { items: [{ name: 'claude_code_oauth_token', present: true, fingerprint: 'GOOD', set_at: '2026-09-13T10:00:00+00:00', set_by: 'root' }], secrets_dir: '/srv/crb/secrets' }

// ─── the table ───────────────────────────────────────────────────────────────────────────

export const INSTRUMENT_SCREENS: Record<string, InstrumentScreen> = {
  '/factory': {
    route: '/factory?repo=alpha',
    path: '/factory',
    element: <FactoryPage />,
    api: {
      'GET /repos': REPOS,
      'GET /factory/alpha/backlog': BACKLOG,
      'GET /factory/alpha/tasks': FACTORY_TASKS,
      'GET /factory/catalogue': CATALOGUE,
      'GET /health': HEALTH,
      'GET /version': VERSION,
      'GET /capability-map': MAP,
      'GET /runs': FACTORY_RUNS,
    },
    roles: ['viewer', 'operator', 'approver'],
  },
  '/factory/intake': {
    route: '/factory/intake?repo=alpha',
    path: '/factory/intake',
    element: <IntakePage />,
    api: {
      'GET /repos': REPOS,
      'GET /factory/alpha/intake': INTAKE,
    },
    roles: ['viewer', 'operator'],
  },
  '/posture': {
    route: '/posture',
    path: '/posture',
    element: <PosturePage />,
    api: { 'GET /version': VERSION, 'GET /health': { ...HEALTH, probes: [...HEALTH.probes, { name: 'worker', status: 'degraded', detail: 'no worker has checked in', data: {} }, { name: 'toolchains', status: 'ok', detail: 'python 3.12', data: {} }, { name: 'append_only', status: 'ok', detail: 'triggers present', data: {} }] }, 'GET /settings': SETTINGS, 'GET /ledger/verify': LEDGER_VERIFY, 'GET /github/app': GITHUB_APP },
    roles: ['viewer', 'admin'],
  },
  '/repos': {
    route: '/repos',
    path: '/repos',
    element: <ReposPage />,
    api: { 'GET /repos': REPOS },
    roles: ['viewer', 'operator'],
  },
  '/repos/:name': {
    route: '/repos/alpha',
    path: '/repos/:name',
    element: <RepoDetail />,
    api: { 'GET /repos/alpha': REPO, 'GET /repos/alpha/profile': PROFILE, 'GET /repos/alpha/tasks': TASKS, 'GET /repos/alpha/events': REPO_EVENTS, 'GET /repos/alpha/posture': REPO_POSTURE, 'GET /health': HEALTH, 'GET /repos': REPOS },
    roles: ['viewer', 'operator'],
  },
  '/runs': {
    route: '/runs',
    path: '/runs',
    element: <RunsPage />,
    api: { 'GET /runs': RUNS, 'GET /repos': REPOS },
    roles: ['viewer', 'operator'],
  },
  '/runs/:id': {
    route: `/runs/${'r'.repeat(32)}`,
    path: '/runs/:id',
    element: <RunDetailPage eventSourceFactory={() => new StubEventSource()} />,
    api: { [`GET /runs/${'r'.repeat(32)}`]: RUN, [`GET /runs/${'r'.repeat(32)}/tasks`]: RUN_TASKS, 'GET /failure-split': FAILURE_SPLIT, 'GET /health': { ...HEALTH, probes: [...HEALTH.probes, { name: 'worker', status: 'ok', detail: 'worker-1 alive', data: { stale_after_s: 120, queued: 0 } }] } },
    roles: ['viewer', 'operator'],
  },
  '/capability': {
    route: '/capability?repo=alpha',
    path: '/capability',
    element: <CapabilityPage />,
    api: { 'GET /capability-map': MAP, 'GET /repos': REPOS },
    roles: ['viewer', 'operator'],
  },
  '/routing': {
    route: '/routing?repo=alpha',
    path: '/routing',
    element: <RoutingPage />,
    api: { 'GET /routes': ROUTES, 'GET /repos': REPOS },
    roles: ['viewer'],
  },
  '/oracle': {
    route: '/oracle?repo=alpha',
    path: '/oracle',
    element: <OraclePage />,
    api: { 'GET /oracle/alpha': ORACLE, 'GET /oracle/alpha/controls': CONTROLS_REPORT, 'GET /repos': REPOS },
    roles: ['viewer'],
  },
  '/learn': {
    route: '/learn?repo=alpha',
    path: '/learn',
    element: <LearnPage />,
    api: { 'GET /learn/register': REGISTER, 'GET /learn/refusals': REFUSALS, 'GET /learn/strengthen': STRENGTHEN, 'GET /learn/remeasure': REMEASURE, 'GET /repos': REPOS },
    // a viewer sees the register and no control; an operator gets the switch, revert and register
    roles: ['viewer', 'operator'],
  },
  '/ledger': {
    route: '/ledger?repo=alpha',
    path: '/ledger',
    element: <LedgerPage />,
    api: { 'GET /ledger/verify': LEDGER_VERIFY, 'GET /grades': GRADES, 'GET /repos': REPOS },
    roles: ['viewer', 'operator'],
  },
  '/settings': {
    route: '/settings',
    path: '/settings',
    element: <SettingsPage />,
    api: { 'GET /health': { ...HEALTH, probes: [...HEALTH.probes, { name: 'worker', status: 'ok', detail: 'worker-1 alive', data: {} }] }, 'GET /version': VERSION, 'GET /settings': SETTINGS, 'GET /users': USERS, 'GET /settings/secrets': SECRETS, 'GET /github/app': GITHUB_APP },
    roles: ['viewer', 'operator', 'admin'],
  },
  '/tasks/:repo/:taskId': {
    route: `/tasks/alpha/${'c'.repeat(40)}`,
    path: '/tasks/:repo/:taskId',
    element: <TaskDetailPage />,
    api: { [`GET /tasks/alpha/${'c'.repeat(40)}`]: { spec: TASK, grades: [ROW, { ...ROW, row_id: 'row-2', row_hash: 'i'.repeat(64), trial: 'r2', clean: false, target_green: false, evidence_pack_hash: '' }] }, 'GET /reviews': REVIEWS },
    roles: ['viewer'],
  },
}

/** An EventSource that never connects: the live log renders its idle state and the rows the run already has. */
class StubEventSource implements EventSourceLike {
  onerror: ((ev: Event) => void) | null = null
  onopen: ((ev: Event) => void) | null = null
  addEventListener() {}
  close() {}
}

const DRAWER_API = { [`GET /evidence/${'p'.repeat(64)}`]: { pack: PACK, verified: true }, [`GET /grades/${'h'.repeat(64)}/retained`]: RETAINED, 'GET /reviews': REVIEWS, [`GET /tasks/alpha/${'c'.repeat(40)}`]: { spec: TASK, grades: [ROW] } }

/** The deeper states of a route the one-entry table cannot reach: a tab, an open dialog, an open drawer. */
export const INSTRUMENT_VARIANTS: Array<InstrumentScreen & { name: string; open?: (container: HTMLElement) => Promise<void> | void; minHints?: number }> = [
  { name: '/repos/:name tab=profile', route: '/repos/alpha?tab=profile', path: '/repos/:name', element: <RepoDetail />, api: INSTRUMENT_SCREENS['/repos/:name']!.api, roles: ['viewer'] },
  { name: '/repos/:name tab=tasks', route: '/repos/alpha?tab=tasks', path: '/repos/:name', element: <RepoDetail />, api: INSTRUMENT_SCREENS['/repos/:name']!.api, roles: ['viewer'] },
  { name: '/repos/:name tab=config', route: '/repos/alpha?tab=config', path: '/repos/:name', element: <RepoDetail />, api: INSTRUMENT_SCREENS['/repos/:name']!.api, roles: ['viewer', 'operator'] },
  {
    name: '/capability + open cell detail',
    route: '/capability?repo=alpha',
    path: '/capability',
    element: <CapabilityPage />,
    api: { 'GET /capability-map': MAP, 'GET /repos': REPOS },
    roles: ['viewer'],
    open: async () => {
      await userEvent.click((await screen.findAllByTestId('cell-measured'))[0]!)
      await screen.findByTestId('tile-point')
    },
    minHints: 40,
  },
  {
    name: '/settings as admin (configuration + users)',
    route: '/settings',
    path: '/settings',
    element: <SettingsPage />,
    api: INSTRUMENT_SCREENS['/settings']!.api,
    roles: ['admin'],
    open: async () => {
      await screen.findByTestId('settings-sandbox-mode')
    },
    minHints: 34,
  },
  {
    name: '/repos + Add a repository dialog',
    route: '/repos',
    path: '/repos',
    element: <ReposPage />,
    api: INSTRUMENT_SCREENS['/repos']!.api,
    roles: ['operator'],
    open: async () => userEvent.click((await screen.findAllByRole('button', { name: 'Add repo' }))[0]!),
    minHints: 20,
  },
  {
    name: '/runs + Start a run dialog',
    route: '/runs?new=replay',
    path: '/runs',
    element: <RunsPage />,
    api: { ...INSTRUMENT_SCREENS['/runs']!.api, 'GET /settings': SETTINGS },
    roles: ['operator'],
    open: async () => {
      await screen.findByRole('dialog')
      await userEvent.click(screen.getByRole('button', { name: 'Add rung' }))
    },
    minHints: 30,
  },
  {
    name: '/runs/:id + evidence drawer (Pack tab)',
    route: `/runs/${'r'.repeat(32)}`,
    path: '/runs/:id',
    element: <RunDetailPage eventSourceFactory={() => new StubEventSource()} />,
    api: { ...INSTRUMENT_SCREENS['/runs/:id']!.api, ...DRAWER_API },
    roles: ['viewer'],
    open: async () => {
      await userEvent.click((await screen.findAllByRole('button', { name: /^r1 /u }))[0]!)
      await screen.findByTestId('pack-verified')
    },
    minHints: 40,
  },
  {
    name: '/runs/:id + evidence drawer (Patch and Review tabs)',
    route: `/runs/${'r'.repeat(32)}`,
    path: '/runs/:id',
    element: <RunDetailPage eventSourceFactory={() => new StubEventSource()} />,
    api: { ...INSTRUMENT_SCREENS['/runs/:id']!.api, ...DRAWER_API },
    roles: ['operator'],
    open: async () => {
      await userEvent.click((await screen.findAllByRole('button', { name: /^r1 /u }))[0]!)
      await screen.findByTestId('pack-verified')
      await userEvent.click(screen.getByTestId('tab-patch'))
      await screen.findByTestId('patch-unavailable')
      await userEvent.click(screen.getByTestId('tab-review'))
      await screen.findByTestId('review-panel')
      await userEvent.click(screen.getByTestId('finding-chip-defect'))
    },
    minHints: 40,
  },
]
