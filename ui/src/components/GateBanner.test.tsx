/**
 * GateBanner — the state is derived from the rows, and an advisory row never holds the gate.
 *
 * Navigation
 * ----------
 * What it is:   The unit tests for `GateBanner`'s derived state.
 * What it does: Pins that the gate is OPEN only when every binding row holds, CLOSED while one
 *               fails and PENDING while one is unevaluated; that an `advisory` row (the sign-off
 *               gate's posture row, G-480) is said — an amber "!" and "advisory, not
 *               satisfied" for a screen reader — but never closes, holds or opens the gate; and
 *               that a gate of advisory rows alone is not OPEN.
 * How:          `render` with plain criteria; `data-state` and the row text are read back.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/GateBanner.tsx (the code under test),
 *               ui/src/screens/Signoff/SignoffPage.tsx (the posture row),
 *               ui/src/screens/Signoff/SignoffPage.test.tsx (the gate as the page draws it)
 * Tested by:    (this is a test file)
 * Touch when:   never for a new repository; the gate gains a row kind or a state.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { GateBanner, type GateCriterion } from './GateBanner'

const held: GateCriterion = { label: 'Cell is measured', ok: true }
const posture = (ok: boolean | null): GateCriterion => ({ label: 'Graded in the sealed posture', ok, advisory: true, detail: 'local/inplace/host-env' })

describe('GateBanner', () => {
  it('an advisory row that does not hold is said in amber, and never closes the gate', () => {
    render(<GateBanner title="Attest a cell" criteria={[held, posture(false)]} data-testid="gate" />)
    const gate = screen.getByTestId('gate')
    expect(gate).toHaveAttribute('data-state', 'OPEN')
    const row = within(gate).getAllByRole('listitem').find((li) => li.textContent?.includes('Graded in the sealed posture'))!
    expect(row.textContent).toMatch(/!\s*advisory, not satisfied:/)
    expect(row.textContent).not.toContain('✗')
  })

  it('an unevaluated advisory row does not hold the gate pending, and a binding row still does', () => {
    const { rerender } = render(<GateBanner title="g" criteria={[held, posture(null)]} data-testid="gate" />)
    expect(screen.getByTestId('gate')).toHaveAttribute('data-state', 'OPEN')
    rerender(<GateBanner title="g" criteria={[{ ...held, ok: null }, posture(true)]} data-testid="gate" />)
    expect(screen.getByTestId('gate')).toHaveAttribute('data-state', 'PENDING')
    rerender(<GateBanner title="g" criteria={[{ ...held, ok: false }, posture(true)]} data-testid="gate" />)
    expect(screen.getByTestId('gate')).toHaveAttribute('data-state', 'CLOSED')
  })

  it('a gate of advisory rows alone is not open: something binding must hold', () => {
    render(<GateBanner title="g" criteria={[posture(true)]} data-testid="gate" />)
    expect(screen.getByTestId('gate')).not.toHaveAttribute('data-state', 'OPEN')
  })
})
