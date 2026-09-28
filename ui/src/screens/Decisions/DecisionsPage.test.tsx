/**
 * DecisionsPage — the inbox across repositories, served once, with the verb by role.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Decisions screen over `GET /decisions` (F6).
 * What it does: Pins that the served rows from two repositories roll up into one count under
 *               "Decisions for <repo>" with no per-repository fan-out; that an approver sees
 *               "Attest" on a sign-off-due row linking to the sign-off page with the cell
 *               preselected; that a viewer sees "Read" and the role that acts, on the stale rows
 *               too; that the evidence line's reason code is a term with its meaning beside it
 *               and the kicker names the apparatus as a term; that a row says how long it has
 *               waited from the server's clock; a held cell's and a stale cell's rows (G-535); a
 *               library entry's rows and its sponsor's read-only row; the empty states; that a
 *               failed read keeps its status and code, says the count is incomplete and Retry
 *               reads it again (G-134); and that every pill, tag, evidence line and button
 *               carries a hint, with the count pill opening on hover.
 * How:          `mockApi` + `renderApp`; `GET /decisions` is mocked with served rows (`row`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/DecisionsPage.tsx (under test), decisions.ts,
 *               useDecisionCount.ts, ui/src/help/hints.ts (the copy the hover test expects),
 *               ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx
 * Touch when:   never for a new repository; a row kind or its verb changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DecisionList, DecisionRowOut } from '../../api/types'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, expectHintOpens, mockApi, renderApp } from '../../test/utils'
import { DecisionsPage } from './DecisionsPage'

/** A served row: the sign-off due on alpha's bug.fix × XS unless overridden. */
function row(over: Partial<DecisionRowOut> = {}): DecisionRowOut {
  return {
    repo: 'alpha',
    kind: 'signoff_due',
    key: 'bug.fix|XS',
    title: 'bug.fix × XS clears the bar — attest it or decline',
    role: 'approver',
    evidence: 'n=22 on 9 tasks · 100% [85%, 100%] · deliver',
    reason_code: 'deliver',
    act: 'Attest',
    href: '/signoff?repo=alpha&cell=bug.fix%7CXS',
    can_act: true,
    signoff: null,
    due_since: '',
    age_s: 0,
    ...over,
  }
}
const HELD = row({ kind: 'routed_human', key: 'bug.fix|S', title: 'bug.fix × S routed to a human — the reading decided against the arm', role: 'viewer', evidence: 'n=20 on 20 tasks · 95% [76%, 99%] · insufficient', reason_code: 'insufficient', act: 'Read why', href: '/routing?repo=alpha' })
const GAP = row({ repo: 'beta', kind: 'gap_unsigned', key: 'I-1', title: 'I-1 Divide is blocked on 1 structural gap', evidence: 'method_path', reason_code: '', act: 'Sign a gap', href: '/factory?repo=beta&item=I-1' })

function list(items: DecisionRowOut[], over: Partial<DecisionList> = {}): DecisionList {
  return { items, total: items.length, as_of: '2026-09-28T09:00:00+00:00', repos: ['alpha'], measured: ['alpha'], errors: [], ...over }
}

function served(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
}

/** A stale attestation as `GET /signoffs` serves it, on a `signoff_stale` row. */
function stale(signoff: Record<string, unknown>, over: Partial<DecisionRowOut> = {}): DecisionRowOut {
  return row({ kind: 'signoff_stale', key: String(signoff.id), title: 'bug.fix × XS was signed on an earlier instrument — revoke or re-sign', reason_code: '', act: 'Revoke or re-sign', href: '/signoff?repo=alpha&cell=bug.fix%7CXS', signoff: signoff as never, ...over })
}
const STALE = { id: 's1', repo: 'alpha', cell: { capability_class: 'bug.fix', size: 'XS' }, revoked: false, active: false, stale: true, apparatus_current: '2.2', approver: 'u9', approver_name: 'Grace', created: '2026-09-01T10:00:00Z', evidence: { n: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, apparatus_versions: ['2.1'] } }

describe('DecisionsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('an approver sees the rows across repositories with the act and the deep link', async () => {
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL, // approver
      'GET /decisions': list([row(), HELD, GAP], { repos: ['alpha', 'beta'], measured: ['alpha', 'beta'] }),
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('3 waiting across 2 repositories')).toBeInTheDocument())
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
    expect(due).toHaveTextContent("the cell's standard arm: every clause holds")
    // one reading for the whole inbox: no per-repository fan-out (F6)
    expect(calls.filter((c) => c.path === '/decisions')).toHaveLength(1)
    expect(calls.some((c) => ['/capability-map', '/signoffs', '/repos'].includes(c.path) || c.path.startsWith('/factory/') || c.path.startsWith('/library/') || c.path.startsWith('/learn/'))).toBe(false)
  })

  it('a row says how long it has been waiting, from the server’s clock (G-516)', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([row({ due_since: '2026-09-12T09:00:00+00:00', age_s: 950400 })]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    const age = await screen.findByTestId('decision-age-signoff_due-bug.fix|XS')
    expect(age).toHaveTextContent('Waiting 11 days — since 2026-09-12')
  })

  it('a decision the server has not stamped yet says nothing rather than "just now"', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([row({ due_since: '', age_s: 0 })]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('bug.fix × XS clears the bar — attest it or decline')).toBeInTheDocument())
    expect(screen.queryByTestId('decision-age-signoff_due-bug.fix|XS')).not.toBeInTheDocument()
  })

  it('a held cell and a cell measured on an earlier apparatus are rows for an operator, each linked to Learn (G-535)', async () => {
    const held = row({ kind: 'strengthen', key: 'bug.fix|M', title: 'bug.fix × M is held until its tests are stronger', role: 'operator', evidence: 'n=20 on 20 tasks · 95% [76%, 99%] · oracle_weak', reason_code: 'oracle_weak', act: 'Strengthen the tests', href: '/learn?repo=alpha#strengthen' })
    const again = row({ kind: 'remeasure', key: '*|bug.fix|S|go|editblock|m|p|sighted', title: 'bug.fix × S (sighted) was measured under apparatus 2.2, not 2.4', role: 'operator', evidence: '20 rows needed · cost not known · editblock/m@p', reason_code: '', act: 'Queue re-measurement', href: '/learn?repo=alpha#remeasure' })
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'operator' }, 'GET /decisions': list([held, again]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    const li = (await screen.findByText('bug.fix × M is held until its tests are stronger')).closest('li')!
    expect(within(li).getByRole('link', { name: 'Strengthen the tests' })).toHaveAttribute('href', '/learn?repo=alpha#strengthen')
    expect(within(li).getByRole('button', { name: 'oracle_weak' })).toBeInTheDocument()
    const stale = screen.getByText(/was measured under apparatus 2\.2, not 2\.4/).closest('li')!
    expect(stale).toHaveTextContent('Re-measure')
    expect(stale).toHaveTextContent('20 rows needed · cost not known')
    expect(within(stale).getByRole('link', { name: 'Queue re-measurement' })).toHaveAttribute('href', '/learn?repo=alpha#remeasure')
  })

  it('a library entry waiting for its second person is a decision even before the repository is measured', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /decisions': list(
        [
          row({ kind: 'entry_stale', key: 'convention/lint', title: 'convention/lint went stale: .golangci.yml changed or went', evidence: 'at 222222222222 · signed by Ben', reason_code: '', act: 'Sign again or retire', href: '/library/alpha#index' }),
          row({ kind: 'entry_to_sign', key: 'convention/context-first', title: 'convention/context-first waits for a second person to sign it', evidence: 'sponsored by Ada · Pass context first', reason_code: '', act: 'Sign', href: '/library/alpha#index' }),
        ],
        { measured: [] },
      ),
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('convention/context-first waits for a second person to sign it')).toBeInTheDocument())
    const r = screen.getByText('convention/context-first waits for a second person to sign it').closest('li')!
    expect(within(r).getByRole('link', { name: 'Sign' })).toHaveAttribute('href', '/library/alpha#index')
    expect(r).toHaveTextContent('Library entry to sign')
    expect(screen.getByText('convention/lint went stale: .golangci.yml changed or went')).toBeInTheDocument()
    expect(screen.queryByText('Nothing measured yet')).toBeNull()
  })

  it('the sponsor of an entry is offered no Sign for it: another approver signs', async () => {
    const title = 'convention/context-first waits for another approver to sign it — you sponsored it'
    mockApi({
      'GET /auth/me': PRINCIPAL, // an approver
      'GET /decisions': list([row({ kind: 'entry_to_sign', key: 'convention/context-first', title, role: 'viewer', evidence: 'sponsored by Ada · Pass context first', reason_code: '', act: 'Read', href: '/library/alpha#index' })]),
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText(title)).toBeInTheDocument())
    const r = screen.getByText(title).closest('li')!
    expect(within(r).queryByRole('link', { name: 'Sign' })).toBeNull()
    expect(within(r).getByRole('link', { name: 'Read' })).toHaveAttribute('href', '/library/alpha#index')
  })

  it('the kicker names the apparatus as a term', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /version': { crb: '0', apparatus: '2.2', policy: 'routing.v1' }, 'GET /decisions': list([row()]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText(/Under/)).toBeInTheDocument())
    expect(screen.getByText(/Under/).closest('span')).toHaveTextContent('Under apparatus ⓘ 2.2')
    expect(screen.getByRole('button', { name: 'apparatus' })).toBeInTheDocument()
  })

  it('a viewer reads a stale sign-off; only an approver may revoke or re-sign', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /decisions': list([stale(STALE, { act: 'Read', can_act: false })]) })
    const first = renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Stale sign-offs' })).toBeInTheDocument())
    const staleList = screen.getByRole('list', { name: 'Stale sign-offs' })
    expect(within(staleList).queryByRole('link', { name: 'Revoke or re-sign' })).toBeNull()
    expect(within(staleList).getByRole('link', { name: 'Read' })).toHaveAttribute('href', '/signoff?repo=alpha&cell=bug.fix%7CXS')
    expect(within(staleList).getByText('approver acts')).toBeInTheDocument()
    // a stale sign-off is counted once, in the pill, and is no card row
    expect(screen.getByText('1 waiting')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Decisions for alpha' })).toBeNull()
    first.unmount()
    vi.unstubAllGlobals()
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([stale(STALE)]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('link', { name: 'Revoke or re-sign' })).toBeInTheDocument())
  })

  it('a sign-off stale because the repository changed its checks arm says so, not the apparatus', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([stale({ ...STALE, id: 's2', checks_arm: 'off', checks_arm_current: 'api', evidence: { ...STALE.evidence, apparatus_versions: ['2.2'] } })]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Stale sign-offs' })).toBeInTheDocument())
    const staleList = screen.getByRole('list', { name: 'Stale sign-offs' })
    expect(within(staleList).getByText(/signed on the off checks arm, now reading the api arm/)).toBeInTheDocument()
    expect(within(staleList).queryByText(/signed at apparatus/)).toBeNull()
  })

  it('a sign-off with no apparatus stamp says it was signed before the stamp and asks for a re-sign', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([stale({ ...STALE, id: 's3', stale_reason: 'no_apparatus_stamp', apparatus_current: '2.3', evidence: { ...STALE.evidence, apparatus_versions: [] } })]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Stale sign-offs' })).toBeInTheDocument())
    const staleList = screen.getByRole('list', { name: 'Stale sign-offs' })
    expect(within(staleList).getByText(/signed before the apparatus stamp, now reading at 2\.3/)).toBeInTheDocument()
    expect(within(staleList).queryByText(/signed at apparatus \?/)).toBeNull()
    expect(within(staleList).getByRole('link', { name: 'Revoke or re-sign' })).toBeInTheDocument()
  })

  it('a viewer sees the same rows with Read and the role that acts', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /decisions': list([row({ act: 'Read', can_act: false })]) })
    const { container } = renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('1 waiting across 1 repository')).toBeInTheDocument()) // the pill names the spread; the card eyebrow carries the repository's own count
    expect(screen.getByText('1 waiting')).toBeInTheDocument()
    expect(screen.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true') // the e2e sweep's readiness anchor
    expect(screen.getByRole('link', { name: 'Read' })).toBeInTheDocument()
    expect(screen.getByText('approver acts').closest('[data-hint]')).toHaveAttribute('data-hint', 'stat.decisions.who_acts')
    expect(container.querySelector('[data-hint="button.decisions.act"]')).toBeNull()
  })

  it('nothing waiting is said, not hidden', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([]) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByText('Nothing is waiting on a person')).toBeInTheDocument())
    expect(screen.getByText('0 waiting')).toBeInTheDocument()
  })

  it('a connected but unmeasured repository is "nothing measured yet", never "no repository connected"', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': list([], { measured: [] }) })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true'))
    expect(screen.getByText('Nothing measured yet')).toBeInTheDocument()
    expect(screen.getByText(/alpha is connected but no capability map exists yet/)).toBeInTheDocument()
    expect(screen.queryByText('No repository connected')).toBeNull()
    expect(screen.queryByText('Nothing is waiting on a person')).toBeNull()
  })

  it('a failed repository query shows its status, code and repository, says the count is incomplete, and Retry re-reads it', async () => {
    let reads = 0
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /decisions': () => {
        reads += 1
        return served(
          reads === 1
            ? list([row()], { repos: ['alpha', 'beta'], errors: [{ repo: 'beta', status: 503, code: 'unavailable', message: 'the library could not be read' }] })
            : list([row(), GAP], { repos: ['alpha', 'beta'], measured: ['alpha', 'beta'] }),
        )
      },
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The decisions for beta could not be read')
    expect(alert).toHaveTextContent('HTTP 503 · unavailable')
    expect(alert).toHaveTextContent('the library could not be read')
    expect(alert).toHaveTextContent('The count above is incomplete until a retry succeeds.')
    // the rows that were read are shown; the count is not called complete and nothing says "nothing waiting"
    expect(screen.getByText('1 waiting across 1 repository')).toBeInTheDocument()
    expect(screen.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'false')
    await userEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByText('2 waiting across 2 repositories')).toBeInTheDocument())
    expect(reads).toBe(2)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a failed read of the whole inbox keeps its envelope and Retry reads it again', async () => {
    let reads = 0
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /decisions': () => {
        reads += 1
        return reads === 1 ? envelope(503, 'unavailable', 'the database is restarting') : served(list([row()]))
      },
    })
    renderApp(<DecisionsPage />, { route: '/decisions' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The decisions could not be read')
    expect(alert).toHaveTextContent('HTTP 503 · unavailable')
    expect(alert).toHaveTextContent('The count above is incomplete until a retry succeeds.')
    expect(screen.getByText('not known')).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByText('1 waiting across 1 repository')).toBeInTheDocument())
  })

  it('every kicker, pill, tag, evidence line, act and stale row carries a hint; the count pill opens on hover with the registry copy', async () => {
    // the stale sign-off is on another cell, so the deliver cell stays "sign-off due" (an Attest act) beside it
    mockApi({
      'GET /auth/me': PRINCIPAL, // approver
      'GET /version': { crb: '0', apparatus: '2.2', policy: 'routing.v1' },
      'GET /decisions': list([row(), HELD, stale({ ...STALE, cell: { capability_class: 'bug.fix', size: 'M' } })]),
    })
    const { container } = renderApp(<DecisionsPage />, { route: '/decisions' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Stale sign-offs' })).toBeInTheDocument())
    await waitFor(() => expect(container.querySelector('[data-hint="stat.decisions.apparatus"]')).not.toBeNull())
    expect(unhinted(container)).toEqual([])
    for (const id of ['stat.decisions.count', 'pill.decisions.kind', 'stat.decisions.evidence', 'button.decisions.act', 'button.decisions.read', 'tile.decisions.stale', 'button.decisions.resign']) {
      expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    const pill = screen.getByText(/waiting across/).closest('[data-hint]')!
    expect(pill).toHaveAttribute('data-hint', 'stat.decisions.count')
    await expectHintOpens(pill, 'stat.decisions.count')
  })
})
