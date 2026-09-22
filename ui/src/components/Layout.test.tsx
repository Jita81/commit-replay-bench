/**
 * Layout.tsx — the journey steps are one constant, the eyebrow derives from the route, the
 * shell carries Help and the About block.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the shell's exported `JOURNEY_STEPS` / `journeyEyebrow` and its chrome.
 * What it does: Pins the four steps (Connection, Baseline, Decisions, Factory), the eyebrow
 *               grammar (`Journey · 2 of 4 · Baseline`, an optional sub, `Journey · start` on
 *               Home, empty for an instrument route), that the top bar and footer link to
 *               /help for a viewer with hints and no hover title, and that the About block
 *               renders once under the page content.
 * How:          Pure calls for the helper; the shell rendered as a layout route with one
 *               child screen for the chrome.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Layout.tsx, ui/src/components/Help.tsx
 * Tested by:    ui/src/components/Layout.test.tsx
 * Touch when:   a journey step is added or the shell's chrome changes.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../lib/auth'
import { PRINCIPAL, mockApi } from '../test/utils'
import { JOURNEY_STEPS, Layout, journeyEyebrow } from './Layout'

/** The shell as the app mounts it: a layout route with one child screen. */
function renderShell(route: string, path: string, screenEl: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path={path} element={screenEl} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('journeyEyebrow', () => {
  it('the four steps, in order', () => {
    expect(JOURNEY_STEPS.map((s) => s.label)).toEqual(['Connection', 'Baseline', 'Decisions', 'Factory'])
    expect(JOURNEY_STEPS.map((s) => s.to)).toEqual(['/connect', '/results', '/decisions', '/factory'])
  })

  it('derives "Journey · n of 4 · Step" from the pathname, with an optional sub', () => {
    expect(journeyEyebrow('/connect')).toBe('Journey · 1 of 4 · Connection')
    expect(journeyEyebrow('/connect/cobra')).toBe('Journey · 1 of 4 · Connection')
    expect(journeyEyebrow('/connect/cobra/measure', 'task 5 of 8 · this step spends money')).toBe('Journey · 1 of 4 · Connection · task 5 of 8 · this step spends money')
    expect(journeyEyebrow('/results')).toBe('Journey · 2 of 4 · Baseline')
    expect(journeyEyebrow('/decisions')).toBe('Journey · 3 of 4 · Decisions')
    expect(journeyEyebrow('/signoff')).toBe('Journey · 3 of 4 · Decisions · sign-off')
    expect(journeyEyebrow('/factory')).toBe('Journey · 4 of 4 · Factory')
    expect(journeyEyebrow('/home')).toBe('Journey · start')
  })

  it('is empty for a route that is not a journey step', () => {
    for (const p of ['/posture', '/runs', '/runs/x', '/capability', '/ledger', '/settings', '/help', '/nowhere']) expect(journeyEyebrow(p), p).toBe('')
  })
})

describe('Layout', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('links to Help from the top bar and the footer, and mounts the About block once under the content', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /health': { status: 'ok', probes: [] },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
      'GET /decisions': { items: [] },
    })
    renderShell('/results', '/results', <h1>Baseline</h1>)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const banner = screen.getByRole('banner')
    const help = within(banner).getByRole('link', { name: 'Help' })
    expect(help).toHaveAttribute('href', '/help')
    // explained by a hint, never a hover-only title
    expect(help).toHaveAttribute('data-hint', 'nav.help')
    expect(help).not.toHaveAttribute('title')
    expect(within(banner).getByRole('button', { name: /Switch theme/ })).not.toHaveAttribute('title')
    expect(within(banner).getByRole('link', { name: 'Baseline' })).toHaveAttribute('data-hint', 'nav.baseline')
    const footer = screen.getByRole('contentinfo')
    expect(within(footer).getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help')
    expect(within(footer).getByRole('link', { name: 'Glossary' })).toHaveAttribute('href', '/help#terms')
    const main = screen.getByRole('main')
    expect(within(main).getAllByTestId('about-this-screen')).toHaveLength(1)
    expect(main).toHaveTextContent('This is the baseline the factory runs on.')
    // the About block sits under the page content
    expect(main.firstElementChild).toHaveTextContent('Baseline')
    expect(main.lastElementChild).toHaveAttribute('data-testid', 'about-this-screen')
  })
})
