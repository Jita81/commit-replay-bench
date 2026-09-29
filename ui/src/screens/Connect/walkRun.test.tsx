/**
 * The walk's own Run button leaves the card watching the run it queued — never on the stale
 * last run (G-428).
 *
 * Navigation
 * ----------
 * What it is:   The regression test for `useCreateRun`'s invalidation as the walk on
 *               /connect/:name depends on it.
 * What it does: Pins that pressing Run on a stage posts the stage's kind and that the card then
 *               reads Queued with the live line the polled run gives — which needs the
 *               repository (`GET /repos/:name`, whose `last_run` names the run the walk watches)
 *               to be read again the moment the run is queued. Before the fix `useCreateRun`
 *               invalidated only the runs list, so the card kept the previous `last_run` and the
 *               person who pressed Run saw nothing happen until they reloaded.
 * How:          `mockApi` with a stateful `GET /repos/alpha` (no run until the POST, the queued
 *               run after it) and `renderApp` with `path` for `useParams`; the walk screen itself,
 *               not the hook alone, so the reading the person sees is what is asserted.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useCreateRun` — invalidates `keys.repo(run.repo)` and
 *               `keys.repos` on success), ui/src/screens/Connect/ConnectPage.tsx (the walk that
 *               presses it), ui/src/screens/Connect/connection.ts (the Queued live line),
 *               ui/e2e/walkthrough/04b-connect-walk.spec.ts (the same press on the live stack)
 * Tested by:    ui/src/screens/Connect/walkRun.test.tsx
 * Touch when:   never for a new repository; the walk reads the watched run from somewhere other
 *               than the repository's `last_run`.
 */

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { ConnectRepoPage } from './ConnectPage'

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
const QUEUED_RUN = {
  id: 'run-9',
  repo: 'alpha',
  kind: 'mine',
  status: 'queued',
  mode: 'sighted',
  builder: '',
  model: '',
  provider: '',
  ladder: [],
  executor: 'local',
  timeout: 600,
  pool: '',
  limit: null,
  task_ids: [],
  builder_config: {},
  actor: 'op',
  created: '2026-09-19T10:00:00Z',
  started: null,
  finished: null,
  cancel_requested: false,
  error: '',
  cost_usd: 0,
  apparatus_version: '2.2',
  counts: { tasks: 0, clean: 0, disqualified: 0, errors: 0, first_pass_clean: 0, rows: 0 },
  progress: { done: 0, total: 0, current_task_id: null },
  queue_position: 1,
  queue_kinds_ahead: [],
}

describe('the walk presses Run', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('pressing Run on a stage turns the card Queued with its live line', async () => {
    // the repository as the API serves it: no run until the POST, and the queued run as
    // `last_run` from then on — the second GET /repos/alpha is what the fix makes happen
    let queued = false
    let repoReads = 0
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': () => {
        repoReads += 1
        return json(queued ? { ...REPO, last_run: { id: 'run-9', kind: 'mine', status: 'queued', finished: null } } : REPO)
      },
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'no oracle report'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'no controls report'),
      'GET /capability-map': EMPTY_MAP,
      'POST /runs': () => {
        queued = true
        return json(QUEUED_RUN, 201)
      },
      'GET /runs/run-9': QUEUED_RUN,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const mine = await screen.findByTestId('stage-mine')
    expect(mine).toHaveTextContent('Not started')
    const readsBefore = repoReads

    await userEvent.click(screen.getByRole('button', { name: 'Run' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST' && c.path === '/runs')!.init?.body))).toEqual({ repo: 'alpha', kind: 'mine' })

    // the card now watches the run it queued: the repository was read again after the POST,
    // the pill reads Queued and the live line says where the run is in the worker's line
    await waitFor(() => expect(repoReads).toBeGreaterThan(readsBefore))
    await waitFor(() => expect(screen.getByTestId('stage-mine')).toHaveTextContent('Queued'))
    expect(screen.getByTestId('stage-mine').querySelector('[aria-label="Commits mined into tasks: Queued"]')).not.toBeNull()
    expect(screen.getByTestId('stage-mine')).toHaveTextContent('Queued — next in line for a worker')
    expect(screen.getByTestId('in-flight')).toHaveTextContent('Waiting for a worker')
    // the Run button has gone: nothing offers to queue a second mine
    expect(screen.queryByRole('button', { name: 'Run' })).not.toBeInTheDocument()
  })
})
