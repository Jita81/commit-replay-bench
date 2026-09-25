/**
 * ui/src/screens/Routing/RoutingPage.tsx — the amended rule, the controls verdict, a reason code
 * and the split per decision.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the routing page against a mocked `GET /routes`.
 * What it does: Pins that the policy card states the amended rule with the controls
 *               thresholds, that the repo's controls verdict pill is rendered as served
 *               (an `escaped` verdict here), that every decision shows its `reason_code`
 *               and its failure split next to the model point, and that the route pills
 *               carry the reason in their accessible label.
 * How:          `mockApi` with a `RoutesWithControls` fixture; `renderApp` at
 *               `/routing?repo=…`; assertions on `reason-code`, `controls-*` and the policy
 *               rule text.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Routing/RoutingPage.tsx (the code under test),
 *               ui/src/screens/Capability/contract.ts (the fixture shapes), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Routing/RoutingPage.test.tsx
 * Touch when:   a reason code or policy threshold is added — extend the fixture and the
 *               rule-text assertion.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import type { ControlsVerdict, RouteDecisionWithControls, RoutesWithControls } from '../Capability/contract'
import { RoutingPage } from './RoutingPage'

const VERDICT: ControlsVerdict = {
  measured: true,
  passed: true,
  complete: true,
  constructible: 12,
  total: 14,
  share: 0.8571,
  escapes: 1,
  run_id: '00000000000000000000000000000000',
  created: '2026-08-26T09:20:00Z',
  state: 'escaped',
}

const decision = (over: Partial<RouteDecisionWithControls>): RouteDecisionWithControls => ({
  route: 'human',
  reason: 'controls_escapes: 1 measurement control(s) graded clean on this repo — the oracle cannot tell an implementation from a cheat; green cannot license auto-delivery until the oracle is hardened and re-measured (controls run 00000000)',
  reason_code: 'controls_escapes',
  cell: { process_step: 'replay', capability_class: 'bug.fix', size: 'S', language: 'python', builder: 'editblock', model: 'gpt-oss-120b', provider: 'cerebras' },
  n: 40,
  point: 0.95,
  ci_low: 0.835,
  ci_high: 0.987,
  false_q1: 0,
  oracle_strength: null,
  policy_version: 'routing.v1',
  verification_tier: 'automated-pass',
  apparatus_versions: ['2.2'],
  belt_sets: ['v5'],
  controls_policy: 'controls-gate.v1',
  controls: VERDICT,
  model_n: 40,
  model_point: 0.95,
  model_ci_low: 0.835,
  model_ci_high: 0.987,
  failure_split: { builder_red: 2, budget: 0, protocol: 0, harness: 0, disqualified: 0 },
  ...over,
})

const ROUTES_BODY: RoutesWithControls = {
  repo: 'alpha',
  policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1', min_controls_share: 0.5, max_controls_escapes: 0, controls_version: 'controls-gate.v1' },
  controls: VERDICT,
  decisions: [
    decision({}),
    decision({
      route: 'calibrate',
      reason: 'n=4 < 10',
      reason_code: 'n_below_min',
      cell: { process_step: 'replay', capability_class: 'backend.route.add', size: 'M', language: 'python', builder: 'editblock', model: 'gpt-oss-120b', provider: 'cerebras' },
      n: 4,
      point: 0.5,
      ci_low: 0.15,
      model_n: 3,
      model_point: 0.6667,
      model_ci_low: null,
      model_ci_high: null,
      failure_split: { builder_red: 1, budget: 0, protocol: 0, harness: 1, disqualified: 0 },
    }),
  ],
}

describe('RoutingPage — reason codes, the controls verdict and the split (A2)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the amended rule, the verdict pill, a reason code per decision and the split', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /routes': ROUTES_BODY,
    })
    renderApp(<RoutingPage />, { route: '/routing?repo=alpha' })
    await waitFor(() => expect(screen.getByTestId('policy-rule')).toBeInTheDocument())

    // the policy card names both clause sets and the controls bars
    const rule = screen.getByTestId('policy-rule')
    expect(rule.textContent).toContain('negative controls passed')
    expect(rule.textContent).toContain('≥ 50% of control rows constructible')
    expect(rule.textContent).toContain('escapes ≤ 0')
    expect(rule.textContent).toContain('never instead of it')
    expect(screen.getByText('routing.v1 + controls-gate.v1')).toBeInTheDocument()

    // the repo's verdict as a pill: passed but escaped
    const pill = screen.getByTestId('controls-escaped')
    expect(pill.textContent).toContain('1 escape')
    expect(pill.getAttribute('aria-label')).toMatch(/1 measurement control\(s\) graded clean/)

    // every decision carries its reason code and the reason string
    const codes = screen.getAllByTestId('reason-code').map((c) => c.textContent)
    expect(codes).toEqual(expect.arrayContaining(['controls_escapes', 'n_below_min']))
    expect(screen.getByText('n=4 < 10')).toBeInTheDocument()
    expect(screen.getByText(/1 measurement control\(s\) graded clean/)).toBeInTheDocument()

    // the split and the model rate travel with each decision
    const splits = screen.getAllByTestId('failure-split')
    expect(splits.map((s) => s.getAttribute('aria-label'))).toEqual(
      expect.arrayContaining(['red 2, lint 0, api 0, budget 0, protocol 0, harness 0, outage 0, DQ 0', 'red 1, lint 0, api 0, budget 0, protocol 0, harness 1, outage 0, DQ 0']),
    )
    const models = screen.getAllByTestId('model-point').map((m) => m.textContent)
    // the model rate keeps its n and, when served, its interval (the second decision has
    // model_ci_* from the fixture default: 0.835–0.987 on 40; the third serves none)
    expect(models.some((t) => t?.includes('model 67%') && t.includes('(2/3'))).toBe(true)
    expect(models.some((t) => t?.includes('model 95%') && t.includes('[84%–99%]'))).toBe(true)
  })

  it('a reason code opens its sentence inline — a button, not a hover title (J-HEL-15)', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 },
      'GET /routes': ROUTES_BODY,
    })
    renderApp(<RoutingPage />, { route: '/routing?repo=alpha' })
    await waitFor(() => expect(screen.getAllByTestId('reason-code').length).toBe(2))
    const code = screen.getAllByTestId('reason-code').find((c) => c.textContent === 'n_below_min')!
    expect(code.getAttribute('title')).toBeNull()
    const button = code.closest('button')!
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('not enough evidence (n below the bar)')).toBeNull()
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const note = document.getElementById(button.getAttribute('aria-controls')!)!
    expect(note.textContent).toContain('not enough evidence (n below the bar)')
    expect(within(note).getByRole('link', { name: 'glossary' })).toHaveAttribute('href', '/help#reason_code')
    await userEvent.keyboard('{Escape}')
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('empty states: no repo sends every role to Connection; no decisions offers the run only to an operator (J-FAC-12)', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /repos': { items: [], total: 0, limit: 50, offset: 0 } })
    const idle = renderApp(<RoutingPage />, { route: '/routing' })
    expect(await screen.findByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/connect')
    idle.unmount()
    vi.unstubAllGlobals()

    const none: RoutesWithControls = { ...ROUTES_BODY, decisions: [] }
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 }, 'GET /routes': none })
    const viewer = renderApp(<RoutingPage />, { route: '/routing?repo=alpha' })
    expect(await screen.findByText('No decisions yet')).toBeInTheDocument()
    expect(screen.getByText(/an operator starts a replay run/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Start a replay run' })).toBeNull()
    viewer.unmount()
    vi.unstubAllGlobals()

    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'operator' }, 'GET /repos': { items: [{ name: 'alpha' }], total: 1, limit: 50, offset: 0 }, 'GET /routes': none })
    renderApp(<RoutingPage />, { route: '/routing?repo=alpha' })
    expect(await screen.findByRole('link', { name: 'Start a replay run' })).toHaveAttribute('href', '/runs?repo=alpha&new=replay')
  })
})
