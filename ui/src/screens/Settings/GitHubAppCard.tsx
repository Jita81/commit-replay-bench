/**
 * GitHubAppCard — is the GitHub App configured, where to install it, what is on record.
 *
 * Navigation
 * ----------
 * What it is:   The Settings card for the enterprise connection: configured or not (and what
 *               an admin sets if not), the install link, and the installations on record
 *               with what each may see and whether it may deliver; an operator can sync.
 * What it does: Tells an admin in one glance whether "Connect from GitHub" will work and
 *               why not; never shows a secret (the API returns none). A read-only
 *               installation says which of the two write permissions delivery needs it
 *               lacks, what it holds today and that Sync installations refreshes the record
 *               after GitHub changes (J-FAC-17). The setup guide is a link into the bundled
 *               docs, not a file path.
 * How:          `useGitHubApp` + `useSyncGitHubInstallations`; `missingForDelivery` reads
 *               `installation.permissions` against the same pair the server's `can_deliver`
 *               checks.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0014-github-app-is-the-connection.md
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (mounts it), src/crb/server/routes/github.py
 *               (`GET /github/app` and the sync it posts to), ui/src/api/hooks.ts (`useGitHubApp`,
 *               `useSyncGitHubInstallations`), ui/src/screens/Connect/GitHubConnectDialog.tsx (the
 *               operator's picker over the same installations), ui/src/components/Help.tsx
 *               (`DocLink`), docs/GITHUB-APP.md (the setup guide it links)
 * Tested by:    ui/src/screens/Settings/GitHubAppCard.test.tsx (the read-only sentence, the
 *               guide link), ui/src/screens/Connect/GitHubConnectDialog.test.tsx (configured
 *               and error states)
 * Touch when:   a field is added to `GitHubAppInfo`, or delivery needs a different permission
 *               pair (src/crb/server/routes/github.py `can_deliver`).
 */

import { useGitHubApp, useSyncGitHubInstallations } from '../../api/hooks'
import type { GitHubInstallation } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { DocLink } from '../../components/Help'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'

/** The two write permissions factory delivery needs (the server's `can_deliver` pair), as GitHub names them. */
const DELIVERY_PERMISSIONS: Array<{ key: string; label: string }> = [
  { key: 'contents', label: 'Contents: write' },
  { key: 'pull_requests', label: 'Pull requests: write' },
]

/** The delivery permissions an installation still lacks, in GitHub's words. */
function missingForDelivery(i: GitHubInstallation): string[] {
  return DELIVERY_PERMISSIONS.filter((p) => i.permissions[p.key] !== 'write').map((p) => p.label)
}

/** One sentence for a read-only installation: measurement only, what to grant, then Sync; what it holds today. */
function ReadOnlyNote({ installation }: { installation: GitHubInstallation }) {
  const missing = missingForDelivery(installation)
  const held = Object.entries(installation.permissions)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ')
  return (
    <p className="m-0 basis-full text-xs text-on-surface-muted">
      Read-only: measurement only.
      {missing.length > 0 ? ` To let the factory deliver, grant ${missing.join(' and ')} on this installation in GitHub, then Sync installations here.` : ' Sync installations here to refresh the record after GitHub changes.'}
      {held ? ` Today it holds ${held}.` : ''}
    </p>
  )
}

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
          <Pill tone="muted" size="xs">not configured</Pill> Set <code>CRB_GITHUB__APP_ID</code> and <code>CRB_GITHUB__PRIVATE_KEY</code> (or <code>_FILE</code>) on the API and the worker, then organisations install the app on selected repositories. Guide: <DocLink to="GITHUB-APP#2-register-the-app-once-per-deployment">Register the GitHub App</DocLink>.
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
                  {!i.can_deliver && <ReadOnlyNote installation={i} />}
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
