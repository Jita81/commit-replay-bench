/**
 * ui/src/components/VerdictPill.tsx — every route has a label, a glyph and a tone; absence is never a colour.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for `VerdictPill`.
 * What it does: Pins, for each of the five routes and NOT_YET_MEASURED, the label, glyph, tone
 *               class and accessible sentence; that NOT_YET_MEASURED is a dashed muted outline
 *               with no status colour; that `null` renders as NOT_YET_MEASURED (no fabricated
 *               verdict); and that the routing reason is appended to the accessible label.
 * How:          `it.each` over the route table; assertions on `data-testid="verdict-<route>"`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/components/VerdictPill.tsx (the code under test), ui/src/lib/verdict.ts
 *               (`routeDisplay` — the table these cases mirror)
 * Tested by:    ui/src/components/VerdictPill.test.tsx
 * Touch when:   a route is added — add its row to the `it.each` table.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { VerdictPill } from './VerdictPill'
import { routeDisplay } from '../lib/verdict'

describe('VerdictPill', () => {
  it.each([
    ['deliver', 'Deliver', '✓', 'text-status-green'],
    ['calibrate', 'Calibrate', '◐', 'text-primary'],
    ['granularize', 'Granularize', '⋮', 'text-status-blue'],
    ['human', 'Human', '☺', 'text-status-amber'],
    ['do_not_ship', 'Do not ship', '✗', 'text-status-red'],
    ['NOT_YET_MEASURED', 'Not yet measured', '·', 'text-on-surface-muted'],
  ])('%s → label %s, glyph %s, tone class %s', (route, label, glyph, cls) => {
    render(<VerdictPill route={route} />)
    const el = screen.getByTestId(`verdict-${route}`)
    expect(el.textContent).toContain(label)
    expect(el.textContent).toContain(glyph)
    expect(el.className).toContain(cls)
    expect(el).toHaveAttribute('aria-label', routeDisplay(route).describe)
  })

  it('NOT_YET_MEASURED is a dashed muted outline, never a status colour', () => {
    render(<VerdictPill route="NOT_YET_MEASURED" />)
    const el = screen.getByTestId('verdict-NOT_YET_MEASURED')
    expect(el.className).toContain('border-dashed')
    expect(el.className).not.toMatch(/status-(red|amber|green)/)
  })

  it('null/undefined renders as NOT_YET_MEASURED (never fabricates a verdict)', () => {
    render(<VerdictPill route={null} />)
    expect(screen.getByTestId('verdict-NOT_YET_MEASURED')).toBeInTheDocument()
  })

  it('appends the reason to the accessible label', () => {
    render(<VerdictPill route="calibrate" reason="n=3 < 10" />)
    expect(screen.getByTestId('verdict-calibrate')).toHaveAttribute('aria-label', expect.stringContaining('n=3 < 10'))
  })
})
