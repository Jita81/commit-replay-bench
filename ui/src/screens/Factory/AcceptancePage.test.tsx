/**
 * The held-out acceptance-test screen (ADR-0026 item 8).
 *
 * Navigation
 * ----------
 * What it is:   The screen test of /factory/acceptance.
 * What it does: Pins that a ticket is shown as it was written — never its own failing test —
 *               with who funded its calibration build; that a person who may write the tests
 *               sends exactly the path and text they typed and is told the builder never sees
 *               them; that a refusal is shown in the API's words beside the form; that an empty
 *               press asks at the fields and sends nothing; that a person who may not write
 *               them is told why and has no form; and that a graded ticket shows its record's
 *               author, digest and result, never the tests.
 * How:          `mockApi` + `renderApp` over the screen's fixture; `userEvent` for the form.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 8)
 * Works with:   ui/src/screens/Factory/AcceptancePage.tsx (under test),
 *               ui/src/screens/Factory/acceptance.fixture.ts (the assignments),
 *               ui/src/test/utils.tsx (`mockApi`, `renderApp`)
 * Tested by:    itself
 * Touch when:   never for a new repository; the screen gains an act or a state.
 */
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { AcceptanceAssignments } from '../../api/types'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { AcceptancePage } from './AcceptancePage'
import { ACCEPTANCE, WRITER_ID } from './acceptance.fixture'

const REPOS = { items: [{ name: 'alpha', language: 'python', runner: 'pytest', url: '', created: '2026-09-01T10:00:00+00:00' }], total: 1, limit: 50, offset: 0 }
const OPERATOR = { ...PRINCIPAL, role: 'operator' }

function setup(body: AcceptanceAssignments = ACCEPTANCE, extra: Record<string, unknown> = {}, me: unknown = OPERATOR) {
  const api = mockApi({ 'GET /auth/me': me, 'GET /repos': REPOS, 'GET /factory/alpha/acceptance': body, ...extra })
  renderApp(<AcceptancePage />, { route: '/factory/acceptance?repo=alpha', path: '/factory/acceptance' })
  return api
}

afterEach(cleanup)

describe('AcceptancePage', () => {
  it('shows the ticket as written and who funded its build, never its own failing test', async () => {
    setup()
    const card = await screen.findByTestId('acceptance-I-1')
    expect(card).toHaveTextContent('calc needs a multiply(a, b) function.')
    expect(card).toHaveTextContent('multiply(3, 4) == 12')
    expect(card).toHaveTextContent('bug.fix · XS')
    expect(card).toHaveTextContent('Ada Approver')
    expect(within(card).getByTestId('acceptance-status-I-1')).toHaveTextContent('tests needed')
    // the form starts from a path this repository's runner accepts, served by the API
    expect(within(card).getByLabelText('Test file')).toHaveValue('tests/test_i_1_held_out.py')
    // and says which forward reading will count the tests written now
    expect(card).toHaveTextContent('Registered (rdg_forward): tests written now are counted by it.')
    expect(document.body.textContent).not.toContain('def test_')
  })

  it('sends exactly the path and the tests typed, and says the builder never sees them', async () => {
    // after the save the list is read again and the ticket reads "tests written": the
    // confirmation must survive the form going away
    let posted = false
    const written: AcceptanceAssignments = {
      ...ACCEPTANCE,
      assignments: [{ ...ACCEPTANCE.assignments[0]!, status: 'written', can_write: false, why_not: 'held-out acceptance tests are already written for this build' }, ACCEPTANCE.assignments[1]!],
    }
    const api = setup(ACCEPTANCE, {
      'GET /factory/alpha/acceptance': () => json(posted ? written : ACCEPTANCE),
      'POST /factory/alpha/items/I-1/acceptance': () => {
        posted = true
        return json({ record_id: 'hot_x', item_id: 'I-1', grant: 'g1', author: 'operator:u', written_at: '2026-09-28T11:00:00+00:00', sha256: 'b'.repeat(64), paths: ['tests/test_mine.py'] }, 201)
      },
    })
    const user = userEvent.setup()
    const form = await screen.findByRole('form', { name: 'Write the held-out tests for I-1' })
    const path = within(form).getByLabelText('Test file')
    await user.clear(path)
    await user.type(path, 'tests/test_mine.py')
    await user.type(within(form).getByLabelText('Held-out acceptance tests'), 'def test_it():{Enter}    assert True')
    await user.click(within(form).getByRole('button', { name: 'Save the held-out tests' }))
    await waitFor(() => expect(screen.getByTestId('acceptance-saved-I-1')).toBeInTheDocument())
    expect(screen.getByTestId('acceptance-saved-I-1')).toHaveTextContent('The builder never sees them')
    await waitFor(() => expect(screen.getByTestId('acceptance-status-I-1')).toHaveTextContent('tests written'))
    expect(screen.getByTestId('acceptance-saved-I-1')).toBeInTheDocument()
    const post = api.calls.find((c) => c.method === 'POST')
    expect(JSON.parse(String(post?.init?.body))).toEqual({ files: [{ path: 'tests/test_mine.py', content: 'def test_it():\n    assert True' }] })
  })

  it('an empty press asks at the fields and sends nothing', async () => {
    const api = setup()
    const user = userEvent.setup()
    const form = await screen.findByRole('form', { name: 'Write the held-out tests for I-1' })
    await user.click(within(form).getByRole('button', { name: 'Save the held-out tests' }))
    expect(await within(form).findByText('Write at least one test.')).toBeInTheDocument()
    expect(api.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows a refusal in the API’s words beside the form', async () => {
    setup(ACCEPTANCE, {
      'POST /factory/alpha/items/I-1/acceptance': () => envelope(403, 'acceptance_same_person', 'the ticket’s author may not write its held-out acceptance tests'),
    })
    const user = userEvent.setup()
    const form = await screen.findByRole('form', { name: 'Write the held-out tests for I-1' })
    await user.type(within(form).getByLabelText('Held-out acceptance tests'), 'def test_it(): pass')
    await user.click(within(form).getByRole('button', { name: 'Save the held-out tests' }))
    expect(await within(form).findByTestId('acceptance-refused-I-1')).toHaveTextContent('the ticket’s author may not write its held-out acceptance tests')
  })

  it('tells a person who may not write them why, and offers no form', async () => {
    const body: AcceptanceAssignments = {
      ...ACCEPTANCE,
      assignments: [{ ...ACCEPTANCE.assignments[0]!, can_write: false, why_not: 'the approver who funded the calibration build may not write its held-out tests' }],
    }
    setup(body)
    expect(await screen.findByTestId('acceptance-why-I-1')).toHaveTextContent('the approver who funded the calibration build may not write')
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
  })

  it('a graded ticket shows who wrote its tests, their digest and the result — never the tests', async () => {
    setup()
    const card = await screen.findByTestId('acceptance-I-2')
    expect(within(card).getByTestId('acceptance-status-I-2')).toHaveTextContent('graded')
    // a whole name, never an id cut to eight characters (verify_fwd_user)
    expect(card).toHaveTextContent('written by Bea Second')
    expect(card).not.toHaveTextContent(`${WRITER_ID.slice(0, 8)}…`)
    expect(card).toHaveTextContent(`digest ${'a'.repeat(12)}…`)
    expect(card).toHaveTextContent('tests/test_divide_held_out.py')
    expect(card).toHaveTextContent('Its first attempt passed the held-out tests. The forward reading rdg_forward counts it.')
  })

  it('a result no forward reading counts says so, and a fail is a miss only where one counts it', async () => {
    const graded = ACCEPTANCE.assignments[1]!
    setup({
      ...ACCEPTANCE,
      assignments: [
        { ...graded, item_id: 'I-8', counted_by: '', result: 'fail' },
        { ...graded, item_id: 'I-9', result: 'fail' },
      ],
    })
    expect(await screen.findByTestId('acceptance-I-8')).toHaveTextContent(
      'Its first attempt did not pass the held-out tests. No forward reading counts it: none was registered on this kind and size before these tests were written.',
    )
    expect(screen.getByTestId('acceptance-I-9')).toHaveTextContent('The forward reading rdg_forward counts it as a miss.')
  })

  it('a build that ran without the tests ends its assignment and says why', async () => {
    setup()
    const card = await screen.findByTestId('acceptance-I-3')
    expect(within(card).getByTestId('acceptance-status-I-3')).toHaveTextContent('built, not graded')
    expect(within(card).getByTestId('acceptance-why-I-3')).toHaveTextContent('the build started before any held-out tests were written')
    expect(within(card).queryByRole('form')).not.toBeInTheDocument()
  })

  it('an open ticket with no forward reading on its cell is told no reading will count it', async () => {
    setup({ ...ACCEPTANCE, assignments: [{ ...ACCEPTANCE.assignments[0]!, forward_reading: '' }] })
    expect(await screen.findByTestId('acceptance-I-1')).toHaveTextContent('your tests will grade the build, but no reading will count the result')
  })

  it('a ticket attempted before reads “cannot be graded”, not “tests needed”', async () => {
    setup({
      ...ACCEPTANCE,
      assignments: [{ ...ACCEPTANCE.assignments[0]!, status: 'cannot_grade', can_write: false, why_not: 'the ticket was attempted before: its next attempt is never graded on held-out tests' }],
    })
    expect(await screen.findByTestId('acceptance-status-I-1')).toHaveTextContent('cannot be graded')
  })
})
