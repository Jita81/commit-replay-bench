/**
 * GitHubConnectDialog — the picker connects a repository through the installation.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the GitHub connect dialog and the Settings card.
 * What it does: Pins that an unconfigured app is a state with the URL fallback, not an
 *               error; that installations are listed with what they may see; that the
 *               picker lists repositories with suggestions, marks a connected one and
 *               disables it; that picking pre-fills name / language / runner; that a
 *               repository without a language asks for one and the Connect button waits;
 *               that Connect posts `{full_name, name, language, runner}` to the right
 *               installation and hands the new name back; that link mode lists only the
 *               repositories with no GitHub link, posts `{installation_id, full_name}` to
 *               `/repos/{name}/github-link` and selects that repository; and that the
 *               Connect screen opens the picker on `?installation=` (the setup callback's
 *               landing).
 * How:          `mockApi` + `renderApp`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0014-github-app-is-the-connection.md
 * Works with:   ui/src/screens/Connect/GitHubConnectDialog.tsx (the component under test),
 *               ui/src/screens/Settings/GitHubAppCard.tsx (the admin's view of the same `/github/app`),
 *               ui/src/test/utils.tsx (`mockApi` / `renderApp` — the fake API these tests answer from),
 *               src/crb/server/routes/github.py (the routes whose shapes the mocks mirror)
 * Tested by:    ui/src/screens/Connect/GitHubConnectDialog.test.tsx
 * Touch when:   the connect body or the picker row changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { GitHubAppCard } from '../Settings/GitHubAppCard'
import { ConnectPage } from './ConnectPage'
import { GitHubConnectDialog } from './GitHubConnectDialog'

const INSTALL = { id: 77, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: 'https://github.com/organizations/acme/settings/installations/77', suspended: false, permissions: { contents: 'read' }, can_deliver: false, recorded_by: 'u1', updated: 'x' }
const APP = { configured: true, app_slug: 'crb-bench', install_url: 'https://github.com/apps/crb-bench/installations/new', api_url: 'https://api.github.com', installations: [INSTALL] }
const CALC = { full_name: 'acme/Calc', name: 'Calc', html_url: 'https://github.com/acme/Calc', clone_url: 'https://github.com/acme/Calc.git', default_branch: 'main', private: true, language: 'Python', archived: false, suggested: { name: 'acme-calc', language: 'python', runner: 'pytest' }, connected_as: null }
const SITE = { ...CALC, full_name: 'acme/site', name: 'site', clone_url: 'https://github.com/acme/site.git', language: '', suggested: { name: 'acme-site', language: '', runner: '' } }
const DONE = { ...CALC, full_name: 'acme/done', name: 'done', connected_as: 'acme-done' }
const PAGE = { items: [CALC, SITE, DONE], total: 3, page: 1, per_page: 50, has_more: false }

describe('GitHubConnectDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('an unconfigured app is a state with the URL fallback', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] } })
    const onUseUrl = vi.fn()
    renderApp(<GitHubConnectDialog open onClose={() => undefined} onConnected={() => undefined} onUseUrl={onUseUrl} />)
    await waitFor(() => expect(screen.getByText('The GitHub App is not configured on this deployment')).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: /Connect by URL/ })[0]!)
    expect(onUseUrl).toHaveBeenCalled()
  })

  it('lists the installation and its repositories, pre-fills the pick, and connects', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': APP,
      'GET /github/installations/77/repositories': PAGE,
      'POST /github/installations/77/connect': (_u: string, init?: RequestInit) => json({ name: JSON.parse(String(init?.body)).name, language: 'python', runner: 'pytest', url: CALC.clone_url }, 201),
    })
    const onConnected = vi.fn()
    renderApp(<GitHubConnectDialog open onClose={() => undefined} onConnected={onConnected} />)
    await waitFor(() => expect(screen.getByRole('list', { name: 'Repositories' })).toBeInTheDocument())
    expect(screen.getByRole('option', { name: /acme · selected repositories/ })).toBeInTheDocument()
    expect(screen.getByText(/sees only the repositories its admin selected/)).toBeInTheDocument()
    expect(screen.getByText(/read-only: measurement only/)).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Repositories' })
    // a connected repository is marked and cannot be picked again
    const done = within(list).getByRole('button', { name: /acme\/done/ })
    expect(done).toBeDisabled()
    expect(within(done).getByText('connected as acme-done')).toBeInTheDocument()
    // no language → the pick asks for one and Connect waits
    await userEvent.click(within(list).getByRole('button', { name: /acme\/site/ }))
    expect(screen.getByText('GitHub reports no language — choose one')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled()
    // the suggestion pre-fills; Connect posts it
    await userEvent.click(within(list).getByRole('button', { name: /acme\/Calc/ }))
    const confirm = screen.getByTestId('github-connect-confirm')
    expect(within(confirm).getByLabelText(/Name in crb/)).toHaveValue('acme-calc')
    expect(within(confirm).getByLabelText(/Language/)).toHaveValue('python')
    expect(within(confirm).getByLabelText(/Test runner/)).toHaveValue('pytest')
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }))
    await waitFor(() => expect(onConnected).toHaveBeenCalledWith('acme-calc'))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.path).toBe('/github/installations/77/connect')
    expect(JSON.parse(String(post.init?.body))).toEqual({ full_name: 'acme/Calc', name: 'acme-calc', language: 'python', runner: 'pytest' })
  })

  it('link mode lists the repositories without a GitHub link, posts the link and selects the repository', async () => {
    const repo = (name: string, github_full_name: string | null) => ({ name, language: 'go', runner: 'go', url: `https://example.org/${name}.git`, clone_path: '', probe: { status: 'not_probed', run_id: null, checked: null, detail: '' }, task_counts: { total: 0, standard: 0, hard: 0, gold_clean: 0, gold_failed: 0, unchecked: 0 }, last_run: null, created: 'x', updated: 'x', github_full_name })
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': APP,
      'GET /github/installations/77/repositories': PAGE,
      'GET /repos': { items: [repo('cobra', null), repo('acme-done', 'acme/done'), repo('alpha', null)], total: 3, limit: 500, offset: 0 },
      'POST /repos/cobra/github-link': () => json({ ...repo('cobra', 'acme/calc'), url: CALC.clone_url, config: {} }, 200),
    })
    const onConnected = vi.fn()
    renderApp(<GitHubConnectDialog open onClose={() => undefined} onConnected={onConnected} />)
    await waitFor(() => expect(screen.getByRole('list', { name: 'Repositories' })).toBeInTheDocument())
    // the two ways appear only once a repository is picked
    expect(screen.queryByRole('radiogroup', { name: 'How to connect' })).not.toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('list', { name: 'Repositories' })).getByRole('button', { name: /acme\/Calc/ }))
    const modes = screen.getByRole('radiogroup', { name: 'How to connect' })
    expect(within(modes).getByRole('radio', { name: /Register as a new repository/ })).toBeChecked()
    await userEvent.click(within(modes).getByRole('radio', { name: /Link to an existing repository/ }))
    // the new-repository form is gone; the select lists only the rows without a link
    expect(screen.queryByTestId('github-connect-confirm')).not.toBeInTheDocument()
    const select = screen.getByLabelText(/Existing repository/)
    const names = within(select).getAllByRole('option').map((o) => o.textContent)
    expect(names).toEqual(['— choose —', 'cobra', 'alpha'])
    expect(screen.getByText(/keeps its name and its measured evidence/)).toBeInTheDocument()
    // nothing chosen → the button waits
    expect(screen.getByRole('button', { name: 'Link' })).toBeDisabled()
    await userEvent.selectOptions(select, 'cobra')
    await userEvent.click(screen.getByRole('button', { name: 'Link' }))
    await waitFor(() => expect(onConnected).toHaveBeenCalledWith('cobra'))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.path).toBe('/repos/cobra/github-link')
    expect(JSON.parse(String(post.init?.body))).toEqual({ installation_id: 77, full_name: 'acme/Calc' })
  })

  it('the Connect screen opens the picker on ?installation= (the setup callback lands there)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /github/app': APP,
      'GET /github/installations/77/repositories': PAGE,
    })
    renderApp(<ConnectPage />, { route: '/connect?installation=77' })
    await waitFor(() => expect(screen.getByRole('list', { name: 'Repositories' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Connect from GitHub' })).toBeInTheDocument()
  })

  it('the Settings card says configured-or-not and lists installations', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /github/app': APP })
    renderApp(<GitHubAppCard />)
    await waitFor(() => expect(screen.getByTestId('github-app-status')).toHaveTextContent('configured'))
    expect(screen.getByRole('list', { name: 'GitHub App installations' })).toHaveTextContent('acme')
    expect(screen.getByText('read-only')).toBeInTheDocument()
    vi.unstubAllGlobals()
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /github/app': () => envelope(500, 'boom', 'x') })
    renderApp(<GitHubAppCard />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
