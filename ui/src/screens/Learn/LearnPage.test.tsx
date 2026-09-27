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
 *               than a hover-only `title=` (G-287); the prevention register card (ADR-0020):
 *               each class with its lever, level, before → after with both n and the bar, and
 *               its status; a viewer sees the switch and every change but no control; an
 *               operator's switch needs a reason and names who threw it; a revert and an item
 *               registration each report what they wrote. For the three decisions beside the
 *               reports (G-532): that a VIEWER is offered none of them; that a refusal verdict
 *               is a form whose success state names the verdict, the decider and the corpus
 *               file; that a class already decided reads its verdict and who made it instead
 *               of offering the form again; that registering an item reports the backlog it
 *               landed on and what it superseded; and that queueing runs confirms the plan's
 *               own estimate first, so nothing is sent by one click, and then names what was
 *               queued — an unknown estimate as unknown, never $0.00; and that the note is a
 *               one-line field (P-094).
 * How:          `mockApi` with three reports (empty, or one row each where a row is needed),
 *               the populated register fixture (ui/src/screens/Learn/register.fixture.ts) and
 *               the POSTs; `renderApp` at `/learn?repo=…` as the role under test.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Learn/LearnPage.tsx (the code under test),
 *               ui/src/screens/Learn/PreventionSection.tsx (the register card),
 *               ui/src/screens/Learn/register.fixture.ts (the register), ui/src/test/utils.tsx
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
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { LearnPage, type RefusalGroup, type RefusalReport, type RemeasureCell, type RemeasurePlan, type StrengthenItem, type StrengthenReport } from './LearnPage'
import { REGISTER } from './register.fixture'

const REFUSALS: RefusalReport = { repo: 'alpha', rows_total: 0, rows_protocol: 0, protocol_share: 0, share: { rows_total: 0, rows_protocol: 0, share: 0, ci_low: 0, ci_high: 0 }, by_apparatus: [], cost_usd: 0, minutes: 0, unparsed: 0, apparatus_versions: [], groups: [], decisions: [], note: 'no rows' }
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

/** One refusal class, one strengthening item and one stale cell — the rows the three decisions act on. */
const GROUP: RefusalGroup = { group_id: 'g1', prefix: 'network', reason: 'egress refused', shape: 'curl <url>', n: 3, cost_usd: 1.2, minutes: 4, repos: ['alpha'], tasks: ['t1'], examples: ['curl https://x'], truncated: false, candidate_honest: 'curl https://x', candidate_refused: 'curl https://x\tnetwork:', verdict: 'unsure' }
const ITEM: StrengthenItem = { id: 'strengthen-1', title: 'Strengthen the divide tests', description: 'kill the surviving mutants', capability_class: 'test.add', labels: { cell: 'bug.fix|S', reason_code: 'oracle_weak', oracle_strength: '0.40', threshold: '0.80', escaped: '1' } }
const CELL: RemeasureCell = { label: 'replay|bug.fix|S|python|editblock|m|cerebras', mode: 'sighted', stale_versions: ['2.1'], n_stale: 12, n_current: 4, n_needed: 6, est_cost_usd: 2.4, est_minutes: 30, cost_known: true, repos: ['alpha'], requests: [{ kind: 'replay' }, { kind: 'replay' }], in_flight_run_ids: [] }

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
    // the header says the product decides nothing, and whose each decision is
    expect(screen.getByText(/The product decides nothing: the register acts only under an operator’s switch, and each report’s decision is an operator’s, recorded with their name\./)).toBeInTheDocument()
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
    // with nothing to decide, the three reports offer an operator no form and no control:
    // each decision is a control on the row it acts on, never a free-standing write
    for (const eyebrow of ['Refusals', 'Weak oracles', 'Stale evidence']) {
      const card = screen.getByText(eyebrow).closest('section')!
      expect(card.querySelector('form')).toBeNull()
      expect(within(card).queryByRole('button', { name: /register|revert|switch|run the loop/i })).toBeNull()
    }
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
    // the hand-off arrives pre-filled: the Factory opens on the item just registered (G-351)
    expect(screen.getByRole('link', { name: 'Factory' })).toHaveAttribute('href', '/factory?repo=alpha&item=strengthen-1-v2')
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

  it('a cell whose runs are still in flight shows them in place of Queue, so the estimate is never spent twice', async () => {
    // the plan reads graded rows only, so it still holds a cell whose runs are queued: after a
    // queue the page re-reads the plan and offers the runs, not a second Queue
    let reads = 0
    mockApi(
      operatorApi({
        'GET /learn/remeasure': () => json({ ...REMEASURE, cells: [{ ...CELL, in_flight_run_ids: reads++ === 0 ? [] : ['r1', 'r2'] }] }),
        'POST /learn/remeasure/queue': { repo: 'alpha', cell: CELL.label, mode: 'sighted', run_ids: ['r1', 'r2'], n_needed: 6, est_cost_usd: 2.4, cost_known: true },
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Queue runs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Queue the runs' }))
    await screen.findByText(/Queued 2 runs/)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    const remeasure = within(document.getElementById('remeasure')!)
    const inFlight = await remeasure.findByRole('link', { name: '2 runs queued' })
    expect(inFlight).toHaveAttribute('href', '/runs?repo=alpha')
    expect(remeasure.queryByRole('button', { name: 'Queue runs' })).toBeNull()
  })

  it('a cell whose cost nothing recorded says so instead of showing zero', async () => {
    mockApi(operatorApi({ 'GET /learn/remeasure': { ...REMEASURE, cells: [{ ...CELL, cost_known: false, est_cost_usd: 0 }] } }))
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Queue runs' }))
    const plan = within(await screen.findByTestId('learn-queue-summary'))
    expect(plan.getByText('not known — no row of this cell recorded a cost')).toBeInTheDocument()
    expect(plan.queryByText('$0.00')).toBeNull()
  })

  it('what was queued for a cell with no recorded cost says the cost is not known, never $0.00', async () => {
    mockApi(
      operatorApi({
        'GET /learn/remeasure': { ...REMEASURE, cells: [{ ...CELL, cost_known: false, est_cost_usd: 0 }] },
        'POST /learn/remeasure/queue': { repo: 'alpha', cell: CELL.label, mode: 'sighted', run_ids: ['r1'], n_needed: 6, est_cost_usd: 0, cost_known: false },
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Queue runs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Queue the runs' }))
    const done = await screen.findByText(/Queued 1 run for/)
    expect(done).toHaveAttribute('role', 'status')
    expect(done.textContent).toContain('The cost is not known: no row of this cell recorded one.')
    expect(done.textContent).not.toContain('$0.00')
    expect(done.textContent).not.toContain('The plan estimated')
  })

  it('the note is one line: the Why field takes no line break, because it is written as a corpus comment (P-094)', async () => {
    const { calls } = mockApi(operatorApi({ 'POST /learn/refusals/accept': { repo: 'alpha', group_id: 'g1', verdict: 'honest', decided_by: 'root', honest_added: ['curl https://x'], refused_added: [], skipped: [], already_present: false, corpus_dir: '/c', honest_path: '/c/shell_corpus.txt', refused_path: '/c/shell_corpus_refused.txt' } }))
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await userEvent.click(await screen.findByRole('button', { name: 'Decide' }))
    const why = screen.getByLabelText(/Why/)
    expect(why.tagName).toBe('INPUT')
    await userEvent.type(why, 'fine{Enter}rm -rf /')
    await userEvent.click(screen.getByRole('button', { name: 'Record this decision' }))
    await screen.findByText(/Recorded as honest by root/)
    const posted = JSON.parse(String(calls.find((c) => c.method === 'POST')!.init!.body)) as { note: string }
    expect(posted.note).not.toMatch(/[\n\r]/)
  })
  it('with no repository chosen, says which is missing and offers the one action to connect one (G-172)', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } })
    renderApp(<LearnPage />, { route: '/learn' })
    expect(await screen.findByText('Pick a repository')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/connect')
  })

  it('the refusal tile reads one apparatus’s rate with its n, interval and version (G-173)', async () => {
    const one = { apparatus_version: '2.2', rows_total: 40, rows_protocol: 3, share: 0.075, ci_low: 0.026, ci_high: 0.2 }
    mockApi(operatorApi({ 'GET /learn/refusals': { ...REFUSALS, rows_total: 40, rows_protocol: 3, protocol_share: 0.075, share: one, by_apparatus: [one], groups: [GROUP] } }))
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const tile = (await screen.findByText('Instrument-caused rows')).closest('[data-component="stat-tile"]')!
    expect(tile).toHaveTextContent('7.5%')
    expect(tile).toHaveTextContent('n =40')
    expect(tile).toHaveTextContent('95% CI[2.6%, 20.0%]')
    expect(tile).toHaveTextContent('apparatus 2.2 · failure_kind = protocol · Wilson 95%')
  })

  it('with two apparatus versions the refusal tile shows each version’s own rate, never a blended headline (G-173)', async () => {
    const a = { apparatus_version: '2.1', rows_total: 20, rows_protocol: 1, share: 0.05, ci_low: 0.009, ci_high: 0.236 }
    const b = { apparatus_version: '2.2', rows_total: 20, rows_protocol: 5, share: 0.25, ci_low: 0.112, ci_high: 0.469 }
    const blended = { rows_total: 40, rows_protocol: 6, share: 0.15, ci_low: 0.071, ci_high: 0.291 }
    mockApi(operatorApi({ 'GET /learn/refusals': { ...REFUSALS, rows_total: 40, rows_protocol: 6, protocol_share: 0.15, share: blended, by_apparatus: [a, b], groups: [GROUP] } }))
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const tile = (await screen.findByText('Instrument-caused rows (per apparatus)')).closest('[data-component="stat-tile"]')!
    expect(tile).toHaveTextContent('2.1: 5.0% · 2.2: 25.0%')
    expect(tile).toHaveTextContent('2.1: 1/20 [1%–24%] · 2.2: 5/20 [11%–47%] · Wilson 95%')
    expect(tile).not.toHaveTextContent('15.0%')
    expect(tile).toHaveTextContent('95% CI—')
  })

  it('a report that fails says why and retries alone; the other two still render (G-174)', async () => {
    let strengthenCalls = 0
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => {
      release = r
    })
    mockApi(
      operatorApi({
        'GET /learn/remeasure': async () => {
          await gate
          return json({ ...REMEASURE, cells: [CELL] })
        },
        'GET /learn/strengthen': () => {
          strengthenCalls += 1
          return strengthenCalls === 1 ? envelope(500, 'internal_error', 'the oracle scores could not be read') : json({ ...STRENGTHEN, items: [ITEM] })
        },
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    // the loading line names the report still being derived
    expect(await screen.findByText('Deriving the re-measurement plan…')).toBeInTheDocument()
    release()
    expect(await screen.findByText('the oracle scores could not be read')).toBeInTheDocument()
    // the other two reports rendered regardless
    expect(await screen.findByText('egress refused')).toBeInTheDocument()
    expect(await screen.findByText(CELL.label)).toBeInTheDocument()
    const card = document.getElementById('strengthen')!
    await userEvent.click(within(card).getByRole('button', { name: /retry/i }))
    expect(await within(card).findByText('Strengthen the divide tests')).toBeInTheDocument()
    expect(strengthenCalls).toBe(2)
  })

  it('an operator’s strengthening row hands off to Runs pre-filled with its task (G-352)', async () => {
    const task = 'c'.repeat(40)
    mockApi(operatorApi({ 'GET /learn/strengthen': { ...STRENGTHEN, items: [{ ...ITEM, labels: { ...ITEM.labels, task_id: task } }] } }))
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    expect(await screen.findByRole('link', { name: 'Re-qualify' })).toHaveAttribute('href', `/runs?repo=alpha&new=qualify&tasks=${task}&from=learn`)
    expect(screen.getByRole('link', { name: 'Re-score' })).toHaveAttribute('href', `/runs?repo=alpha&new=oracle&tasks=${task}&from=learn`)
    expect(screen.getByRole('link', { name: 'Re-run controls' })).toHaveAttribute('href', `/runs?repo=alpha&new=controls&tasks=${task}&from=learn`)
  })

  it('a viewer is offered no run hand-off from a strengthening row', async () => {
    mockApi({ ...operatorApi(), 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    await screen.findByText('Strengthen the divide tests')
    for (const name of ['Re-qualify', 'Re-score', 'Re-run controls']) expect(screen.queryByRole('link', { name })).toBeNull()
  })

  it('says which loop the reader is in, and each report is an anchor the screens that reveal a need link to (G-348)', async () => {
    mockApi(operatorApi())
    renderApp(<LearnPage />, { route: '/learn?repo=alpha#strengthen' })
    const loop = await screen.findByTestId('learn-loop')
    expect(loop).toHaveTextContent('You are in the learning loop')
    for (const step of ['read the reports', 'Oracle', 'strengthen the tests in your repository', 're-score and re-qualify', 'register and queue', 'decide the refusals']) expect(loop).toHaveTextContent(step)
    for (const id of ['prevention', 'refusals', 'strengthen', 'remeasure']) expect(document.getElementById(id)).not.toBeNull()
  })
  it('the strengthen report says what the test work cost a person, measured, with its n and apparatus (G-350)', async () => {
    mockApi(operatorApi())
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const cost = await screen.findByTestId('learn-strengthen-cost')
    expect(cost).toHaveTextContent('five author–adversary rounds and about 45 test rows')
    expect(cost).toHaveTextContent('measured: n = 1 item, 5 revisions, 10 wrong builds')
    expect(cost).toHaveTextContent('apparatus 2.2')
    expect(within(cost).getByRole('link', { name: 'What strengthening costs' })).toHaveAttribute('href', '/help/docs/LEARNING-LOOP#24-what-strengthening-costs-a-person')
  })
  it('the plan can be read against a named apparatus before a bump, and a what-if plan queues nothing (G-983)', async () => {
    const { calls } = mockApi(
      operatorApi({
        'GET /learn/remeasure': (url: string) =>
          url.includes('apparatus=9.9') ? json({ ...REMEASURE, current_apparatus: '9.9', rows_stale: 12, cells: [CELL] }) : json(REMEASURE),
      }),
    )
    renderApp(<LearnPage />, { route: '/learn?repo=alpha' })
    const card = await waitFor(() => {
      const c = document.getElementById('remeasure')
      if (!c || !within(c).queryByText('Nothing stale')) throw new Error('not yet')
      return c
    })
    await userEvent.type(within(card).getByLabelText(/^Plan against apparatus/), '9.9')
    await userEvent.click(within(card).getByRole('button', { name: 'Plan' }))
    expect(await within(card).findByText(CELL.label)).toBeInTheDocument()
    expect(within(card).getByTestId('learn-plan-whatif')).toHaveTextContent('planned against apparatus 9.9')
    // a what-if plan is a preview: its runs would grade under the running apparatus, so none is offered
    expect(within(card).queryByRole('button', { name: 'Queue runs' })).toBeNull()
    expect(calls.some((c) => c.path === '/learn/remeasure' && c.url.includes('apparatus=9.9'))).toBe(true)
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
    // back to the running version: the plan, and the Queue control, return
    await userEvent.click(within(card).getByRole('button', { name: 'Plan for the running version' }))
    expect(await within(card).findByText('Nothing stale')).toBeInTheDocument()
  })
})
