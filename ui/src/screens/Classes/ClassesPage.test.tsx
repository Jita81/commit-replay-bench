/**
 * The classes screen: a version with its report, a class's page in plain words, blind labelling,
 * and the two-person rule at the Sign button.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests of ui/src/screens/Classes/ClassesPage.tsx over the fixture
 *               organisation (ui/src/screens/Classes/classes.fixture.ts).
 * What it does: Pins that an unsigned version reads "Routes nothing" with the reason; that the
 *               validity report shows each measure's result, n and state; that a class's page
 *               says what the work is, the rule in words, derivation examples, what a ticket
 *               carries, the signed context and "No proven standard" per size; that the labelling
 *               screen shows the next commit to label and never the rule's answer, and posts a
 *               person's label; that the sponsor's own Sign button is disabled with the reason
 *               while another approver's posts the digest read; and that every element carries a
 *               hint.
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
import { ADA, CLASSES_API, SUMMARY } from './classes.fixture'
import { ClassesPage } from './ClassesPage'

const AT = { route: '/classes?org=acme&v=1&class=parser-fix', path: '/classes' }

describe('ClassesPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a version reads its report and routes nothing unsigned; a class page reads in plain words', async () => {
    mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, ...CLASSES_API })
    const { container } = renderApp(<ClassesPage />, AT)
    await screen.findByRole('heading', { name: 'Class set acme/classes@v1' })
    expect(screen.getAllByText('Routes nothing').length).toBeGreaterThan(0)
    expect(container).toHaveTextContent('No approver other than its sponsor has signed it, so it routes nothing.')
    const report = screen.getByRole('table', { name: 'Validity report of acme/classes@v1' })
    const agreement = within(report).getByText('Agreement with a person (κ)').closest('tr')!
    expect(agreement).toHaveTextContent('0.41')
    expect(agreement).toHaveTextContent('fail')
    expect(within(report).getByText('Ticket and message agree').closest('tr')).toHaveTextContent('not applicable')
    const split = screen.getByRole('table', { name: 'Derivation and confirmation commits of acme/classes@v1' })
    expect(within(split).getByText('alpha').closest('tr')).toHaveTextContent('70')
    await screen.findByRole('heading', { name: 'Class: A fix to the parser' })
    expect(screen.getByTestId('class-rule')).toHaveTextContent("the ticket's text says “parser” or “parse”")
    expect(screen.getByRole('link', { name: 'cccccccccccc' })).toHaveAttribute('href', `/tasks/alpha/${'c'.repeat(40)}`)
    expect(container).toHaveTextContent('read from its message')
    expect(container).toHaveTextContent('reproduction — How is the bug reproduced')
    expect(screen.getByRole('link', { name: /alpha library’s bug.fix page/ })).toHaveAttribute('href', '/library/alpha?type=bug.fix')
    const sizes = screen.getByRole('table', { name: 'Proven standard per size for parser-fix' })
    expect(within(sizes).getAllByText('No proven standard').length).toBe(2)
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
    await userEvent.selectOptions(screen.getByLabelText('Which class is it?'), 'cli-fix')
    await userEvent.click(screen.getByRole('button', { name: 'Save label' }))
    await waitFor(() => expect(posted).toEqual([{ repo: 'alpha', task_id: 'e'.repeat(40), class: 'cli-fix' }]))
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
  })
})
