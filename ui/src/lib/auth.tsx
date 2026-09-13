/**
 * Auth context: the current principal from `GET /auth/me`, and a route guard.
 *
 * A 401 resolves to `null` (see `useMe`), which the guard turns into a
 * redirect to `/login?next=…`. A 403 on a specific screen is rendered by that
 * screen as an honest "insufficient role" state — never hidden.
 */

import { createContext, useContext, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useMe } from '../api/hooks'
import type { ApiError } from '../api/client'
import type { Principal, Role } from '../api/types'
import { roleAtLeast } from '../api/types'

export interface AuthState {
  me: Principal | null
  loading: boolean
  error: ApiError | null
  can: (min: Role) => boolean
  refetch: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const q = useMe()
  const me = q.data ?? null
  const value: AuthState = {
    me,
    loading: q.isLoading,
    error: q.error ?? null,
    can: (min) => roleAtLeast(me?.role, min),
    refetch: () => {
      void q.refetch()
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** Redirects to /login when there is no session. Renders children otherwise. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading, error } = useAuth()
  const loc = useLocation()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-on-surface-muted" role="status">
        Checking your session…
      </div>
    )
  }
  if (!me && !error) {
    const next = encodeURIComponent(loc.pathname + loc.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <>{children}</>
}
