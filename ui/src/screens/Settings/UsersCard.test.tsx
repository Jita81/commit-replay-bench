/**
 * ui/src/screens/Settings/UsersCard.tsx — every account act on the screen, including the ones
 * the API has had since #42 and no screen offered (F23).
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Users card and its Set-password dialog against mocked
 *               `/users`, `/users/{id}/active`, `/users/{id}/password` and
 *               `/users/{id}/events`.
 * What it does: Pins the six things the gap asked for: the row shows `active` and the last
 *               sign-in as an age; the active toggle sends `PUT /users/{id}/active` and says
 *               what it did; the toggle AND the role select of the last active admin are
 *               DISABLED before they are used, with the reason in the accessible name; an
 *               identity-provider account cannot have its password set here; the Set-password
 *               dialog refuses a mismatch and a short password locally, never echoes either
 *               value, and on success names the account and says its sessions ended; a 409
 *               from the server is shown in the server's own words; and the account's `user.*`
 *               events are fetched and rendered under the row.
 * How:          `mockApi` + `renderApp` with an admin principal; `userEvent` for every act;
 *               the mutation bodies read back off `calls` so the test pins the request, not
 *               only the rendering.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/UsersCard.tsx and
 *               ui/src/screens/Settings/SetPasswordDialog.tsx (the code under test),
 *               ui/src/help/hints-collector.ts (`unhinted` — the card's own hint contract),
 *               ui/src/test/utils.tsx, tests/test_server_admin_users.py (the routes' own tests)
 * Tested by:    ui/src/screens/Settings/UsersCard.test.tsx
 * Touch when:   an account act is added — it needs a case here.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Page, StepEvent, User } from '../../api/types'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { UsersCard } from './UsersCard'

const ADA: User = { id: 'u1', username: 'ada', display_name: 'Ada', email: 'ada@example.org', role: 'admin', issuer: 'local', active: true, created: '2026-09-01T10:00:00+00:00', last_login: '2026-09-15T09:00:00+00:00' }
const LEAVER: User = { id: 'u2', username: 'cliff', display_name: 'Cliff', email: 'cliff@example.org', role: 'operator', issuer: 'local', active: true, created: '2026-09-02T10:00:00+00:00', last_login: '' }
const PROVIDED: User = { id: 'u3', username: 'sub-123', display_name: 'Dana', email: 'dana@example.org', role: 'approver', issuer: 'https://login.example/t', active: true, created: '2026-09-03T10:00:00+00:00', last_login: '2026-09-20T09:00:00+00:00' }

const EVENTS: Page<StepEvent> = {
  items: [
    { event_id: 'e2', seq: 2, trace_id: 't', step_id: 's2', parent_step_id: '', repo: '', task_id: '', error_code: '', cost_usd: null, stage: 'system', action: 'user.password_set', status: 'ok', actor: 'u1', timestamp: '2026-09-16T10:00:00+00:00', duration_ms: 0, payload: { target: 'u2', username: 'cliff', role: 'operator', active: true, by: 'admin' }, error_message: '', input_ref: '', output_ref: '' },
    { event_id: 'e1', seq: 1, trace_id: 't', step_id: 's1', parent_step_id: '', repo: '', task_id: '', error_code: '', cost_usd: null, stage: 'system', action: 'user.created', status: 'ok', actor: 'cli:paul', timestamp: '2026-09-02T10:00:00+00:00', duration_ms: 0, payload: { target: 'u2', username: 'cliff', role: 'operator', active: true }, error_message: '', input_ref: '', output_ref: '' },
  ],
  total: 2,
  limit: 50,
  offset: 0,
}

function list(...users: User[]) {
  return { items: users, total: users.length, limit: 50, offset: 0 }
}

function admin(routes: Record<string, unknown>) {
  return mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'admin' }, ...routes })
}

describe('UsersCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('every row carries the account state that decides sign-in: active, and the last sign-in as an age', async () => {
    admin({ 'GET /users': list(ADA, LEAVER) })
    const { container } = renderApp(<UsersCard />)
    await screen.findByTestId('user-active-ada')
    expect(screen.getByTestId('user-active-cliff')).toBeChecked()
    // an account that has never signed in says so, rather than showing an empty cell
    expect(screen.getByTestId('user-last-login-cliff')).toHaveTextContent('Never')
    expect(screen.getByTestId('user-last-login-ada')).toHaveTextContent(/ago$/)
    expect(unhinted(container)).toEqual([])
  })

  it('the active toggle deactivates through PUT /users/{id}/active and says what it did', async () => {
    const { calls } = admin({
      'GET /users': list(ADA, LEAVER),
      'PUT /users/u2/active': { ...LEAVER, active: false },
    })
    renderApp(<UsersCard />)
    await userEvent.click(await screen.findByTestId('user-active-cliff'))
    await waitFor(() => expect(screen.getByTestId('users-said')).toHaveTextContent('cliff is deactivated and is refused on its very next request.'))
    const put = calls.find((c) => c.method === 'PUT' && c.path === '/users/u2/active')
    expect(put).toBeDefined()
    expect(JSON.parse(String(put?.init?.body))).toEqual({ active: false })
  })

  // The walkthrough caught this as a real defect: the controlled checkbox snapped back to the row
  // still in the cache, so Playwright reported a click that did not change the state — while the
  // account it HAD deactivated stayed deactivated. The control now shows the act it sent.
  it('the toggle shows the act it sent straight away, and hands authority back when the served row agrees', async () => {
    let active = true
    admin({
      'GET /users': () => json({ items: [ADA, { ...LEAVER, active }], total: 2, limit: 50, offset: 0 }),
      'PUT /users/u2/active': () => {
        active = false
        return json({ ...LEAVER, active: false })
      },
    })
    renderApp(<UsersCard />)
    const toggle = await screen.findByTestId('user-active-cliff')
    expect(toggle).toBeChecked()
    await userEvent.click(toggle)
    // …not after a refetch: immediately, because the screen shows what it asked for
    expect(toggle).not.toBeChecked()
    await waitFor(() => expect(screen.getByTestId('users-said')).toHaveTextContent('is deactivated'))
    await waitFor(() => expect(screen.getByTestId('user-active-cliff')).not.toBeChecked())
  })

  it('a refusal puts the toggle back: the server is the one that decides', async () => {
    admin({
      'GET /users': list(ADA, { ...LEAVER, role: 'admin' }),
      'PUT /users/u1/active': () => envelope(409, 'last_admin', 'refusing to demote or deactivate the last active admin'),
    })
    renderApp(<UsersCard />)
    const toggle = await screen.findByTestId('user-active-ada')
    await userEvent.click(toggle)
    expect(await screen.findByTestId('error-state')).toHaveTextContent('last active admin')
    await waitFor(() => expect(screen.getByTestId('user-active-ada')).toBeChecked())
  })

  it('reactivating says the earlier sessions work again and how to end them', async () => {
    admin({
      'GET /users': list(ADA, { ...LEAVER, active: false }),
      'PUT /users/u2/active': { ...LEAVER, active: true },
    })
    renderApp(<UsersCard />)
    await userEvent.click(await screen.findByTestId('user-active-cliff'))
    await waitFor(() => expect(screen.getByTestId('users-said')).toHaveTextContent(/is active again and can sign in.*set a password to end them/))
  })

  it('the last active admin cannot be deactivated or demoted: both controls are disabled before they are used, and say why', async () => {
    admin({ 'GET /users': list(ADA, LEAVER) })
    renderApp(<UsersCard />)
    const toggle = await screen.findByTestId('user-active-ada')
    expect(toggle).toBeDisabled()
    expect(toggle).toHaveAccessibleName(/last active admin.*activate or create a second admin first/)
    const role = screen.getByTestId('user-role-ada')
    expect(role).toBeDisabled()
    expect(role).toHaveAccessibleName(/last active admin/)
    // …and a second active admin releases both
    expect(screen.getByTestId('user-active-cliff')).toBeEnabled()
  })

  it('with two active admins nothing is guarded', async () => {
    admin({ 'GET /users': list(ADA, { ...LEAVER, role: 'admin' }) })
    renderApp(<UsersCard />)
    expect(await screen.findByTestId('user-active-ada')).toBeEnabled()
    expect(screen.getByTestId('user-role-ada')).toBeEnabled()
  })

  it('a role change says the new role, naming the account', async () => {
    admin({ 'GET /users': list(ADA, LEAVER), 'PUT /users/u2/role': { ...LEAVER, role: 'approver' } })
    renderApp(<UsersCard />)
    await userEvent.selectOptions(await screen.findByTestId('user-role-cliff'), 'approver')
    await waitFor(() => expect(screen.getByTestId('users-said')).toHaveTextContent('Role of cliff is now approver.'))
  })

  it('an identity-provider account has no password to set here, and its kind says so', async () => {
    admin({ 'GET /users': list(ADA, PROVIDED) })
    renderApp(<UsersCard />)
    expect(await screen.findByTestId('user-set-password-sub-123')).toBeDisabled()
    // …while a local account, whose password this deployment holds, can have one set
    expect(screen.getByTestId('user-set-password-ada')).toBeEnabled()
    const kinds = screen.getAllByRole('img', { name: /: (local account|managed by your identity provider)$/ })
    expect(kinds.map((k) => k.textContent)).toEqual(['local', 'oidc'])
  })

  it('the Set-password dialog refuses a short password and a mismatch before it asks the server', async () => {
    const { calls } = admin({ 'GET /users': list(ADA, LEAVER) })
    renderApp(<UsersCard />)
    await userEvent.click(await screen.findByTestId('user-set-password-cliff'))
    const form = await screen.findByTestId('set-password-form')
    await userEvent.type(within(form).getByTestId('set-password-new'), 'short')
    await userEvent.type(within(form).getByTestId('set-password-again'), 'short')
    await userEvent.click(within(form).getByTestId('set-password-submit'))
    expect(await screen.findByTestId('set-password-refused')).toHaveTextContent('Use at least 12 characters.')
    await userEvent.clear(within(form).getByTestId('set-password-new'))
    await userEvent.type(within(form).getByTestId('set-password-new'), 'a-long-enough-password')
    await userEvent.click(within(form).getByTestId('set-password-submit'))
    expect(await screen.findByTestId('set-password-refused')).toHaveTextContent('The two passwords are not the same.')
    expect(calls.filter((c) => c.method === 'PUT')).toEqual([])
  })

  it('a set password is never echoed, and the success state names the account and says its sessions ended', async () => {
    const pw = 'a-long-enough-password'
    const { calls } = admin({ 'GET /users': list(ADA, LEAVER), 'PUT /users/u2/password': LEAVER })
    const { container } = renderApp(<UsersCard />)
    await userEvent.click(await screen.findByTestId('user-set-password-cliff'))
    const form = await screen.findByTestId('set-password-form')
    const first = within(form).getByTestId('set-password-new')
    expect(first).toHaveAttribute('type', 'password')
    expect(within(form).getByTestId('set-password-again')).toHaveAttribute('type', 'password')
    await userEvent.type(first, pw)
    await userEvent.type(within(form).getByTestId('set-password-again'), pw)
    await userEvent.click(within(form).getByTestId('set-password-submit'))
    const done = await screen.findByTestId('set-password-done')
    expect(done).toHaveAttribute('role', 'status')
    expect(done).toHaveTextContent('Password set for cliff. Every session that account held has ended — it signs in again with the new password.')
    // the value left the browser once, in the body, and is nowhere in the page or in a field
    expect(JSON.parse(String(calls.find((c) => c.path === '/users/u2/password')?.init?.body))).toEqual({ password: pw })
    expect(container.textContent ?? '').not.toContain(pw)
    expect(first).toHaveValue('')
  })

  it('closing the dialog clears the success, so the next account is never greeted with the last one’s name', async () => {
    const pw = 'a-long-enough-password'
    admin({ 'GET /users': list(ADA, LEAVER), 'PUT /users/u2/password': LEAVER })
    renderApp(<UsersCard />)
    await userEvent.click(await screen.findByTestId('user-set-password-cliff'))
    let form = await screen.findByTestId('set-password-form')
    await userEvent.type(within(form).getByTestId('set-password-new'), pw)
    await userEvent.type(within(form).getByTestId('set-password-again'), pw)
    await userEvent.click(within(form).getByTestId('set-password-submit'))
    await screen.findByTestId('set-password-done')
    await userEvent.click(within(form).getByRole('button', { name: 'Close' }))
    await userEvent.click(screen.getByTestId('user-set-password-ada'))
    form = await screen.findByTestId('set-password-form')
    expect(within(form).queryByTestId('set-password-done')).toBeNull()
  })

  it('a 409 from the server is shown in the server’s own words', async () => {
    admin({
      'GET /users': list(ADA, LEAVER),
      'PUT /users/u2/password': () => envelope(409, 'not_local', "this account signs in through the organisation's identity provider; change its password there"),
    })
    renderApp(<UsersCard />)
    // the screen reads `issuer` from the list it fetched; when that copy is stale the server is
    // the one that decides, and its refusal is shown in its own words rather than swallowed
    await userEvent.click(await screen.findByTestId('user-set-password-cliff'))
    const form = await screen.findByTestId('set-password-form')
    await userEvent.type(within(form).getByTestId('set-password-new'), 'a-long-enough-password')
    await userEvent.type(within(form).getByTestId('set-password-again'), 'a-long-enough-password')
    await userEvent.click(within(form).getByTestId('set-password-submit'))
    expect(await screen.findByTestId('error-state')).toHaveTextContent('change its password there')
  })

  it('the account’s own user.* events are served and shown, with the actor who made each change', async () => {
    admin({ 'GET /users': list(ADA, LEAVER), 'GET /users/u2/events': EVENTS })
    renderApp(<UsersCard />)
    await userEvent.click(await screen.findByTestId('user-history-cliff'))
    const history = await screen.findByTestId('account-history')
    expect(history).toHaveTextContent('History for cliff')
    const rows = within(history).getAllByTestId('account-history-event')
    expect(rows.map((r) => r.getAttribute('data-action'))).toEqual(['user.password_set', 'user.created'])
    expect(rows[0]).toHaveTextContent('by u1')
    // a change made on the API host names the operating-system user who made it
    expect(rows[1]).toHaveTextContent('by cli:paul')
  })

  it('the card says what it does not do, and where recovery lives when nobody can sign in', async () => {
    admin({ 'GET /users': list(ADA) })
    renderApp(<UsersCard />)
    const notHere = await screen.findByTestId('users-not-here')
    expect(notHere).toHaveTextContent('no email reset, no self-service unlock and no security questions')
    expect(notHere).toHaveTextContent('crb users')
    expect(within(notHere).getByRole('link', { name: 'Users, and what to do when nobody can sign in' })).toHaveAttribute('href', '/help/docs/OPERATOR#9-users')
  })

  it('a created account is named, with the role it got', async () => {
    admin({ 'GET /users': list(ADA), 'POST /users': { ...LEAVER, role: 'approver' } })
    renderApp(<UsersCard />)
    await userEvent.type(await screen.findByLabelText(/^Username/), 'cliff')
    await userEvent.type(screen.getByLabelText(/^Display name/), 'Cliff')
    await userEvent.type(screen.getByLabelText(/^Email/), 'cliff@example.org')
    await userEvent.type(screen.getByLabelText(/^Initial password/), 'a-long-enough-password')
    await userEvent.click(screen.getByRole('button', { name: 'Create local user' }))
    await waitFor(() => expect(screen.getByTestId('users-created')).toHaveTextContent('Account cliff created as approver. It can sign in now with the password you typed.'))
  })
})
