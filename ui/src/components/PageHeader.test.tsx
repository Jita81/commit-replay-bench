/**
 * PageHeader.tsx — the eyebrow comes from the route unless a screen passes its own.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `PageHeader`'s eyebrow default.
 * What it does: Pins that a screen passing no `eyebrow` on a journey route gets
 *               `journeyEyebrow(pathname)`, that an explicit eyebrow wins, and that a
 *               non-journey route with no eyebrow renders none.
 * How:          `renderApp` at a route with the header as the element.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/PageHeader.tsx, ui/src/components/Layout.tsx (`journeyEyebrow`)
 * Tested by:    ui/src/components/PageHeader.test.tsx
 * Touch when:   the eyebrow grammar changes.
 */
import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../test/utils'
import { PageHeader } from './PageHeader'

describe('PageHeader eyebrow', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('defaults to the journey eyebrow on a journey route', () => {
    mockApi({ 'GET /auth/me': PRINCIPAL })
    renderApp(<PageHeader title="Baseline" />, { route: '/results', path: '/results' })
    expect(screen.getByText('Journey · 2 of 4 · Baseline')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Baseline' })).toBeInTheDocument()
  })

  it('an explicit eyebrow wins; a non-journey route with none renders no eyebrow', () => {
    mockApi({ 'GET /auth/me': PRINCIPAL })
    const first = renderApp(<PageHeader eyebrow="Instrument · Runs" title="Runs" />, { route: '/runs', path: '/runs' })
    expect(screen.getByText('Instrument · Runs')).toBeInTheDocument()
    first.unmount()
    const { container } = renderApp(<PageHeader title="Runs" />, { route: '/runs', path: '/runs' })
    expect(container.querySelector('.label')).toBeNull()
  })
})
