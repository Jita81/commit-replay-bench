import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BeltPills } from './BeltPills'

describe('BeltPills', () => {
  it('renders four belts with ✓ / ✗ / — glyphs and full names for assistive tech', () => {
    render(<BeltPills belts={{ tests_unmodified: true, target_green: false, no_new_failures: null, source_changed: true }} />)
    const list = screen.getByRole('list', { name: 'Four belts' })
    expect(list.querySelectorAll('li')).toHaveLength(4)

    const b1 = screen.getByTestId('belt-tests_unmodified')
    expect(b1).toHaveAttribute('aria-label', 'Belt 1 — tests unmodified: held')
    expect(b1.textContent).toContain('✓')

    const b2 = screen.getByTestId('belt-target_green')
    expect(b2).toHaveAttribute('aria-label', 'Belt 2 — target green: failed')
    expect(b2.textContent).toContain('✗')

    const b3 = screen.getByTestId('belt-no_new_failures')
    expect(b3).toHaveAttribute('aria-label', 'Belt 3 — no new failures: not recorded')
    expect(b3.textContent).toContain('—')

    expect(screen.getByTestId('belt-source_changed')).toHaveAttribute('aria-label', 'Belt 4 — source changed: held')
  })

  it('shows belt names by default and status words when showNames is false', () => {
    const { rerender } = render(<BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true }} />)
    expect(screen.getByTestId('belt-target_green').textContent).toContain('B2 target')
    rerender(<BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: false }} showNames={false} />)
    expect(screen.getByTestId('belt-target_green').textContent).toContain('pass')
    expect(screen.getByTestId('belt-source_changed').textContent).toContain('fail')
  })
})
