/**
 * NotFoundPage — an unknown path stays on the journey.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the catch-all screen.
 * What it does: Pins that the requested path is shown and the one way back is Home, never
 *               the legacy repository list.
 * How:          `renderApp` at an unknown path.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/NotFoundPage.tsx (under test)
 * Tested by:    ui/src/screens/NotFoundPage.test.tsx
 * Touch when:   the way back changes.
 */
import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../test/utils'
import { NotFoundPage } from './NotFoundPage'

describe('NotFoundPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the path and leads back to Home', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL })
    renderApp(<NotFoundPage />, { route: '/nowhere/at/all' })
    expect(await screen.findByText('/nowhere/at/all')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Home' })).toHaveAttribute('href', '/home')
    expect(screen.queryByRole('link', { name: 'Back to repos' })).toBeNull()
  })
})
