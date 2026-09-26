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
 *               than a hover-only `title=` (G-287); that the three reports keep no write
 *               affordance; and the prevention register card (ADR-0020): each class with its
 *               lever, level, before → after with both n and the bar, and its status; a viewer
 *               sees the switch and every change but no control; an operator's switch needs a
 *               reason and names who threw it; a revert and an item registration each report
 *               what they wrote.
 * How:          `mockApi` with three empty reports and the populated register fixture
 *               (ui/src/screens/Learn/register.fixture.ts); `renderApp` at `/learn?repo=…`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Learn/LearnPage.tsx (the code under test),
 *               ui/src/screens/Learn/PreventionSection.tsx (the register card),
 *               ui/src/screens/Learn/register.fixture.ts (the register), ui/src/test/utils.tsx
 *               (renders the page with a mocked API)
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx
 * Touch when:   a fourth report is added.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { LearnPage, type RefusalReport, type RemeasurePlan, type StrengthenReport } from './LearnPage'
import { REGISTER } from './register.fixture'

const REFUSALS: RefusalReport = { repo: 'alpha', rows_total: 0, rows_protocol: 0, protocol_share: 0, share: { rows_total: 0, rows_protocol: 0, share: 0, ci_low: 0, ci_high: 0 }, by_apparatus: [], cost_usd: 0, minutes: 0, unparsed: 0, apparatus_versions: [], groups: [], note: 'no rows' }
const STRENGTHEN: StrengthenReport = { repo: 'alpha', threshold: 0.8, cells_flagged: [], cells_without_scores: [], items: [], note: 'nothing held' }
const REMEASURE: RemeasurePlan = { repo: 'alpha', current_apparatus: '2.2', min_n: 10, rows_total: 0, rows_stale: 0, cells: [], up_to_date: [], summary: { cells_stale: 0, n_needed_total: 0, est_cost_usd_total: 0, est_minutes_total: 0, cost_known_cells: 0 }, note: 'nothing stale' }

describe('the register fixture', () => {
  it('gives every entry its own counts, never those of another entry (CodeRabbit, PR #57)', () => {
    const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0)
    for (const e of REGISTER.entries) {
      expect(sum(e.by_mode)).toBe(e.occurrences)
      expect(sum(e.by_apparatus)).toBe(e.occurrences)
      expect(e.refs_total).toBe(e.occurrences)
      expect(e.refs.length).toBeLessThanOrEqual(e.refs_total)
      expect(e.stratum.k).toBe(e.first_attempts)
      expect(e.tasks).toBeLessThanOrEqual(e.occurrences)
      // "41 of 10 comparable" contradicts itself: n is never read as a share of the minimum
      for (const m of `${e.why_not} ${e.next}`.matchAll(/(\d+) of (\d+) comparable/g)) {
        expect(Number(m[1])).toBeLessThanOrEqual(Number(m[2]))
      }
    }
  })
})

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
    for (const eyebrow of ['Prevention', 'Refusals', 'Weak oracles', 'Stale evidence']) expect(screen.getByText(eyebrow)).toBeInTheDocument()
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
    // the three reports are read-only by design: no form, no submit — even for an operator
    // (the register card above them is the one place an operator acts, under the switch)
    for (const eyebrow of ['Refusals', 'Weak oracles', 'Stale evidence']) {
      const card = screen.getByText(eyebrow).closest('section')!
      expect(card.querySelector('form')).toBeNull()
      expect(within(card).queryByRole('button', { name: /register|revert|switch|run the loop/i })).toBeNull()
    }
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

  const BASE = {
    'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
    'GET /learn/refusals': REFUSALS,
    'GET /learn/strengthen': STRENGTHEN,
    'GET /learn/remeasure': REMEASURE,
  }

  it('the register card shows each class with its lever, level, before → after and status', async () => {
    mockApi({ ...BASE, 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /learn/register': REGISTER })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const table = (await screen.findByText('Bug classes and the change that removes them')).closest('table')!
    const row = within(table).getByText('protocol:network:go mod').closest('tr')!
    expect(row).toHaveTextContent('12 of 41 blind')
    expect(row).toHaveTextContent('line:T-NET')
    expect(within(row).getByText('advisory')).toBeInTheDocument()
    // before → after, each with its n, and the bar the rule decides at
    expect(row).toHaveTextContent('9/30 → 3/11')
    expect(row).toHaveTextContent('keep if P(X ≤ k | n = 11, p0 = 0.300) ≤ 0.025')
    expect(within(row).getByText('applied')).toBeInTheDocument()
    const watch = within(table).getByText('budget:max_turns').closest('tr')!
    expect(within(watch).getByText('open')).toBeInTheDocument()
    expect(within(watch).getByText('watch')).toBeInTheDocument()
    const escalated = within(table).getByText('harness:runner-tool-missing:jest').closest('tr')!
    expect(within(escalated).getByText('escalated')).toBeInTheDocument()
    // the tiles: classes by status, the playbook against its caps, the switch with who and why
    expect(screen.getByText('1 of 7 lines')).toBeInTheDocument()
    expect(screen.getByText(/thrown by op-1 on .*: try the lines on alpha/)).toBeInTheDocument()
    expect(screen.getByText('0 of 3')).toBeInTheDocument()
  })

  it('a viewer sees the switch and every change but no control', async () => {
    mockApi({ ...BASE, 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /learn/register': REGISTER })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha&class=protocol%3Anetwork%3Ago%20mod' })
    await screen.findByText('Bug classes and the change that removes them')
    expect(screen.getByText('context')).toBeInTheDocument()
    // ?class= opens that class's details: what changed, the records, the filed items
    const details = document.querySelector('details[data-class="protocol:network:go mod"]') as HTMLDetailsElement
    expect(details.open).toBe(true)
    expect(details).toHaveTextContent('Change c0ffee0c0ffe')
    expect(details).toHaveTextContent('prevent-e2e3c3b7b3e8')
    const card = screen.getByText('Prevention').closest('section')!
    expect(card.querySelector('form')).toBeNull()
    expect(within(card).queryByRole('button', { name: /register|revert|throw the switch|run the loop/i })).toBeNull()
  })

  it('an operator reverts a change with a reason', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /learn/register': REGISTER,
      'POST /learn/changes/c0ffee0c0ffee0c0/revert': { repo: 'alpha', change_id: 'c0ffee0c0ffee0c0', lever_id: 'line:T-NET', targets: ['protocol:network:go mod'], record: { kind: 'reverted', repo: 'alpha', record_id: 'x', created: '', actor: 'op-7', on_behalf_of: 'op-7', reason: 'it confused review', payload: {}, row_hash: 'ab'.repeat(32) } },
    })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha&class=protocol%3Anetwork%3Ago%20mod' })
    const revert = await screen.findByRole('button', { name: 'Revert' })
    expect(revert).toBeDisabled() // a reason is required
    await userEvent.type(screen.getByLabelText(/Why revert/), 'it confused review')
    await userEvent.click(revert)
    expect(await screen.findByText(/Reverted line:T-NET by op-7; the loop will not re-apply it\. Record abababababab\./)).toBeInTheDocument()
    const call = calls.find((c) => c.method === 'POST' && c.path === '/learn/changes/c0ffee0c0ffee0c0/revert')!
    expect(call.url).toContain('repo=alpha')
    expect(JSON.parse(String(call.init?.body))).toEqual({ reason: 'it confused review' })
  })

  it('the switch needs a reason and names who threw it', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /learn/register': REGISTER,
      'PUT /learn/switch': { repo: 'alpha', switch: { ...REGISTER.switch, auto_apply: 'config', switched_by: 'op-7' }, record: { kind: 'switched', repo: 'alpha', record_id: 'y', created: '', actor: 'op-7', on_behalf_of: 'op-7', reason: 'switches on alpha', payload: {}, row_hash: 'cd'.repeat(32) } },
    })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const go = await screen.findByRole('button', { name: 'Throw the switch' })
    expect(go).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('Learning switch'), 'config')
    await userEvent.type(screen.getByLabelText(/^Reason/), 'switches on alpha')
    await userEvent.click(go)
    expect(await screen.findByText('Switch set to config by op-7; record cdcdcdcdcdcd.')).toBeInTheDocument()
    const call = calls.find((c) => c.method === 'PUT' && c.path === '/learn/switch')!
    // the body carries the choice and the reason — never who decided (the session is the decider)
    expect(JSON.parse(String(call.init?.body))).toEqual({ auto_apply: 'config', reason: 'switches on alpha' })
  })

  it('a filed item registers in one act', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /learn/register': REGISTER,
      'POST /learn/items/prevent-e2e3c3b7b3e8/register': { repo: 'alpha', item_id: 'prevent-e2e3c3b7b3e8', registered_id: 'prevent-e2e3c3b7b3e8', supersedes: '', how: 'frozen', record: { kind: 'registered', repo: 'alpha', record_id: 'z', created: '', actor: 'op-7', on_behalf_of: 'op-7', reason: '', payload: {}, row_hash: 'ef'.repeat(32) } },
    })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha&class=protocol%3Anetwork%3Ago%20mod' })
    const details = await waitFor(() => {
      const d = document.querySelector('details[data-class="protocol:network:go mod"]')
      if (!d) throw new Error('not yet')
      return d as HTMLElement
    })
    // the product-scoped item is served, never offered for this repository's backlog
    expect(details).toHaveTextContent('never put on this repository’s backlog')
    const buttons = within(details).getAllByRole('button', { name: 'Register' })
    expect(buttons).toHaveLength(1)
    await userEvent.click(buttons[0]!)
    expect(await within(details).findByText('Registered prevent-e2e3c3b7b3e8 (frozen) by op-7; record efefefefefef.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/learn/items/prevent-e2e3c3b7b3e8/register' && c.url.includes('repo=alpha'))).toBe(true)
  })
})
