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

import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { useDecisionCount } from './useDecisionCount'

function Probe() {
  const n = useDecisionCount()
  return <output data-testid="badge">{n === null ? 'none' : String(n)}</output>
}

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
})
