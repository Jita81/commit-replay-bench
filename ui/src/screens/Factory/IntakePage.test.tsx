/**
 * The intake screen — default OFF, the three acts, and never a number it invented.
 *
 * Navigation
 * ----------
 * What it is:   The intake screen's suite: what a viewer sees when nothing is switched on,
 *               what each act sends and what its success state says, and how a stop is shown.
 * What it does: Pins that the listener reads "Not listening" until somebody switches it on
 *               and that a viewer is told who can, that "Switch the listener on" sends the
 *               PUT and reports the column and the interval, that "Re-read the column now"
 *               and "Post the feedback again" send the poll with and without `force` and
 *               report tickets read, comments posted and items registered, that a stop shows
 *               the server's reason AND the server's advice, that an unmeasured cell is
 *               named rather than shown as zero, and that the credential is never rendered.
 * How:          `mockApi` + `renderApp` at `/factory/intake?repo=alpha`; every response is
 *               the shape `src/crb/server/routes/factory.py` serves.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
 * Works with:   ui/src/screens/Factory/IntakePage.tsx (under test), ui/src/api/types.ts
 *               (`Intake`), src/crb/server/routes/factory.py (the shapes mirrored here),
 *               ui/src/test/utils.tsx, tests/test_server_routes_intake.py (the same journey
 *               against the real server)
 * Tested by:    ui/src/screens/Factory/IntakePage.test.tsx
 * Touch when:   an act is added to the screen; a field is added to the intake response.
 */
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { Intake } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { IntakePage } from './IntakePage'

const DELIVER = { route: 'deliver', reason_code: 'deliver', reason: 'ok', n: 42, point: 0.95, ci_low: 0.83, ci_high: 0.99, apparatus_versions: ['2.2'], deliverable: true }
const REPOS = { items: [{ name: 'alpha', language: 'python', runner: 'pytest', url: '', created: '2026-09-01T10:00:00+00:00' }], total: 1, limit: 50, offset: 0 }

const CONNECTION: Intake['connection'] = {
  tracker: 'ado',
  url: 'https://dev.azure.invalid/contoso',
  project: 'Widgets',
  column: 'Ready for manufacture',
  poll_s: 300,
  outcome_map: {},
  configured: true,
  credential_set: true,
  credential_fingerprint: 'AB12',
}

const OFF: Intake = {
  repo: 'alpha',
  listener: { enabled: false, column: '', switched_by: '', switched_at: '', since: '' },
  connection: CONNECTION,
  last_poll: null,
  rows: [],
}

const READY_ROW: Intake['rows'][number] = {
  key: '4711',
  title: 'Fix the crash when the cart is empty',
  url: 'https://dev.azure.invalid/contoso/Widgets/_workitems/edit/4711',
  revision: '3',
  label: 'crb:queued',
  state: 'Ready for manufacture',
  item_id: 'ado-4711',
  item_url: '/factory?repo=alpha&item=ado-4711',
  feedback: 'Commit Replay Bench: this ticket is ready to manufacture.',
  open_questions: [],
  capability_class: 'bug.fix',
  confidence: 0.67,
  size: 'S',
  registered: true,
  is_evolution: false,
  supersedes: '',
  cell_route: DELIVER,
  read_at: '2026-09-22T09:05:00+00:00',
  stopped: '',
  stopped_advice: '',
}

const NEEDS_INFO_ROW: Intake['rows'][number] = {
  ...READY_ROW,
  key: '4712',
  title: 'Add a POST /health route',
  label: 'crb:needs-info',
  item_id: 'ado-4712',
  item_url: '/factory?repo=alpha&item=ado-4712',
  feedback: 'Commit Replay Bench: this ticket needs more information before anything is built.',
  open_questions: [{ ref: 'ado-4712::backend.route.add::response_shape', severity: 'blocking', reason: 'What is the response shape (status code, body fields and types)?' }],
  capability_class: 'backend.route.add',
  confidence: 0.5,
  registered: false,
  cell_route: null,
}

const ON: Intake = {
  ...OFF,
  listener: { enabled: true, column: 'Ready for manufacture', switched_by: 'Ada', switched_at: '2026-09-22T09:00:00+00:00', since: '' },
  last_poll: { repo: 'alpha', column: 'Ready for manufacture', seen: 2, read: 2, skipped: 0, commented: 2, registered: 1, queued: 0, stopped: '', detail: '', advice: '', at: '2026-09-22T09:05:00+00:00' },
  rows: [READY_ROW, NEEDS_INFO_ROW],
}

function setup(intake: Intake, extra: Record<string, unknown> = {}) {
  const api = mockApi({
    'GET /auth/me': PRINCIPAL,
    'GET /repos': REPOS,
    'GET /factory/alpha/intake': intake,
    ...extra,
  })
  renderApp(<IntakePage />, { route: '/factory/intake?repo=alpha', path: '/factory/intake' })
  return api
}

afterEach(cleanup)

describe('IntakePage', () => {
  it('says the listener is off, and that is the default for every repository', async () => {
    setup(OFF)
    expect(await screen.findByText('Not listening')).toBeInTheDocument()
    expect(screen.getByText(/That is the default for every repository/)).toBeInTheDocument()
    expect(screen.getByTestId('intake-empty')).toBeInTheDocument()
  })

  it('never renders the tracker credential, only that one is stored and its last characters', async () => {
    setup(OFF)
    expect(await screen.findByText(/Stored \(…AB12\)/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('tracker_token')
  })

  it('switching the listener on sends the PUT and says what it will now do', async () => {
    const api = setup(OFF, { 'PUT /factory/alpha/intake': ON })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Switch the listener on/ }))
    await waitFor(() => expect(screen.getByTestId('intake-success')).toBeInTheDocument())
    expect(screen.getByTestId('intake-success').textContent).toContain('Ready for manufacture')
    expect(screen.getByTestId('intake-success').textContent).toContain('300')
    const put = api.calls.find((c) => c.method === 'PUT')
    expect(JSON.parse(String(put?.init?.body))).toEqual({ enabled: true, column: '' })
  })

  it('switching it off says that nothing on the board will be read or written', async () => {
    const api = setup(ON, { 'PUT /factory/alpha/intake': OFF })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Switch the listener off/ }))
    await waitFor(() => expect(screen.getByTestId('intake-success').textContent).toMatch(/is off/))
    expect(JSON.parse(String(api.calls.find((c) => c.method === 'PUT')?.init?.body))).toMatchObject({ enabled: false })
  })

  it('re-reading the column names what happened: seen, read, commented, registered', async () => {
    setup(ON, { 'POST /factory/alpha/intake/poll': ON })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Re-read the column now/ }))
    await waitFor(() => expect(screen.getByTestId('intake-success')).toBeInTheDocument())
    const said = screen.getByTestId('intake-success').textContent ?? ''
    expect(said).toContain('2 ticket(s) seen')
    expect(said).toContain('2 commented on')
    expect(said).toContain('1 registered')
  })

  it('"Post the feedback again" is the same poll with force, so a deleted comment comes back', async () => {
    const api = setup(ON, { 'POST /factory/alpha/intake/poll': ON })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Post the feedback again/ }))
    await waitFor(() => expect(screen.getByTestId('intake-success')).toBeInTheDocument())
    expect(JSON.parse(String(api.calls.find((c) => c.method === 'POST')?.init?.body))).toEqual({ force: true })
  })

  it('announces the outcome and the stop to a screen reader as they land', async () => {
    setup(ON, { 'POST /factory/alpha/intake/poll': ON })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Re-read the column now/ }))
    await waitFor(() => expect(screen.getByTestId('intake-success')).toHaveAttribute('role', 'status'))
    cleanup()
    setup({ ...ON, last_poll: { ...ON.last_poll!, stopped: 'unreachable', advice: 'Check the URL.' } })
    expect(await screen.findByRole('alert')).toHaveTextContent('unreachable')
  })

  it('a stop shows the server’s reason and the server’s own advice, never our own', async () => {
    setup({
      ...ON,
      last_poll: { ...ON.last_poll!, stopped: 'unauthorised', detail: 'the tracker answered 401', advice: 'Ask an admin to set a new token with permission to read work items and add comments.' },
    })
    expect(await screen.findByText(/unauthorised/)).toBeInTheDocument()
    expect(screen.getByText(/Ask an admin to set a new token/)).toBeInTheDocument()
  })

  it('a registered ticket links to its item and says what it became', async () => {
    setup(ON)
    const row = await screen.findByTestId('intake-row-4711')
    expect(row.textContent).toContain('ado-4711')
    expect(row.textContent).toContain('bug.fix')
    expect(row.textContent).toContain('confidence 0.67')
    // the route is a verdict pill, the same gloss as the map and the factory — not the bare
    // machine word, on the one screen aimed at the newest reader
    // and the number carries its n, its interval AND its apparatus, like every other number
    expect(row.textContent).toContain('Deliver on n = 42, interval 83–99 % · apparatus 2.2')
    expect(within(row).getByTestId('verdict-deliver')).toBeInTheDocument()
  })

  it('the item link stays inside the app although the ticket carries an absolute one', async () => {
    // `item_url` is the ABSOLUTE address written on the customer's ticket, so a reader on
    // their board can open it. In here the same page is one route away.
    setup(ON)
    const row = await screen.findByTestId('intake-row-4711')
    const link = within(row).getByRole('link', { name: 'ado-4711' })
    expect(link).toHaveAttribute('href', '/factory?repo=alpha&item=ado-4711')
  })

  it('a ticket the classifier could not place says the one thing that closes it', async () => {
    // the commonest bad ticket: `crb:needs-info` with no open question at all, because a
    // class nobody could work out means nobody can say what the test needs
    setup({
      ...ON,
      rows: [{ ...ON.rows[0]!, key: '4713', label: 'crb:needs-info', capability_class: '(unclassified)', confidence: 0, registered: false, open_questions: [] }],
    })
    const row = await screen.findByTestId('intake-row-4713')
    expect(row.textContent).toContain('needs information')
    expect(row.textContent).toContain('could not work out what kind of change this is')
    expect(row.textContent).toContain('crb:class=bug.fix')
    expect(row.textContent).toContain('unclassified')
    expect(row.textContent).not.toContain('(unclassified)')
  })

  it('a ticket that needs information shows the question and says nothing is registered', async () => {
    setup(ON)
    const row = await screen.findByTestId('intake-row-4712')
    expect(row.textContent).toContain('needs information')
    expect(row.textContent).toContain('nothing is registered until the questions are answered')
    expect(row.textContent).toContain('1 question(s) the acceptance test needs answered')
  })

  it('an unmeasured cell is named as unmeasured, never shown as a zero rate', async () => {
    setup(ON)
    const row = await screen.findByTestId('intake-row-4712')
    expect(row.textContent).toContain('has not been measured on this repository')
    expect(row.textContent).not.toContain('n = 0')
  })

  it('a viewer is told who can switch the listener rather than shown a dead button', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': REPOS,
      'GET /factory/alpha/intake': OFF,
    })
    renderApp(<IntakePage />, { route: '/factory/intake?repo=alpha', path: '/factory/intake' })
    expect(await screen.findByText(/Only an operator can switch the listener/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Switch the listener on/ })).not.toBeInTheDocument()
  })

  it('the switch is disabled while no tracker is configured, and says who configures it', async () => {
    setup({ ...OFF, connection: { ...CONNECTION, tracker: 'none', configured: false, credential_set: false } })
    expect(await screen.findByRole('button', { name: /Switch the listener on/ })).toBeDisabled()
    expect(screen.getByText(/An admin configures the tracker for the whole deployment/)).toBeInTheDocument()
  })
})
