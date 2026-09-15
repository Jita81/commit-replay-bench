/**
 * QueryBoundary — loading line, honest error, or the data; a disabled query shows a designed
 * prompt.
 *
 * Navigation
 * ----------
 * What it is:   The `QueryBoundary` render-prop wrapper around one TanStack query.
 * What it does: Turns a query's three states into the three things a screen may show: a
 *               loading sentence that says WHAT is loading, the error envelope through
 *               `ErrorState` with a Retry (never swallowed), or the children with the data. A
 *               disabled query (no `?repo=` yet) renders `idle` so a screen never spins forever.
 * How:          `fetchStatus === 'idle' && status === 'pending'` → idle; `isPending` →
 *               loading; `isError` → `ErrorState`; else `children(data)`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/ErrorState.tsx (the error branch), ui/src/api/hooks.ts (every
 *               hook returns the `UseQueryResult` this takes), ui/src/components/RepoPicker.tsx
 *               (the usual reason a query is idle), ui/src/screens/Runs/RunDetailPage.tsx (a
 *               typical use around a table)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx (loading → data → error
 *               transitions as rendered), ui/src/screens/Runs/RunDetailPage.test.tsx
 * Touch when:   never for a new repository.
 */
import type { ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { ErrorState } from './ErrorState'

interface QueryBoundaryProps<T> {
  query: UseQueryResult<T, unknown>
  /** Copy for the loading state — say what is being fetched. */
  loading: string
  children: (data: T) => ReactNode
  /** Shown when the query is disabled (e.g. no repo chosen). */
  idle?: ReactNode
}

/**
 * Loading → honest loading line; error → the envelope (never swallowed);
 * data → render. A disabled query renders `idle` (a designed prompt), so a
 * screen with no `?repo=` never shows a spinner forever.
 */
export function QueryBoundary<T>({ query, loading, children, idle }: QueryBoundaryProps<T>) {
  // A disabled query (`enabled: false`) is pending AND idle forever; that is "nothing
  // chosen yet", not "loading", so it gets the designed prompt rather than a spinner.
  if (query.fetchStatus === 'idle' && query.status === 'pending') return <>{idle ?? null}</>
  if (query.isPending) {
    return (
      <p role="status" className="text-sm text-on-surface-muted" data-testid="loading">
        {loading}
      </p>
    )
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  return <>{children(query.data as T)}</>
}
