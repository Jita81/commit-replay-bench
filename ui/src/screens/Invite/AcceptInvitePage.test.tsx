/**
 * The invitation link's page (/invite) — what the second person meets before they have an account.
 *
 * Navigation
 * ----------
 * What it is:   The test suite for `AcceptInvitePage` and `passwordProblem`.
 * What it does: Pins that a link with no token says so instead of showing a form, that the two
 *               password fields are compared in the browser (too short, and not the same, each
 *               with its own sentence) and nothing is posted until they agree, that a valid
 *               submission posts the token and the chosen password and nothing else, that the
 *               success state names the account and its role and offers the way to sign in, and
 *               that a refused link renders the server's envelope with a title a person can act
 *               on rather than a blank form.
 * How:          `mockApi` + `renderApp` at `/invite?token=…`; the POST body is read back from
 *               the recorded calls.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Invite/AcceptInvitePage.tsx (under test),
 *               ui/src/help/hints-ratchet.shell.tsx (the same screen under the hint ratchet),
 *               src/crb/server/routes/invitations.py (the route it posts to)
 * Tested by:    itself
 * Touch when:   the accept body or the password floor changes.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AcceptInvitePage, passwordProblem } from './AcceptInvitePage'
import { envelope, mockApi, renderApp } from '../../test/utils'

const ACCEPTED = { username: 'walk-approver', display_name: 'Walk Approver', role: 'approver', accepted: '2026-09-23T10:00:00Z' }

describe('passwordProblem', () => {
  it('names the one thing that is wrong, shortest first', () => {
    expect(passwordProblem('short', 'short')).toBe('Use at least 12 characters.')
    expect(passwordProblem('long-enough-password', 'something-else')).toBe('The two passwords are not the same.')
    expect(passwordProblem('long-enough-password', 'long-enough-password')).toBe('')
  })
})

describe('AcceptInvitePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a link with no token says what to do instead of showing a form', async () => {
    mockApi({ 'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session') })
    renderApp(<AcceptInvitePage />, { route: '/invite' })
    expect(await screen.findByTestId('invite-no-token')).toHaveTextContent('Open the link you were sent, or ask your admin for a new one')
    expect(screen.queryByLabelText(/^New password \*/)).not.toBeInTheDocument()
  })

  it('compares the two passwords here, then posts the token and the password and nothing else', async () => {
    const { calls } = mockApi({
      'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'),
      'POST /invitations/accept': ACCEPTED,
    })
    renderApp(<AcceptInvitePage />, { route: '/invite?token=a-one-time-token' })
    const password = await screen.findByLabelText(/^New password \*/)
    // both fields filled: the browser's own `required` is satisfied, and the page's own check
    // is what refuses a password that is too short
    await userEvent.type(password, 'too-short')
    await userEvent.type(screen.getByLabelText(/^New password again/), 'too-short')
    await userEvent.click(screen.getByRole('button', { name: 'Set my password' }))
    expect(screen.getByTestId('invite-problem')).toHaveTextContent('Use at least 12 characters.')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    await userEvent.clear(password)
    await userEvent.type(password, 'a-long-enough-password')
    await userEvent.clear(screen.getByLabelText(/^New password again/))
    await userEvent.type(screen.getByLabelText(/^New password again/), 'a-different-password')
    await userEvent.click(screen.getByRole('button', { name: 'Set my password' }))
    expect(screen.getByTestId('invite-problem')).toHaveTextContent('The two passwords are not the same.')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    await userEvent.clear(screen.getByLabelText(/^New password again/))
    await userEvent.type(screen.getByLabelText(/^New password again/), 'a-long-enough-password')
    await userEvent.click(screen.getByRole('button', { name: 'Set my password' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/invitations/accept')).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body))
    expect(body).toEqual({ token: 'a-one-time-token', password: 'a-long-enough-password' })
    // the success state names the account and its role, and the next step is to sign in
    const done = await screen.findByTestId('invite-accepted')
    expect(done).toHaveTextContent('walk-approver is now active as approver')
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
    expect(screen.queryByLabelText(/^New password \*/)).not.toBeInTheDocument()
  })

  it('a refused link renders the envelope with a title a person can act on', async () => {
    mockApi({
      'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'),
      'POST /invitations/accept': () => envelope(401, 'invalid_token', 'this invitation link is not valid: it may have been used, withdrawn or expired — ask your admin for a new one'),
    })
    renderApp(<AcceptInvitePage />, { route: '/invite?token=spent' })
    await userEvent.type(await screen.findByLabelText(/^New password \*/), 'a-long-enough-password')
    await userEvent.type(screen.getByLabelText(/^New password again/), 'a-long-enough-password')
    await userEvent.click(screen.getByRole('button', { name: 'Set my password' }))
    expect(await screen.findByText('This invitation link cannot be used')).toBeInTheDocument()
    expect(screen.getByText(/ask your admin for a new one/)).toBeInTheDocument()
    // the form is still there: the person can try the right link without reloading
    expect(screen.getByLabelText(/^New password \*/)).toBeInTheDocument()
  })
})
