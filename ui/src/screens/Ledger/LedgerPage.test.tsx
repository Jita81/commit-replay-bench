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
 *               that open inline next to the filters; and that the gate's failure states
 *               each close it on their own row — the grade chain (its row), the audit trail
 *               (its event, ADR-0029), false-Q1 (and the red tile) and a missing pack.
 * How:          `mockApi` + `renderApp` at `/ledger` per role.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0007-abstract-cell-export-only.md,
 *               docs/adr/0029-the-audit-trail-is-hash-chained.md
 * Works with:   ui/src/screens/Ledger/LedgerPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Ledger/LedgerPage.test.tsx
 * Touch when:   an export or a filter is added, or `GET /ledger/verify` gains a part.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { LedgerPage } from './LedgerPage'

const EVENTS_OK = { rows: 5, chain_ok: true, broken_at: null, detail: '5 events, chain intact', head_row_hash: 'e'.repeat(64) }
const VERIFY = { rows: 0, ok: true, false_q1_total: 0, chain_ok: true, broken_at: null, detail: '0 rows, chain intact, false_q1=0', clean_without_pack: 0, verified_at: '2026-09-27T00:00:00Z', head_row_hash: '', events: EVENTS_OK }
const NONE = { items: [], total: 0, limit: 100, offset: 0 }

function setup(me: Principal, verify: object = VERIFY) {
  mockApi({ 'GET /auth/me': me, 'GET /repos': NONE, 'GET /ledger/verify': verify, 'GET /grades': NONE })
  return renderApp(<LedgerPage />, { route: '/ledger' })
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

  // The failure states (G-183, P-243): each part of the verification is its own row, so a
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
})
