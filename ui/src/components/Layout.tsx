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

/** The one brand string in chrome (design law 9): header, footer and the login page use it. */
export const BRAND = 'Commit Replay Bench'

/** The primary navigation, in display order; a new screen is added here and in `App.tsx`. */
const NAV: Array<{ to: string; label: string }> = [
  { to: '/repos', label: 'Repos' },
  { to: '/runs', label: 'Runs' },
  { to: '/capability', label: 'Capability' },
  { to: '/routing', label: 'Routing' },
  { to: '/oracle', label: 'Oracle' },
  { to: '/learn', label: 'Learn' },
  { to: '/ledger', label: 'Ledger' },
  { to: '/signoff', label: 'Sign-off' },
  { to: '/factory', label: 'Factory' },
  { to: '/settings', label: 'Settings' },
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
  const { me } = useAuth()
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
      <header className="border-b border-border bg-surface-container">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-2.5">
          <NavLink to="/" className="font-serif text-[17px] font-semibold text-on-surface no-underline">
            {BRAND}
          </NavLink>
          <nav aria-label="Primary" className="order-last w-full md:order-none md:w-auto md:flex-1">
            <ul className="m-0 flex list-none flex-wrap gap-1 p-0">
              {NAV.map((n) => (
                <li key={n.to}>
                  <NavLink
                    to={n.to}
                    className={({ isActive }) =>
                      `inline-flex h-9 items-center rounded-[var(--radius-control)] px-3 text-sm no-underline ${
                        isActive ? 'bg-primary-container font-semibold text-primary' : 'text-on-surface-body hover:bg-surface-high'
                      }`
                    }
                  >
                    {n.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {h && (
              <Pill tone={h.tone} glyph={h.glyph} size="xs" label={`Instrument health: ${h.label}`}>
                {h.label}
              </Pill>
            )}
            {me && (
              <span className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-pill)] border border-border px-3 text-xs" data-testid="user-chip">
                <span className="font-semibold text-on-surface">{me.display_name || me.email}</span>
                <span className="label rounded-[var(--radius-pill)] bg-primary-container px-1.5 py-0.5 text-primary">{me.role}</span>
              </span>
            )}
            <Button size="sm" variant="ghost" onClick={cycle} aria-label={`Theme: ${theme}. Switch theme`} title={`Theme: ${theme}`}>
              <span aria-hidden>{THEME_GLYPH[theme]}</span>
            </Button>
            {me && (
              <Button
                size="sm"
                onClick={() =>
                  logout.mutate(undefined, {
                    onSettled: () => navigate('/login'),
                  })
                }
              >
                Sign out
              </Button>
            )}
          </div>
        </div>
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
