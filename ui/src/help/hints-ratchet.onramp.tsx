/**
 * The on-ramp routes' entries for the hint ratchet — fixtures under which Home, Connect (the
 * list, the walk, Measure), Baseline, Decisions and Sign-off render every element they have.
 *
 * Navigation
 * ----------
 * What it is:   `ONRAMP_SCREENS`: one `{ route, path, element, api, roles }` per on-ramp route,
 *               spread into the ratchet's `SCREENS` table.
 * What it does: Gives the ratchet a data state for each screen that is neither empty nor
 *               not-found — a measured repository with a deliver cell and a human cell, a
 *               stale sign-off, a running measurement, a chosen cell with refusals and an
 *               active attestation — so every hinted element the screen can render is on the
 *               page and counted, and the `MIN_HINTS` floor means something. The roles are
 *               the ones that change what renders (`can()` branches on each screen).
 * How:          Plain fixture objects in the shapes the screen tests use (`mockApi` tables),
 *               kept beside the ratchet rather than imported from the screens' own test files
 *               (importing a test file would run its suite twice). One stream owns this file;
 *               the instrument screens add their own sidecar the same way.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints-ratchet.test.tsx (spreads these into `SCREENS`),
 *               ui/src/test/utils.tsx (`envelope`, `json` — the fixture idiom),
 *               ui/src/screens/Home/HomePage.tsx, ui/src/screens/Connect/ConnectPage.tsx,
 *               ui/src/screens/Connect/MeasurePage.tsx, ui/src/screens/Results/ResultsPage.tsx,
 *               ui/src/screens/Decisions/DecisionsPage.tsx, ui/src/screens/Signoff/SignoffPage.tsx
 *               (the screens rendered under these fixtures)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx
 * Touch when:   an on-ramp screen gains a data state that renders a new element — extend the
 *               fixture so the element is on the page and the ratchet sees it.
 */
import type { ReactElement } from 'react'
import type { Role } from '../api/types'
import { ConnectPage, ConnectRepoPage } from '../screens/Connect/ConnectPage'
import { MeasurePage } from '../screens/Connect/MeasurePage'
import { DecisionsPage } from '../screens/Decisions/DecisionsPage'
import { HomePage } from '../screens/Home/HomePage'
import { ResultsPage } from '../screens/Results/ResultsPage'
import { SignoffPage } from '../screens/Signoff/SignoffPage'
import { envelope, json } from '../test/utils'

/** The shape the ratchet's `SCREENS` table takes (structurally the ratchet's own `ScreenEntry`). */
export interface OnrampScreen {
  route: string
  path: string
  element: ReactElement
  api: Record<string, unknown>
  roles: Role[]
}

const REPO = {
  name: 'alpha',
  language: 'python',
  runner: 'pytest',
  url: 'https://github.com/acme/alpha',
  clone_path: '',
  probe: { status: 'ok', run_id: 'r1', checked: '2026-09-17T00:00:00Z', detail: 'pytest 8' },
  task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 },
  last_run: null,
  created: '2026-09-17T00:00:00Z',
  updated: '2026-09-17T00:00:00Z',
  config: {},
}
const BETA = { ...REPO, name: 'beta', task_counts: { total: 0, standard: 0, hard: 0, gold_clean: 0, gold_failed: 0, unchecked: 0 }, updated: '2026-09-10T00:00:00Z' }
const CELL = { capability_class: 'bug.fix', size: 'XS', n: 22, n_tasks: 9, clean: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, route: 'deliver', reason: 'n=22', reason_code: 'deliver', verification_tier: 'automated-pass', apparatus_versions: ['2.2'], cost_usd_mean: 0.34, latency_s_mean: 200 }
const HUMAN = { ...CELL, size: 'S', n: 13, n_tasks: 11, clean: 11, point: 0.846, ci_low: 0.578, ci_high: 0.957, route: 'human', reason: 'oracle strength 0.76 < 0.80', reason_code: 'oracle_weak' }
const GRANULAR = { ...CELL, size: 'XL', n: 0, clean: 0, point: 0, ci_low: 0, ci_high: 0, route: 'granularize', reason: 'split first', reason_code: 'granularize' }
const POLICY = { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' }
const MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: ['bug.fix'], sizes: ['XS', 'S'], languages: [], models: [], cells: [CELL, HUMAN, GRANULAR], summary: { trusted_autonomy_coverage: 0.5, total_cells: 2, measured_cells: 2, deliver_cells: 1, n_total: 35, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: POLICY }
const CONTROLS = { schema: 'x', apparatus: { apparatus_version: '2.2', controls_version: 'controls.v3' }, n_tasks: 32, n_rows: 224, violations: 0, escapes: 0, not_constructible: 43, skipped: 0, passed: true, escape_rows: [], rows: [], verdict: { measured: true, passed: true, complete: true, constructible: 181, total: 224, share: 0.81, escapes: 0, run_id: 'r', created: 'x', state: 'passed' } }
const ORACLE = { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }, { task_id: 't2', strength: 0.7 }], cells: [], apparatus_versions: ['2.2'] }
const RUN = {
  id: 'r9',
  repo: 'alpha',
  kind: 'replay',
  status: 'running',
  mode: 'sighted',
  builder: 'fixture',
  model: 'gold',
  provider: '',
  ladder: [],
  executor: 'docker',
  timeout: 600,
  pool: '',
  limit: 10,
  task_ids: [],
  builder_config: {},
  actor: 'op',
  created: '2026-09-19T10:00:00Z',
  started: '2026-09-19T10:00:20Z',
  finished: null,
  cancel_requested: false,
  error: '',
  cost_usd: 0.42,
  apparatus_version: '2.2',
  counts: { tasks: 2, clean: 2, disqualified: 0, errors: 0, first_pass_clean: 2, rows: 2 },
  progress: { done: 2, total: 10, current_task_id: 't3' },
}
/** A stale sign-off on another cell, so the deliver cell stays "sign-off due" beside it. */
const STALE = { id: 's1', repo: 'alpha', cell: { capability_class: 'bug.fix', size: 'M' }, revoked: false, active: false, stale: true, apparatus_current: '2.2', approver: 'u9', approver_name: 'Grace', created: '2026-09-01T10:00:00Z', evidence: { n: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, apparatus_versions: ['2.1'] } }
const HEALTH = { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: 'docker not reachable', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: 'configured: claude_code_cli', data: { anthropic: false, claude_code_cli: true } }] }

// ── sign-off: a chosen cell with refusals, an accepted row and an active attestation
const ROW = 'c'.repeat(64)
const ESCAPED = { measured: true, passed: true, complete: true, constructible: 12, total: 14, share: 0.857, escapes: 1, run_id: '0'.repeat(32), created: '2026-08-26T09:20:00+00:00', state: 'escaped' }
const SIGNOFF_POLICY = { policy_version: 'signoff-policy.v2', relaxed: false, non_overridable: ['false_q1', 'oracle_unmeasured', 'attestation_missing'], bounds: { n_min: [1, 10000] }, n_min: 10, require_route_deliver: true, require_controls_passed: true, max_controls_escapes: 0, min_constructible_share: 0.5, min_oracle_strength: 0.8, require_oracle_measured: true, require_attestation: true }
const SIGNOFF_CELL = { capability_class: 'bug.fix', size: 'S', n: 40, clean: 38, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, cost_usd_mean: 0.01, latency_s_mean: 30, oracle_strength_mean: null, route: 'human', reason: 'controls_escapes: 1 measurement control(s) graded clean on this repo', reason_code: 'controls_escapes', verification_tier: 'automated-pass', apparatus_versions: ['2.1'], n_builder_red: 2, n_budget: 0, n_protocol: 0, n_harness: 0, n_disqualified: 0, model_n: 40, model_point: 0.95, model_ci_low: 0.835, model_ci_high: 0.985, failure_split: { builder_red: 2, budget: 0, protocol: 0, harness: 0, disqualified: 0 } }
const SIGNOFF_MAP = { repo: 'r', by: ['capability_class', 'size'], classes: ['bug.fix'], sizes: ['S'], languages: [], models: [], cells: [SIGNOFF_CELL], summary: { trusted_autonomy_coverage: 0, total_cells: 1, measured_cells: 1, deliver_cells: 0, n_total: 40, false_q1_total: 0, apparatus_versions: ['2.1'] }, policy: { ...POLICY, min_controls_share: 0.5, max_controls_escapes: 0, controls_version: 'controls-gate.v1' }, controls: ESCAPED }
const PREVIEW = {
  repo: 'r',
  cell: { process_step: '*', capability_class: 'bug.fix', size: 'S', language: '*', builder: '*', model: '*', provider: '*' },
  policy: SIGNOFF_POLICY,
  evidence: { measured: true, n: 40, clean: 38, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, oracle_strength: 0.5778, oracle: { strength: 0.5778, scored: 3, tasks: 4 }, apparatus_versions: ['2.1'], belt_sets: ['v4'], model_n: 40, model_point: 0.95, failure_split: { builder_red: 2, budget: 0, protocol: 0, harness: 0, disqualified: 0 } },
  route: { route: 'human', reason: 'controls_escapes: 1 measurement control(s) graded clean on this repo', reason_code: 'controls_escapes' },
  controls: ESCAPED,
  refusals: [
    { code: 'controls_escapes', message: '1 measurement control(s) graded clean on this repo > max_controls_escapes=0', threshold: 0, observed: 1, overridable: true },
    { code: 'attestation_missing', message: 'the approver must name one accepted (clean) row of this cell whose diff they have read, with a statement', threshold: 'reviewed_row_hash + statement', observed: '', overridable: false },
  ],
  signable: false,
  would_record: {},
  accepted_rows: [{ row_hash: ROW, row_id: 'r1', task_id: 'a'.repeat(40), subject: 'fix: task 4', created: '2026-08-30T09:03:00+00:00', run_id: 'c'.repeat(32), trial: 'r1', builder: 'editblock', model: 'gpt-oss-120b', evidence_pack_hash: 'e'.repeat(64) }],
  attestation: null,
}
const SIGNED = {
  id: 's1',
  repo: 'r',
  cell: { process_step: '*', capability_class: 'bug.fix', size: 'S', language: '*', builder: '*', model: '*', provider: '*' },
  note: 'reviewed',
  approver: 'u1',
  created: '2026-09-14T10:00:00+00:00',
  revoked: false,
  revoked_by: null,
  revoked_at: null,
  active: true,
  stale: false,
  apparatus_current: '2.1',
  current_false_q1: 0,
  prev_hash: '0'.repeat(64),
  row_hash: 'a'.repeat(64),
  schema: 'crb.signoff.v2',
  evidence: { n: 40, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, apparatus_versions: ['2.1'], oracle_strength: 0.9 },
  policy_version: 'signoff-policy.v2',
  policy_thresholds: SIGNOFF_POLICY,
  route: { route: 'deliver', reason: 'n=40 point=0.950 ci_low=0.835 false_q1=0', reason_code: 'deliver' },
  controls: { verdict: 'passed', run_id: '5'.repeat(32), k: 12, total: 14, escapes: 0, created: '2026-09-10T09:00:00+00:00' },
  attestation: { reviewed_task_id: 'a'.repeat(40), reviewed_row_hash: ROW, statement: 'I read the diff.', at: '2026-09-14T10:00:00+00:00', subject: 'fix: task 4' },
}

const ALPHA_WALK = {
  'GET /repos/alpha': { ...REPO, last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null } },
  'GET /oracle/alpha': ORACLE,
  'GET /oracle/alpha/controls': CONTROLS,
  'GET /capability-map': MAP,
  'GET /runs/r9': RUN,
}

/** The on-ramp routes, keyed by App.tsx pattern. */
export const ONRAMP_SCREENS: Record<string, OnrampScreen> = {
  '/home': {
    route: '/home',
    path: '/home',
    element: <HomePage />,
    api: {
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': ORACLE,
      'GET /oracle/alpha/controls': CONTROLS,
      'GET /capability-map': MAP,
      'GET /health': HEALTH,
      'GET /users': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    },
    roles: ['viewer', 'operator', 'admin'],
  },
  '/connect': {
    route: '/connect',
    path: '/connect',
    element: <ConnectPage />,
    api: {
      'GET /repos': { items: [REPO, BETA], total: 2, limit: 500, offset: 0 },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /oracle/alpha': ORACLE,
      'GET /oracle/alpha/controls': CONTROLS,
      'GET /oracle/beta': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/beta/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': (url: string) => json(url.includes('repo=alpha') ? MAP : { ...MAP, repo: 'beta', cells: [], summary: { ...MAP.summary, measured_cells: 0, n_total: 0 } }),
    },
    roles: ['viewer', 'operator', 'admin'],
  },
  '/connect/:name': {
    route: '/connect/alpha',
    path: '/connect/:name',
    element: <ConnectRepoPage />,
    api: ALPHA_WALK,
    roles: ['viewer', 'operator'],
  },
  '/connect/:name/measure': {
    route: '/connect/alpha/measure',
    path: '/connect/:name/measure',
    element: <MeasurePage />,
    api: {
      'GET /repos/alpha': REPO,
      'GET /capability-map': MAP,
      'GET /health': HEALTH,
    },
    roles: ['viewer', 'operator'],
  },
  '/results': {
    route: '/results?repo=alpha',
    path: '/results',
    element: <ResultsPage />,
    api: {
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': { ...REPO, last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null } },
      'GET /runs/r9': RUN,
      'GET /capability-map': MAP,
      'GET /oracle/alpha/controls': CONTROLS,
      'GET /oracle/alpha': ORACLE,
      'GET /repos/alpha/pool': { repo: 'alpha', n_tasks: 8, oldest_authored: '2026-08-01T12:00:00+00:00', newest_authored: '2026-08-08T12:00:00+00:00', history_commits: 5, history_first_authored: '2026-06-01T12:00:00+00:00', window_commits: 3, share: 0.6, history_unavailable: '' },
      'GET /signoffs': { items: [STALE], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    },
    roles: ['viewer', 'approver'],
  },
  '/decisions': {
    route: '/decisions',
    path: '/decisions',
    element: <DecisionsPage />,
    api: {
      'GET /version': { crb: '0', apparatus: '2.2', policy: 'routing.v1' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [STALE], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    },
    roles: ['viewer', 'approver'],
  },
  '/signoff': {
    route: '/signoff?repo=r&cell=bug.fix%7CS',
    path: '/signoff',
    element: <SignoffPage />,
    api: {
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': SIGNOFF_MAP,
      'GET /signoffs': { items: [SIGNED], total: 1, limit: 50, offset: 0 },
      'GET /signoffs/preview': PREVIEW,
    },
    roles: ['viewer', 'approver'],
  },
}

