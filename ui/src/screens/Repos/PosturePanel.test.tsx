/**
 * ui/src/screens/Repos/PosturePanel.tsx — qualified N of M, the refusals with their fixes, and
 * a Qualify button only an operator sees (ADR-0019).
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the Posture panel on /repos/:name against a mocked
 *               `GET /repos/{name}/posture`.
 * What it does: Pins that the panel reads the counts, the class, the toolchain and the
 *               provisioning state; lists every refusal code with its count, its fix and a guide
 *               link into /help/docs; says why a reading is stale; offers "Qualify for this
 *               posture — no model spend" to an operator only; and that pressing it posts a
 *               `qualify` run and opens it.
 * How:          `mockApi` + `renderApp` at `/repos/:name`; assertions on text, links and the
 *               POST body.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0019-qualification-is-posture-relative.md
 * Works with:   ui/src/screens/Repos/PosturePanel.tsx (under test),
 *               ui/src/screens/Repos/RepoDetail.tsx (mounts it),
 *               ui/src/screens/Repos/repoFixtures.ts
 *               (`REPO`), ui/src/test/utils.tsx (`mockApi`, `renderApp`)
 * Tested by:    ui/src/screens/Repos/PosturePanel.test.tsx
 * Touch when:   the panel shows a new fact from the posture route.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal, RepoPosture } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { guideHref } from './PosturePanel'
import { RepoDetail } from './RepoDetail'
import { REPO } from './repoFixtures'

const VIEWER: Principal = { ...PRINCIPAL, role: 'viewer' }
const OPERATOR: Principal = { ...PRINCIPAL, role: 'operator' }

const POSTURE: RepoPosture = {
  repo: REPO.name,
  executor: 'docker',
  image_ref: 'crb-sandbox-go:main-8ab88ad',
  posture_id: 'pst_' + '1'.repeat(24),
  posture_class: 'docker/readonly/sealed',
  posture: { toolchain: 'go version go1.26.8 linux/arm64' },
  provisioning: { enabled: false },
  qualified: 3,
  total: 9,
  refusals_by_code: [
    { code: 'QUAL_ENV_UNLOADABLE', n: 5, message: '', fix: 'the parent cannot load its dependencies offline: switch provisioning on if it is off; if it is on, run crb deps verify and delete any set it names (the next run fetches it again); otherwise fix the module named', doc: 'docs/OPERATOR.md#7a-when-a-posture-is-unqualified' },
    { code: 'POSTURE_UNQUALIFIED', n: 1, message: '', fix: 'qualify the repository in this posture (crb repo qualify, or leave qualify_first on); this costs no model money', doc: 'docs/OPERATOR.md#7a-when-a-posture-is-unqualified' },
  ],
  delta: [],
  stale_reason: '',
}

function setup(me: Principal, posture: RepoPosture = POSTURE, extra: Record<string, unknown> = {}) {
  const api = mockApi({
    'GET /auth/me': me,
    [`GET /repos/${REPO.name}`]: REPO,
    [`GET /repos/${REPO.name}/profile`]: { repo: REPO.name, n_commits: 0, cells: [], classes: [], sizes: [] },
    [`GET /repos/${REPO.name}/events`]: { items: [], total: 0, limit: 50, offset: 0 },
    [`GET /repos/${REPO.name}/posture`]: posture,
    'GET /health': { status: 'ok', probes: [] },
    ...extra,
  })
  renderApp(<RepoDetail />, { route: `/repos/${REPO.name}`, path: '/repos/:name' })
  return api
}

describe('PosturePanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads qualified N of M, the class, the toolchain, provisioning, and every refusal with its fix and guide', async () => {
    setup(VIEWER)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Posture' })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('3 of 9')).toBeInTheDocument())
    expect(screen.getByTestId('posture-class')).toHaveTextContent('docker/readonly/sealed')
    expect(screen.getByTestId('posture-toolchain')).toHaveTextContent('go1.26.8')
    expect(screen.getByTestId('posture-image')).toHaveTextContent('crb-sandbox-go:main-8ab88ad')
    expect(screen.getByTestId('posture-provisioning')).toHaveTextContent('off')
    const unloadable = screen.getByTestId('refusal-QUAL_ENV_UNLOADABLE')
    expect(within(unloadable).getByRole('img', { name: 'QUAL_ENV_UNLOADABLE: 5 tasks' })).toBeInTheDocument()
    expect(unloadable).toHaveTextContent('switch provisioning on')
    expect(within(unloadable).getByRole('link', { name: 'What to do' })).toHaveAttribute('href', '/help/docs/OPERATOR#7a-when-a-posture-is-unqualified')
    expect(screen.getByTestId('refusal-POSTURE_UNQUALIFIED')).toHaveTextContent('costs no model money')
    expect(screen.queryByTestId('posture-stale')).toBeNull()
  })

  it('a viewer sees no Qualify button; the stale reason is said in words', async () => {
    setup(VIEWER, { ...POSTURE, posture_id: '', posture_class: '', qualified: 0, refusals_by_code: [], stale_reason: 'no task has been qualified under docker with crb-sandbox-go:main yet — qualify the repository (no model spend)' })
    await waitFor(() => expect(screen.getByTestId('posture-stale')).toHaveTextContent('qualify the repository'))
    expect(screen.getByTestId('posture-class')).toHaveTextContent('none recorded')
    expect(screen.queryByRole('button', { name: /Qualify for this posture/ })).toBeNull()
  })

  it('an operator presses Qualify: a qualify run is posted (no builder) and opened', async () => {
    const run = { id: 'q'.repeat(32), repo: REPO.name, kind: 'qualify', status: 'queued' }
    const api = setup(OPERATOR, POSTURE, { 'POST /runs': run, [`GET /runs/${run.id}`]: run })
    const button = await screen.findByRole('button', { name: 'Qualify for this posture — no model spend' })
    await userEvent.click(button)
    await waitFor(() => expect(api.calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    const post = api.calls.find((c) => c.method === 'POST' && c.path === '/runs')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ repo: REPO.name, kind: 'qualify' })
  })

  it('guideHref maps a served guide anchor into the bundled help', () => {
    expect(guideHref('docs/DEPLOYMENT.md#34-the-workers-sandbox--choose-deliberately')).toBe('/help/docs/DEPLOYMENT#34-the-workers-sandbox--choose-deliberately')
    expect(guideHref('elsewhere')).toBe('/help')
  })
})
