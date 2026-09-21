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
 *               (J-FAC-12). The no-repo state sends every role to Connection.
 * How:          `mockApi` + `renderApp` at `/oracle?repo=…` per role.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0010-polyglot-negative-controls.md
 * Works with:   ui/src/screens/Oracle/OraclePage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Oracle/OraclePage.test.tsx
 * Touch when:   a band, gate or empty state is added.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OracleReport, Principal } from '../../api/types'
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
})
