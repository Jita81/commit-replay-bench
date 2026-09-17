/**
 * DecisionsPage — the inbox across repositories, with the verb by role.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Decisions screen.
 * What it does: Pins that the rows from two repositories roll up into one count; that an
 *               approver sees "Attest" on a sign-off-due row linking to the sign-off page
 *               with the cell preselected; that a viewer sees "View" and the role that
 *               acts; that a repository with no factory backlog (404) contributes no
 *               factory rows and no error; and the empty state when nothing waits.
 * How:          `mockApi` + `renderApp`; the map mock has one `deliver` cell (unsigned) and
 *               one `human` cell.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/DecisionsPage.tsx (under test), decisions.ts
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx
 * Touch when:   a row kind or its verb changes.
 */

import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { DecisionsPage } from './DecisionsPage'

const CELL = { capability_class: 'bug.fix', size: 'XS', n: 22, n_tasks: 9, clean: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, route: 'deliver', reason: 'n=22', reason_code: 'deliver', verification_tier: 'automated-pass', apparatus_versions: ['2.2'] }
const HUMAN = { ...CELL, size: 'S', route: 'human', reason: 'oracle strength 0.76 < 0.80 — green cannot license auto-delivery', reason_code: 'oracle_weak' }
function map(repo: string, cells: unknown[]) {
  return { repo, by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells, summary: { trusted_autonomy_coverage: 0, total_cells: 2, measured_cells: 2, deliver_cells: 1, n_total: 44, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }
}
const REPOS = { items: [{ name: 'alpha' }, { name: 'beta' }], total: 2, limit: 500, offset: 0 }

describe('DecisionsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('an approver sees the rows across repositories with the act and the deep link', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL, // approver
      'GET /repos': REPOS,
      'GET /capability-map': (url: string) => new Response(JSON.stringify(map(url.includes('repo=alpha') ? 'alpha' : 'beta', url.includes('repo=alpha') ? [CELL, HUMAN] : [])), { headers: { 'Content-Type': 'application/json' } }),
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/beta/tasks': [{ id: 'I-1', title: 'Divide', capability_class: 'bug.fix', size: 'S', kind: 'code', status: 'blocked', dor_gaps: ['method_path'], route_hint: 'human', red_proof: null, build_status: 'not_started', pr_url: null, review_verdict: null, last_event: 'readiness.blocked' }],
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('3 waiting')).toBeInTheDocument())
    expect(screen.getByRole('list', { name: 'Decisions for alpha' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Decisions for beta' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Attest' })).toHaveAttribute('href', '/signoff?repo=alpha&cell=bug.fix%7CXS')
    expect(screen.getByRole('link', { name: 'Sign a gap' })).toHaveAttribute('href', '/factory?repo=beta&item=I-1')
    expect(screen.getByRole('link', { name: 'Read why' })).toHaveAttribute('href', '/routing?repo=alpha')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a viewer sees the same rows with Read and the role that acts', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': map('alpha', [CELL]),
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getAllByText('1 waiting')).toHaveLength(2)) // the pill AND the card eyebrow
    expect(screen.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true') // the e2e sweep's readiness anchor
    expect(screen.getByRole('link', { name: 'Read' })).toBeInTheDocument()
    expect(screen.getByText('approver acts')).toBeInTheDocument()
  })

  it('nothing waiting is said, not hidden', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': map('alpha', [{ ...CELL, route: 'calibrate', reason_code: 'n_below_min' }]),
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': [],
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('Nothing is waiting on a person')).toBeInTheDocument())
    expect(screen.getByText('0 waiting')).toBeInTheDocument()
  })
})
