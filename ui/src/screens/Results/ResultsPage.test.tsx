/**
 * ResultsPage — the answer in order: instrument, routes, what waits on a person.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Results screen.
 * What it does: Pins that the three instrument tiles render from the controls verdict, the
 *               oracle report and the map summary (with n); that the route tiles count
 *               measured cells with their n; that the paragraph says what `deliver` means
 *               and does not mean, with the policy's numbers; that the "waiting on a
 *               person" panel lists the sign-off due; and that a controls/oracle 404 renders
 *               "not run" / "not scored", never an alert.
 * How:          `mockApi` + `renderApp` at `/results?repo=alpha`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Results/ResultsPage.tsx (under test)
 * Tested by:    ui/src/screens/Results/ResultsPage.test.tsx
 * Touch when:   a headline fact or the deliver wording changes.
 */

import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { ResultsPage } from './ResultsPage'

const CELL = { capability_class: 'bug.fix', size: 'XS', n: 22, n_tasks: 9, clean: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, route: 'deliver', reason: 'n=22', reason_code: 'deliver', verification_tier: 'automated-pass', apparatus_versions: ['2.2'] }
const HUMAN = { ...CELL, size: 'S', n: 13, n_tasks: 11, clean: 11, point: 0.846, ci_low: 0.578, ci_high: 0.957, route: 'human', reason: 'oracle strength 0.76 < 0.80', reason_code: 'oracle_weak' }
const MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: ['bug.fix'], sizes: ['XS', 'S'], languages: [], models: [], cells: [CELL, HUMAN], summary: { trusted_autonomy_coverage: 0.5, total_cells: 2, measured_cells: 2, deliver_cells: 1, n_total: 35, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }
const CONTROLS = { schema: 'x', apparatus: {}, n_tasks: 32, n_rows: 224, violations: 0, escapes: 0, not_constructible: 43, skipped: 0, passed: true, escape_rows: [], rows: [], verdict: { measured: true, passed: true, complete: true, constructible: 181, total: 224, share: 0.81, escapes: 0, run_id: 'r', created: 'x', state: 'passed' } }
const ORACLE = { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }, { task_id: 't2', strength: 0.7 }], cells: [], apparatus_versions: ['2.2'] }

describe('ResultsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the instrument gates, the routes with n, what deliver means, and what waits on a person', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': MAP,
      'GET /oracle/alpha/controls': CONTROLS,
      'GET /oracle/alpha': ORACLE,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('Is the instrument trustworthy here?')).toBeInTheDocument())
    expect(screen.getByText('passed')).toBeInTheDocument() // controls verdict state
    expect(screen.getByText('80%')).toBeInTheDocument() // oracle mean of 0.9 and 0.7
    // the routes with n: one deliver cell, one human cell, and the sentence with the policy's numbers
    expect(screen.getAllByText('1 of 2 measured cells', { exact: false })).toHaveLength(2) // deliver and human, one cell each
    expect(screen.getByText(/means the cell clears the published bar/)).toHaveTextContent('n ≥ 10')
    expect(screen.getByText(/It never means a change is safe to merge or deploy/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the full map' })).toHaveAttribute('href', '/capability?repo=alpha')
    // waiting on a person: the unsigned deliver cell
    await waitFor(() => expect(screen.getByRole('list', { name: 'Decisions for alpha' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Attest' })).toHaveAttribute('href', '/signoff?repo=alpha&cell=bug.fix%7CXS')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a controls or oracle 404 is "not run" / "not scored", never an alert', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': { ...MAP, cells: [], summary: { ...MAP.summary, measured_cells: 0, n_total: 0 } },
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'x'),
    })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('not run')).toBeInTheDocument())
    expect(screen.getByText('not scored')).toBeInTheDocument()
    expect(screen.getByText('Nothing measured yet')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
