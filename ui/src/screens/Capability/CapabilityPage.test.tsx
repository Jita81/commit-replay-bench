import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CapabilityCell, CapabilityMap } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { CapabilityPage } from './CapabilityPage'

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

  it('shows the designed empty state when no repo is chosen', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } })
    renderApp(<CapabilityPage />, { route: '/capability' })
    expect(await screen.findByText('Choose a repo to see its capability map')).toBeInTheDocument()
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
