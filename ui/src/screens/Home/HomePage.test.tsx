/**
 * HomePage — the eight tasks derive their status from the API; nothing is kept locally.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Get-started task list.
 * What it does: Pins that a deployment with the app configured and installed, a probed +
 *               mined repository with oracle and controls done but nothing measured reads
 *               "5 of 8" (connect, choose, shape, prove and approver complete — an admin who
 *               can list users sees one exists; measure incomplete; baseline cannot start)
 *               and that Continue points at the first task that is neither Completed nor
 *               Cannot start yet (J-ONR-1); that a viewer reads the same list as a progress
 *               report, a run in flight is "In progress", the baseline opens from the first
 *               row, a frozen backlog with no factory run reads "Backlog frozen — run the
 *               factory" and a non-admin is told whom to ask about task 7 (J-TEL-10,
 *               J-ONR-19); that an active sign-off completes task 6, a STALE one does not
 *               (the API's `active`/`stale` flags, never the row count) and an active factory
 *               run reads "item k of n" (J-ONR-2); that an App with no installation is
 *               "Incomplete" and no App with a URL repository "Optional"; that the degraded
 *               sandbox is an "Important" banner linking to Deployment (J-HEL-5), and that
 *               the cost statement and "Why two people" are present.
 * How:          `mockApi` + `renderApp`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Home/HomePage.tsx, ui/src/screens/Connect/connection.ts,
 *               ui/src/api/hooks.ts (`useActiveRun`, `useSignoffs`)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx
 * Touch when:   a task or its evidence source changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { HomePage, factoryStatusFor } from './HomePage'

const REPO = {
  name: 'alpha',
  language: 'python',
  runner: 'pytest',
  url: 'https://github.com/acme/alpha',
  clone_path: '',
  probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: 'pytest 8' },
  task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 },
  last_run: null,
  created: '2026-09-17T00:00:00Z',
  updated: '2026-09-17T00:00:00Z',
  config: {},
}
const FACTORY_TASK = { id: 'T-1', title: 'x', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'pending', dor_gaps: [], route_hint: '', red_proof: null, build_status: 'not_built', pr_url: null, review_verdict: null, last_event: '', cell_route: { route: '', reason_code: '', reason: '', n: 0, point: 0, ci_low: 0, ci_high: 0, apparatus_versions: [], deliverable: false } }
const EMPTY_MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [], summary: { trusted_autonomy_coverage: 0, total_cells: 0, measured_cells: 0, deliver_cells: 0, n_total: 0, false_q1_total: 0, apparatus_versions: [] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

describe('factoryStatusFor', () => {
  it('reads the factory task from the API facts, delivered first', () => {
    const t = (over: Partial<{ pr_url: string | null; status: string }>) => ({ pr_url: null, status: 'pending', ...over })
    expect(factoryStatusFor({ measured: false, deliverCells: false, backlog: 'none', items: [] })).toBe('blocked')
    expect(factoryStatusFor({ measured: true, deliverCells: false, backlog: 'none', items: [] })).toBe('no_deliver_cell')
    expect(factoryStatusFor({ measured: true, deliverCells: true, backlog: 'none', items: [] })).toBe('ready')
    // frozen with no run behind it is ready to run, not "in progress"; an active run is
    expect(factoryStatusFor({ measured: true, deliverCells: true, backlog: 'frozen', items: [t({})] })).toBe('frozen')
    expect(factoryStatusFor({ measured: true, deliverCells: true, backlog: 'frozen', items: [t({})], activeRun: true })).toBe('running')
    expect(factoryStatusFor({ measured: true, deliverCells: true, backlog: 'frozen', items: [t({ pr_url: 'https://x/pr/1' })] })).toBe('delivered')
    expect(factoryStatusFor({ measured: true, deliverCells: true, backlog: 'frozen', items: [t({ status: 'accepted' })] })).toBe('delivered')
    expect(factoryStatusFor({ measured: true, deliverCells: true, backlog: 'unknown', items: [] })).toBe('unknown')
  })
})

describe('HomePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('derives the seven tasks from the API and counts the completed ones', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: false, recorded_by: '', updated: '' }] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: 'docker not reachable', data: {} }] },
      'GET /users': { items: [{ id: 'u2', username: 'ada', display_name: 'Ada', email: '', role: 'approver', issuer: 'local', created: '' }], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 5 of 8 tasks.')).toBeInTheDocument())
    const list = screen.getByRole('list', { name: 'Tasks' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(8)
    expect(rows[0]).toHaveTextContent('Connect GitHub')
    expect(rows[0]).toHaveTextContent('Completed')
    expect(rows[3]).toHaveTextContent('Prove the instrument (£0)')
    expect(rows[3]).toHaveTextContent('Completed')
    expect(rows[4]).toHaveTextContent('Measure — spends money')
    expect(rows[4]).toHaveTextContent('Incomplete')
    expect(rows[5]).toHaveTextContent('Cannot start yet')
    expect(rows[6]).toHaveTextContent('Invite an approver')
    expect(rows[6]).toHaveTextContent('Completed')
    // the destination: nothing measured yet, so the factory cannot start
    expect(rows[7]).toHaveTextContent('Deliver your first change')
    expect(rows[7]).toHaveTextContent('Cannot start yet')
    expect(within(rows[7]!).getByRole('link')).toHaveAttribute('href', '/factory?repo=alpha')
    expect(within(rows[4]!).getByRole('link')).toHaveAttribute('href', '/connect/alpha/measure')
    // the degraded sandbox is the Important banner, linking to Deployment (words, not JSON)
    expect(screen.getByRole('region', { name: 'Important' })).toHaveTextContent('The sandbox probe is degraded on this host.')
    expect(screen.getByRole('link', { name: "See the deployment's health" })).toHaveAttribute('href', '/posture')
    expect(screen.getByText(/Tasks 1 to 4 cost nothing/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Why two people' })).toBeInTheDocument()
    // Continue goes to the first task that is neither Completed nor Cannot start yet: Measure
    expect(screen.getByRole('link', { name: 'Continue to task 5: Measure — spends money' })).toHaveAttribute('href', '/connect/alpha/measure')
  })

  it('a viewer reads the same list as a progress report, a measurement in flight is "In progress", and the map opens from the first row', async () => {
    const running = { ...REPO, last_run: { id: 'r9', kind: 'replay', status: 'running', created: '2026-09-17T10:00:00Z' } }
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [running], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': running,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 6 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /factory/alpha/backlog': { repo: 'alpha', hash: 'b'.repeat(64), frozen_at: '2026-09-17T10:00:00Z', items: [] },
      'GET /factory/alpha/tasks': [FACTORY_TASK],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('The operators have completed 3 of 8 tasks.')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Where this deployment is' })).toBeInTheDocument()
    expect(screen.getByText(/You can read everything here and change nothing/)).toBeInTheDocument()
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    // no App configured but a repository connected by URL: the connection task is optional, not a blocker
    expect(rows[0]).toHaveTextContent('Optional')
    expect(rows[4]).toHaveTextContent('In progress')
    expect(within(rows[4]!).getByRole('link')).toHaveAttribute('href', '/connect/alpha')
    expect(rows[5]).toHaveTextContent('Read the baseline')
    expect(rows[5]).toHaveTextContent('Incomplete')
    // a non-admin is not sent to a settings page that refuses them, and is told whom to ask
    expect(rows[6]).toHaveTextContent('Not known yet')
    expect(within(rows[6]!).getByRole('link')).toHaveAttribute('href', '/posture')
    expect(screen.getByText(/Only an admin can add users/)).toBeInTheDocument()
    // a frozen backlog with no factory run behind it is ready to run, not "in progress"
    expect(rows[7]).toHaveTextContent('Backlog frozen — run the factory')
    // the viewer's Continue keeps its rule — the baseline once any row exists — and names
    // its destination like the operator's does; the lede says what a viewer does there
    expect(screen.getByRole('link', { name: 'Continue to the baseline for alpha' })).toHaveAttribute('href', '/results?repo=alpha')
    expect(screen.getByText(/a viewer reads what the evidence says and what is waiting on a person/)).toBeInTheDocument()
  })

  it('an active sign-off completes "Read the baseline"; an active factory run reads item k of n; Continue lands on the factory', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: true, recorded_by: '', updated: '' }] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 30, deliver_cells: 1 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /users': () => envelope(403, 'forbidden', 'x'),
      'GET /factory/alpha/backlog': { repo: 'alpha', hash: 'b'.repeat(64), frozen_at: '2026-09-17T10:00:00Z', items: [] },
      'GET /factory/alpha/tasks': [FACTORY_TASK],
      'GET /signoffs': { items: [{ id: 'sgn_1', repo: 'alpha', revoked: false, active: true, stale: false }], total: 1, limit: 50, offset: 0 },
      'GET /runs': { items: [{ id: 'run-f', repo: 'alpha', kind: 'factory', status: 'running', created: '2026-09-19T10:00:00Z', started: '2026-09-19T10:00:10Z', finished: null, cancel_requested: false, cost_usd: 0.5, counts: { tasks: 0, clean: 0, disqualified: 0, errors: 0, first_pass_clean: 0, rows: 0 }, progress: { done: 1, total: 5, current_task_id: 'T-2' } }], total: 1, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 6 of 8 tasks.')).toBeInTheDocument())
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[5]).toHaveTextContent('Read the baseline')
    expect(rows[5]).toHaveTextContent('Completed')
    expect(rows[6]).toHaveTextContent('Not known yet')
    await waitFor(() => expect(rows[7]).toHaveTextContent('In progress — item 2 of 5'))
    expect(screen.getByRole('link', { name: 'Continue to task 8: Deliver your first change' })).toHaveAttribute('href', '/factory?repo=alpha')
  })

  it('a stale sign-off (the apparatus moved on) completes nothing: task 6 stays Incomplete and Continue lands on it', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: true, recorded_by: '', updated: '' }] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 30, deliver_cells: 1 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /users': () => envelope(403, 'forbidden', 'x'),
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      // the API's own verdict on the row: kept, not revoked, but stale — it lifts nothing
      'GET /signoffs': { items: [{ id: 'sgn_1', repo: 'alpha', revoked: false, active: false, stale: true }], total: 1, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 5 of 8 tasks.')).toBeInTheDocument())
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[5]).toHaveTextContent('Read the baseline')
    expect(rows[5]).toHaveTextContent('Incomplete')
    expect(screen.getByRole('link', { name: 'Continue to task 6: Read the baseline' })).toHaveAttribute('href', '/results?repo=alpha')
  })

  it('an App that is configured with no installation on record is "Incomplete", never "Completed" because a repository exists', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'ok', probes: [] },
      'GET /users': () => envelope(403, 'forbidden', 'x'),
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 2 of 8 tasks.')).toBeInTheDocument())
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Incomplete')
  })

  it('with nothing connected every task after the first is not started', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /users': () => envelope(403, 'forbidden', 'x'),
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 0 of 8 tasks.')).toBeInTheDocument())
    expect(screen.getByText('Not configured')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Important' })).not.toBeInTheDocument()
    // the first press goes to choosing a repository, never to an empty Decisions
    expect(screen.getByRole('link', { name: 'Continue to task 2: Choose a repository' })).toHaveAttribute('href', '/connect')
  })
})
