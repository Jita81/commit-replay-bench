/**
 * One hover per instrument screen — a real element on the rendered page opens its bubble on
 * mouse-over with the registry's text, and Escape closes it.
 *
 * Navigation
 * ----------
 * What it is:   The per-screen hover test for /factory, /posture, /repos, /repos/:name, /runs,
 *               /runs/:id, /tasks/:repo/:taskId, /capability, /routing, /oracle, /learn,
 *               /ledger and /settings: one named element each, hovered on the screen it
 *               lives on (not the primitive in isolation).
 * What it does: Renders the screen under the ratchet's fixtures, finds the element by its
 *               `data-hint`, fires mouse-over, waits for the bubble (`role="tooltip"`,
 *               `data-open="true"`) whose text is the registry's, then presses Escape and
 *               requires it closed. So a screen whose wiring broke the trigger (a wrapper
 *               that swallowed the event, a bubble id that no longer resolves) fails here,
 *               where the ratchet — which only counts `data-hint` — would pass.
 * How:          `renderApp` / `mockApi` from ui/src/test/utils.tsx with the entries of
 *               `INSTRUMENT_SCREENS`; real timers (`waitFor` outlasts the 150 ms open delay).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints-ratchet.instrument.tsx (the screens and fixtures),
 *               ui/src/components/Hint.tsx (the trigger contract), ui/src/help/hints.ts
 *               (`HINTS`, the text asserted), ui/src/test/utils.tsx (`renderApp`, `mockApi`)
 * Tested by:    ui/src/help/hints-hover.instrument.test.tsx
 * Touch when:   a screen is added to the instrument row — add its route and one element here.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, mockApi, renderApp } from '../test/utils'
import { HINTS, type HintId } from './hints'
import { INSTRUMENT_SCREENS } from './hints-ratchet.instrument'

/** One element per screen: something only that screen renders. */
const HOVER: Record<string, HintId> = {
  '/factory': 'pill.factory.frozen',
  '/posture': 'summary.posture.apparatus',
  '/repos': 'col.repos.probe',
  '/repos/:name': 'stat.repo.gold',
  '/runs': 'col.runs.progress',
  '/runs/:id': 'stat.run.clean',
  '/tasks/:repo/:taskId': 'tile.task.target_tests',
  '/capability': 'stat.capability.coverage',
  '/routing': 'policy.routing.min_ci_low',
  '/oracle': 'stat.oracle.mean',
  '/learn': 'stat.learn.refusal_share',
  '/ledger': 'stat.ledger.false_q1',
  '/settings': 'pill.settings.health',
}

describe('hover on the instrument screens', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('names one element on every instrument screen', () => {
    expect(Object.keys(HOVER).sort()).toEqual(Object.keys(INSTRUMENT_SCREENS).sort())
  })

  for (const [route, id] of Object.entries(HOVER)) {
    it(`${route}: mouse-over on ${id} opens its bubble with the registry text; Escape closes it`, async () => {
      const s = INSTRUMENT_SCREENS[route]!
      mockApi({ 'GET /auth/me': { ...PRINCIPAL, role: s.roles[s.roles.length - 1]! }, ...s.api })
      const { container } = renderApp(s.element, { route: s.route, path: s.path })
      await screen.findByRole('heading', { level: 1 })
      const trigger = await waitFor(() => {
        const el = container.querySelector<HTMLElement>(`[data-hint="${id}"]`)
        expect(el, `${route}: no element carries ${id}`).not.toBeNull()
        return el!
      })
      const bubbleId = trigger.getAttribute('aria-describedby')!.split(' ').pop()!
      const bubble = document.getElementById(bubbleId)!
      expect(bubble).toHaveAttribute('role', 'tooltip')
      expect(bubble).toHaveTextContent(HINTS[id])
      expect(bubble).toHaveAttribute('data-open', 'false')

      fireEvent.mouseOver(trigger)
      await waitFor(() => expect(bubble).toHaveAttribute('data-open', 'true'))
      expect(trigger).toHaveAttribute('data-open', 'true')

      fireEvent.keyDown(document, { key: 'Escape' })
      await waitFor(() => expect(bubble).toHaveAttribute('data-open', 'false'))
    })
  }
})
