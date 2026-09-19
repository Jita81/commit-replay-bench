/**
 * HelpPage / DocPage — the glossary lists every term with an id; a guide renders from the
 * bundle; an unknown guide says so.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the two help screens.
 * What it does: Pins that /help renders the 22 terms as a definition list with `id` per term
 *               and a link to its guide, the eight guides as links to /help/docs/<name>, and
 *               the ADR index; that /help/docs/OPERATOR renders the guide's h1 with slug ids
 *               and links back to /help; and that an unknown name renders the empty state.
 * How:          `mockApi` + `renderApp` at the route with `path` for `useParams`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Help/HelpPage.tsx, ui/src/screens/Help/DocPage.tsx
 * Tested by:    ui/src/screens/Help/HelpPage.test.tsx
 * Touch when:   a section is added to either page.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TERM_IDS } from '../../help/glossary'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
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
})

describe('DocPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders a bundled guide with slug ids and a way back', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<DocPage />, { route: '/help/docs/DATA-RETENTION', path: '/help/docs/:name' })
    const article = await screen.findByRole('article')
    await waitFor(() => expect(within(article).getByRole('heading', { level: 1 })).toHaveTextContent(/retention and privacy/))
    expect(document.getElementById('2-retention-defaults-zero-raw-retention')).not.toBeNull()
    expect(screen.getByRole('link', { name: 'Back to glossary and guides' })).toHaveAttribute('href', '/help')
  })

  it('an unknown name renders the empty state with a link to /help', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<DocPage />, { route: '/help/docs/NOPE', path: '/help/docs/:name' })
    expect(await screen.findByRole('heading', { level: 1, name: 'No guide with that name' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Glossary and guides' })).toHaveAttribute('href', '/help')
  })
})
