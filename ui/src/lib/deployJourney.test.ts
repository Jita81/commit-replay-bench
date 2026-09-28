/**
 * deployEyebrow — the go-live journey's place, named on the two screens that carry it.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests of ui/src/lib/deployJourney.ts.
 * What it does: Pins the eyebrow of Settings and Deployment (stream, journey, step n of 4) and
 *               that a route outside the journey gets none.
 * How:          Plain calls.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/deployJourney.ts (under test), ui/src/components/PageHeader.tsx
 *               (renders the eyebrow), docs/dod/journeys/deploy-and-go-live.md (the steps)
 * Tested by:    this file
 * Touch when:   never for a new repository; the journey's steps change.
 */
import { describe, expect, it } from 'vitest'
import { DEPLOY_STEPS, deployEyebrow } from './deployJourney'

describe('deployEyebrow', () => {
  it('names the platform stream, the go-live journey and the step on Settings and Deployment', () => {
    expect(deployEyebrow('/settings')).toBe('Run the platform · Deploy and go live · 2 of 4 · Settings')
    expect(deployEyebrow('/posture')).toBe('Run the platform · Deploy and go live · 3 of 4 · Deployment')
    expect(DEPLOY_STEPS.map((s) => s.to)).toEqual(['/login', '/settings', '/posture', '/home'])
  })

  it('gives a route outside the journey no eyebrow', () => {
    expect(deployEyebrow('/results')).toBe('')
  })
})
