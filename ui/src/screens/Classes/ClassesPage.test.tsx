/**
 * The classes screen: a version with its report, a class's page in plain words, blind labelling,
 * and the two-person rule at the Sign button.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests of ui/src/screens/Classes/ClassesPage.tsx over the fixture
 *               organisation (ui/src/screens/Classes/classes.fixture.ts).
 * What it does: Pins that an unsigned version reads "Routes nothing" with the reason; that the
 *               validity report shows each measure's result, n and state, the points check
 *               saying what it decides rather than "fail", and a withheld agreement as withheld;
 *               that a class's page says what the work is with its parent's meaning, the rule in
 *               words, derivation examples, what a ticket carries (or, with no slot, says so),
 *               the signed context with underlined links and "No proven standard" per size with
 *               the reason once; that a failed class or queue read is said; that the labelling
 *               screen shows the next commit and what each class means, never the rule's answer,
 *               posts a person's label, moves focus to the next commit and says what was saved,
 *               and says what to do when the queue is empty, short or the reader is its
 *               sponsor; that the proposal form lists the global parents; that the back link
 *               goes to the context library; that the sponsor's own Sign button is disabled with
 *               the reason while another approver's posts the digest read and hears the result;
 *               and that every element carries a hint.
 * How:          `mockApi` + `renderApp` (ui/src/test/utils.tsx); `unhinted` over the container.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 9)
 * Works with:   ui/src/screens/Classes/ClassesPage.tsx (under test),
 *               ui/src/screens/Classes/classes.fixture.ts (the state),
 *               ui/src/help/hints-collector.ts (reads every hinted element)
 * Tested by:    this file
 * Touch when:   never for a new repository; a section or an act of the page changes.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, json, mockApi, renderApp } from '../../test/utils'
import { ADA, CLASS_PAGE, CLASSES_API, QUEUE, SUMMARY, VERSION } from './classes.fixture'
import { ClassesPage } from './ClassesPage'

const AT = { route: '/classes?org=acme&v=1&class=parser-fix', path: '/classes' }

describe('ClassesPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a version reads its report and routes nothing unsigned; a class page reads in plain words', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, ...CLASSES_API })
    const { container } = renderApp(<ClassesPage />, AT)
    await screen.findByRole('heading', { name: 'Class set acme/classes@v1' })
    expect(screen.getAllByText('Routes nothing').length).toBeGreaterThan(0)
    // at 375 px the versions table keeps Open on screen: the id breaks, the route tag wraps
    const versions = screen.getByRole('table', { name: 'Class-set versions' })
    expect(within(versions).getAllByTestId('version-id')[0]).toHaveClass('break-all')
    expect(within(versions).getAllByTestId('version-routes')[0]!.className).not.toContain('whitespace-nowrap')
    expect(container).toHaveTextContent('No approver other than its sponsor has signed it, so it routes nothing.')
    const report = screen.getByRole('table', { name: 'Validity report of acme/classes@v1' })
    const agreement = within(report).getByText('Agreement with a person (κ)').closest('tr')!
    expect(agreement).toHaveTextContent('0.41')
    expect(agreement).toHaveTextContent('fail')
    expect(within(report).getByText('Ticket and message agree').closest('tr')).toHaveTextContent('not applicable')
    const split = screen.getByRole('table', { name: 'Derivation and confirmation commits of acme/classes@v1' })
    expect(within(split).getByText('alpha').closest('tr')).toHaveTextContent('70')
    await screen.findByRole('heading', { name: 'Class: A fix to the parser' })
    expect(screen.getByTestId('class-rule')).toHaveTextContent('the ticket’s text says “parser” or “parse”')
    expect(container).toHaveTextContent('a kind of bug.fix: Fixes a defect in existing behaviour.')
    expect(screen.getByRole('link', { name: 'Back to the context library' })).toHaveAttribute('href', '/library/alpha')
    const report2 = screen.getByRole('table', { name: 'Validity report of acme/classes@v1' })
    const points = within(report2).getByText('Points agree with churn').closest('tr')!
    expect(within(points).getByTestId('measure-size_agreement')).toHaveTextContent('points not used')
    expect(points).not.toHaveTextContent(/\bfail\b/)
    expect(screen.getByRole('link', { name: 'cccccccccccc' })).toHaveAttribute('href', `/tasks/alpha/${'c'.repeat(40)}`)
    expect(container).toHaveTextContent('read from its message')
    expect(container).toHaveTextContent('reproduction — How is the bug reproduced')
    const library = screen.getByRole('link', { name: /alpha library’s bug.fix page/ })
    expect(library).toHaveAttribute('href', '/library/alpha?type=bug.fix')
    // a link inside running text is underlined, not told apart by colour alone (WCAG 1.4.1, P-687)
    expect(library).toHaveClass('underline')
    expect(screen.getByRole('link', { name: 'cccccccccccc' })).toHaveClass('underline')
    const sizes = screen.getByRole('table', { name: 'Proven standard per size for parser-fix' })
    expect(within(sizes).getAllByText('No proven standard').length).toBe(2)
    expect(container).toHaveTextContent('No size has a proven standard while the class set routes nothing: No approver other than its sponsor')
    expect(within(sizes).queryByText(/No approver/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Propose/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Label a sample')).not.toBeInTheDocument()
    expect(unhinted(container)).toEqual([])
  })

  it('the labelling screen shows the next commit, never the rule’s answer, and posts a person’s label', async () => {
    const posted: unknown[] = []
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      ...CLASSES_API,
      'POST /classes/acme/v/1/labels': (_url: string, init?: RequestInit) => {
        posted.push(JSON.parse(String(init?.body)))
        return json({ version_id: 'acme/classes@v1' }, 201)
      },
    })
    const { container } = renderApp(<ClassesPage />, AT)
    const message = await screen.findByTestId('label-message')
    expect(message).toHaveTextContent('fix: the cli flag --x4 is ignored')
    expect(container).toHaveTextContent('You have labelled 1 of 2 derivation commits')
    expect(container).toHaveTextContent('No linked ticket: the message stands in for one.')
    expect(container).toHaveTextContent('1 source file and 2 test files, 12 lines of source.')
    // what each class means, so the label is a reading of the definition
    const meanings = screen.getByTestId('label-definitions')
    expect(meanings).toHaveTextContent('A fix to the command line (cli-fix): A change that corrects the command line’s flags.')
    expect(container).not.toHaveTextContent('never the rule’s answer')
    await userEvent.selectOptions(screen.getByLabelText('Which class is it?'), 'cli-fix')
    await userEvent.click(screen.getByRole('button', { name: 'Save label' }))
    await waitFor(() => expect(posted).toEqual([{ repo: 'alpha', task_id: 'e'.repeat(40), class: 'cli-fix' }]))
    // the result is said by the commit's words, and focus moves to the next commit's message
    await waitFor(() => expect(screen.getByTestId('class-labelled')).toHaveTextContent('Saved: “fix: the cli flag --x4 is ignored” is A fix to the command line.'))
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('label-next')))
    expect(unhinted(container)).toEqual([])
  })

  it('the sponsor cannot sign; another approver signs the digest they read', async () => {
    const signed: unknown[] = []
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, id: ADA, role: 'approver' },
      ...CLASSES_API,
    })
    const first = renderApp(<ClassesPage />, AT)
    const own = await screen.findByRole('button', { name: 'Sign this class set' })
    expect(own).toBeDisabled()
    expect(first.container).toHaveTextContent('You sponsored this class set, so a second person must sign it.')
    first.unmount()
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'approver' },
      ...CLASSES_API,
      'POST /classes/acme/v/1/sign': (_url: string, init?: RequestInit) => {
        signed.push(JSON.parse(String(init?.body)))
        return json({ ...SUMMARY, status: 'signed' })
      },
    })
    renderApp(<ClassesPage />, AT)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign this class set' }))
    await waitFor(() => expect(signed).toEqual([{ digest: 'd'.repeat(64) }]))
    // the result is announced where focus lands, with why it still routes nothing
    const said = screen.getByTestId('class-set-signed')
    await waitFor(() => expect(said).toHaveTextContent('You signed acme/classes@v1. No approver other than its sponsor has signed it'))
    expect(document.activeElement).toBe(said)
  })

  it('a class with no readiness slot says so, and opening a class brings its heading into focus', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      ...CLASSES_API,
      'GET /classes/acme/v/1/classes/parser-fix': { ...CLASS_PAGE, parent: 'feature.add', ticket_slots: [] },
    })
    const { container } = renderApp(<ClassesPage />, AT)
    const heading = await screen.findByRole('heading', { name: 'Class: A fix to the parser' })
    await waitFor(() => expect(document.activeElement).toBe(heading))
    const none = screen.getByTestId('class-no-slots')
    expect(none).toHaveTextContent('No readiness question is set for feature.add yet')
    expect(within(none).getByRole('link', { name: 'the library' })).toHaveAttribute('href', '/library/alpha?type=bug.fix')
    expect(unhinted(container)).toEqual([])
  })

  it('a class or a queue that cannot be read says why', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      ...CLASSES_API,
      'GET /classes/acme/v/1/classes/nope': () => json({ error: { code: 'not_found', message: "acme/classes@v1 has no class 'nope'", detail: {} } }, 404),
      'GET /classes/acme/v/1/label-queue': () => json({ error: { code: 'not_found', message: 'no class set', detail: {} } }, 404),
    })
    const { container } = renderApp(<ClassesPage />, { route: '/classes?org=acme&v=1&class=nope', path: '/classes' })
    await screen.findByRole('heading', { name: 'Class set acme/classes@v1' })
    await waitFor(() => expect(container).toHaveTextContent("acme/classes@v1 has no class 'nope'"))
    expect(container).toHaveTextContent('no class set')
  })

  it('the labelling screen says what to do when there is nothing, too little or it is yours', async () => {
    for (const [queue, words] of [
      [{ ...QUEUE, items: [], labelled_by_me: 0 }, 'No derivation commit is ready to label yet. Mine more of the repositories’ history'],
      [{ ...QUEUE, items: QUEUE.items.map((x) => ({ ...x, my_label: 'cli-fix' })), labelled_by_me: 2 }, 'Its sample needs 48 more commits than its repositories hold'],
      [{ ...QUEUE, items: [], labelled_by_me: 0, sponsor: true }, 'You sponsored this class set. Its rule is your own words, so another person labels its sample'],
    ] as const) {
      mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'operator' }, ...CLASSES_API, 'GET /classes/acme/v/1/label-queue': queue })
      const view = renderApp(<ClassesPage />, AT)
      await waitFor(() => expect(view.container).toHaveTextContent(words))
      expect(screen.queryByRole('button', { name: 'Save label' })).not.toBeInTheDocument()
      view.unmount()
    }
  })

  it('the proposal form lists the global classes a class can refine, and a withheld agreement reads withheld', async () => {
    const withheld = {
      ...VERSION,
      report: {
        ...VERSION.report,
        measures: VERSION.report.measures.map((m) => (m.name === 'agreement' ? { ...m, value: null, state: 'withheld' as const, words: 'Withheld from you while you label this version’s sample.' } : m)),
      },
    }
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'operator' }, ...CLASSES_API, 'GET /classes/acme/v/1': withheld })
    const { container } = renderApp(<ClassesPage />, AT)
    const parents = await screen.findByTestId('global-parents')
    expect(parents).toHaveTextContent('bug.fix — Fixes a defect in existing behaviour.')
    expect(parents).toHaveTextContent('feature.add — Adds a new capability.')
    const report = await screen.findByRole('table', { name: 'Validity report of acme/classes@v1' })
    const agreement = within(report).getByText('Agreement with a person (κ)').closest('tr')!
    expect(within(agreement).getByTestId('measure-agreement')).toHaveTextContent('withheld')
    expect(agreement).toHaveTextContent('—')
    expect(unhinted(container)).toEqual([])
  })
})
