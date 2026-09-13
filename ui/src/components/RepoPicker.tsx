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
