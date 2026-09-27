/**
 * auth.tsx — `RequireAuth` sends a signed-out reader to sign-in carrying the whole address.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `RequireAuth`'s redirect.
 * What it does: Pins that a definite "no session" on a protected address lands on
 *               `/login?next=` with the path, the query AND the fragment, so a link to a guide's
 *               section (`/help/docs/OPERATOR#9-users`) opens at that section after signing in
 *               rather than at the top of the guide.
 * How:          A `MemoryRouter` with `/login` (which prints its `next`) and a protected
 *               catch-all under `AuthProvider`; `mockApi` answers `/auth/me` with 401.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/auth.tsx (`RequireAuth`), ui/src/screens/Login/LoginPage.tsx
 *               (`safeNext` reads the `next` this writes), ui/src/App.tsx (the routes it guards)
 * Tested by:    ui/src/lib/auth.test.tsx
 * Touch when:   never for a new repository; the redirect's `next` changes shape.
 */
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { envelope, mockApi } from '../test/utils'
import { AuthProvider, RequireAuth } from './auth'

function ShowNext() {
  const [params] = useSearchParams()
  return <p data-testid="next">{params.get('next')}</p>
}

describe('RequireAuth', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('carries the path, the query and the fragment into next, so a section link survives signing in', async () => {
    mockApi({ 'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session') })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/help/docs/OPERATOR?from=login#9-users']}>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<ShowNext />} />
              <Route path="*" element={<RequireAuth>protected</RequireAuth>} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByTestId('next')).toHaveTextContent('/help/docs/OPERATOR?from=login#9-users')
  })
})
