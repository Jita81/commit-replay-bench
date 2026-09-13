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
