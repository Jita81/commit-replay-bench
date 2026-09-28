/**
 * ui/src/screens/Oracle/OraclePage.tsx — plain-English purpose, no "auto-ship", and run actions
 * only for the role that can run them.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the oracle page against mocked `GET /oracle/{repo}` and
 *               `GET /oracle/{repo}/controls`.
 * What it does: Pins that the purpose says what a green is worth in plain words (J-HEL-16),
 *               that no tile or pill says "auto-ship" (J-HEL-22), that the band and gate
 *               columns are explained with terms that open inline, and that "Run oracle" /
 *               "Run controls" are offered to an operator only while a viewer reads who acts
 *               (J-FAC-12). The no-repo state sends every role to Connection. Each task's
 *               strength carries the Wilson interval of its served killed / mutants, the
 *               Strong and Adequate tiles name the served policy's floors, and the About
 *               block repeats no floor that could drift from them (G-204); each caught control
 *               shows its gold witness, a red one as an instrument failure (G-952); a passed
 *               report the server reads as unmeasured says it licenses nothing (P-176).
 * How:          `mockApi` + `renderApp` at `/oracle?repo=…` per role.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0010-polyglot-negative-controls.md
 * Works with:   ui/src/screens/Oracle/OraclePage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Oracle/OraclePage.test.tsx
 * Touch when:   never for a new repository; a band, gate or empty state is added.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OracleReport, Principal } from '../../api/types'
import { helpFor } from '../../help/help'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { OraclePage } from './OraclePage'

const VIEWER: Principal = { ...PRINCIPAL, role: 'viewer' }
const OPERATOR: Principal = { ...PRINCIPAL, role: 'operator' }

const EMPTY: OracleReport = { repo: 'alpha', policy: { autoship_floor: 0.8, adequate_floor: 0.5, version: 'adequacy.v1' }, tasks: [], cells: [], apparatus_versions: ['2.2'] }
const SCORED: OracleReport = {
  ...EMPTY,
  tasks: [{ task_id: 'a'.repeat(40), capability_class: 'bug.fix', size: 'S', strength: 0.9, band: 'strong', mutants: 10, killed: 9, gate: 'auto_ship' }],
  cells: [{ capability_class: 'bug.fix', size: 'S', n: 1, strength_mean: 0.9, band: 'strong', gate: 'auto_ship' }],
}

function setup(me: Principal, report: OracleReport, route = '/oracle?repo=alpha') {
  mockApi({
    'GET /auth/me': me,
    'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
    'GET /oracle/alpha': report,
    'GET /oracle/alpha/controls': () => envelope(404, 'not_measured', 'no controls report'),
  })
  return renderApp(<OraclePage />, { route })
}

describe('OraclePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says what a green is worth in plain words and never "auto-ship"; the columns are explained with terms', async () => {
    setup(OPERATOR, SCORED)
    await waitFor(() => expect(screen.getByText('Oracle strength per cell')).toBeInTheDocument())
    expect(screen.getByText(/How much a green is worth for this repository: whether the tests on the changed lines notice a wrong patch/)).toBeInTheDocument()
    // the fixture's raw gate value is `auto_ship`: every spelling of it is banned, the wire form first
    expect(document.body.textContent).not.toMatch(/auto_ship/i)
    expect(document.body.textContent).not.toMatch(/auto-ship/i)
    expect(document.body.textContent).not.toMatch(/autoship/i)
    // the gate column's meaning opens inline from a term
    const term = screen.getAllByRole('button', { name: /oracle strength/ })[0]!
    expect(term).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(term)
    expect(term).toHaveAttribute('aria-expanded', 'true')
    // the escape line names controls and escapes as terms
    expect(screen.getByRole('button', { name: /negative controls/ })).toBeInTheDocument()
  })

  it('a viewer reads who runs the oracle and the controls; an operator gets the links (J-FAC-12)', async () => {
    const viewer = setup(VIEWER, EMPTY)
    await waitFor(() => expect(screen.getByText('No cells scored')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('No controls report yet')).toBeInTheDocument())
    expect(screen.queryByRole('link', { name: 'Run oracle' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Run controls' })).toBeNull()
    expect(screen.getByText(/an operator runs an oracle run/)).toBeInTheDocument()
    expect(screen.getByText(/An operator runs the controls/)).toBeInTheDocument()
    viewer.unmount()
    vi.unstubAllGlobals()

    setup(OPERATOR, EMPTY)
    expect(await screen.findByRole('link', { name: 'Run oracle' })).toHaveAttribute('href', '/runs?repo=alpha&new=oracle')
    expect(await screen.findByRole('link', { name: 'Run controls' })).toHaveAttribute('href', '/runs?repo=alpha&new=controls')
  })

  it('no repo sends every role to Connection', async () => {
    mockApi({ 'GET /auth/me': VIEWER, 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } })
    renderApp(<OraclePage />, { route: '/oracle' })
    expect(await screen.findByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/connect')
  })
  it('a controls escape links to the strengthen report on Learn, for the repository (G-348, G-432)', async () => {
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /oracle/alpha': SCORED,
      'GET /oracle/alpha/controls': { repo: 'alpha', run_id: 'r1', passed: true, n_rows: 7, n_tasks: 1, violations: 0, escapes: 1, not_constructible: 1, skipped: 0, rows: [], verdict: { state: 'escapes', measured: true, passed: false, constructible: 6, total: 7, share: 0.86, escapes: 1, complete: true, run_id: 'r1' } },
    })
    renderApp(<OraclePage />, { route: '/oracle?repo=alpha' })
    const link = await screen.findByRole('link', { name: 'Strengthen the tests on Learn' })
    expect(link.closest('p')).toHaveTextContent('Learning loop, step 2 of 6')
    expect(link).toHaveAttribute('href', '/learn?repo=alpha#strengthen')
  })

  it('a clean controls report sends nobody to Learn', async () => {
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /oracle/alpha': SCORED,
      'GET /oracle/alpha/controls': { repo: 'alpha', run_id: 'r1', passed: true, n_rows: 7, n_tasks: 1, violations: 0, escapes: 0, not_constructible: 1, skipped: 0, rows: [], verdict: { state: 'passed', measured: true, passed: true, constructible: 6, total: 7, share: 0.86, escapes: 0, complete: true, run_id: 'r1' } },
    })
    renderApp(<OraclePage />, { route: '/oracle?repo=alpha' })
    await screen.findByText('Negative-control rows')
    expect(screen.queryByRole('link', { name: 'Strengthen the tests on Learn' })).toBeNull()
  })

  it('a task’s strength carries the Wilson interval of its served counts, and the tiles name the served policy’s floors (G-204)', async () => {
    // a deployment that tightened its floors: the page must read them, never a default
    const tightened: OracleReport = { ...SCORED, policy: { autoship_floor: 0.85, adequate_floor: 0.6, version: 'adequacy.v1+tightened' } }
    setup(OPERATOR, tightened)
    await screen.findByText('Oracle strength per cell')
    // 9 killed of 10 planted: Wilson 95 % [0.60, 0.98], computed from the served counts
    expect(document.body.textContent).toContain('0.90 [0.60, 0.98]')
    expect(screen.getByText('9 / 10')).toBeInTheDocument()
    expect(document.body.textContent).toContain('floor 0.85')
    expect(document.body.textContent).toContain('floor 0.60')
    expect(document.body.textContent).not.toContain('floor 0.80')
    // the Mean strength tile: n = scored tasks, the policy version, the apparatus, and no interval
    expect(document.body.textContent).toContain('mean of 1 task kill-rates (each carries its own Wilson interval below; a mean of rates has none) · adequacy.v1+tightened · apparatus 2.2')
  })

  it('the About block names no floor of its own, so it cannot drift from the served policy (G-204)', () => {
    const about = helpFor('/oracle')!
    expect(about.numbers).toMatch(/policy’s deliver floor/)
    expect(about.numbers).not.toMatch(/[≥≤]\s*0?\.\d/)
  })

  it('each caught control shows its gold witness; a red witness reads as an instrument failure (G-952)', async () => {
    const row = (control: string, verdict: string, witness: string | null) => ({ task_id: 't'.repeat(40), repo: 'alpha', control, expected: 'red', observed: 'red', verdict, note: '', duration_s: 1, witness })
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /oracle/alpha': SCORED,
      'GET /oracle/alpha/controls': { repo: 'alpha', run_id: 'r1', passed: false, n_rows: 3, n_tasks: 1, violations: 1, escapes: 0, not_constructible: 0, skipped: 0, witnessed: 2, witness_failures: 1, rows: [row('gold', 'ok', null), row('noop', 'ok', 'clean'), row('stub', 'VIOLATION', 'red')], verdict: { state: 'failed', measured: true, passed: false, constructible: 3, total: 3, share: 1, escapes: 0, complete: true, run_id: 'r1' } },
    })
    renderApp(<OraclePage />, { route: '/oracle?repo=alpha' })
    await screen.findByText('Negative-control rows')
    const witnesses = screen.getAllByTestId('controls-witness').map((e) => e.textContent)
    expect([...witnesses].sort()).toEqual(['clean', 'red — instrument failure'])
    expect(screen.getByRole('columnheader', { name: /Gold witness/ })).toBeInTheDocument()
  })

  it('a passed report from before the gold witness says it licenses nothing and asks for the controls again (P-176)', async () => {
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /oracle/alpha': SCORED,
      'GET /oracle/alpha/controls': { repo: 'alpha', run_id: 'r1', passed: true, apparatus: { controls_version: 'controls.v2' }, n_rows: 7, n_tasks: 1, violations: 0, escapes: 0, not_constructible: 0, skipped: 0, rows: [], verdict: { state: 'unmeasured', measured: false, passed: false, constructible: 0, total: 0, share: 0, escapes: 0, complete: true, run_id: '' } },
    })
    renderApp(<OraclePage />, { route: '/oracle?repo=alpha' })
    await screen.findByText('Negative-control rows')
    expect(screen.getByText(/unmeasured · no gold witness beside its catches \(controls\.v2\): run the controls again before anything here can deliver/)).toBeInTheDocument()
  })
})
