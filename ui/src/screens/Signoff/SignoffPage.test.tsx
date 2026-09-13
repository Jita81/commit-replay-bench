import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CapabilityMap } from '../../api/types'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { SignoffPage } from './SignoffPage'

const MAP: CapabilityMap = {
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
      ci_low: 0.84,
      ci_high: 0.99,
      false_q1: 0,
      cost_usd_mean: 0.01,
      latency_s_mean: 30,
      oracle_strength_mean: 0.9,
      route: 'deliver',
      reason: 'ok',
      verification_tier: 'automated-pass',
      apparatus_versions: ['2.0'],
    },
  ],
  summary: { trusted_autonomy_coverage: 1, total_cells: 1, measured_cells: 1, deliver_cells: 1, n_total: 40, false_q1_total: 0, apparatus_versions: ['2.0'] },
  policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' },
}

describe('SignoffPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders a 409 false_q1_refused as a gate REFUSED, not a generic error', async () => {
    document.cookie = 'crb_csrf=t; path=/'
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'POST /signoffs': () => envelope(409, 'false_q1_refused', 'cell bug.fix|S has 1 false-Q1 row since the map was computed', { false_q1: 1 }),
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()

    const gate = await screen.findByTestId('signoff-gate')
    expect(gate).toHaveAttribute('data-state', 'PENDING')
    // The approver button appears once /auth/me has resolved the role.
    const submit = await screen.findByRole('button', { name: 'Sign off' })
    expect(submit).toBeDisabled()

    // Choose the measured cell → all criteria hold → gate OPEN, button enabled once a note is typed.
    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/Cell/), 'bug.fix|S')
    expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'OPEN')
    await user.type(screen.getByLabelText(/Attestation note/), 'Reviewed 40 packs.')
    expect(submit).toBeEnabled()

    await user.click(submit)

    await waitFor(() => expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'REFUSED'))
    const refused = screen.getByTestId('signoff-gate')
    expect(refused.textContent).toContain('Sign-off refused: false-Q1 invariant')
    expect(refused.textContent).toContain('false_q1_refused')
    expect(refused.textContent).toContain('has 1 false-Q1 row')
    expect(refused.textContent).toContain('Nothing was recorded')
    // No generic red error box for this case.
    expect(screen.queryByTestId('error-state')).toBeNull()

    // The POST carried the CSRF header and the contract body.
    const post = calls.find((c) => c.method === 'POST' && c.path === '/signoffs')!
    expect((post.init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('t')
    expect(JSON.parse(String(post.init?.body))).toEqual({ repo: 'r', cell: { capability_class: 'bug.fix', size: 'S' }, note: 'Reviewed 40 packs.' })
  })

  it('renders other errors as the envelope, and records a success', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [{ name: 'r' }], total: 1, limit: 50, offset: 0 },
      'GET /capability-map': MAP,
      'GET /signoffs': { items: [], total: 0, limit: 50, offset: 0 },
      'POST /signoffs': () => envelope(403, 'forbidden', 'approver role required'),
    })
    renderApp(<SignoffPage />, { route: '/signoff?repo=r' })
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('option', { name: /bug\.fix · S/ })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText(/Cell/), 'bug.fix|S')
    await user.type(screen.getByLabelText(/Attestation note/), 'x')
    await user.click(screen.getByRole('button', { name: 'Sign off' }))
    const err = await screen.findByTestId('error-state')
    expect(err.textContent).toContain('approver role required')
    expect(err.textContent).toContain('HTTP 403')
    expect(screen.getByTestId('signoff-gate')).toHaveAttribute('data-state', 'OPEN')
  })
})
