/**
 * HelpPage / DocPage — the glossary lists every term with an id; a guide or a decision record
 * renders from the bundle; an unknown name says so, and a chunk that fails to load says that.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the two help screens.
 * What it does: Pins that /help renders the 22 terms as a definition list with `id` per term
 *               and a link to its guide, the eight guides as links to /help/docs/<name>, and
 *               every decision record as a link to /help/docs/ADR-nnnn (G-156); that
 *               /help/docs/OPERATOR renders the guide's h1 with slug ids, links back to /help
 *               and states its non-goals under the header (G-150); that a record renders the
 *               same way; that an unknown name renders the empty state; and that a guide whose
 *               chunk fails to load renders the error envelope with Retry — never "No guide
 *               with that name" — and Retry loads it (G-148).
 * How:          `mockApi` + `renderApp` at the route with `path` for `useParams`; `loadDoc` is
 *               wrapped so a test can make its next call reject, as a failed chunk does.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-077)
 * Works with:   ui/src/screens/Help/HelpPage.tsx, ui/src/screens/Help/DocPage.tsx,
 *               ui/src/help/docs.ts (`loadDoc`), ui/src/help/adrs.ts (`ADR_TITLES`)
 * Tested by:    ui/src/screens/Help/HelpPage.test.tsx
 * Touch when:   a section is added to either page.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ADR_TITLES } from '../../help/adrs'
import { TERM_IDS } from '../../help/glossary'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'

/** How many of the next `loadDoc` calls reject, as a chunk that fails to load does. */
const chunk = vi.hoisted(() => ({ failures: 0 }))
vi.mock('../../help/docs', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../help/docs')>()
  return {
    ...real,
    loadDoc: (name: Parameters<typeof real.loadDoc>[0]) => {
      if (chunk.failures > 0) {
        chunk.failures -= 1
        return Promise.reject(new TypeError('Failed to fetch dynamically imported module'))
      }
      return real.loadDoc(name)
    },
  }
})
import { DocPage } from './DocPage'
import { HelpPage } from './HelpPage'

describe('HelpPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the glossary, the guides and the decisions for a viewer', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<HelpPage />, { route: '/help', path: '/help' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Glossary and guides' })).toBeInTheDocument()
    const terms = screen.getByRole('region', { name: 'Terms' })
    for (const id of TERM_IDS) expect(terms.querySelector(`#${id}`), id).not.toBeNull()
    expect(within(terms).getAllByRole('link', { name: 'Read more' }).length).toBe(TERM_IDS.length)
    const guides = screen.getByRole('region', { name: 'Guides' })
    expect(within(guides).getAllByRole('link')).toHaveLength(8)
    expect(within(guides).getByRole('link', { name: 'Operator guide' })).toHaveAttribute('href', '/help/docs/OPERATOR')
    const decisions = screen.getByRole('region', { name: 'Decisions (ADRs)' })
    expect(decisions).toHaveTextContent('ADR-0003')
    expect(decisions).toHaveTextContent('One routing rule')
  })

  it('every decision record is a link that opens it here, one row per record the repository holds', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<HelpPage />, { route: '/help', path: '/help' })
    const decisions = await screen.findByRole('region', { name: 'Decisions (ADRs)' })
    const links = within(decisions).getAllByRole('link')
    expect(links).toHaveLength(ADR_TITLES.length)
    expect(within(decisions).getByRole('link', { name: /^ADR-0015 — A sign-off expires with the apparatus/ })).toHaveAttribute('href', '/help/docs/ADR-0015')
    for (const l of links) expect(l).toHaveAttribute('data-hint', 'link.help.adr')
  })
})

describe('DocPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders a bundled guide with slug ids and a way back', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<DocPage />, { route: '/help/docs/DATA-RETENTION', path: '/help/docs/:name' })
    const article = await screen.findByRole('article')
    await waitFor(() => expect(within(article).getByRole('heading', { level: 2 })).toHaveTextContent(/retention and privacy/))
    expect(document.getElementById('2-retention-defaults-zero-raw-retention')).not.toBeNull()
    expect(screen.getByRole('link', { name: 'Back to glossary and guides' })).toHaveAttribute('href', '/help')
    // the non-goals, where the reader stands (G-150)
    expect(screen.getByText(/A copy of the repository’s guide, built into this deployment when it was installed\./)).toHaveTextContent('Read-only: it is changed in the repository, not here.')
  })

  it('a decision record renders at /help/docs/ADR-nnnn with its title and the same way back', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<DocPage />, { route: '/help/docs/ADR-0016', path: '/help/docs/:name' })
    expect(await screen.findByRole('heading', { level: 1, name: 'ADR-0016 — The two-person rule is a policy clause, not an apparatus move' })).toBeInTheDocument()
    const article = await screen.findByRole('article')
    await waitFor(() => expect(within(article).getByRole('heading', { level: 2 })).toHaveTextContent(/ADR-0016/))
    expect(screen.getByText(/A copy of the repository’s decision record/)).toHaveTextContent('Read-only')
    expect(screen.getByRole('link', { name: 'Back to glossary and guides' })).toHaveAttribute('href', '/help')
  })

  it('a guide and a decision record each carry exactly one h1 — the page title — with the file’s own title one level under it', async () => {
    for (const [name, title] of [
      ['DATA-RETENTION', /retention and privacy/],
      ['ADR-0016', /ADR-0016/],
    ] as const) {
      mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
      const view = renderApp(<DocPage />, { route: `/help/docs/${name}`, path: '/help/docs/:name' })
      const article = await screen.findByRole('article')
      await waitFor(() => expect(within(article).getAllByRole('heading').length).toBeGreaterThan(1))
      // one h1 per page: two made the walkthrough's heading query ambiguous (13-orient) and
      // give a screen-reader two page titles
      expect(document.querySelectorAll('h1'), name).toHaveLength(1)
      expect(within(article).queryAllByRole('heading', { level: 1 }), name).toHaveLength(0)
      expect(within(article).getAllByRole('heading')[0], name).toHaveTextContent(title)
      expect(within(article).getAllByRole('heading')[0]!.tagName, name).toBe('H2')
      view.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('a guide whose chunk fails to load says so with Retry — never "No guide with that name" — and Retry loads it', async () => {
    chunk.failures = 1
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<DocPage />, { route: '/help/docs/SECURITY', path: '/help/docs/:name' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The guide could not be loaded')
    expect(alert).toHaveTextContent('This deployment holds the guide')
    expect(screen.queryByText('No guide with that name')).not.toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    const article = await screen.findByRole('article')
    await waitFor(() => expect(within(article).getByRole('heading', { level: 2 })).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('an unknown name renders the empty state with a link to /help', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<DocPage />, { route: '/help/docs/NOPE', path: '/help/docs/:name' })
    expect(await screen.findByRole('heading', { level: 1, name: 'No guide with that name' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Glossary and guides' })).toHaveAttribute('href', '/help')
  })
})
