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
 * How:          `useSearchParams` with `replace: true` (no history entry per change); the
 *               select renders an honest placeholder while loading or when no repo exists.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useRepos`), ui/src/components/Field.tsx (`InlineSelect`),
 *               ui/src/screens/Capability/CapabilityPage.tsx and ui/src/screens/Signoff/SignoffPage.tsx
 *               (typical consumers — the page header's actions slot),
 *               ui/src/components/QueryBoundary.tsx (its `idle` branch is what an empty
 *               `?repo=` shows)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx, ui/src/screens/Routing/RoutingPage.test.tsx
 *               and ui/src/screens/Signoff/SignoffPage.test.tsx (each renders with `?repo=`),
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   never for a new repository (a newly added repo appears in the list).
 */
import { useSearchParams } from 'react-router'
import { useRepos } from '../api/hooks'
import { InlineSelect } from './Field'

/** Reads/writes `?repo=` and offers the known repos. Returns the selected name. */
export function useRepoParam(): [string, (name: string) => void] {
  const [params, setParams] = useSearchParams()
  const repo = params.get('repo') ?? ''
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
  const repos = useRepos()
  const names = repos.data?.items.map((r) => r.name) ?? []
  const known = value && !names.includes(value) ? [value, ...names] : names
  return (
    <InlineSelect label="Repo" value={value} onChange={(e) => onChange(e.target.value)} data-testid="repo-picker">
      <option value="">{repos.isLoading ? 'Loading…' : known.length ? 'Choose a repo' : 'No repos yet'}</option>
      {known.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </InlineSelect>
  )
}
