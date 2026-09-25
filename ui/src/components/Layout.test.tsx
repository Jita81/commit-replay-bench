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
 *               /help for a viewer with hints and no hover title, that the About block
 *               renders once under the page content, and the phone "Menu" disclosure (F26):
 *               it controls the chrome cluster and both nav rows, folds them below 640 px
 *               while closed, opens and closes with `aria-expanded`, closes on Escape with
 *               focus back on the button (after a first Escape closed a hint bubble, never on
 *               the same press) and on following a link inside it. jsdom applies no CSS, so
 *               the fold is asserted as the `max-sm:hidden` class; the 375-px walkthrough
 *               (11-screens) asserts what a phone actually shows.
 * How:          Pure calls for the helper; the shell rendered as a layout route with one
 *               child screen for the chrome.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Layout.tsx, ui/src/components/Help.tsx,
 *               ui/src/components/Hint.tsx (the menu button's hint spends the first Escape),
 *               ui/e2e/walkthrough/11-screens.spec.ts (the same menu at 375 px in Chromium)
 * Tested by:    ui/src/components/Layout.test.tsx
 * Touch when:   a journey step is added or the shell's chrome changes.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../lib/auth'
import { PRINCIPAL, mockApi } from '../test/utils'
import { JOURNEY_STEPS, Layout, SHELL_MENU_IDS, journeyEyebrow } from './Layout'

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

describe('Layout: the phone menu (F26)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const API = {
    'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
    'GET /health': { status: 'ok', probes: [] },
    'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
    'GET /decisions': { items: [] },
  }
  const blocks = () => SHELL_MENU_IDS.map((id) => document.getElementById(id))

  it('one Menu button controls the chrome and both nav rows, which fold below 640 px until it is opened', async () => {
    mockApi(API)
    renderShell('/results', '/results', <h1>Baseline</h1>)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const button = screen.getByRole('button', { name: 'Menu' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveAttribute('data-hint', 'button.shell.menu')
    // the button is for phones only: from sm up it is not shown
    expect(button.className).toMatch(/(^|\s)sm:hidden(\s|$)/)
    expect(button.getAttribute('aria-controls')?.split(' ')).toEqual([...SHELL_MENU_IDS])
    const [actions, primary, instrument] = blocks()
    // every block the button names exists, and holds what the brief moves into the menu
    expect(primary).toBe(screen.getByRole('navigation', { name: 'Primary' }))
    expect(instrument).toBe(screen.getByRole('navigation', { name: 'Instrument' }))
    expect(actions).toContainElement(screen.getByTestId('user-chip'))
    expect(actions).toContainElement(screen.getByRole('button', { name: 'Sign out' }))
    expect(actions).toContainElement(within(screen.getByRole('banner')).getByRole('link', { name: 'Help' }))
    expect(actions).toContainElement(screen.getByRole('button', { name: /Switch theme/ }))
    for (const b of blocks()) expect(b!.className, b!.id).toMatch(/(^|\s)max-sm:hidden(\s|$)/)

    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    for (const b of blocks()) expect(b!.className, b!.id).not.toMatch(/max-sm:hidden/)
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
    for (const b of blocks()) expect(b!.className, b!.id).toMatch(/(^|\s)max-sm:hidden(\s|$)/)
  })

  it('Escape closes it and puts focus back on the button; an Escape spent on a hint bubble does not', async () => {
    mockApi(API)
    renderShell('/results', '/results', <h1>Baseline</h1>)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const button = screen.getByRole('button', { name: 'Menu' })
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    // focus a control inside the menu: its hint bubble opens on focus
    const baseline = within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Baseline' })
    baseline.focus()
    const tipId = baseline.getAttribute('aria-describedby')!.split(' ').pop()!
    await waitFor(() => expect(document.getElementById(tipId)).toHaveAttribute('data-open', 'true'))
    // the first Escape closes the innermost thing — the bubble — and leaves the menu open
    await userEvent.keyboard('{Escape}')
    expect(document.getElementById(tipId)).not.toHaveAttribute('data-open', 'true')
    expect(button).toHaveAttribute('aria-expanded', 'true')
    // the second closes the menu, and focus goes back to the button that opened it
    await userEvent.keyboard('{Escape}')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveFocus()
  })

  it('following a link inside it closes it, so the next screen starts with the navigation folded', async () => {
    mockApi(API)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/results']}>
          <AuthProvider>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/results" element={<h1>Baseline</h1>} />
                <Route path="/factory" element={<h1>Factory</h1>} />
              </Route>
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const button = screen.getByRole('button', { name: 'Menu' })
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Factory' }))
    expect(await screen.findByRole('heading', { name: 'Factory' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Menu' })).toHaveAttribute('aria-expanded', 'false')
  })
})
