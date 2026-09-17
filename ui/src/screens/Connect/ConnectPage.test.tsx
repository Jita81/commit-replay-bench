/**
 * ConnectPage — the walk resumes where the repository is; actions are role-gated.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Connect list and the per-repository task list.
 * What it does: Pins that the list shows each repository's next stage; that the per-repo
 *               page renders six stages with the API-derived statuses (a 404 oracle/controls
 *               = not started, not an error); that the operator's action on the next stage
 *               posts the right run kind (`POST /runs {kind: mine}`) and the probe posts to
 *               its own route; that a viewer sees the stage but no button; and that the
 *               header offers the results door.
 * How:          `mockApi` + `renderApp` with `path` set so `useParams` resolves.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (under test), connection.ts
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx
 * Touch when:   a stage or its action changes.
 */

import { screen, waitFor } from '@testing-library/react'
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
const EMPTY_MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [], summary: { trusted_autonomy_coverage: 0, total_cells: 0, measured_cells: 0, deliver_cells: 0, n_total: 0, false_q1_total: 0, apparatus_versions: [] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

describe('ConnectPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists connected repositories with their next stage', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 } })
    renderApp(<ConnectPage />, { route: '/connect' })
    await waitFor(() => expect(screen.getByRole('table', { name: 'Connected repositories' })).toBeInTheDocument())
    expect(screen.getByText('commits mined into tasks')).toBeInTheDocument() // the next stage after a good probe
    expect(screen.getByRole('link', { name: 'Continue' })).toHaveAttribute('href', '/connect/alpha')
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
    expect(screen.getByRole('link', { name: 'Results' })).toHaveAttribute('href', '/results?repo=alpha')
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
    expect(screen.getByTestId('stage-probe')).toHaveTextContent('operator')
  })
})
