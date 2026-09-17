/**
 * ui/src/screens/Factory/FactoryPage.tsx — the shipped contract: a backlog, a bare task list,
 * and the 404 that means "no backlog registered".
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the factory page against mocked `GET /factory/{repo}/backlog`
 *               and `/tasks`.
 * What it does: Pins that a registered backlog renders its hash, frozen pill and items; that
 *               `/tasks` is consumed as the bare list the server serves (not a `Page`) with
 *               status, route hint, DoR gaps, RED proof, build status and review verdict;
 *               and that a 404 `not_found` is the "no backlog registered" instruction, never
 *               an error state or fabricated rows (the old screen matched a phase-P6 501
 *               that the shipped server never answers — CodeRabbit on PR #6).
 * How:          `mockApi` + `renderApp` at `/factory?repo=…`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Factory/FactoryPage.tsx (under test), ui/src/api/types.ts
 *               (`FactoryBacklog`, `FactoryTask`), src/crb/server/routes/factory.py (the
 *               shapes mirrored here), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Factory/FactoryPage.test.tsx
 * Touch when:   a factory action moves into the UI; a `FactoryTaskOut` field is added.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FactoryBacklog, FactoryTask } from '../../api/types'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { FactoryPage, stepsFor } from './FactoryPage'

const BACKLOG: FactoryBacklog = {
  repo: 'alpha',
  hash: 'a'.repeat(64),
  frozen_at: '2026-09-15T10:00:00+00:00',
  items: [
    { id: 'I-1', title: 'Multiply', kind: 'code', capability_class: 'bug.fix', size: 'XS', level: 'L1', depends_on: [], structural_facts: ['reproduction: x'], has_authored_test: true },
    { id: 'I-2', title: 'Divide', kind: 'code', capability_class: 'feature.add', size: 'S', level: 'L1', depends_on: ['I-1'], structural_facts: [], has_authored_test: false },
  ],
}

const TASKS: FactoryTask[] = [
  { id: 'I-1', title: 'Multiply', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'accepted', dor_gaps: [], route_hint: 'build', red_proof: true, build_status: 'clean', pr_url: null, review_verdict: 'accept', last_event: 'item.outcome', cell_route: { route: 'deliver', reason_code: 'deliver', reason: 'ok', n: 40, deliverable: true } },
  { id: 'I-2', title: 'Divide', capability_class: 'feature.add', size: 'S', kind: 'code', status: 'blocked', dor_gaps: ['method_path', 'response_shape'], route_hint: 'human', red_proof: null, build_status: 'not_started', pr_url: null, review_verdict: null, last_event: 'readiness.blocked', cell_route: { route: '', reason_code: '', reason: '', n: 0, deliverable: false } },
]

describe('stepsFor — an item the factory has not touched', () => {
  it('reads as not assessed / not run / not started, never as done or failed', () => {
    // exactly what the API folds for a frozen-but-unrun item (factory_state.task_views)
    const untouched: FactoryTask = { id: 'T-1', title: 'x', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'pending', dor_gaps: [], route_hint: '', red_proof: null, build_status: 'not_built', pr_url: null, review_verdict: null, last_event: '', cell_route: { route: '', reason_code: '', reason: '', n: 0, deliverable: false } }
    const steps = stepsFor(untouched)
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

  it('a build that ran and was not clean is the failure, spelled out', () => {
    const notClean: FactoryTask = { id: 'T-2', title: 'x', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'not_clean', dor_gaps: [], route_hint: 'build', red_proof: true, build_status: 'not_clean', pr_url: null, review_verdict: null, last_event: 'build', cell_route: { route: 'deliver', reason_code: 'deliver', reason: 'ok', n: 40, deliverable: true } }
    const build = stepsFor(notClean)[2]!
    expect(build.status).toBe('failed')
    expect(build.detail).toBe('not clean')
  })
})

describe('FactoryPage — the shipped contract', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the frozen backlog and the bare task list', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/backlog': BACKLOG,
      'GET /factory/alpha/tasks': TASKS,
    })
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    await waitFor(() => expect(screen.getByText(/hash aaaaaaaaaaaaaaaa/)).toBeInTheDocument())
    expect(screen.getByText('frozen')).toBeInTheDocument()
    expect(screen.getByText('2 items')).toBeInTheDocument()
    expect(screen.getAllByText('Multiply').length).toBeGreaterThan(0)
    // each item is the six-step process: I-1 done through review, I-2 waiting at readiness
    expect(screen.getByText('accepted · build')).toBeInTheDocument()
    expect(screen.getByText('blocked · human')).toBeInTheDocument()
    expect(screen.getByTestId('step-I-1-review')).toHaveTextContent('done')
    expect(screen.getByTestId('step-I-1-outcome')).toHaveTextContent('accepted')
    expect(screen.getByTestId('step-I-2-readiness')).toHaveTextContent('2 structural gaps unsigned: method_path, response_shape')
    expect(screen.getByTestId('step-I-2-red')).toHaveTextContent('not yet')
    // the approver can sign a gap right there; the operator's run controls are present
    expect(screen.getByRole('form', { name: 'Sign a structural gap for I-2' })).toBeInTheDocument()
    expect(screen.getByTestId('factory-run-controls')).toBeInTheDocument()
    // F28 — each item shows its cell's route BEFORE the run, and the controls count the deliverable ones
    expect(screen.getByTestId('cell-route-I-1')).toHaveTextContent('routes deliver · n=40')
    expect(screen.getByTestId('cell-route-I-2')).toHaveTextContent('cell not measured · delivery withheld')
    expect(screen.getByTestId('factory-deliverable-count')).toHaveTextContent('1 of 2 items sit in a cell that routes deliver today')
  })

  it('the freeze form asks the class\'s structural questions and posts slot: fact lines (F24)', async () => {
    const CATALOGUE = {
      classes: [
        { capability_class: 'backend.route.add', slots: [{ name: 'method_path', question: 'What HTTP method and path does the new route answer?', kind: 'structural' }, { name: 'example_payload', question: 'A representative request and its exact expected response.', kind: 'value' }] },
        { capability_class: 'bug.fix', slots: [{ name: 'reproduction', question: 'How is the bug reproduced?', kind: 'structural' }] },
      ],
      sizes: ['XS', 'S', 'M', 'L', 'XL'],
      kinds: ['code', 'infra', 'operator'],
      levels: ['L1', 'L2', 'L3'],
    }
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', "no backlog registered for 'alpha'"),
      'GET /factory/alpha/tasks': [],
      'GET /factory/catalogue': CATALOGUE,
      'POST /factory/alpha/backlog': () => json(BACKLOG, 201),
    })
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
    await userEvent.click(screen.getByRole('button', { name: 'Freeze 1 item' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/factory/alpha/backlog')).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))
    expect(body).toEqual({
      items: [{ id: 'I-1', title: 'Add /health', kind: 'code', level: 'L1', description: '', capability_class: 'backend.route.add', size_estimate: 'XS', structural_facts: ['method_path: GET /health'], depends_on: [] }],
    })
  })

  it('signing a gap posts the slot and the answer to the item', async () => {
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/backlog': BACKLOG,
      'GET /factory/alpha/tasks': TASKS,
      'POST /factory/alpha/tasks/I-2/signoff-gap': { item_id: 'I-2', slot: 'method_path', kind: 'structural' },
    })
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha&item=I-2' })
    const form = await screen.findByRole('form', { name: 'Sign a structural gap for I-2' })
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.type(within(form).getByLabelText(/Your answer/), 'GET /health')
    await userEvent.click(within(form).getByRole('button', { name: 'Sign the gap' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/factory/alpha/tasks/I-2/signoff-gap')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ slot: 'method_path', answer: 'GET /health' })
    expect(await screen.findByText('signed — on the chain')).toBeInTheDocument()
  })

  it('a 404 is "no backlog registered", not an error and not fabricated rows', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /factory/alpha/backlog': () => envelope(404, 'not_found', "no backlog registered for 'alpha'"),
      'GET /factory/alpha/tasks': [],
    })
    renderApp(<FactoryPage />, { route: '/factory?repo=alpha' })
    await waitFor(() => expect(screen.getByTestId('factory-no-backlog')).toBeInTheDocument())
    expect(screen.getByText(/Freeze one: the items are validated, hashed/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('No factory items yet')).toBeInTheDocument()
  })
})
