/**
 * useDecisions / useDecisionCount — the inbox as the server serves it, once (F6).
 *
 * Navigation
 * ----------
 * What it is:   `useDecisions` reads `GET /decisions` — every due decision across the connected
 *               repositories, each with its act, its link, whether this person can take it and
 *               how long it has waited — and `useDecisionCount` reads `GET /decisions?count=1`
 *               for the nav badge.
 * What it does: Gives the Decisions page and the header badge the SAME derivation, made once on
 *               the server (src/crb/server/decisions.py), instead of five queries per repository
 *               in every browser on every screen (decisions.operations.10). The page's rows keep
 *               the server's order; a stale sign-off (`signoff_stale`) is listed in its own
 *               section. A read that failed keeps its `ApiError` — status, code and message —
 *               and so does each repository the server could not read (G-134): the page says
 *               the count is incomplete and offers a retry, and the badge shows no number
 *               rather than a smaller one.
 * How:          One `useQuery` each. The badge's reading may be held 30 s (the server says so
 *               too, `Cache-Control: private, max-age=30`); the page's list is re-read whenever
 *               the page mounts, because a person who has just acted must not see the act
 *               still waiting. Both are revalidated with the server's `ETag`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/decisions.ts (the row type and labels),
 *               ui/src/screens/Decisions/DecisionsPage.tsx, ui/src/components/Layout.tsx (the
 *               badge), src/crb/server/routes/decisions.py (both readings)
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx,
 *               ui/src/screens/Decisions/useDecisionCount.test.tsx
 * Touch when:   never for a new repository; the served row gains a field the page shows.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { ApiError, api } from '../../api/client'
import type { DecisionCount, DecisionList, DecisionRowOut } from '../../api/types'
import type { Decision, DecisionKind } from './decisions'

/** The page's reading and the badge's: one prefix, so an act anywhere can re-read both. */
export const decisionsKey = ['decisions', 'list'] as const
export const decisionCountKey = ['decisions', 'count'] as const

/** A repository the server could not read, as the error it answered — never a bare string. */
export interface RepoReadError {
  repo: string
  error: ApiError
}

export interface DecisionsState {
  /** True once the reading answered and every repository in it was read. */
  ready: boolean
  /** Every row but the stale sign-offs, in the server's order. */
  decisions: Decision[]
  /** The `signoff_stale` rows: their own section. */
  stale: Decision[]
  byRepo: Record<string, Decision[]>
  /** Every repository on record (measured or not) — the empty state's truth. */
  connected: string[]
  /** The repositories with at least one measured cell. */
  measured: string[]
  /** The reading itself failed: the whole inbox is unknown. */
  error: ApiError | null
  /** Repositories whose inputs the server could not read: the count is incomplete. */
  repoErrors: RepoReadError[]
  /** Read the inbox again (the Retry). */
  refetch: () => void
}

function toDecision(r: DecisionRowOut): Decision {
  return {
    kind: r.kind as DecisionKind,
    repo: r.repo,
    key: r.key,
    title: r.title,
    evidence: r.evidence,
    ...(r.reason_code ? { reasonCode: r.reason_code } : {}),
    act: r.act,
    href: r.href,
    role: r.role,
    canAct: r.can_act,
    ...(r.signoff ? { signoff: r.signoff } : {}),
    ...(r.due_since ? { dueSince: r.due_since, ageS: r.age_s } : {}),
  }
}

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, 'network', e instanceof Error ? e.message : String(e))
}

/** `GET /decisions` — the inbox, its clock and each row's act for this person. */
export function useDecisions(): DecisionsState {
  const q = useQuery({ queryKey: decisionsKey, queryFn: () => api<DecisionList>('/decisions'), retry: false })
  const { refetch } = q
  return useMemo(() => {
    const again = () => void refetch()
    if (q.isError) return { ready: false, decisions: [], stale: [], byRepo: {}, connected: [], measured: [], error: asApiError(q.error), repoErrors: [], refetch: again }
    const body = q.data
    if (!body) return { ready: false, decisions: [], stale: [], byRepo: {}, connected: [], measured: [], error: null, repoErrors: [], refetch: again }
    const rows = body.items.map(toDecision)
    const decisions = rows.filter((d) => d.kind !== 'signoff_stale')
    const byRepo: Record<string, Decision[]> = {}
    for (const d of decisions) (byRepo[d.repo] ??= []).push(d)
    const repoErrors = body.errors.map((e) => ({ repo: e.repo, error: new ApiError(e.status, e.code, e.message) }))
    return {
      ready: repoErrors.length === 0,
      decisions,
      stale: rows.filter((d) => d.kind === 'signoff_stale'),
      byRepo,
      connected: body.repos,
      measured: body.measured,
      error: null,
      repoErrors,
      refetch: again,
    }
  }, [q.data, q.isError, q.error, refetch])
}

/**
 * The nav badge's number: every decision waiting, stale sign-offs included, from the count
 * reading — one request, whatever the number of repositories. `null` until it answers, when it
 * failed, and while any repository could not be read: a smaller number would read as fewer
 * decisions, not as an unknown one.
 */
export function useDecisionCount(): number | null {
  const q = useQuery({ queryKey: decisionCountKey, queryFn: () => api<DecisionCount>('/decisions?count=1'), retry: false, staleTime: 30_000 })
  const body: Partial<DecisionCount> | undefined = q.data
  // a body that is not the count's shape is no number either: the nav never breaks on it
  if (q.isError || typeof body?.total !== 'number' || !Array.isArray(body.errors) || body.errors.length > 0) return null
  return body.total
}

/** `GET /version` is cheap; the badge re-renders with the count only. */
export function useApparatus(): string {
  const v = useQuery({ queryKey: ['version'], queryFn: () => api<{ apparatus: string }>('/version'), staleTime: 60_000 })
  return v.data?.apparatus ?? ''
}
