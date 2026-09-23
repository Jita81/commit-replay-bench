/**
 * ui/src/screens/Factory/FactoryPage.tsx — the shipped contract: a backlog, a bare task list,
 * the 404 that means "no backlog registered", and the run that a developer starts from here.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the factory page against mocked `GET /factory/{repo}/backlog`,
 *               `/tasks`, `/health`, `/capability-map` and `/runs`.
 * What it does: Pins that a registered backlog renders its hash, frozen pill and items; that
 *               `/tasks` is consumed as the bare list the server serves (not a `Page`) with
 *               status, route hint, DoR gaps, RED proof, build status and review verdict;
 *               that a 404 `not_found` is the "no backlog registered" instruction, never
 *               an error state or fabricated rows (the old screen matched a phase-P6 501
 *               that the shipped server never answers — CodeRabbit on PR #6), and that its
 *               sentence is role-aware (a viewer reads "An operator freezes one", no
 *               Freeze button); that "Run the
 *               factory" posts the builder `builderChoice` picks (J-FAC-1 — the 422 a run
 *               without one met), names the estimate and never a cap (F5b), says what it
 *               will spend and where it delivers first, that reached without `?repo=` the
 *               latest repository is chosen (as the Baseline) and a viewer is offered no
 *               action on an empty deployment
 *               (J-FAC-2/3), that a refusal's reason reaches the step and the row (J-FAC-4,
 *               J-FAC-15), that the drafted successor takes the item it supersedes out of the
 *               form AND out of the other items' dependencies (G-904 — a stale dependency is
 *               refused 422 on freeze), that a built item opens its evidence (F15), and that an active
 *               factory run is a banner that polls the chain (J-FAC-5 / J-TEL-9), and that
 *               at phone width an item is one line with the six cards behind a Details and
 *               the cell-route pill short (J-FAC-14).
 * How:          `mockApi` + `renderApp` at `/factory?repo=…`; a stubbed `matchMedia` for the
 *               phone-width case (jsdom has none, so the page otherwise renders wide).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Factory/FactoryPage.tsx (under test), ui/src/api/types.ts
 *               (`FactoryBacklog`, `FactoryTask`), src/crb/server/routes/factory.py (the
 *               shapes mirrored here), ui/src/lib/builder.ts (`builderChoice`), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Factory/FactoryPage.test.tsx
 * Touch when:   a factory action moves into the UI; a `FactoryTaskOut` field is added.
 */
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FactoryBacklog, FactoryEvolutionPrefill, FactoryTask } from '../../api/types'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { FactoryPage, deliverableCount, estimateFromMap, nextId, refusalSentence, stepsFor, withEvolution } from './FactoryPage'

const NO_ROUTE = { route: '', reason_code: '', reason: '', n: 0, point: 0, ci_low: 0, ci_high: 0, apparatus_versions: [], deliverable: false }
const DELIVER = { route: 'deliver', reason_code: 'deliver', reason: 'ok', n: 40, point: 0.95, ci_low: 0.835, ci_high: 0.985, apparatus_versions: ['2.2'], deliverable: true }
const CALIBRATE = { route: 'calibrate', reason_code: 'ci_low_below_bar', reason: 'the lower bound sits under the bar', n: 24, point: 0.96, ci_low: 0.8, ci_high: 0.99, apparatus_versions: ['2.2'], deliverable: false }
const NOT_LINKED = { can_deliver: false, reason_code: 'not_linked' as const, reason: 'Delivery is not possible for this repository: it is connected by URL, not through the GitHub App. Connect it through the GitHub App with Contents: write and Pull requests: write, then Sync installations in Settings.', full_name: '', default_branch: '', installation_id: null, account_login: '' }
const LINKED = { can_deliver: true, reason_code: 'ok' as const, reason: '', full_name: 'acme/cobra', default_branch: 'main', installation_id: 77, account_login: 'acme' }
const UNTOUCHED = { outcome_reason: '', refusal: null, error: '', task_id: '', run_id: '', pack_hash: '', row_hash: '' }

/** The superseding item the API drafts for the stopped `I-1` (G-904), as `_prefill` serves it. */
const PREFILL: FactoryEvolutionPrefill = {
  id: 'I-1-v2',
  title: 'Multiply',
  kind: 'code',
  description: 'calc needs multiply',
  capability_class: 'bug.fix',
  size_estimate: 'XS',
  structural_facts: ['reproduction: x'],
  acceptance_criteria: ['multiply(3, 4) == 12'],
  depends_on: [],
  level: 'L1',
  supersedes: 'I-1',
}

const BACKLOG: FactoryBacklog = {
  repo: 'alpha',
  hash: 'a'.repeat(64),
  frozen_at: '2026-09-15T10:00:00+00:00',
  delivery: NOT_LINKED,
  items: [
    { id: 'I-1', title: 'Multiply', kind: 'code', capability_class: 'bug.fix', size: 'XS', level: 'L1', depends_on: [], structural_facts: ['reproduction: x'], has_authored_test: true, description: 'calc needs multiply' },
    { id: 'I-2', title: 'Divide', kind: 'code', capability_class: 'feature.add', size: 'S', level: 'L1', depends_on: ['I-1'], structural_facts: [], has_authored_test: false, description: '' },
  ],
}

const TASKS: FactoryTask[] = [
  { id: 'I-1', title: 'Multiply', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'accepted', dor_gaps: [], route_hint: 'build', red_proof: true, build_status: 'clean', pr_url: null, review_verdict: 'accept', last_event: 'item.outcome', cell_route: DELIVER, ...UNTOUCHED, task_id: 'c'.repeat(40), run_id: 'r'.repeat(32), pack_hash: 'p'.repeat(64), row_hash: 'h'.repeat(64) },
  { id: 'I-2', title: 'Divide', capability_class: 'feature.add', size: 'S', kind: 'code', status: 'blocked', dor_gaps: ['method_path', 'response_shape'], route_hint: 'human', red_proof: null, build_status: 'not_started', pr_url: null, review_verdict: null, last_event: 'readiness.blocked', cell_route: NO_ROUTE, ...UNTOUCHED },
]

const HEALTH_CLI = { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: 'configured: claude_code_cli', data: { anthropic: false, claude_code_cli: true } }] }
const HEALTH_NONE = { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: '', data: { executor: 'local' } }, { name: 'builders', status: 'degraded', detail: 'configured: none', data: { anthropic: false, claude_code_cli: false } }] }
const MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [{ capability_class: 'bug.fix', size: 'XS', n: 40, clean: 38, point: 0.95, ci_low: 0.835, ci_high: 0.985, false_q1: 0, route: 'deliver', reason: '', cost_usd_mean: 0.34, latency_s_mean: 200, verification_tier: 'automated-pass', apparatus_versions: ['2.2'] }], summary: { trusted_autonomy_coverage: 1, total_cells: 1, measured_cells: 1, deliver_cells: 1, n_total: 40, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }
const NO_RUNS = { items: [], total: 0, limit: 10, offset: 0 }
const CATALOGUE = {
  classes: [
    { capability_class: 'backend.route.add', slots: [{ name: 'method_path', question: 'What HTTP method and path does the new route answer?', kind: 'structural' }, { name: 'example_payload', question: 'A representative request and its exact expected response.', kind: 'value' }] },
    { capability_class: 'feature.add', slots: [{ name: 'method_path', question: 'Which HTTP method and path does the change add?', kind: 'structural' }, { name: 'response_shape', question: 'What shape does the response have?', kind: 'structural' }] },
    { capability_class: 'bug.fix', slots: [{ name: 'reproduction', question: 'How is the bug reproduced?', kind: 'structural' }] },
  ],
  sizes: ['XS', 'S', 'M', 'L', 'XL'],
  kinds: ['code', 'infra', 'operator'],
  levels: ['L1', 'L2', 'L3'],
}

const task = (over: Partial<FactoryTask>): FactoryTask => ({ id: 'T', title: 'x', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'pending', dor_gaps: [], route_hint: '', red_proof: null, build_status: 'not_built', pr_url: null, review_verdict: null, last_event: '', cell_route: NO_ROUTE, ...UNTOUCHED, ...over })

const base = (over: Record<string, unknown> = {}) => ({
  'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
  'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
  'GET /factory/alpha/backlog': BACKLOG,
  'GET /factory/alpha/tasks': TASKS,
  'GET /factory/catalogue': CATALOGUE,
  'GET /health': HEALTH_CLI,
  'GET /capability-map': MAP,
  'GET /runs': NO_RUNS,
  ...over,
})

describe('stepsFor — an item the factory has not touched', () => {
  it('reads as not assessed / not run / not started, never as done or failed', () => {
    // exactly what the API folds for a frozen-but-unrun item (factory_state.task_views)
    const steps = stepsFor(task({ id: 'T-1' }))
    expect(steps.map((x) => [x.id, x.status])).toEqual([
      ['readiness', 'current'],
      ['red', 'todo'],
      ['build', 'todo'],
      ['delivery', 'todo'],
      ['review', 'todo'],
      ['outcome', 'todo'],
    ])
    expect(steps[0]!.detail).toMatch(/not assessed/)
    expect(steps[2]!.detail).toBe('not started')
  })

  it('a value gap is never a gap to sign: readiness names it as routing test-first, beside the structural ones', () => {
    // the server folds structural and value slots apart (factory_state.task_views);
    // the page must not count or offer a value slot as something an approver signs
    const blocked = stepsFor(task({ status: 'not_ready', route_hint: 'human', dor_gaps: ['method_path'], value_gaps: ['example_payload'] }))[0]!
    expect(blocked.status).toBe('current')
    expect(blocked.detail).toBe('1 structural gap unsigned: method_path · value gap example_payload routes test-first, never signed')
    const routed = stepsFor(task({ status: 'pending', route_hint: 'test_first_authoring', value_gaps: ['example_payload'], last_event: 'route.decided' }))[0]!
    expect(routed.status).toBe('done')
    expect(routed.detail).toBe('route test_first_authoring · value gap example_payload routes test-first, never signed')
  })

  it('a delivery a rework updated says so, rather than reading as a first opening', () => {
    // `delivery.updated` is the chain's event for a rework re-pointing the SAME pull request (DL-045)
    const updated = task({ id: 'T-3', route_hint: 'build', red_proof: true, build_status: 'clean', pr_url: 'https://github.invalid/acme/calc/pull/7', review_verdict: 'accept_with_edit', last_event: 'delivery.updated', cell_route: DELIVER })
    const delivery = stepsFor(updated)[3]!
    expect(delivery.status).toBe('done')
    expect(delivery.detail).toBe('pull request updated by a rework')
    expect(stepsFor({ ...updated, last_event: 'delivery.opened' })[3]!.detail).toBe('branch + pull request opened')
  })

  it('an item stopped for a stronger oracle reads as a sentence with the way forward (DL-045 rule 3)', () => {
    // the loop refused to rebuild against an unchanged oracle: one clean build, one PR, one
    // `accept_with_edit` verdict with a `weak_oracle` finding, routed human — the outcome
    // step must say what happened and what to do, not spell the status
    const reason = 'the reviewer found the oracle weak (statement deleted) and this deployment has no test author: strengthen the test and register a superseding item'
    const stopped = task({ id: 'T-4', status: 'oracle_needs_strengthening', outcome_reason: reason, route_hint: 'human', red_proof: true, build_status: 'clean', pr_url: 'https://github.invalid/acme/calc/pull/7', review_verdict: 'accept_with_edit', last_event: 'item.outcome', cell_route: DELIVER })
    const steps = stepsFor(stopped)
    expect(steps.map((x) => [x.id, x.status])).toEqual([
      ['readiness', 'done'],
      ['red', 'done'],
      ['build', 'done'],
      ['delivery', 'done'],
      ['review', 'current'],
      ['outcome', 'failed'],
    ])
    const outcome = steps[5]!
    expect(outcome.detail).toMatch(/^the reviewer found the oracle weak and no stronger test could be had/)
    expect(outcome.detail).toContain('did not rebuild against the same one')
    expect(outcome.detail).toContain('strengthen the test and register a superseding item')
    // the chain's reason ends with the same way forward the sentence already gives — the
    // parentheses carry only the finding and why no stronger test could be had, once
    expect(outcome.detail).toContain('(the reviewer found the oracle weak (statement deleted) and this deployment has no test author)')
    expect(outcome.detail.split('strengthen the test and register a superseding item')).toHaveLength(2)
    expect(outcome.detail).not.toContain('oracle_needs_strengthening')
    // a reason without that suffix (a reviewer that words it differently) is quoted whole
    expect(stepsFor({ ...stopped, outcome_reason: 'the oracle is weak' })[5]!.detail).toContain('(the oracle is weak)')
    // without a reason on the view the sentence still stands on its own
    expect(stepsFor({ ...stopped, outcome_reason: '' })[5]!.detail).not.toContain('(')
    // the readiness step keeps the pre-build reading: the item was BUILT (a PR is open), and
    // `route_hint` is `human` only because the stop routed it there after the review
    expect(steps[0]!.detail).not.toBe('route human')
    expect(steps[0]!.detail).toContain('after the review')
    expect(steps[0]!.detail).toContain('human')
    // the server folds that stop's `route.decided` as a REVIEW-step refusal (J-FAC-4): the
    // readiness step must not read it as "Routed to a person", the review step names it, and
    // the item's sentence gives the finding and the way forward
    const served = { ...stopped, refusal: { step: 'review' as const, reason, reason_code: '', measured_route: '' }, error: reason }
    const servedSteps = stepsFor(served)
    expect(servedSteps.map((x) => [x.id, x.status])).toEqual(steps.map((x) => [x.id, x.status]))
    expect(servedSteps[0]!.detail).toContain('after the review')
    expect(servedSteps[4]!.detail).toBe('accept with edit — the reviewer asked for a stronger test')
    expect(refusalSentence(served)).toBe('The review found the test too weak to rebuild against: the reviewer found the oracle weak (statement deleted) and this deployment has no test author. To bring it back into the factory, strengthen the test and register an evolution that supersedes this item (the frozen hash stays; the old chain is kept); or open the change by hand and mark the item done in the next backlog.')
  })

  it('a build that ran and was not clean is the failure, spelled out', () => {
    const build = stepsFor(task({ status: 'not_clean', route_hint: 'build', red_proof: true, build_status: 'not_clean', last_event: 'build', cell_route: DELIVER }))[2]!
    expect(build.status).toBe('failed')
    expect(build.detail).toBe('not clean')
  })
})

describe('stepsFor — every refusal carries its reason (J-FAC-4)', () => {
  it('the route gate withholding delivery names the measured route and the reason code', () => {
    const t = task({ status: 'accepted', route_hint: 'build', red_proof: true, build_status: 'clean', review_verdict: 'accept', last_event: 'item.outcome', cell_route: CALIBRATE, refusal: { step: 'delivery', reason: 'route gate: the cell routes calibrate (ci_low_below_bar)', reason_code: 'ci_low_below_bar', measured_route: 'calibrate' } })
    const delivery = stepsFor(t)[3]!
    expect(delivery.status).toBe('skipped')
    expect(delivery.detail).toBe('Delivery withheld — the route gate: bug.fix × XS routes calibrate (ci_low_below_bar: the lower bound sits under the bar). Built, graded and reviewed; no pull request opened.')
  })

  it('delivery that was off for the run says so; a refused push is a failure with the reason', () => {
    const off = task({ status: 'accepted', route_hint: 'build', red_proof: true, build_status: 'clean', review_verdict: 'accept', cell_route: DELIVER, refusal: { step: 'delivery', reason: 'delivery is opt-in and OFF — built and graded locally only', reason_code: '', measured_route: '' } })
    expect(stepsFor(off)[3]).toMatchObject({ status: 'skipped', detail: 'Delivery withheld — delivery was off for this run. Built and graded locally only.' })
    const pushed = task({ status: 'delivery_failed', route_hint: 'build', red_proof: true, build_status: 'clean', cell_route: DELIVER, error: 'DeliveryError: push refused (403)', refusal: { step: 'delivery', reason: 'push refused (403)', reason_code: '', measured_route: '' } })
    const steps = stepsFor(pushed)
    expect(steps[3]).toMatchObject({ status: 'failed', detail: 'Delivery failed — the push was refused: push refused (403).' })
    expect(steps[5]).toMatchObject({ status: 'failed', detail: 'delivery failed — DeliveryError: push refused (403)' })
  })

  it('a refused RED proof and a readiness refusal carry the chain’s reason; a dependency block names the item it waits on', () => {
    const red = task({ status: 'not_red', route_hint: 'build', red_proof: false, refusal: { step: 'red', reason: 'the authored test passed at the parent', reason_code: '', measured_route: '' } })
    expect(stepsFor(red)[1]).toMatchObject({ status: 'failed', detail: 'RED proof refused — the authored test passed at the parent, so it proves nothing: the authored test passed at the parent.' })
    const human = task({ status: 'routed_human', route_hint: 'human', refusal: { step: 'readiness', reason: 'a value gap (expected response shape) is not signed and routes test-first', reason_code: '', measured_route: '' } })
    expect(stepsFor(human)[0]).toMatchObject({ status: 'failed', detail: 'Routed to a person — a value gap (expected response shape) is not signed and routes test-first.' })
    expect(refusalSentence(human)).toBe('This item goes to a person: a value gap (expected response shape) is not signed and routes test-first. To bring it back into the factory, add the fact and register an evolution that supersedes this item (the frozen hash stays; the old chain is kept); or open the change by hand and mark the item done in the next backlog.')
    const blocked = task({ status: 'blocked_on_dependency', refusal: { step: 'dependency', reason: 'waiting on I-1', reason_code: '', measured_route: '' } })
    expect(refusalSentence(blocked)).toBe('Waiting on I-1, which has not been accepted yet.')
    expect(refusalSentence(task({}))).toBe('')
  })
})

describe('estimateFromMap — the repository’s measured mean per attempt (J-FAC-2)', () => {
  it('is the row-weighted mean over measured cells with its n and apparatus; null when nothing is measured', () => {
    expect(estimateFromMap(MAP.cells as never)).toEqual({ mean: 0.34, n: 40, apparatus: '2.2' })
    expect(estimateFromMap([])).toBeNull()
    expect(estimateFromMap([{ ...MAP.cells[0]!, route: 'NOT_YET_MEASURED', n: 0 }] as never)).toBeNull()
  })
})

describe('FactoryPage — the shipped contract', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the frozen backlog and the bare task list', async () => {
    mockApi(base({ 'GET /auth/me': PRINCIPAL }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    await waitFor(() => expect(screen.getByTestId('factory-backlog-hash')).toHaveTextContent(`hash ${'a'.repeat(64)}`))
    expect(screen.getByText('frozen')).toBeInTheDocument()
    expect(screen.getByText('2 items')).toBeInTheDocument()
    expect(screen.getAllByText('Multiply').length).toBeGreaterThan(0)
    // each item is the six-step process: I-1 done through review, I-2 waiting at readiness
    expect(screen.getByTestId('factory-item-I-1')).toHaveTextContent('Accepted')
    expect(screen.getByTestId('factory-item-I-2')).toHaveTextContent('Waiting on a signature')
    expect(screen.getByTestId('step-I-1-review')).toHaveTextContent('done')
    expect(screen.getByTestId('step-I-1-outcome')).toHaveTextContent('accepted')
    expect(screen.getByTestId('step-I-2-readiness')).toHaveTextContent('2 structural gaps unsigned: method_path, response_shape')
    expect(screen.getByTestId('step-I-2-red')).toHaveTextContent('not yet')
    // the approver can sign a gap right there; the operator's run controls are present
    expect(screen.getByRole('form', { name: 'Sign a structural gap for I-2' })).toBeInTheDocument()
    expect(screen.getByTestId('factory-run-controls')).toBeInTheDocument()
    // F28 / J-FAC-14 — the pill is short; the n · point [interval] · apparatus wrap after it
    expect(screen.getByTestId('cell-route-I-1')).toHaveTextContent('routes deliver')
    expect(screen.getByTestId('cell-route-I-1-prov')).toHaveTextContent('n = 40 · 95 % [84 %, 99 %] · apparatus 2.2')
    expect(screen.getByTestId('cell-route-I-2')).toHaveTextContent('not measured · withheld')
    expect(screen.getByTestId('factory-deliverable-count')).toHaveTextContent('1 of 2 items sit in a cell that routes deliver today')
  })

  it('a stopped item shows what to change and the replacement item already drafted (G-904)', async () => {
    const reason = 'the reviewer found the oracle weak (the test asserts only that the call returns) and this deployment has no test author: strengthen the test and register a superseding item'
    const stopped: FactoryTask = {
      ...TASKS[0]!,
      status: 'oracle_needs_strengthening',
      outcome_reason: reason,
      error: reason,
      refusal: { step: 'review', reason, reason_code: '', measured_route: '' },
      way_forward: {
        action: 'register_evolution',
        route: '/factory/alpha/backlog/evolutions',
        supersedes: 'I-1',
        what_to_change: 'Strengthen the test so it fails for the reason the review gave, then register this item with the stronger test attached.',
        needs_authored_test: true,
        prefill: { ...PREFILL, description: `${PREFILL.description}\n\nWhy the last attempt stopped: ${reason}` },
      },
    }
    mockApi(base({ 'GET /factory/alpha/tasks': [stopped, TASKS[1]!] }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const panel = await screen.findByTestId('prefill-I-1')
    // one sentence saying what must be different, and that this stop needs a test with it
    expect(panel).toHaveTextContent('Strengthen the test so it fails for the reason the review gave')
    expect(panel).toHaveTextContent('Attach the failing test with the item.')
    // the draft itself: a new id superseding the stopped one, the item's own words, and the
    // reason it stopped — so nothing is retyped and the reader sees what was too weak
    expect(panel).toHaveTextContent('I-1-v2 supersedes I-1')
    expect(panel).toHaveTextContent('the test asserts only that the call returns')
    expect(panel).toHaveTextContent('reproduction: x')
    // an item that has not stopped offers no draft
    expect(screen.queryByTestId('prefill-I-2')).not.toBeInTheDocument()

    // and the button beside the draft USES the draft: the drafted item replaces the one it
    // supersedes in the form, so nothing that was already worked out is retyped
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.click(within(await screen.findByTestId('factory-item-I-1')).getByRole('button', { name: 'Freeze a revised backlog…' }))
    const form = await screen.findByTestId('backlog-form')
    expect(within(form).getAllByLabelText(/^Id/).map((el) => (el as HTMLInputElement).value)).toEqual(['I-1-v2', 'I-2'])
    expect((within(form).getByLabelText(/How is the bug reproduced\?/) as HTMLInputElement).value).toBe('x')
    expect(within(form).getAllByLabelText(/^Title/).map((el) => (el as HTMLInputElement).value)).toEqual(['Multiply', 'Divide'])
    // I-2 depended on I-1: the successor takes the predecessor's place in the GRAPH too, or
    // the freeze is refused 422 for a dependency on an id the revised backlog no longer holds
    expect((within(form).getAllByLabelText(/^Depends on/)[1] as HTMLInputElement).value).toBe('I-1-v2')
  })

  it('a revision that keeps the item’s own id leaves every dependency alone (G-904)', async () => {
    // the same-id case is NOT a replacement: nothing moves in the graph, so I-2 still reads I-1
    const same = withEvolution(BACKLOG, { ...PREFILL, id: 'I-1', supersedes: '' })
    expect(same.items.map((i) => i.id)).toEqual(['I-1', 'I-2'])
    expect(same.items[1]!.depends_on).toEqual(['I-1'])
    // and an item the backlog does not hold is appended, with the rest untouched
    const added = withEvolution(BACKLOG, { ...PREFILL, id: 'I-9', supersedes: 'I-nope' })
    expect(added.items.map((i) => i.id)).toEqual(['I-1', 'I-2', 'I-9'])
    expect(added.items[1]!.depends_on).toEqual(['I-1'])
  })

  it('the factory screen is the way in to the work arriving from the board (ADR-0017)', async () => {
    // there was no link anywhere in the app: /factory/intake could only be reached by typing
    // its URL, and the guides handed the reader a raw path because there was nothing to click
    mockApi(base())
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const link = await screen.findByRole('link', { name: 'Work arriving from your board' })
    expect(link).toHaveAttribute('href', '/factory/intake?repo=alpha')
  })

  it('Run the factory posts the builder builderChoice picks, and says the spend first (J-FAC-1/2)', async () => {
    const { calls } = mockApi(base({ 'POST /runs': () => json({ id: 'f'.repeat(32), repo: 'alpha', kind: 'factory', status: 'queued' }, 201) }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const box = await screen.findByTestId('before-you-start')
    await waitFor(() => expect(box).toHaveTextContent('Claude Code · claude-sonnet-5 · the operator’s own CLI login'))
    // the estimate rests on the map's measured mean, with its n and apparatus, and names the band
    await waitFor(() => expect(box).toHaveTextContent("this repository's measured mean over n = 40 attempts at apparatus 2.2"))
    expect(box).toHaveTextContent('$0.27 to $0.41 for 1 item at about $0.34 each')
    expect(box).toHaveTextContent('1 of 2 will be worked (1 waits on a signed gap); 1 sits in a cell that routes deliver')
    expect(box).toHaveTextContent('no spend cap yet')
    expect(box).toHaveTextContent('You can cancel the run at any point. Items already built are still charged.')
    const { default: userEvent } = await import('@testing-library/user-event')
    // the button names the estimate — never a cap the request does not carry (F5b)
    await userEvent.click(screen.getByRole('button', { name: 'Run the factory — estimated $0.27 to $0.41' }))
    expect(screen.queryByRole('button', { name: /spend up to/ })).not.toBeInTheDocument()
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))).toEqual({
      repo: 'alpha',
      kind: 'factory',
      deliver: false,
      builder: 'claude_code',
      model: 'claude-sonnet-5',
      builder_config: { auth: 'cli' },
    })
    expect(await screen.findByRole('link', { name: /run ffffffff/ })).toHaveAttribute('href', `/runs/${'f'.repeat(32)}`)
  })

  it('with no ?repo= the most recently updated repository is chosen (as the Baseline); an empty deployment offers Connect to an operator only', async () => {
    mockApi(base({ 'GET /repos': { items: [{ name: 'alpha', updated: '2026-09-10T00:00:00Z' }, { name: 'beta', updated: '2026-09-12T00:00:00Z' }], total: 2, limit: 50, offset: 0 }, 'GET /factory/beta/backlog': { ...BACKLOG, repo: 'beta' }, 'GET /factory/beta/tasks': TASKS }))
    renderApp(<FactoryPage />, { route: '/factory' })
    await waitFor(() => expect(screen.getByTestId('factory-backlog-hash')).toHaveTextContent(`hash ${'a'.repeat(64)}`))
    expect(screen.queryByText('Choose a repository')).toBeNull()
    expect((screen.getByTestId('repo-picker') as HTMLSelectElement).value).toBe('beta')
    cleanup()
    mockApi(base({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } }))
    renderApp(<FactoryPage />, { route: '/factory' })
    await screen.findByText('No repository connected yet')
    expect(screen.queryByRole('link', { name: /Connect/ })).toBeNull()
    cleanup()
    mockApi(base({ 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } }))
    renderApp(<FactoryPage />, { route: '/factory' })
    expect(await screen.findByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/connect')
  })

  it('with no builder the button is disabled and the reason is the one Measure gives; the estimate says it is unmeasured', async () => {
    mockApi(base({ 'GET /health': HEALTH_NONE, 'GET /capability-map': { ...MAP, cells: [] } }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const box = await screen.findByTestId('before-you-start')
    await waitFor(() => expect(box).toHaveTextContent('No builder is configured on this deployment — an admin adds a provider key (Settings)'))
    expect(screen.getByRole('button', { name: /^Run the factory/ })).toBeDisabled()
    expect(box).toHaveTextContent('this repository has no measured mean yet (n = 0 on the current apparatus)')
  })

  it('an operator may name another builder (every knob); the choice replaces the default in the body', async () => {
    const { calls } = mockApi(base({ 'POST /runs': () => json({ id: 'e'.repeat(32), repo: 'alpha', kind: 'factory', status: 'queued' }, 201) }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    await screen.findByTestId('before-you-start')
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.click(screen.getByText(/Use a different builder/, { selector: 'summary' }))
    await userEvent.type(screen.getByLabelText('Builder'), 'fixture_gold')
    await userEvent.type(screen.getByLabelText('Model'), 'gold')
    await userEvent.click(screen.getByRole('button', { name: /^Run the factory/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))).toEqual({ repo: 'alpha', kind: 'factory', deliver: false, builder: 'fixture_gold', model: 'gold' })
  })

  it('the deliver opt-in is disabled with the reason and the next step when the repository cannot deliver (J-FAC-3)', async () => {
    mockApi(base())
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const box = await screen.findByTestId('before-you-start')
    const deliver = within(box).getByRole('checkbox', { name: /Open pull requests/ })
    expect(deliver).toBeDisabled()
    expect(deliver).not.toBeChecked()
    expect(box).toHaveTextContent('Delivery is not possible for this repository: it is connected by URL, not through the GitHub App.')
    expect(box).toHaveTextContent('then Sync installations in Settings')
    expect(box).toHaveTextContent('not linked — no pull request')
  })

  it('an API older than J-FAC-3 that sends no `delivery` reads as not possible with "update the API" — never a white screen or a guess', async () => {
    const { delivery: _omitted, ...older } = BACKLOG
    const olderBacklog: FactoryBacklog = older // `delivery` is optional in the type for exactly this response
    mockApi(base({ 'GET /factory/alpha/backlog': olderBacklog }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const box = await screen.findByTestId('before-you-start')
    const deliver = within(box).getByRole('checkbox', { name: /Open pull requests/ })
    expect(deliver).toBeDisabled()
    expect(deliver).not.toBeChecked()
    expect(box).toHaveTextContent('this API did not report the delivery pre-flight. Update the API, then reload.')
    expect(box).toHaveTextContent('not linked — no pull request')
  })

  it('when the repository can deliver, the opt-in says where the pull request goes and the approver’s override is explained in visible text', async () => {
    const { calls } = mockApi(
      base({
        'GET /auth/me': { ...PRINCIPAL, role: 'approver' },
        'GET /factory/alpha/backlog': { ...BACKLOG, delivery: LINKED },
        'POST /runs': () => json({ id: 'd'.repeat(32), repo: 'alpha', kind: 'factory', status: 'queued' }, 201),
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const box = await screen.findByTestId('before-you-start')
    const deliver = within(box).getByRole('checkbox', { name: /Open pull requests/ })
    expect(deliver).toBeEnabled()
    expect(box).toHaveTextContent('off — built and graded locally only. When on, a clean build in a deliver cell pushes a branch to acme/cobra and opens a pull request against main; nothing is written to main.')
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.click(deliver)
    expect(box).toHaveTextContent('on — a clean build in a deliver cell pushes a branch to acme/cobra and opens a pull request against main; nothing is written to main.')
    const override = within(box).getByRole('checkbox', { name: /Override the route gate/ })
    expect(box).toHaveTextContent('Recorded on the evidence chain as your override of the route gate, under your name.')
    await userEvent.click(override)
    await userEvent.click(screen.getByRole('button', { name: /^Run the factory/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))).toMatchObject({ deliver: true, deliver_override: true })
  })

  it('an item that was built opens its evidence and links its run; a refused item says why and what to do (F15, J-FAC-15)', async () => {
    const refused: FactoryTask = { ...TASKS[1]!, status: 'routed_human', dor_gaps: [], last_event: 'item.outcome', refusal: { step: 'readiness', reason: 'a value gap (expected response shape) is not signed and routes test-first', reason_code: '', measured_route: '' } }
    mockApi(base({ 'GET /factory/alpha/tasks': [TASKS[0], refused], [`GET /evidence/${'p'.repeat(64)}`]: () => envelope(404, 'not_found', 'no pack') }))
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha&item=I-2' })
    const row1 = await screen.findByTestId('factory-item-I-1')
    expect(within(row1).getByRole('link', { name: /run rrrrrrrr/ })).toHaveAttribute('href', `/runs/${'r'.repeat(32)}`)
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.click(within(row1).getByRole('button', { name: 'Evidence' }))
    expect(await screen.findByTestId('evidence-drawer')).toBeInTheDocument()
    const row2 = screen.getByTestId('factory-item-I-2')
    expect(within(row2).queryByRole('button', { name: 'Evidence' })).not.toBeInTheDocument()
    expect(row2).toHaveTextContent('Goes to a person')
    expect(row2).toHaveTextContent('This item goes to a person: a value gap (expected response shape) is not signed and routes test-first. To bring it back into the factory, add the fact and register an evolution that supersedes this item (the frozen hash stays; the old chain is kept)')
    // the way forward opens the freeze dialog prefilled from the active backlog
    await userEvent.click(within(row2).getByRole('button', { name: 'Freeze a revised backlog…' }))
    const form = await screen.findByTestId('backlog-form')
    expect(within(form).getAllByLabelText(/^Title/).map((el) => (el as HTMLInputElement).value)).toEqual(['Multiply', 'Divide'])
    expect((within(form).getByLabelText(/How is the bug reproduced\?/) as HTMLInputElement).value).toBe('x')
    expect((within(form).getAllByLabelText(/^Depends on/)[1] as HTMLInputElement).value).toBe('I-1')
  })

  it('an active factory run is a banner with the run link, done of items and the current item; the run controls step aside; an operator can cancel it (J-FAC-5 / J-TEL-9)', async () => {
    const working: FactoryTask = { ...TASKS[1]!, status: 'pending', dor_gaps: [], route_hint: 'build', red_proof: true, last_event: 'red.proved', cell_route: CALIBRATE }
    const runId = 'b'.repeat(32)
    const { calls } = mockApi(
      base({
        'GET /factory/alpha/tasks': [TASKS[0], working],
        'GET /runs': { items: [{ id: runId, repo: 'alpha', kind: 'factory', status: 'running', progress: { done: 1, total: 2, current_task_id: null }, started: '2026-09-15T10:00:00+00:00', cost_usd: 0.31, counts: {}, finished: null }], total: 1, limit: 10, offset: 0 },
        [`POST /runs/${runId}/cancel`]: () => json({ id: runId, repo: 'alpha', kind: 'factory', status: 'cancelling' }),
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const banner = await screen.findByTestId('factory-active-run')
    expect(banner).toHaveTextContent('Factory run bbbbbbbbbb is working the backlog — item 2 of 2 (I-2: RED proof — the authored test failed at the parent, so the build may start).')
    expect(banner).toHaveTextContent('$0.31 so far')
    expect(within(banner).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', `/runs/${runId}`)
    expect(screen.queryByRole('button', { name: /^Run the factory/ })).not.toBeInTheDocument()
    expect(screen.queryByTestId('before-you-start')).not.toBeInTheDocument()
    // the operator's Cancel posts to the run; items already built stay charged (the copy says so)
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.click(within(banner).getByRole('button', { name: 'Cancel the run' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === `/runs/${runId}/cancel`)).toBe(true))
  })

  it('a viewer sees the active-run banner without a Cancel button', async () => {
    mockApi(
      base({
        'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
        'GET /runs': { items: [{ id: 'b'.repeat(32), repo: 'alpha', kind: 'factory', status: 'queued', progress: null, started: null, cost_usd: 0, counts: {}, finished: null }], total: 1, limit: 10, offset: 0 },
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const banner = await screen.findByTestId('factory-active-run')
    expect(banner).toHaveTextContent('waiting for a worker')
    expect(within(banner).queryByRole('button', { name: 'Cancel the run' })).not.toBeInTheDocument()
  })

  it('a queued run with no progress and no tasks yet reads without a number — never "item 1 of 0"', async () => {
    mockApi(
      base({
        'GET /factory/alpha/tasks': [],
        'GET /runs': { items: [{ id: 'b'.repeat(32), repo: 'alpha', kind: 'factory', status: 'queued', progress: null, started: null, cost_usd: 0, counts: {}, finished: null }], total: 1, limit: 10, offset: 0 },
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const banner = await screen.findByTestId('factory-active-run')
    expect(banner).toHaveTextContent('is working the backlog (waiting for a worker).')
    expect(banner).not.toHaveTextContent(/\bof 0\b/)
    expect(banner).not.toHaveTextContent(/item \d/)
  })

  it('a queued run that still carries progress and a touched item (reclaimed after a stale worker) reads waiting — no item number, no item in hand', async () => {
    const touched: FactoryTask = { ...TASKS[1]!, status: 'pending', dor_gaps: [], route_hint: 'build', red_proof: true, last_event: 'red.proved', cell_route: CALIBRATE }
    mockApi(
      base({
        'GET /factory/alpha/tasks': [TASKS[0], touched],
        'GET /runs': { items: [{ id: 'b'.repeat(32), repo: 'alpha', kind: 'factory', status: 'queued', progress: { done: 1, total: 2, current_task_id: null }, started: null, cost_usd: 0.31, counts: {}, finished: null }], total: 1, limit: 10, offset: 0 },
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const banner = await screen.findByTestId('factory-active-run')
    expect(banner).toHaveTextContent('is working the backlog (waiting for a worker).')
    expect(banner).not.toHaveTextContent(/item \d/)
    expect(banner).not.toHaveTextContent('I-2:')
  })

  it('at phone width the item reads as one line — the current step and "step n of 6" — with the six cards behind a Details (J-FAC-14)', async () => {
    // jsdom has no matchMedia: stand one in that says the viewport is narrow
    const listeners = new Set<() => void>()
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query === '(max-width: 639px)', media: query, addEventListener: (_: string, fn: () => void) => listeners.add(fn), removeEventListener: (_: string, fn: () => void) => listeners.delete(fn) }))
    try {
      mockApi(base())
      renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
      const row = await screen.findByTestId('factory-item-I-2')
      expect(within(row).getByTestId('steps-compact-I-2')).toHaveTextContent(/here.*Readiness.*step 1 of 6/)
      // the cards are still there, behind a closed Details the reader can open
      const details = within(row).getByText('All 6 steps').closest('details')!
      expect(details).not.toHaveAttribute('open')
      expect(within(details).getByTestId('step-I-2-readiness')).toHaveTextContent('2 structural gaps unsigned: method_path, response_shape')
      // the cell-route pill is short; the numbers follow in their own span
      expect(within(row).getByTestId('cell-route-I-2')).toHaveTextContent('not measured · withheld')
      const wide = screen.getByTestId('factory-item-I-1')
      expect(within(wide).getByTestId('cell-route-I-1')).toHaveTextContent('routes deliver')
      expect(within(wide).getByTestId('cell-route-I-1-prov')).toHaveTextContent('n = 40 · 95 % [84 %, 99 %] · apparatus 2.2')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('the freeze form asks the class\'s structural questions and posts slot: fact lines (F24)', async () => {
    const { calls } = mockApi(
      base({
        'GET /factory/alpha/backlog': () => envelope(404, 'not_found', "no backlog registered for 'alpha'"),
        'GET /factory/alpha/tasks': [],
        'POST /factory/alpha/backlog': () => json(BACKLOG, 201),
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Freeze a backlog…' }))[0]!)
    const form = await screen.findByTestId('backlog-form')
    // the class's structural question is the field; a value slot is marked optional
    await userEvent.selectOptions(within(form).getByLabelText(/^Class/), 'backend.route.add')
    expect(within(form).getByLabelText(/What HTTP method and path does the new route answer\?/)).toBeInTheDocument()
    expect(within(form).getByLabelText(/A representative request and its exact expected response\. \(value — optional\)/)).toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText(/^Title/), 'Add /health')
    await userEvent.type(within(form).getByLabelText(/What HTTP method and path/), 'GET /health')
    // enabled only once the catalogue answered and every item has an id and a title
    await waitFor(() => expect(screen.getByRole('button', { name: 'Freeze 1 item' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Freeze 1 item' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/factory/alpha/backlog')).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))
    expect(body).toEqual({
      items: [{ id: 'I-1', title: 'Add /health', kind: 'code', level: 'L1', description: '', capability_class: 'backend.route.add', size_estimate: 'XS', structural_facts: ['method_path: GET /health'], depends_on: [] }],
    })
  })

  it('a generated item id never recycles one still in use', () => {
    const d = (id: string) => ({ id, title: '', capability_class: 'bug.fix', size_estimate: 'XS', kind: 'code', level: 'L1', description: '', depends_on: '', facts: {} })
    expect(nextId([])).toBe('I-1')
    expect(nextId([d('I-1'), d('I-3')])).toBe('I-4') // I-2 was removed; length+1 = I-3 is taken
    expect(nextId([d('I-1'), d('I-2')])).toBe('I-3')
  })

  it('signing a gap posts the slot and the answer to the item; the gap is the catalogue’s question and the signer and time come back (J-FAC-16)', async () => {
    const { calls } = mockApi(
      base({
        'GET /auth/me': PRINCIPAL,
        'POST /factory/alpha/tasks/I-2/signoff-gap': { item_id: 'I-2', slot: 'method_path', kind: 'structural', verifier: 'approver:u1', signed_at: '2026-09-15T14:02:00+00:00', row_hash: 'z'.repeat(64) },
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha&item=I-2' })
    const form = await screen.findByRole('form', { name: 'Sign a structural gap for I-2' })
    await waitFor(() => expect(within(form).getByRole('option', { name: 'Which HTTP method and path does the change add? (method_path)' })).toBeInTheDocument())
    expect(within(form).getByLabelText(/Your answer/)).toHaveAccessibleDescription(/Which HTTP method and path does the change add\?/)
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.type(within(form).getByLabelText(/Your answer/), 'GET /health')
    await userEvent.click(within(form).getByRole('button', { name: 'Sign the gap' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/factory/alpha/tasks/I-2/signoff-gap')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ slot: 'method_path', answer: 'GET /health' })
    expect(await screen.findByText(/Signed by approver:u1 at .* — on the chain/)).toBeInTheDocument()
  })

  it('a 404 is "no backlog registered", not an error and not fabricated rows', async () => {
    mockApi(
      base({
        'GET /auth/me': PRINCIPAL,
        'GET /factory/alpha/backlog': () => envelope(404, 'not_found', "no backlog registered for 'alpha'"),
        'GET /factory/alpha/tasks': [],
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    await waitFor(() => expect(screen.getByTestId('factory-no-backlog')).toBeInTheDocument())
    expect(screen.getByText(/Freeze one: the items are validated, hashed/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('No factory items yet')).toBeInTheDocument()
    expect(within(screen.getByTestId('factory-no-backlog')).getByRole('button', { name: 'Freeze a backlog…' })).toBeInTheDocument()
  })

  it('a viewer is told an operator freezes the backlog, and is not shown the Freeze button', async () => {
    mockApi(
      base({
        'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
        'GET /factory/alpha/backlog': () => envelope(404, 'not_found', "no backlog registered for 'alpha'"),
        'GET /factory/alpha/tasks': [],
      }),
    )
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    await waitFor(() => expect(screen.getByTestId('factory-no-backlog')).toBeInTheDocument())
    expect(screen.getByText(/An operator freezes one: the items are validated, hashed/)).toBeInTheDocument()
    expect(screen.queryByText(/^Freeze one:/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Freeze a backlog/ })).not.toBeInTheDocument()
  })

  it('deliverableCount counts the items whose cell routes deliver', () => {
    expect(deliverableCount(TASKS)).toBe(1)
  })
})
