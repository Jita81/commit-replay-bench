/**
 * The invite-an-approver card on Settings — the admin's half of the second person (G-518).
 *
 * Navigation
 * ----------
 * What it is:   The test suite for `InviteApproverCard` and `stateMeaning`.
 * What it does: Pins that the deployment's two-person readiness is shown in the server's own
 *               words (and not as a guess from the presence of an admin), that inviting posts
 *               the form and then shows the link ONCE with the warning that it cannot be
 *               recovered, that each invitation row says where it stands — including an
 *               accepted account that has never signed in, which is the state an admin's
 *               presence could never reveal — that a pending link can be withdrawn with a
 *               recorded reason and an accepted one offers no such button, and that a refused
 *               invitation renders the envelope rather than a blank form.
 * How:          `mockApi` + `renderApp`; the POST bodies are read back from the recorded calls.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/InviteApproverCard.tsx (under test),
 *               src/crb/server/routes/invitations.py (the routes it calls),
 *               ui/src/screens/Home/HomePage.test.tsx (task 7 reads the same readiness)
 * Tested by:    itself
 * Touch when:   an invitation state is added, or the readiness reading gains a field a person
 *               reads.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InviteApproverCard, stateMeaning } from './InviteApproverCard'
import type { Invitation } from '../../api/types'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'

const inv = (over: Partial<Invitation>): Invitation => ({
  id: 'i1',
  user_id: 'u1',
  username: 'walk-approver',
  display_name: 'Walk Approver',
  email: '',
  role: 'approver',
  state: 'pending',
  created: '2026-09-23T09:00:00Z',
  expires: '2026-09-26T09:00:00Z',
  accepted: '',
  revoked: '',
  created_by: 'admin1',
  revoked_reason: '',
  last_login: '',
  ...over,
})

const NOT_READY = {
  ready: false,
  reason_code: 'approver_never_signed_in',
  reason: 'the only account that can sign has never signed in, so it can sign nothing yet — the invitation has not been used',
  approvers_active: 1,
  approvers_signed_in: 0,
  other_active_accounts: 1,
  accounts_signed_in: 1,
  invitations_pending: 1,
}

const base = (over: Record<string, unknown> = {}) => ({
  'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
  'GET /two-person-readiness': NOT_READY,
  'GET /invitations': { items: [inv({})], total: 1, limit: 50, offset: 0 },
  ...over,
})

describe('stateMeaning', () => {
  it('says what each state means for the person reading the row', () => {
    expect(stateMeaning(inv({ state: 'accepted' }))).toBe('accepted, but this account has never signed in')
    expect(stateMeaning(inv({ state: 'accepted', last_login: '2026-09-23T10:00:00Z' }))).toContain('accepted and signed in')
    expect(stateMeaning(inv({ state: 'pending' }))).toContain('the link works until')
    expect(stateMeaning(inv({ state: 'expired' }))).toContain('invite again')
    expect(stateMeaning(inv({ state: 'revoked', revoked_reason: 'wrong person' }))).toBe('withdrawn: wrong person')
  })
})

describe('InviteApproverCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the deployment’s readiness in the server’s words, not a guess from the account list', async () => {
    mockApi(base())
    renderApp(<InviteApproverCard />, { route: '/settings' })
    const pill = await screen.findByTestId('two-person-readiness')
    expect(pill).toHaveTextContent('not two-person ready')
    expect(screen.getByTestId('two-person-reason')).toHaveTextContent('has never signed in')
    expect(screen.getByTestId('two-person-reason')).toHaveTextContent('0 of 1 account that can sign have signed in; 1 invitation waiting')
  })

  it('an accepted invitation whose account never signed in says so, and offers no withdraw button', async () => {
    mockApi(base({ 'GET /invitations': { items: [inv({ state: 'accepted', accepted: '2026-09-23T10:00:00Z' })], total: 1, limit: 50, offset: 0 } }))
    renderApp(<InviteApproverCard />, { route: '/settings' })
    const state = await screen.findByTestId('invitation-state-walk-approver')
    expect(state).toHaveTextContent('accepted')
    expect(state).toHaveAttribute('aria-label', 'accepted, but this account has never signed in')
    expect(screen.queryByTestId('revoke-walk-approver')).not.toBeInTheDocument()
  })

  it('inviting posts the form and shows the one-time link once, with the warning', async () => {
    const created = {
      invitation: inv({ id: 'i2', username: 'second-person' }),
      accept_url: 'https://crb.example.nhs.uk/invite?token=the-one-time-token',
      token: 'the-one-time-token',
      public_url_missing: false,
    }
    const { calls } = mockApi(base({ 'POST /invitations': created }))
    renderApp(<InviteApproverCard />, { route: '/settings' })
    await userEvent.type(await screen.findByLabelText(/^Username/), 'second-person')
    await userEvent.type(screen.getByLabelText(/^Display name/), 'Second Person')
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/invitations')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))).toEqual({
      username: 'second-person',
      role: 'approver',
      display_name: 'Second Person',
      email: '',
      expires_hours: 72,
    })
    const panel = await screen.findByTestId('invitation-link')
    expect(within(panel).getByTestId('invitation-url')).toHaveTextContent('https://crb.example.nhs.uk/invite?token=the-one-time-token')
    expect(panel).toHaveTextContent('This link is shown once and cannot be recovered')
    expect(within(panel).getByRole('button', { name: 'Copy the link' })).toBeInTheDocument()
  })

  it('a pending link is withdrawn with a reason, and a refused invitation renders the envelope', async () => {
    const { calls } = mockApi(
      base({
        'POST /invitations/i1/revoke': inv({ state: 'revoked', revoked: '2026-09-23T11:00:00Z', revoked_reason: 'withdrawn by an admin on the Settings screen' }),
        'POST /invitations': () => envelope(409, 'user_exists', "user 'walk-approver' already exists"),
      }),
    )
    renderApp(<InviteApproverCard />, { route: '/settings' })
    await userEvent.click(await screen.findByTestId('revoke-walk-approver'))
    await waitFor(() => expect(calls.some((c) => c.path === '/invitations/i1/revoke')).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.path === '/invitations/i1/revoke')!.init?.body))
    expect(String(body.reason).length).toBeGreaterThan(3)
    // a refused invitation says why, in the server's words
    await userEvent.type(screen.getByLabelText(/^Username/), 'walk-approver')
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    expect(await screen.findByText(/already exists/)).toBeInTheDocument()
  })
})
