import { useState, type FormEvent } from 'react'
import { Navigate, useSearchParams } from 'react-router'
import { useLogin } from '../../api/hooks'
import { apiUrl } from '../../api/client'
import { AnchorButton, Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { TextField } from '../../components/Field'
import { BRAND } from '../../components/Layout'
import { useAuth } from '../../lib/auth'

/** Where a safe `?next=` may point: same-origin paths only. */
function safeNext(raw: string | null): string {
  if (!raw) return '/repos'
  const decoded = decodeURIComponent(raw)
  return decoded.startsWith('/') && !decoded.startsWith('//') ? decoded : '/repos'
}

export function LoginPage() {
  const { me, loading } = useAuth()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const login = useLogin()
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
          <p className="text-sm text-on-surface-muted">Grade an AI builder against a repository's own tests, under four belts. false-Q1 = 0.</p>
        </header>

        <section className="rounded-[var(--radius-card)] border border-border bg-surface-container p-6 shadow-[var(--shadow-card)]">
          <form onSubmit={submit} className="space-y-4" aria-label="Local account sign in">
            <TextField label="Username" name="username" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
            <TextField
              label="Password"
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
            <Button type="submit" variant="filled" className="w-full" disabled={login.isPending}>
              {login.isPending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <div className="my-5 flex items-center gap-3 text-[11px] text-on-surface-muted">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>

          <AnchorButton href={apiUrl(`/auth/oidc/start?next=${encodeURIComponent(next)}`)} className="w-full">
            Sign in with organisation account
          </AnchorButton>
        </section>

        <p className="text-center text-[11px] text-on-surface-muted">Sessions are cookie-based and expire with the browser unless your organisation's policy says otherwise.</p>
      </main>
    </div>
  )
}

export default LoginPage
