/**
 * ui/src/screens/Repos/ReposPage.tsx — the list of repositories, its probe pills and its empty state per role.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the /repos list against a mocked `GET /repos` (gap G-230).
 * What it does: Pins that each row shows the served values — the name linking to its
 *               repository page, language and runner, the probe pill with an accessible label
 *               naming its state and detail, and the task, gold-clean and hard-pool counts —
 *               and a never-probed repository reads "Not probed"; that an operator is offered
 *               Add repo and, on an empty list, Add the first repo; and that a viewer is offered
 *               neither and is told to ask an operator.
 * How:          `mockApi` with `GET /auth/me` per role and `GET /repos`; `renderApp` at `/repos`;
 *               assertions on the table rows, the pill labels and the buttons.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/ReposPage.tsx (the code under test),
 *               ui/src/screens/Repos/repoFixtures.ts (`REPO`), ui/src/lib/verdict.ts
 *               (`probeDisplay`), ui/src/test/utils.tsx (`mockApi`, `renderApp`, `PRINCIPAL`)
 * Tested by:    ui/src/screens/Repos/ReposPage.test.tsx
 * Touch when:   a column is added to the list or the role rule for Add repo changes.
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

  it('each row shows the served name, runner, probe state and counts', async () => {
    setup(OPERATOR, [MEASURED, UNPROBED])
    const table = await screen.findByRole('table', { name: 'Repositories under measurement' })
    const row = within(table).getByRole('link', { name: MEASURED.name }).closest('tr')!
    expect(within(table).getByRole('link', { name: MEASURED.name })).toHaveAttribute('href', `/repos/${MEASURED.name}`)
    expect(row).toHaveTextContent('python · pytest')
    expect(within(row).getByText('36')).toBeInTheDocument()
    expect(within(row).getByText('33')).toBeInTheDocument()
    expect(within(row).getByText('5')).toBeInTheDocument()
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
})
