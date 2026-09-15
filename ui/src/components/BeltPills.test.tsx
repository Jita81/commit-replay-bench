/**
 * ui/src/components/BeltPills.tsx — a missing belt is never rendered, and never rendered as failed.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for `BeltPills`.
 * What it does: Pins the glyph and the accessible sentence per belt value (held / failed / not
 *               recorded), that belt set `v5` shows five belts and anything else four, that a
 *               `v5` row with `repo_lint_clean: null` reads "not evaluated — no linter" rather
 *               than failed, that an evidence pack without a belt set infers the count from
 *               the presence of the `repo_lint_clean` key, and the name / status-word display
 *               modes.
 * How:          Testing Library render + `rerender` across belt sets; assertions on
 *               `data-testid="belt-<name>"` and `aria-label`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0011-repo-lint-belt.md
 * Works with:   ui/src/components/BeltPills.tsx (the code under test), ui/src/api/types.ts
 *               (`beltNamesFor` — the rule these cases pin), ui/src/lib/verdict.ts
 *               (`beltDisplay` wording)
 * Tested by:    ui/src/components/BeltPills.test.tsx
 * Touch when:   a belt or belt set is added — add its expected label and count here.
 */
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

  it('shows five belts under belt_set v5 and four otherwise — a missing belt is never rendered', () => {
    const four = { tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true, repo_lint_clean: null }
    const { rerender } = render(<BeltPills belts={four} beltSet="v4" />)
    expect(screen.getByRole('list', { name: 'Four belts' }).querySelectorAll('li')).toHaveLength(4)
    expect(screen.queryByTestId('belt-repo_lint_clean')).toBeNull()

    rerender(<BeltPills belts={four} beltSet="v3-legacy" />)
    expect(screen.getByRole('list', { name: 'Four belts' }).querySelectorAll('li')).toHaveLength(4)

    rerender(<BeltPills belts={{ ...four, repo_lint_clean: false }} beltSet="v5" />)
    const list = screen.getByRole('list', { name: 'Five belts' })
    expect(list.querySelectorAll('li')).toHaveLength(5)
    const b5 = screen.getByTestId('belt-repo_lint_clean')
    expect(b5).toHaveAttribute('aria-label', "Belt 5 — repo's own lint clean: failed")
    expect(b5.textContent).toContain('✗')

    // v5 with no linter configured: not evaluated, shown as such — never as failed
    rerender(<BeltPills belts={four} beltSet="v5" />)
    expect(screen.getByTestId('belt-repo_lint_clean')).toHaveAttribute('aria-label', "Belt 5 — repo's own lint clean: not evaluated — no linter configured for this repository")
    expect(screen.getByTestId('belt-repo_lint_clean').textContent).toContain('—')

    rerender(<BeltPills belts={{ ...four, repo_lint_clean: true }} beltSet="v5" />)
    expect(screen.getByTestId('belt-repo_lint_clean')).toHaveAttribute('aria-label', "Belt 5 — repo's own lint clean: held")
  })

  it('infers the belt count from the result shape when no belt set is given (evidence packs)', () => {
    const { rerender } = render(<BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true }} />)
    expect(screen.getByRole('list', { name: 'Four belts' }).querySelectorAll('li')).toHaveLength(4)
    rerender(<BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true, repo_lint_clean: null }} />)
    expect(screen.getByRole('list', { name: 'Five belts' }).querySelectorAll('li')).toHaveLength(5)
  })

  it('shows belt names by default and status words when showNames is false', () => {
    const { rerender } = render(<BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true }} />)
    expect(screen.getByTestId('belt-target_green').textContent).toContain('B2 target')
    rerender(<BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: false }} showNames={false} />)
    expect(screen.getByTestId('belt-target_green').textContent).toContain('pass')
    expect(screen.getByTestId('belt-source_changed').textContent).toContain('fail')
  })
})
