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
 *               the About block opens the go-live checklist (DEPLOYMENT §8) and OPERATOR §9.
 * How:          `mockApi` + `renderApp` at `/settings`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Settings/SettingsPage.test.tsx
 * Touch when:   a setup card is added.
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
})
