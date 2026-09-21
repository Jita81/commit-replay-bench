/**
 * ConnectPage — the walk resumes where the repository is; actions are role-gated.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Connect list and the per-repository task list.
 * What it does: Pins that the list shows each repository's next stage and names the door
 *               "Baseline" (J-ONR-14); that the per-repo page renders six stages with the
 *               API-derived statuses (a 404 oracle/controls = not started, not an error)
 *               under the journey eyebrow; that the operator's action on the next stage
 *               posts the right run kind (`POST /runs {kind: mine}`) and the probe posts to
 *               its own route; that a viewer sees the stage and a sentence, not a bare
 *               "operator" (J-ONR-15); that a running measurement renders the in-flight
 *               panel from the polled run — attempts, spend, started, Cancel with a confirm
 *               that posts the cancel (J-ONR-5) — and a queued run reads "Queued" with its
 *               place in the line (J-TEL-6).
 * How:          `mockApi` + `renderApp` with `path` set so `useParams` resolves.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (under test), connection.ts
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx
 * Touch when:   a stage or its action changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { ConnectPage, ConnectRepoPage } from './ConnectPage'

const REPO = {
  name: 'alpha',
  language: 'python',
  runner: 'pytest',
  url: 'https://github.com/acme/alpha',
  clone_path: '',
  probe: { status: 'ok', run_id: 'r1', checked: '2026-09-17T00:00:00Z', detail: 'pytest 8' },
  task_counts: { total: 0, standard: 0, hard: 0, gold_clean: 0, gold_failed: 0, unchecked: 0 },
  last_run: null,
  created: '2026-09-17T00:00:00Z',
  updated: '2026-09-17T00:00:00Z',
  config: {},
}
const MEASURED = { ...REPO, task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 } }
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
const EMPTY_MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [], summary: { trusted_autonomy_coverage: 0, total_cells: 0, measured_cells: 0, deliver_cells: 0, n_total: 0, false_q1_total: 0, apparatus_versions: [] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

describe('ConnectPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists connected repositories with their next stage', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 } })
    renderApp(<ConnectPage />, { route: '/connect' })
    await waitFor(() => expect(screen.getByRole('table', { name: 'Connected repositories' })).toBeInTheDocument())
    expect(screen.getByText('commits mined into tasks')).toBeInTheDocument() // the next stage after a good probe
    expect(screen.getByRole('link', { name: 'Continue' })).toHaveAttribute('href', '/connect/alpha')
    // gold-clean carries its definition one click away
    expect(screen.getByRole('button', { name: /gold-clean/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Journey · 1 of 4 · Connection')).toBeInTheDocument()
  })

  it('a measured repository\'s door is named Baseline, the same as the nav', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [MEASURED], total: 1, limit: 500, offset: 0 },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 22 } },
    })
    renderApp(<ConnectPage />, { route: '/connect' })
    await waitFor(() => expect(screen.getByRole('link', { name: 'Baseline' })).toHaveAttribute('href', '/connect/alpha'))
    expect(screen.queryByRole('link', { name: 'Results' })).not.toBeInTheDocument()
  })

  it('the per-repository walk: six stages, statuses from the API, the operator runs the next one', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'no oracle report'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'no controls report'),
      'GET /capability-map': EMPTY_MAP,
      'POST /runs': (_u: string, init?: RequestInit) => json({ id: 'run-9', repo: 'alpha', kind: JSON.parse(String(init?.body)).kind, status: 'queued' }, 201),
      'GET /runs/run-9': { id: 'run-9', repo: 'alpha', kind: 'mine', status: 'queued' },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Connection stages' })).toBeInTheDocument())
    const ids = ['register', 'probe', 'mine', 'oracle', 'controls', 'measure']
    for (const id of ids) expect(screen.getByTestId(`stage-${id}`)).toBeInTheDocument()
    expect(screen.getByTestId('stage-probe')).toHaveTextContent('Done')
    expect(screen.getByTestId('stage-probe')).toHaveTextContent('ok — pytest 8')
    expect(screen.getByTestId('stage-mine')).toHaveTextContent('Not started')
    expect(screen.getByTestId('stage-oracle')).toHaveTextContent('Waiting')
    // a 404 on the oracle/controls is a stage state, never an alert
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // the only button is on the next stage (mine); it queues a mine run
    const buttons = screen.getAllByRole('button', { name: /^Run$|^Measure…$|^Retry$/ })
    expect(buttons).toHaveLength(1)
    await userEvent.click(buttons[0]!)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    const post = calls.find((c) => c.method === 'POST' && c.path === '/runs')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ repo: 'alpha', kind: 'mine' })
    expect(screen.getByRole('link', { name: 'Baseline' })).toHaveAttribute('href', '/results?repo=alpha')
    expect(screen.getByText('Journey · 1 of 4 · Connection')).toBeInTheDocument()
  })

  it('a viewer sees the walk but no action', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': { ...REPO, probe: { status: 'not_probed', run_id: null, checked: null, detail: '' } },
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-probe')).toHaveTextContent('Not started'))
    expect(screen.queryByRole('button', { name: /^Run$/ })).not.toBeInTheDocument()
    expect(screen.getByTestId('stage-probe')).toHaveTextContent('An operator runs this.')
  })

  it('a viewer on the measure stage is told it spends, in a sentence', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Not started'))
    expect(screen.getByTestId('stage-measure')).toHaveTextContent('An operator starts this; it spends model budget.')
    expect(screen.queryByRole('button', { name: /^Measure…$/ })).not.toBeInTheDocument()
  })

  it('a running measurement shows attempts, spend, started and a Cancel that confirms before posting (J-ONR-5)', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 4 } },
      'GET /runs/r9': RUN,
      'POST /runs/r9/cancel': () => json({ ...RUN, cancel_requested: true }),
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('In progress'))
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Measuring — attempt 3 of 10 · $0.42 so far, builder-reported (4 rows already on the current apparatus)'))
    const panel = screen.getByTestId('in-flight')
    expect(panel).toHaveTextContent(/Attempt 3 of 10 · \$0\.42 spent so far · started \d{2}:\d{2}\./)
    expect(panel).toHaveTextContent('Rows land on the baseline as each attempt is graded; when the run finishes this stage turns Done and the Baseline button fills in.')
    expect(within(panel).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/runs/r9')
    // no second spend is offered while the run is in flight
    expect(screen.queryByRole('button', { name: /^Measure…$/ })).not.toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: 'Cancel the run' }))
    expect(globalThis.confirm).toHaveBeenCalledWith('Cancel this run? Attempts already made are still charged.')
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs/r9/cancel')).toBe(true))
  })

  it('a queued run reads Queued with the server’s queue_position (the worker’s own order), never a client recount (J-TEL-6)', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'queued', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /runs/r9': { ...RUN, status: 'queued', started: null, progress: { done: 0, total: 0, current_task_id: null }, cost_usd: 0, queue_position: 3, queue_kinds_ahead: ['replay', 'mine'] },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Queued — 2 runs ahead of it'))
    // the queued list is not read when the server states the position
    expect(calls.some((c) => c.method === 'GET' && c.path === '/runs')).toBe(false)
  })

  it('an older server that sends no queue_position: the place in the line falls back to the queued list', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'queued', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /runs/r9': { ...RUN, status: 'queued', started: null, progress: { done: 0, total: 0, current_task_id: null }, cost_usd: 0 },
      'GET /runs': { items: [{ ...RUN, id: 'r7', created: '2026-09-19T09:00:00Z', status: 'queued' }, { ...RUN, status: 'queued' }], total: 2, limit: 200, offset: 0 },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Queued — 1 run ahead of it'))
    expect(within(screen.getByTestId('stage-measure')).getByText('Queued', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByTestId('stage-measure')).not.toHaveTextContent('In progress')
    expect(screen.getByTestId('in-flight')).toHaveTextContent('Waiting for a worker')
  })
})
