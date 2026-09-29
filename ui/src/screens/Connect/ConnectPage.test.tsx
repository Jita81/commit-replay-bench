/**
 * ConnectPage — the walk resumes where the repository is; actions are role-gated.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Connect list and the per-repository task list.
 * What it does: Pins that the list shows each repository's next stage and names the door
 *               "Baseline" (J-ONR-14); that the per-repo page renders six stages with the
 *               API-derived statuses (a 404 oracle/controls = not started, not an error)
 *               under the journey eyebrow; that the operator's action on the next stage
 *               posts the right run kind (`POST /runs {kind: mine}`) and the probe posts to
 *               its own route; that a viewer sees the stage and a sentence, not a bare
 *               "operator" (J-ONR-15); that a running measurement renders the in-flight
 *               panel from the polled run — attempts, spend, started, and a Cancel that asks
 *               in the app's own dialog and posts only once "Cancel the run" is confirmed,
 *               nothing on "Keep it running" (J-ONR-5, G-117) — and a queued run reads
 *               "Queued" with its place in the line (J-TEL-6); that every element on both
 *               screens carries a hint, the door column's hidden header included (G-127),
 *               with a stage-summary pill and a stage title opening on hover; that a
 *               row, and the walk, whose oracle, controls or map read fails for a reason other
 *               than 404 shows the error with Retry, never a stage state — each of the three
 *               reads failing on its own, and on the walk with no stage action offered (G-124,
 *               G-730); that a viewer is offered no Connect control on the list or its empty
 *               state (G-126); that the header offers every role All repositories (G-228);
 *               that the walk's Measure… opens the Measure page and posts nothing (G-907);
 *               that an unknown name says so and offers Connection while a 500 offers Retry
 *               (G-979); and that the mine stage lists the config candidates the notes imply
 *               with Accept and Reject for an operator only (DL-316). No test stubs
 *               `window.confirm`: the product has none.
 * How:          `mockApi` + `renderApp` with `path` set so `useParams` resolves; the Measure
 *               door is proved with a second route mounted beside the walk.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (under test), connection.ts,
 *               ui/src/help/hints.ts (the copy the hover tests expect),
 *               ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx
 * Touch when:   never for a new repository; a stage or its action changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, expectHintOpens, json, mockApi, renderApp } from '../../test/utils'
import { ConnectPage, ConnectRepoPage } from './ConnectPage'

/**
 * G-117's class: a native `window.confirm` carries no hint, cannot be reached by the hint
 * ratchet and is invisible to axe. Every source of the app as text (Vite's raw import), so a
 * new one anywhere in ui/src fails here — the question is always the app's own `Dialog`.
 */
const SOURCES = import.meta.glob('../../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** The walk's mine stage reads the candidates (DL-316); most walks imply none. */
const NO_CANDIDATES = { 'GET /repos/alpha/config-candidates': { repo: 'alpha', items: [] } }

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
const MEASURED = { ...REPO, task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 } }
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
const EMPTY_MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [], summary: { trusted_autonomy_coverage: 0, total_cells: 0, measured_cells: 0, deliver_cells: 0, n_total: 0, false_q1_total: 0, apparatus_versions: [] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

describe('no screen asks a question through window.confirm (G-117)', () => {
  it('no source under ui/src calls confirm(); the app Dialog asks instead', () => {
    const offenders = Object.entries(SOURCES)
      .filter(([path]) => !/\.test\.tsx?$/.test(path))
      .filter(([, text]) => /\b(?:window\.|globalThis\.)?confirm\s*\(/.test(text))
      .map(([path]) => path)
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50) // the glob matched the app, not nothing
    expect(offenders).toEqual([])
  })
})

describe('ConnectPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists connected repositories with their next stage', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 } })
    renderApp(<ConnectPage />, { route: '/connect' })
    await waitFor(() => expect(screen.getByRole('table', { name: 'Connected repositories' })).toBeInTheDocument())
    expect(screen.getByText('commits mined into tasks')).toBeInTheDocument() // the next stage after a good probe
    expect(screen.getByRole('link', { name: 'Continue' })).toHaveAttribute('href', '/connect/alpha')
    // gold-clean carries its definition one click away
    expect(screen.getByRole('button', { name: /gold-clean/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Journey · 1 of 4 · Connection')).toBeInTheDocument()
  })

  // G-124: each of the row's three reads, failing on its own while the other two answer
  const FAILING_READS = [
    { read: 'oracle', route: 'GET /oracle/alpha', title: 'Could not read the oracle scores' },
    { read: 'controls', route: 'GET /oracle/alpha/controls', title: 'Could not read the controls report' },
    { read: 'capability map', route: 'GET /capability-map', title: 'Could not read the capability map' },
  ] as const
  it.each(FAILING_READS)('a row whose $read read fails (not 404) shows the error with Retry, never a stage state (G-124)', async ({ route, title }) => {
    const reads: string[] = []
    const answering: Record<string, unknown> = {
      'GET /oracle/alpha': () => envelope(404, 'not_measured', 'no oracle scores'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_measured', 'no controls report'),
      'GET /capability-map': EMPTY_MAP,
    }
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [MEASURED], total: 1, limit: 500, offset: 0 },
      ...answering,
      [route]: () => {
        reads.push(route)
        return envelope(503, 'store_unavailable', 'the store is not answering')
      },
    })
    renderApp(<ConnectPage />, { route: '/connect' })
    const err = await screen.findByTestId('connect-row-error')
    expect(err).toHaveTextContent(title)
    expect(err).toHaveTextContent('the store is not answering')
    expect(err).toHaveTextContent('HTTP 503')
    // no stage state is shown in its place: the walk cannot know the stage without the read
    expect(document.querySelector('[data-hint="pill.connect.stage_summary"]')).toBeNull()
    const before = reads.length
    await userEvent.click(within(err).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(reads.length).toBeGreaterThan(before))
  })

  it('a 404 on the oracle or the controls is never run, not an error: the row reads its stage (G-124)', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 } })
    renderApp(<ConnectPage />, { route: '/connect' })
    await screen.findByText('commits mined into tasks')
    expect(screen.queryByTestId('connect-row-error')).toBeNull()
  })

  it('a viewer is offered neither connect button nor the empty state’s Connect, and reads the list (G-126)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'https://github.com/apps/crb/installations/new', api_url: '', installations: [] },
    })
    renderApp(<ConnectPage />, { route: '/connect' })
    await screen.findByText('No repository connected yet')
    expect(screen.queryByRole('button', { name: /Connect/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /Connect/ })).toBeNull()
  })

  it('a measured repository\'s door is named Baseline, the same as the nav, and opens the baseline', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [MEASURED], total: 1, limit: 500, offset: 0 },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 22 } },
    })
    renderApp(<ConnectPage />, { route: '/connect' })
    // the button does what its name says: it lands on /results, not on the walk (a second Baseline away)
    await waitFor(() => expect(screen.getByRole('link', { name: 'Baseline' })).toHaveAttribute('href', '/results?repo=alpha'))
    expect(screen.queryByRole('link', { name: 'Results' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Continue' })).not.toBeInTheDocument()
    // the repository link is still the door to the walk
    expect(screen.getByRole('link', { name: 'alpha' })).toHaveAttribute('href', '/connect/alpha')
  })

  it('every column header, pill and button on the list carries a hint; the stage-summary pill opens on hover with the registry copy', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'operator' }, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 }, 'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] } })
    const { container } = renderApp(<ConnectPage />, { route: '/connect' })
    await waitFor(() => expect(screen.getByRole('table', { name: 'Connected repositories' })).toBeInTheDocument())
    expect(unhinted(container)).toEqual([])
    expect(container.querySelectorAll('th[scope="col"] [data-hint^="col.connect."]').length).toBe(6)
    expect(screen.getByRole('button', { name: 'Connect by URL' })).toHaveAttribute('data-hint', 'button.connect.url')
    expect(screen.getByRole('link', { name: 'Continue' })).toHaveAttribute('data-hint', 'button.connect.row_action')
    const pill = container.querySelector('[data-hint="pill.connect.stage_summary"]')!
    await expectHintOpens(pill, 'pill.connect.stage_summary')
  })

  it('every stage title, status pill, detail line and action on the walk carries a hint; the oracle stage title opens on hover', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 4 } },
      'GET /runs/r9': RUN,
      ...NO_CANDIDATES,
    })
    const { container } = renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('in-flight')).toBeInTheDocument())
    expect(unhinted(container)).toEqual([])
    for (const id of ['stage.walk.register', 'stage.walk.probe', 'stage.walk.mine', 'stage.walk.oracle', 'stage.walk.controls', 'stage.walk.measure', 'pill.walk.stage_status', 'stat.walk.stage_detail', 'button.walk.configuration', 'button.walk.baseline', 'stat.walk.inflight_progress', 'stat.walk.inflight_spend', 'link.walk.inflight_open', 'button.walk.cancel']) {
      expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    // the title holds a Term button: the wrapper is not a second tab stop, and hovering it explains the stage
    const title = screen.getByTestId('stage-oracle').querySelector('[data-hint="stage.walk.oracle"]')!
    expect(within(title as HTMLElement).getByRole('button', { name: 'Oracle strength' })).toBeInTheDocument()
    expect(title).not.toHaveAttribute('tabindex')
    await expectHintOpens(title, 'stage.walk.oracle')
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
      ...NO_CANDIDATES,
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
    expect(screen.getByRole('link', { name: 'Baseline' })).toHaveAttribute('href', '/results?repo=alpha')
    expect(screen.getByText('Journey · 1 of 4 · Connection')).toBeInTheDocument()
  })

  it.each(FAILING_READS)('the walk whose $read read fails (not 404) says so with Retry, shows no stage state and offers no stage action (G-730)', async ({ route, title }) => {
    const reads: string[] = []
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6, apparatus: { controls_version: 'controls.v3' } },
      'GET /capability-map': EMPTY_MAP,
      ...NO_CANDIDATES,
      [route]: () => {
        reads.push(route)
        return envelope(503, 'store_unavailable', 'the store is not answering')
      },
    })
    const { container } = renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const err = await screen.findByTestId('connect-walk-error')
    expect(unhinted(container)).toEqual([])
    expect(err).toHaveTextContent(title)
    expect(err).toHaveTextContent('HTTP 503')
    // no stage reads "Not started" in the read's place, and nothing is offered to run or spend
    expect(screen.queryByTestId('stage-measure')).toBeNull()
    expect(screen.queryByText('Not started')).toBeNull()
    expect(screen.queryByRole('button', { name: /^(Run|Measure…)$/ })).toBeNull()
    // the only Retry is the read's own, never a stage's
    expect(screen.getAllByRole('button', { name: 'Retry' })).toEqual([within(err).getByRole('button', { name: 'Retry' })])
    expect(document.body).toHaveTextContent('cannot say where this repository is')
    const before = reads.length
    await userEvent.click(within(err).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(reads.length).toBeGreaterThan(before))
  })

  it('a viewer sees the walk but no action', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': { ...REPO, probe: { status: 'not_probed', run_id: null, checked: null, detail: '' } },
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      ...NO_CANDIDATES,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-probe')).toHaveTextContent('Not started'))
    expect(screen.queryByRole('button', { name: /^Run$/ })).not.toBeInTheDocument()
    expect(screen.getByTestId('stage-probe')).toHaveTextContent('An operator runs this.')
  })

  it('a viewer on the measure stage is told it spends, in a sentence', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      ...NO_CANDIDATES,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Not started'))
    expect(screen.getByTestId('stage-measure')).toHaveTextContent('An operator starts this; it spends model budget.')
    expect(screen.queryByRole('button', { name: /^Measure…$/ })).not.toBeInTheDocument()
  })

  it('a running measurement shows attempts, spend, started and a Cancel that confirms before posting (J-ONR-5)', async () => {
    // no window.confirm: the question is the app's own dialog (G-117)
    let cancelled = false
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 4 } },
      // the run is re-read after the cancel answers (useCancelRun), so the mock answers it live
      'GET /runs/r9': () => json({ ...RUN, cancel_requested: cancelled }),
      'POST /runs/r9/cancel': () => {
        cancelled = true
        return json({ ...RUN, cancel_requested: true })
      },
      ...NO_CANDIDATES,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('In progress'))
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Measuring — attempt 3 of 10 · $0.42 so far, builder-reported (4 rows already on the current apparatus)'))
    const panel = screen.getByTestId('in-flight')
    // the progress line is a polite live region (it changes every poll: attempt, spend) — the
    // link and the Cancel button sit outside it, so they are never re-announced
    const status = within(panel).getByRole('status')
    expect(status).toHaveTextContent(/Attempt 3 of 10 · \$0\.42 spent so far · started \d{2}:\d{2}\./)
    expect(status).toHaveTextContent('Rows land on the baseline as each attempt is graded; when the run finishes this stage turns Done and the Baseline button fills in.')
    expect(within(status).queryByRole('link')).toBeNull()
    expect(within(status).queryByRole('button')).toBeNull()
    expect(within(panel).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/runs/r9')
    // no second spend is offered while the run is in flight
    expect(screen.queryByRole('button', { name: /^Measure…$/ })).not.toBeInTheDocument()
    const posted = () => calls.some((c) => c.method === 'POST' && c.path === '/runs/r9/cancel')
    // the question opens; nothing is posted until it is answered
    await userEvent.click(within(panel).getByRole('button', { name: 'Cancel the run' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAccessibleName('Cancel this run?')
    expect(dialog).toHaveTextContent('Attempts already made are still charged.')
    expect(posted()).toBe(false)
    // Keep it running: the question closes and nothing is posted
    await userEvent.click(within(dialog).getByRole('button', { name: 'Keep it running' }))
    await waitFor(() => expect(screen.queryByTestId('cancel-confirm')).toBeNull())
    expect(posted()).toBe(false)
    // asked again and confirmed: the cancel is posted and the run re-read says so
    await userEvent.click(within(panel).getByRole('button', { name: 'Cancel the run' }))
    const again = await screen.findByRole('dialog')
    expect(within(again).getByRole('button', { name: 'Keep it running' })).toHaveAttribute('data-hint', 'button.connect.cancel_keep')
    expect(within(again).getByRole('button', { name: 'Cancel the run' })).toHaveAttribute('data-hint', 'button.connect.cancel_confirm')
    await userEvent.click(within(again).getByRole('button', { name: 'Cancel the run' }))
    await waitFor(() => expect(posted()).toBe(true))
    await waitFor(() => expect(screen.queryByTestId('cancel-confirm')).toBeNull())
    await waitFor(() => expect(panel).toHaveTextContent('Cancel requested — the worker stops between attempts.'))
  })

  it('every column of the connected-repositories table has an accessible header, the door column included', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 } })
    renderApp(<ConnectPage />, { route: '/connect' })
    const table = await screen.findByRole('table', { name: 'Connected repositories' })
    const headers = within(table).getAllByRole('columnheader')
    expect(headers).toHaveLength(6)
    for (const th of headers) expect((th.textContent ?? '').trim(), 'an empty th names nothing').not.toBe('')
    // the door column's name is for a screen reader: hidden, hinted, never drawn
    const door = headers[5]!
    expect(door).toHaveTextContent('Next')
    expect(door.querySelector('.sr-only')).not.toBeNull()
    expect(door.querySelector('[data-hint="col.connect.next"]')).not.toBeNull()
  })

  it('the Connection header offers All repositories to every role (G-228)', async () => {
    for (const role of ['viewer', 'operator', 'admin'] as const) {
      vi.unstubAllGlobals()
      mockApi({ 'GET /auth/me': { ...PRINCIPAL, role }, 'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 }, 'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] } })
      const { unmount } = renderApp(<ConnectPage />, { route: '/connect' })
      const door = await screen.findByRole('link', { name: 'All repositories' })
      expect(door).toHaveAttribute('href', '/repos')
      expect(door).toHaveAttribute('data-hint', 'button.connect.all_repos')
      unmount()
    }
  })

  it('the walk’s Measure… opens the Measure page, never the run form, and posts nothing (G-907)', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      ...NO_CANDIDATES,
    })
    renderApp(
      <Routes>
        <Route path="/connect/:name" element={<ConnectRepoPage />} />
        <Route path="/connect/:name/measure" element={<h1>Measure page</h1>} />
      </Routes>,
      { route: '/connect/alpha', path: '*' },
    )
    const measure = await screen.findByRole('button', { name: 'Measure…' })
    expect(measure).toHaveAttribute('data-hint', 'button.walk.run_stage')
    await userEvent.click(measure)
    await screen.findByRole('heading', { name: 'Measure page' })
    // no run form opened and nothing was posted: the Measure page is where the spend is confirmed
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('a failed replay’s Retry takes the same door to the Measure page (G-907)', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'failed', finished: 'x' } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      ...NO_CANDIDATES,
    })
    renderApp(
      <Routes>
        <Route path="/connect/:name" element={<ConnectRepoPage />} />
        <Route path="/connect/:name/measure" element={<h1>Measure page</h1>} />
      </Routes>,
      { route: '/connect/alpha', path: '*' },
    )
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Failed'))
    await userEvent.click(within(screen.getByTestId('stage-measure')).getByRole('button', { name: 'Retry' }))
    await screen.findByRole('heading', { name: 'Measure page' })
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('an unknown repository says so and offers Connection, not a bare retry (G-979)', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos/ghost': () => envelope(404, 'not_found', "no repo 'ghost'"),
      'GET /oracle/ghost': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/ghost/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      'GET /repos/ghost/config-candidates': () => envelope(404, 'not_found', "no repo 'ghost'"),
    })
    const { container } = renderApp(<ConnectRepoPage />, { route: '/connect/ghost', path: '/connect/:name' })
    const state = await screen.findByTestId('unknown-repo')
    expect(state).toHaveTextContent('No repository called ghost')
    expect(within(state).getByRole('link', { name: 'Open Connection' })).toHaveAttribute('href', '/connect')
    expect(within(state).getByRole('link', { name: 'Open Connection' })).toHaveAttribute('data-hint', 'button.shared.unknown_repo')
    expect(container).toHaveTextContent('Not found')
    // not an error, no retry, no stage list and no door to a configuration that does not exist
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(screen.queryByRole('list', { name: 'Connection stages' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Configuration' })).toBeNull()
    expect(unhinted(container)).toEqual([])
  })

  it('a repository read that fails for another reason is an error with Retry, not a missing repository (G-979)', async () => {
    const reads: string[] = []
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos/alpha': () => {
        reads.push('repo')
        return envelope(500, 'internal_error', 'the store is not answering')
      },
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      ...NO_CANDIDATES,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const err = await screen.findByRole('alert')
    expect(err).toHaveTextContent('the store is not answering')
    expect(err).toHaveTextContent('HTTP 500')
    expect(screen.queryByTestId('unknown-repo')).toBeNull()
    const before = reads.length
    await userEvent.click(within(err).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(reads.length).toBeGreaterThan(before))
  })

  const CANDIDATES = {
    repo: 'alpha',
    items: [
      { id: 'raise_test_timeout:runner_opts.timeout:1800', kind: 'raise_test_timeout', scope: 'repo', field: 'runner_opts.timeout', observed: 900, proposed: 1800, reason: '2 commit(s) hit the 900 s test wall clock at the parent, the baseline or the gold; raising it lets them qualify', sources: ['a'.repeat(40), 'b'.repeat(40)] },
      { id: 'provisioning_on:CRB_PROVISION__ENABLED:True', kind: 'provisioning_on', scope: 'deployment', field: 'CRB_PROVISION__ENABLED', observed: null, proposed: true, reason: '1 commit(s) could not load their dependencies offline; switch dependency provisioning on for this deployment (docs/DEPLOYMENT.md §3.4), then qualify again', sources: ['c'.repeat(40)] },
    ],
  }

  it('the mine stage lists the config changes the notes imply; an operator accepts or rejects each, and a deployment setting has no Accept (DL-316)', async () => {
    let decided = ''
    // the hook encodes the id (its colons) in the path, as any id must be
    const ACCEPT = `/repos/alpha/config-candidates/${encodeURIComponent('raise_test_timeout:runner_opts.timeout:1800')}/accept`
    const { calls, fetchMock } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      'GET /repos/alpha/config-candidates': () => json(decided ? { repo: 'alpha', items: CANDIDATES.items.filter((c) => c.id !== decided) } : CANDIDATES),
      [`POST ${ACCEPT}`]: () => {
        decided = 'raise_test_timeout:runner_opts.timeout:1800'
        return json({ repo: 'alpha', id: decided, decision: 'accepted', candidate: CANDIDATES.items[0], config: { ...MEASURED.config, runner_opts: { timeout: 1800 } } })
      },
    })
    const { container } = renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const panel = await screen.findByTestId('config-candidates')
    expect(within(screen.getByTestId('stage-mine')).getByTestId('config-candidates')).toBe(panel)
    expect(panel).toHaveTextContent('The mine notes imply 2 configuration changes. Nothing changes until an operator decides.')
    const timeout = within(panel).getByTestId('candidate-raise_test_timeout')
    expect(timeout).toHaveTextContent('runner_opts.timeout: 900 s → 1800 s')
    expect(timeout).toHaveTextContent('(2 commits)')
    expect(within(timeout).getByRole('button', { name: 'Accept' })).toHaveAttribute('data-hint', 'button.walk.candidate_accept')
    expect(within(timeout).getByRole('button', { name: 'Reject' })).toHaveAttribute('data-hint', 'button.walk.candidate_reject')
    // a deployment setting is named, never applied from here
    const env = within(panel).getByTestId('candidate-provisioning_on')
    expect(env).toHaveTextContent('CRB_PROVISION__ENABLED → true (a deployment setting)')
    expect(within(env).queryByRole('button', { name: 'Accept' })).toBeNull()
    expect(within(env).getByRole('button', { name: 'Reject' })).toBeInTheDocument()
    expect(unhinted(container)).toEqual([])
    await expectHintOpens(timeout.querySelector('[data-hint="stat.walk.candidate"]')!, 'stat.walk.candidate')
    // nothing was posted by reading; Accept posts the decision and the list is re-read without it
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    await userEvent.click(within(timeout).getByRole('button', { name: 'Accept' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === ACCEPT)).toBe(true))
    await waitFor(() => expect(within(panel).queryByTestId('candidate-raise_test_timeout')).toBeNull())
    expect(panel).toHaveTextContent('The mine notes imply a configuration change.')
    expect(fetchMock).toHaveBeenCalled()
  })

  it('a viewer reads the candidates and is told an operator decides; a failed read is said with Retry (DL-316)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      'GET /repos/alpha/config-candidates': CANDIDATES,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const panel = await screen.findByTestId('config-candidates')
    expect(within(panel).queryByRole('button', { name: /Accept|Reject/ })).toBeNull()
    expect(within(panel).getAllByText('An operator decides this.')).toHaveLength(2)
    vi.unstubAllGlobals()
    const reads: string[] = []
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      'GET /repos/alpha/config-candidates': () => {
        reads.push('c')
        return envelope(503, 'store_unavailable', 'the store is not answering')
      },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const err = await screen.findByTestId('config-candidates-error')
    expect(err).toHaveTextContent('Could not read the config candidates')
    const before = reads.length
    await userEvent.click(within(err).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(reads.length).toBeGreaterThan(before))
  })

  it('a queued run reads Queued with the server’s queue_position (the worker’s own order), never a client recount (J-TEL-6)', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'queued', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /runs/r9': { ...RUN, status: 'queued', started: null, progress: { done: 0, total: 0, current_task_id: null }, cost_usd: 0, queue_position: 3, queue_kinds_ahead: ['replay', 'mine'] },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Queued — 2 runs ahead of it'))
    // the queued list is not read when the server states the position
    expect(calls.some((c) => c.method === 'GET' && c.path === '/runs')).toBe(false)
  })

  it('an older server that sends no queue_position: the place in the line falls back to the queued list', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'queued', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /runs/r9': { ...RUN, status: 'queued', started: null, progress: { done: 0, total: 0, current_task_id: null }, cost_usd: 0 },
      'GET /runs': { items: [{ ...RUN, id: 'r7', created: '2026-09-19T09:00:00Z', status: 'queued' }, { ...RUN, status: 'queued' }], total: 2, limit: 200, offset: 0 },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Queued — 1 run ahead of it'))
    expect(within(screen.getByTestId('stage-measure')).getByText('Queued', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByTestId('stage-measure')).not.toHaveTextContent('In progress')
    expect(screen.getByTestId('in-flight')).toHaveTextContent('Waiting for a worker')
  })

  it('a queued run that still carries progress (reclaimed after a stale worker) reads Waiting, never an attempt in hand', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/alpha': { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'queued', finished: null } },
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      // the counts the run had before it was reclaimed are still on the row
      'GET /runs/r9': { ...RUN, status: 'queued', started: null, progress: { done: 2, total: 10, current_task_id: null }, cost_usd: 0.42, queue_position: 1, queue_kinds_ahead: [] },
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    await waitFor(() => expect(screen.getByTestId('stage-measure')).toHaveTextContent('Queued'))
    const status = within(screen.getByTestId('in-flight')).getByRole('status')
    expect(status).toHaveTextContent('Waiting for a worker')
    expect(status).not.toHaveTextContent(/Attempt \d/)
  })
  it('an amber controls stage links to the strengthen report on Learn (G-348, G-432)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/alpha': MEASURED,
      'GET /oracle/alpha': { repo: 'alpha', policy: { autoship_floor: 0.8, adequate_floor: 0.5, version: 'adequacy.v1' }, tasks: [{ task_id: 'a'.repeat(40), capability_class: 'bug.fix', size: 'S', strength: 0.6, band: 'adequate', mutants: 10, killed: 6, gate: 'human' }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { repo: 'alpha', run_id: 'r1', passed: true, n_rows: 7, n_tasks: 1, violations: 0, escapes: 1, not_constructible: 1, skipped: 0, rows: [] },
      'GET /capability-map': EMPTY_MAP,
    })
    renderApp(<ConnectRepoPage />, { route: '/connect/alpha', path: '/connect/:name' })
    const stage = await screen.findByTestId('stage-controls')
    await waitFor(() => expect(stage).toHaveTextContent('Done, with a finding'))
    expect(within(stage).getByRole('link', { name: 'Strengthen the tests on Learn' })).toHaveAttribute('href', '/learn?repo=alpha#strengthen')
    // a stage with no finding carries no such link
    expect(within(screen.getByTestId('stage-probe')).queryByRole('link', { name: 'Strengthen the tests on Learn' })).toBeNull()
  })
})
