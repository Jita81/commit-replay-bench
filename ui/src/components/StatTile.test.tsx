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
