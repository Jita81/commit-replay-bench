/**
 * GitHubConnectDialog — pick a repository from an installation of the GitHub App and connect it.
 *
 * Navigation
 * ----------
 * What it is:   The enterprise way onto the Connect walk: choose an installation (the org
 *               that installed the app, and what it may see), search its repositories, pick
 *               one, then either register it as a NEW crb repository (confirm the pre-filled
 *               name / language / runner) or LINK it to an existing one (a repository
 *               measured before the app existed, or whose history now lives on a fork —
 *               it keeps its name and its evidence; its URL becomes the clone URL). Where
 *               the app is not configured, the dialog says what an admin does instead and
 *               offers the URL path.
 * What it does: Makes "connect a repository" the org-install → repository-selection flow
 *               every comparable product uses (docs/GITHUB-APP.md, ADR-0014) without asking
 *               anyone for a token: the deployment's app mints its own. Repositories already
 *               connected are marked and cannot be connected twice; a repository GitHub
 *               reports no language for asks for one; the link select offers only rows with
 *               no GitHub link; the operator role gates both acts, as the API does.
 * How:          `useGitHubApp` (configured? installations?), `useSyncGitHubInstallations`,
 *               `useGitHubRepos(installation, q, page)`, then `useConnectGitHubRepo` (new) or
 *               `useLinkRepoToGitHub` (existing, over `useAllRepos` filtered to
 *               `github_full_name === null`) → on success `onConnected(name)` (the Connect
 *               screen navigates to the walk).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0014-github-app-is-the-connection.md
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (opens it), ui/src/api/hooks.ts
 *               (`useConnectGitHubRepo`, `useLinkRepoToGitHub`, `useAllRepos`),
 *               ui/src/api/types.ts (`RepoSummary.github_full_name`),
 *               src/crb/server/routes/github.py (the routes), docs/GITHUB-APP.md
 * Tested by:    ui/src/screens/Connect/GitHubConnectDialog.test.tsx
 * Touch when:   the connect body grows a field (mirror `ConnectRequest`); the link body
 *               changes (mirror `LinkRequest`).
 */

import { useEffect, useMemo, useState } from 'react'
import { useAllRepos, useConnectGitHubRepo, useGitHubApp, useGitHubRepos, useLinkRepoToGitHub, useSyncGitHubInstallations } from '../../api/hooks'
import { LANGUAGES, RUNNERS, type GitHubPickerRepo, type Language, type Runner } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextField } from '../../components/Field'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'

type ConnectMode = 'new' | 'link'

const MODES: ReadonlyArray<{ id: ConnectMode; title: string; note: string }> = [
  { id: 'new', title: 'Register as a new repository', note: 'A new crb repository, named from the suggestion; its evidence starts here.' },
  { id: 'link', title: 'Link to an existing repository', note: 'A repository measured before the app existed, or whose history now lives on this fork.' },
]

interface Props {
  open: boolean
  onClose: () => void
  onConnected: (name: string) => void
  /** Preselect an installation (the setup callback lands on `/connect?installation=`). */
  initialInstallation?: number
  /** The callback carried no signed state for this session, so the installation was NOT
   * recorded (`/connect?installation=&unverified=1`): offer the sync that records it. */
  landedUnverified?: boolean
  /** Offer the URL path (the dialog the walk had before the app existed). */
  onUseUrl?: () => void
}

export function GitHubConnectDialog({ open, onClose, onConnected, initialInstallation, landedUnverified = false, onUseUrl }: Props) {
  const { can } = useAuth()
  const app = useGitHubApp()
  const sync = useSyncGitHubInstallations()
  const connect = useConnectGitHubRepo()
  const link = useLinkRepoToGitHub()
  const [installation, setInstallation] = useState<number>(initialInstallation ?? 0)
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [picked, setPicked] = useState<GitHubPickerRepo | null>(null)
  const [name, setName] = useState('')
  const [language, setLanguage] = useState<Language | ''>('')
  const [runner, setRunner] = useState<Runner | ''>('')
  // 'new' = register a new crb repository (today's form); 'link' = attach the picked GitHub
  // repository to a repository that already exists (it keeps its name and its evidence)
  const [mode, setMode] = useState<ConnectMode>('new')
  const [existing, setExisting] = useState('')
  const allRepos = useAllRepos()
  const unlinked = useMemo(() => (allRepos.data?.items ?? []).filter((r) => !r.github_full_name), [allRepos.data])

  const installations = useMemo(() => (app.data?.installations ?? []).filter((i) => !i.suspended), [app.data])
  // the selected installation is always one of the ACTIVE options: a preselected id that is
  // suspended or not on record falls back to the first active one (the picker, the repos
  // query and the connect request all read the same state)
  useEffect(() => {
    if (installations.length === 0) return
    if (installations.some((i) => i.id === installation)) return
    const wanted = initialInstallation ? installations.find((i) => i.id === initialInstallation) : undefined
    setInstallation(wanted ? wanted.id : installations[0]!.id)
    // a repository picked under the replaced installation must not be sent under the new one
    setPicked(null)
    setName('')
    setLanguage('')
    setRunner('')
    setExisting('')
    setPage(1)
  }, [installation, installations, initialInstallation])
  const landedOnRecord = !initialInstallation || installations.some((i) => i.id === initialInstallation)
  const syncAndSelect = () =>
    sync.mutate(undefined, {
      onSuccess: (rows) => {
        if (initialInstallation && rows.some((r) => r.id === initialInstallation && !r.suspended)) setInstallation(initialInstallation)
      },
    })
  const repos = useGitHubRepos(installation, q, page)

  const pick = (r: GitHubPickerRepo) => {
    setPicked(r)
    setName(r.suggested.name)
    setLanguage((r.suggested.language || '') as Language | '')
    setRunner((r.suggested.runner || '') as Runner | '')
  }
  const submit = () => {
    if (!picked) return
    if (mode === 'link') {
      if (!existing) return
      link.mutate({ name: existing, installation, full_name: picked.full_name }, { onSuccess: (repo) => onConnected(repo.name) })
      return
    }
    if (!language) return
    connect.mutate(
      { installation, body: { full_name: picked.full_name, name: name.trim() || undefined, language, runner: runner || undefined } },
      { onSuccess: (repo) => onConnected(repo.name) },
    )
  }
  const ready = mode === 'link' ? Boolean(existing) : Boolean(language)
  const pending = connect.isPending || link.isPending

  const current = installations.find((i) => i.id === installation)

  return (
    <Dialog
      open={open}
      title="Connect from GitHub"
      onClose={onClose}
      width="lg"
      footer={
        app.data && !app.data.configured ? (
          // nothing can be connected from here until an admin registers the app: the body's
          // one "Connect by URL" is the whole offer, so the footer only closes
          <Button onClick={onClose}>Cancel</Button>
        ) : (
          <>
            {onUseUrl && (
              <Button variant="ghost" onClick={onUseUrl}>
                Connect by URL instead
              </Button>
            )}
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="filled" disabled={!picked || !ready || !can('operator') || pending} onClick={submit}>
              {mode === 'link' ? 'Link' : 'Connect'}
            </Button>
          </>
        )
      }
    >
      {app.isError && <ErrorState error={app.error} onRetry={() => void app.refetch()} />}
      {app.data && !app.data.configured && (
        <EmptyState
          glyph="⎇"
          title="The GitHub App is not configured on this deployment"
          reason="An admin registers the app once (docs/GITHUB-APP.md: app id + private key in the environment), then an org admin installs it on the repositories it may see. Until then, connect by URL."
          action={onUseUrl ? <Button onClick={onUseUrl}>Connect by URL</Button> : undefined}
        />
      )}
      {app.data?.configured && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <SelectField label="Installation (the organisation that installed the app)" value={installation} onChange={(e) => { setInstallation(Number(e.target.value)); setPage(1); setPicked(null) }} className="min-w-[24ch]">
              {installations.length === 0 && <option value={0}>— none on record —</option>}
              {installations.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.account_login} · {i.repository_selection === 'all' ? 'all repositories' : 'selected repositories'}
                  {i.can_deliver ? ' · can deliver' : ''}
                </option>
              ))}
            </SelectField>
            {can('operator') && (
              <Button size="sm" disabled={sync.isPending} onClick={syncAndSelect}>
                Sync installations
              </Button>
            )}
            {app.data.install_url && (
              <a className="text-sm" href={app.data.install_url} target="_blank" rel="noreferrer">
                Install the app on another organisation ↗
              </a>
            )}
          </div>
          {sync.isError && <ErrorState compact error={sync.error} />}
          {initialInstallation && !landedOnRecord && (
            <div className="border-l-4 border-status-amber-fill bg-status-amber-soft p-3 text-sm" role="status" data-testid="installation-unrecorded">
              <p className="m-0 font-semibold">GitHub sent installation {initialInstallation} back, but it is not on record.</p>
              <p className="m-0 mt-1">
                {landedUnverified
                  ? 'The link you arrived on carried no signed state for your session, so nothing was recorded automatically. '
                  : ''}
                Press <strong>Sync installations</strong> to record it: the deployment verifies it with the app’s own credential before anything is written.
              </p>
            </div>
          )}
          {current && (
            <p className="m-0 text-xs text-on-surface-muted">
              {current.repository_selection === 'selected'
                ? 'This installation sees only the repositories its admin selected; a repository missing here is added in GitHub under the app’s repository access.'
                : 'This installation sees every repository in the organisation.'}
              {current.can_deliver ? ' It may push branches and open pull requests, so the factory can deliver.' : ' It is read-only: measurement only — the factory cannot deliver until write access is granted.'}
            </p>
          )}
          {installations.length === 0 && (
            <EmptyState compact glyph="⎇" title="No installation on record" reason="Install the app on an organisation (the link above), or sync if it was installed already." />
          )}
          {installation > 0 && (
            <>
              <TextField label="Find a repository" placeholder="owner/name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
              {repos.isPending && <p className="text-sm text-on-surface-muted">Loading repositories…</p>}
              {repos.isError && <ErrorState compact error={repos.error} onRetry={() => void repos.refetch()} />}
              {repos.data && repos.data.items.length === 0 && (
                <EmptyState
                  compact
                  title={q ? 'No repository matches on this page' : 'No repositories'}
                  reason={q && repos.data.has_more ? 'The search filters one page of GitHub’s listing at a time; press Next to keep looking.' : undefined}
                />
              )}
              {repos.data && repos.data.items.length > 0 && (
                <ul className="m-0 max-h-72 list-none divide-y divide-border overflow-y-auto rounded-[var(--radius-control)] border border-border p-0" aria-label="Repositories">
                  {repos.data.items.map((r) => {
                    const chosen = picked?.full_name === r.full_name
                    return (
                      <li key={r.full_name}>
                        <button
                          type="button"
                          className={`flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm ${chosen ? 'bg-primary-container' : 'hover:bg-surface-high'}`}
                          disabled={Boolean(r.connected_as) || r.archived}
                          aria-pressed={chosen}
                          onClick={() => pick(r)}
                        >
                          <span className="font-mono text-xs">{r.full_name}</span>
                          {r.private && <Pill tone="muted" size="xs">private</Pill>}
                          {r.language && <span className="text-xs text-on-surface-muted">{r.language}</span>}
                          {r.archived && <Pill tone="muted" size="xs">archived</Pill>}
                          {r.connected_as && (
                            <Pill tone="green" size="xs" glyph="✓">
                              connected as {r.connected_as}
                            </Pill>
                          )}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
              {repos.data && (repos.data.has_more || page > 1) && (
                <div className="flex gap-2 text-xs">
                  <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                    Previous
                  </Button>
                  <Button size="sm" disabled={!repos.data.has_more} onClick={() => setPage((p) => p + 1)}>
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
          {picked && (
            <div role="radiogroup" aria-label="How to connect" className="grid gap-2 sm:grid-cols-2">
              {MODES.map((m) => (
                <label key={m.id} className={`flex cursor-pointer items-start gap-2 rounded-[var(--radius-control)] border px-3 py-2 text-sm ${mode === m.id ? 'border-primary bg-primary-container' : 'border-border'}`}>
                  <input type="radio" name="github-connect-mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} className="mt-1" />
                  <span className="min-w-0">
                    <span className="block font-semibold">{m.title}</span>
                    <span className="block text-xs text-on-surface-muted">{m.note}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          {picked && mode === 'link' && (
            <div className="space-y-2 rounded-[var(--radius-control)] border border-border p-3" data-testid="github-link-existing">
              <SelectField label="Existing repository" value={existing} onChange={(e) => setExisting(e.target.value)} hint={unlinked.length === 0 && allRepos.data ? 'Every repository already has a GitHub link.' : 'Only repositories with no GitHub link are listed.'}>
                <option value="">— choose —</option>
                {unlinked.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name}
                  </option>
                ))}
              </SelectField>
              {allRepos.isError && <ErrorState compact error={allRepos.error} onRetry={() => void allRepos.refetch()} />}
              <p className="m-0 text-xs text-on-surface-muted">
                The repository keeps its name and its measured evidence; its URL becomes <code>{picked.clone_url}</code>, cloned with a short-lived installation token. Language, runner and layout are not changed — edit them under Configuration if the fork differs. The link is recorded on the repository’s events.
              </p>
            </div>
          )}
          {picked && mode === 'new' && (
            <div className="grid gap-3 rounded-[var(--radius-control)] border border-border p-3 sm:grid-cols-3" data-testid="github-connect-confirm">
              <TextField label="Name in crb" value={name} onChange={(e) => setName(e.target.value)} hint="lowercase; the ledger key" />
              <SelectField label="Language" value={language} onChange={(e) => setLanguage(e.target.value as Language | '')} error={language ? undefined : 'GitHub reports no language — choose one'}>
                <option value="">— choose —</option>
                {LANGUAGES.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Test runner" value={runner} onChange={(e) => setRunner(e.target.value as Runner | '')} hint="the probe verifies it">
                <option value="">— default —</option>
                {RUNNERS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </SelectField>
              <p className="m-0 text-xs text-on-surface-muted sm:col-span-3">
                Clones <code>{picked.clone_url}</code> with a short-lived installation token; default branch <code>{picked.default_branch}</code>. Source and test layout can be adjusted afterwards under Configuration.
              </p>
            </div>
          )}
          {connect.isError && <ErrorState compact error={connect.error} />}
          {link.isError && <ErrorState compact error={link.error} />}
          {!can('operator') && <p className="m-0 text-xs text-on-surface-muted">Connecting needs the operator role.</p>}
        </div>
      )}
    </Dialog>
  )
}
