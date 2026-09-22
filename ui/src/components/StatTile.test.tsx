/**
 * ui/src/components/StatTile.tsx — a headline number never appears without its n, interval and
 * apparatus.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for `StatTile`.
 * What it does: Pins that a measured tile shows the value, `n =` with thousands separators,
 *               the interval text and the apparatus line; that an unmeasured tile (`—`, n = 0)
 *               is muted with no fabricated zero and no `NaN` / `Infinity` / `undefined`; that
 *               a non-finite `n` still renders without `NaN`; that `footer` renders the
 *               visible line and `hint` makes the tile root the trigger (`data-hint` on the
 *               element that carries the test id, `data-component="stat-tile"` either way).
 * How:          Testing Library render; assertions on the tile's text content and the muted
 *               class.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/StatTile.tsx (the code under test), ui/src/lib/format.ts
 *               (the guards whose output is asserted), ui/src/help/hints.ts (the hint text)
 * Tested by:    ui/src/components/StatTile.test.tsx
 * Touch when:   the tile gains a line (e.g. a belt set) — assert it here so no variant can
 *               drop it.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HINTS } from '../help/hints'
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

  it('the apparatus line is read in full, never cut to one line behind a hover title', () => {
    const long = 'a mean of builder-reported $ over cells with a known cost, current apparatus — no interval yet: the API serves the mean only'
    render(<StatTile label="Cost per attempt" value="$0.12" n={40} apparatus={long} data-testid="tile" />)
    const dd = screen.getByText(long)
    expect(dd).not.toHaveAttribute('title')
    expect(dd.className).not.toMatch(/truncate/)
  })

  it('the label may be a node, so a route name can be a term with its definition', () => {
    render(<StatTile label={<button type="button">deliver</button>} value="1" n={22} apparatus="1 of 2 measured cells" data-testid="tile" />)
    expect(screen.getByRole('button', { name: 'deliver' })).toBeInTheDocument()
  })

  it('never renders NaN when given a non-finite n', () => {
    render(<StatTile label="X" value="1" n={Number.NaN} apparatus="a" data-testid="tile" />)
    expect(screen.getByTestId('tile').textContent).not.toContain('NaN')
  })

  it('footer is the visible line under the evidence; hint makes the tile itself the trigger', () => {
    render(<StatTile label="False-Q1" value="0" n={12} apparatus="a" hint="stat.results.false_q1" footer="must be zero; refused at write" data-testid="tile" />)
    const tile = screen.getByTestId('tile')
    expect(tile).toHaveAttribute('data-hint', 'stat.results.false_q1')
    expect(tile).toHaveAttribute('data-component', 'stat-tile')
    expect(tile).toHaveAttribute('tabindex', '0')
    expect(tile).toHaveAccessibleDescription(HINTS['stat.results.false_q1'])
    expect(tile.textContent).toContain('must be zero; refused at write')
  })

  it('without a hint the tile is a plain div the ratchet can still find', () => {
    render(<StatTile label="X" value="1" n={1} apparatus="a" data-testid="tile" />)
    const tile = screen.getByTestId('tile')
    expect(tile).not.toHaveAttribute('data-hint')
    expect(tile).toHaveAttribute('data-component', 'stat-tile')
  })
})
