/**
 * HomePage — the seven tasks derive their status from the API; nothing is kept locally.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Get-started task list.
 * What it does: Pins that a deployment with the app configured, a probed + mined repository
 *               with oracle and controls done but nothing measured reads "4 of 7"
 *               (connect, choose, shape, prove complete; measure incomplete; map cannot
 *               start; approver — an admin who can list users sees one exists), that the
 *               degraded sandbox is an "Important" banner, and that the cost statement and
 *               "Why two people" are present.
 * How:          `mockApi` + `renderApp`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Home/HomePage.tsx, ui/src/screens/Connect/connection.ts
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx
 * Touch when:   a task or its evidence source changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { HomePage } from './HomePage'

const REPO = {
  name: 'alpha',
  language: 'python',
  runner: 'pytest',
  url: 'https://github.com/acme/alpha',
  clone_path: '',
  probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: 'pytest 8' },
  task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 },
  last_run: null,
  created: '2026-09-17T00:00:00Z',
  updated: '2026-09-17T00:00:00Z',
  config: {},
}
const EMPTY_MAP = { repo: 'alpha', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [], summary: { trusted_autonomy_coverage: 0, total_cells: 0, measured_cells: 0, deliver_cells: 0, n_total: 0, false_q1_total: 0, apparatus_versions: [] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

describe('HomePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('derives the seven tasks from the API and counts the completed ones', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [{ id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: {}, can_deliver: false, recorded_by: '', updated: '' }] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: 'docker not reachable', data: {} }] },
      'GET /users': { items: [{ id: 'u2', username: 'ada', display_name: 'Ada', email: '', role: 'approver', issuer: 'local', created: '' }], total: 1, limit: 50, offset: 0 },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 5 of 7 tasks.')).toBeInTheDocument())
    const list = screen.getByRole('list', { name: 'Tasks' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(7)
    expect(rows[0]).toHaveTextContent('Connect GitHub')
    expect(rows[0]).toHaveTextContent('Completed')
    expect(rows[3]).toHaveTextContent('Prove the instrument (£0)')
    expect(rows[3]).toHaveTextContent('Completed')
    expect(rows[4]).toHaveTextContent('Measure — spends money')
    expect(rows[4]).toHaveTextContent('Incomplete')
    expect(rows[5]).toHaveTextContent('Cannot start yet')
    expect(rows[6]).toHaveTextContent('Invite an approver')
    expect(rows[6]).toHaveTextContent('Completed')
    expect(within(rows[4]!).getByRole('link')).toHaveAttribute('href', '/connect/alpha/measure')
    // the degraded sandbox is the Important banner; the cost statement and why two people
    expect(screen.getByRole('region', { name: 'Important' })).toHaveTextContent('The sandbox probe is degraded on this host.')
    expect(screen.getByText(/Tasks 1 to 4 cost nothing/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Why two people' })).toBeInTheDocument()
  })

  it('a viewer reads the same list as a progress report, a measurement in flight is "In progress", and the map opens from the first row', async () => {
    const running = { ...REPO, last_run: { id: 'r9', kind: 'replay', status: 'running', created: '2026-09-17T10:00:00Z' } }
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [running], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': running,
      'GET /oracle/alpha': { repo: 'alpha', policy: {}, tasks: [{ task_id: 't1', strength: 0.9 }], cells: [], apparatus_versions: ['2.2'] },
      'GET /oracle/alpha/controls': { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 },
      'GET /capability-map': { ...EMPTY_MAP, summary: { ...EMPTY_MAP.summary, n_total: 6 } },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('The operators have completed 3 of 7 tasks.')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Where this deployment is' })).toBeInTheDocument()
    expect(screen.getByText(/You can read everything here and change nothing/)).toBeInTheDocument()
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    // no App configured but a repository connected by URL: the connection task is optional, not a blocker
    expect(rows[0]).toHaveTextContent('Optional')
    expect(rows[4]).toHaveTextContent('In progress')
    expect(within(rows[4]!).getByRole('link')).toHaveAttribute('href', '/connect/alpha')
    expect(rows[5]).toHaveTextContent('Read the map')
    expect(rows[5]).toHaveTextContent('Incomplete')
    // a non-admin is not sent to a settings page that refuses them
    expect(within(rows[6]!).getByRole('link')).toHaveAttribute('href', '/posture')
    expect(screen.getByRole('link', { name: /Continue/ })).toHaveAttribute('href', '/results?repo=alpha')
  })

  it('an App that is configured with no installation on record is "Incomplete", never "Completed" because a repository exists', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: true, app_slug: 'crb', install_url: 'x', api_url: 'y', installations: [] },
      'GET /repos': { items: [REPO], total: 1, limit: 500, offset: 0 },
      'GET /repos/alpha': REPO,
      'GET /oracle/alpha': () => envelope(404, 'not_found', 'x'),
      'GET /oracle/alpha/controls': () => envelope(404, 'not_found', 'x'),
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'ok', probes: [] },
      'GET /users': () => envelope(403, 'forbidden', 'x'),
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 2 of 7 tasks.')).toBeInTheDocument())
    const rows = within(screen.getByRole('list', { name: 'Tasks' })).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Incomplete')
  })

  it('with nothing connected every task after the first is not started', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /repos': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: {} }] },
      'GET /users': () => envelope(403, 'forbidden', 'x'),
    })
    renderApp(<HomePage />, { route: '/home' })
    await waitFor(() => expect(screen.getByText('You have completed 0 of 7 tasks.')).toBeInTheDocument())
    expect(screen.getByText('Not configured')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Important' })).not.toBeInTheDocument()
  })
})
