/**
 * ui/src/screens/Settings/ChangeMyPasswordCard.tsx — the self-service door of the
 * recover-an-account journey, on the screen (F23).
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the "Change my password" card against a mocked
 *               `PUT /users/me/password` and the two kinds of signed-in account.
 * What it does: Pins that a local account gets the three fields, that the current password is
 *               sent with the new one, that neither is echoed, that the success state says
 *               this browser stays signed in while every other session ends, that a wrong
 *               current password and the 429 rate limit are shown in the server's own words
 *               (with the seconds to wait), and that an identity-provider account gets one
 *               sentence and no form.
 * How:          `mockApi` + `renderApp` with the principal's `issuer` deciding the state.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/ChangeMyPasswordCard.tsx (the code under test),
 *               ui/src/test/utils.tsx, tests/test_server_admin_users.py (the route's own tests)
 * Tested by:    ui/src/screens/Settings/ChangeMyPasswordCard.test.tsx
 * Touch when:   the limiter or the password floor changes — the hints state both.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { ChangeMyPasswordCard } from './ChangeMyPasswordCard'

const ME = { ...PRINCIPAL, id: 'u1', display_name: 'Ada', email: 'ada@example.org', role: 'operator' as const, issuer: 'local' }
const OUT = { id: 'u1', username: 'ada', display_name: 'Ada', email: 'ada@example.org', role: 'operator', issuer: 'local', active: true, created: 'x', last_login: 'y' }

const CURRENT = 'the-current-password'
const NEXT = 'a-brand-new-password'

async function fill(current: string, next: string, again: string) {
  await userEvent.type(await screen.findByTestId('my-password-current'), current)
  await userEvent.type(screen.getByTestId('my-password-new'), next)
  await userEvent.type(screen.getByTestId('my-password-again'), again)
  await userEvent.click(screen.getByTestId('my-password-submit'))
}

describe('ChangeMyPasswordCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('changes the password, echoes neither value, and says this browser stays signed in while every other session ends', async () => {
    const { calls } = mockApi({ 'GET /auth/me': ME, 'PUT /users/me/password': OUT })
    const { container } = renderApp(<ChangeMyPasswordCard />)
    for (const id of ['my-password-current', 'my-password-new', 'my-password-again']) {
      expect(await screen.findByTestId(id), id).toHaveAttribute('type', 'password')
    }
    await fill(CURRENT, NEXT, NEXT)
    const done = await screen.findByTestId('my-password-done')
    expect(done).toHaveAttribute('role', 'status')
    expect(done).toHaveTextContent('Your password is changed. This browser is still signed in as Ada; every other session of your account has ended.')
    expect(JSON.parse(String(calls.find((c) => c.path === '/users/me/password')?.init?.body))).toEqual({ current_password: CURRENT, new_password: NEXT })
    expect(container.textContent ?? '').not.toContain(NEXT)
    expect(screen.getByTestId('my-password-current')).toHaveValue('')
    expect(unhinted(container)).toEqual([])
  })

  it('a short new password and a mismatch are refused before the server is asked', async () => {
    const { calls } = mockApi({ 'GET /auth/me': ME })
    renderApp(<ChangeMyPasswordCard />)
    await fill(CURRENT, 'short', 'short')
    expect(await screen.findByTestId('my-password-refused')).toHaveTextContent('Use at least 12 characters for the new password.')
    await userEvent.clear(screen.getByTestId('my-password-new'))
    await userEvent.type(screen.getByTestId('my-password-new'), NEXT)
    await userEvent.click(screen.getByTestId('my-password-submit'))
    expect(await screen.findByTestId('my-password-refused')).toHaveTextContent('The two new passwords are not the same.')
    expect(calls.filter((c) => c.method === 'PUT')).toEqual([])
  })

  it('a wrong current password is the server’s sentence, not a guess', async () => {
    mockApi({ 'GET /auth/me': ME, 'PUT /users/me/password': () => envelope(401, 'invalid_credentials', 'current password is incorrect') })
    renderApp(<ChangeMyPasswordCard />)
    await fill('wrong-one-entirely', NEXT, NEXT)
    expect(await screen.findByTestId('error-state')).toHaveTextContent('current password is incorrect')
    expect(screen.queryByTestId('my-password-done')).toBeNull()
  })

  it('five wrong attempts in a minute are refused with the seconds to wait', async () => {
    mockApi({ 'GET /auth/me': ME, 'PUT /users/me/password': () => envelope(429, 'rate_limited', 'too many failed attempts; try again later', { retry_after_s: 47 }) })
    renderApp(<ChangeMyPasswordCard />)
    await fill('wrong-one-entirely', NEXT, NEXT)
    const err = await screen.findByTestId('error-state')
    expect(err).toHaveTextContent('too many failed attempts')
    await waitFor(() => expect(err).toHaveTextContent('47'))
  })

  it('an identity-provider account is told its password is managed there, and gets no form', async () => {
    mockApi({ 'GET /auth/me': { ...ME, issuer: 'https://login.example/t' } })
    renderApp(<ChangeMyPasswordCard />)
    expect(await screen.findByTestId('my-password-oidc')).toHaveTextContent('This account is managed by your identity provider.')
    expect(screen.queryByTestId('my-password-form')).toBeNull()
  })
})
