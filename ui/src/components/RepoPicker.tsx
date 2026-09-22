/**
 * RepoPicker — the ?repo= selector shared by every per-repository screen.
 *
 * Navigation
 * ----------
 * What it is:   `useRepoParam` (read / write `?repo=` in the URL) and the `RepoPicker` select.
 * What it does: Keeps the chosen repository in the query string so a screen URL is
 *               shareable and the choice survives navigation between Capability, Routing,
 *               Oracle, Ledger and Sign-off; offers the repos from `GET /repos` and keeps an
 *               unknown value from the URL selectable rather than silently dropping it.
 *               With `defaultToLatest` a screen reached without `?repo=` chooses the most
 *               recently updated repository itself (Home's rule) instead of asking the
 *               person to do by hand what the previous screen did for them; with no
 *               repository at all the empty state stays.
 * How:          `useSearchParams` with `replace: true` (no history entry per change, and the
 *               default is written with replace too so Back leaves the screen, not the
 *               choice); the select renders an honest placeholder while loading or when no
 *               repo exists.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useAllRepos`), ui/src/components/Field.tsx (`InlineSelect`),
 *               ui/src/screens/Results/ResultsPage.tsx and
 *               ui/src/screens/Signoff/SignoffPage.tsx (`defaultToLatest` — the two screens
 *               the afternoon ends on), ui/src/screens/Home/HomePage.tsx (the same
 *               most-recently-updated rule), ui/src/screens/Capability/CapabilityPage.tsx
 *               (a typical consumer — the page header's actions slot),
 *               ui/src/components/QueryBoundary.tsx (its `idle` branch is what an empty
 *               `?repo=` shows)
 * Tested by:    ui/src/screens/Results/ResultsPage.test.tsx (`defaultToLatest`),
 *               ui/src/screens/Capability/CapabilityPage.test.tsx,
 *               ui/src/screens/Routing/RoutingPage.test.tsx
 *               and ui/src/screens/Signoff/SignoffPage.test.tsx (each renders with `?repo=`),
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   never for a new repository (a newly added repo appears in the list).
 */
import { useEffect } from 'react'
import { useSearchParams } from 'react-router'
import { useAllRepos } from '../api/hooks'
import type { RepoSummary } from '../api/types'
import { InlineSelect } from './Field'

/** The most recently updated repository's name — Home's rule, shared. Empty with none. */
export function latestRepoName(items: readonly Pick<RepoSummary, 'name' | 'updated'>[]): string {
  return items.slice().sort((a, b) => (b.updated > a.updated ? 1 : -1))[0]?.name ?? ''
}

/**
 * Reads/writes `?repo=` and offers the known repos. Returns the selected name. With
 * `defaultToLatest`, an absent `?repo=` is filled with the most recently updated repository
 * once the list has one (written with replace, so the URL stays shareable and Back leaves
 * the screen); a deployment with no repository keeps the empty value.
 */
export function useRepoParam(opts: { defaultToLatest?: boolean } = {}): [string, (name: string) => void] {
  const [params, setParams] = useSearchParams()
  const repo = params.get('repo') ?? ''
  const repos = useAllRepos()
  const latest = opts.defaultToLatest && !repo ? latestRepoName(repos.data?.items ?? []) : ''
  useEffect(() => {
    if (!latest) return
    const next = new URLSearchParams(params)
    next.set('repo', latest)
    setParams(next, { replace: true })
  }, [latest, params, setParams])
  const set = (name: string) => {
    const next = new URLSearchParams(params)
    if (name) next.set('repo', name)
    else next.delete('repo')
    setParams(next, { replace: true })
  }
  return [repo, set]
}

/** The select for the actions slot; an unknown `value` from the URL stays selectable so the URL is not silently rewritten. */
export function RepoPicker({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const repos = useAllRepos() // every page, so no repository is missing from the select
  const names = repos.data?.items.map((r) => r.name) ?? []
  const known = value && !names.includes(value) ? [value, ...names] : names
  return (
    <InlineSelect label="Repo" hint="field.shared.repo_picker" value={value} onChange={(e) => onChange(e.target.value)} data-testid="repo-picker">
      <option value="">{repos.isLoading ? 'Loading…' : known.length ? 'Choose a repo' : 'No repos yet'}</option>
      {known.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </InlineSelect>
  )
}
