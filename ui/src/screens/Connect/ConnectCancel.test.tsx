/**
 * The walk's Cancel, refused — the measure journey's own door says why (journey-measure.actions.4).
 *
 * Navigation
 * ----------
 * What it is:   One test for the Connect walk's in-flight Cancel when the server refuses it.
 * What it does: Pins that a cancel refused on the walk (409: the run finished between the
 *               poll and the click) is shown to the person on the walk itself, with the
 *               server's status, code and message — not only on the run page. The walk is
 *               the measure journey's own door to Cancel, so the journey's criterion is
 *               proven here and not through the run page alone.
 * How:          `mockApi` answers the walk's reads with a running measurement and the cancel
 *               with a 409 envelope; `confirm` is stubbed to accept; the assertion is on the
 *               `ErrorState` alert the walk renders.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (the walk; its `actionError`),
 *               ui/src/screens/Connect/ConnectPage.test.tsx (the walk's other cases, whose
 *               fixtures these mirror), ui/src/components/ErrorState.tsx (the envelope line)
 * Tested by:    ui/src/screens/Connect/ConnectCancel.test.tsx
 * Touch when:   never for a new repository; the walk's Cancel or its refusal changes.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { ConnectRepoPage } from './ConnectPage'

const REPO = {
  name: 'alpha',
  language: 'python',
  runner: 'pytest',
  url: 'https://github.com/acme/alpha',
  clone_path: '',
  probe: { status: 'ok', run_id: 'r1', checked: '2026-09-17T00:00:00Z', detail: 'pytest 8' },
  task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 },
  last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null },
  created: '2026-09-17T00:00:00Z',
  updated: '2026-09-17T00:00:00Z',
  config: {},
}
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
const MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [], summary: { trusted_autonomy_coverage: 0, total_cells: 0, measured_cells: 0, deliver_cells: 0, n_total: 4, false_q1_total: 0, apparatus_versions: [] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

describe('the walk’s Cancel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a cancel refused on the walk is shown there with the server’s status, code and message', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': MAP,
      'GET /runs/r9': RUN,
      'POST /runs/r9/cancel': () => envelope(409, 'run_terminal', 'run is already succeeded', { status: 'succeeded' }),
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('In progress'))
    expect(screen.queryByRole('alert')).toBeNull()
    await userEvent.click(within(screen.getByTestId('in-flight')).getByRole('button', { name: 'Cancel the run' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('run is already succeeded')
    expect(alert).toHaveTextContent('HTTP 409 · run_terminal')
  })
})
