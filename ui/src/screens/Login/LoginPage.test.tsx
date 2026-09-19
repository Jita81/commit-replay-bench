/**
 * LoginPage — the first screen a sponsor sees explains the product in plain English.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the strapline under the brand on /login.
 * What it does: Pins that the strapline says what the product does for a team in one
 *               sentence with no term left undefined (J-ONR-18): no "belts", no "false-Q1"
 *               before anyone has signed in to read the glossary. The form, the wrong-password
 *               envelope and the OIDC button are covered by the e2e specs named in the page.
 * How:          `mockApi` + `renderApp` with no session (`GET /auth/me` → 401).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Login/LoginPage.tsx
 * Tested by:    ui/src/screens/Login/LoginPage.test.tsx
 * Touch when:   the strapline changes.
 */

import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { envelope, mockApi, renderApp } from '../../test/utils'
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
})
