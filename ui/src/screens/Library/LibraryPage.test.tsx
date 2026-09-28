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
 *               second person must sign; that an operator runs the miners and is told what was
 *               proposed and that each proposal waits for a person, while a viewer is not offered
 *               them; that the sponsor's own Sign button is disabled with the
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

  it('a ceiling says "ceiling only — forward-unvalidated", what a calibration build needs, and its forward reading with its n', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, ...LIBRARY_API })
    const { container } = renderApp(<LibraryPage />, AT)
    await screen.findByRole('heading', { name: 'Work type: bug.fix' })
    const sizes = screen.getByRole('table', { name: 'Proven standard per size for bug.fix' })
    const l = within(sizes).getByText('L').closest('tr')!
    expect(l).toHaveTextContent('S3 (ceiling only — forward-unvalidated)')
    expect(within(l).getByTestId('ceiling-L')).toHaveTextContent('built only as a calibration build, which never opens a pull request')
    expect(within(l).getByTestId('forward-L')).toHaveTextContent('Forward reading: reading · n = 1 (1 passed the held-out tests) · 19 more to its look at 20')
    expect(within(l).getByTestId('forward-L')).toHaveAttribute('data-hint', 'item.library.forward')
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

  it('an operator proposes from the repository’s files and is told each proposal waits for a person', async () => {
    const mined = { ...LIBRARY.entries[1], entry_id: 'convention/ruff', sponsor: '', sponsor_name: '', entry: { ...LIBRARY.entries[1]!.entry, proposed_by: 'mined:lint@1' } }
    const run = (proposed: number, unchanged: number) => ({
      repo: 'alpha',
      commit: 'a'.repeat(40),
      miners: ['adrs@1', 'owners@1', 'lint@2', 'tests@1', 'change-profile@1'],
      counts: { proposed, unchanged, held: 0, refused: 0, noted: 1, failed: 0 },
      proposed: proposed ? [mined] : [],
      outcomes: [],
      files_read: 7,
      reaches_briefs: false,
    })
    let n = 0
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      ...LIBRARY_API,
      'POST /library/alpha/mine': () => json(n++ === 0 ? run(1, 0) : run(0, 1)),
    })
    const { container } = renderApp(<LibraryPage />, AT)
    await screen.findByRole('heading', { name: 'Propose from the repository’s files' })
    await userEvent.type(screen.getByLabelText(/^Commit/), 'main')
    await userEvent.click(screen.getByRole('button', { name: 'Propose from the files' }))
    await waitFor(() =>
      expect(screen.getByTestId('library-mined')).toHaveTextContent(
        'Read alpha at aaaaaaaaaaaa: 1 proposed, 0 unchanged, 1 noted. Each proposal waits for a person to sponsor it and a different approver to sign it.',
      ),
    )
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ commit: 'main' })
    // the same commit again proposes nothing new
    await userEvent.click(screen.getByRole('button', { name: 'Propose from the files' }))
    await waitFor(() => expect(screen.getByTestId('library-mined')).toHaveTextContent('0 proposed, 1 unchanged, 1 noted. Nothing new at this commit.'))
    expect(unhinted(container)).toEqual([])
  })

  it('a viewer is not offered the miners', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, ...LIBRARY_API })
    renderApp(<LibraryPage />, AT)
    await screen.findByRole('table', { name: 'Library entries for alpha' })
    expect(screen.queryByRole('button', { name: 'Propose from the files' })).not.toBeInTheDocument()
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

  it('a refused proposal is said at its own form, marks the field it names, and takes focus (P-397)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      ...LIBRARY_API,
      'POST /library/alpha/entries': () => envelope(422, 'invalid_entry', 'a slug is lower case letters, digits, ‘.’, ‘_’ or ‘-’, at most 64 characters'),
    })
    renderApp(<LibraryPage />, AT)
    const card = (await screen.findByRole('heading', { name: 'Propose an entry' })).closest('section, div')!.parentElement!
    const form = screen.getByRole('form', { name: 'Propose an entry for alpha' })
    await userEvent.type(screen.getByLabelText(/Short name \(slug\)/), 'Bad Slug!')
    await userEvent.type(screen.getByLabelText(/^Title/), 'No package globals')
    await userEvent.type(screen.getByLabelText(/^Statement/), 'State lives on the command.')
    await userEvent.click(screen.getByRole('button', { name: 'Propose as sponsor' }))
    const refused = await within(form).findByTestId('library-propose-refused')
    expect(refused).toHaveTextContent('a slug is lower case letters')
    await waitFor(() => expect(document.activeElement).toBe(refused))
    expect(screen.getByLabelText(/Short name \(slug\)/)).toHaveAttribute('aria-invalid', 'true')
    expect(within(card).queryByTestId('library-refused')).toBeNull()
    expect(screen.queryByTestId('library-refused')).toBeNull() // never at the top of the page
  })

  it('a retirement says what it did beside its form and clears it; an empty press asks at the fields instead of a silent disabled button (P-397)', async () => {
    const retired = { ...LIBRARY.entries[1]!, status: 'retired' as const }
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      ...LIBRARY_API,
      [`POST /library/alpha/entries/${LIBRARY.entries[1]!.entry_id}/retire`]: () => json(retired),
    })
    renderApp(<LibraryPage />, AT)
    const form = await screen.findByRole('form', { name: 'Revoke or retire an entry' })
    const retire = within(form).getByRole('button', { name: 'Retire' })
    expect(retire).toBeEnabled()
    await userEvent.click(retire)
    expect(within(form).getByLabelText('Entry')).toHaveAttribute('aria-invalid', 'true')
    expect(within(form).getByLabelText('Reason')).toHaveAttribute('aria-invalid', 'true')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    await userEvent.selectOptions(within(form).getByLabelText('Entry'), LIBRARY.entries[1]!.entry_id)
    await userEvent.type(within(form).getByLabelText('Reason'), 'no longer how we work')
    await userEvent.click(retire)
    await waitFor(() => expect(within(form).getByTestId('library-withdrawn')).toHaveTextContent(`Retired ${LIBRARY.entries[1]!.entry_id}: no longer how we work`))
    expect((within(form).getByLabelText('Entry') as HTMLSelectElement).value).toBe('')
    expect((within(form).getByLabelText('Reason') as HTMLInputElement).value).toBe('')
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
    // said beside the table the act was pressed in, and focused (P-397)
    const index = screen.getByRole('table', { name: 'Library entries for alpha' }).closest('[data-testid="library-index"]')!
    expect(within(index as HTMLElement).getByTestId('library-refused')).toBe(document.activeElement)
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ version: 'e'.repeat(64) })
    const stale = screen.getAllByText('convention/lint').find((el) => el.closest('tr'))!.closest('tr')!
    expect(within(stale).getByRole('button', { name: 'Sign again' })).toBeEnabled()
  })
})
