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
 *               the cost statement and "Why two people" are present; and that every
 *               element carries a hint whose copy opens on hover (the task-5 status tag); and
 *               that the north-star tile shows working changes per £ with n, its range in
 *               pounds and its apparatus, reads every repository, and is an honest empty tile
 *               when unmeasured or refused; that an approver reads the progress report, not
 *               "Get started" (G-911); that a recorded read of the baseline completes task 6
 *               with no sign-off (G-165); and that a failed read is an error envelope with
 *               Retry and "Unavailable" on the tasks that stand on it, never "no repository
 *               yet", "Cannot start yet" or "Incomplete" (G-164) — the GitHub App and the
 *               factory runs included, so task 8 never reads "Backlog frozen" on a runs read
 *               that failed; that every GET the page makes, failed alone, reaches the
 *               envelope (a read added later cannot be missed); and that a failed read never
 *               offers "Continue to the factory" — Continue stops at the task it could not
 *               read (P-108); and that task 7 asks `GET /two-person-readiness?repo=` of the
 *               repository shown and never reads Completed for the bootstrap admin alone — a
 *               viewer, or the admin who queued every run, is not a second person (G-477).
 * How:          `mockApi` + `renderApp`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Home/HomePage.tsx, ui/src/screens/Connect/connection.ts,
 *               ui/src/api/hooks.ts (`useActiveRun`, `useSignoffs`), ui/src/help/hints.ts
 *               (the copy the hover test expects), ui/src/help/hints-collector.ts
 *               (`unhinted`)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx
 * Touch when:   never for a new repository; a task or its evidence source changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, expectHintOpens, json, mockApi, renderApp } from '../../test/utils'
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
/** `GET /two-person-readiness` when the deployment can license something (G-518). */
const READY = { ready: true, reason_code: 'ready', reason: 'an account that can sign has signed in, and at least one other account has too, so a sign-off the two-person rule accepts is possible. The product can see accounts, not people', approvers_active: 2, approvers_signed_in: 2, other_active_accounts: 1, accounts_signed_in: 3, invitations_pending: 0 }
const FACTORY_TASK = { id: 'T-1', title: 'x', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'pending', outcome_reason: '', dor_gaps: [], route_hint: '', red_proof: null, build_status: 'not_built', pr_url: null, review_verdict: null, last_event: '', cell_route: { route: '', reason_code: '', reason: '', n: 0, point: 0, ci_low: 0, ci_high: 0, apparatus_versions: [], deliverable: false } }
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

  it('derives the eight tasks from the API and counts the completed ones', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: false, recorded_by: '', updated: '' }] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: 'docker not reachable', data: {} }] },
      'GET /two-person-readiness': READY,
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
      'GET /two-person-readiness': { ...READY, ready: false, reason_code: 'approver_never_signed_in', reason: 'the only account that can sign has never signed in, so it can sign nothing yet — the invitation has not been used', approvers_signed_in: 0, invitations_pending: 1 },
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
    // G-518 — task 7 reads the deployment's real readiness, not the presence of an admin: an
    // invitation that was sent and not used is "In progress", and the note is the server's
    // own reason plus who can act. A non-admin is not sent to a page that refuses them.
    expect(rows[6]).toHaveTextContent('In progress')
    expect(within(rows[6]!).getByRole('link')).toHaveAttribute('href', '/posture')
    expect(screen.getByTestId('home-task-7-note')).toHaveTextContent('has never signed in')
    expect(screen.getByText(/Only an admin can invite somebody/)).toBeInTheDocument()
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
      'GET /two-person-readiness': { ...READY, ready: false, reason_code: 'single_person', reason: 'only one account has ever signed in: whoever runs the measurements would be signing their own evidence, which the API refuses (same_actor)', approvers_signed_in: 1, other_active_accounts: 0, accounts_signed_in: 1 },
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
    expect(rows[6]).toHaveTextContent('Incomplete')
    await waitFor(() => expect(rows[7]).toHaveTextContent('In progress — item 2 of 5'))
    expect(screen.getByRole('link', { name: 'Continue to task 8: Deliver your first change' })).toHaveAttribute('href', '/factory?repo=alpha')
  })

  it('task 7 asks the readiness of the repository shown, and the bootstrap admin alone never reads Completed (G-477)', async () => {
    let readiness: Record<string, unknown> = { ...READY, ready: false, reason_code: 'single_person', reason: 'only one account that can run measurements or sign has ever signed in: whoever runs the measurements would be signing their own evidence, which the API refuses (same_actor) — a viewer is not a second person, because a viewer can do neither', approvers_active: 1, approvers_signed_in: 1, other_active_accounts: 1, accounts_signed_in: 2 }
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: false, recorded_by: '', updated: '' }] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /two-person-readiness': () => json(readiness),
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    const first = renderApp(<HomePage />, { route: '/home?repo=alpha' })
    await waitFor(() => expect(screen.getByText('You have completed 4 of 8 tasks.')).toBeInTheDocument())
    // the question is asked of the repository on the page, not of the deployment
    expect(calls.some((c) => c.path === '/two-person-readiness' && c.url.includes('repo=alpha'))).toBe(true)
    let rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[6]).toHaveTextContent('Invite an approver')
    expect(rows[6]).toHaveTextContent('Incomplete')
    expect(rows[6]).not.toHaveTextContent('Completed')
    expect(screen.getByTestId('home-task-7-note')).toHaveTextContent('a viewer is not a second person')
    first.unmount()
    // an operator exists, but the admin queued every run of this repository and is the only signer
    readiness = { ...readiness, reason_code: 'runner_is_the_only_signer', reason: 'every account that can sign and has signed in queued every run of this repository, so it would be signing its own evidence, which the API refuses (same_actor): invite an approver who did not run them' }
    renderApp(<HomePage />, { route: '/home?repo=alpha' })
    await waitFor(() => expect(screen.getByText('You have completed 4 of 8 tasks.')).toBeInTheDocument())
    rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[6]).toHaveTextContent('Incomplete')
    expect(screen.getByTestId('home-task-7-note')).toHaveTextContent('queued every run of this repository')
    expect(screen.getByTestId('home-task-7-note')).toHaveTextContent('Invite them on the Settings screen')
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
      'GET /two-person-readiness': { ...READY, ready: false, reason_code: 'single_person', reason: 'only one account has ever signed in: whoever runs the measurements would be signing their own evidence, which the API refuses (same_actor)', approvers_signed_in: 1, other_active_accounts: 0, accounts_signed_in: 1 },
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
      'GET /two-person-readiness': { ...READY, ready: false, reason_code: 'single_person', reason: 'only one account has ever signed in: whoever runs the measurements would be signing their own evidence, which the API refuses (same_actor)', approvers_signed_in: 1, other_active_accounts: 0, accounts_signed_in: 1 },
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
      'GET /two-person-readiness': { ...READY, ready: false, reason_code: 'single_person', reason: 'only one account has ever signed in: whoever runs the measurements would be signing their own evidence, which the API refuses (same_actor)', approvers_signed_in: 1, other_active_accounts: 0, accounts_signed_in: 1 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 0 of 8 tasks.')).toBeInTheDocument())
    expect(screen.getByText('Not configured')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Important' })).not.toBeInTheDocument()
    // the first press goes to choosing a repository, never to an empty Decisions
    expect(screen.getByRole('link', { name: 'Continue to task 2: Choose a repository' })).toHaveAttribute('href', '/connect')
  })

  it('the north star tile shows working changes per £ with its n, its range in pounds and its apparatus, and opens its hint', async () => {
    const ns = { label: 'working changes per pound, blind', per_pound: 0.2063, per_pound_low: 0.0581, per_pound_high: 0.5433, pounds_per_working: 4.85, pounds_per_working_low: 1.84, pounds_per_working_high: 17.21, working_rate: 0.072, working_rate_low: 0.02, working_rate_high: 0.19, working_estimate: 6.77, n_attempts: 260, n_valid: 94, n_tasks: 37, clean: 22, clean_tasks: 15, clean_rate: { k: 22, n: 94, point: 0.234, ci_low: 0.16, ci_high: 0.329 }, precision_basis: 'review', precision: { k: 4, n: 13, point: 0.308, ci_low: 0.127, ci_high: 0.576 }, spend_usd: 44.3, spend_gbp: 32.81, usd_per_gbp: 1.35, method: 'estimate' }
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /value': { schema: 'crb.value.v1', repo: null, apparatus: '2.2', apparatus_versions: ['2.2'], pooled: false, rows: 518, usd_per_gbp: 1.35, north_star: ns, learning_curve: { source: 'crb.prevention.register.v1', attempts: 278, register: { source: 'crb.prevention.register.v1', n_classes: 29, closed: 0, closed_share: 0 } } },
    })
    renderApp(<HomePage />, { route: '/home' })
    const tile = await screen.findByTestId('tile-value')
    await waitFor(() => expect(tile).toHaveTextContent('0.21 per £'))
    expect(tile).toHaveTextContent('n =94')
    expect(tile).toHaveTextContent('apparatus 2.2 · blind · estimate')
    // the range is the product of two Wilson bounds: never labelled a 95% interval (P-027)
    expect(tile).toHaveTextContent('range 0.06–0.54 per £ (the product of two 95% Wilson bounds, not itself a 95% interval)')
    expect(tile).not.toHaveTextContent('95% range')
    // n counts attempts; the tasks under them say how independent they are (P-025)
    expect(tile).toHaveTextContent('n = 94 attempts on 37 tasks')
    expect(tile).toHaveTextContent('about £4.85 per working change')
    expect(tile).toHaveTextContent('precision from reviews (n = 13)')
    // the deployment's north star: every repository, never scoped to the kicker's repository
    expect(calls.find((c) => c.path === '/value')?.url).not.toContain('repo=')
    await expectHintOpens(tile, 'stat.home.value')
  })

  it('an unmeasured or refused north star is an honest empty tile, never a zero', async () => {
    const empty = { label: 'x', per_pound: null, per_pound_low: null, per_pound_high: null, pounds_per_working: null, pounds_per_working_low: null, pounds_per_working_high: null, working_rate: null, working_rate_low: null, working_rate_high: null, working_estimate: null, n_attempts: 0, n_valid: 0, clean: 0, clean_rate: { k: 0, n: 0, point: null, ci_low: null, ci_high: null }, precision_basis: 'none', precision: { k: 0, n: 0, point: null, ci_low: null, ci_high: null }, spend_usd: 0, spend_gbp: 0, usd_per_gbp: 1.35, method: 'estimate' }
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /value': { schema: 'crb.value.v1', repo: null, apparatus: '2.2', apparatus_versions: [], pooled: false, rows: 0, usd_per_gbp: 1.35, north_star: empty, learning_curve: { source: 's', attempts: 0, register: { source: 's', n_classes: 0, closed: 0, closed_share: null } } },
    })
    renderApp(<HomePage />, { route: '/home' })
    const tile = await screen.findByTestId('tile-value')
    await waitFor(() => expect(tile).toHaveTextContent('No blind attempt with a precision yet'))
    expect(tile).not.toHaveTextContent('0.00')
    vi.unstubAllGlobals()
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /repos': { items: [], total: 0, limit: 500, offset: 0 }, 'GET /value': () => envelope(409, 'false_q1_refused', 'x') })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getAllByTestId('tile-value').at(-1)).toHaveTextContent('Not available: the API refused the scorecard.'))
  })

  it('a north star over an unpriced blind attempt is withheld with the reason, never divided by a floor', async () => {
    const withheld = { label: 'x', per_pound: null, per_pound_low: null, per_pound_high: null, pounds_per_working: null, pounds_per_working_low: null, pounds_per_working_high: null, working_rate: 0.18, working_rate_low: 0.05, working_rate_high: 0.4, working_estimate: 2, n_attempts: 11, n_valid: 11, clean: 4, clean_rate: { k: 4, n: 11, point: 0.36, ci_low: 0.15, ci_high: 0.65 }, precision_basis: 'proxy', precision: { k: 3, n: 4, point: 0.75, ci_low: 0.3, ci_high: 0.95 }, spend_usd: 20, spend_gbp: 14.81, spend_rows_priced: 10, spend_rows_unpriced: 1, per_pound_withheld: '1 blind attempt carried no price (the builder had none for its model), so the pounds spent are unknown and a figure per pound would overstate; the rate is served, the figure per pound is not', usd_per_gbp: 1.35, method: 'estimate' }
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /value': { schema: 'crb.value.v1', repo: null, apparatus: '2.3', apparatus_versions: ['2.3'], pooled: false, rows: 11, usd_per_gbp: 1.35, north_star: withheld, learning_curve: { source: 's', attempts: 11, register: { source: 's', n_classes: 0, closed: 0, closed_share: null } } },
    })
    renderApp(<HomePage />, { route: '/home' })
    const tile = await screen.findByTestId('tile-value')
    await waitFor(() => expect(tile).toHaveTextContent('1 blind attempt carried no price'))
    expect(tile).not.toHaveTextContent('No blind attempt with a precision yet')
    expect(tile).not.toHaveTextContent('range ')
  })

  it('an approver reads the progress report the About block promises — never "Get started" or "Continue to task n"', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'approver' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 30 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    // the approver's own lede, once the session has loaded (before it, every role reads the viewer's)
    expect(await screen.findByText(/an approver reads what the evidence says and signs what is waiting on them/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/The operators have completed \d of 8 tasks\./)).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Where this deployment is' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Get started' })).not.toBeInTheDocument()
    // the approver's next press is the baseline (the About block's "Read the baseline meanwhile"), not an operator's task
    expect(screen.queryByRole('link', { name: /^Continue to task/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue to the baseline for alpha' })).toHaveAttribute('href', '/results?repo=alpha')
  })

  it('a baseline a person has read completes "Read the baseline" with no sign-off behind it (the server’s record of the read)', async () => {
    const read = { ...REPO, baseline_read: { at: '2026-09-26T09:00:00Z', by: 'ada' } }
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [read], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': read,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 30 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    const rows = await waitFor(() => {
      const r = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
      expect(r[5]).toHaveTextContent('Completed')
      return r
    })
    expect(rows[5]).toHaveTextContent('Read the baseline')
    expect(screen.queryByRole('link', { name: 'Continue to task 6: Read the baseline' })).not.toBeInTheDocument()
  })

  it('a failed read shows the error envelope with Retry and tags the tasks that depend on it "Unavailable" — never "no repository yet"', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': () => envelope(500, 'internal', 'database unavailable'),
      'GET /health': () => envelope(503, 'unavailable', 'health unreadable'),
      'GET /two-person-readiness': () => envelope(500, 'internal', 'readiness unreadable'),
    })
    renderApp(<HomePage />, { route: '/home' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Part of this deployment’s state could not be read')
    expect(alert).toHaveTextContent('the repositories')
    expect(alert).toHaveTextContent('the deployment’s health')
    await waitFor(() => expect(alert).toHaveTextContent('the deployment’s two-person readiness'))
    expect(document.body).not.toHaveTextContent('no repository yet')
    expect(screen.getByText('repositories unavailable')).toBeInTheDocument()
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    for (const i of [1, 2, 3, 4, 5, 6, 7]) expect(rows[i], `task ${i + 1}`).toHaveTextContent('Unavailable')
    expect(rows[6]).not.toHaveTextContent('Not known yet')
    // Retry asks again for every read that failed, and only for those
    const before = calls.filter((c) => c.path === '/repos').length
    await userEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/repos').length).toBeGreaterThan(before))
    expect(calls.some((c) => c.path === '/two-person-readiness' && c.method === 'GET')).toBe(true)
  })

  it('a failed capability map or sign-off read makes the tasks that read it "Unavailable", never "Cannot start yet" or "Incomplete"', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': () => envelope(500, 'internal', 'ledger unreadable'),
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': () => envelope(500, 'internal', 'signoffs unreadable'),
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    const alert = await screen.findByRole('alert')
    await waitFor(() => expect(alert).toHaveTextContent('the sign-offs'))
    expect(alert).toHaveTextContent('the capability map')
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[4]).toHaveTextContent('Unavailable')
    expect(rows[5]).toHaveTextContent('Unavailable')
    expect(rows[7]).toHaveTextContent('Unavailable')
    // the tasks that do not read the failed reads keep their honest status
    expect(rows[1]).toHaveTextContent('Completed')
    expect(rows[3]).toHaveTextContent('Completed')
  })

  it('a failed read of the GitHub App or of the factory runs is named in the envelope, and task 8 is "Unavailable", never "Backlog frozen"', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': () => envelope(500, 'internal', 'app unreadable'),
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 30, deliver_cells: 1 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /factory/alpha/backlog': { repo: 'alpha', hash: 'b'.repeat(64), frozen_at: '2026-09-17T10:00:00Z', items: [] },
      'GET /factory/alpha/tasks': [FACTORY_TASK],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': () => envelope(500, 'internal', 'runs unreadable'),
    })
    renderApp(<HomePage />, { route: '/home' })
    const alert = await screen.findByRole('alert')
    await waitFor(() => expect(alert).toHaveTextContent('the GitHub App'))
    await waitFor(() => expect(alert).toHaveTextContent('the factory runs'))
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Unavailable')
    // a status built on a read that failed is never shown: no run could be read, so none is claimed absent
    expect(rows[7]).toHaveTextContent('Unavailable')
    expect(rows[7]).not.toHaveTextContent('Backlog frozen')
  })

  it('a failed read never offers "Continue to the factory": Continue stops at the first task it could not read', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: true, recorded_by: '', updated: '' }] },
      'GET /repos': () => envelope(500, 'internal', 'database unavailable'),
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await screen.findByRole('alert')
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    await waitFor(() => expect(rows[0]).toHaveTextContent('Completed'))
    expect(rows[1]).toHaveTextContent('Unavailable')
    expect(screen.queryByRole('link', { name: 'Continue to the factory' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue to task 2: Choose a repository' })).toHaveAttribute('href', '/connect')
  })

  it('every read Home makes, when it alone fails, is named in the error envelope — a read added later cannot be missed', async () => {
    const app = { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: true, recorded_by: '', updated: '' }] }
    const ok: Record<string, unknown> = {
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /github/app': app,
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 30, deliver_cells: 1 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /two-person-readiness': READY,
      'GET /factory/alpha/backlog': { repo: 'alpha', hash: 'b'.repeat(64), frozen_at: '2026-09-17T10:00:00Z', items: [] },
      'GET /factory/alpha/tasks': [FACTORY_TASK],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    }
    // every GET the page makes when all is well: the session is the shell's, and the north-star
    // tile reads /value and states its own failure (the tile's tests), so neither is Home's task list
    const first = mockApi(ok)
    const view = renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText(/You have completed \d of 8 tasks\./)).toBeInTheDocument())
    await waitFor(() => expect(first.calls.some((c) => c.path === '/runs')).toBe(true))
    const reads = [...new Set(first.calls.filter((c) => c.method === 'GET').map((c) => c.path))].filter((p) => p !== '/auth/me' && p !== '/value')
    for (const p of Object.keys(ok).map((k) => k.slice(4))) if (p !== '/auth/me') expect(reads, `Home no longer reads ${p}`).toContain(p)
    view.unmount()
    vi.unstubAllGlobals()
    for (const path of reads) {
      mockApi({ ...ok, [`GET ${path}`]: () => envelope(500, 'internal', `${path} unreadable`) })
      const one = renderApp(<HomePage />, { route: '/home' })
      await waitFor(() => expect(screen.queryByRole('alert'), `a failed GET ${path} showed no error envelope`).toBeInTheDocument())
      // and a task left unknown by it stops Continue: a failed read never skips on to the factory
      expect(screen.queryByRole('link', { name: 'Continue to the factory' }), path).not.toBeInTheDocument()
      one.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('every task tag, the kicker, the summary, the banner and Continue carry a hint; the Measure tag opens on hover with the registry copy', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: 'docker not reachable', data: {} }] },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', 'no backlog'),
      'GET /factory/alpha/tasks': [],
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /runs': { items: [], total: 0, limit: 20, offset: 0 },
    })
    const { container } = renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 3 of 8 tasks.')).toHaveAttribute('data-hint', 'stat.home.completed'))
    expect(unhinted(container)).toEqual([])
    for (const id of ['stat.home.kicker', 'banner.home.sandbox', 'button.home.continue', 'task.home.connect_github', 'task.home.deliver']) {
      expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    // the status tag sits inside the task's link: the link is the tab stop, the tag is the trigger
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    const tag = rows[4]!.querySelector('[data-hint="task.home.measure"]')!
    expect(tag).not.toHaveAttribute('tabindex')
    await expectHintOpens(tag, 'task.home.measure')
  })
})
