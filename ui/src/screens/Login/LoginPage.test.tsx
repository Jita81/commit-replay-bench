/**
 * LoginPage — the first screen a sponsor sees explains the product in plain English.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the strapline under the brand on /login, and that its hints resolve.
 * What it does: Pins that the strapline says what the product does for a team in one
 *               sentence with no term left undefined (J-ONR-18): no "belts", no "false-Q1"
 *               before anyone has signed in to read the glossary. The form, the wrong-password
 *               envelope and the OIDC button are covered by the e2e specs named in the page.
 *               Also that a sample hint (the Sign in button) opens on hover with the
 *               registry's copy — the fields and buttons explain themselves before sign-in —
 *               and that the sentence under the form names who resets a password or
 *               reactivates an account and says it does not happen on this page. And that every
 *               stop names its way forward: a wrong password's envelope says who sets a new one
 *               (G-460), a 429 names the wait (G-189), a failed organisation sign-in shows a
 *               fixed reason for its code and never echoes an unknown one (G-188), the two
 *               `/version` states (G-191), and the session length it states.
 * How:          `mockApi` + `renderApp` with no session (`GET /auth/me` → 401).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Login/LoginPage.tsx, ui/src/help/hints.ts (the copy the
 *               hover test expects), ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Login/LoginPage.test.tsx
 * Touch when:   never for a new repository; the strapline or the recovery sentence changes,
 *               a field or button is added to the form, the callback gains a failure code, or
 *               what the page shows while the session check is in flight changes (P-324).
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { hintText } from '../../help/hints'
import { unhinted } from '../../help/hints-collector'
import { envelope, expectHintOpens, mockApi, renderApp } from '../../test/utils'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('the strapline is one plain sentence about what the product does for a team', async () => {
    mockApi({
      'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'),
      'GET /version': { version: '2.2.0', apparatus_version: '2.2', policy_version: 'routing.v1', oidc_enabled: false },
    })
    renderApp(<LoginPage />, { route: '/login' })
    await waitFor(() => expect(screen.getByRole('form', { name: 'Local account sign in' })).toBeInTheDocument())
    const strap = screen.getByText('Measures what an AI builder can be trusted to change in your repository, graded by your own tests.')
    expect(strap).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/belts|false-Q1/)
  })

  it('a person who cannot sign in is told who resets a password, and that it does not happen here', async () => {
    mockApi({
      'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'),
      'GET /version': { version: '2.2.0', apparatus_version: '2.2', policy_version: 'routing.v1', oidc_enabled: false },
    })
    renderApp(<LoginPage />, { route: '/login' })
    await waitFor(() => expect(screen.getByRole('form', { name: 'Local account sign in' })).toBeInTheDocument())
    // the way forward (who), and the non-goal (not on this page)
    expect(screen.getByText(/Forgotten your password, or locked out\?/)).toHaveTextContent('Ask an admin to reset it on the Settings screen, or ask the person who runs this deployment.')
    expect(screen.getByText(/Forgotten your password, or locked out\?/)).toHaveTextContent('Accounts are not created, reset or reactivated here.')
  })

  it('every field and both sign-in buttons carry a hint; the Sign in hint opens on hover with the registry copy', async () => {
    mockApi({
      'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'),
      'GET /version': { version: '2.2.0', apparatus_version: '2.2', policy_version: 'routing.v1', oidc_enabled: true },
    })
    const { container } = renderApp(<LoginPage />, { route: '/login' })
    await screen.findByRole('form', { name: 'Local account sign in' })
    await waitFor(() => expect(screen.getByRole('link', { name: 'Sign in with organisation account' })).toHaveAttribute('data-hint', 'button.login.oidc'))
    expect(unhinted(container)).toEqual([])
    const submit = screen.getByRole('button', { name: 'Sign in' })
    expect(submit).toHaveAttribute('data-hint', 'button.login.submit')
    await expectHintOpens(submit, 'button.login.submit')
    // a field's control lists the bubble in its own description, so focus reaches the same text
    expect(screen.getByLabelText(/^Username/)).toHaveAccessibleDescription(hintText('field.login.username'))
  })
})

const NO_SESSION = { 'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session') }
const VERSION = { version: '2.2.0', apparatus_version: '2.2', policy_version: 'routing.v1', oidc_enabled: false }

/** Fill the form and press Sign in. */
async function signIn(username = 'ann', password = 'a-long-password-1') {
  await waitFor(() => expect(screen.getByRole('form', { name: 'Local account sign in' })).toBeInTheDocument())
  fireEvent.change(screen.getByLabelText(/^Username/), { target: { value: username } })
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('LoginPage — every stop names its way forward', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a wrong password names who sets a new one, inside the envelope (G-460)', async () => {
    mockApi({ ...NO_SESSION, 'GET /version': VERSION, 'POST /auth/login': () => envelope(401, 'invalid_credentials', 'username or password is incorrect') })
    renderApp(<LoginPage />, { route: '/login' })
    await signIn()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Wrong username or password')
    expect(within(alert).getByTestId('login-next-step')).toHaveTextContent(
      'If you have forgotten your password, ask an admin of this deployment to set a new one on the Settings screen. If no admin can sign in, the person who runs the deployment sets it on the host (crb users, OPERATOR §9).',
    )
  })

  it('a sixth failure in a minute names the wait in seconds, not "Request failed" (G-189)', async () => {
    mockApi({
      ...NO_SESSION,
      'GET /version': VERSION,
      'POST /auth/login': () => envelope(429, 'rate_limited', 'too many failed logins; try again later', { retry_after_s: 42 }),
    })
    renderApp(<LoginPage />, { route: '/login' })
    await signIn()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Too many failed sign-ins')
    expect(alert).not.toHaveTextContent('Request failed')
    expect(within(alert).getByTestId('login-next-step')).toHaveTextContent('Wait 42 seconds, then try again.')
  })

  it('a wait of one second is singular', async () => {
    mockApi({ ...NO_SESSION, 'GET /version': VERSION, 'POST /auth/login': () => envelope(429, 'rate_limited', 'too many', { retry_after_s: 1 }) })
    renderApp(<LoginPage />, { route: '/login' })
    await signIn()
    expect(await screen.findByTestId('login-next-step')).toHaveTextContent('Wait 1 second, then try again.')
  })

  it.each([
    ['oidc_provider_error', 'Your organisation’s sign-in refused or cancelled the sign-in.'],
    ['oidc_state_missing', 'The sign-in started in another browser or tab, or took too long.'],
    ['oidc_state_mismatch', 'The sign-in started in another browser or tab, or took too long.'],
    ['oidc_exchange_failed', 'This deployment could not complete the sign-in with your organisation.'],
    ['account_disabled', 'Your account on this deployment is turned off.'],
    ['something_else', 'The organisation sign-in did not complete.'],
  ])('a failed organisation sign-in (%s) returns here with its reason and the form (G-188)', async (code, reason) => {
    mockApi({ ...NO_SESSION, 'GET /version': { ...VERSION, oidc_enabled: true } })
    renderApp(<LoginPage />, { route: `/login?error=${code}&next=%2Fruns` })
    const alert = await screen.findByTestId('login-oidc-error')
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert).toHaveTextContent('Organisation sign-in did not complete')
    expect(alert).toHaveTextContent(reason)
    // the code is shown as data, never as markup: an unknown code is not echoed at all
    if (code === 'something_else') expect(alert).not.toHaveTextContent('something_else')
    // the way back is right here: the form, and the organisation button keeps `next`
    expect(await screen.findByRole('form', { name: 'Local account sign in' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Sign in with organisation account' }).getAttribute('href')).toContain(encodeURIComponent('/runs')))
  })

  it('while the session check is in flight no form is offered, so a signed-in visitor types nothing the redirect throws away (P-324)', async () => {
    let answer: (r: Response) => void = () => {}
    mockApi({ 'GET /auth/me': () => new Promise<Response>((resolve) => (answer = resolve)), 'GET /version': VERSION })
    renderApp(<LoginPage />, { route: '/login' })
    expect(await screen.findByTestId('login-checking-session')).toHaveTextContent('Checking whether you are already signed in…')
    expect(screen.queryByLabelText(/^Username/)).toBeNull()
    expect(screen.queryByLabelText(/^Password/)).toBeNull()
    // the answer is "no session": the form arrives
    answer(envelope(401, 'unauthenticated', 'no session'))
    expect(await screen.findByRole('form', { name: 'Local account sign in' })).toBeInTheDocument()
    expect(screen.queryByTestId('login-checking-session')).toBeNull()
  })

  it('"Checking for an organisation sign-in…" shows while GET /version is pending (G-191)', async () => {
    mockApi({ ...NO_SESSION, 'GET /version': () => new Promise<Response>(() => {}) })
    renderApp(<LoginPage />, { route: '/login' })
    expect(await screen.findByText('Checking for an organisation sign-in…')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Sign in with organisation account' })).toBeNull()
  })

  it('a failed GET /version says so with Retry, rather than silently hiding the button (G-191)', async () => {
    let calls = 0
    mockApi({
      ...NO_SESSION,
      'GET /version': () => {
        calls += 1
        return calls === 1 ? envelope(503, 'unavailable', 'try later') : new Response(JSON.stringify({ ...VERSION, oidc_enabled: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp(<LoginPage />, { route: '/login' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not check for an organisation sign-in')
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: 'Sign in with organisation account' })).toBeInTheDocument()
  })

  it('says how long a session lasts, and that signing out ends it everywhere', async () => {
    mockApi({ ...NO_SESSION, 'GET /version': VERSION })
    renderApp(<LoginPage />, { route: '/login' })
    const line = await screen.findByTestId('login-session-note')
    expect(line).toHaveTextContent('A session lasts 8 hours unless this deployment sets another length. Signing out ends it on every device.')
    expect(document.body).not.toHaveTextContent(/expire with the browser/)
  })
})
