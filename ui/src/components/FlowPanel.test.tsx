/**
 * ui/src/components/FlowPanel.tsx — the stream's own numbers, and the ones it refuses to invent.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for `FlowPanel`, the card each screen shows its own value
 *               stream's lead time, spend and counts in.
 * What it does: Pins that a measured duration reads at human scale with its n, its range and the
 *               apparatus; that an unmeasured one is a dash with the server's reason and never a
 *               zero; that the spend names how many rows reported no price so the total reads as
 *               a floor; that a cost per delivery with nothing priced is a dash; that the counts
 *               render as a readable list; that the figures nothing records are printed with
 *               their gap ids; that every element carries a registry hint; and that a stream
 *               absent from the reading renders nothing at all.
 * How:          `mockApi` with one `GET /flow` body → `renderApp` with the panel as the route
 *               element; `unhinted` proves the hint contract on the panel itself.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/FlowPanel.tsx (the code under test), ui/src/api/types.ts
 *               (the `Flow` shape the body mirrors), ui/src/help/hints-collector.ts
 *               (`unhinted`), ui/src/test/utils.tsx (`mockApi`, `renderApp`),
 *               tests/test_server_routes_flow.py (the server side of the same contract)
 * Tested by:    ui/src/components/FlowPanel.test.tsx
 * Touch when:   a stream gains a milestone pair or a figure leaves `not_captured`.
 */
import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Flow } from '../api/types'
import { unhinted } from '../help/hints-collector'
import { PRINCIPAL, mockApi, renderApp } from '../test/utils'
import { FlowPanel } from './FlowPanel'

const MANUFACTURE: Flow['streams'][number] = {
  stream: 'manufacture-and-deliver',
  name: 'Manufacture & deliver',
  lead_times: [
    {
      key: 'registered_to_pr',
      label: 'Item registered → pull request opened',
      n: 3,
      median_s: 7500,
      min_s: 3600,
      max_s: 280_800,
      dropped: 1,
      reason: '',
    },
    {
      key: 'pr_to_merged',
      label: 'Pull request opened → merged',
      n: 0,
      median_s: null,
      min_s: null,
      max_s: null,
      dropped: 0,
      reason: 'no pull request of this repository has been read back as merged yet',
    },
  ],
  spend: { usd: 0.528, rows_priced: 44, rows_unpriced: 6 },
  spend_label: 'the graded rows of this repository’s factory runs',
  per_unit: null,
  per_unit_label: 'per merged pull request',
  counts: { items_registered: 4, pull_requests_opened: 3, merged: 0 },
  not_captured: [
    {
      figure: 'the reviewer minutes each decision cost',
      why: 'POST /reviews records a verdict and its findings, and asks for no minutes',
      gap: 'G-557',
    },
  ],
}

const FLOW: Flow = {
  repo: 'alpha',
  apparatus: '2.2',
  generated: '2026-09-23T10:00:00+00:00',
  method: 'derived from the stored runs, graded rows, events, sign-offs and factory chain',
  streams: [MANUFACTURE],
}

function mount(stream = 'manufacture-and-deliver', body: Flow = FLOW) {
  mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /flow': body })
  return renderApp(<FlowPanel stream={stream} repo="alpha" />, { route: '/factory?repo=alpha', path: '*' })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FlowPanel', () => {
  it('reads a measured lead time at human scale, with its n, its range and the apparatus', async () => {
    mount()
    const tile = await screen.findByTestId('flow-registered_to_pr')
    expect(tile.textContent).toContain('Item registered → pull request opened')
    expect(tile.textContent).toContain('2 h 5 min')
    expect(tile.textContent).toContain('n =')
    expect(tile.textContent).toContain('3')
    expect(tile.textContent).toContain('fastest 1 h 0 min, slowest 3 days 6 h')
    expect(tile.textContent).toContain('apparatus 2.2')
    expect(tile.textContent).toContain('derived from the stored')
  })

  it('says a pair with an unreadable or out-of-order stamp was left out', async () => {
    mount()
    const tile = await screen.findByTestId('flow-registered_to_pr')
    expect(tile.textContent).toContain('1 pair(s) had an unreadable or out-of-order stamp')
  })

  it('an unmeasured duration is a dash with the reason, never a zero', async () => {
    mount()
    const tile = await screen.findByTestId('flow-pr_to_merged')
    expect(tile.textContent).toContain('—')
    expect(tile.textContent).not.toMatch(/0 s|NaN|undefined/)
    expect(tile.textContent).toContain('no pull request of this repository has been read back as merged yet')
  })

  it('the spend names what it covers and how many rows reported no price', async () => {
    mount()
    const tile = await screen.findByTestId('flow-spend-manufacture-and-deliver')
    expect(tile.textContent).toContain('$0.5280')
    expect(tile.textContent).toContain('factory runs')
    expect(tile.textContent).toContain('6 row(s) reported no price and are not counted as zero, so this is a floor.')
  })

  it('a cost per delivery with nothing priced is a dash that says why', async () => {
    mount()
    const tile = await screen.findByTestId('flow-per-unit-manufacture-and-deliver')
    expect(tile.textContent).toContain('Cost per merged pull request')
    expect(tile.textContent).toContain('Unmeasured: either nothing is priced yet or nothing has been delivered.')
  })

  it('the counts read as words, not keys', async () => {
    mount()
    await screen.findByTestId('flow-registered_to_pr')
    expect(screen.getByText('pull requests opened')).toBeInTheDocument()
    expect(screen.queryByText('pull_requests_opened')).not.toBeInTheDocument()
  })

  it('a figure nothing records is printed with its gap, so its absence is not a zero', async () => {
    mount()
    await screen.findByTestId('flow-registered_to_pr')
    expect(screen.getByText(/the reviewer minutes each decision cost/)).toBeInTheDocument()
    expect(screen.getByText(/Gap G-557\./)).toBeInTheDocument()
  })

  it('every element a reader meets carries a registry hint', async () => {
    const { container } = mount()
    await screen.findByTestId('flow-registered_to_pr')
    expect(unhinted(container)).toEqual([])
  })

  it('a stream the reading does not carry renders nothing at all', async () => {
    const { container } = mount('learn')
    await waitFor(() => expect(container.querySelector('[data-testid="flow-tiles-learn"]')).toBeNull())
    expect(container.textContent).toBe('')
  })
})
