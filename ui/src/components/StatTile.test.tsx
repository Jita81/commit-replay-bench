/**
 * ui/src/components/StatTile.tsx — a headline number never appears without its n, interval and
 * apparatus.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for `StatTile`.
 * What it does: Pins that a measured tile shows the value, `n =` with thousands separators,
 *               the interval text and the apparatus line; that an unmeasured tile (`—`, n = 0)
 *               is muted with no fabricated zero and no `NaN` / `Infinity` / `undefined`; and
 *               that a non-finite `n` still renders without `NaN`.
 * How:          Testing Library render; assertions on the tile's text content and the muted
 *               class.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/StatTile.tsx (the code under test), ui/src/lib/format.ts
 *               (the guards whose output is asserted)
 * Tested by:    ui/src/components/StatTile.test.tsx
 * Touch when:   the tile gains a line (e.g. a belt set) — assert it here so no variant can
 *               drop it.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatTile } from './StatTile'

describe('StatTile', () => {
  it('always shows value, n, CI and apparatus — never a bare number', () => {
    render(<StatTile label="Pass rate" value="84.4%" n={1071} ci={{ low: 0.821, high: 0.865 }} apparatus="apparatus 2.0 · Wilson 95%" data-testid="tile" />)
    const tile = screen.getByTestId('tile')
    expect(tile.textContent).toContain('Pass rate')
    expect(tile.textContent).toContain('84.4%')
    expect(tile.textContent).toContain('n =')
    expect(tile.textContent).toContain('1,071')
    expect(tile.textContent).toContain('[82.1%, 86.5%]')
    expect(tile.textContent).toContain('apparatus 2.0 · Wilson 95%')
  })

  it('renders an honest unmeasured tile when n is 0 (muted, dash, no fabricated zero)', () => {
    render(<StatTile label="Coverage" value="—" n={0} ci={null} apparatus="not yet measured" data-testid="tile" />)
    const tile = screen.getByTestId('tile')
    expect(tile.textContent).toContain('—')
    expect(tile.textContent).toContain('n =0')
    expect(tile.textContent).not.toMatch(/NaN|Infinity|undefined/)
    expect(tile.querySelector('.text-on-surface-muted.num')).not.toBeNull()
  })

  it('never renders NaN when given a non-finite n', () => {
    render(<StatTile label="X" value="1" n={Number.NaN} apparatus="a" data-testid="tile" />)
    expect(screen.getByTestId('tile').textContent).not.toContain('NaN')
  })
})
