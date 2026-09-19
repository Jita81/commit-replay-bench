/**
 * ui/src/screens/Runs/RunsPage.tsx — the list names every kind it lists.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Runs list screen against a mocked API.
 * What it does: Pins that the Kind filter can select every kind a run can have (factory,
 *               probe and label included, not only the kinds the dialog starts), that the
 *               purpose and empty-state copy name the factory, that a factory run lists, and
 *               that `?new=<kind>` opens the start dialog only for a role that can start a
 *               run (J-FAC-12) — a viewer reads who acts instead.
 * How:          `renderApp` at `/runs` with `mockApi`; assertions on the select's options
 *               and the header copy.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Runs/RunsPage.tsx (the code under test), ui/src/api/types.ts
 *               (`RUN_KINDS`, `RunKind`), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Runs/RunsPage.test.tsx
 * Touch when:   a run kind is added — extend the expected option list; the role that may
 *               start a run changes — update the ?new= gate test.
 */
import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Run } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { RunsPage } from './RunsPage'

const RUN: Run = {
  id: 'run-factory-1',
  repo: 'alpha',
  kind: 'factory',
  status: 'succeeded',
  mode: 'sighted',
  builder: 'editblock',
  model: 'm',
  provider: 'p',
  ladder: ['r1'],
  executor: 'docker',
  timeout: 900,
  pool: 'standard',
  limit: null,
  task_ids: [],
  builder_config: {},
  actor: 'ada',
  created: '2026-09-13T09:00:00Z',
  started: '2026-09-13T09:01:00Z',
  finished: '2026-09-13T09:30:00Z',
  cancel_requested: false,
  error: '',
  cost_usd: 0.2,
  apparatus_version: '2.2',
  counts: { tasks: 2, clean: 2, disqualified: 0, errors: 0, first_pass_clean: 2, rows: 2 },
  progress: { done: 2, total: 2, current_task_id: null },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RunsPage', () => {
  it('the Kind filter offers every kind a run can have and the copy names the factory', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [], total: 0, limit: 200, offset: 0 },
      'GET /runs': { items: [RUN], total: 1, limit: 200, offset: 0 },
    })
    renderApp(<RunsPage />, { route: '/runs', path: '/runs' })
    const kind = await screen.findByRole('combobox', { name: 'Kind' })
    const options = within(kind)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value)
    expect(options).toEqual(['', 'mine', 'replay', 'blind', 'oracle', 'controls', 'probe', 'label', 'factory'])
    expect(screen.getByText(/Every mine, replay, blind, oracle, controls and factory run/)).toBeInTheDocument()
    expect(await screen.findByText('run-fact')).toBeInTheDocument()
  })

  it('the empty state names the factory too', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [], total: 0, limit: 200, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<RunsPage />, { route: '/runs', path: '/runs' })
    expect(await screen.findByText(/mine, replay, blind, oracle, controls or factory job over one repo/)).toBeInTheDocument()
  })

  it('?new= opens the start dialog for an operator, never for a viewer (J-FAC-12)', async () => {
    const viewer = { ...PRINCIPAL, role: 'viewer' as const }
    mockApi({
      'GET /auth/me': viewer,
      'GET /repos': { items: [], total: 0, limit: 200, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<RunsPage />, { route: '/runs?new=replay', path: '/runs' })
    await screen.findByText('No runs match')
    expect(screen.queryByRole('dialog', { name: 'Start a run' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Start a run' })).toBeNull()
    expect(screen.getByText(/An operator starts a run/)).toBeInTheDocument()
  })
})
