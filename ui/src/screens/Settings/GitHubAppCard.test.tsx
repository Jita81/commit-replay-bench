/**
 * ui/src/screens/Settings/GitHubAppCard.tsx — a read-only installation says what it lacks and what
 * to do; the setup guide is a link, not a file path.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Settings GitHub App card against a mocked `GET /github/app`.
 * What it does: Pins that a read-only installation keeps its pill and adds one sentence naming
 *               the two permissions delivery needs, the permissions it holds today and the
 *               Sync step (J-FAC-17); that an installation that can deliver says so without the
 *               instruction; and that the not-configured state links the register-the-app
 *               guide through the bundled docs (J-HEL-20).
 * How:          `mockApi` + `renderApp`; assertions on `github-app-status` and the roles.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0014-github-app-is-the-connection.md
 * Works with:   ui/src/screens/Settings/GitHubAppCard.tsx (the code under test),
 *               ui/src/screens/Connect/GitHubConnectDialog.test.tsx (the configured / error cases),
 *               ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Settings/GitHubAppCard.test.tsx
 * Touch when:   the permissions delivery needs change (src/crb/server/routes/github.py `can_deliver`).
 */
import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GitHubAppInfo, GitHubInstallation } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { GitHubAppCard } from './GitHubAppCard'

const READ_ONLY: GitHubInstallation = {
  id: 77,
  account_login: 'acme',
  account_type: 'Organization',
  repository_selection: 'selected',
  html_url: 'https://github.com/organizations/acme/settings/installations/77',
  suspended: false,
  permissions: { contents: 'read', metadata: 'read' },
  can_deliver: false,
  recorded_by: 'u1',
  updated: 'x',
}
const WRITER: GitHubInstallation = { ...READ_ONLY, id: 78, account_login: 'beta', permissions: { contents: 'write', pull_requests: 'write', metadata: 'read' }, can_deliver: true }

const APP: GitHubAppInfo = { configured: true, app_slug: 'crb', api_url: 'https://api.github.com', install_url: 'https://github.com/apps/crb/installations/new', installations: [READ_ONLY, WRITER] }

describe('GitHubAppCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a read-only installation names the missing permissions, what it holds and the Sync step; a writer does not', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'admin' }, 'GET /github/app': APP })
    renderApp(<GitHubAppCard />)
    const list = await screen.findByRole('list', { name: 'GitHub App installations' })
    const rows = list.querySelectorAll('li')
    expect(rows).toHaveLength(2)
    const acme = rows[0]!
    expect(acme.textContent).toContain('read-only')
    expect(acme.textContent).toContain('Read-only: measurement only. To let the factory deliver, grant Contents: write and Pull requests: write on this installation in GitHub, then Sync installations here. Today it holds contents: read, metadata: read.')
    const beta = rows[1]!
    expect(beta.textContent).toContain('can deliver')
    expect(beta.textContent).not.toContain('To let the factory deliver')
  })

  it('a read-only installation with one write permission names only the one still missing', async () => {
    const half = { ...READ_ONLY, permissions: { contents: 'write', metadata: 'read' } }
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'admin' }, 'GET /github/app': { ...APP, installations: [half] } })
    renderApp(<GitHubAppCard />)
    const list = await screen.findByRole('list', { name: 'GitHub App installations' })
    expect(list.textContent).toContain('grant Pull requests: write on this installation')
    expect(list.textContent).not.toContain('grant Contents: write')
  })

  it('not configured links the register-the-app guide through the bundled docs', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'admin' }, 'GET /github/app': { configured: false, app_slug: '', api_url: '', install_url: '', installations: [] } })
    renderApp(<GitHubAppCard />)
    await waitFor(() => expect(screen.getByTestId('github-app-status')).toHaveTextContent('not configured'))
    expect(screen.getByRole('link', { name: 'Register the GitHub App' })).toHaveAttribute('href', '/help/docs/GITHUB-APP#2-register-the-app-once-per-deployment')
    expect(screen.queryByText('docs/GITHUB-APP.md')).toBeNull()
  })
})
