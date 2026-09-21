/**
 * Help.tsx — the term button is accessible, the About block follows the route and the role.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `Term`, `AboutThisScreen` and `DocLink`.
 * What it does: Pins that `Term` is a real button whose `aria-expanded` / `aria-controls`
 *               toggle an inline definition (click, Enter, Space), that Escape closes it, that
 *               the definition text is the glossary's and links to the guide and the glossary;
 *               that `AboutThisScreen` renders the entry for the current route with the next
 *               step for the signed-in role (falling down the ladder to viewer), every term,
 *               the read-more links and the glossary link, and renders nothing on a route
 *               with no entry; that `DocLink` builds the /help/docs href.
 * How:          `renderApp` with a mocked `/auth/me` per role; `Term` rendered inside a
 *               `MemoryRouter` on its own.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Help.tsx, ui/src/help/help.ts, ui/src/help/glossary.ts
 * Tested by:    ui/src/components/Help.test.tsx
 * Touch when:   the About block gains a part or `Term` changes its markup.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TERMS } from '../help/glossary'
import { PRINCIPAL, mockApi, renderApp } from '../test/utils'
import { AboutThisScreen, DocLink, Term } from './Help'

describe('Term', () => {
  it('is a button that toggles an inline definition with aria-expanded / aria-controls; Escape closes', async () => {
    render(
      <MemoryRouter>
        <p>
          The bracket is the <Term id="wilson">Wilson interval</Term>.
        </p>
      </MemoryRouter>,
    )
    const btn = screen.getByRole('button', { name: /Wilson interval/ })
    expect(btn).toHaveAttribute('type', 'button')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('note')).toBeNull()
    await userEvent.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    const note = screen.getByRole('note')
    expect(btn.getAttribute('aria-controls')).toBe(note.id)
    expect(note).toHaveTextContent(TERMS.wilson.short)
    expect(within(note).getByRole('link', { name: 'Read more' })).toHaveAttribute('href', '/help/docs/EVIDENCE-AND-CLAIMS#3-every-number-carries-its-method')
    expect(within(note).getByRole('link', { name: 'glossary' })).toHaveAttribute('href', '/help#wilson')
    await userEvent.keyboard('{Escape}')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('note')).toBeNull()
    btn.focus()
    await userEvent.keyboard('{Enter}')
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard(' ')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
  })

  it('without children it prints the glossary term; no hover title is set', () => {
    render(
      <MemoryRouter>
        <Term id="false_q1" />
      </MemoryRouter>,
    )
    const btn = screen.getByRole('button', { name: /false-Q1/ })
    expect(btn).not.toHaveAttribute('title')
  })
})

describe('DocLink', () => {
  it('links into the bundled guide', () => {
    render(
      <MemoryRouter>
        <DocLink to="GITHUB-APP#2-register-the-app-once-per-deployment">the GitHub App guide</DocLink>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'the GitHub App guide' })).toHaveAttribute('href', '/help/docs/GITHUB-APP#2-register-the-app-once-per-deployment')
  })

  it('is underlined, so a link inside a sentence is told apart from its text without colour (WCAG 1.4.1)', () => {
    render(
      <MemoryRouter>
        <p>
          Guide: <DocLink to="GITHUB-APP">Register the GitHub App</DocLink>.
        </p>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Register the GitHub App' })).toHaveClass('underline')
  })
})

describe('AboutThisScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the Baseline entry for a viewer: the four parts, the terms, the links', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    renderApp(<AboutThisScreen />, { route: '/results', path: '/results' })
    const about = await screen.findByTestId('about-this-screen')
    expect(within(about).getByText('About this screen')).toBeInTheDocument()
    expect(within(about).getByRole('heading', { level: 3, name: 'What this screen is for' })).toBeInTheDocument()
    expect(about).toHaveTextContent('This is the baseline the factory runs on.')
    expect(within(about).getByRole('heading', { level: 3, name: 'What to do next' })).toBeInTheDocument()
    expect(about).toHaveTextContent('Read the three gates first.')
    expect(about).not.toHaveTextContent('Attest takes you to the sign-off form')
    expect(within(about).getByRole('heading', { level: 3, name: 'What the numbers mean' })).toBeInTheDocument()
    expect(about).toHaveTextContent('The interval is the claim, not the point.')
    expect(within(about).getByRole('heading', { level: 3, name: 'Terms on this screen' })).toBeInTheDocument()
    expect(within(about).getByRole('link', { name: 'Wilson interval' })).toHaveAttribute('href', '/help#wilson')
    expect(about).toHaveTextContent(TERMS.granularize.short)
    expect(within(about).getByRole('link', { name: 'Read the map' })).toHaveAttribute('href', '/help/docs/ONBOARDING-A-REPO#step-5--read-the-map-everyone')
    expect(within(about).getByRole('link', { name: 'Glossary and guides' })).toHaveAttribute('href', '/help')
  })

  it('an approver on Baseline is told the approver step; an admin on Runs falls down the ladder to the operator step', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'approver' } })
    const first = renderApp(<AboutThisScreen />, { route: '/results', path: '/results' })
    await waitFor(() => expect(screen.getByTestId('about-this-screen')).toHaveTextContent('Attest takes you to the sign-off form'))
    first.unmount()
    vi.unstubAllGlobals()
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'admin' } })
    renderApp(<AboutThisScreen />, { route: '/runs/abc', path: '/runs/:id' })
    await waitFor(() => expect(screen.getByTestId('about-this-screen')).toHaveTextContent('cancel if the spend is wrong'))
  })

  it('renders nothing on a route with no entry', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' } })
    const { container } = renderApp(<AboutThisScreen />, { route: '/help', path: '/help' })
    await waitFor(() => expect(container.querySelector('[data-testid="user-chip"]')).toBeNull())
    expect(screen.queryByTestId('about-this-screen')).toBeNull()
    expect(container).toBeEmptyDOMElement()
  })
})
