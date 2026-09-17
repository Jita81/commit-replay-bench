/**
 * GitHubAppCard — is the GitHub App configured, where to install it, what is on record.
 *
 * Navigation
 * ----------
 * What it is:   The Settings card for the enterprise connection: configured or not (and what
 *               an admin sets if not), the install link, and the installations on record
 *               with what each may see and whether it may deliver; an operator can sync.
 * What it does: Tells an admin in one glance whether "Connect from GitHub" will work and
 *               why not; never shows a secret (the API returns none).
 * How:          `useGitHubApp` + `useSyncGitHubInstallations`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0014-github-app-is-the-connection.md
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (mounts it), src/crb/server/routes/github.py
 * Tested by:    ui/src/screens/Connect/GitHubConnectDialog.test.tsx (the card is covered there)
 * Touch when:   a field is added to `GitHubAppInfo`.
 */

import { useGitHubApp, useSyncGitHubInstallations } from '../../api/hooks'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'

export function GitHubAppCard() {
  const { can } = useAuth()
  const app = useGitHubApp()
  const sync = useSyncGitHubInstallations()
  return (
    <Card
      title="GitHub App"
      eyebrow="the enterprise connection · no tokens handed over"
      actions={
        app.data?.configured && can('operator') ? (
          <Button size="sm" disabled={sync.isPending} onClick={() => sync.mutate()}>
            Sync installations
          </Button>
        ) : undefined
      }
    >
      {app.isError && <ErrorState error={app.error} onRetry={() => void app.refetch()} />}
      {app.data && !app.data.configured && (
        <p className="m-0 text-sm text-on-surface-body" data-testid="github-app-status">
          <Pill tone="muted" size="xs">not configured</Pill> Set <code>CRB_GITHUB__APP_ID</code> and <code>CRB_GITHUB__PRIVATE_KEY</code> (or <code>_FILE</code>) on the API and the worker, then organisations install the app on selected repositories — <code>docs/GITHUB-APP.md</code>.
        </p>
      )}
      {app.data?.configured && (
        <div className="space-y-2 text-sm" data-testid="github-app-status">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone="green" size="xs" glyph="✓">configured</Pill>
            <span className="font-mono text-xs">{app.data.app_slug}</span>
            <span className="font-mono text-xs text-on-surface-muted">{app.data.api_url}</span>
            {app.data.install_url && (
              <a className="text-xs" href={app.data.install_url} target="_blank" rel="noreferrer">
                Install on an organisation ↗
              </a>
            )}
          </div>
          {app.data.installations.length === 0 ? (
            <p className="m-0 text-xs text-on-surface-muted">No installation on record yet.</p>
          ) : (
            <ul className="m-0 list-none divide-y divide-border p-0" aria-label="GitHub App installations">
              {app.data.installations.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <span className="font-semibold">{i.account_login}</span>
                  <span className="text-xs text-on-surface-muted">{i.account_type} · {i.repository_selection === 'all' ? 'all repositories' : 'selected repositories'}</span>
                  <Pill tone={i.can_deliver ? 'primary' : 'muted'} size="xs">{i.can_deliver ? 'can deliver' : 'read-only'}</Pill>
                  {i.suspended && <Pill tone="red" size="xs">uninstalled</Pill>}
                  <span className="num ml-auto font-mono text-[11px] text-on-surface-muted">#{i.id}</span>
                </li>
              ))}
            </ul>
          )}
          {sync.isError && <ErrorState compact error={sync.error} />}
        </div>
      )}
    </Card>
  )
}
