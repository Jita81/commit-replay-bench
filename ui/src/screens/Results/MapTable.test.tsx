/**
 * MapTable — every cell carries its route, n, interval and sign-off state; the licence sentence.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the class × size table and `licenseSentence`.
 * What it does: Pins that a signed cell reads "signed <date>", an unsigned deliver cell
 *               "sign-off due" (a link to the sign-off with the cell preselected), a stale
 *               sign-off "sign-off stale", an unmeasured cell "not measured · no attempt
 *               sighted", a wide interval "—" + "interval too wide"; and that the licence
 *               sentence names repo, apparatus, belt set, gate, n, class × size, rate with
 *               interval, approver and date, and says nothing about anything else.
 * How:          Pure renders over hand-built cells and sign-offs.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Results/MapTable.tsx (renders the behaviour tested here),
 *               ui/src/api/types.ts (`signoffScopeMatches`, the scope rule the sign-off state follows),
 *               ui/src/screens/Results/ResultsPage.tsx (mounts the table and the licence sentence)
 * Tested by:    ui/src/screens/Results/MapTable.test.tsx
 * Touch when:   a cell line or the sentence's qualifiers change.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { CapabilityCell, CapabilityMap, Signoff } from '../../api/types'
import { MapTable, licenseSentence, signStateOf } from './MapTable'

function cell(over: Partial<CapabilityCell>): CapabilityCell {
  return { capability_class: 'bug.fix', size: 'XS', n: 31, n_tasks: 12, clean: 23, point: 0.74, ci_low: 0.56, ci_high: 0.87, false_q1: 0, route: 'deliver', reason: 'ok', reason_code: 'deliver', verification_tier: 'automated-pass', apparatus_versions: ['2.2'], belt_sets: ['v5'], cost_usd_mean: 0.34, latency_s_mean: 252, ...over } as CapabilityCell
}
function signoff(over: Partial<Signoff>): Signoff {
  return { id: 's1', repo: 'cobra', cell: { capability_class: 'bug.fix', size: 'XS' }, approver: 'a.okafor', created: '2026-09-15T10:00:00Z', revoked: false, active: true, stale: false, apparatus_current: '2.2', evidence: { n: 31, point: 0.74, ci_low: 0.56, ci_high: 0.87, false_q1: 0, apparatus_versions: ['2.2'] }, ...over } as Signoff
}
const MAP = (cells: CapabilityCell[]): CapabilityMap => ({ repo: 'cobra', by: ['capability_class', 'size'], classes: ['bug.fix', 'refactor'], sizes: ['XS', 'S', 'M', 'L', 'XL'], languages: [], models: [], cells, summary: { trusted_autonomy_coverage: 0, total_cells: 10, measured_cells: cells.length, deliver_cells: 1, n_total: 31, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } })

describe('MapTable', () => {
  it('renders the sign-off state on the cell and the honest empty cells', () => {
    const cells = [
      cell({}),
      cell({ size: 'S', n: 18, n_tasks: 9, clean: 11, point: 0.61, ci_low: 0.38, ci_high: 0.8, route: 'human', reason_code: 'ci_low_below_bar' }),
      cell({ size: 'M', n: 4, n_tasks: 3, clean: 3, point: 0.75, ci_low: 0.3, ci_high: 0.95, route: 'calibrate', reason_code: 'n_below_min' }),
      cell({ size: 'XL', n: 0, route: 'granularize', reason_code: 'granularize' }),
      cell({ capability_class: 'refactor', size: 'XS', n: 14, n_tasks: 7, clean: 10, point: 0.71, ci_low: 0.45, ci_high: 0.88 }),
      cell({ capability_class: 'refactor', size: 'S', n: 22, n_tasks: 10, clean: 15, point: 0.68, ci_low: 0.47, ci_high: 0.84, route: 'human', reason_code: 'ci_low_below_bar' }),
    ]
    const signoffs = [signoff({}), signoff({ id: 's2', cell: { capability_class: 'refactor', size: 'S' }, active: false, stale: true, apparatus_current: '2.2', evidence: { n: 22, point: 0.68, ci_low: 0.47, ci_high: 0.84, false_q1: 0, apparatus_versions: ['2.1'] } })]
    render(
      <MemoryRouter>
        <MapTable map={MAP(cells)} signoffs={signoffs} repo="cobra" />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('cell-bug.fix-XS')).toHaveTextContent('deliver')
    expect(screen.getByTestId('cell-bug.fix-XS')).toHaveTextContent('n=31 on 12 tasks')
    expect(screen.getByTestId('cell-bug.fix-XS')).toHaveTextContent('74%')
    expect(screen.getByTestId('cell-bug.fix-XS')).toHaveTextContent('[56%, 87%]')
    // the number carries its apparatus
    expect(screen.getByTestId('cell-bug.fix-XS')).toHaveTextContent('app 2.2')
    expect(screen.getByTestId('cell-bug.fix-XS')).toHaveTextContent('signed 15 Sept')
    expect(screen.getByTestId('cell-bug.fix-S')).toHaveTextContent('ci_low_below_bar')
    expect(screen.getByTestId('cell-bug.fix-M')).toHaveTextContent('interval too wide')
    expect(screen.getByTestId('cell-bug.fix-M')).toHaveTextContent('n_below_min')
    expect(screen.getByTestId('cell-bug.fix-L')).toHaveTextContent('not measured')
    expect(screen.getByTestId('cell-bug.fix-L')).toHaveTextContent('no attempt sighted')
    expect(screen.getByTestId('cell-bug.fix-XL')).toHaveTextContent('XL is split first')
    // an unsigned deliver cell is due, linking to the sign-off with the cell preselected
    const due = screen.getByTestId('cell-refactor-XS')
    expect(due).toHaveTextContent('sign-off due')
    expect(due.querySelector('a')).toHaveAttribute('href', '/signoff?repo=cobra&cell=refactor%7CXS')
    expect(screen.getByTestId('cell-refactor-S')).toHaveTextContent('sign-off stale')
    expect(signStateOf(cells[5]!, signoffs).state).toBe('stale')
  })

  it('the licence sentence quotes the STAMPED snapshot with every qualifier, says when the cell has moved on, and is null with no signed cell', () => {
    const map = { ...MAP([cell({})]), controls: { measured: true, passed: true, complete: true, constructible: 31, total: 56, share: 0.55, escapes: 0, run_id: 'r', created: 'x', state: 'passed' as const } }
    const s = licenseSentence('cobra', map, [signoff({})])
    expect(s).toBe('On cobra at apparatus 2.2, under belt set v5 and a passed controls gate, 31 sighted attempts at bug.fix × XS were graded clean at 74% (95% Wilson 56%–87%) with false-Q1 0, as signed by a.okafor on 15 September 2026. It says nothing about any other repository, class or size.')
    // rows added since signing: the sentence still quotes what was signed, and says the cell moved
    const grown = { ...map, cells: [cell({ n: 40, clean: 32, point: 0.8, ci_low: 0.65, ci_high: 0.9 })] }
    expect(licenseSentence('cobra', grown, [signoff({})])).toContain('31 sighted attempts at bug.fix × XS were graded clean at 74%')
    expect(licenseSentence('cobra', grown, [signoff({})])).toContain('The cell has since grown to n=40 (80%); that is not what was signed.')
    expect(licenseSentence('cobra', MAP([cell({})]), [])).toBeNull()
    expect(licenseSentence('cobra', MAP([cell({})]), [signoff({ stale: true, active: false })])).toBeNull()
  })

  it('sign-off scope follows the server: a size wildcard covers the cell, a narrower model does not', () => {
    const c = cell({})
    expect(signStateOf(c, [signoff({ cell: { capability_class: 'bug.fix', size: '*' } })]).state).toBe('signed')
    expect(signStateOf(c, [signoff({ cell: { capability_class: 'bug.fix', size: 'XS', model: 'claude-sonnet-5' } })]).state).toBe('due')
    expect(signStateOf(c, [signoff({ cell: { capability_class: 'feature.add', size: '*' } })]).state).toBe('due')
  })
})
