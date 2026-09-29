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
 * Touch when:   never for a new repository; a stream gains a milestone pair or a figure leaves
 *               `not_captured`.
 */
import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Flow } from '../api/types'
import { unhinted } from '../help/hints-collector'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../test/utils'
import { FlowPanel } from './FlowPanel'

/** The n a tile shows — the text of the `dd` beside its `n =` term, nothing else in the tile. */
function nOf(tile: HTMLElement): string {
  const term = Array.from(tile.querySelectorAll('dt')).find((dt) => dt.textContent === 'n =')
  return term?.nextElementSibling?.textContent ?? ''
}

const MANUFACTURE: Flow['streams'][number] = {
  stream: 'manufacture-and-deliver',
  name: 'Manufacture & deliver',
  lead_times: [
    {
      key: 'registered_to_pr',
      label: 'Item registered → pull request opened',
      n: 7,
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
  spend: { usd: 0.528, rows_priced: 44, rows_unpriced: 6, apparatus_versions: ['2.2', '2.3'] },
  spend_label: 'the graded rows the factory built for this repository',
  per_unit: null,
  per_unit_label: 'per merged pull request',
  per_unit_spend: { usd: 0.528, rows_priced: 44, rows_unpriced: 6, apparatus_versions: ['2.2', '2.3'] },
  per_unit_units: 0,
  per_unit_reason: '6 rows counted here reported no price, so the money is a floor and a cost per merged pull request over it would understate; it is not served',
  counts: { items_registered: 4, pull_requests_opened: 3, merged: 0 },
  not_captured: [
    {
      figure: 'how many go-live lines are proven',
      why: 'nothing reads the go-live checklist against this deployment’s own probes',
      gap: 'G-584',
    },
  ],
}

const FLOW: Flow = {
  repo: 'alpha',
  apparatus: '2.2',
  generated: '2026-09-23T10:00:00+00:00',
  method: 'derived from the stored runs, graded rows, events, sign-offs and factory chain',
  spend: { usd: 1.028, rows_priced: 45, rows_unpriced: 6, apparatus_versions: ['2.2', '2.3'] },
  streams: [MANUFACTURE],
}

const MEASURE: Flow['streams'][number] = {
  ...MANUFACTURE,
  stream: 'measure',
  name: 'Measure',
  spend: { usd: 0.5, rows_priced: 1, rows_unpriced: 0, apparatus_versions: ['2.3'] },
  spend_label: 'the replay and blind attempts graded for this repository',
  per_unit_label: '',
  not_captured: [],
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
    expect(nOf(tile)).toBe('7')
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
    expect(tile.textContent).toContain('the factory built')
    expect(tile.textContent).toContain('6 row(s) reported no price and are not counted as zero, so this is a floor.')
    expect(tile.textContent).toContain('rows of apparatus 2.2, 2.3')
  })

  it('the measure stream shows the repository’s cumulative spend beside its own part of it', async () => {
    mount('measure', { ...FLOW, streams: [MEASURE] })
    const own = await screen.findByTestId('flow-spend-measure')
    expect(own.textContent).toContain('$0.5000')
    const total = screen.getByTestId('flow-spend-total')
    expect(total.textContent).toContain('Cumulative spend, this repository')
    expect(total.textContent).toContain('$1.03')
    expect(total.textContent).toContain('every graded row counted once')
    expect(total.textContent).toContain('6 row(s) reported no price')
  })

  it('only the measure stream carries the repository total', async () => {
    mount()
    await screen.findByTestId('flow-spend-manufacture-and-deliver')
    expect(screen.queryByTestId('flow-spend-total')).toBeNull()
  })

  it('a cost per unit over a floor is a dash with the server’s reason, never a divided floor', async () => {
    mount()
    const tile = await screen.findByTestId('flow-per-unit-manufacture-and-deliver')
    expect(tile.textContent).toContain('Cost per merged pull request')
    expect(tile.textContent).toContain('—')
    expect(tile.textContent).toContain('6 rows counted here reported no price, so the money is a floor')
  })

  it('a served cost per unit names its unit, its n and whether every row it covers was priced', async () => {
    const measure: Flow['streams'][number] = {
      ...MEASURE,
      per_unit: 0.12,
      per_unit_label: 'per cell that reached 10 rows, over its first 10 rows',
      per_unit_spend: { usd: 0.24, rows_priced: 20, rows_unpriced: 0, apparatus_versions: ['2.3'] },
      per_unit_units: 2,
      per_unit_reason: '',
    }
    mount('measure', { ...FLOW, streams: [measure] })
    const tile = await screen.findByTestId('flow-per-unit-measure')
    expect(tile.textContent).toContain('Cost per cell that reached 10 rows, over its first 10 rows')
    expect(tile.textContent).toContain('$0.1200')
    expect(nOf(tile)).toBe('2')
    expect(tile.textContent).toContain('$0.2400 over 20 priced row(s), divided by n')
    expect(tile.textContent).toContain('Every row counted here reported its own price.')
    expect(tile.textContent).not.toContain('deliveries')
  })

  it('a refused reading says so with the server’s message, and never vanishes', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /flow': () => envelope(409, 'false_q1_refused', 'a clean row of alpha failed a belt: the ledger refuses to load it'),
    })
    renderApp(<FlowPanel stream="run-the-platform" repo="alpha" />, { route: '/posture', path: '*' })
    const card = await screen.findByTestId('flow-refused-run-the-platform')
    expect(card.textContent).toContain('a clean row of alpha failed a belt: the ledger refuses to load it')
    expect(card.textContent).toContain('These figures are not shown')
    expect(unhinted(card)).toEqual([])
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
    expect(screen.getByText(/how many go-live lines are proven/)).toBeInTheDocument()
    expect(screen.getByText(/Gap G-584\./)).toBeInTheDocument()
  })

  it('an install that passed before recording is a dash with the reason, never a guessed date', async () => {
    const platform: Flow['streams'][number] = {
      ...MANUFACTURE,
      stream: 'run-the-platform',
      name: 'Run the platform',
      lead_times: [
        {
          key: 'installed_to_healthy',
          label: 'Installed → first green /health',
          n: 0,
          median_s: null,
          min_s: null,
          max_s: null,
          dropped: 0,
          reason: 'the install passed before this product recorded it (an existing deployment upgraded), so it is not dated',
        },
      ],
      spend: { usd: null, rows_priced: 0, rows_unpriced: 0, apparatus_versions: [] },
      per_unit_label: '',
      counts: { install_recorded: 0 },
    }
    const { container } = mount('run-the-platform', { ...FLOW, streams: [platform] })
    const tile = await screen.findByTestId('flow-installed_to_healthy')
    expect(tile.textContent).toContain('—')
    expect(tile.textContent).toContain('the install passed before this product recorded it')
    expect(screen.getByText('install recorded')).toBeInTheDocument()
    expect(unhinted(container)).toEqual([])
  })

  it('the connect stream shows registration to the first green probe and each proving run, each with its own hint (G-302, G-430)', async () => {
    const lt = (key: string, label: string, n: number, median_s: number | null, reason = '') => ({ key, label, n, median_s, min_s: median_s, max_s: median_s, dropped: 0, reason })
    const connect: Flow['streams'][number] = {
      ...MANUFACTURE,
      stream: 'connect-and-prove',
      name: 'Connect & prove',
      lead_times: [
        lt('registered_to_probe_green', 'Registered → first green probe', 1, 1800),
        lt('step_2_span', 'Step 2: first failed probe or qualify → first qualified task (an estimate of the developer’s time on step 2, not a measure of it)', 0, null, 'no probe or qualify of this repository has failed since it was registered, so step 2 has not been needed or has not started'),
        lt('mine_run', 'One mine run, started → finished', 2, 750),
        lt('oracle_run', 'One oracle run, started → finished', 1, 1800),
        lt('controls_run', 'One controls run, started → finished', 0, null, 'no controls run of this repository has succeeded yet'),
      ],
      per_unit_label: '',
      counts: { probe_green: 1 },
      not_captured: [],
    }
    const { container } = mount('connect-and-prove', { ...FLOW, streams: [connect] })
    const probe = await screen.findByTestId('flow-registered_to_probe_green')
    expect(probe.textContent).toContain('30 min')
    expect(nOf(probe)).toBe('1')
    expect(probe.getAttribute('data-hint')).toBe('flow.registered_to_probe_green')
    for (const key of ['step_2_span', 'mine_run', 'oracle_run', 'controls_run']) {
      expect(screen.getByTestId(`flow-${key}`).getAttribute('data-hint')).toBe(`flow.${key}`)
    }
    expect(screen.getByTestId('flow-step_2_span').textContent).toContain('an estimate of the developer’s time')
    expect(screen.getByTestId('flow-controls_run').textContent).toContain('no controls run of this repository has succeeded yet')
    expect(unhinted(container)).toEqual([])
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
