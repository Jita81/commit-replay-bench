/**
 * ui/src/screens/Ledger/LedgerPage.tsx — a filter that arrives in a link is shown, and can be
 * removed, so Matching rows never shrinks with nothing on screen saying why.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the ledger page's linked filters (`run_id`, `task_id`,
 *               `builder`, `language`) against a mocked `GET /grades`.
 * What it does: Pins that arriving at `/ledger?run_id=…` (a run page's door) shows one chip per
 *               filter the page has no control for, that the request carries the filter, and
 *               that pressing a chip removes the filter from the URL and the request; with no
 *               linked filter there is no chip row; and that a link value a select does not
 *               offer (`?size=xl`) is not sent, the select reads "all" and a chip says it is
 *               not applied, while an offered value is applied with no chip (G-180).
 * How:          `mockApi` + `renderApp` at `/ledger?…`; the `GET /grades` calls are read back
 *               from the mock to see which filters each request carried.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
 * Works with:   ui/src/screens/Ledger/LedgerPage.tsx (`LINKED_FILTERS`, the code under test),
 *               ui/src/test/utils.tsx (`mockApi`, `renderApp`), ui/src/help/hints.ts
 *               (`button.ledger.remove_filter`)
 * Tested by:    ui/src/screens/Ledger/LedgerFilters.test.tsx
 * Touch when:   never for a new repository; a filter is added to `GET /grades` without a
 *               control on the page (it must get a chip, and a case here).
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { hintText } from '../../help/hints'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { LedgerPage } from './LedgerPage'

const VERIFY = { rows: 3, ok: true, false_q1_total: 0, broken_at: null }
const NONE = { items: [], total: 0, limit: 100, offset: 0 }

function setup(route: string) {
  const api = mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: 'viewer' }, 'GET /repos': NONE, 'GET /ledger/verify': VERIFY, 'GET /grades': NONE })
  renderApp(<LedgerPage />, { route })
  const gradeUrls = () => api.calls.filter((c) => c.path === '/grades').map((c) => new URL(c.url, 'http://x').searchParams)
  return { gradeUrls }
}

describe('LedgerPage — filters that arrive in a link (G-180)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('arriving at ?run_id=… shows the run as a chip, the request carries it, and the chip removes it', async () => {
    const { gradeUrls } = setup('/ledger?run_id=r-0123456789abcdef&builder=claude_code')
    const run = await screen.findByTestId('ledger-filter-chip-run_id')
    expect(run).toHaveTextContent('Run: r-0123456789…')
    expect(run).toHaveAccessibleName('Remove the run filter r-0123456789abcdef')
    expect(screen.getByTestId('ledger-filter-chip-builder')).toHaveTextContent('Builder: claude_code')
    expect(hintText('button.ledger.remove_filter')).toContain('Matching rows counts only the rows it lets through')
    await waitFor(() => expect(gradeUrls().some((q) => q.get('run_id') === 'r-0123456789abcdef')).toBe(true))

    await userEvent.click(run)
    await waitFor(() => expect(screen.queryByTestId('ledger-filter-chip-run_id')).toBeNull())
    // the builder filter stays; the next request no longer carries the run
    expect(screen.getByTestId('ledger-filter-chip-builder')).toBeInTheDocument()
    await waitFor(() => {
      const last = gradeUrls().at(-1)!
      expect(last.get('run_id')).toBeNull()
      expect(last.get('builder')).toBe('claude_code')
    })
  })

  it('every filter with no control of its own gets a chip; none arrives, no chip row', async () => {
    setup('/ledger?task_id=t1&language=go')
    expect(await screen.findByTestId('ledger-filter-chip-task_id')).toHaveTextContent('Task: t1')
    expect(screen.getByTestId('ledger-filter-chip-language')).toHaveTextContent('Language: go')
  })

  it('a link value a select does not offer is not applied, and says so as a chip that removes it (G-180)', async () => {
    const { gradeUrls } = setup('/ledger?size=xl&mode=native&clean=maybe')
    const size = await screen.findByTestId('ledger-filter-chip-size')
    expect(size).toHaveTextContent('Size: xl — not applied')
    expect(size).toHaveAccessibleName('Remove the size value xl, which is not one of the page’s choices and is not applied')
    expect(screen.getByTestId('ledger-filter-chip-mode')).toHaveTextContent('Mode: native — not applied')
    expect(screen.getByTestId('ledger-filter-chip-clean')).toHaveTextContent('Clean: maybe — not applied')
    // each select reads "all", and the rows are not narrowed by a value it cannot show
    for (const name of ['Clean', 'Mode', 'Size']) expect(screen.getByRole('combobox', { name })).toHaveValue('')
    await waitFor(() => expect(gradeUrls().length).toBeGreaterThan(0))
    for (const q of gradeUrls()) {
      expect(q.get('size')).toBeNull()
      expect(q.get('mode')).toBeNull()
      expect(q.get('clean')).toBeNull()
    }
    await userEvent.click(size)
    await waitFor(() => expect(screen.queryByTestId('ledger-filter-chip-size')).toBeNull())
    expect(screen.getByTestId('ledger-filter-chip-mode')).toBeInTheDocument()
  })

  it('an offered select value is applied and gets no chip', async () => {
    const { gradeUrls } = setup('/ledger?size=XL&mode=blind&clean=false')
    await waitFor(() => expect(gradeUrls().some((q) => q.get('size') === 'XL' && q.get('mode') === 'blind' && q.get('clean') === 'false')).toBe(true))
    expect(screen.queryByTestId('ledger-linked-filters')).toBeNull()
  })

  it('with no linked filter there is no chip row', async () => {
    setup('/ledger?clean=true')
    await screen.findByTestId('ledger-filter-legend')
    expect(screen.queryByTestId('ledger-linked-filters')).toBeNull()
  })
})
