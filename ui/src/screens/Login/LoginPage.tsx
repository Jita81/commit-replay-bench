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
 *               straight to `next`. Both fields and both sign-in buttons carry a hint
 *               (`field.login.*`, `button.login.*`) so the form explains itself on hover,
 *               focus and tap before a person has any role at all. Every stop names its way
 *               forward where the person meets it: a wrong password's envelope says who sets a
 *               new one (G-460); a 429 is "Too many failed sign-ins" with the wait in seconds
 *               from `retry_after_s` (G-189); a failed organisation sign-in comes back as
 *               `?error=<code>` and shows a fixed sentence for that code — never the code or
 *               the provider's words (G-188). Under the form one sentence states the page's
 *               non-goal: an admin resets a password on Settings, or the person who runs the
 *               deployment does (`crb users`, OPERATOR §9) — accounts are never created, reset
 *               or reactivated here. The session note states the server's default length.
 *               Last, it mounts the "About this screen" block itself — the screen is outside
 *               the shell that mounts it everywhere else (G-926).
 * How:          `useAuth` (redirect if logged in) → `useLogin` mutation on submit → the auth
 *               query is seeded with the principal; `safeNext` validates the return path;
 *               `nextStep` / `failureTitle` pick the envelope's copy by status;
 *               `OIDC_FAILURE_REASONS` maps a callback code to its sentence.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/auth.tsx (`RequireAuth` sends people here with `?next=`),
 *               ui/src/api/hooks.ts (`useLogin`), ui/src/components/ErrorState.tsx (the 401
 *               envelope), ui/src/help/hints.ts (the `field.login.*` / `button.login.*`
 *               copy), src/crb/server/routes/auth.py (login and the OIDC start URL),
 *               src/crb/server/auth.py (the session and CSRF cookies the login sets, and
 *               `session_ttl`, the length the session note states), ui/src/components/Help.tsx
 *               (`AboutThisScreen`, fed by the `/login` entry in ui/src/help/help.ts)
 * Tested by:    ui/src/screens/Login/LoginPage.test.tsx (the strapline; the hints resolve;
 *               every stop's next step; the /version states),
 *               tests/test_server_auth.py (the session note matches `session_ttl`),
 *               ui/e2e/walkthrough/13-recover-an-account.spec.ts (the recovery, timed),
 *               ui/e2e/smoke.spec.ts (renders against a mocked API, OIDC button href, axe),
 *               ui/e2e/walkthrough/01-login.spec.ts (wrong password → envelope; right one →
 *               the role chip), ui/src/components/Help.test.tsx (the About block mounts here)
 * Touch when:   never for a new repository; the OIDC start path or the login body changes
 *               (docs/API.md "Auth").
 */
import { useState, type FormEvent } from 'react'
import { Navigate, useSearchParams } from 'react-router'
import { useLogin, useVersion } from '../../api/hooks'
import { apiUrl, type ApiError } from '../../api/client'
import { AnchorButton, Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { AboutThisScreen } from '../../components/Help'
import { TextField } from '../../components/Field'
import { BRAND } from '../../components/Layout'
import { useAuth } from '../../lib/auth'

/** Where a safe `?next=` may point: same-origin paths only; a direct login lands on the
 * journey's first screen (`/home`), the same place the index route sends everyone. */
function safeNext(raw: string | null): string {
  if (!raw) return '/home'
  const decoded = decodeURIComponent(raw)
  return decoded.startsWith('/') && !decoded.startsWith('//') ? decoded : '/home'
}

/** What a failed organisation sign-in says when the callback sends the person back here with
 * `?error=<code>` (src/crb/server/routes/auth.py `OIDC_FAILURE_CODES`). The code picks one of
 * these fixed sentences; it is never rendered itself, so a crafted link cannot put words here. */
export const OIDC_FAILURE_REASONS: Record<string, string> = {
  oidc_provider_error: 'Your organisation’s sign-in refused or cancelled the sign-in. Try again, or ask your IT team whether your account may use this service.',
  oidc_state_missing: 'The sign-in started in another browser or tab, or took too long. Start it again from this page.',
  oidc_state_expired: 'The sign-in started in another browser or tab, or took too long. Start it again from this page.',
  oidc_state_invalid: 'The sign-in started in another browser or tab, or took too long. Start it again from this page.',
  oidc_state_mismatch: 'The sign-in started in another browser or tab, or took too long. Start it again from this page.',
  oidc_exchange_failed: 'This deployment could not complete the sign-in with your organisation. Try again; if it fails again, tell the person who runs this deployment.',
  oidc_discovery_failed: 'This deployment could not complete the sign-in with your organisation. Try again; if it fails again, tell the person who runs this deployment.',
  account_disabled: 'Your account on this deployment is turned off. Ask an admin of this deployment to turn it back on.',
}

/** The sentence for an unknown or missing code. */
const OIDC_FAILURE_FALLBACK = 'The organisation sign-in did not complete. Try again, or sign in with a local account below.'

/** The next step under a failed sign-in's envelope: who sets a password (401), or how long to wait (429). */
function nextStep(error: ApiError): string | null {
  if (error.status === 401) {
    return 'If you have forgotten your password, ask an admin of this deployment to set a new one on the Settings screen. If no admin can sign in, the person who runs the deployment sets it on the host (crb users, OPERATOR §9).'
  }
  if (error.status === 429) {
    const raw = error.detail.retry_after_s
    const wait = typeof raw === 'number' && raw > 0 ? Math.ceil(raw) : null
    return wait === null ? 'Wait a minute, then try again.' : `Wait ${wait} ${wait === 1 ? 'second' : 'seconds'}, then try again.`
  }
  return null
}

/** The heading of a failed sign-in's envelope. */
function failureTitle(error: ApiError): string | undefined {
  if (error.status === 401) return 'Wrong username or password'
  if (error.status === 429) return 'Too many failed sign-ins'
  return undefined
}

/** The screen; redirects to `next` once a session exists. */
export function LoginPage() {
  const { me, loading } = useAuth()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  // a failed organisation sign-in comes back here as `?error=<code>` (G-188)
  const oidcError = params.get('error')
  const login = useLogin()
  // the organisation button is offered only when `/version` says a provider is configured
  const version = useVersion()
  const oidc = version.data?.oidc_enabled === true
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  if (!loading && me) return <Navigate to={next} replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate({ username, password })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4 py-10 text-on-surface">
      <main className="w-full max-w-[420px] space-y-6">
        <header className="space-y-1 text-center">
          <div className="label">Sign in</div>
          <h1 className="text-[26px] leading-8">{BRAND}</h1>
          <p className="text-sm text-on-surface-muted">Measures what an AI builder can be trusted to change in your repository, graded by your own tests.</p>
        </header>

        {oidcError !== null && (
          <div role="alert" data-testid="login-oidc-error" className="rounded-[var(--radius-card)] border border-status-red/40 bg-status-red-soft px-4 py-3 text-on-surface">
            <div className="font-serif text-[16px] font-semibold text-status-red">Organisation sign-in did not complete</div>
            <p className="m-0 text-sm">{OIDC_FAILURE_REASONS[oidcError] ?? OIDC_FAILURE_FALLBACK}</p>
          </div>
        )}

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
              <ErrorState compact error={login.error} title={failureTitle(login.error)}>
                {nextStep(login.error) && (
                  <p className="m-0 text-sm" data-testid="login-next-step">
                    {nextStep(login.error)}
                  </p>
                )}
              </ErrorState>
            )}
            <Button type="submit" variant="filled" hint="button.login.submit" className="w-full" disabled={login.isPending}>
              {login.isPending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

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
            names who can reset a password or reactivate an account: an admin on Settings (the
            Users card), or the person who runs the deployment (`crb users`, docs/OPERATOR.md §9). */}
        <p className="text-center text-[13px] text-on-surface-muted">
          Forgotten your password, or locked out? Ask an admin to reset it on the Settings screen, or ask the person who runs this deployment. Accounts are not created, reset or reactivated here.
        </p>

        {/* The length is the server's default (`Settings.session_ttl`); tests/test_server_auth.py
            fails if the two drift (docs/PREVENTION.md). */}
        <p className="text-center text-[11px] text-on-surface-muted" data-testid="login-session-note">
          A session lasts 8 hours unless this deployment sets another length. Signing out ends it on every device.
        </p>

        {/* The screen sits outside the shell, so it mounts its own About block (G-926). */}
        <AboutThisScreen />
      </main>
    </div>
  )
}

export default LoginPage
