/**
 * DecisionsPage — the inbox across repositories, with the verb by role.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Decisions screen.
 * What it does: Pins that the rows from two repositories roll up into one count; that an
 *               approver sees "Attest" on a sign-off-due row linking to the sign-off page
 *               with the cell preselected; that a viewer sees "Read" and the role that
 *               acts, on the stale rows too; that the evidence line's reason code is a term
 *               with its meaning beside it and the kicker names the apparatus as a term;
 *               that a repository with no factory backlog (404) contributes no factory rows
 *               and no error; and the empty state when nothing waits.
 * How:          `mockApi` + `renderApp`; the map mock has one `deliver` cell (unsigned) and
 *               one `human` cell.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/DecisionsPage.tsx (under test), decisions.ts
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx
 * Touch when:   a row kind or its verb changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
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
    // the evidence line: the reason code is a term (what a reason code is) with its meaning beside it
    const due = screen.getByText('bug.fix × XS clears the bar — attest it or decline').closest('li')!
    expect(due).toHaveTextContent('n=22 on 9 tasks · 100% [85%, 100%]')
    expect(within(due).getByRole('button', { name: 'deliver' })).toHaveAttribute('aria-expanded', 'false')
    expect(due).toHaveTextContent('every bar cleared')
    const human = screen.getByText(/bug.fix × S routed to a human/).closest('li')!
    expect(within(human).getByRole('button', { name: 'oracle_weak' })).toBeInTheDocument()
    expect(human).toHaveTextContent('oracle too weak to license auto-delivery')
  })

  it('the kicker names the apparatus as a term', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /version': { crb: '0', apparatus: '2.2', policy: 'routing.v1' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': map('alpha', [CELL]),
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText(/Under/)).toBeInTheDocument())
    expect(screen.getByText(/Under/).closest('span')).toHaveTextContent('Under apparatus ⓘ 2.2')
    expect(screen.getByRole('button', { name: 'apparatus' })).toBeInTheDocument()
  })

  it('a viewer reads a stale sign-off; only an approver may revoke or re-sign', async () => {
    const stale = { id: 's1', repo: 'alpha', cell: { capability_class: 'bug.fix', size: 'XS' }, revoked: false, active: false, stale: true, apparatus_current: '2.2', approver: 'u9', approver_name: 'Grace', created: '2026-09-01T10:00:00Z', evidence: { n: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, apparatus_versions: ['2.1'] } }
    const routes = {
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': map('alpha', [CELL]),
      'GET /signoffs': { items: [stale], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    }
    mockApi({ ...routes, 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    const first = renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Stale sign-offs' })).toBeInTheDocument())
    const staleList = screen.getByRole('list', { name: 'Stale sign-offs' })
    expect(within(staleList).queryByRole('link', { name: 'Revoke or re-sign' })).toBeNull()
    expect(within(staleList).getByRole('link', { name: 'Read' })).toHaveAttribute('href', '/signoff?repo=alpha&cell=bug.fix%7CXS')
    expect(within(staleList).getByText('approver acts')).toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()
    mockApi({ ...routes, 'GET /auth/me': PRINCIPAL })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('link', { name: 'Revoke or re-sign' })).toBeInTheDocument())
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

  it('a connected but unmeasured repository is "nothing measured yet", never "no repository connected"', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 500, offset: 0 },
      'GET /capability-map': () => envelope(404, 'not_found', 'no rows for alpha'), // the permitted 404: never measured
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true'))
    expect(screen.getByText('Nothing measured yet')).toBeInTheDocument()
    expect(screen.getByText(/alpha is connected but no capability map exists yet/)).toBeInTheDocument()
    expect(screen.queryByText('No repository connected')).toBeNull()
  })
})
