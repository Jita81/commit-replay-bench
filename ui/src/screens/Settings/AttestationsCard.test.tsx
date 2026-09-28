/**
 * Go-live attestations on Settings — an admin records what only the operator can prove.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests of ui/src/screens/Settings/AttestationsCard.tsx.
 * What it does: Pins that only the operator's lines are offered; that Record attestation sends
 *               the line, the words and the day through `PUT /settings/attestations/{line}`
 *               and says what it recorded; that Withdraw asks first, sends `DELETE` and says
 *               the line reads unproven again, while Keep it sends nothing; and that the
 *               server's refusal is shown in its own words.
 * How:          `mockApi` over the shared go-live fixture; the calls it records are read back.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
 * Works with:   ui/src/screens/Settings/AttestationsCard.tsx (under test), ui/src/test/golive.ts
 *               (the reading it is given),
 *               src/crb/server/routes/golive.py (the routes these calls reach)
 * Tested by:    this file
 * Touch when:   never for a new repository; the card's writes change.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GOLIVE } from '../../test/golive'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { AttestationsCard } from './AttestationsCard'

const ADMIN = { 'GET /auth/me': { ...PRINCIPAL, role: 'admin' }, 'GET /golive': GOLIVE }

describe('AttestationsCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('offers only the lines the operator proves, each with its state', async () => {
    mockApi(ADMIN)
    renderApp(<AttestationsCard />, { route: '/settings' })
    const select = await screen.findByTestId('attest-line')
    expect(Array.from((select as HTMLSelectElement).options).map((o) => o.value)).toEqual(['egress-denied', 'penetration-test'])
    expect(screen.getByTestId('attestation-egress-denied')).toHaveTextContent('Attested')
    expect(screen.getByTestId('attestation-penetration-test')).toHaveTextContent('Unproven')
    expect(screen.queryByTestId('attestation-health-green')).toBeNull()
  })

  it('records an attestation with the line, the words and the day, and says what it recorded', async () => {
    const { calls } = mockApi({ ...ADMIN, 'PUT /settings/attestations/penetration-test': GOLIVE })
    renderApp(<AttestationsCard />, { route: '/settings' })
    await userEvent.selectOptions(await screen.findByTestId('attest-line'), 'penetration-test')
    await userEvent.type(screen.getByTestId('attest-statement'), 'Tested by Acme Security; report PT-7 in the risk register')
    const day = screen.getByTestId('attest-day') as HTMLInputElement
    await userEvent.clear(day)
    await userEvent.type(day, '2026-09-20')
    await userEvent.click(screen.getByTestId('attest-submit'))
    await waitFor(() => expect(screen.getByTestId('attest-done')).toHaveTextContent('Recorded: “A penetration test of this deployment has been done and its findings handled” was done on 2026-09-20.'))
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.path).toBe('/settings/attestations/penetration-test')
    expect(JSON.parse(String(put.init?.body))).toEqual({ statement: 'Tested by Acme Security; report PT-7 in the risk register', performed_on: '2026-09-20' })
  })

  it('withdraws only after asking, and Keep it withdraws nothing', async () => {
    const { calls } = mockApi({ ...ADMIN, 'DELETE /settings/attestations/egress-denied': GOLIVE })
    renderApp(<AttestationsCard />, { route: '/settings' })
    await userEvent.click(await screen.findByTestId('withdraw-egress-denied'))
    await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByTestId('withdraw-egress-denied'))
    expect(within(screen.getByTestId('attestation-egress-denied')).getByText('Withdraw it? The line reads unproven again.')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('withdraw-confirm-egress-denied'))
    await waitFor(() => expect(screen.getByTestId('attest-done')).toHaveTextContent('Withdrawn: “An egress test from a worker pod to a public address fails” reads unproven again.'))
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/settings/attestations/egress-denied'])
  })

  it('shows the server’s refusal in its own words', async () => {
    mockApi({ ...ADMIN, 'PUT /settings/attestations/egress-denied': () => envelope(422, 'invalid_attestation', 'the act cannot be dated in the future') })
    renderApp(<AttestationsCard />, { route: '/settings' })
    await userEvent.type(await screen.findByTestId('attest-statement'), 'done')
    await userEvent.click(screen.getByTestId('attest-submit'))
    expect(await screen.findByText(/the act cannot be dated in the future/)).toBeInTheDocument()
    expect(screen.queryByTestId('attest-done')).toBeNull()
  })
})
