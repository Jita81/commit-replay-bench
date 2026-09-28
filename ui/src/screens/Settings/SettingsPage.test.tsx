/**
 * ui/src/screens/Settings/SettingsPage.tsx — the admin's three setup jobs each link their guide.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Settings page as an admin against mocked health, version,
 *               settings, users, secrets and GitHub App routes.
 * What it does: Pins that the Users card links the sign-in and roles guide through the
 *               bundled docs, beside the GitHub App and builder-token cards' own links
 *               (J-HEL-20); that the eyebrow names the go-live journey and its step; and that
 *               the About block opens the go-live checklist (DEPLOYMENT §8) and OPERATOR
 *               §9; and that every form on the page is named once, so the Users card and
 *               the invitation card — which both ask for a Username — are told apart by a
 *               screen reader and a test (P-323).
 * How:          `mockApi` + `renderApp` at `/settings`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Settings/SettingsPage.test.tsx
 * Touch when:   never for a new repository; a setup card or a form is added.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AboutThisScreen } from '../../components/Help'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { SettingsPage } from './SettingsPage'

describe('SettingsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('the Users card links the sign-in and roles guide; the eyebrow names the go-live journey and its step (J-HEL-20)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /health': { status: 'ok', probes: [] },
      'GET /version': { crb: '0.1', apparatus: '2.2', policy: 'routing.v1' },
      'GET /settings': { sandbox_mode: 'docker', ledger_backend: 'sqlite', builders: {}, retention: {} },
      'GET /users': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /settings/secrets': { items: [], secrets_dir: '' },
      'GET /github/app': { configured: false, app_slug: '', api_url: '', install_url: '', installations: [] },
    })
    renderApp(<SettingsPage />, { route: '/settings' })
    expect(await screen.findByRole('link', { name: 'How sign-in and roles work' })).toHaveAttribute('href', '/help/docs/SECURITY#34-authentication-and-authorisation--crbserverauth')
    expect(screen.getByText('Run the platform · Deploy and go live · 2 of 4 · Settings')).toBeInTheDocument()
  })

  it('the About block opens the go-live checklist and the users guide, and names the attestations (G-316)', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'admin' } })
    renderApp(<AboutThisScreen />, { route: '/settings', path: '/settings' })
    const about = await screen.findByTestId('about-this-screen')
    await waitFor(() => expect(about).toHaveTextContent('Go-live attestations'))
    expect(within(about).getByRole('link', { name: 'The go-live checklist' })).toHaveAttribute('href', '/help/docs/DEPLOYMENT#8-go-live-checklist')
    expect(within(about).getByRole('link', { name: 'Record what only you can prove' })).toHaveAttribute('href', '/help/docs/DEPLOYMENT#81-record-what-only-you-can-prove')
    expect(within(about).getByRole('link', { name: 'Users, and what to do when nobody can sign in' })).toHaveAttribute('href', '/help/docs/OPERATOR#9-users')
  })
  it('two cards that both ask for a Username are told apart: every form is named, once, and a repeated label never sits outside one (P-323)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /health': { status: 'ok', probes: [] },
      'GET /version': { crb: '0.1', apparatus: '2.2', policy: 'routing.v1' },
      'GET /settings': { sandbox_mode: 'docker', ledger_backend: 'sqlite', builders: {}, retention: {} },
      'GET /users': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /settings/secrets': { items: [], secrets_dir: '' },
      'GET /github/app': { configured: false, app_slug: '', api_url: '', install_url: '', installations: [] },
      'GET /invitations': { items: [], total: 0, limit: 50, offset: 0 },
      'GET /two-person-readiness': { ready: false, reason_code: 'single_person', reason: 'only one account', approvers_active: 1, approvers_signed_in: 1, other_active_accounts: 0, accounts_signed_in: 1, invitations_pending: 0 },
    })
    renderApp(<SettingsPage />, { route: '/settings' })
    await waitFor(() => expect(screen.getByRole('form', { name: 'Create a local user' })).toBeInTheDocument())
    expect(screen.getByRole('form', { name: 'Invite an approver' })).toBeInTheDocument()
    const forms = Array.from(document.querySelectorAll('form'))
    const names = forms.map((f) => f.getAttribute('aria-label') ?? '')
    // every form carries its own name, and no two share one
    expect(names.filter((n) => n === '')).toEqual([])
    expect(new Set(names).size).toBe(names.length)
    // a label used more than once on the page is inside a named form each time
    const labels = Array.from(document.querySelectorAll('label')).map((l) => (l.textContent ?? '').replace(/\s*\*$/, '').trim())
    const repeated = labels.filter((l, i) => l && labels.indexOf(l) !== i)
    expect(repeated.length).toBeGreaterThan(0) // Username, Display name, Email, Role: the reason for the rule
    for (const l of document.querySelectorAll('label')) {
      const text = (l.textContent ?? '').replace(/\s*\*$/, '').trim()
      if (repeated.includes(text)) expect(l.closest('form[aria-label]'), `the "${text}" field is outside a named form`).not.toBeNull()
    }
  })
})
