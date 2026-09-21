/**
 * ui/src/screens/Capability/CapabilityPage.tsx — absence is NOT_YET_MEASURED, false-Q1 is red, and
 * the controls verdict is shown as it is.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests for the capability map against a mocked API.
 * What it does: Pins that a cell absent from the map renders NOT_YET_MEASURED with n = 0 (never
 *               a zero rate), that a cell with false-Q1 > 0 is red with the page alert, that
 *               the summary tiles carry value + n + apparatus, that no repo gives the designed
 *               empty state, that a 503 renders the envelope (message, HTTP status, code), and
 *               — after A2 — that a failed / thin / escaped / unmeasured controls verdict gets
 *               its own pill and the split and model point appear next to the point.
 * How:          `mockApi` answers `GET /capability-map` with hand-built maps; `renderApp` at
 *               `/capability?repo=…`; assertions on the `cell-*`, `tile-*`, `kind-*` and
 *               `controls-*` test ids.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/CapabilityPage.tsx (the code under test),
 *               ui/src/screens/Capability/contract.ts (the fixture shapes),
 *               ui/src/test/utils.tsx (`mockApi`, `renderApp`, `PRINCIPAL`)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx
 * Touch when:   a cell field or controls state is added — extend the fixtures and assert its
 *               rendering here.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CapabilityCell, CapabilityMap } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { CapabilityPage } from './CapabilityPage'
import type { CapabilityCellSplit, CapabilityMapWithControls, ControlsVerdict } from './contract'

const cell = (over: Partial<CapabilityCell>): CapabilityCell => ({
  capability_class: 'bug.fix',
  size: 'S',
  n: 40,
  clean: 37,
  point: 0.925,
  ci_low: 0.803,
  ci_high: 0.972,
  false_q1: 0,
  cost_usd_mean: 0.012,
  latency_s_mean: 41.2,
  oracle_strength_mean: 0.83,
  route: 'deliver',
  reason: 'n=40 point=0.925 ci_low=0.803 false_q1=0 oracle=0.83',
  verification_tier: 'automated-pass',
  apparatus_versions: ['2.0'],
  belt_set: 'v4',
  ...over,
})

const MAP: CapabilityMap = {
  repo: 'sqlalchemy',
  by: ['capability_class', 'size'],
  classes: ['bug.fix', 'test.add'],
  sizes: ['XS', 'S'],
  languages: ['python'],
  models: ['gpt-oss-120b'],
  cells: [
    cell({}),
    cell({ capability_class: 'test.add', size: 'XS', n: 12, clean: 12, point: 1, ci_low: 0.76, ci_high: 1, false_q1: 1, route: 'do_not_ship', reason: '1 false-Q1 row(s) in cell — evidence untrusted' }),
    // bug.fix × XS and test.add × S are absent → NOT_YET_MEASURED
  ],
  summary: { trusted_autonomy_coverage: 0.42, total_cells: 4, measured_cells: 2, deliver_cells: 1, n_total: 52, false_q1_total: 1, apparatus_versions: ['2.0'] },
  policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' },
}

describe('CapabilityPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders NOT_YET_MEASURED for absent cells and a red false-Q1 cell', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })

    await waitFor(() => expect(screen.getByTestId('tile-coverage')).toBeInTheDocument())

    // Summary tile: value + n + apparatus.
    const cov = screen.getByTestId('tile-coverage')
    expect(cov.textContent).toContain('42.0%')
    expect(cov.textContent).toContain('n =')
    expect(cov.textContent).toContain('52')
    expect(cov.textContent).toContain('routing.v1')

    // Two measured cells, two honest-empty cells in a 2×2 grid.
    expect(screen.getAllByTestId('cell-not-measured')).toHaveLength(2)
    expect(screen.getAllByTestId('verdict-NOT_YET_MEASURED').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByTestId('cell-measured')).toBeInTheDocument()

    // The false-Q1 cell is rendered red with the do_not_ship verdict and its count.
    const bad = screen.getByTestId('cell-false-q1')
    expect(bad.className).toContain('border-status-red')
    expect(bad.textContent).toContain('fQ1 1')
    expect(bad.querySelector('[data-testid="verdict-do_not_ship"]')).not.toBeNull()

    // The page-level alert and the false-Q1 total tile go red.
    expect(screen.getByTestId('false-q1-alert')).toBeInTheDocument()
    expect(screen.getByTestId('tile-false-q1').textContent).toContain('1')
    expect(screen.getByTestId('tile-false-q1').querySelector('.text-status-red')).not.toBeNull()

    // Every measured cell carries n and a CI bar.
    expect(screen.getAllByTestId('ci-bar')).toHaveLength(2)
    expect(screen.getByTestId('cell-measured').textContent).toContain('n=40')
    expect(screen.getByTestId('cell-measured').textContent).toContain('92.5%')
  })

  it('shows the designed empty state when no repo is chosen; its action is Connection, not the repo list (J-HEL-14)', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } })
    renderApp(<CapabilityPage />, { route: '/capability' })
    expect(await screen.findByText('Choose a repo to see its capability map')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/connect')
  })

  it('a tile carries no hover titles: its five numbers are described by one legend; the open cell shows the legend with terms (J-HEL-14)', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    const tile = await screen.findByTestId('cell-measured')

    // no hover-only meaning on the numbers (the route pill is the shared Pill's concern)
    expect(within(tile).getByTestId('cell-numbers').querySelectorAll('[title]')).toHaveLength(0)
    expect(within(tile).getByText('92.5%').getAttribute('title')).toBeNull()
    // the tile is described by the one legend under the grid, which names every number
    const legendId = tile.getAttribute('aria-describedby')
    expect(legendId).toBeTruthy()
    const legend = document.getElementById(legendId!)!
    expect(legend.textContent).toContain('fQ1')
    expect(legend.textContent).toContain('false-Q1')
    expect(legend.textContent).toContain('oracle strength')
    expect(legend.textContent).toContain('verification tier')
    // no button (a Term) sits inside the tile button
    expect(tile.querySelectorAll('button')).toHaveLength(0)

    // open the cell: the legend line is visible text with Terms that open inline
    fireEvent.click(tile)
    const line = await screen.findByTestId('cell-legend-line')
    expect(line.textContent).toContain('fQ1')
    const term = within(line).getByRole('button', { name: /false-Q1/ })
    expect(term).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(term)
    expect(term).toHaveAttribute('aria-expanded', 'true')
  })

  it('a viewer on an unmeasured repo reads who starts the run; an operator gets the link (J-FAC-12)', async () => {
    const empty = { ...MAP, cells: [], summary: { ...MAP.summary, measured_cells: 0, n_total: 0, false_q1_total: 0 } }
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': empty,
    })
    const first = renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    expect(await screen.findByText('Nothing measured for this repo yet')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Start a replay run' })).toBeNull()
    expect(screen.getByText(/an operator starts a replay run/i)).toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()

    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': empty,
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    expect(await screen.findByRole('link', { name: 'Start a replay run' })).toBeInTheDocument()
  })

  it('renders the error envelope honestly when the map fails', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /capability-map': () => new Response(JSON.stringify({ error: { code: 'ledger_unavailable', message: 'ledger is locked', detail: {} } }), { status: 503, headers: { 'Content-Type': 'application/json' } }),
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=x' })
    const err = await screen.findByTestId('error-state')
    expect(err.textContent).toContain('ledger is locked')
    expect(err.textContent).toContain('HTTP 503')
    expect(err.textContent).toContain('ledger_unavailable')
  })
})

// ---------------------------------------------------------------------------
// A2: the controls verdict pill, the failure split and model point on every cell
// ---------------------------------------------------------------------------

const VERDICT_FAILED: ControlsVerdict = {
  measured: true,
  passed: false,
  complete: true,
  constructible: 49,
  total: 49,
  share: 1,
  escapes: 0,
  run_id: 'c0ffee0000000000000000000000cafe',
  created: '2026-09-13T12:00:00Z',
  state: 'failed',
}

const splitCell = (over: Partial<CapabilityCellSplit>): CapabilityCellSplit => ({
  ...cell({}),
  n: 13,
  clean: 8,
  point: 0.6154,
  ci_low: 0.355,
  ci_high: 0.823,
  route: 'human',
  reason: 'controls_failed: the negative-controls gate FAILED on this repo — an instrument defect, nothing measured under it licenses autonomy (controls run c0ffee00)',
  reason_code: 'controls_failed',
  n_builder_red: 1,
  n_budget: 1,
  n_protocol: 1,
  n_harness: 2,
  n_disqualified: 1,
  model_n: 9,
  model_point: 0.8889,
  model_ci_low: 0.565,
  model_ci_high: 0.981,
  failure_split: { builder_red: 1, budget: 1, protocol: 1, harness: 2, disqualified: 1 },
  ...over,
})

const MAP_WITH_CONTROLS: CapabilityMapWithControls = {
  ...MAP,
  cells: [splitCell({})],
  summary: { ...MAP.summary, false_q1_total: 0, deliver_cells: 0, measured_cells: 1 },
  policy: { ...MAP.policy, min_controls_share: 0.5, max_controls_escapes: 0, controls_version: 'controls-gate.v1' },
  controls: VERDICT_FAILED,
}

describe('CapabilityPage — controls verdict + failure split (A2)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the failed controls pill, the split and the model point next to the point', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP_WITH_CONTROLS,
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    await waitFor(() => expect(screen.getByTestId('tile-controls')).toBeInTheDocument())

    // the repo-level verdict: FAILED, with its k of N and the gate it is judged by
    const tile = screen.getByTestId('tile-controls')
    expect(tile.textContent).toContain('FAILED')
    expect(tile.textContent).toContain('49 of 49')
    expect(tile.textContent).toContain('controls-gate.v1')
    expect(screen.getAllByTestId('controls-failed').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByTestId('controls-failed')[0]!.getAttribute('aria-label')).toMatch(/gate FAILED/)

    // the cell: all-rows point, clean n/N, then the model rate and the split — never instead of
    const measured = screen.getByTestId('cell-measured')
    // the accessible label carries the whole claim: n, point, the Wilson interval and the
    // apparatus + belt-set provenance (CodeRabbit on PR #6)
    expect(measured.getAttribute('aria-label')).toBe('bug.fix S: human, n 13, point 61.5%, 95% CI 35.5% to 82.3%, false-Q1 0, apparatus 2.0 · belts v4')
    expect(measured.textContent).toContain('61.5%')
    expect(measured.textContent).toContain('clean 8/13')
    const model = measured.querySelector('[data-testid="model-point"]')!
    expect(model.textContent).toContain('model 89%')
    expect(model.textContent).toContain('(8/9 [56%–98%])') // n and the served Wilson interval travel with the model rate
    const split = measured.querySelector('[data-testid="failure-split"]')!
    expect(split.getAttribute('aria-label')).toBe('red 1, lint 0, budget 1, protocol 1, harness 2, outage 0, DQ 1')
    expect(split.querySelector('[data-testid="kind-harness"]')!.textContent).toBe('harness2')

    // the route pill carries the reason on hover; the detail card names the code
    expect(measured.querySelector('[data-testid="verdict-human"]')!.getAttribute('aria-label')).toContain('controls_failed')
    fireEvent.click(measured)
    const reason = await screen.findByTestId('cell-reason')
    expect(reason.querySelector('code')!.textContent).toBe('controls_failed')
    expect(reason.textContent).toContain('instrument defect')
    expect(screen.getByTestId('tile-model-point').textContent).toContain('88.9%')
    expect(screen.getByTestId('tile-model-point').textContent).toContain('diagnostic, not a gate')
    expect(screen.getByTestId('tile-point').textContent).toContain('the rate that routes')
    expect(screen.getByTestId('cell-split-pills')).toBeInTheDocument()
  })

  it('renders unmeasured, thin and escaped verdicts as their own pills', async () => {
    const thin: ControlsVerdict = { ...VERDICT_FAILED, passed: true, constructible: 24, total: 56, share: 0.4286, state: 'thin' }
    const escaped: ControlsVerdict = { ...VERDICT_FAILED, passed: true, escapes: 3, state: 'escaped' }
    const unmeasured: ControlsVerdict = { measured: false, passed: false, complete: true, constructible: 0, total: 0, share: 0, escapes: 0, run_id: '', created: '', state: 'unmeasured' }
    for (const [v, testid, text] of [
      [thin, 'controls-thin', 'thin 24 of 56'],
      [escaped, 'controls-escaped', '3 escapes'],
      [unmeasured, 'controls-unmeasured', 'unmeasured'],
    ] as const) {
      const { fetchMock } = mockApi({
        'GET /auth/me': PRINCIPAL,
        'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
        'GET /capability-map': { ...MAP_WITH_CONTROLS, cells: [splitCell({ route: 'calibrate', reason: 'controls_thin: …', reason_code: 'controls_thin' })], controls: v },
      })
      const { unmount } = renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
      await waitFor(() => expect(screen.getAllByTestId(testid).length).toBeGreaterThanOrEqual(1))
      expect(screen.getAllByTestId(testid)[0]!.textContent).toContain(text)
      expect(fetchMock).toHaveBeenCalled()
      unmount()
      vi.unstubAllGlobals()
    }
  })
})
