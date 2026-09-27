/**
 * The context library screen — the page per work type, the index, the acts and the two-person rule.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests of ui/src/screens/Library/LibraryPage.tsx against the fixtures in
 *               library.fixture.ts.
 * What it does: Pins that the page for a work type says what it is (definition, example
 *               commits), what a ticket must carry, the signed context with sponsor, signer,
 *               date, provenance and an `unmeasured` effect, what is proven per size (arm, n,
 *               interval, apparatus — or "No proven standard" and the next measurement), and
 *               which switched-on checks evidence which ISO/IEC 25010 characteristic; that
 *               nothing is shown as reaching a brief; that an operator proposes and is told a
 *               second person must sign; that the sponsor's own Sign button is disabled with the
 *               reason while another approver's posts the version read; that a refusal is shown
 *               in the API's words; and that every element resolves to a hint.
 * How:          `renderApp` at `/library/alpha` with `mockApi`; the principal is switched by
 *               the mocked `GET /auth/me`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 10)
 * Works with:   ui/src/screens/Library/LibraryPage.tsx (the screen under test),
 *               ui/src/screens/Library/library.fixture.ts (the populated state),
 *               ui/src/help/hints-collector.ts (reads every hinted element)
 * Tested by:    this file
 * Touch when:   never for a new repository; a section or an act of the page changes.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { ADA, LIBRARY, LIBRARY_API, WORK_TYPE } from './library.fixture'
import { LibraryPage } from './LibraryPage'

const AT = { route: '/library/alpha', path: '/library/:repo' }

describe('LibraryPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('the page for a work type says what it is, what a ticket carries, the signed context and what is proven per size', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, ...LIBRARY_API })
    const { container } = renderApp(<LibraryPage />, AT)
    await screen.findByRole('heading', { name: 'Work type: bug.fix' })
    const page = container
    expect(page).toHaveTextContent('Repairs a defect')
    expect(screen.getByRole('link', { name: 'cccccccccccc' })).toHaveAttribute('href', `/tasks/alpha/${'c'.repeat(40)}`)
    expect(page).toHaveTextContent('expected_behavior — What should happen instead?')
    const ctx = screen.getByRole('table', { name: 'Signed context for bug.fix' })
    const row = within(ctx).getByText('convention/errors-wrap').closest('tr')!
    expect(row).toHaveTextContent('Ada')
    expect(row).toHaveTextContent('Ben')
    expect(row).toHaveTextContent('unmeasured')
    expect(within(ctx).queryByText('convention/context-first')).not.toBeInTheDocument() // unsigned: never context
    const sizes = screen.getByRole('table', { name: 'Proven standard per size for bug.fix' })
    const xs = within(sizes).getByText('XS').closest('tr')!
    expect(xs).toHaveTextContent('S1@gpt-oss-120b')
    expect(xs).toHaveTextContent('20 of 20')
    expect(xs).toHaveTextContent('83.9% to 100.0%')
    expect(xs).toHaveTextContent('apparatus 2.4')
    const s = within(sizes).getByText('S').closest('tr')!
    expect(s).toHaveTextContent('No proven standard')
    expect(s).toHaveTextContent('A first look needs 20 distinct commits; 6 commits')
    const quality = screen.getByRole('table', { name: /ISO\/IEC 25010 characteristics/ })
    expect(within(quality).getByText('Functional suitability').closest('tr')).toHaveTextContent('Part of it')
    expect(within(quality).getByText('Security').closest('tr')).toHaveTextContent('Not evidenced')
    expect(page).toHaveTextContent('standard/vet refines Maintainability')
    expect(page).toHaveTextContent('evidenced by go-vet')
    expect(screen.getAllByText('Reaches no brief').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /Propose/ })).not.toBeInTheDocument() // a viewer proposes nothing
    expect(unhinted(container)).toEqual([])
  })

  it('without the quality table on the build the page names no characteristic as evidenced', async () => {
    const page = { ...WORK_TYPE, quality: { ...WORK_TYPE.quality, served: false, rows: [] } }
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /library/alpha': LIBRARY, 'GET /library/alpha/work-types/bug.fix': page })
    renderApp(<LibraryPage />, AT)
    expect(await screen.findByTestId('quality-not-served')).toHaveTextContent('not on this build')
  })

  it('an operator proposes an entry and is told a different approver must sign it', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      ...LIBRARY_API,
      'POST /library/alpha/entries': (_u: string, init: RequestInit | undefined) => {
        const body = JSON.parse(String(init?.body)) as { kind: string; slug: string }
        return json({ ...LIBRARY.entries[1], entry_id: `${body.kind}/${body.slug}` }, 201)
      },
    })
    renderApp(<LibraryPage />, AT)
    await screen.findByRole('heading', { name: 'Propose an entry' })
    await userEvent.type(screen.getByLabelText(/Short name \(slug\)/), 'no-globals')
    await userEvent.type(screen.getByLabelText(/^Title/), 'No package globals')
    await userEvent.type(screen.getByLabelText(/^Statement/), 'State lives on the command, never in a package variable.')
    await userEvent.type(screen.getByLabelText('Work types it applies to'), 'bug.fix, feature.add')
    await userEvent.click(screen.getByRole('button', { name: 'Propose as sponsor' }))
    await waitFor(() => expect(screen.getByTestId('library-proposed')).toHaveTextContent('Proposed convention/no-globals. You are its sponsor; a different approver must sign it.'))
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({ kind: 'convention', slug: 'no-globals', work_types: ['bug.fix', 'feature.add'] })
    // a mined proposal nobody adopted offers the operator Sponsor
    const mined = screen.getAllByText('decision/adr-0001').find((el) => el.closest('tr'))!.closest('tr')!
    expect(within(mined).getByRole('button', { name: 'Sponsor' })).toBeEnabled()
  })

  it('the sponsor cannot sign their own entry; another approver signs the version read', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, id: ADA }, // the sponsor of every fixture entry
      ...LIBRARY_API,
    })
    renderApp(<LibraryPage />, AT)
    await screen.findByRole('table', { name: 'Library entries for alpha' })
    const own = screen.getAllByText('convention/context-first').find((el) => el.closest('tr'))!.closest('tr')!
    expect(within(own).getByRole('button', { name: 'Sign' })).toBeDisabled()
    expect(own).toHaveTextContent('You sponsored this entry, so a second person must sign it.')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    vi.unstubAllGlobals()
  })

  it('a second approver signs, and a refusal is shown in the API’s words', async () => {
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL, // u1: not the sponsor
      ...LIBRARY_API,
      'POST /library/alpha/entries/convention/context-first/sign': () => envelope(409, 'library_refused', 'the sponsor cannot sign their own entry — a second person must sign it', { code: 'same_person' }),
    })
    renderApp(<LibraryPage />, AT)
    await screen.findByRole('table', { name: 'Library entries for alpha' })
    const row = screen.getAllByText('convention/context-first').find((el) => el.closest('tr'))!.closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: 'Sign' }))
    await waitFor(() => expect(screen.getByTestId('library-refused')).toHaveTextContent('a second person must sign it'))
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ version: 'e'.repeat(64) })
    const stale = screen.getAllByText('convention/lint').find((el) => el.closest('tr'))!.closest('tr')!
    expect(within(stale).getByRole('button', { name: 'Sign again' })).toBeEnabled()
  })
})
