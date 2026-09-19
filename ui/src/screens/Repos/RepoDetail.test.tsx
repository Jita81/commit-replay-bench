/**
 * ui/src/screens/Repos/RepoDetail.tsx — Next steps reach the journey, and the tab lives in the URL.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the repository detail page against a mocked `GET /repos/{name}`.
 * What it does: Pins that Next steps link the Connection walk and the Factory for this
 *               repository as well as the instrument screens (J-FAC-18), that Start a run is
 *               offered only to an operator, and that `?tab=config` opens the Configuration
 *               tab so a link can land on it (the walk's Configuration button).
 * How:          `mockApi` with the config-tab fixture; `renderApp` at `/repos/:name` with and
 *               without `?tab=`; assertions on the links and the selected tab.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/RepoDetail.tsx (the code under test),
 *               ui/src/screens/Repos/repoConfigModel.test.ts (`REPO`), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Repos/RepoDetail.test.tsx
 * Touch when:   a Next step is added or the tab set changes.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { RepoDetail } from './RepoDetail'
import { REPO } from './repoConfigModel.test'

const VIEWER: Principal = { ...PRINCIPAL, role: 'viewer' }

function setup(me: Principal, route: string) {
  mockApi({
    'GET /auth/me': me,
    [`GET /repos/${REPO.name}`]: REPO,
    [`GET /repos/${REPO.name}/profile`]: { repo: REPO.name, n_commits: 0, cells: [], classes: [], sizes: [] },
    [`GET /repos/${REPO.name}/events`]: { items: [], total: 0, limit: 50, offset: 0 },
    'GET /health': { status: 'ok', probes: [] },
  })
  return renderApp(<RepoDetail />, { route, path: '/repos/:name' })
}

describe('RepoDetail', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('Next steps reach the Connection walk and the Factory for this repository; a viewer gets no Start a run (J-FAC-18)', async () => {
    setup(VIEWER, `/repos/${REPO.name}`)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Next steps' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Connection walk' })).toHaveAttribute('href', `/connect/${REPO.name}`)
    expect(screen.getByRole('link', { name: 'Factory' })).toHaveAttribute('href', `/factory?repo=${REPO.name}`)
    expect(screen.getByRole('link', { name: 'Capability map' })).toHaveAttribute('href', `/capability?repo=${REPO.name}`)
    expect(screen.getByRole('link', { name: 'Oracle adequacy' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Runs' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start a run' })).toBeNull()
  })

  it('?tab=config opens the Configuration tab; clicking a tab writes it to the URL', async () => {
    setup(VIEWER, `/repos/${REPO.name}?tab=config`)
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Configuration' })).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'false')
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(screen.getByRole('tab', { name: 'Tasks' })).toHaveAttribute('aria-selected', 'true')
    // an unknown value falls back to Overview, never a blank panel
    vi.unstubAllGlobals()
    setup(VIEWER, `/repos/${REPO.name}?tab=nonsense`)
    await waitFor(() => expect(screen.getAllByRole('tab', { name: 'Overview' }).at(-1)).toHaveAttribute('aria-selected', 'true'))
  })
})
