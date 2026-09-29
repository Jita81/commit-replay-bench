/**
 * useDecisionCount — the nav badge's number, from one request (F6).
 *
 * Navigation
 * ----------
 * What it is:   Tests for `useDecisionCount`, the hook the header badge (Layout.tsx) reads on
 *               every screen.
 * What it does: Pins that the badge makes ONE request, `GET /decisions?count=1`, however many
 *               repositories are connected — never the five queries per repository it used to
 *               repeat on every screen — and that it shows no number while a read failed or a
 *               repository could not be read, because a smaller number would read as fewer
 *               decisions.
 * How:          `mockApi` + `renderApp` over a probe component that prints the hook's value.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/useDecisionCount.ts (under test),
 *               src/crb/server/routes/decisions.py (the count reading),
 *               ui/src/components/Layout.tsx (the badge that reads it)
 * Tested by:    ui/src/screens/Decisions/useDecisionCount.test.tsx
 * Touch when:   never for a new repository; the badge's reading changes.
 */

import { QueryClientProvider, useMutation } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { useCreateSignoff } from '../../api/hooks'
import { makeQueryClient } from '../../api/queryClient'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { useDecisionCount, useDecisions } from './useDecisionCount'

function Probe() {
  const n = useDecisionCount()
  return <output data-testid="badge">{n === null ? 'none' : String(n)}</output>
}

/** The badge beside an Attest (a wired act) and an act nobody wired to the inbox. */
function BadgeAndActs() {
  const attest = useCreateSignoff()
  const other = useMutation({ mutationFn: () => api<unknown>('/some/new/act', { method: 'POST', body: {} }) })
  return (
    <>
      <Probe />
      <button type="button" onClick={() => attest.mutate({ repo: 'alpha', cell: { capability_class: 'bug.fix', size: 'S' }, note: '' })}>
        attest
      </button>
      <button type="button" onClick={() => other.mutate()}>
        new act
      </button>
    </>
  )
}

function ListProbe() {
  const d = useDecisions()
  return <output data-testid="rows">{d.ready ? String(d.decisions.length) : 'loading'}</output>
}

const ROW = { repo: 'alpha', kind: 'signoff_due', key: 'bug.fix|S', title: 'bug.fix × S clears the bar', role: 'approver', evidence: '', reason_code: '', act: 'Attest', href: '/signoff?repo=alpha', can_act: true, signoff: null, due_since: '2026-09-28T09:00:00+00:00', age_s: 60 }

const REPOS = { items: ['alpha', 'beta', 'gamma', 'delta'].map((name) => ({ name })), total: 4, limit: 500, offset: 0 }

describe('useDecisionCount', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('the decisions badge makes one request, not one per repository', async () => {
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': REPOS,
      'GET /decisions': { total: 7, by_role: { approver: 3, operator: 2, viewer: 2 }, errors: [] },
    })
    renderApp(<Probe />)
    await waitFor(() => expect(screen.getByTestId('badge')).toHaveTextContent('7'))
    const reads = calls.filter((c) => c.path !== '/auth/me')
    expect(reads.map((c) => c.url.replace(/^\/api\/v1/, ''))).toEqual(['/decisions?count=1'])
  })

  it('shows no number while a repository could not be read, or the reading failed', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': { total: 2, by_role: { approver: 2 }, errors: ['beta'] } })
    const first = renderApp(<Probe />)
    await waitFor(() => expect(screen.getByTestId('badge')).toHaveTextContent('none'))
    first.unmount()
    vi.unstubAllGlobals()
    const { calls } = mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /decisions': () => envelope(503, 'unavailable', 'no database') })
    renderApp(<Probe />)
    await waitFor(() => expect(calls.some((c) => c.path === '/decisions')).toBe(true))
    expect(screen.getByTestId('badge')).toHaveTextContent('none')
  })

  it('the badge re-reads the moment any act settles — a wired act or one added later (P-613)', async () => {
    let waiting = 3
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /decisions': () => json({ total: waiting, by_role: { approver: waiting }, errors: [] }),
      'POST /signoffs': () => {
        waiting -= 1
        return json({ id: 'sgn_1', repo: 'alpha' }, 201)
      },
      'POST /some/new/act': () => {
        waiting -= 1
        return json({}, 201)
      },
    })
    renderApp(<BadgeAndActs />)
    await waitFor(() => expect(screen.getByTestId('badge')).toHaveTextContent('3'))
    await userEvent.click(screen.getByRole('button', { name: 'attest' }))
    // inside the badge's 30 s: only the act's invalidation can move it
    await waitFor(() => expect(screen.getByTestId('badge')).toHaveTextContent('2'))
    await userEvent.click(screen.getByRole('button', { name: 'new act' }))
    await waitFor(() => expect(screen.getByTestId('badge')).toHaveTextContent('1'))
  })

  it('the list is re-read every time a page that shows it mounts, inside the app’s stale time', async () => {
    let rows = [ROW]
    const { calls } = mockApi({ 'GET /decisions': () => json({ items: rows, total: rows.length, as_of: '', repos: ['alpha'], measured: ['alpha'], errors: [] }) })
    // the app's own client and defaults (10 s stale), not the tests' zero-stale one
    const qc = makeQueryClient()
    const first = render(
      <QueryClientProvider client={qc}>
        <ListProbe />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent('1'))
    first.unmount()
    rows = []
    render(
      <QueryClientProvider client={qc}>
        <ListProbe />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent('0'))
    expect(calls.filter((c) => c.path === '/decisions')).toHaveLength(2)
  })
})
