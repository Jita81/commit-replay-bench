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
 *               its own pill and the split and model point appear next to the point; that
 *               a map whose refetch fails shows the error and no controls pill, the page
 *               reading every query only through `currentData` (PR #54 review); and that
 *               the open cell's cost and latency carry their known n, interval and apparatus,
 *               an unknown reading as the dash (F35); and that Export CSV is offered to a
 *               viewer, as the About block and the button's hint say (G-102).
 * How:          `mockApi` answers `GET /capability-map` with hand-built maps; `renderApp` at
 *               `/capability?repo=…`; assertions on the `cell-*`, `tile-*`, `kind-*` and
 *               `controls-*` test ids; `qc.refetchQueries()` for a refetch; the page's own
 *               source as `?raw` text for the `currentData` ratchet.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/CapabilityPage.tsx (the code under test),
 *               ui/src/screens/Capability/contract.ts (the fixture shapes),
 *               ui/src/test/utils.tsx (`mockApi`, `renderApp`, `PRINCIPAL`),
 *               ui/src/test/source-ratchets.ts (`queryDataReads`, the `currentData` ratchet)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx
 * Touch when:   never for a new repository; a cell field or controls state is added — extend the
 *               fixtures and assert its rendering here.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CapabilityCell, CapabilityMap } from '../../api/types'
import { helpFor } from '../../help/help'
import { hintText } from '../../help/hints'
import { queryDataReads } from '../../test/source-ratchets'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { CapabilityPage } from './CapabilityPage'
import pageSource from './CapabilityPage.tsx?raw'
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
  policy: { rule: 'look.v1', looks: { '20': 0, '30': 1, '40': 2 }, p_deliver_at_0_80: 0.021, cell_error_budget: 0.05, min_oracle_strength: 0.8, min_oracle_share: 0.5, granularize_sizes: ['XL'], version: 'routing.v2', description: 'A cell routes deliver (routing.v2) only for its standard context arm.' },
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
    expect(cov.textContent).toContain('routing.v2')

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

  it('the posture tile carries its apparatus and says no interval applies; every tile names the apparatus (PR #56 review)', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': { ...MAP, summary: { ...MAP.summary, posture_class: 'docker/copy/sealed', unqualified_posture: 3, excluded_posture_divergent: 1 } },
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    const posture = await screen.findByTestId('tile-posture')
    expect(posture).toHaveTextContent('docker/copy/sealed')
    expect(posture).toHaveTextContent('apparatus 2.0')
    expect(posture).toHaveTextContent('95% CI—')
    expect(posture).toHaveTextContent('no interval: a posture and row counts, not a rate')
    // the class, not the instance: every headline tile on the page carries the map's apparatus
    for (const tile of document.querySelectorAll('[data-component="stat-tile"]')) {
      expect(tile.textContent, tile.getAttribute('data-testid') ?? tile.textContent ?? '').toContain('apparatus 2.0')
    }
  })

  it('the open cell: cost and latency carry the known count as n, the served interval and the apparatus; an unknown is a dash, never $0.00 (F35)', async () => {
    const T = 'Student-t 95% on the known rows (n-1 df), lower bound floored at 0'
    const economics = {
      n_attempts: 40,
      n_clean: 37,
      cost_known: 38,
      cost_known_clean: 35,
      latency_known: 0,
      latency_known_clean: 0,
      apparatus_versions: ['2.3'],
      posture_classes: ['docker/copy/sealed'],
      checks_arms: ['off'],
      pooled: false,
      pooled_reason: '',
      cost_per_attempt: { n: 38, value: 0.012, ci_low: 0.01, ci_high: 0.014, method: T, reason: '' },
      cost_per_clean: { n: 35, value: 0.013, ci_low: 0.011, ci_high: 0.015, method: T, reason: '' },
      latency_per_attempt: { n: 0, value: null, ci_low: null, ci_high: null, method: T, reason: 'no attempt recorded a known latency' },
    }
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': { ...MAP, cells: [cell({ latency_s_mean: 0, economics })] },
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    const tile = await screen.findByTestId('cell-measured')
    // the grid line: the known cost, and a dash for the latency nobody recorded (not "0.0 s")
    expect(within(tile).getByTestId('cell-cost').textContent).toBe('$0.0120')
    expect(within(tile).getByTestId('cell-latency').textContent).toBe('—')
    // in the grid too, a dash carries its reason: the cell's accessible name says it
    expect(tile.getAttribute('aria-label')).toContain('cost $0.0120, latency not shown: no attempt recorded a known latency')
    fireEvent.click(tile)
    const cost = await screen.findByTestId('tile-cost')
    expect(cost).toHaveTextContent('n =38')
    expect(cost).toHaveTextContent('95% CI[$0.0100, $0.0140]')
    expect(cost).toHaveTextContent(`38 of 40 attempts with a known cost · ${T} · apparatus 2.3 · posture docker/copy/sealed`)
    const latency = screen.getByTestId('tile-latency')
    expect(latency).toHaveTextContent('n =0')
    expect(latency).toHaveTextContent('no attempt recorded a known latency')
  })

  it('a cell whose rows span two posture classes shows no cost or latency, and the tile says why (F35, ADR-0019)', async () => {
    const T = 'Student-t 95% on the known rows (n-1 df), lower bound floored at 0'
    const reason = 'rows from 2 posture classes (docker/copy/sealed, local/inplace/host-env) — economics are never pooled across apparatus versions, posture classes or checks arms; read one of each'
    const withheld = { n: 40, value: null, ci_low: null, ci_high: null, method: T, reason }
    const economics = {
      n_attempts: 40,
      n_clean: 37,
      cost_known: 40,
      cost_known_clean: 37,
      latency_known: 40,
      latency_known_clean: 37,
      apparatus_versions: ['2.3'],
      posture_classes: ['docker/copy/sealed', 'local/inplace/host-env'],
      checks_arms: ['off'],
      pooled: true,
      pooled_reason: reason,
      cost_per_attempt: withheld,
      cost_per_clean: { ...withheld, n: 37 },
      latency_per_attempt: withheld,
    }
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': { ...MAP, cells: [cell({ economics })] },
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    const tile = await screen.findByTestId('cell-measured')
    // the flat means still exist on the wire; the grid reads the refused fold, never them
    expect(within(tile).getByTestId('cell-cost').textContent).toBe('—')
    expect(within(tile).getByTestId('cell-latency').textContent).toBe('—')
    expect(tile.getAttribute('aria-label')).toContain(`cost not shown: ${reason}, latency not shown: ${reason}`)
    fireEvent.click(tile)
    const latency = await screen.findByTestId('tile-latency')
    expect(latency).toHaveTextContent('95% CI—')
    expect(latency).toHaveTextContent('never pooled')
    expect(latency).toHaveTextContent('posture docker/copy/sealed, local/inplace/host-env')
  })

  it('the grid legend says cost and latency are means over the attempts with a known value, and what a dash means (F35)', () => {
    for (const id of ['map.cell.cost', 'map.cell.latency'] as const) {
      const text = hintText(id)
      expect(text).toMatch(/over the attempts with a known (cost|latency)/)
      expect(text).toContain('A dash means none was recorded, or the rows span more than one apparatus version, posture class or checks arm')
      expect(text).toContain('open the cell for the reason')
    }
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
    // the tile is described by the one legend under the grid, which names every number (and by its hint bubble, appended)
    const described = tile.getAttribute('aria-describedby')!.split(' ')
    expect(described).toHaveLength(2)
    const legend = document.getElementById(described[0]!)!
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

  it('a viewer is offered Export CSV, and the About block and the hint say anyone signed in can take it (G-102)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    const link = await screen.findByRole('link', { name: /Export CSV/ })
    expect(link.getAttribute('href')).toContain('/ledger/export?format=csv&repo=sqlalchemy')
    // the viewer's own About line names the export, so the button is offered to the role the copy says
    expect(helpFor('/capability')!.next.viewer).toContain('Anyone signed in can press Export CSV')
    expect(hintText('button.capability.export')).toContain('Anyone signed in can take it')
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
    expect(measured.getAttribute('aria-label')).toBe('bug.fix S: human, n 13, point 61.5%, 95% CI 35.5% to 82.3%, false-Q1 0, apparatus 2.0 · belts v4, cost not served, latency not served')
    expect(measured.textContent).toContain('61.5%')
    expect(measured.textContent).toContain('clean 8/13')
    const model = measured.querySelector('[data-testid="model-point"]')!
    expect(model.textContent).toContain('model 89%')
    expect(model.textContent).toContain('(8/9 [56%–98%])') // n and the served Wilson interval travel with the model rate
    const split = measured.querySelector('[data-testid="failure-split"]')!
    expect(split.getAttribute('aria-label')).toBe('red 1, lint 0, api 0, budget 1, protocol 1, harness 2, outage 0, DQ 1')
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

  it('a map that fails on a refetch shows the error and no controls pill as current (PR #54 review)', async () => {
    let calls = 0
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': () => (++calls === 1 ? json(MAP_WITH_CONTROLS) : envelope(500, 'internal', 'boom')),
    })
    const { qc } = renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    await waitFor(() => expect(screen.getByTestId('tile-controls')).toBeInTheDocument())
    expect(screen.getAllByTestId('controls-failed').length).toBeGreaterThanOrEqual(1)
    await qc.refetchQueries()
    await waitFor(() => expect(screen.getByTestId('error-state')).toBeInTheDocument())
    expect(calls).toBe(2)
    expect(screen.queryAllByTestId('controls-failed')).toEqual([])
  })

  it('reads one context arm at a time and names the standard of the cell, or no proven standard (ADR-0026)', async () => {
    const S1 = 'S1@claude-opus-5'
    const reading = {
      reading_id: 'rdg_0123456789abcdef01234567',
      rule: 'look.v1',
      hierarchy: ['S3', S1],
      state: 'standard',
      standard: S1,
      ceiling: false,
      chain: ['S3', S1],
      stopped_at: null,
      needed: 0,
      spend: 0.021,
      registered_at: '2026-09-27T10:00:00+00:00',
      pool: 40,
      pool_sha256: 'a'.repeat(64),
      arms: [
        { arm: 'S3', state: 'deliver', descriptive: false, stopped_by: '', counted: 20, clean: 20, misses: 0, ci_low: 0.839, ci_high: 1, next_look: null, needed: 0 },
        { arm: S1, state: 'deliver', descriptive: false, stopped_by: '', counted: 20, clean: 20, misses: 0, ci_low: 0.839, ci_high: 1, next_look: null, needed: 0 },
      ],
    }
    const standardCell = cell({
      n: 20,
      clean: 20,
      point: 1,
      ci_low: 0.839,
      ci_high: 1,
      context_arm: S1,
      look_state: 'deliver',
      counted: 20,
      counted_clean: 20,
      counted_ci_low: 0.839,
      counted_ci_high: 1,
      reading,
      standard: { standard: S1, ceiling: false, label: `standard ${S1}`, next: '', next_count: 0, budget: 0.05, spent: 0.021 },
      shortfalls: [],
    })
    const s3Cell = cell({
      route: 'calibrate',
      reason: 'no registered reading reads the arm S3',
      reason_code: 'reading_unregistered',
      context_arm: 'S3',
      look_state: 'reading_unregistered',
      reading: null,
      standard: { standard: null, ceiling: false, label: 'no proven standard', next: 'register', next_count: 0, budget: 0.05, spent: 0 },
      shortfalls: [{ code: 'reading_unregistered', route: 'calibrate', observed: null, threshold: 'registered', next: 'register', count: 0, model_money: false }],
    })
    const urls: string[] = []
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'sqlalchemy' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': (url: string) => {
        urls.push(url)
        const s3 = url.includes('arm=S3')
        return json({ ...MAP, cells: [s3 ? s3Cell : standardCell], arm: s3 ? 'S3' : 'standard', arms: ['S3', S1] })
      },
    })
    renderApp(<CapabilityPage />, { route: '/capability?repo=sqlalchemy' })
    await waitFor(() => expect(screen.getByTestId('cell-measured')).toBeInTheDocument())
    expect(screen.getByTestId('cell-arm').textContent).toContain(S1)
    fireEvent.click(screen.getByTestId('cell-measured'))
    expect(screen.getByTestId('tile-standard').textContent).toContain(S1)
    // the tile's headline VALUE itself, not the served label on its sub-line
    expect(within(screen.getByTestId('tile-standard')).getByText(S1, { exact: true }).className).toContain('text-[24px]')
    expect(screen.getAllByTestId('cell-reading-arm')).toHaveLength(2)
    expect(screen.getByTestId('route-bar').textContent).toContain(MAP.policy.description)
    // choose one arm: the map is read on it alone, and it names no proven standard
    fireEvent.change(screen.getByTestId('arm-select'), { target: { value: 'S3' } })
    await waitFor(() => expect(urls.some((u) => u.includes('arm=S3'))).toBe(true))
    await waitFor(() => expect(screen.getByTestId('cell-arm').textContent).toContain('S3'))
    fireEvent.click(screen.getByTestId('cell-measured'))
    expect(screen.getByTestId('tile-standard').textContent).toContain('no proven standard')
    expect(
      within(screen.getByTestId('tile-standard')).getByText('no proven standard', { exact: true }).className,
    ).toContain('text-[24px]')
    expect(screen.getByTestId('cell-shortfalls').textContent).toContain('register')
    expect(screen.getByTestId('cell-readings').textContent).toContain('No reading is registered')
  })

  it('the page reads every query only through currentData', () => {
    // a `<query>.data` read outside QueryBoundary shows an old value after a failed refetch
    // (PR #54 review), so the page's source may not contain one
    expect(queryDataReads(pageSource)).toEqual([])
  })
})
