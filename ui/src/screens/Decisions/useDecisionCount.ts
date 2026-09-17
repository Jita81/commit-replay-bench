/**
 * useDecisions / useDecisionCount — the inbox's rows across every repository, once.
 *
 * Navigation
 * ----------
 * What it is:   One hook that fetches the map, the sign-offs and the factory tasks for
 *               every connected repository and folds them through `decisionsFor`; and a
 *               count for the nav badge.
 * What it does: Keeps the Decisions page and the header badge on the same numbers (one
 *               query set, cached by TanStack), and adds the "signed but stale" rows the
 *               inbox lists separately — a sign-off the API marks `stale` because the
 *               apparatus has moved since it was made.
 * How:          `useQueries` over the connected repositories; `ready` when every query has
 *               either data or the 404 that means "no backlog"; null count until then.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/decisions.ts, ui/src/screens/Decisions/DecisionsPage.tsx,
 *               ui/src/components/Layout.tsx (the badge), ui/src/api/hooks.ts
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx
 * Touch when:   a row source is added.
 */

import { useQueries, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, isApiError, qs } from '../../api/client'
import { keys, useAllRepos } from '../../api/hooks'
import type { CapabilityMap, FactoryTask, Page, Signoff } from '../../api/types'
import { type Decision, decisionsFor } from './decisions'

export interface StaleSignoff {
  repo: string
  signoff: Signoff
}

export interface DecisionsState {
  ready: boolean
  decisions: Decision[]
  stale: StaleSignoff[]
  byRepo: Record<string, Decision[]>
  /** Every repository on record (measured or not) — the empty state's truth, not `byRepo`'s keys. */
  connected: string[]
  errors: string[]
}

function notFound(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

export function useDecisions(): DecisionsState {
  const repos = useAllRepos()
  const names = useMemo(() => (repos.data?.items ?? []).map((r) => r.name), [repos.data])
  const maps = useQueries({
    queries: names.map((repo) => ({
      queryKey: keys.capability(repo, 'capability_class,size'),
      queryFn: () => api<CapabilityMap>(`/capability-map${qs({ repo, by: 'capability_class,size' })}`),
      retry: false,
    })),
  })
  const signoffs = useQueries({
    queries: names.map((repo) => ({
      queryKey: keys.signoffs(repo),
      queryFn: () => api<Page<Signoff>>(`/signoffs${qs({ repo, limit: 500 })}`),
      retry: false,
    })),
  })
  const tasks = useQueries({
    queries: names.map((repo) => ({
      queryKey: keys.factoryTasks(repo),
      queryFn: () => api<FactoryTask[]>(`/factory/${encodeURIComponent(repo)}/tasks`),
      retry: false,
    })),
  })
  return useMemo(() => {
    if (!repos.data) return { ready: false, decisions: [], stale: [], byRepo: {}, connected: [], errors: repos.isError ? [String(repos.error?.message ?? 'repos')] : [] }
    const byRepo: Record<string, Decision[]> = {}
    const stale: StaleSignoff[] = []
    const errors: string[] = []
    let ready = true
    names.forEach((repo, i) => {
      const m = maps[i]
      const s = signoffs[i]
      const t = tasks[i]
      // a 404 is an expected absence (never measured, no backlog): the repo simply has no
      // decisions; any OTHER error means the count is incomplete — never served as ready
      const failures = [m, s, t].flatMap((q) => (q?.isError && !notFound(q.error) ? [q.error] : []))
      if (failures.length > 0) {
        for (const e of failures) errors.push(`${repo}: ${e.message}`)
        ready = false
        return
      }
      // each source is settled when it has data or its permitted 404; the repo counts only
      // when ALL THREE are settled — a settled 404 on one must not hide a pending other
      const settled = (q: { data?: unknown; isError: boolean; error: unknown } | undefined) => q?.data !== undefined || (q?.isError === true && notFound(q.error))
      if (!settled(m) || !settled(s) || !settled(t)) {
        ready = false
        return
      }
      if (!m?.data || !s?.data) return // a permitted 404: never measured / no sign-offs — no decisions here
      byRepo[repo] = decisionsFor({ repo, cells: m.data.cells, signoffs: s.data.items, tasks: t?.data ?? [] })
      for (const so of s.data.items) if (so.stale && !so.revoked) stale.push({ repo, signoff: so })
    })
    // `connected` is every repository on record; `byRepo` only those with a measured map — an
    // unmeasured repository is connected and has no decisions, not "no repository"
    return { ready, decisions: Object.values(byRepo).flat(), stale, byRepo, connected: names, errors }
  }, [repos.data, repos.isError, repos.error, names, maps, signoffs, tasks])
}

/** The nav badge's number: decisions + stale sign-offs; null until every repo answered. */
export function useDecisionCount(): number | null {
  const d = useDecisions()
  return d.ready ? d.decisions.length + d.stale.length : null
}

/** `GET /version` is cheap; the badge re-renders with the count only. */
export function useApparatus(): string {
  const v = useQuery({ queryKey: ['version'], queryFn: () => api<{ apparatus: string }>('/version'), staleTime: 60_000 })
  return v.data?.apparatus ?? ''
}
