/**
 * Login — the local-account form and the OIDC button (/login).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /login, outside the shell.
 * What it does: Says what the product does for a team in one plain sentence (the only screen
 *               a sponsor sees before signing in carries no undefined term), then signs in
 *               with `POST /auth/login` (the local bootstrap account) or hands off to
 *               `GET /auth/oidc/start` (the organisation's identity provider — the button is
 *               offered only when `/version` says one is configured); renders the
 *               error envelope on a wrong password (never a blank form), and returns the user
 *               to the `?next=` path — same-origin paths only, so a crafted link cannot bounce
 *               a session to another host. An already-authenticated visitor is redirected
 *               straight to `next`; until the session check settles (the automatic sign-in
 *               included) a status line stands in for the form, so it never flashes before a
 *               redirect, and a failed check is shown above the form with a retry. While a
 *               development stack has automatic sign-in on, the banner above the form says so
 *               (`DevAutologinBanner`). Both fields and both
 *               sign-in buttons carry a hint
 *               (`field.login.*`, `button.login.*`) so the form explains itself on hover,
 *               focus and tap before a person has any role at all. Under the form one
 *               sentence gives the person who cannot get in a way forward and states the
 *               page's non-goal: an admin resets a password on Settings, or the person who
 *               runs the deployment does (`crb users`, OPERATOR §9) — accounts are never
 *               created, reset or reactivated here (the reset screen is backlog F23).
 * How:          `useAuth` (redirect if logged in) → `useLogin` mutation on submit → the auth
 *               query is seeded with the principal; `safeNext` validates the return path.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/auth.tsx (`RequireAuth` sends people here with `?next=`),
 *               ui/src/api/hooks.ts (`useLogin`), ui/src/components/ErrorState.tsx (the 401
 *               envelope), ui/src/help/hints.ts (the `field.login.*` / `button.login.*`
 *               copy), src/crb/server/routes/auth.py (login and the OIDC start URL),
 *               src/crb/server/auth.py (the session and CSRF cookies the login sets),
 *               ui/src/components/DevAutologinBanner.tsx (the automatic sign-in strip)
 * Tested by:    ui/src/screens/Login/LoginPage.test.tsx (the strapline; the hints resolve),
 *               ui/e2e/smoke.spec.ts (renders against a mocked API, OIDC button href, axe),
 *               ui/e2e/walkthrough/01-login.spec.ts (wrong password → envelope; right one →
 *               the role chip),
 *               ui/src/components/DevAutologinBanner.test.tsx (the status while an automatic
 *               sign-in settles; a failed one shown above the form)
 * Touch when:   the OIDC start path or the login body changes (docs/API.md "Auth"); never for
 *               a new repository.
 */
import { useState, type FormEvent } from 'react'
import { Navigate, useSearchParams } from 'react-router'
import { useLogin, useVersion } from '../../api/hooks'
import { apiUrl } from '../../api/client'
import { AnchorButton, Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { TextField } from '../../components/Field'
import { DevAutologinBanner } from '../../components/DevAutologinBanner'
import { BRAND } from '../../components/Layout'
import { useAuth } from '../../lib/auth'

/** Where a safe `?next=` may point: same-origin paths only; a direct login lands on the
 * journey's first screen (`/home`), the same place the index route sends everyone. */
function safeNext(raw: string | null): string {
  if (!raw) return '/home'
  const decoded = decodeURIComponent(raw)
  return decoded.startsWith('/') && !decoded.startsWith('//') ? decoded : '/home'
}

/** The screen; redirects to `next` once a session exists. */
export function LoginPage() {
  const { me, loading, error: authError, refetch: recheck } = useAuth()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const login = useLogin()
  // the organisation button is offered only when `/version` says a provider is configured
  const version = useVersion()
  const oidc = version.data?.oidc_enabled === true
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  if (!loading && me) return <Navigate to={next} replace />
  // Until the session check settles (`/auth/me`, and on a development stack the automatic
  // sign-in), the form is not shown: a visitor about to be signed in never sees it flash.
  if (loading) {
    return (
      <div className="flex min-h-screen flex-col bg-surface text-on-surface">
        <DevAutologinBanner />
        <div className="flex flex-1 items-center justify-center text-on-surface-muted" role="status">
          Checking your session…
        </div>
      </div>
    )
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate({ username, password })
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface text-on-surface">
      <DevAutologinBanner />
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <main className="w-full max-w-[420px] space-y-6">
          <header className="space-y-1 text-center">
            <div className="label">Sign in</div>
            <h1 className="text-[26px] leading-8">{BRAND}</h1>
            <p className="text-sm text-on-surface-muted">Measures what an AI builder can be trusted to change in your repository, graded by your own tests.</p>
          </header>

          <section className="rounded-[var(--radius-card)] border border-border bg-surface-container p-6 shadow-[var(--shadow-card)]">
            <form onSubmit={submit} className="space-y-4" aria-label="Local account sign in">
              <TextField label="Username" hint="field.login.username" name="username" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
              <TextField
                label="Password"
                hint="field.login.password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {login.isError && (
                <ErrorState
                  compact
                  error={login.error}
                  title={login.error.status === 401 ? 'Wrong username or password' : undefined}
                />
              )}
              <Button type="submit" variant="filled" hint="button.login.submit" className="w-full" disabled={login.isPending}>
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>

            {authError && (
              <div className="mt-5">
                <ErrorState compact error={authError} onRetry={recheck} title="Could not check your session" />
              </div>
            )}
            {version.isPending && <p className="mt-5 text-center text-[11px] text-on-surface-muted">Checking for an organisation sign-in…</p>}
            {version.isError && (
              <div className="mt-5">
                <ErrorState compact error={version.error} onRetry={() => void version.refetch()} title="Could not check for an organisation sign-in" />
              </div>
            )}
            {oidc && (
              <>
                <div className="my-5 flex items-center gap-3 text-[11px] text-on-surface-muted">
                  <span className="h-px flex-1 bg-border" />
                  or
                  <span className="h-px flex-1 bg-border" />
                </div>

                <AnchorButton href={apiUrl(`/auth/oidc/start?next=${encodeURIComponent(next)}`)} hint="button.login.oidc" className="w-full">
                  Sign in with organisation account
                </AnchorButton>
              </>
            )}
          </section>

          {/* The stop has a way forward. This page signs people in and does nothing else, so it
              names who can reset a password or reactivate an account: an admin on Settings, or
              the person who runs the deployment (`crb users`, docs/OPERATOR.md §9). The reset
              screen itself is backlog F23. */}
          <p className="text-center text-[13px] text-on-surface-muted">
            Forgotten your password, or locked out? Ask an admin to reset it on the Settings screen, or ask the person who runs this deployment. Accounts are not created, reset or reactivated here.
          </p>

          <p className="text-center text-[11px] text-on-surface-muted">Sessions are cookie-based and expire with the browser unless your organisation's policy says otherwise.</p>
        </main>
      </div>
    </div>
  )
}

export default LoginPage
