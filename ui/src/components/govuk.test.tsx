/**
 * govuk.tsx — the patterns render what they say and nothing else.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the GOV.UK / NHS pattern components and the Posture page.
 * What it does: Pins the task list's "completed n of m" and row links; the summary list's
 *               key / value / change cells; the banner's landmark and title; the
 *               confirmation panel's reference; the details pattern (a native `<details>`
 *               whose summary is the one line shown, closed unless `open`); and that the
 *               posture page renders every group from the API without a secret value.
 * How:          Plain renders; `mockApi` + `renderApp` for the page.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/govuk.tsx, ui/src/screens/Posture/PosturePage.tsx
 * Tested by:    ui/src/components/govuk.test.tsx
 * Touch when:   a pattern is added.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PosturePage } from '../screens/Posture/PosturePage'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../test/utils'
import { ConfirmationPanel, Details, NotificationBanner, SummaryList, TaskList } from './govuk'

describe('govuk patterns', () => {
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

describe('PosturePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the four groups from the API and never a secret', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', uptime_s: 1 },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: {} }, { name: 'toolchains', status: 'ok', detail: 'all present', data: {} }, { name: 'ledger', status: 'ok', detail: '592 rows, false_q1=0', data: {} }, { name: 'append_only', status: 'ok', detail: 'triggers present; UPDATE on grades refused', data: {} }] },
      'GET /ledger/verify': { rows: 592, ok: true, false_q1_total: 0, broken_at: null },
      'GET /github/app': { configured: false, app_slug: '', install_url: '', api_url: '', installations: [] },
      'GET /settings': () => envelope(403, 'forbidden', 'admin only'),
    })
    renderApp(<PosturePage />, { route: '/posture' })
    await waitFor(() => expect(screen.getByText('crb 2.0.0a1')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'About this deployment' })).toBeInTheDocument()
    expect(screen.getByText('2.2 · belt set v5 · routing routing.v1')).toBeInTheDocument()
    expect(screen.getByText('Append-only, hash-chained · 592 rows · chain intact · false-Q1 0')).toBeInTheDocument()
    expect(screen.getByText('GitHub App not configured — repositories connect by URL')).toBeInTheDocument()
    expect(screen.getAllByText('shown to admins').length).toBeGreaterThan(0)
    expect(screen.getByText(/not enforced at write yet/)).toBeInTheDocument()
  })
})
