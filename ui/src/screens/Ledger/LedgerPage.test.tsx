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
 *               abstract cells, sees neither; and that clean, sighted and blind are terms
 *               that open inline next to the filters.
 * How:          `mockApi` + `renderApp` at `/ledger` per role.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0007-abstract-cell-export-only.md
 * Works with:   ui/src/screens/Ledger/LedgerPage.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Ledger/LedgerPage.test.tsx
 * Touch when:   an export or a filter is added.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { LedgerPage } from './LedgerPage'

const VERIFY = { rows: 0, ok: true, false_q1_total: 0, broken_at: null }
const NONE = { items: [], total: 0, limit: 100, offset: 0 }

function setup(me: Principal) {
  mockApi({ 'GET /auth/me': me, 'GET /repos': NONE, 'GET /ledger/verify': VERIFY, 'GET /grades': NONE })
  return renderApp(<LedgerPage />, { route: '/ledger' })
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
})
