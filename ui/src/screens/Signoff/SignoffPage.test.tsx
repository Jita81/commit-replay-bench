/**
 * ui/src/screens/Signoff/SignoffPage.tsx — the bar is shown before the approver tries, a refusal is
 * a gate, a record carries its snapshot.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests for the sign-off page under `signoff-policy.v2`, against a
 *               mocked map, preview, POST and list.
 * What it does: Pins that a seeded deliver cell is refused on a controls escape with
 *               observed vs threshold shown before any attempt; that an unmeasured oracle is
 *               a non-overridable refusal (gate row, tile and clause); that a cell whose
 *               preview lists no refusal is signed with an attestation and listed with its
 *               snapshot; that a 409 `signoff_refused` renders as a REFUSED gate with the
 *               clauses and a 409 `false_q1_refused` as the floor; that other errors render
 *               as the envelope with the gate as the preview says; that a pre-policy
 *               record is listed without a fabricated snapshot next to a policy record;
 *               that the header says in two sentences what the screen is for and keeps the
 *               refusal clauses behind a Details; that a viewer gets the gate, the evidence
 *               and the attestations but never the form; that with no repository the
 *               exit is Connect, never the legacy repository list; and that every element
 *               a viewer or an approver meets carries a hint (no native `title` remains;
 *               the attestation statement is shown under its row), with the false-Q1 gate
 *               clause opening on hover with the registry copy.
 * How:          `mockApi` with capability, preview and sign-off fixtures; `userEvent` picks
 *               the cell and row, ticks the affirmation and submits; assertions on the
 *               `signoff-*` / `refusal-*` / `attest-*` test ids and the gate's `data-state`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Signoff/SignoffPage.tsx and ui/src/screens/Signoff/contract.ts
 *               (the code under test), ui/src/components/GateBanner.tsx (the states asserted),
 *               ui/src/test/utils.tsx, ui/src/help/hints.ts (the copy the hover test expects),
 *               ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Signoff/SignoffPage.test.tsx
 * Touch when:   a refusal clause is added — add a preview fixture that lists it and assert
 *               its gate row and clause.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { hintText } from '../../help/hints'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import type { CapabilityMapWithControls, ControlsVerdict } from '../Capability/contract'
import { SignoffPage } from './SignoffPage'
import type { SignoffPreview, SignoffRefusal, SignoffWithPolicy } from './contract'

const ROW = 'c'.repeat(64)
const ROW2 = 'd'.repeat(64)

const ESCAPED: ControlsVerdict = { measured: true, passed: true, complete: true, constructible: 12, total: 14, share: 0.857, escapes: 1, run_id: '0'.repeat(32), created: '2026-08-26T09:20:00+00:00', state: 'escaped' }
const PASSED: ControlsVerdict = { ...ESCAPED, escapes: 0, run_id: '5'.repeat(32), created: '2026-09-10T09:00:00+00:00', state: 'passed' }

const POLICY = {
  policy_version: 'signoff-policy.v2',
  relaxed: false,
  non_overridable: ['false_q1', 'oracle_unmeasured', 'attestation_missing'],
  bounds: { n_min: [1, 10000] as [number, number] },
  n_min: 10,
  require_route_deliver: true,
  require_controls_passed: true,
  max_controls_escapes: 0,
  min_constructible_share: 0.5,
  min_oracle_strength: 0.8,
  require_oracle_measured: true,
  require_attestation: true,
}
/** The seed's measured oracle on the cell: 3 of its 4 tasks scored, mean 0.58 (< 0.80). */
const ORACLE_WEAK = { strength: 0.5778, scored: 3, tasks: 4 }
const ORACLE_STRONG = { strength: 0.9, scored: 4, tasks: 4 }
const ORACLE_NONE = { strength: null, scored: 0, tasks: 4 }

const MAP: CapabilityMapWithControls = {
  repo: 'r',
  by: ['capability_class', 'size'],
  classes: ['bug.fix'],
  sizes: ['S'],
  languages: [],
  models: [],
  cells: [
    {
      capability_class: 'bug.fix',
      size: 'S',
      n: 40,
      clean: 38,
      point: 0.95,
      ci_low: 0.835,
      ci_high: 0.985,
      false_q1: 0,
      cost_usd_mean: 0.01,
      latency_s_mean: 30,
      oracle_strength_mean: null,
      route: 'human',
      reason: 'controls_escapes: 1 measurement control(s) graded clean on this repo',
      reason_code: 'controls_escapes',
      verification_tier: 'automated-pass',
      apparatus_versions: ['2.1'],
      n_builder_red: 2,
      n_budget: 0,
      n_protocol: 0,
      n_harness: 0,
      n_disqualified: 0,
      model_n: 40,
      model_point: 0.95,
      model_ci_low: 0.835,
      model_ci_high: 0.985,
      failure_split: { builder_red: 2, budget: 0, protocol: 0, harness: 0, disqualified: 0 },
    },
  ],
  summary: { trusted_autonomy_coverage: 0, total_cells: 1, measured_cells: 1, deliver_cells: 0, n_total: 40, false_q1_total: 0, apparatus_versions: ['2.1'] },
  policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1', min_controls_share: 0.5, max_controls_escapes: 0, controls_version: 'controls-gate.v1' },
  controls: ESCAPED,
}

const ESCAPE_REFUSALS: SignoffRefusal[] = [
  { code: 'controls_escapes', message: '1 measurement control(s) graded clean on this repo (controls run 00000000) > max_controls_escapes=0 — the oracle cannot tell an implementation from a cheat', threshold: 0, observed: 1, overridable: true },
  { code: 'oracle_weak', message: 'oracle strength 0.58 < min_oracle_strength=0.80 — green cannot license auto-delivery', threshold: 0.8, observed: 0.5778, overridable: true },
  { code: 'route_not_deliver:controls_escapes', message: "the routing rule says 'human' (controls_escapes): 1 measurement control(s) graded clean", threshold: 'deliver', observed: 'human', overridable: true },
  { code: 'attestation_missing', message: 'the approver must name one accepted (clean) row of this cell whose diff they have read, with a statement', threshold: 'reviewed_row_hash + statement', observed: '', overridable: false },
]
const ATTESTATION_MISSING = ESCAPE_REFUSALS[3]!
const ORACLE_UNMEASURED: SignoffRefusal = { code: 'oracle_unmeasured', message: "no task of cell 'bug.fix|S' has a mutation score — the oracle's strength is unknown, so a green here is not evidence; run an 'oracle' run on this repo before signing (cannot be relaxed)", threshold: 'measured', observed: null, overridable: false }

function preview(over: Partial<SignoffPreview> = {}): SignoffPreview {
  return {
    repo: 'r',
    cell: { process_step: '*', capability_class: 'bug.fix', size: 'S', language: '*', builder: '*', model: '*', provider: '*' },
    policy: POLICY,
    evidence: { measured: true, n: 40, clean: 38, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, oracle_strength: 0.5778, oracle: ORACLE_WEAK, apparatus_versions: ['2.1'], belt_sets: ['v4'], model_n: 40, model_point: 0.95, failure_split: { builder_red: 2, budget: 0, protocol: 0, harness: 0, disqualified: 0 } },
    route: { route: 'human', reason: 'controls_escapes: 1 measurement control(s) graded clean on this repo', reason_code: 'controls_escapes' },
    controls: ESCAPED,
    refusals: ESCAPE_REFUSALS,
    signable: false,
    would_record: {},
    accepted_rows: [
      { row_hash: ROW, row_id: 'r1', task_id: 'a'.repeat(40), subject: 'fix: task 4', created: '2026-08-30T09:03:00+00:00', run_id: 'c'.repeat(32), trial: 'r1', builder: 'editblock', model: 'gpt-oss-120b', evidence_pack_hash: 'e'.repeat(64) },
      { row_hash: ROW2, row_id: 'r2', task_id: 'b'.repeat(40), subject: 'fix: task 3', created: '2026-08-30T09:02:00+00:00', run_id: 'c'.repeat(32), trial: 'r2', builder: 'editblock', model: 'gpt-oss-120b', evidence_pack_hash: 'f'.repeat(64) },
    ],
    attestation: null,
    ...over,
  }
}

const SIGNED: SignoffWithPolicy = {
  id: 's1',
  repo: 'r',
  cell: { process_step: '*', capability_class: 'bug.fix', size: 'S', language: '*', builder: '*', model: '*', provider: '*' },
  note: 'reviewed',
  approver: 'u1',
  created: '2026-09-14T10:00:00+00:00',
  revoked: false,
  revoked_by: null,
  revoked_at: null,
  active: true,
  stale: false,
  apparatus_current: '2.1',
  current_false_q1: 0,
  prev_hash: '0'.repeat(64),
  row_hash: 'a'.repeat(64),
  schema: 'crb.signoff.v2',
  evidence: { n: 40, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, apparatus_versions: ['2.1'], oracle_strength: 0.9 },
  policy_version: 'signoff-policy.v2',
  policy_thresholds: POLICY,
  route: { route: 'deliver', reason: 'n=40 point=0.950 ci_low=0.835 false_q1=0', reason_code: 'deliver' },
  controls: { verdict: 'passed', run_id: '5'.repeat(32), k: 12, total: 14, escapes: 0, created: '2026-09-10T09:00:00+00:00' },
  attestation: { reviewed_task_id: 'a'.repeat(40), reviewed_row_hash: ROW, statement: 'I read the diff.', at: '2026-09-14T10:00:00+00:00', subject: 'fix: task 4' },
}

/** The preview handler dispatches on the named row so the flow re-fetches like the real API. */
function previewFor(unsigned: SignoffPreview, signed: SignoffPreview) {
  return (url: string) => {
    const q = new URL(url, 'http://x').searchParams
    return json(q.get('reviewed_row_hash') ? signed : unsigned)
  }
}

const gateRow = (gate: HTMLElement, label: string | RegExp) => within(gate).getAllByRole('listitem').find((li) => (typeof label === 'string' ? li.textContent?.includes(label) : label.test(li.textContent ?? '')))!

/** A preview whose only refusal is the attestation: clean gate, strong measured oracle, route deliver. */
function signablePreview(over: Partial<SignoffPreview> = {}): SignoffPreview {
  const base = preview()
  return preview({
    controls: PASSED,
    route: { route: 'deliver', reason: 'n=40 point=0.950 ci_low=0.835 false_q1=0', reason_code: 'deliver' },
    evidence: { ...base.evidence, oracle_strength: 0.9, oracle: ORACLE_STRONG },
    refusals: [ATTESTATION_MISSING],
    ...over,
  })
}

describe('SignoffPage (signoff-policy.v2)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says what the screen is for in two sentences, keeps the refusal clauses behind a Details, and takes the journey eyebrow', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /signoffs/preview': preview(),
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    await screen.findByTestId('signoff-gate')
    expect(screen.getByText('Journey · 3 of 4 · Decisions · sign-off')).toBeInTheDocument()
    expect(screen.getByText('Record that you reviewed this cell’s evidence and read one accepted change. The server refuses a sign-off that does not meet the published policy; a refusal is the gate working, not an error.')).toBeInTheDocument()
    const why = screen.getByText('Why a sign-off can be refused').closest('details')!
    expect(why).not.toHaveAttribute('open')
    expect(why).toHaveTextContent('a thin cell')
    expect(why).toHaveTextContent('no attestation that you read an accepted diff')
    // the clauses' terms carry their definitions
    expect(within(why).getByRole('button', { name: 'false-Q1' })).toBeInTheDocument()
    expect(within(why).getByRole('button', { name: /negative controls/ })).toBeInTheDocument()
  })

  it('a viewer reads the gate, the evidence and the attestations, and is never shown the approver form', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [SIGNED], total: 1, limit: 50, offset: 0 },
      'GET /signoffs/preview': preview(),
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r&cell=bug.fix%7CS' })
    const gate = await screen.findByTestId('signoff-gate')
    await waitFor(() => expect(gate).toHaveTextContent('Attest bug.fix × S'))
    expect(gate).toHaveTextContent('Requires the approver role (you are viewer).')
    await screen.findByTestId('signoff-evidence')
    expect(screen.getByText('Only an approver can sign. You are signed in as viewer: you can read the gate, the evidence and the attestations on this page, and nothing here changes because you read it.')).toBeInTheDocument()
    expect(screen.queryByText('Approver form')).toBeNull()
    expect(screen.queryByTestId('attest-row')).toBeNull()
    expect(screen.queryByTestId('attest-read')).toBeNull()
    expect(screen.queryByTestId('attest-statement')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Sign off' })).toBeNull()
    // the attestations table is theirs to read; Revoke is not theirs
    await waitFor(() => expect(screen.getByRole('table', { name: 'Sign-offs for r' })).toHaveTextContent('active'))
    expect(screen.queryByRole('button', { name: 'Revoke' })).toBeNull()
  })

  it('with no repository at all the exit is Connect, never the legacy repository list', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [], total: 0, limit: 50, offset: 0 },
    })
    renderApp(<SignoffPage />, { route: '/signoff' })
    await screen.findByText('Choose a repository')
    expect(screen.getByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/connect')
    expect(screen.queryByRole('link', { name: 'Go to repos' })).toBeNull()
  })

  it('with no ?repo= the most recently updated repository is chosen for you', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'old', updated: '2026-09-01T00:00:00Z' }, { name: 'r', updated: '2026-09-15T00:00:00Z' }], total: 2, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /signoffs/preview': preview(),
    })
    renderApp(<SignoffPage />, { route: '/signoff' })
    await waitFor(() => expect(screen.getByRole('table', { name: 'Sign-offs for r' })).toBeInTheDocument())
    expect(screen.queryByText('Choose a repository')).toBeNull()
  })

  it('shows the bar before the approver tries: the seeded deliver cell is refused on the controls escape, with observed vs threshold', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /signoffs/preview': preview(),
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()

    const gate = await screen.findByTestId('signoff-gate')
    expect(gate).toHaveAttribute('data-state', 'PENDING')
    const submit = await screen.findByRole('button', { name: 'Sign off' })
    expect(submit).toBeDisabled()

    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Cell/), 'bug.fix|S')

    // the evidence the approver must see: n / point / Wilson-low / false-Q1 / oracle / controls / route
    const evidence = await screen.findByTestId('signoff-evidence')
    expect(within(evidence).getByTestId('signoff-tile-point').textContent).toContain('95.0%')
    expect(within(evidence).getByTestId('signoff-tile-point').textContent).toContain('40')
    expect(within(evidence).getByTestId('signoff-tile-ci-low').textContent).toContain('83.5%')
    expect(within(evidence).getByTestId('signoff-tile-false-q1').textContent).toContain('0')
    expect(within(evidence).getByTestId('signoff-tile-oracle').textContent).toContain('0.58')
    expect(within(evidence).getByTestId('signoff-tile-oracle').textContent).toContain('3 of 4 task(s) scored')
    const controls = screen.getByTestId('signoff-controls')
    expect(within(controls).getByTestId('controls-escaped')).toBeInTheDocument()
    expect(controls.textContent).toContain('12 of 14 constructible')
    expect(controls.textContent).toContain('1 escape(s)')
    expect(controls.textContent).toContain('run 00000000')
    const route = screen.getByTestId('signoff-route')
    expect(route.textContent).toContain('controls_escapes')
    expect(within(route).getByRole('img', { name: /^Route: human/ })).toBeInTheDocument()
    expect(screen.getByTestId('signoff-split')).toBeInTheDocument()

    // the gate is CLOSED on exactly the failing clauses, and every refusal is listed
    expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'CLOSED')
    expect(gateRow(gate, 'Cell is measured').textContent).toMatch(/satisfied:/)
    expect(gateRow(gate, 'false-Q1 = 0').textContent).toMatch(/✓\s*satisfied:/)
    expect(gateRow(gate, 'n ≥ 10').textContent).toMatch(/✓\s*satisfied:/)
    expect(gateRow(gate, /Negative controls passed/).textContent).toMatch(/✗\s*not satisfied:/)
    expect(gateRow(gate, /Oracle strength measured and ≥ 0\.80/).textContent).toMatch(/✗\s*not satisfied:/)
    expect(gateRow(gate, /Oracle strength measured/).textContent).toContain('strength 0.58 · 3 of 4 task(s) scored')
    expect(gateRow(gate, 'Route = deliver').textContent).toMatch(/✗\s*not satisfied:/)
    expect(gateRow(gate, 'Accepted row read and affirmed').textContent).toMatch(/✗\s*not satisfied:/)
    const list = screen.getByTestId('signoff-refusals')
    const escape = within(list).getByTestId('refusal-controls_escapes')
    expect(escape.textContent).toContain('a measurement control escaped the oracle')
    expect(escape.textContent).toContain('observed 1')
    expect(escape.textContent).toContain('threshold 0')
    const weak = within(list).getByTestId('refusal-oracle_weak')
    expect(weak.textContent).toContain('oracle too weak to license auto-delivery')
    expect(weak.textContent).toContain('observed 0.58 · threshold 0.80')
    expect(weak.textContent).not.toContain('non-overridable')
    expect(within(list).getByTestId('refusal-route_not_deliver:controls_escapes').textContent).toContain('observed human')
    const missing = within(list).getByTestId('refusal-attestation_missing')
    expect(missing.textContent).toContain('non-overridable')
    // the button stays disabled even with a row picked and affirmed — the preview still refuses
    await user.selectOptions(screen.getByLabelText(/^Accepted row/), ROW)
    await user.click(screen.getByTestId('attest-read'))
    await user.type(screen.getByLabelText(/^Attestation statement/), 'Read it.')
    expect(screen.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'CLOSED')
  })

  it('shows an unmeasured oracle as a non-overridable refusal (signoff-policy.v2): the gate row, the tile and the clause', async () => {
    const unmeasured = signablePreview({ evidence: { ...preview().evidence, oracle_strength: null, oracle: ORACLE_NONE }, refusals: [ORACLE_UNMEASURED, ATTESTATION_MISSING] })
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': { ...MAP, controls: PASSED, cells: [{ ...MAP.cells[0]!, route: 'deliver', reason: 'ok', reason_code: 'deliver' }] },
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /signoffs/preview': unmeasured,
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Cell/), 'bug.fix|S')
    const gate = screen.getByTestId('signoff-gate')
    await waitFor(() => expect(screen.getByTestId('refusal-oracle_unmeasured')).toBeInTheDocument())
    expect(gate.textContent).toContain('policy signoff-policy.v2')
    expect(gate).toHaveAttribute('data-state', 'CLOSED')
    // the tile says "—" (never 0) and how many tasks carry a score
    const tile = screen.getByTestId('signoff-tile-oracle')
    expect(tile.textContent).toContain('—')
    expect(tile.textContent).toContain('0 of 4 task(s) scored')
    // the gate row is the one criterion that fails besides the attestation
    const row = gateRow(gate, /Oracle strength measured and ≥ 0\.80/)
    expect(row.textContent).toMatch(/✗\s*not satisfied:/)
    expect(row.textContent).toContain('unmeasured — no task of this cell has a mutation score')
    expect(row.textContent).toContain('non-overridable')
    expect(gateRow(gate, /Negative controls passed/).textContent).toMatch(/✓\s*satisfied:/)
    expect(gateRow(gate, 'Route = deliver').textContent).toMatch(/✓\s*satisfied:/)
    // the clause: observed null renders as "—", threshold "measured", and it cannot be relaxed
    const clause = within(screen.getByTestId('signoff-refusals')).getByTestId('refusal-oracle_unmeasured')
    expect(clause.textContent).toContain('oracle never measured on this cell')
    expect(clause.textContent).toContain('no policy can waive this')
    expect(clause.textContent).toContain('observed — · threshold measured')
    expect(clause.textContent).toContain('non-overridable')
    // naming and affirming a row does not open the gate: the server would still refuse
    await user.selectOptions(screen.getByLabelText(/^Accepted row/), ROW)
    await user.click(screen.getByTestId('attest-read'))
    await user.type(screen.getByLabelText(/^Attestation statement/), 'Read it.')
    expect(screen.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    expect(gate).toHaveAttribute('data-state', 'CLOSED')
  })

  it('signs with an attestation once the preview reports no refusal, and lists the record with its snapshot', async () => {
    document.cookie = 'crb_csrf=t; path=/'
    const unsigned = signablePreview()
    const signed = { ...unsigned, refusals: [], signable: true, attestation: SIGNED.attestation }
    let items: SignoffWithPolicy[] = []
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': { ...MAP, controls: PASSED, cells: [{ ...MAP.cells[0]!, route: 'deliver', reason: 'ok', reason_code: 'deliver' }] },
      'GET /signoffs': () => json({ items, total: items.length, limit: 50, offset: 0 }),
      'GET /signoffs/preview': previewFor(unsigned, signed),
      'POST /signoffs': () => {
        items = [SIGNED]
        return json(SIGNED, 201)
      },
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Cell/), 'bug.fix|S')
    const gate = screen.getByTestId('signoff-gate')
    await waitFor(() => expect(screen.getByTestId('refusal-attestation_missing')).toBeInTheDocument())
    expect(gate).toHaveAttribute('data-state', 'CLOSED')
    const submit = screen.getByRole('button', { name: 'Sign off' })
    expect(submit).toBeDisabled()

    // the picker offers the cell's accepted rows: subject · row hash · date
    const picker = screen.getByLabelText(/^Accepted row/)
    expect(within(picker).getByRole('option', { name: /fix: task 4 · cccccccccc/ })).toBeInTheDocument()
    expect(within(picker).getByRole('option', { name: /fix: task 3 · dddddddddd/ })).toBeInTheDocument()
    await user.selectOptions(picker, ROW)
    // the preview re-fetched with the named row → no refusal → but the affirmation is still required
    await waitFor(() => expect(screen.queryByTestId('signoff-refusals')).toBeNull())
    expect(submit).toBeDisabled()
    await user.click(screen.getByTestId('attest-read'))
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/^Attestation statement/), 'I read the diff.')
    await user.type(screen.getByLabelText(/^Note/), 'reviewed')
    expect(gate).toHaveAttribute('data-state', 'OPEN')
    expect(submit).toBeEnabled()

    await user.click(submit)
    await screen.findByTestId('signoff-recorded')
    expect(screen.getByTestId('signoff-recorded').textContent).toContain('signoff-policy.v2')
    expect(gateRow(gate, /Oracle strength measured and ≥ 0\.80/).textContent).toMatch(/✓\s*satisfied:/)
    const post = calls.find((c) => c.method === 'POST' && c.path === '/signoffs')!
    expect((post.init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('t')
    expect(JSON.parse(String(post.init?.body))).toEqual({
      repo: 'r',
      cell: { capability_class: 'bug.fix', size: 'S' },
      note: 'reviewed',
      attestation: { reviewed_row_hash: ROW, statement: 'I read the diff.' },
    })
    // the record shows the snapshot: evidence, policy · route · controls, the attestation
    const table = await screen.findByRole('table', { name: 'Sign-offs for r' })
    await waitFor(() => expect(within(table).getByTestId('signoff-row-evidence')).toBeInTheDocument())
    expect(within(table).getByTestId('signoff-row-evidence').textContent).toContain('n=40 · 95.0% · lower 83.5% · fQ1 0 · oracle 0.90')
    expect(within(table).getByTestId('signoff-row-policy').textContent).toContain('signoff-policy.v2 · deliver (deliver) · controls passed 12/14 esc 0')
    expect(within(table).getByTestId('signoff-row-attestation').textContent).toContain('cccccccccc · fix: task 4')
    expect(within(table).getByRole('img', { name: 'Active attestation' })).toBeInTheDocument()
  })

  it('revokes only after a confirmation with a reason, sends the reason as the note, and keeps the revoked row in the list', async () => {
    document.cookie = 'crb_csrf=t; path=/'
    let items: SignoffWithPolicy[] = [{ ...SIGNED, approver_name: 'ada' }]
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': { ...MAP, controls: PASSED },
      'GET /signoffs': () => json({ items, total: items.length, limit: 50, offset: 0 }),
      'GET /signoffs/preview': signablePreview(),
      [`POST /signoffs/${SIGNED.id}/revoke`]: () => {
        items = [{ ...SIGNED, approver_name: 'ada', revoked: true, active: false, revoked_by: 'u2', revoked_by_name: 'ada', revoked_at: '2026-09-17T17:00:00+00:00' }]
        return json(items[0])
      },
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()
    const table = await screen.findByRole('table', { name: 'Sign-offs for r' })
    // the listing asks for the history, and shows the approver by name, not id
    expect(calls.find((c) => c.path === '/signoffs')!.url).toContain('include_revoked=true')
    expect(within(table).getByText('ada')).toBeInTheDocument()
    await user.click(within(table).getByRole('button', { name: 'Revoke' }))
    // nothing was sent yet: the confirmation asks why
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    const dialog = screen.getByTestId('revoke-confirm')
    expect(dialog.textContent).toContain('Are you sure you want to revoke this sign-off?')
    const confirm = within(dialog).getByRole('button', { name: 'Revoke sign-off' })
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByLabelText(/Why are you revoking it/), 'evidence re-examined')
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    await waitFor(() => expect(screen.queryByTestId('revoke-confirm')).toBeNull())
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.path).toBe(`/signoffs/${SIGNED.id}/revoke`)
    expect(JSON.parse(String(post.init?.body))).toEqual({ note: 'evidence re-examined' })
    // the row stays on the record, marked revoked, and can no longer be revoked
    await waitFor(() => expect(within(table).getByRole('img', { name: /Revoked by ada at/ })).toBeInTheDocument())
    expect(within(table).queryByRole('button', { name: 'Revoke' })).toBeNull()
  })

  it('renders a 409 signoff_refused from the server as a gate REFUSED with the clauses, and a 409 false_q1_refused as the floor', async () => {
    const signable = signablePreview({ refusals: [], signable: true, attestation: SIGNED.attestation })
    const refusals: SignoffRefusal[] = [{ code: 'controls_escapes', message: '1 measurement control(s) graded clean on this repo > max_controls_escapes=0', threshold: 0, observed: 1, overridable: true }]
    let post = 0
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /signoffs/preview': signable,
      'POST /signoffs': () => {
        post += 1
        return post === 1
          ? envelope(409, 'signoff_refused', 'cell is thin: n=4 < n_min=10', { code: 'controls_escapes', threshold: 0, observed_value: 1, refusals })
          : envelope(409, 'false_q1_refused', 'cell has false_q1=1 > 0 — untrusted, cannot be signed off', { code: 'false_q1', false_q1: 1, refusals: [{ code: 'false_q1', message: 'false_q1=1', threshold: 0, observed: 1, overridable: false }] })
      },
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Cell/), 'bug.fix|S')
    await waitFor(() => expect(screen.getByTestId('signoff-evidence')).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Accepted row/), ROW)
    await user.click(screen.getByTestId('attest-read'))
    await user.type(screen.getByLabelText(/^Attestation statement/), 'Read it.')
    const submit = screen.getByRole('button', { name: 'Sign off' })
    await waitFor(() => expect(submit).toBeEnabled())

    await user.click(submit)
    await waitFor(() => expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'REFUSED'))
    let gate = screen.getByTestId('signoff-gate')
    expect(gate.textContent).toContain('Sign-off refused: controls_escapes')
    expect(gate.textContent).toContain('signoff_refused')
    expect(gate.textContent).toContain('Nothing was recorded')
    expect(within(gate).getByTestId('refusal-controls_escapes').textContent).toContain('observed 1 · threshold 0')
    expect(screen.queryByTestId('error-state')).toBeNull()

    await user.click(submit)
    await waitFor(() => expect(screen.getByTestId('signoff-gate').textContent).toContain('Sign-off refused: false-Q1 invariant'))
    gate = screen.getByTestId('signoff-gate')
    expect(gate.textContent).toContain('false_q1_refused')
    expect(gate.textContent).toContain('verify chain')
    expect(within(gate).getByTestId('refusal-false_q1').textContent).toContain('non-overridable')
  })

  it('renders other errors as the envelope and keeps the gate as the preview says', async () => {
    const signable = signablePreview({ refusals: [], signable: true, attestation: SIGNED.attestation })
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /signoffs/preview': signable,
      'POST /signoffs': () => envelope(403, 'forbidden', 'approver role required'),
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Cell/), 'bug.fix|S')
    await waitFor(() => expect(screen.getByTestId('signoff-evidence')).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/^Accepted row/), ROW)
    await user.click(screen.getByTestId('attest-read'))
    await user.type(screen.getByLabelText(/^Attestation statement/), 'x')
    const submit = screen.getByRole('button', { name: 'Sign off' })
    await waitFor(() => expect(submit).toBeEnabled())
    await user.click(submit)
    const err = await screen.findByTestId('error-state')
    expect(err.textContent).toContain('approver role required')
    expect(err.textContent).toContain('HTTP 403')
    expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'OPEN')
  })

  it('lists a pre-policy record honestly (no snapshot) next to a policy record', async () => {
    const legacy: SignoffWithPolicy = { ...SIGNED, id: 's0', schema: 'crb.signoff.v1', policy_version: '', policy_thresholds: {}, route: { route: '', reason: '', reason_code: '' }, controls: { verdict: '', run_id: '', k: 0, total: 0, escapes: 0, created: '' }, attestation: null, created: '2026-09-01T00:00:00+00:00', note: 'old' }
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [SIGNED, legacy], total: 2, limit: 50, offset: 0 },
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const table = await screen.findByRole('table', { name: 'Sign-offs for r' })
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(3))
    expect(table.textContent).toContain('pre-policy record')
    expect(within(table).getAllByTestId('signoff-row-policy')).toHaveLength(1)
    expect(within(table).getAllByTestId('signoff-row-attestation')).toHaveLength(1)
  })

  it('every gate clause, refusal, tile, block, field, column and status pill carries a hint for a viewer and an approver; the false-Q1 clause opens on hover; the statement is shown, not a title', async () => {
    const routes = {
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [SIGNED], total: 1, limit: 50, offset: 0 },
      'GET /signoffs/preview': preview(),
    }
    mockApi({ ...routes, 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    const first = renderApp(<SignoffPage />, { route: '/signoff?repo=r&cell=bug.fix%7CS' })
    await screen.findByTestId('signoff-evidence')
    await waitFor(() => expect(screen.getByRole('table', { name: 'Sign-offs for r' })).toHaveTextContent('active'))
    expect(unhinted(first.container)).toEqual([])
    for (const id of ['details.signoff.why_refused', 'gate.signoff.banner', 'gate.signoff.measured', 'gate.signoff.false_q1', 'gate.signoff.thin_cell', 'gate.signoff.controls', 'gate.signoff.oracle', 'gate.signoff.route', 'gate.signoff.attestation', 'tile.signoff.refusal', 'pill.signoff.non_overridable', 'stat.signoff.point', 'stat.signoff.ci_low', 'stat.signoff.false_q1', 'stat.signoff.oracle', 'tile.signoff.controls', 'tile.signoff.route', 'tile.signoff.failure_split', 'field.signoff.cell_read', 'col.signoff.cell', 'col.signoff.status', 'pill.signoff.status', 'col.signoff.attestation', 'field.shared.repo_picker']) {
      expect(first.container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    // the statement is the governance record: visible under the row, never a hover-only title
    expect(screen.getByTestId('signoff-row-attestation')).toHaveTextContent('I read the diff.')
    expect(first.container.querySelectorAll('[title]').length).toBe(0)
    const clause = first.container.querySelector('[data-hint="gate.signoff.false_q1"]')!
    await userEvent.hover(clause)
    const tip = document.getElementById(clause.getAttribute('aria-describedby')!)!
    await waitFor(() => expect(tip).toHaveAttribute('data-open', 'true'))
    expect(tip).toHaveTextContent(hintText('gate.signoff.false_q1'))
    first.unmount()
    vi.unstubAllGlobals()

    mockApi({ ...routes, 'GET /auth/me': PRINCIPAL })
    const { container } = renderApp(<SignoffPage />, { route: '/signoff?repo=r&cell=bug.fix%7CS' })
    await screen.findByTestId('signoff-evidence')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/^Accepted row/), ROW)
    await waitFor(() => expect(screen.getByTestId('read-the-diff')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(screen.getByTestId('revoke-confirm')).toBeInTheDocument())
    expect(unhinted(container)).toEqual([])
    for (const id of ['button.signoff.sign', 'banner.signoff.not_meaning', 'field.signoff.cell', 'tile.signoff.cell_summary', 'field.signoff.accepted_row', 'field.signoff.read_affirmation', 'tile.signoff.read_diff', 'button.signoff.task', 'button.signoff.run', 'field.signoff.statement', 'field.signoff.note', 'button.signoff.revoke', 'field.signoff.revoke_reason', 'button.signoff.revoke_confirm']) {
      expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    // the affirmation's label is the trigger; the checkbox keeps the tab stop and lists the bubble in its description
    const box = screen.getByTestId('attest-read')
    expect(box.closest('[data-hint]')).toHaveAttribute('data-hint', 'field.signoff.read_affirmation')
  })
})
