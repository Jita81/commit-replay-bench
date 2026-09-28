/**
 * ui/src/screens/Repos/ReposPage.tsx — the list of repositories, its probe pills and its empty
 * state per role.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the /repos list against a mocked `GET /repos` (gap G-230).
 * What it does: Pins that each row shows the served values — the name linking to its
 *               repository page, language and runner, the probe pill with an accessible label
 *               naming its state and detail, and the task, gold-clean and hard-pool counts —
 *               and a never-probed repository reads "Not probed"; that an operator is offered
 *               Add repo and, on an empty list, Add the first repo; and that a viewer is offered
 *               neither and is told to ask an operator; and that a deployment past one page is
 *               listed whole with a line saying so, or says how many of the total it shows; a
 *               repository added ahead of the read is neither missed nor listed twice, and a
 *               list that keeps changing is never called whole (G-229).
 * How:          `mockApi` with `GET /auth/me` per role and `GET /repos`; `renderApp` at `/repos`;
 *               assertions on the table rows, the pill labels and the buttons.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/ReposPage.tsx (the code under test),
 *               ui/src/screens/Repos/repoFixtures.ts (`REPO`), ui/src/lib/verdict.ts
 *               (`probeDisplay`), ui/src/test/utils.tsx (`mockApi`, `renderApp`, `PRINCIPAL`)
 * Tested by:    ui/src/screens/Repos/ReposPage.test.tsx
 * Touch when:   never for a new repository; a column is added to the list or the role rule
 *               for Add repo changes.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal, RepoSummary } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { ReposPage } from './ReposPage'
import { REPO } from './repoFixtures'

const OPERATOR: Principal = { ...PRINCIPAL, role: 'operator' }
const VIEWER: Principal = { ...PRINCIPAL, role: 'viewer' }

const MEASURED: RepoSummary = {
  ...REPO,
  task_counts: { total: 36, standard: 31, hard: 5, gold_clean: 33, gold_failed: 2, unchecked: 1 },
  last_run: { id: 'r1', kind: 'replay', status: 'succeeded', finished: '2026-09-20T10:00:00+00:00' },
}
const UNPROBED: RepoSummary = { ...REPO, name: 'fresh', probe: { status: 'not_probed', run_id: null, checked: null, detail: '' } }

function setup(me: Principal, items: RepoSummary[]) {
  mockApi({ 'GET /auth/me': me, 'GET /repos': { items, total: items.length, limit: 50, offset: 0 } })
  return renderApp(<ReposPage />, { route: '/repos' })
}

describe('ReposPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('carries the journey eyebrow of step 1 — Repos is where the shape is confirmed (G-301)', async () => {
    setup(OPERATOR, [MEASURED])
    await screen.findByRole('table', { name: 'Repositories under measurement' })
    expect(screen.getByText('Journey · 1 of 4 · Connection · shape')).toBeInTheDocument()
  })

  it('each row shows the served name, runner, probe state and counts', async () => {
    setup(OPERATOR, [MEASURED, UNPROBED])
    const table = await screen.findByRole('table', { name: 'Repositories under measurement' })
    const row = within(table).getByRole('link', { name: MEASURED.name }).closest('tr')!
    expect(within(table).getByRole('link', { name: MEASURED.name })).toHaveAttribute('href', `/repos/${MEASURED.name}`)
    expect(row).toHaveTextContent('python · pytest')
    // each count is its own table cell, so a screen reader reads it under its column header
    expect(within(row).getByRole('cell', { name: '36' })).toBeInTheDocument()
    expect(within(row).getByRole('cell', { name: '33' })).toBeInTheDocument()
    expect(within(row).getByRole('cell', { name: '5' })).toBeInTheDocument()
    expect(within(row).getByText('replay')).toBeInTheDocument()
    // the probe pill names its state and the runner's own summary for a screen reader
    expect(within(row).getByText('OK')).toBeInTheDocument()
    expect(within(row).getByLabelText(/^Probe: ok: /)).toBeInTheDocument()
    const fresh = within(table).getByRole('link', { name: 'fresh' }).closest('tr')!
    expect(within(fresh).getByText('Not probed')).toBeInTheDocument()
    expect(within(fresh).getByLabelText('Probe: not yet run')).toBeInTheDocument()
  })

  it('an operator is offered Add repo, and Add the first repo on an empty list', async () => {
    setup(OPERATOR, [])
    await waitFor(() => expect(screen.getByText('No repositories yet')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add the first repo' })).toBeInTheDocument()
    expect(screen.queryByText('Ask an operator to add one.')).toBeNull()
  })

  it('a viewer is offered neither button and is told to ask an operator', async () => {
    setup(VIEWER, [])
    await waitFor(() => expect(screen.getByText('No repositories yet')).toBeInTheDocument())
    expect(screen.getByText('Ask an operator to add one.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add repo' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add the first repo' })).toBeNull()
  })

  it('a deployment past one page lists every repository and says all are listed (G-229)', async () => {
    // 60 repositories served 50 to a page: the page must read the second page too
    const all = Array.from({ length: 60 }, (_, i) => ({ ...REPO, name: `r${String(i).padStart(2, '0')}` }))
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': (url: string) => {
        const q = new URL(url, 'http://x').searchParams
        const offset = Number(q.get('offset') ?? 0)
        const limit = Math.min(Number(q.get('limit') ?? 50), 50)
        return new Response(JSON.stringify({ items: all.slice(offset, offset + limit), total: all.length, limit, offset }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp(<ReposPage />, { route: '/repos' })
    const table = await screen.findByRole('table', { name: 'Repositories under measurement' })
    expect(within(table).getByRole('link', { name: 'r59' })).toBeInTheDocument()
    expect(screen.getByTestId('repos-count')).toHaveTextContent('All 60 repositories are listed.')
  })

  it('a repository added ahead of the read while the pages are walked is neither missed nor listed twice: the list is read again (G-229)', async () => {
    // 120 repositories, 50 to a page; `a000` is created (sorting first) just after the first page
    const all = Array.from({ length: 120 }, (_, i) => ({ ...REPO, name: `r${String(i).padStart(3, '0')}` }))
    let served = 0
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': (url: string) => {
        const q = new URL(url, 'http://x').searchParams
        const offset = Number(q.get('offset') ?? 0)
        const limit = Math.min(Number(q.get('limit') ?? 50), 50)
        if (served++ === 1) all.unshift({ ...REPO, name: 'a000' })
        return new Response(JSON.stringify({ items: all.slice(offset, offset + limit), total: all.length, limit, offset }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp(<ReposPage />, { route: '/repos' })
    const table = await screen.findByRole('table', { name: 'Repositories under measurement' })
    expect(within(table).getByRole('link', { name: 'a000' })).toBeInTheDocument()
    expect(within(table).getAllByRole('link', { name: 'r049' })).toHaveLength(1)
    expect(screen.getByTestId('repos-count')).toHaveTextContent('All 121 repositories are listed.')
  })

  it('a list that keeps changing while it is read is never called whole (G-229)', async () => {
    // every page answers a total one higher than the last: no read ever sees one list
    let total = 3
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': (url: string) => {
        const offset = Number(new URL(url, 'http://x').searchParams.get('offset') ?? 0)
        total += 1
        const items = offset === 0 ? [MEASURED, UNPROBED] : Array.from({ length: total - offset }, (_, i) => ({ ...REPO, name: `n${total}-${i}` }))
        return new Response(JSON.stringify({ items, total, limit: 500, offset }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp(<ReposPage />, { route: '/repos' })
    const line = await screen.findByTestId('repos-count')
    expect(line).not.toHaveTextContent(/^All/)
    expect(line).toHaveTextContent('the list changed while it was read')
  })

  it('a list that changed while it was read says how many of the total it shows (G-229)', async () => {
    // the first page promised 2; the second came back empty (one was removed meanwhile)
    mockApi({
      'GET /auth/me': VIEWER,
      'GET /repos': (url: string) => {
        const offset = Number(new URL(url, 'http://x').searchParams.get('offset') ?? 0)
        return new Response(JSON.stringify({ items: offset === 0 ? [MEASURED] : [], total: 2, limit: 500, offset }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      },
    })
    renderApp(<ReposPage />, { route: '/repos' })
    expect(await screen.findByTestId('repos-count')).toHaveTextContent('1 of 2 repositories are listed')
  })
})
