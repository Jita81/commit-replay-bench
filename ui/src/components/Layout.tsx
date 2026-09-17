/**
 * The app shell — brand, primary nav, instrument health, user chip with role, theme toggle,
 * provenance footer.
 *
 * Navigation
 * ----------
 * What it is:   The `Layout` shell every authenticated route renders inside (`<Outlet>`).
 * What it does: One brand name in chrome, the primary nav (Repos … Settings), the instrument
 *               health pill from `GET /health`, the user chip showing the principal's ROLE (so a
 *               viewer knows why a button is missing), theme cycling and sign-out. The footer
 *               carries crb / apparatus / policy versions — the one place internals appear,
 *               because an auditor needs the provenance of what they are reading.
 * How:          `useAuth` for the principal, `useHealth` / `useVersion` for the chrome facts,
 *               `useLogout` then navigate to `/login`; a skip link precedes the header.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/App.tsx (mounts this under `RequireAuth`), ui/src/lib/auth.tsx (the
 *               principal), ui/src/api/hooks.ts (`useHealth`, `useVersion`, `useLogout`),
 *               ui/src/lib/theme.ts (the toggle), ui/src/lib/verdict.ts (`probeDisplay` for
 *               the health pill), ui/src/screens/Login/LoginPage.tsx (uses `BRAND`)
 * Tested by:    ui/e2e/smoke.spec.ts (the shell renders the nav),
 *               ui/e2e/walkthrough/01-login.spec.ts
 *               (the role chip reads the bootstrap admin's role), ui/src/test/utils.tsx
 *               (`renderApp` mounts the shell for every screen test)
 * Touch when:   a screen is added — add its `NAV` entry here and its route in ui/src/App.tsx;
 *               never for a new repository.
 */
import { NavLink, Outlet, useNavigate } from 'react-router'
import { useHealth, useLogout, useVersion } from '../api/hooks'
import { useAuth } from '../lib/auth'
import { useTheme } from '../lib/theme'
import { Button } from './Button'
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
const JOURNEY: Array<{ to: string; label: string; badge?: boolean }> = [
  { to: '/home', label: 'Home' },
  { to: '/connect', label: 'Connection' },
  { to: '/results', label: 'Baseline' },
  { to: '/decisions', label: 'Decisions', badge: true },
  { to: '/factory', label: 'Factory' },
  { to: '/posture', label: 'Deployment' },
]
const INSTRUMENT: Array<{ to: string; label: string; role: 'viewer' | 'operator' | 'admin' }> = [
  { to: '/runs', label: 'Runs', role: 'operator' },
  { to: '/capability', label: 'Map grid', role: 'operator' },
  { to: '/routing', label: 'Routes', role: 'operator' },
  { to: '/oracle', label: 'Oracle', role: 'operator' },
  { to: '/learn', label: 'Learn', role: 'operator' },
  { to: '/ledger', label: 'Ledger', role: 'viewer' },
  { to: '/settings', label: 'Settings', role: 'admin' },
]

/** Sun / moon / half-disc for the theme toggle; the glyph is decorative, the `aria-label` carries the state. */
const THEME_GLYPH = { light: '☀', dark: '☾', system: '◐' } as const

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

  return (
    <div className="flex min-h-screen flex-col bg-surface text-on-surface">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface-container focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header>
        <div className="bg-primary text-on-primary">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-6 px-5 py-4">
            <NavLink to="/home" className="flex items-center gap-3 text-on-primary no-underline">
              <span className="block rounded-[2px] bg-on-primary px-2.5 pb-[7px] pt-[9px] text-[22px] font-bold leading-none tracking-[-.02em] text-primary">crb</span>
              <span className="text-[22px] font-bold leading-none">{BRAND}</span>
            </NavLink>
            <div className="ml-auto flex items-center gap-4 text-[16px]">
              {h && (
                <Pill tone={h.tone} glyph={h.glyph} size="xs" label={`Instrument health: ${h.label}`}>
                  {h.label}
                </Pill>
              )}
              {me && (
                <span className="inline-flex items-center gap-3" data-testid="user-chip">
                  <span>{me.display_name || me.email}</span>
                  <span className="label rounded-[4px] bg-on-primary px-2 py-1 text-[13px] font-bold uppercase tracking-[.05em] text-primary">{me.role}</span>
                </span>
              )}
              <Button size="sm" variant="ghost" className="text-on-primary" onClick={cycle} aria-label={`Theme: ${theme}. Switch theme`} title={`Theme: ${theme}`}>
                <span aria-hidden>{THEME_GLYPH[theme]}</span>
              </Button>
              {me && (
                <button
                  type="button"
                  className="bg-transparent p-0 text-[16px] text-on-primary underline"
                  onClick={() =>
                    logout.mutate(undefined, {
                      onSettled: () => navigate('/login'),
                    })
                  }
                >
                  Sign out
                </button>
              )}
            </div>
          </div>
        </div>
        <nav aria-label="Primary" className="bg-primary-deep">
          <ul className="mx-auto m-0 flex max-w-[1400px] list-none flex-wrap px-5 p-0">
            {JOURNEY.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  className={({ isActive }) =>
                    `flex items-center gap-2 border-b-4 px-4 py-3.5 text-[16px] leading-tight text-on-primary no-underline hover:bg-[#002265] ${
                      isActive ? 'border-on-primary font-bold' : 'border-transparent'
                    }`
                  }
                >
                  {n.label}
                  {n.badge && <DecisionsBadge />}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Instrument" className="border-b border-border bg-surface-high">
          <ul className="mx-auto m-0 flex max-w-[1400px] list-none flex-wrap items-center gap-1 px-5 py-1 p-0">
            <li className="pr-2 text-[11px] font-bold uppercase tracking-[.08em] text-on-surface-muted" aria-hidden>
              {instrument.length > 1 ? 'Instrument' : 'Record'}
            </li>
            {instrument.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  className={({ isActive }) =>
                    `inline-flex h-8 items-center rounded-[4px] px-2.5 text-xs no-underline ${
                      isActive ? 'bg-primary-container font-bold text-primary' : 'text-on-surface-muted hover:bg-surface-highest hover:text-on-surface'
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <StopConditionBanner />
      </header>
      <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 space-y-7 px-5 py-7">
        <Outlet />
      </main>
      <footer className="border-t border-border px-5 py-3 text-center text-[11px] text-on-surface-muted">
        {BRAND}
        {version.data && (
          <span className="num font-mono">
            {' '}
            · crb {version.data.crb} · apparatus {version.data.apparatus} · policy {version.data.policy}
          </span>
        )}
      </footer>
    </div>
  )
}

/** The count of decisions waiting on a person, on the nav — the design's badge. */
function DecisionsBadge() {
  const n = useDecisionCount()
  if (n === null) return null
  return (
    <span className="inline-block rounded-[10px] bg-on-primary px-[7px] py-[5px] text-[14px] font-bold leading-none text-primary-deep" aria-label={`${n} decisions waiting`}>
      {n}
    </span>
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
        <strong>Delivery halted — {falseQ1} false-Q1 row{falseQ1 === 1 ? '' : 's'} on the ledger.</strong> Nothing measured is evidence until it is investigated. No policy setting can override this.{' '}
        <NavLink to="/ledger" className="font-bold text-on-primary">
          Investigate in the ledger
        </NavLink>
      </div>
    </div>
  )
}

