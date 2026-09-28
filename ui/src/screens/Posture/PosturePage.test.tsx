/**
 * The Deployment page as a review board reads it: every row with its source, the go-live
 * checklist's state, the print, and where it sits in going live.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests of /posture beyond the five groups (those are in
 *               ui/src/components/govuk.test.tsx).
 * What it does: Pins that every summary row names its source and a failed `GET /version` says
 *               so instead of "…"; that the go-live section shows each line as proven, attested
 *               or unproven with its reason and source, an attestation with who, the day and
 *               what, and lists the acts this product does not perform apart from its own
 *               checks; that Print this page prints and the shell's header leaves the print;
 *               that the eyebrow names the platform stream, the journey and the step; and that
 *               the About block says the page changes nothing and is not the checklist, and
 *               links DEPLOYMENT §8 and OPERATOR §9.
 * How:          `mockApi` with the go-live fixture from govuk.test.tsx; the shell mounted as the
 *               app mounts it where the print of the chrome is under test.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
 * Works with:   ui/src/screens/Posture/PosturePage.tsx (under test),
 *               ui/src/screens/Posture/GoLiveList.tsx (the go-live section),
 *               ui/src/components/Layout.tsx (the print of the chrome), ui/src/help/help.ts
 *               (the About block's words and links)
 * Tested by:    this file
 * Touch when:   never for a new repository; a row, the go-live section or the print changes.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AboutThisScreen } from '../../components/Help'
import { Layout } from '../../components/Layout'
import { AuthProvider } from '../../lib/auth'
import { GOLIVE } from '../../test/golive'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { PosturePage } from './PosturePage'

const VERSION = { crb: '2.0.0a1', apparatus: '2.3', policy: 'routing.v1', uptime_s: 1, oidc_enabled: false, belt_set: 'v5', signoff_policy: 'signoff-policy.v3', licence: 'Apache-2.0' }

function base(role: string, extra: Record<string, unknown> = {}) {
  return {
    'GET /auth/me': { ...PRINCIPAL, role },
    'GET /version': VERSION,
    'GET /health': { status: 'ok', probes: [{ name: 'toolchains', status: 'ok', detail: 'go 1.26', data: {} }], posture: { env: 'dev', sandbox_executor: 'local', builder_executor: 'host', sealed: false, unsealed_prod_override: false } },
    'GET /ledger/verify': { rows: 3, ok: true, false_q1_total: 0, broken_at: null },
    'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
    'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
    'GET /golive': GOLIVE,
    'GET /repos': { items: [], total: 0, limit: 50, offset: 0 },
    ...extra,
  }
}

describe('PosturePage — sources, go-live and print', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('every row names its source, and a failed /version says so instead of an ellipsis (G-212)', async () => {
    mockApi(base('viewer'))
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(screen.getByText('crb 2.0.0a1')).toBeInTheDocument())
    const groups = ['Build and apparatus', 'Identity and access', 'Execution and egress', 'Delivery', 'Data and audit']
    let rows = 0
    for (const g of groups) {
      const section = screen.getByRole('heading', { level: 2, name: g }).parentElement!
      for (const dd of Array.from(section.querySelectorAll('dl > div, dl > [data-hint]'))) {
        rows += 1
        expect(dd, `${g}: ${dd.querySelector('dt')?.textContent}`).toHaveTextContent(/Source: /)
      }
    }
    expect(rows).toBe(25)
    expect(screen.getByText('Source: GET /version — the package’s licence in pyproject.toml').closest('dd')).toHaveTextContent('Apache-2.0')
    vi.unstubAllGlobals()
    mockApi(base('viewer', { 'GET /version': () => envelope(503, 'unavailable', 'down') }))
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(screen.getAllByText('the version could not be read').length).toBeGreaterThan(2))
  })

  it('reads the belt set, the sign-off policy and the licence from /version, never from a literal (P-330)', async () => {
    // values no literal in the page could match: a row that prints its own words fails here
    mockApi(base('viewer', { 'GET /version': { ...VERSION, belt_set: 'v9-test', signoff_policy: 'signoff-policy.test', licence: 'TEST-1.0' } }))
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(screen.getByText('crb 2.0.0a1')).toBeInTheDocument())
    const row = (hint: string) => document.querySelector(`[data-hint="${hint}"]`) as HTMLElement
    expect(row('summary.posture.apparatus')).toHaveTextContent(/belt set\W*v9-test/)
    expect(row('summary.posture.apparatus')).not.toHaveTextContent(/belt set\W*v5/)
    expect(row('summary.posture.policies')).toHaveTextContent('routing.v1 (routing) · signoff-policy.test')
    expect(row('summary.posture.policies')).not.toHaveTextContent('signoff-policy.v3')
    expect(row('summary.posture.licence')).toHaveTextContent('TEST-1.0')
    expect(row('summary.posture.licence')).not.toHaveTextContent('Apache-2.0')
    // and when /version fails, each of those rows says so rather than printing a value
    cleanup()
    vi.unstubAllGlobals()
    mockApi(base('viewer', { 'GET /version': () => envelope(503, 'unavailable', 'down') }))
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(row('summary.posture.licence')).toHaveTextContent('the version could not be read'))
    for (const hint of ['summary.posture.version', 'summary.posture.apparatus', 'summary.posture.policies', 'summary.posture.licence']) {
      expect(row(hint), hint).toHaveTextContent('the version could not be read')
      expect(row(hint), hint).not.toHaveTextContent(/Apache-2\.0|signoff-policy\.v3|belt set\W*v5/)
    }
  })

  it('shows each go-live line as proven, attested or unproven, and apart from its own checks the acts it does not perform (G-317, G-583)', async () => {
    mockApi(base('viewer'))
    renderApp(<PosturePage />, { route: '/posture' })
    const section = await screen.findByTestId('posture-go-live')
    await waitFor(() => expect(within(section).getByTestId('golive-counts')).toHaveTextContent('2 of 4 go-live lines stand: 1 proven by this product, 1 attested by an admin, 2 unproven.'))
    expect(within(section).getByRole('img', { name: 'The health check is green: Proven' })).toBeInTheDocument()
    expect(within(section).getByRole('img', { name: 'Tests and the builder both run sealed in docker: Unproven' })).toBeInTheDocument()
    expect(within(section).getByTestId('golive-sealed-posture')).toHaveTextContent('tests run local, the builder runs host')
    expect(within(section).getByTestId('golive-egress-denied-attestation')).toHaveTextContent('Done on 2026-09-25, recorded by root on 2026-09-26: “curl to 1.1.1.1 from worker-0 timed out; CHG-1042”')
    expect(within(section).getByText('Source: GET /health, read when this page was loaded')).toBeInTheDocument()
    const product = section.querySelector('dl[aria-label="Go-live lines the product proves"]') as HTMLElement
    const operator = section.querySelector('dl[aria-label="Go-live acts the operator attests"]') as HTMLElement
    expect(within(product).queryByText(/penetration test/)).toBeNull()
    expect(within(operator).getByText('A penetration test of this deployment has been done and its findings handled')).toBeInTheDocument()
    expect(within(section).getByRole('heading', { name: 'Acts the operator attests' })).toBeInTheDocument()
    // two of the acts are the product's own commands, and the words say so
    expect(within(section).getByTestId('golive-operator-acts')).toHaveTextContent('crb doctor and crb repo probe, are this product’s own commands, which the operator runs on each host')
    expect(within(section).getByRole('link', { name: 'the go-live checklist (DEPLOYMENT §8)' })).toHaveAttribute('href', '/help/docs/DEPLOYMENT#8-go-live-checklist')
    // a viewer is not offered Settings; an admin is, on the operator's lines only
    expect(within(section).queryByRole('link', { name: 'Record or withdraw on Settings' })).toBeNull()
  })

  it('offers an admin the way to Settings on each line only the operator can prove', async () => {
    mockApi(base('admin', { 'GET /settings': { sandbox_mode: 'local', raw: {} } }))
    renderApp(<PosturePage />, { route: '/posture' })
    const section = await screen.findByTestId('posture-go-live')
    await waitFor(() => expect(within(section).getAllByRole('link', { name: 'Record or withdraw on Settings' })).toHaveLength(2))
    expect(within(section).getAllByRole('link', { name: 'Record or withdraw on Settings' })[0]).toHaveAttribute('href', '/settings#golive-attestations')
  })

  it('says so when the go-live checklist could not be read, never an empty list', async () => {
    mockApi(base('viewer', { 'GET /golive': () => envelope(503, 'unavailable', 'the checklist could not be read') }))
    renderApp(<PosturePage />, { route: '/posture' })
    const section = await screen.findByTestId('posture-go-live')
    await waitFor(() => expect(section).toHaveTextContent('the checklist could not be read'))
  })

  it('Print this page prints, and the shell’s header and the About block leave the print (G-213)', async () => {
    mockApi(base('viewer', { 'GET /decisions': { items: [] } }))
    const print = vi.fn()
    vi.stubGlobal('print', print)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/posture']}>
          <AuthProvider>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/posture" element={<PosturePage />} />
              </Route>
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const button = await screen.findByRole('button', { name: 'Print this page' })
    await userEvent.click(button)
    expect(print).toHaveBeenCalledTimes(1)
    expect(button).toHaveClass('print:hidden')
    expect(screen.getByTestId('shell-header')).toHaveClass('print:hidden')
    await waitFor(() => expect(screen.getByTestId('about-this-screen')).toHaveClass('print:hidden'))
    // the footer's versions stay: they are the provenance of the printed statement
    expect(screen.getByRole('contentinfo')).not.toHaveClass('print:hidden')
  })

  it('the About block says the page changes nothing and is not the checklist, and opens DEPLOYMENT §8 and OPERATOR §9 (G-215, G-316)', async () => {
    mockApi(base('viewer'))
    renderApp(<AboutThisScreen />, { route: '/posture', path: '/posture' })
    const about = await screen.findByTestId('about-this-screen')
    await waitFor(() => expect(about).toHaveTextContent('The page changes nothing'))
    expect(about).toHaveTextContent('it is not the checklist and ticks nothing')
    expect(within(about).getByRole('link', { name: 'The go-live checklist' })).toHaveAttribute('href', '/help/docs/DEPLOYMENT#8-go-live-checklist')
    expect(within(about).getByRole('link', { name: 'Users, and what to do when nobody can sign in' })).toHaveAttribute('href', '/help/docs/OPERATOR#9-users')
  })

  it('the eyebrow names the platform stream, the go-live journey and the step (G-318, G-580)', async () => {
    mockApi(base('viewer'))
    renderApp(<PosturePage />, { route: '/posture' })
    const eyebrow = await screen.findByText('Run the platform · Deploy and go live · 3 of 4 · Deployment')
    expect(eyebrow).toHaveAttribute('data-hint', 'nav.deploy_position')
  })
})
