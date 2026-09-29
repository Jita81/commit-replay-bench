/**
 * ui/src/screens/Ledger/LedgerPage.tsx — the abstract export is explained in visible text and
 * the filter words are defined where they are chosen.
 *
 * Navigation
 * ----------
 * What it is:   Screen test for the ledger page against mocked `GET /ledger/verify` and
 *               `GET /grades`.
 * What it does: Pins that an operator sees the abstract export's sentence as text beside the
 *               button, never a hover title (J-HEL-18); that a viewer, who cannot export the
 *               abstract cells, sees neither; that clean, sighted and blind are terms
 *               that open inline next to the filters; that the gate's failure states
 *               each close it on their own row — the grade chain (its row), the audit trail
 *               (its event, ADR-0029), false-Q1 (and the red tile) and a missing pack; that
 *               a refused abstract export (409 `false_q1_refused`) is reported beside the
 *               button, never opened as a raw response (G-182); that a filtered empty ledger
 *               offers Clear filters, which resets the URL, and an empty ledger says why with
 *               no action (G-181); and that the Disqualified tile reads the served window,
 *               threshold and count, turns red when a builder is over, and says when the
 *               figure is not served (G-400).
 * How:          `mockApi` + `renderApp` at `/ledger` per role; the export's object URL and
 *               anchor click stubbed as ExportButton.test does.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0007-abstract-cell-export-only.md,
 *               docs/adr/0029-the-audit-trail-is-hash-chained.md
 * Works with:   ui/src/screens/Ledger/LedgerPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Ledger/LedgerPage.test.tsx
 * Touch when:   never for a new repository; an export or a filter is added, or `GET /ledger/verify`
 *               gains a part or a figure.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LedgerDisqualified, Principal } from '../../api/types'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../../test/utils'
import { LedgerPage } from './LedgerPage'

const EVENTS_OK = { rows: 5, chain_ok: true, broken_at: null, detail: '5 events, chain intact', head_row_hash: 'e'.repeat(64) }
const VERIFY = { rows: 0, ok: true, false_q1_total: 0, chain_ok: true, broken_at: null, detail: '0 rows, chain intact, false_q1=0', clean_without_pack: 0, verified_at: '2026-09-27T00:00:00Z', head_row_hash: '', events: EVENTS_OK }
const NONE = { items: [], total: 0, limit: 100, offset: 0 }

function setup(me: Principal, verify: object = VERIFY, route = '/ledger', extra: Record<string, unknown> = {}) {
  const api = mockApi({ 'GET /auth/me': me, 'GET /repos': NONE, 'GET /ledger/verify': verify, 'GET /grades': NONE, ...extra })
  const view = renderApp(<LedgerPage />, { route })
  const gradeUrls = () => api.calls.filter((c) => c.path === '/grades').map((c) => new URL(c.url, 'http://x').searchParams)
  return { ...view, api, gradeUrls }
}

/** The gate's row for `label`: its glyph state (✓ / ✗) and its detail line. */
async function gateRow(label: string) {
  const gate = await screen.findByTestId('ledger-gate')
  const row = within(gate).getByText(label).closest('li')!
  return { gate, row, ok: row.textContent!.includes('✓'), text: row.textContent! }
}

describe('LedgerPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('an operator reads what the abstract export shares as visible text; the button has no hover title (J-HEL-18)', async () => {
    setup({ ...PRINCIPAL, role: 'operator' })
    const button = await screen.findByRole('link', { name: 'Export abstract' })
    expect(button.getAttribute('title')).toBeNull()
    const note = screen.getByTestId('abstract-export-note')
    expect(note.textContent).toContain('Cells only: no code, no identifiers; what a federated deployment may share.')
    // the note stays the first description; the hint bubble is appended to it (both resolve)
    const described = button.getAttribute('aria-describedby')!.split(' ')
    expect(described[0]).toBe(note.id)
    expect(described).toHaveLength(2)
    expect(document.getElementById(described[1]!)).toHaveAttribute('role', 'tooltip')
  })

  it('a viewer has no abstract export and no note; the filter words are terms that open inline', async () => {
    setup({ ...PRINCIPAL, role: 'viewer' })
    await waitFor(() => expect(screen.getByTestId('ledger-gate')).toBeInTheDocument())
    expect(screen.queryByRole('link', { name: 'Export abstract' })).toBeNull()
    expect(screen.queryByTestId('abstract-export-note')).toBeNull()
    const legend = screen.getByTestId('ledger-filter-legend')
    for (const name of [/^clean/, /^sighted/, /^blind/]) {
      const term = screen.getByRole('button', { name })
      expect(legend.contains(term)).toBe(true)
    }
    const clean = screen.getByRole('button', { name: /^clean/ })
    await userEvent.click(clean)
    expect(clean).toHaveAttribute('aria-expanded', 'true')
  })

  // The failure states (G-183, P-251): each part of the verification is its own row, so a
  // break is reported as the part that broke — never an audit-trail break read as the grades'.

  it('an edited audit event closes the gate on the audit trail, naming the event, while the grade chain still verifies', async () => {
    setup({ ...PRINCIPAL, role: 'viewer' }, {
      ...VERIFY, rows: 12, ok: false, detail: '12 rows, chain intact, false_q1=0; events chain broken — event 3: row_hash mismatch (row edited)',
      events: { rows: 5, chain_ok: false, broken_at: 3, detail: 'event 3: row_hash mismatch (row edited)', head_row_hash: 'e'.repeat(64) },
    })
    const trail = await gateRow('Audit trail verifies')
    expect(trail.gate).toHaveAttribute('data-state', 'CLOSED')
    expect(trail.ok).toBe(false)
    expect(trail.text).toContain('broken at event 3 of 5: event 3: row_hash mismatch (row edited)')
    expect(trail.row.querySelector('[data-hint="gate.ledger.audit_trail"]')).not.toBeNull()
    const grades = await gateRow('Hash chain verifies')
    expect(grades.ok).toBe(true)
    expect(grades.text).toContain('12 rows, every prev_hash and row_hash match')
  })

  it('a broken grade chain names its row, and the audit trail row still verifies', async () => {
    setup({ ...PRINCIPAL, role: 'viewer' }, { ...VERIFY, rows: 12, ok: false, chain_ok: false, broken_at: 7 })
    const grades = await gateRow('Hash chain verifies')
    expect(grades.gate).toHaveAttribute('data-state', 'CLOSED')
    expect(grades.ok).toBe(false)
    expect(grades.text).toContain('broken at row 7 of 12')
    expect((await gateRow('Audit trail verifies')).ok).toBe(true)
  })

  it('a false-Q1 row closes the gate and turns its tile red; a clean row without a pack closes it on its own row', async () => {
    setup({ ...PRINCIPAL, role: 'viewer' }, { ...VERIFY, rows: 12, ok: false, false_q1_total: 1, clean_without_pack: 2 })
    const fq1 = await gateRow('false-Q1 total = 0')
    expect(fq1.gate).toHaveAttribute('data-state', 'CLOSED')
    expect(fq1.ok).toBe(false)
    expect(fq1.text).toContain('false_q1_total = 1')
    const packs = await gateRow('Every clean row has its evidence pack')
    expect(packs.ok).toBe(false)
    expect(packs.text).toContain('clean rows without a pack = 2')
    expect((await gateRow('Hash chain verifies')).ok).toBe(true)
    expect(screen.getByTestId('tile-false-q1-total').querySelector('.text-status-red')).not.toBeNull()
  })

  // The exports are fetched by the page (G-182): a refusal is a message beside the button.

  it('a refused abstract export (409 false_q1_refused) is reported beside the button, not opened as a raw response', async () => {
    const createObjectURL = vi.fn(() => 'blob:x')
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    try {
      setup({ ...PRINCIPAL, role: 'operator' }, VERIFY, '/ledger', {
        'GET /ledger/export/abstract': () => envelope(409, 'false_q1_refused', 'The ledger holds 1 false-Q1 row; the abstract export is refused until it is investigated.', { false_q1_total: 1 }),
      })
      const button = await screen.findByRole('link', { name: 'Export abstract' })
      // the link still points at the real export, so the no-script fallback stays
      expect(button).toHaveAttribute('href', '/api/v1/ledger/export/abstract')
      await userEvent.click(button)
      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('Refused: false-Q1 invariant')
      expect(alert).toHaveTextContent('The ledger holds 1 false-Q1 row; the abstract export is refused until it is investigated.')
      expect(alert).toHaveTextContent('HTTP 409 · false_q1_refused')
      expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument()
      // nothing was opened or downloaded
      expect(createObjectURL).not.toHaveBeenCalled()
      expect(click).not.toHaveBeenCalled()
      // the note still describes the button, first
      expect(button.getAttribute('aria-describedby')!.split(' ')[0]).toBe('abstract-export-note')
    } finally {
      delete (URL as unknown as Record<string, unknown>).createObjectURL
      delete (URL as unknown as Record<string, unknown>).revokeObjectURL
    }
  })

  // The empty state is two states (G-181): filtered, with a way out; empty, with the reason.

  it('a filtered empty ledger offers Clear filters, which resets the URL', async () => {
    const { gradeUrls } = setup({ ...PRINCIPAL, role: 'viewer' }, VERIFY, '/ledger?repo=alpha&clean=true&builder=fixture')
    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('No rows match these filters')
    expect(empty).not.toHaveTextContent('The ledger is empty')
    await waitFor(() => expect(gradeUrls().at(-1)!.get('clean')).toBe('true'))
    const clear = within(empty).getByRole('button', { name: 'Clear filters' })
    expect(clear).toHaveAttribute('data-hint', 'button.ledger.clear_filters')
    await userEvent.click(clear)
    // the URL is empty again: the next request carries no filter and no repository ...
    await waitFor(() => {
      const last = gradeUrls().at(-1)!
      expect(last.get('clean')).toBeNull()
      expect(last.get('builder')).toBeNull()
      expect(last.get('repo')).toBeNull()
    })
    // ... the chip row is gone and the empty state now says why the ledger is empty
    expect(screen.queryByTestId('ledger-linked-filters')).toBeNull()
    await waitFor(() => expect(screen.getByTestId('empty-state')).toHaveTextContent('The ledger is empty'))
    expect(screen.queryByRole('button', { name: 'Clear filters' })).toBeNull()
  })

  it('an empty ledger says every graded trial appends one row and offers no Clear filters', async () => {
    setup({ ...PRINCIPAL, role: 'viewer' })
    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('The ledger is empty')
    expect(empty).toHaveTextContent('Every graded trial appends one row.')
    expect(empty).not.toHaveTextContent('No rows match')
    expect(screen.queryByRole('button', { name: 'Clear filters' })).toBeNull()
  })

  // The disqualified tile (G-400, the Ledger half): the served figure, red when a builder is over.

  it('the disqualified tile turns red when a builder is over the threshold, with n and the window', async () => {
    const disqualified: LedgerDisqualified = { window_days: 7, threshold: 3, by_builder: [{ builder: 'claude_code', n: 5 }, { builder: 'editblock', n: 1 }], over: ['claude_code'] }
    setup({ ...PRINCIPAL, role: 'viewer' }, { ...VERIFY, disqualified })
    const tile = await screen.findByTestId('tile-disqualified')
    await waitFor(() => expect(tile).toHaveTextContent('Disqualified (7 days)'))
    expect(tile.querySelector('.text-status-red')).toHaveTextContent('6')
    expect(within(tile).getByText('n =').nextElementSibling).toHaveTextContent('6')
    expect(tile).toHaveTextContent('threshold 3 per builder · 7-day window')
    expect(tile).toHaveTextContent('Over the threshold: claude_code')
    expect(tile).toHaveAttribute('data-hint', 'stat.ledger.disqualified')
  })

  it('the disqualified tile is not red under the threshold, and says so when the server does not serve the figure', async () => {
    const under: LedgerDisqualified = { window_days: 7, threshold: 3, by_builder: [{ builder: 'editblock', n: 1 }], over: [] }
    const view = setup({ ...PRINCIPAL, role: 'viewer' }, { ...VERIFY, disqualified: under })
    let tile = await screen.findByTestId('tile-disqualified')
    await waitFor(() => expect(tile).toHaveTextContent('threshold 3 per builder'))
    expect(tile.querySelector('.text-status-red')).toBeNull()
    expect(tile).toHaveTextContent('editblock 1')
    view.unmount()
    vi.unstubAllGlobals()

    setup({ ...PRINCIPAL, role: 'viewer' })
    tile = await screen.findByTestId('tile-disqualified')
    await waitFor(() => expect(tile).toHaveTextContent('not served'))
    expect(tile).toHaveTextContent('—')
    expect(tile).toHaveTextContent('This server does not report the disqualified count.')
  })
})
