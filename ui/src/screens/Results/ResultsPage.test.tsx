/**
 * ResultsPage — the answer in order: instrument, routes, what waits on a person.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Results screen.
 * What it does: Pins that the three instrument tiles render from the controls verdict, the
 *               oracle report and the map summary, each with its n, an interval or an honest
 *               "95% CI —" with the reason, and the apparatus from the data; that the route
 *               tiles count measured cells with their n and carry a term definition; that
 *               the paragraph says what `deliver` means and does not mean, with the policy's
 *               numbers; that the "waiting on a person" panel offers the act only to the role
 *               that can take it; that a replay in flight is announced with its progress; that
 *               the page defaults to the most recently updated repository; that a loading map
 *               says so; that a controls/oracle 404 renders "not run" / "not scored",
 *               never an alert; and that every tile, header, cell, pill and button carries
 *               a hint, with the false-Q1 tile opening on hover with the registry copy.
 * How:          `mockApi` + `renderApp` at `/results?repo=alpha`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Results/ResultsPage.tsx (under test),
 *               ui/src/components/RepoPicker.tsx (`defaultToLatest`),
 *               ui/src/components/StatTile.tsx (the tile anatomy asserted),
 *               ui/src/help/hints.ts (the copy the hover test expects),
 *               ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Results/ResultsPage.test.tsx
 * Touch when:   a headline fact or the deliver wording changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, expectHintOpens, mockApi, renderApp } from '../../test/utils'
import { ResultsPage } from './ResultsPage'

const CELL = { capability_class: 'bug.fix', size: 'XS', n: 22, n_tasks: 9, clean: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, route: 'deliver', reason: 'n=22', reason_code: 'deliver', verification_tier: 'automated-pass', apparatus_versions: ['2.2'] }
const HUMAN = { ...CELL, size: 'S', n: 13, n_tasks: 11, clean: 11, point: 0.846, ci_low: 0.578, ci_high: 0.957, route: 'human', reason: 'oracle strength 0.76 < 0.80', reason_code: 'oracle_weak' }
const MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: ['bug.fix'], sizes: ['XS', 'S'], languages: [], models: [], cells: [CELL, HUMAN], summary: { trusted_autonomy_coverage: 0.5, total_cells: 2, measured_cells: 2, deliver_cells: 1, n_total: 35, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }
const CONTROLS = { schema: 'x', apparatus: { apparatus_version: '2.2', controls_version: 'controls.v3' }, n_tasks: 32, n_rows: 224, violations: 0, escapes: 0, not_constructible: 43, skipped: 0, passed: true, escape_rows: [], rows: [], verdict: { measured: true, passed: true, complete: true, constructible: 181, total: 224, share: 0.81, escapes: 0, run_id: 'r', created: 'x', state: 'passed' } }
const ORACLE = { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }, { task_id: 't2', strength: 0.7 }], cells: [], apparatus_versions: ['2.2'] }
const REPO = { name: 'alpha', language: 'python', runner: 'pytest', url: '', last_run: null, created: '2026-09-01T00:00:00Z', updated: '2026-09-02T00:00:00Z', config: {} }

const ROUTES = {
  'GET /auth/me': PRINCIPAL,
  'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
  'GET /repos/alpha': REPO,
  'GET /capability-map': MAP,
  'GET /oracle/alpha/controls': CONTROLS,
  'GET /oracle/alpha': ORACLE,
  'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
  'GET /factory/alpha/tasks': () => envelope(404, 'not_found', 'no backlog'),
}

describe('ResultsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the instrument gates, the routes with n, what deliver means, and what waits on a person', async () => {
    mockApi(ROUTES)
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('Is the instrument trustworthy here?')).toBeInTheDocument())
    expect(screen.getByText('Journey · 2 of 4 · Baseline')).toBeInTheDocument() // the journey eyebrow, from the route
    expect(screen.getByText('passed')).toBeInTheDocument() // controls verdict state
    expect(screen.getByText('80%')).toBeInTheDocument() // oracle mean of 0.9 and 0.7
    // the routes with n: one deliver cell, one human cell, and the sentence with the policy's numbers
    expect(screen.getAllByText('1 of 2 measured cells', { exact: false })).toHaveLength(2) // deliver and human, one cell each
    expect(screen.getByText(/means the cell clears the published bar/)).toHaveTextContent('n ≥ 10')
    expect(screen.getByText(/It never means a change is safe to merge or deploy/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the full map' })).toHaveAttribute('href', '/capability?repo=alpha')
    // waiting on a person: the unsigned deliver cell — the approver gets the act
    await waitFor(() => expect(screen.getByRole('list', { name: 'Decisions for alpha' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Attest' })).toHaveAttribute('href', '/signoff?repo=alpha&cell=bug.fix%7CXS')
    // an approver's "sign-off due" on the map is a link to the form
    expect(within(screen.getByTestId('cell-bug.fix-XS')).getByRole('link', { name: 'sign-off due' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(/A measurement is running/)).toBeNull()
  })

  it('every instrument tile carries n, an interval or an honest "95% CI —" with the reason, and the apparatus from the data', async () => {
    mockApi(ROUTES)
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('80%')).toBeInTheDocument())
    const oracle = screen.getByTestId('tile-oracle-strength')
    expect(oracle).toHaveTextContent('n =2')
    expect(oracle).toHaveTextContent('95% CI—') // a mean of per-task scores has no interval — said, not hidden
    expect(oracle).toHaveTextContent('no interval: a mean of per-task scores, not a rate')
    // the apparatus and the bar come from the report and the policy, never a UI constant
    expect(oracle).toHaveTextContent('apparatus 2.2 · mean of per-task mutation scores · ≥ 80% per cell to deliver')
    const controls = screen.getByTestId('tile-negative-controls')
    expect(controls).toHaveTextContent('apparatus 2.2 · controls.v3')
    expect(controls).toHaveTextContent('0 violations · 0 escapes · 43 not constructible')
    // no customer-facing backlog id; the honest "mean only" statement stays
    expect(screen.queryByText(/backlog F35/)).toBeNull()
    expect(screen.getAllByText(/no interval yet: the API serves the mean only/)).toHaveLength(2)
  })

  it('the bar in the oracle tile follows the policy in force, not a constant', async () => {
    mockApi({ ...ROUTES, 'GET /capability-map': { ...MAP, policy: { ...MAP.policy, min_oracle_strength: 0.9 } } })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('80%')).toBeInTheDocument())
    expect(screen.getByTestId('tile-oracle-strength')).toHaveTextContent('≥ 90% per cell to deliver')
  })

  it('the four route tiles are terms with a definition one click away', async () => {
    mockApi(ROUTES)
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('What may the builder be trusted to do?')).toBeInTheDocument())
    for (const r of ['deliver', 'calibrate', 'granularize', 'human']) {
      expect(screen.getByRole('button', { name: r })).toHaveAttribute('aria-expanded', 'false')
    }
  })

  it('a viewer is never offered an act they cannot take: Read and who acts, and "sign-off due" as plain text', async () => {
    mockApi({ ...ROUTES, 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Decisions for alpha' })).toBeInTheDocument())
    expect(screen.queryByRole('link', { name: 'Attest' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Read' })).toHaveAttribute('href', '/signoff?repo=alpha&cell=bug.fix%7CXS')
    expect(screen.getByText('approver acts')).toBeInTheDocument()
    const due = screen.getByTestId('cell-bug.fix-XS')
    expect(due).toHaveTextContent('sign-off due')
    expect(within(due).queryByRole('link')).toBeNull()
  })

  it('a replay in flight is announced above the numbers with its progress and the run link', async () => {
    mockApi({
      ...ROUTES,
      'GET /repos/alpha': { ...REPO, last_run: { id: 'run1', kind: 'replay', status: 'running', finished: null } },
      'GET /runs/run1': { id: 'run1', repo: 'alpha', kind: 'replay', status: 'running', cost_usd: 0.42, progress: { done: 3, total: 8, current_task_id: null }, counts: {} },
    })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByRole('region', { name: 'A measurement is running' })).toBeInTheDocument())
    const banner = screen.getByRole('region', { name: 'A measurement is running' })
    // done = 3 → the FOURTH attempt is running: the same number the Connection walk shows for this run (`kOfN`)
    expect(banner).toHaveTextContent('attempt 4 of 8, $0.42 spent so far')
    expect(banner).toHaveTextContent('The numbers on this page change as each attempt is graded')
    expect(within(banner).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/runs/run1')
  })

  it('a queued replay is announced as waiting, with no attempt number even when the row still carries progress', async () => {
    mockApi({
      ...ROUTES,
      'GET /repos/alpha': { ...REPO, last_run: { id: 'run1', kind: 'replay', status: 'queued', finished: null } },
      // reclaimed after a stale worker: the counts it had are still on the row while it waits
      'GET /runs/run1': { id: 'run1', repo: 'alpha', kind: 'replay', status: 'queued', cost_usd: 0.42, progress: { done: 3, total: 8, current_task_id: null }, counts: {} },
    })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByRole('region', { name: 'A measurement is queued' })).toBeInTheDocument())
    const banner = screen.getByRole('region', { name: 'A measurement is queued' })
    // the reclaimed run still carries done: 3 — the banner says those were graded, without an attempt-in-hand number
    expect(banner).toHaveTextContent('A measurement is waiting for a worker — 3 attempt(s) were graded before it went back to the queue.')
    expect(banner).not.toHaveTextContent(/attempt \d/)
    expect(banner).not.toHaveTextContent('spent so far')
    expect(within(banner).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/runs/run1')
    expect(screen.queryByRole('region', { name: 'A measurement is running' })).toBeNull()
  })

  it('a finished replay shows no banner, even when the repository still reads it as running', async () => {
    mockApi({ ...ROUTES, 'GET /repos/alpha': { ...REPO, last_run: { id: 'run1', kind: 'replay', status: 'succeeded', finished: 'x' } } })
    const first = renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('80%')).toBeInTheDocument())
    expect(screen.queryByRole('region', { name: 'A measurement is running' })).toBeNull()
    first.unmount()
    vi.unstubAllGlobals()
    // the run poll is the fresher source: it says succeeded while `last_run` still says running
    const { calls } = mockApi({
      ...ROUTES,
      'GET /repos/alpha': { ...REPO, last_run: { id: 'run1', kind: 'replay', status: 'running', finished: null } },
      'GET /runs/run1': { id: 'run1', repo: 'alpha', kind: 'replay', status: 'succeeded', cost_usd: 1, progress: { done: 8, total: 8, current_task_id: null }, counts: {} },
    })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(calls.some((c) => c.path === '/runs/run1')).toBe(true))
    await waitFor(() => expect(screen.getByText('80%')).toBeInTheDocument())
    expect(screen.queryByRole('region', { name: 'A measurement is running' })).toBeNull()
  })

  it('with no ?repo= the most recently updated repository is chosen for you (replace, not push)', async () => {
    const { calls } = mockApi({
      ...ROUTES,
      'GET /repos': { items: [REPO, { ...REPO, name: 'beta', updated: '2026-09-10T00:00:00Z' }], total: 2, limit: 500, offset: 0 },
      'GET /repos/beta': { ...REPO, name: 'beta' },
      'GET /capability-map': { ...MAP, repo: 'beta' },
      'GET /oracle/beta/controls': CONTROLS,
      'GET /oracle/beta': ORACLE,
      'GET /factory/beta/tasks': () => envelope(404, 'not_found', 'no backlog'),
    })
    renderApp(<ResultsPage />, { route: '/results' })
    await waitFor(() => expect(screen.getByRole('table', { name: 'Capability map for beta' })).toBeInTheDocument())
    expect(screen.queryByText('Choose a repository')).toBeNull()
    expect(calls.some((c) => c.path === '/capability-map' && c.url.includes('repo=beta'))).toBe(true)
    expect(calls.some((c) => c.path === '/capability-map' && c.url.includes('repo=alpha'))).toBe(false)
  })

  it('with no repository at all the empty state stays and leads to Connect', async () => {
    mockApi({ ...ROUTES, 'GET /repos': { items: [], total: 0, limit: 500, offset: 0 } })
    renderApp(<ResultsPage />, { route: '/results' })
    await waitFor(() => expect(screen.getByText('Choose a repository')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Connect one' })).toHaveAttribute('href', '/connect')
  })

  it('a map still loading says so, never an empty baseline', async () => {
    mockApi({ ...ROUTES, 'GET /capability-map': () => new Promise<Response>(() => {}) })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('Loading the baseline for alpha…')).toBeInTheDocument())
    expect(screen.queryByText('Is the instrument trustworthy here?')).toBeNull()
  })

  it('a controls or oracle 404 is "not run" / "not scored", never an alert', async () => {
    mockApi({
      ...ROUTES,
      'GET /capability-map': { ...MAP, cells: [], summary: { ...MAP.summary, measured_cells: 0, n_total: 0 } },
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
    })
    renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByText('not run')).toBeInTheDocument())
    expect(screen.getByText('not scored')).toBeInTheDocument()
    expect(screen.getByText('Nothing measured yet')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('every tile, map header and cell, pill and door carries a hint; the false-Q1 tile opens on hover with the registry copy', async () => {
    mockApi(ROUTES)
    const { container } = renderApp(<ResultsPage />, { route: '/results?repo=alpha' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Decisions for alpha' })).toBeInTheDocument())
    expect(unhinted(container)).toEqual([])
    for (const id of ['field.shared.repo_picker', 'stat.results.controls', 'stat.results.oracle_strength', 'stat.results.route_deliver', 'stat.results.route_human', 'col.map.class', 'col.map.size', 'map.cell.route', 'map.cell.n', 'map.cell.interval', 'map.cell.signoff', 'map.cell.not_measured', 'stat.results.cost_per_attempt', 'banner.results.no_throughput', 'button.results.routing', 'pill.results.decision_kind', 'button.results.decision_act', 'button.results.all_decisions']) {
      expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    // a cell's numbers opt out of the tab order (the grid is not 300 tab stops); the route tag keeps it
    const cell = screen.getByTestId('cell-bug.fix-XS')
    expect(cell.querySelector('[data-hint="map.cell.n"]')).not.toHaveAttribute('tabindex')
    expect(cell.querySelector('[data-hint="map.cell.route"]')).toHaveAttribute('tabindex', '0')
    const tile = container.querySelector('[data-hint="stat.results.false_q1"]')!
    expect(tile).toHaveAttribute('tabindex', '0')
    await expectHintOpens(tile, 'stat.results.false_q1')
  })
})
