/**
 * ui/src/screens/Learn/LearnPage.tsx — the three reports are named in plain phrases and their
 * words are defined where they appear.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Learn page against the three mocked `GET /learn/*` reports.
 * What it does: Pins that the card eyebrows are plain phrases, not playbook numbers
 *               (J-HEL-17); that each report opens with one sentence saying what a person does
 *               with it and that stale, oracle strength and apparatus are terms that open
 *               inline; that a strengthening item's description is text in the table rather
 *               than a hover-only `title=` (G-287); and that the page keeps no write affordance.
 * How:          `mockApi` with three empty reports; `renderApp` at `/learn?repo=…`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Learn/LearnPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx
 * Touch when:   a fourth report is added.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { LearnPage, type RefusalReport, type RemeasurePlan, type StrengthenReport } from './LearnPage'

const REFUSALS: RefusalReport = { repo: 'alpha', rows_total: 0, rows_protocol: 0, protocol_share: 0, share: { rows_total: 0, rows_protocol: 0, share: 0, ci_low: 0, ci_high: 0 }, by_apparatus: [], cost_usd: 0, minutes: 0, unparsed: 0, apparatus_versions: [], groups: [], note: 'no rows' }
const STRENGTHEN: StrengthenReport = { repo: 'alpha', threshold: 0.8, cells_flagged: [], cells_without_scores: [], items: [], note: 'nothing held' }
const REMEASURE: RemeasurePlan = { repo: 'alpha', current_apparatus: '2.2', min_n: 10, rows_total: 0, rows_stale: 0, cells: [], up_to_date: [], summary: { cells_stale: 0, n_needed_total: 0, est_cost_usd_total: 0, est_minutes_total: 0, cost_known_cells: 0 }, note: 'nothing stale' }

describe('LearnPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('names the three reports in plain phrases and defines their words inline (J-HEL-17)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /learn/refusals': REFUSALS,
      'GET /learn/strengthen': STRENGTHEN,
      'GET /learn/remeasure': REMEASURE,
    })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await waitFor(() => expect(screen.getByText('Nothing stale')).toBeInTheDocument())
    for (const eyebrow of ['Refusals', 'Weak oracles', 'Stale evidence']) expect(screen.getByText(eyebrow)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/play 0\d/)
    expect(document.body.textContent).not.toContain('evidence expires')
    // each report says what a person does with it, and its words are terms
    expect(screen.getByText(/A person judges each class honest or refused/)).toBeInTheDocument()
    // the column header "Stale" is a sort button too: the term is the one with aria-expanded
    const stale = screen.getAllByRole('button', { name: /^stale/i }).find((b) => b.hasAttribute('aria-expanded'))!
    expect(stale).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(stale)
    expect(stale).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /^oracle strength/ })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^apparatus/ }).length).toBeGreaterThanOrEqual(1)
    // read-only by design: no form, no submit
    expect(document.querySelector('form')).toBeNull()
  })

  it('a strengthening item shows its description as text, not as a hover-only title (G-287)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /learn/refusals': REFUSALS,
      'GET /learn/strengthen': {
        ...STRENGTHEN,
        cells_flagged: ['cond_logic/M'],
        items: [
          {
            id: 'alpha-strengthen-1',
            title: 'Cover the branch the mutant survived',
            description: 'Add a test that fails when the comparison is inverted.',
            capability_class: 'cond_logic',
            labels: { cell: 'cond_logic/M', reason_code: 'weak_oracle', oracle_strength: '0.61', threshold: '0.80', escaped: '3' },
          },
        ],
      } satisfies StrengthenReport,
      'GET /learn/remeasure': REMEASURE,
    })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const description = await screen.findByText('Add a test that fails when the comparison is inverted.')
    expect(description).toBeVisible()
    // a keyboard or touch reader can reach it: it is in the table, not on a `title=`
    expect(description.closest('table')).not.toBeNull()
    expect(document.querySelector('[title]')).toBeNull()
  })
})
