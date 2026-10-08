/**
 * govuk.tsx — the patterns render what they say and nothing else.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the GOV.UK / NHS pattern components and the Posture page.
 * What it does: Pins the task list's "completed n of m" and row links, and that its status tag
 *               may wrap (a long one scrolled Home sideways at 375 px); the summary list's
 *               key / value / change cells and that a hinted row opens from its value with
 *               the key as its About label; the banner's landmark and title; the
 *               confirmation panel's reference; the details pattern (a native `<details>`
 *               whose summary is the one line shown, closed unless `open`); and that the
 *               posture page renders every group from the API without a secret value.
 * How:          Plain renders; `mockApi` + `renderApp` for the page.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/govuk.tsx (the code under test),
 *               ui/src/screens/Posture/PosturePage.tsx (rendered through `renderApp`),
 *               ui/src/components/Hint.tsx (a summary row's trigger), ui/src/components/Help.tsx
 *               (`collectHints` — the About label a row gets), ui/src/help/hints.ts (the copy)
 * Tested by:    ui/src/components/govuk.test.tsx
 * Touch when:   never for a new repository (the patterns are the product's own); a pattern
 *               is added.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HINTS } from '../help/hints'
import { PosturePage } from '../screens/Posture/PosturePage'
import { GOLIVE } from '../test/golive'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../test/utils'
import type { LedgerVerify } from '../api/types'
import { collectHints } from './Help'
import { ConfirmationPanel, Details, NotificationBanner, SummaryList, Tag, TaskList } from './govuk'

describe('govuk patterns', () => {
  it('a task list status wraps at phone width instead of pushing the page sideways (P-315)', () => {
    render(
      <MemoryRouter>
        <TaskList completed={0} tasks={[{ num: 8, name: 'Deliver your first change', status: 'Backlog frozen — run the factory', tone: 'blue', to: '/factory' }]} />
      </MemoryRouter>,
    )
    const tag = screen.getByText('Backlog frozen — run the factory')
    expect(tag.className).toContain('whitespace-normal')
    expect(tag.className).not.toContain('whitespace-nowrap')
  })

  it('task list, summary list, banner and confirmation panel', () => {
    render(
      <MemoryRouter>
        <TaskList completed={1} tasks={[{ num: 1, name: 'Connect GitHub', status: 'Completed', tone: 'pale', to: '/connect' }, { num: 2, name: 'Measure', status: 'Incomplete', tone: 'blue', onClick: () => undefined }]} />
        <SummaryList rows={[{ key: 'Test prefix', value: 'tests/', note: 'wrong prefix: the belts cannot tell a fix from a test edit', changeTo: '/repos/x' }]} />
        <NotificationBanner title="Important">The sandbox probe is degraded.</NotificationBanner>
        <ConfirmationPanel title="Sign-off recorded" reference="sgn_7f3c04a9" />
      </MemoryRouter>,
    )
    expect(screen.getByText('You have completed 1 of 2 tasks.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Connect GitHub/ })).toHaveAttribute('href', '/connect')
    expect(screen.getByRole('button', { name: /Measure/ })).toBeInTheDocument()
    expect(screen.getAllByText('Test prefix').length).toBeGreaterThan(0) // the key and the sr-only change label
    expect(screen.getByText('wrong prefix: the belts cannot tell a fix from a test edit')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Change/ })).toHaveAttribute('href', '/repos/x')
    expect(screen.getByRole('region', { name: 'Important' })).toHaveTextContent('The sandbox probe is degraded.')
    expect(screen.getByText('sgn_7f3c04a9')).toBeInTheDocument()
  })

  it('a hinted summary row is the trigger as a whole: hovering the VALUE opens the hint, and the About block lists it under the key', async () => {
    render(
      <MemoryRouter>
        <SummaryList rows={[{ key: 'Roles', value: 'four', hint: 'summary.posture.roles', changeTo: '/posture' }, { key: 'Plain', value: '2', hint: 'summary.posture.roles' }]} />
      </MemoryRouter>,
    )
    const value = screen.getByText('four')
    const row = value.closest('[data-hint]') as HTMLElement
    expect(row.tagName).toBe('DIV')
    expect(row).toHaveAttribute('data-hint-label', 'Roles')
    expect(row.querySelector('dt')?.textContent).toBe('Roles')
    // a row with a Change link is not a tab stop of its own (the link is); one without is
    expect(row).not.toHaveAttribute('tabindex')
    expect(screen.getByText('2').closest('[data-hint]')).toHaveAttribute('tabindex', '0')
    const tip = document.getElementById(row.getAttribute('aria-describedby')!)!
    await userEvent.hover(value)
    await waitFor(() => expect(tip).toHaveAttribute('data-open', 'true'))
    expect(tip).toHaveTextContent(HINTS['summary.posture.roles'])
    expect(collectHints(document)[0]).toMatchObject({ id: 'summary.posture.roles', label: 'Roles' })
  })

  it('a task-list status tag may wrap, so a long status never widens its row past a phone; a plain tag stays on one line', () => {
    render(
      <MemoryRouter>
        <TaskList completed={0} tasks={[{ num: 7, name: 'Run the factory', status: 'No cell routes deliver yet', tone: 'grey', to: '/factory' }]} />
        <Tag tone="blue">Ready</Tag>
      </MemoryRouter>,
    )
    const long = screen.getByText('No cell routes deliver yet')
    expect(long.className).toContain('whitespace-normal')
    expect(long.className).not.toContain('whitespace-nowrap')
    expect(screen.getByText('Ready').className).toContain('whitespace-nowrap')
  })

  it('details is a native <details> with the summary as its one visible line, closed by default', () => {
    const { container } = render(
      <>
        <Details summary="What these words mean" id="words">
          <p>cell — one class of change at one size.</p>
        </Details>
        <Details summary="Already open" open>
          <p>shown</p>
        </Details>
      </>,
    )
    const [closed, opened] = Array.from(container.querySelectorAll('details'))
    expect(closed).toHaveAttribute('id', 'words')
    expect(closed).not.toHaveAttribute('open')
    expect(closed!.querySelector('summary')).toHaveTextContent('What these words mean')
    expect(screen.getByText('cell — one class of change at one size.')).toBeInTheDocument()
    expect(opened).toHaveAttribute('open')
  })
})

/** An intact `/ledger/verify` answer of the declared shape; each test overrides what it breaks. */
const VERIFY_OK = {
  rows: 1,
  ok: true,
  false_q1_total: 0,
  chain_ok: true,
  broken_at: null,
  detail: '',
  clean_without_pack: 0,
  signoffs: { rows: 0, chain_ok: true, broken_at: null, detail: '' },
  reviews: { rows: 0, chain_ok: true, broken_at: null, detail: '' },
  verified_at: '',
  head_row_hash: '',
  events: { rows: 0, chain_ok: true, broken_at: null, detail: '', head_row_hash: '', walk: 'full', full_walk_at: '' },
  disqualified: { window_days: 7, threshold: 2, by_builder: [], over: [] },
} satisfies LedgerVerify

describe('PosturePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the five groups from the API and never a secret', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1, belt_set: 'v5', signoff_policy: 'signoff-policy.v3', licence: 'Apache-2.0' },
      'GET /golive': GOLIVE,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: {} }, { name: 'toolchains', status: 'ok', detail: 'all present', data: {} }, { name: 'ledger', status: 'ok', detail: '592 rows, false_q1=0', data: {} }, { name: 'append_only', status: 'ok', detail: 'triggers present; UPDATE on grades refused', data: {} }] },
      'GET /ledger/verify': { ...VERIFY_OK, rows: 592 } satisfies LedgerVerify,
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
    })
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(screen.getByText('crb 2.0.0a1')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'About this deployment' })).toBeInTheDocument()
    // the five groups, each a level-2 heading in the page's order (G-214: the title once said four)
    for (const g of ['Build and apparatus', 'Identity and access', 'Execution and egress', 'Delivery', 'Data and audit']) expect(screen.getByRole('heading', { level: 2, name: g })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Build and apparatus' }).parentElement).toHaveTextContent(/2.2 · belt set .* v5 · routing routing.v1/)
    expect(screen.getByRole('heading', { name: 'Build and apparatus' }).parentElement).toHaveTextContent('routing.v1 (routing) · signoff-policy.v3')
    expect(screen.getByText('Append-only, hash-chained · 592 rows · chain intact · false-Q1 0')).toBeInTheDocument()
    expect(screen.getByText(/GitHub App not configured — repositories connect by URL/)).toHaveTextContent('register the app once for this deployment')
    expect(screen.getAllByText('shown to admins').length).toBeGreaterThan(0)
    expect(screen.getByText(/Enforced at write: the API refuses a sign-off \(409 same_actor\)/)).toBeInTheDocument()
  })

  it('every row that is not the production posture says what to do next, and the Delivery group reads from the API (J-FAC-10)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'admin' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1, oidc_enabled: false },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'local', data: { executor: 'local' } }, { name: 'toolchains', status: 'ok', detail: 'all present', data: {} }, { name: 'ledger', status: 'ok', detail: '592 rows', data: {} }, { name: 'append_only', status: 'ok', detail: 'triggers present', data: {} }] },
      'GET /ledger/verify': { ...VERIFY_OK, rows: 592, ok: false, chain_ok: false, broken_at: 412, detail: 'seq 412: row_hash mismatch (row edited)' } satisfies LedgerVerify,
      'GET /github/app': {
        configured: true,
        app_slug: 'crb-bench',
        install_url: '',
        api_url: 'https://api.github.com',
        installations: [
          { id: 1, account_login: 'acme', account_type: 'Organization', repository_selection: 'selected', html_url: '', suspended: false, permissions: { contents: 'write', pull_requests: 'write' }, can_deliver: true, recorded_by: 'u1', updated: '2026-09-15T10:00:00+00:00' },
          { id: 2, account_login: 'beta', account_type: 'Organization', repository_selection: 'all', html_url: '', suspended: false, permissions: { contents: 'read' }, can_deliver: false, recorded_by: 'u1', updated: '2026-09-15T10:00:00+00:00' },
        ],
      },
      'GET /settings': { sandbox_mode: 'local', raw: { builder: { executor: 'local' }, factory: { test_author: 'none', require_signed_cell: true } } },
    })
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(screen.getByText('crb 2.0.0a1')).toBeInTheDocument())
    // the test executor is a development reading: the next step names the switch and the guide
    const executor = screen.getByText(/^local — a development reading, not evidence/)
    expect(executor).toHaveTextContent('To count runs as evidence set CRB_SANDBOX_MODE=docker on the worker')
    expect(screen.getByRole('link', { name: 'Sandbox (DEPLOYMENT)' })).toHaveAttribute('href', '/help/docs/DEPLOYMENT#34-the-workers-sandbox--choose-deliberately')
    // local accounts only → configure OpenID Connect
    expect(screen.getByText(/^Local accounts only/)).toHaveTextContent('To sign people in with the organisation account configure OpenID Connect')
    // a broken chain → what to do
    expect(screen.getByText(/chain broken at 412/)).toHaveTextContent('Stop writing and verify the ledger from the export')
    // the Delivery group, from GET /github/app — values never hardcoded where the API serves them
    const delivery = screen.getByRole('heading', { name: 'Delivery' }).parentElement!
    expect(delivery).toHaveTextContent('a branch named by the item and one pull request against the repository’s default branch; the factory never writes to the default branch')
    expect(delivery).toHaveTextContent('1 of 2 installations can deliver')
    expect(delivery).toHaveTextContent('a pull request opens only for a cell the capability map routes deliver under routing.v1')
    // ADR-0018 — the second clause of the same gate, read from this deployment's own settings
    // (the settings query is only enabled once /auth/me has answered admin, so it lands later)
    await waitFor(() => expect(delivery).toHaveTextContent('a signed cell as well as a deliver route: the factory does not build an item until a person has signed off its cell’s proven standard'))
    expect(delivery).toHaveTextContent('a second approver — never the person who queued the run — may lift the sign-off clause for one run, and never the route; the override is an event on the chain naming the approver and the clause')
    expect(delivery).toHaveTextContent('installation tokens minted per push, never stored')
    // admins get the Settings link on rows they can act on
    expect(screen.getAllByRole('link', { name: 'Settings' }).length).toBeGreaterThan(0)
  })


  it('an edited audit event is reported as the audit trail, naming the event, and sends the reader to verify the store (P-251)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1 },
      'GET /health': { status: 'ok', probes: [{ name: 'ledger', status: 'ok', detail: '12 rows', data: {} }, { name: 'append_only', status: 'ok', detail: 'triggers present', data: {} }] },
      'GET /ledger/verify': { ...VERIFY_OK, rows: 12, ok: false, detail: '12 rows, chain intact, false_q1=0; events chain broken — event 3: row_hash mismatch (row edited)', events: { ...VERIFY_OK.events, rows: 5, chain_ok: false, broken_at: 3, detail: 'event 3: row_hash mismatch (row edited)' } } satisfies LedgerVerify,
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
    })
    renderApp(<PosturePage />, { route: '/posture' })
    const row = await screen.findByText(/audit trail broken at event 3/)
    // the grade chain is intact and says so; the export (grades only) is not offered as the check
    expect(row).toHaveTextContent('12 rows · chain intact · false-Q1 0 · audit trail broken at event 3')
    expect(row).toHaveTextContent('Stop writing and verify the store itself (crb ledger verify --store)')
    expect(row).not.toHaveTextContent('verify the ledger from the export')
    expect(screen.queryByText(/chain broken at \?/)).toBeNull()
  })
  it('production running unsealed under CRB_ALLOW_UNSEALED_PROD says so to every viewer, from /health (ADR-0023)', async () => {
    const base = {
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1 },
      'GET /ledger/verify': VERIFY_OK,
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
    }
    mockApi({
      ...base,
      'GET /health': {
        status: 'ok',
        probes: [],
        posture: { env: 'prod', sandbox_executor: 'local', builder_executor: 'host', sealed: false, unsealed_prod_override: true },
      },
    })
    renderApp(<PosturePage />, { route: '/posture' })
    const row = await screen.findByText(/^unsealed in production under CRB_ALLOW_UNSEALED_PROD=1/)
    expect(row).toHaveTextContent('tests run local, the builder runs host')
    expect(row).toHaveTextContent("every run's apparatus carries the override")
    expect(row).toHaveTextContent('Remove CRB_ALLOW_UNSEALED_PROD')
  })

  it('a sealed production deployment reads sealed on the posture row', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1 },
      'GET /ledger/verify': VERIFY_OK,
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
      'GET /health': {
        status: 'ok',
        probes: [],
        posture: { env: 'prod', sandbox_executor: 'docker', builder_executor: 'docker', sealed: true, unsealed_prod_override: false },
      },
    })
    renderApp(<PosturePage />, { route: '/posture' })
    expect(await screen.findByText('sealed — tests and the builder run in docker')).toBeInTheDocument()
  })

  it('a sealed production deployment says factory runs are refused, because factory builds are not sealed (ADR-0023)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1 },
      'GET /ledger/verify': VERIFY_OK,
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
      'GET /health': {
        status: 'ok',
        probes: [],
        posture: { env: 'prod', sandbox_executor: 'docker', builder_executor: 'docker', sealed: true, unsealed_prod_override: false, factory_builds: 'refused' },
      },
    })
    renderApp(<PosturePage />, { route: '/posture' })
    const row = await screen.findByText(/^sealed — tests and the builder run in docker/)
    expect(row).toHaveTextContent('factory runs are refused')
    expect(row).toHaveTextContent('factory builds run the builder on the host')
  })

  it('under the override a sealed deployment says factory builds run on the host and are stamped (ADR-0023)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1 },
      'GET /ledger/verify': VERIFY_OK,
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
      'GET /health': {
        status: 'ok',
        probes: [],
        posture: { env: 'prod', sandbox_executor: 'docker', builder_executor: 'docker', sealed: true, unsealed_prod_override: false, factory_builds: 'host' },
      },
    })
    renderApp(<PosturePage />, { route: '/posture' })
    const row = await screen.findByText(/^sealed — tests and the builder run in docker/)
    expect(row).toHaveTextContent('factory builds run on the host under CRB_ALLOW_UNSEALED_PROD=1')
    expect(row).toHaveTextContent("every factory run's apparatus carries the override")
  })
})
