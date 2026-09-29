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
 *               the same press) and on following a link inside it; that the instrument row's
 *               label names the Operate path as a hint trigger and every chrome id in
 *               `SHELL_CHROME_HINTS` renders (G-396); and that the ledger health probe's
 *               `false_q1` drives the "Delivery halted" banner — plural, singular, and none
 *               at zero or with no probe (G-564). jsdom applies no CSS, so
 *               the fold is asserted as the `max-sm:hidden` class; the 375-px walkthrough
 *               (11-screens) asserts what a phone actually shows.
 * How:          Pure calls for the helper; the shell rendered as a layout route with one
 *               child screen for the chrome.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Layout.tsx, ui/src/components/Help.tsx,
 *               ui/src/components/Hint.tsx (the menu button's hint spends the first Escape),
 *               ui/src/help/hints-ratchet.shell.tsx (`SHELL_CHROME_HINTS`), ui/src/api/types.ts
 *               (`Probe` — the ledger probe's shape; its `false_q1` field is
 *               src/crb/server/routes/system.py's `probe_ledger`),
 *               ui/e2e/walkthrough/11-screens.spec.ts (the same menu at 375 px in Chromium)
 * Tested by:    ui/src/components/Layout.test.tsx
 * Touch when:   never for a new repository; a journey step is added or the shell's chrome changes.
 */
import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Probe } from '../api/types'
import { hintText } from '../help/hints'
import { SHELL_CHROME_HINTS } from '../help/hints-ratchet.shell'
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

  it('places Repos and the repository page in step 1, where confirming the shape happens (G-301)', () => {
    expect(journeyEyebrow('/repos')).toBe('Journey · 1 of 4 · Connection · shape')
    expect(journeyEyebrow('/repos/cobra')).toBe('Journey · 1 of 4 · Connection · shape')
    expect(journeyEyebrow('/repos/cobra', 'probe')).toBe('Journey · 1 of 4 · Connection · shape · probe')
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

describe('Layout: the instrument row by role (G-914)', () => {
  afterEach(() => vi.unstubAllGlobals())

  /** The labels of the Instrument nav row as `role` sees it. */
  async function instrumentAs(role: 'viewer' | 'operator' | 'approver' | 'admin'): Promise<string[]> {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role },
      'GET /health': { status: 'ok', probes: [] },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
      'GET /decisions': { items: [] },
    })
    const view = renderShell('/ledger', '/ledger', <h1>Ledger</h1>)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const nav = screen.getByRole('navigation', { name: 'Instrument' })
    const labels = within(nav).getAllByRole('link').map((a) => a.textContent ?? '')
    view.unmount()
    return labels
  }

  it('a viewer has an entry to every page whose route and API a viewer may read: Map grid, Routes, Oracle, Learn and Ledger', async () => {
    // the four reads are `viewer` at the API (docs/API.md: /capability-map, /routes,
    // /oracle/{repo}, /learn/*), so a governance reader gets the same doors an operator does
    expect(await instrumentAs('viewer')).toEqual(['Map grid', 'Routes', 'Oracle', 'Learn', 'Ledger'])
  })

  it('Runs stays an operator entry and Settings an admin one', async () => {
    expect(await instrumentAs('operator')).toEqual(['Runs', 'Map grid', 'Routes', 'Oracle', 'Learn', 'Ledger'])
    expect(await instrumentAs('admin')).toEqual(['Runs', 'Map grid', 'Routes', 'Oracle', 'Learn', 'Ledger', 'Settings'])
  })
})

describe('Layout: the Operate path (G-396)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it("the instrument row names the Operate path: its label opens the group's purpose (G-396)", async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /health': { status: 'ok', probes: [] },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
      'GET /decisions': { items: [] },
    })
    const { container } = renderShell('/ledger', '/ledger', <h1>Ledger</h1>)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const nav = screen.getByRole('navigation', { name: 'Instrument' })
    const label = within(nav).getByTestId('instrument-group-label')
    expect(label).toHaveTextContent('Instrument')
    expect(label).toHaveAttribute('data-hint', 'nav.instrument_group')
    // no longer hidden from assistive technology: it is a trigger like every nav entry
    expect(label).not.toHaveAttribute('aria-hidden')
    expect(label).not.toHaveAttribute('title')
    // focus opens the group's purpose, which names the path
    label.focus()
    const tipId = label.getAttribute('aria-describedby')!.split(' ').pop()!
    await waitFor(() => expect(document.getElementById(tipId)).toHaveAttribute('data-open', 'true'))
    expect(document.getElementById(tipId)).toHaveTextContent(hintText('nav.instrument_group'))
    expect(hintText('nav.instrument_group')).toContain('health → Runs → Ledger → Settings')
    // every chrome id the shell registry names is rendered
    for (const id of SHELL_CHROME_HINTS) expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
  })

  it('the label does not steal the phone Menu’s first Tab: it follows the chrome and the Primary row (F26)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /health': { status: 'ok', probes: [] },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
      'GET /decisions': { items: [] },
    })
    renderShell('/ledger', '/ledger', <h1>Ledger</h1>)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const button = screen.getByRole('button', { name: 'Menu' })
    await userEvent.click(button)
    expect(button).toHaveFocus()
    await userEvent.tab()
    // the first Tab lands in the chrome cluster the menu discloses first, not on the label
    expect(document.getElementById(SHELL_MENU_IDS[0])).toContainElement(document.activeElement as HTMLElement)
    expect(screen.getByTestId('instrument-group-label')).not.toHaveFocus()
  })
})

describe('Layout: the stop-condition banner (G-564)', () => {
  afterEach(() => vi.unstubAllGlobals())

  /** The ledger probe as `GET /health` serves it (`probe_ledger`): `false_q1` is the server's field name. */
  const ledgerProbe = (falseQ1: number): Probe => ({ name: 'ledger', status: falseQ1 ? 'down' : 'ok', detail: falseQ1 ? `false_q1=${falseQ1} — honesty floor breached` : '10 rows, false_q1=0', data: { rows: 10, false_q1: falseQ1 } })

  function renderWith(probes: Probe[]) {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /health': { status: probes.some((p) => p.status !== 'ok') ? 'down' : 'ok', probes },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
      'GET /decisions': { items: [] },
    })
    return renderShell('/results', '/results', <h1>Baseline</h1>)
  }

  it('a false-Q1 row on the ledger probe halts delivery in a red alert above every screen, linking to the ledger (G-564)', async () => {
    renderWith([ledgerProbe(2)])
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Delivery halted — 2 false-Q1 rows on the ledger.')
    expect(alert).toHaveTextContent('Nothing measured is evidence until it is investigated. No policy setting can override this.')
    expect(within(alert).getByRole('link', { name: 'Investigate in the ledger' })).toHaveAttribute('href', '/ledger')
    expect(alert.className).toContain('bg-status-red')
    expect(alert.querySelector('[data-hint="banner.shell.stop_condition"]')).not.toBeNull()
    // above every screen: inside the header, before the page content
    expect(screen.getByRole('banner')).toContainElement(alert)
  })

  it('one false-Q1 row reads in the singular', async () => {
    renderWith([ledgerProbe(1)])
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Delivery halted — 1 false-Q1 row on the ledger.')
    expect(alert).not.toHaveTextContent('rows on the ledger')
  })

  it('a ledger probe reading zero false-Q1 shows no stop banner', async () => {
    const view = renderWith([ledgerProbe(0)])
    await screen.findByLabelText('Instrument health: OK')
    expect(screen.queryByRole('alert')).toBeNull()
    view.unmount()
    vi.unstubAllGlobals()
    // and so does a health with no ledger probe at all (an older server): absence is not a stop
    renderWith([{ name: 'worker', status: 'ok', detail: 'checked in', data: {} }])
    await screen.findByLabelText('Instrument health: OK')
    expect(screen.queryByRole('alert')).toBeNull()
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

  it('an Escape spent by another layer (a drawer or dialog holding focus) leaves the menu open', async () => {
    mockApi(API)
    // a layer like the evidence drawer: a window keydown listener closes it on Escape without
    // default-preventing, and focus sits inside it while it is open
    function Drawer() {
      const [open, setOpen] = useState(false)
      useEffect(() => {
        if (!open) return
        const onKey = (e: KeyboardEvent) => {
          if (e.key === 'Escape') setOpen(false)
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [open])
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open evidence
          </button>
          {open && (
            <div role="dialog" aria-label="Evidence">
              <button type="button" autoFocus>
                Close evidence
              </button>
            </div>
          )}
        </>
      )
    }
    renderShell('/results', '/results', <Drawer />)
    await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
    const button = screen.getByRole('button', { name: 'Menu' })
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Open evidence' }))
    expect(screen.getByRole('button', { name: 'Close evidence' })).toHaveFocus()
    // one press closes the innermost thing: the drawer, not the menu as well
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Evidence' })).toBeNull()
    expect(button).toHaveAttribute('aria-expanded', 'true')
    // with focus back on the menu's own button, Escape closes the menu (the first press
    // closes the button's own hint bubble, which opens on focus)
    button.focus()
    await userEvent.keyboard('{Escape}{Escape}')
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('a health that is not OK stays signalled on the closed Menu button, where the folded pill cannot be seen', async () => {
    mockApi({ ...API, 'GET /health': { status: 'degraded', probes: [] } })
    renderShell('/results', '/results', <h1>Baseline</h1>)
    // the pill itself is folded into the menu below 640 px ...
    const pill = await screen.findByLabelText('Instrument health: Degraded')
    expect(document.getElementById(SHELL_MENU_IDS[0])).toContainElement(pill)
    // ... so the button that stays on the bar carries the probe's glyph and says it in words
    const button = screen.getByRole('button', { name: 'Menu, instrument health: Degraded' })
    expect(button.textContent).toContain('⚠')
    expect(button.textContent).not.toContain('☰')
    // open, it shows the pill itself and the button goes back to its plain name
    await userEvent.click(button)
    expect(screen.getByRole('button', { name: 'Menu' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('an OK health adds nothing to the Menu button', async () => {
    mockApi(API)
    renderShell('/results', '/results', <h1>Baseline</h1>)
    await screen.findByLabelText('Instrument health: OK')
    const button = screen.getByRole('button', { name: 'Menu' })
    expect(button.textContent).toContain('☰')
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
