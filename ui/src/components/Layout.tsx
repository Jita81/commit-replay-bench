/**
 * The app shell — brand, primary nav, instrument health, user chip with role, theme toggle,
 * Help, the About block under every screen, provenance footer.
 *
 * Navigation
 * ----------
 * What it is:   The `Layout` shell every authenticated route renders inside (`<Outlet>`), plus
 *               `JOURNEY_STEPS` and `journeyEyebrow()` — the one source of "where am I".
 * What it does: One brand name in chrome, the journey nav and the instrument row, the
 *               instrument health pill from `GET /health`, the user chip showing the
 *               principal's ROLE (so a viewer knows why a button is missing; the display name
 *               only from `sm` up), theme cycling, Help as a compact "?" icon (the footer
 *               carries the words) and sign-out — sized so the cluster is one row at 375 px
 *               and "Sign out" never becomes a third header row. `AboutThisScreen` is mounted
 *               once after the outlet so every
 *               screen carries its help with no wiring. The footer carries crb / apparatus /
 *               policy versions — the one place internals appear, because an auditor needs
 *               the provenance of what they are reading — and links to Help and the glossary.
 *               `journeyEyebrow(pathname, sub?)` derives `Journey · 2 of 4 · Baseline` from
 *               the four steps so no screen hand-types its position. Every element of the
 *               chrome — each nav entry (`nav.*`), the health pill, the role chip, Help, the
 *               theme toggle, Sign out, the stop-condition banner, the footer's version line
 *               and links — is a `<Hint>` trigger, so the shell explains itself on hover,
 *               focus and tap on every screen; no native `title` remains.
 * How:          `useAuth` for the principal, `useHealth` / `useVersion` for the chrome facts,
 *               `useLogout` then navigate to `/login`; a skip link precedes the header; each
 *               `JOURNEY` / `INSTRUMENT` entry names its hint id.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/App.tsx (mounts this under `RequireAuth`), ui/src/components/Hint.tsx
 *               (the trigger), ui/src/help/hints.ts (`nav.*`, `pill.shell.*`, `button.shell.*`,
 *               `banner.shell.stop_condition`), ui/src/components/Help.tsx
 *               (`AboutThisScreen`, mounted once here), ui/src/components/PageHeader.tsx
 *               (defaults its eyebrow to `journeyEyebrow`), ui/src/lib/auth.tsx (the
 *               principal), ui/src/api/hooks.ts (`useHealth`, `useVersion`, `useLogout`),
 *               ui/src/lib/verdict.ts (`probeDisplay` for the health pill)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx (every element of the
 *               shell carries a hint), ui/src/components/Layout.test.tsx (the steps, the eyebrow, Help, the About
 *               block), ui/e2e/smoke.spec.ts (the shell renders the nav),
 *               ui/e2e/walkthrough/01-login.spec.ts
 *               (the role chip reads the bootstrap admin's role), ui/src/test/utils.tsx
 *               (`renderApp` mounts the shell for every screen test)
 * Touch when:   a screen is added — add its `NAV` entry here and its route in ui/src/App.tsx;
 *               never for a new repository.
 */
import { useEffect, useState } from 'react'
import { NavLink, Outlet, matchPath, useLocation, useNavigate } from 'react-router'
import { useHealth, useLogout, useVersion } from '../api/hooks'
import { useAuth } from '../lib/auth'
import { useTheme } from '../lib/theme'
import type { HintId } from '../help/hints'
import { Button } from './Button'
import { AboutThisScreen } from './Help'
import { Hint } from './Hint'
import { Pill } from './Pill'
import { probeDisplay } from '../lib/verdict'
import { useDecisionCount } from '../screens/Decisions/useDecisionCount'

/** The one brand string in chrome (design law 9): header, footer and the login page use it. */
export const BRAND = 'Commit Replay Bench'

/**
 * The primary nav is the JOURNEY — connect a repository, earn its baseline, decide what is
 * waiting on a person, run the factory (DL-044: the factory and the self-improvement loop
 * are the product; the rest is the on-ramp that earns their baseline). Every role sees the
 * journey. The INSTRUMENT row beneath it is the operator's tooling — runs, the map grid,
 * routes, the oracle, the learning loop — plus the ledger for every role (an auditor's
 * screen) and Settings for admins. Nothing is removed from the URL space: the repositories
 * list, the sign-off form and the map grid stay routable, reached from the journey (the
 * Connection page lists repositories; Decisions and the map link to the sign-off form).
 */
const JOURNEY: Array<{ to: string; label: string; hint: HintId; badge?: boolean }> = [
  { to: '/home', label: 'Home', hint: 'nav.home' },
  { to: '/connect', label: 'Connection', hint: 'nav.connect' },
  { to: '/results', label: 'Baseline', hint: 'nav.baseline' },
  { to: '/decisions', label: 'Decisions', hint: 'nav.decisions', badge: true },
  { to: '/factory', label: 'Factory', hint: 'nav.factory' },
  { to: '/posture', label: 'Deployment', hint: 'nav.posture' },
]
/**
 * The four journey STEPS the eyebrow counts (Home is the start; Deployment is a review page,
 * not a step). Every journey screen derives "Journey · n of 4 · Step" from this list through
 * `journeyEyebrow`, so the position a reader sees cannot drift from the nav.
 */
export const JOURNEY_STEPS: readonly { label: string; to: string }[] = [
  { label: 'Connection', to: '/connect' },
  { label: 'Baseline', to: '/results' },
  { label: 'Decisions', to: '/decisions' },
  { label: 'Factory', to: '/factory' },
]

/** Route pattern → the step it belongs to (index into `JOURNEY_STEPS`) and its own sub-label. */
const STEP_OF: Array<{ pattern: string; step: number; sub?: string }> = [
  { pattern: '/connect/*', step: 0 },
  { pattern: '/results', step: 1 },
  { pattern: '/decisions', step: 2 },
  { pattern: '/signoff', step: 2, sub: 'sign-off' },
  { pattern: '/factory', step: 3 },
  // intake is a sub-step of the factory, reached by a link ON /factory rather than by a nav
  // entry of its own (ui/src/App.reachability.test.ts holds that the link exists)
  { pattern: '/factory/intake', step: 3, sub: 'intake' },
]

/**
 * The eyebrow for a journey route: `Journey · 2 of 4 · Baseline`, plus ` · <sub>` when the
 * screen passes one (Measure: `task 5 of 8 · this step spends money`); `Journey · start` on
 * Home; `''` for every other route, so a PageHeader there renders no eyebrow unless the
 * screen passes its own.
 */
export function journeyEyebrow(pathname: string, sub?: string): string {
  if (matchPath('/home', pathname)) return sub ? `Journey · start · ${sub}` : 'Journey · start'
  const hit = STEP_OF.find((s) => matchPath(s.pattern, pathname))
  if (!hit) return ''
  const parts = ['Journey', `${hit.step + 1} of ${JOURNEY_STEPS.length}`, JOURNEY_STEPS[hit.step]!.label]
  if (hit.sub) parts.push(hit.sub)
  if (sub) parts.push(sub)
  return parts.join(' · ')
}

const INSTRUMENT: Array<{ to: string; label: string; role: 'viewer' | 'operator' | 'admin'; hint: HintId }> = [
  { to: '/runs', label: 'Runs', role: 'operator', hint: 'nav.runs' },
  { to: '/capability', label: 'Map grid', role: 'operator', hint: 'nav.capability' },
  { to: '/routing', label: 'Routes', role: 'operator', hint: 'nav.routing' },
  { to: '/oracle', label: 'Oracle', role: 'operator', hint: 'nav.oracle' },
  { to: '/learn', label: 'Learn', role: 'operator', hint: 'nav.learn' },
  { to: '/ledger', label: 'Ledger', role: 'viewer', hint: 'nav.ledger' },
  { to: '/settings', label: 'Settings', role: 'admin', hint: 'nav.settings' },
]

/** Sun / moon / half-disc for the theme toggle; the glyph is decorative, the `aria-label` carries the state. */
const THEME_GLYPH = { light: '☀', dark: '☾', system: '◐' } as const

/**
 * The ids of the three blocks the phone "Menu" discloses (F26): the chrome cluster (health
 * pill, role chip, Help, theme, Sign out) and the two nav rows. From `sm` (640 px) up they
 * are always shown and the Menu button is not rendered visible; below it they are shown
 * only while the menu is open. One button controls all three, so `aria-controls` lists them.
 */
export const SHELL_MENU_IDS = ['shell-menu-actions', 'shell-nav-primary', 'shell-nav-instrument'] as const
/** The Menu button's DOM id: Escape returns focus here. */
export const SHELL_MENU_BUTTON_ID = 'shell-menu-button'

/**
 * The phone menu's open state, keyed to the address it was opened on, so following any link
 * inside it closes it (the next screen starts with the navigation folded away) without an
 * effect that resets state after render. Escape closes it and puts focus back on the button
 * — unless the Escape was already spent closing a hint bubble (`Hint` default-prevents it and
 * stops it in the capture phase), so one press closes the innermost thing, as in a dialog.
 */
function useShellMenu(): { open: boolean; toggle: () => void } {
  const { pathname, search } = useLocation()
  const here = `${pathname}${search}`
  const [openAt, setOpenAt] = useState<string | null>(null)
  const open = openAt === here
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      setOpenAt(null)
      document.getElementById(SHELL_MENU_BUTTON_ID)?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  return { open, toggle: () => setOpenAt(open ? null : here) }
}

/**
 * The app shell: brand, top nav (one brand name in chrome — law 9), health
 * dot, user chip with role, theme toggle. No internals (endpoints, models,
 * versions) in the chrome except the apparatus version in the footer, which
 * is a provenance fact the auditor needs.
 */
export function Layout() {
  const { me, can } = useAuth()
  const instrument = INSTRUMENT.filter((n) => can(n.role))
  const [theme, , cycle] = useTheme()
  const logout = useLogout()
  const navigate = useNavigate()
  const health = useHealth()
  const version = useVersion()
  const h = health.data ? probeDisplay(health.data.status) : null
  const menu = useShellMenu()
  // below sm the three blocks show only while the menu is open; from sm up, always
  const folded = menu.open ? '' : 'max-sm:hidden'

  return (
    <div className="flex min-h-screen flex-col bg-surface text-on-surface">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface-container focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header>
        <div className="bg-primary text-on-primary">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-2 gap-y-3 px-5 py-3 sm:gap-6 sm:py-4">
            <NavLink to="/home" className="flex items-center gap-2 text-on-primary no-underline sm:gap-3">
              <span className="block rounded-[2px] bg-on-primary px-2 pb-[6px] pt-[8px] text-[17px] font-bold leading-none tracking-[-.02em] text-primary sm:px-2.5 sm:pb-[7px] sm:pt-[9px] sm:text-[22px]">crb</span>
              <span className="text-[17px] font-bold leading-none sm:text-[22px]">{BRAND}</span>
            </NavLink>
            {/* F26: below 640 px the journey and instrument rows and this cluster fold behind one
                "Menu" disclosure, so a phone's first screen is the page, not three rows of chrome */}
            {/* on the header's own blue, like the nav links (hover darkens, never lightens): a
                ghost button's light hover fill put blue text on light blue (axe, 2.29:1) */}
            <Hint
              as="button"
              id="button.shell.menu"
              elementId={SHELL_MENU_BUTTON_ID}
              type="button"
              className="ml-auto inline-flex h-9 shrink-0 cursor-pointer items-center gap-1 rounded-[var(--radius-control)] border border-on-primary bg-transparent px-2.5 text-[14px] font-semibold text-on-primary hover:bg-[#002265] sm:hidden"
              aria-expanded={menu.open}
              aria-controls={SHELL_MENU_IDS.join(' ')}
              onClick={menu.toggle}
              data-testid="shell-menu-button"
            >
              <span aria-hidden>{menu.open ? '✕' : '☰'}</span> Menu
            </Hint>
            {/* the gaps and the role pill are tighter below sm; on a phone this cluster is the menu's first row */}
            <div
              id={SHELL_MENU_IDS[0]}
              className={`${folded} flex basis-full flex-wrap items-center gap-x-2.5 gap-y-2 text-[16px] sm:ml-auto sm:basis-auto sm:justify-end sm:gap-x-4`}
            >
              {h && (
                <Pill tone={h.tone} glyph={h.glyph} size="xs" label={`Instrument health: ${h.label}`} hint="pill.shell.health">
                  {h.label}
                </Pill>
              )}
              {me && (
                <span className="inline-flex items-center gap-2.5 sm:gap-3" data-testid="user-chip">
                  {/* the name is a courtesy the role pill does not need: below sm it goes, so the cluster stays on one row at 375 px and "Sign out" is never a third header row */}
                  <span className="hidden sm:inline">{me.display_name || me.email}</span>
                  <Hint id="pill.shell.role" data-component="pill" className="label rounded-[4px] bg-on-primary px-1.5 py-1 text-[12px] font-bold uppercase tracking-[.05em] text-primary sm:px-2 sm:text-[13px]">
                    {me.role}
                  </Hint>
                </span>
              )}
              {/* a compact icon, not a word: the footer carries the written Help · Glossary links on every screen */}
              <Hint
                as={NavLink}
                id="nav.help"
                to="/help"
                aria-label="Help"
                className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-on-primary text-[15px] font-bold text-on-primary no-underline"
              >
                <span aria-hidden>?</span>
              </Hint>
              <Button size="sm" variant="ghost" className="text-on-primary" onClick={cycle} aria-label={`Theme: ${theme}. Switch theme`} hint="button.shell.theme">
                <span aria-hidden>{THEME_GLYPH[theme]}</span>
              </Button>
              {me && (
                <Hint
                  as="button"
                  id="button.shell.sign_out"
                  type="button"
                  className="bg-transparent p-0 text-[16px] text-on-primary underline"
                  onClick={() =>
                    logout.mutate(undefined, {
                      onSettled: () => navigate('/login'),
                    })
                  }
                >
                  Sign out
                </Hint>
              )}
            </div>
          </div>
        </div>
        <nav aria-label="Primary" id={SHELL_MENU_IDS[1]} className={`${folded} bg-primary-deep`}>
          <ul className="mx-auto m-0 flex max-w-[1400px] list-none flex-wrap px-5 p-0 max-sm:flex-col">
            {JOURNEY.map((n) => (
              <li key={n.to}>
                <Hint
                  as={NavLink}
                  id={n.hint}
                  to={n.to}
                  className={({ isActive }: { isActive: boolean }) =>
                    `flex items-center gap-2 border-b-4 px-4 py-3.5 text-[16px] leading-tight text-on-primary no-underline hover:bg-[#002265] ${
                      isActive ? 'border-on-primary font-bold' : 'border-transparent'
                    }`
                  }
                >
                  {n.label}
                  {n.badge && <DecisionsBadge />}
                </Hint>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Instrument" id={SHELL_MENU_IDS[2]} className={`${folded} border-b border-border bg-surface-high`}>
          <ul className="mx-auto m-0 flex max-w-[1400px] list-none flex-wrap items-center gap-1 px-5 py-1 p-0">
            <li className="pr-2 text-[11px] font-bold uppercase tracking-[.08em] text-on-surface-muted" aria-hidden>
              {instrument.length > 1 ? 'Instrument' : 'Record'}
            </li>
            {instrument.map((n) => (
              <li key={n.to}>
                <Hint
                  as={NavLink}
                  id={n.hint}
                  to={n.to}
                  className={({ isActive }: { isActive: boolean }) =>
                    `inline-flex h-8 items-center rounded-[4px] px-2.5 text-xs no-underline ${
                      isActive ? 'bg-primary-container font-bold text-primary' : 'text-on-surface-muted hover:bg-surface-highest hover:text-on-surface'
                    }`
                  }
                >
                  {n.label}
                </Hint>
              </li>
            ))}
          </ul>
        </nav>
        <StopConditionBanner />
      </header>
      <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 space-y-7 px-5 py-7">
        <Outlet />
        <AboutThisScreen />
      </main>
      <footer className="border-t border-border px-5 py-3 text-center text-[11px] text-on-surface-muted">
        {BRAND}
        {version.data && (
          <Hint id="nav.version_line" className="num font-mono">
            {' '}
            · crb {version.data.crb} · apparatus {version.data.apparatus} · policy {version.data.policy}
          </Hint>
        )}
        {' · '}
        <Hint as={NavLink} id="nav.footer_help" to="/help" className="underline">
          Help
        </Hint>
        {' · '}
        <Hint as={NavLink} id="nav.footer_glossary" to="/help#terms" className="underline">
          Glossary
        </Hint>
      </footer>
    </div>
  )
}

/** The count of decisions waiting on a person, on the nav — the design's badge. */
function DecisionsBadge() {
  const n = useDecisionCount()
  if (n === null) return null
  return (
    <Hint id="nav.decisions_count" tabStop={false} className="inline-block rounded-[10px] bg-on-primary px-[7px] py-[5px] text-[14px] font-bold leading-none text-primary-deep" aria-label={`${n} decisions waiting`}>
      {n}
    </Hint>
  )
}

/**
 * The stop condition: a false-Q1 row anywhere on the ledger halts delivery and nothing
 * measured is evidence until it is investigated. Rendered full-width and red, above every
 * screen, from the ledger health probe — no policy setting can hide it.
 */
function StopConditionBanner() {
  const health = useHealth()
  const ledger = health.data?.probes.find((p) => p.name === 'ledger')
  const falseQ1 = Number(ledger?.data.false_q1 ?? 0)
  if (!ledger || falseQ1 === 0) return null
  return (
    <div className="bg-status-red text-on-primary" role="alert">
      <div className="mx-auto max-w-[1400px] px-5 py-4 text-[19px] leading-[1.47]">
        <Hint as="strong" id="banner.shell.stop_condition">
          Delivery halted — {falseQ1} false-Q1 row{falseQ1 === 1 ? '' : 's'} on the ledger.
        </Hint>{' '}
        Nothing measured is evidence until it is investigated. No policy setting can override this.{' '}
        <NavLink to="/ledger" className="font-bold text-on-primary">
          Investigate in the ledger
        </NavLink>
      </div>
    </div>
  )
}

