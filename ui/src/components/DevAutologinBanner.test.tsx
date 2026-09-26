/**
 * DevAutologinBanner.tsx and the automatic sign-in in `useMe` — a development stack that signs
 * a browser on its own machine in says so on every page, and sign-out still means something.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the automatic-sign-in banner and for the sign-in `useMe` attempts
 *               when `/auth/me` says there is no session.
 * What it does: Pins that the banner renders — with its hint and the exact sentence — in the
 *               shell and on the sign-in page when `GET /version` reports `dev_autologin`,
 *               and renders nothing when it does not; that a visitor with no session is
 *               signed in through `POST /auth/dev-autologin` and lands on the screen, never on
 *               the form; that nothing is posted when the setting is off; and that after
 *               Sign out the same page load shows the sign-in form instead of signing straight
 *               back in.
 * How:          `mockApi` routes for `/auth/me`, `/version`, `/health` and the autologin POST;
 *               the shell as a layout route and the login page on `/login`; `resetDevAutologin`
 *               between tests stands in for a fresh page load.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0027-dev-autologin-on-loopback.md
 * Works with:   ui/src/components/DevAutologinBanner.tsx, ui/src/api/hooks.ts (`useMe`,
 *               `useLogout`, `resetDevAutologin`), ui/src/components/Layout.tsx,
 *               ui/src/screens/Login/LoginPage.tsx, ui/src/help/hints.ts
 *               (`banner.shell.dev_autologin`)
 * Tested by:    ui/src/components/DevAutologinBanner.test.tsx
 * Touch when:   the banner's sentence changes (docs/OPERATOR.md quotes it) or the conditions
 *               under which the UI asks for an automatic sign-in change.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetDevAutologin } from '../api/hooks'
import { AuthProvider, RequireAuth } from '../lib/auth'
import { LoginPage } from '../screens/Login/LoginPage'
import { PRINCIPAL, envelope, mockApi } from '../test/utils'
import { DEV_AUTOLOGIN_SENTENCE } from './DevAutologinBanner'
import { Layout } from './Layout'

const VERSION_ON = { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false, dev_autologin: true }
const VERSION_OFF = { ...VERSION_ON, dev_autologin: false }
const HEALTH = { status: 'ok', probes: [] }

/** The app's shape: /login outside the shell, everything else behind the guard. */
function renderApp(route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route path="/results" element={<h1>Baseline</h1>} />
              {/* where the login page sends a stale session after Sign out; the guard sends it back */}
              <Route path="/home" element={<h1>Home</h1>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => resetDevAutologin())
afterEach(() => vi.unstubAllGlobals())

describe('the automatic sign-in banner', () => {
  it('shows on every shell page, hinted, while automatic sign-in is on', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /version': VERSION_ON, 'GET /health': HEALTH, 'GET /repos': { items: [] } })
    const { container } = renderApp('/results')
    const banner = await screen.findByTestId('dev-autologin-banner')
    expect(banner).toHaveTextContent(DEV_AUTOLOGIN_SENTENCE)
    expect(DEV_AUTOLOGIN_SENTENCE).toBe('Automatic sign-in is on for this development stack — never use in production')
    expect(container.querySelector('[data-hint="banner.shell.dev_autologin"]')).not.toBeNull()
  })

  it('shows on the sign-in page too', async () => {
    mockApi({ 'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'), 'GET /version': VERSION_ON, 'POST /auth/dev-autologin': () => envelope(403, 'dev_autologin_unavailable', 'x') })
    renderApp('/login')
    expect(await screen.findByTestId('dev-autologin-banner')).toHaveTextContent(DEV_AUTOLOGIN_SENTENCE)
  })

  it('renders nothing while it is off', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /version': VERSION_OFF, 'GET /health': HEALTH, 'GET /repos': { items: [] } })
    renderApp('/results')
    await screen.findByRole('heading', { name: 'Baseline' })
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    expect(screen.queryByTestId('dev-autologin-banner')).toBeNull()
  })
})

describe('the automatic sign-in', () => {
  it('a visitor with no session is signed in and lands on the screen, never the form', async () => {
    let signedIn = false
    const { calls } = mockApi({
      'GET /auth/me': () => (signedIn ? new Response(JSON.stringify(PRINCIPAL), { status: 200, headers: { 'Content-Type': 'application/json' } }) : envelope(401, 'unauthenticated', 'no session')),
      'GET /version': VERSION_ON,
      'GET /health': HEALTH,
      'GET /repos': { items: [] },
      'POST /auth/dev-autologin': () => {
        signedIn = true
        return new Response(JSON.stringify(PRINCIPAL), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp('/results')
    expect(await screen.findByRole('heading', { name: 'Baseline' })).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Local account sign in' })).toBeNull()
    expect(calls.filter((c) => c.method === 'POST' && c.path === '/auth/dev-autologin')).toHaveLength(1)
  })

  it('nothing is posted while it is off: the visitor gets the sign-in form', async () => {
    const { calls } = mockApi({ 'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'), 'GET /version': VERSION_OFF })
    renderApp('/results')
    expect(await screen.findByRole('form', { name: 'Local account sign in' })).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/dev-autologin')).toBe(false)
  })

  it('after Sign out the same page load shows the form instead of signing straight back in', async () => {
    let session = true
    const { calls } = mockApi({
      'GET /auth/me': () => (session ? new Response(JSON.stringify(PRINCIPAL), { status: 200, headers: { 'Content-Type': 'application/json' } }) : envelope(401, 'unauthenticated', 'no session')),
      'GET /version': VERSION_ON,
      'GET /health': HEALTH,
      'GET /repos': { items: [] },
      'POST /auth/logout': () => {
        session = false
        return new Response(null, { status: 204 })
      },
      'POST /auth/dev-autologin': () => {
        session = true
        return new Response(JSON.stringify(PRINCIPAL), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp('/results')
    await screen.findByRole('heading', { name: 'Baseline' })
    await userEvent.click(await screen.findByRole('button', { name: /sign out/i }))
    // the shell may bounce once through the guard on its way out, so wait for the form to settle
    await waitFor(() => {
      expect(screen.getByRole('form', { name: 'Local account sign in' })).toBeInTheDocument()
      expect(screen.getByTestId('dev-autologin-banner')).toBeInTheDocument()
    })
    expect(calls.some((c) => c.path === '/auth/dev-autologin')).toBe(false)
  })
})
