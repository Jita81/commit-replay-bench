/**
 * Auth context: the current principal from `GET /auth/me`, and a route guard.
 *
 * A 401 resolves to `null` (see `useMe`), which the guard turns into a
 * redirect to `/login?next=…`. A 403 on a specific screen is rendered by that
 * screen as an honest "insufficient role" state — never hidden.
 *
 * Navigation
 * ----------
 * What it is:   The auth context (`AuthProvider` / `useAuth`) and the `RequireAuth` route guard.
 * What it does: Holds the logged-in principal from `GET /auth/me`, exposes `can(role)` for the
 *               RBAC ladder so screens hide or disable what the role cannot do, and redirects
 *               an unauthenticated visitor to `/login?next=…`. A 403 is NOT handled here —
 *               the screen that received it renders it — and a network / server error while
 *               checking the session is shown, not turned into a login redirect.
 * How:          `useMe` (a 401 → `null`) feeds a React context; `RequireAuth` reads it: loading
 *               → a status line, no principal and no error → `<Navigate to=/login>`, otherwise
 *               the children.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useMe`, `useLogin`, `useLogout`), ui/src/api/types.ts
 *               (`Principal`, `Role`, `roleAtLeast`), ui/src/App.tsx (wraps the router in the
 *               provider and every shell route in the guard), ui/src/components/Layout.tsx (the
 *               role chip and sign-out), ui/src/screens/Login/LoginPage.tsx (honours `?next=`)
 * Tested by:    ui/src/test/utils.tsx (`renderApp` mounts the provider for every screen test),
 *               ui/e2e/walkthrough/01-login.spec.ts, ui/e2e/smoke.spec.ts
 * Touch when:   a role is added to the ladder (docs/API.md "Conventions") — extend `Role` in
 *               ui/src/api/types.ts first; never for a new repository.
 */

import { createContext, useContext, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useMe } from '../api/hooks'
import type { ApiError } from '../api/client'
import type { Principal, Role } from '../api/types'
import { roleAtLeast } from '../api/types'

/** What every screen can ask about the session; `can(min)` is the one RBAC check in the UI. */
export interface AuthState {
  me: Principal | null
  loading: boolean
  error: ApiError | null
  can: (min: Role) => boolean
  refetch: () => void
}

const AuthContext = createContext<AuthState | null>(null)

/** Mounts once around the router; one `GET /auth/me` per session (60 s stale), shared by every screen. */
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

/** The session from context; throws outside `AuthProvider` so a misplaced screen fails loudly in tests. */
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
  // Only a definite "no session" redirects. A network / 5xx error while checking is
  // not "logged out": the children render and the screen shows the error, so an API
  // outage never becomes a login loop.
  if (!me && !error) {
    const next = encodeURIComponent(loc.pathname + loc.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <>{children}</>
}
