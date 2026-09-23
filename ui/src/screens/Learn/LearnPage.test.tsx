/**
 * ui/src/screens/Learn/LearnPage.tsx — the three reports are named in plain phrases and their
 * words are defined where they appear.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Learn page against the three mocked `GET /learn/*` reports
 *               and the three writes an operator makes from them.
 * What it does: Pins that the card eyebrows are plain phrases, not playbook numbers
 *               (J-HEL-17); that each report opens with one sentence saying what a person does
 *               with it and that stale, oracle strength and apparatus are terms that open
 *               inline; that a strengthening item's description is text in the table rather
 *               than a hover-only `title=` (G-287). For the three decisions (G-532): that a
 *               VIEWER is offered none of them; that a refusal verdict is a form whose success
 *               state names the verdict, the decider and the corpus file; that a class already
 *               decided reads its verdict and who made it instead of offering the form again;
 *               that registering an item reports the backlog it landed on and what it
 *               superseded; and that queueing runs confirms the plan's own estimate first, so
 *               nothing is sent by one click, and then names what was queued.
 * How:          `mockApi` with three reports (empty, or one row each where a row is needed) and
 *               the three POSTs; `renderApp` at `/learn?repo=…` as the role under test.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Learn/LearnPage.tsx (the code under test), ui/src/test/utils.tsx
 *               (`mockApi`, `renderApp`, `PRINCIPAL`), src/crb/server/routes/learn.py (the
 *               routes these mocks stand in for), tests/test_server_routes_learn.py (the same
 *               three writes proved against a real store)
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx
 * Touch when:   a fourth report is added, or a write path gains a field the success state
 *               should name.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { LearnPage, type RefusalGroup, type RefusalReport, type RemeasureCell, type RemeasurePlan, type StrengthenItem, type StrengthenReport } from './LearnPage'

const REFUSALS: RefusalReport = { repo: 'alpha', rows_total: 0, rows_protocol: 0, protocol_share: 0, share: { rows_total: 0, rows_protocol: 0, share: 0, ci_low: 0, ci_high: 0 }, by_apparatus: [], cost_usd: 0, minutes: 0, unparsed: 0, apparatus_versions: [], groups: [], decisions: [], note: 'no rows' }
const STRENGTHEN: StrengthenReport = { repo: 'alpha', threshold: 0.8, cells_flagged: [], cells_without_scores: [], items: [], note: 'nothing held' }
const REMEASURE: RemeasurePlan = { repo: 'alpha', current_apparatus: '2.2', min_n: 10, rows_total: 0, rows_stale: 0, cells: [], up_to_date: [], summary: { cells_stale: 0, n_needed_total: 0, est_cost_usd_total: 0, est_minutes_total: 0, cost_known_cells: 0 }, note: 'nothing stale' }

/** One refusal class, one strengthening item and one stale cell — the rows the three decisions act on. */
const GROUP: RefusalGroup = { group_id: 'g1', prefix: 'network', reason: 'egress refused', shape: 'curl <url>', n: 3, cost_usd: 1.2, minutes: 4, repos: ['alpha'], tasks: ['t1'], examples: ['curl https://x'], truncated: false, candidate_honest: 'curl https://x', candidate_refused: 'curl https://x\tnetwork:', verdict: 'unsure' }
const ITEM: StrengthenItem = { id: 'strengthen-1', title: 'Strengthen the divide tests', description: 'kill the surviving mutants', capability_class: 'test.add', labels: { cell: 'bug.fix|S', reason_code: 'oracle_weak', oracle_strength: '0.40', threshold: '0.80', escaped: '1' } }
const CELL: RemeasureCell = { label: 'replay|bug.fix|S|python|editblock|m|cerebras', mode: 'sighted', stale_versions: ['2.1'], n_stale: 12, n_current: 4, n_needed: 6, est_cost_usd: 2.4, est_minutes: 30, cost_known: true, repos: ['alpha'], requests: [{ kind: 'replay' }, { kind: 'replay' }] }

/** The signed-in operator's view of one repository with one row in each report. */
function operatorApi(extra: Record<string, unknown> = {}) {
  return {
    'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
    'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
    'GET /learn/refusals': { ...REFUSALS, groups: [GROUP] },
    'GET /learn/strengthen': { ...STRENGTHEN, items: [ITEM] },
    'GET /learn/remeasure': { ...REMEASURE, cells: [CELL] },
    ...extra,
  }
}

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
  })

  it('offers a viewer none of the three decisions (they are operator acts at the API too)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /learn/refusals': { ...REFUSALS, groups: [GROUP] },
      'GET /learn/strengthen': { ...STRENGTHEN, items: [ITEM] },
      'GET /learn/remeasure': { ...REMEASURE, cells: [CELL] },
    })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await waitFor(() => expect(screen.getByText('egress refused')).toBeInTheDocument())
    for (const name of ['Decide', 'Register', 'Queue runs']) expect(screen.queryByRole('button', { name })).toBeNull()
    expect(screen.getByText(/An operator records the verdict/)).toBeInTheDocument()
    // the verdict is still shown, and still unsure
    expect(screen.getByText('unsure')).toBeInTheDocument()
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

  it('a refusal verdict is a form, and its success state names the verdict, the decider and the file (G-532)', async () => {
    const { calls } = mockApi(
      operatorApi({
        'POST /learn/refusals/accept': {
          repo: 'alpha',
          group_id: 'g1',
          verdict: 'refuse',
          decided_by: 'root',
          honest_added: [],
          refused_added: ['curl https://x\tnetwork:'],
          skipped: [],
          already_present: false,
          corpus_dir: '/srv/crb/learn/corpus',
          honest_path: '/srv/crb/learn/corpus/shell_corpus.txt',
          refused_path: '/srv/crb/learn/corpus/shell_corpus_refused.txt',
        },
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Decide' }))
    // the class's own words, so nobody decides from a row number
    const summary = within(await screen.findByTestId('learn-decide-summary'))
    expect(summary.getByText('egress refused')).toBeInTheDocument()
    expect(summary.getByText('curl <url>')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText(/Your verdict/), 'refuse')
    await userEvent.type(screen.getByLabelText(/Why/), 'probing the sandbox')
    await userEvent.click(screen.getByRole('button', { name: 'Record this decision' }))
    const done = await screen.findByText(/Recorded as refuse by root/)
    expect(done).toHaveAttribute('role', 'status')
    expect(done.textContent).toContain('shell_corpus_refused.txt')
    expect(done.textContent).toContain('Run the guard corpus test')
    // the decider is never sent by the browser: the server takes it from the session
    const posted = JSON.parse(String(calls.find((c) => c.method === 'POST')!.init!.body))
    expect(posted).toEqual({ group_id: 'g1', verdict: 'refuse', note: 'probing the sandbox' })
  })

  it('a class already decided reads its verdict and who decided it, and is not offered the form again', async () => {
    mockApi(
      operatorApi({
        'GET /learn/refusals': {
          ...REFUSALS,
          groups: [GROUP],
          decisions: [{ group_id: 'g1', verdict: 'honest', decided_by: 'root', decided_by_id: 'u1', decided_at: '2026-09-23T10:00:00+00:00', note: 'quoted argument', lines: ['curl https://x'], already_present: false }],
        } satisfies RefusalReport,
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    expect(await screen.findByText('honest')).toBeInTheDocument()
    expect(screen.getByText('by root')).toBeInTheDocument()
    expect(screen.getByText('recorded')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Decide' })).toBeNull()
  })

  it('registering a strengthening item says which backlog it is on and what it superseded (G-532)', async () => {
    mockApi(
      operatorApi({
        'POST /learn/strengthen/register': {
          repo: 'alpha',
          registered: [{ item_id: 'strengthen-1-v2', supersedes: 'strengthen-1', how: 'evolved' }],
          backlog_hash: 'h'.repeat(64),
          evolutions_hash: 'e'.repeat(64),
        },
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Register' }))
    const done = await screen.findByText(/strengthen-1-v2 was registered/)
    expect(done).toHaveAttribute('role', 'status')
    expect(done.textContent).toContain('superseding strengthen-1')
    expect(screen.getByRole('link', { name: 'Factory' })).toHaveAttribute('href', '/factory?repo=alpha')
  })

  it('queueing a re-measurement confirms the plan’s own estimate before anything is sent (G-532)', async () => {
    const { calls } = mockApi(
      operatorApi({
        'POST /learn/remeasure/queue': { repo: 'alpha', cell: CELL.label, mode: 'sighted', run_ids: ['r1', 'r2'], n_needed: 6, est_cost_usd: 2.4, cost_known: true },
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Queue runs' }))
    // the confirmation repeats the plan's numbers, and nothing has been sent yet
    const plan = within(await screen.findByTestId('learn-queue-summary'))
    expect(plan.getByText(CELL.label)).toBeInTheDocument()
    expect(plan.getByText('sighted')).toBeInTheDocument()
    expect(plan.getByText('6')).toBeInTheDocument()
    expect(plan.getByText('$2.40')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
    await userEvent.click(screen.getByRole('button', { name: 'Queue the runs' }))
    const done = await screen.findByText(/Queued 2 runs/)
    expect(done).toHaveAttribute('role', 'status')
    expect(done.textContent).toContain('The plan estimated $2.40.')
    expect(screen.getByRole('link', { name: 'Runs' })).toHaveAttribute('href', '/runs?repo=alpha')
  })

  it('a cell whose cost nothing recorded says so instead of showing zero', async () => {
    mockApi(operatorApi({ 'GET /learn/remeasure': { ...REMEASURE, cells: [{ ...CELL, cost_known: false, est_cost_usd: 0 }] } }))
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Queue runs' }))
    const plan = within(await screen.findByTestId('learn-queue-summary'))
    expect(plan.getByText('not known — no row of this cell recorded a cost')).toBeInTheDocument()
    expect(plan.queryByText('$0.00')).toBeNull()
  })
})
