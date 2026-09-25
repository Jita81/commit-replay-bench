/**
 * NotFoundPage — an unknown path stays on the journey.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the catch-all screen.
 * What it does: Pins that the requested path is shown and the one way back is Home, never
 *               the legacy repository list; that the address shown is the whole address asked
 *               for (query string and hash included, G-197); and that the page names why an
 *               address fails, what to do, and what it will not do (G-196).
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

  it('shows the whole address asked for — the query string and the hash too', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL })
    renderApp(<NotFoundPage />, { route: '/runs/abc/log?tab=patch#L12' })
    expect(await screen.findByTestId('notfound-address')).toHaveTextContent(/^\/runs\/abc\/log\?tab=patch#L12$/)
  })

  it('says why the address failed, what to do, and what the page will not do', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL })
    renderApp(<NotFoundPage />, { route: '/nowhere/at/all' })
    const cause = await screen.findByTestId('notfound-cause')
    // the causes: typed or copied wrongly; a link from an older version; a run or task deleted
    expect(cause).toHaveTextContent('If you typed or copied the address, check it for a mistake and try again.')
    expect(cause).toHaveTextContent('an older version of this product')
    expect(cause).toHaveTextContent('a run or task that has since been deleted')
    // and the move for a followed link: where to start, and who to tell
    expect(cause).toHaveTextContent('start from Home, or look for the run on Runs, and tell whoever sent you the link.')
    expect(screen.getByTestId('notfound-nongoal')).toHaveTextContent('This page does not search for what you meant, guess a near match or report the broken link to anyone.')
  })
})
