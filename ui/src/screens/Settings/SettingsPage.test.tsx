/**
 * ui/src/screens/Settings/SettingsPage.tsx — the admin's three setup jobs each link their guide.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Settings page as an admin against mocked health, version,
 *               settings, users, secrets and GitHub App routes.
 * What it does: Pins that the Users card links the sign-in and roles guide through the
 *               bundled docs, beside the GitHub App and builder-token cards' own links
 *               (J-HEL-20), and that the eyebrow names the instrument row.
 * How:          `mockApi` + `renderApp` at `/settings`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Settings/SettingsPage.test.tsx
 * Touch when:   a setup card is added.
 */
import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { SettingsPage } from './SettingsPage'

describe('SettingsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('the Users card links the sign-in and roles guide; the eyebrow names the instrument row (J-HEL-20)', async () => {
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
    expect(screen.getByText('Instrument · Settings')).toBeInTheDocument()
  })
})
