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
 *               reactivates an account and says it does not happen on this page.
 * How:          `mockApi` + `renderApp` with no session (`GET /auth/me` → 401).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Login/LoginPage.tsx, ui/src/help/hints.ts (the copy the
 *               hover test expects), ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Login/LoginPage.test.tsx
 * Touch when:   the strapline or the recovery sentence changes, or a field or button is
 *               added to the form.
 */

import { screen, waitFor } from '@testing-library/react'
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
    await waitFor(() => expect(screen.getByRole('link', { name: 'Sign in with organisation account' })).toHaveAttribute('data-hint', 'button.login.oidc'))
    expect(unhinted(container)).toEqual([])
    const submit = screen.getByRole('button', { name: 'Sign in' })
    expect(submit).toHaveAttribute('data-hint', 'button.login.submit')
    await expectHintOpens(submit, 'button.login.submit')
    // a field's control lists the bubble in its own description, so focus reaches the same text
    expect(screen.getByLabelText(/^Username/)).toHaveAccessibleDescription(hintText('field.login.username'))
  })
})
