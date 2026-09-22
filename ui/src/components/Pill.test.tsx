/**
 * Pill.tsx — the base chip carries its sentence, never a hover title, and a hint when given one.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for `Pill`.
 * What it does: Pins that a labelled pill is `role="img"` with the sentence as its name and
 *               the visible text hidden from the tree; that no native `title` is rendered
 *               (hover-only, unreachable on touch); that `hint` puts `data-hint` on the pill
 *               itself with the registry text as its description while the name stays; and
 *               that every pill carries `data-component="pill"` for the ratchet.
 * How:          Testing Library render; attribute assertions.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Pill.tsx (the code under test), ui/src/help/hints.ts (the
 *               copy asserted), ui/src/components/Hint.tsx (the trigger a hinted pill renders
 *               through)
 * Tested by:    ui/src/components/Pill.test.tsx
 * Touch when:   the pill's markup changes.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HINTS } from '../help/hints'
import { Pill } from './Pill'

describe('Pill', () => {
  it('a labelled pill is an image named by its sentence, with no hover title', () => {
    render(
      <Pill tone="green" glyph="✓" label="Belt 2 — target green: held" data-testid="p">
        B2 target
      </Pill>,
    )
    const pill = screen.getByTestId('p')
    expect(pill).toHaveAttribute('role', 'img')
    expect(pill).toHaveAccessibleName('Belt 2 — target green: held')
    expect(pill).not.toHaveAttribute('title')
    expect(pill).toHaveAttribute('data-component', 'pill')
    expect(pill).not.toHaveAttribute('data-hint')
  })

  it('a hint lands on the pill itself: name kept, description added, a tab stop', () => {
    render(
      <Pill tone="green" glyph="✓" label="Instrument health: OK" hint="pill.shell.health" data-testid="p">
        OK
      </Pill>,
    )
    const pill = screen.getByTestId('p')
    expect(pill).toHaveAttribute('data-hint', 'pill.shell.health')
    expect(pill).toHaveAccessibleName('Instrument health: OK')
    expect(pill).toHaveAccessibleDescription(HINTS['pill.shell.health'])
    expect(pill).toHaveAttribute('tabindex', '0')
    expect(pill).not.toHaveAttribute('title')
  })

  it('tabStop={false} keeps a dense pill out of the tab order', () => {
    render(
      <Pill tone="muted" hint="belt.target_green" tabStop={false} data-testid="p">
        B2
      </Pill>,
    )
    expect(screen.getByTestId('p')).not.toHaveAttribute('tabindex')
  })
})
