/**
 * scrollToHash.ts — a deep link lands on its target once it exists, and stays there while the
 * page above it fills in (P-399).
 *
 * Navigation
 * ----------
 * What it is:   Hook tests for `useScrollToHash`.
 * What it does: Pins that a hash whose target renders AFTER the route (as a card under a
 *               loading query does) is scrolled to when it appears; that it is scrolled again
 *               when the page above it grows; that a person's own move (a key, a wheel) stops
 *               it; and that a route with no hash scrolls nothing.
 * How:          A MemoryRouter at a hashed path, a page whose target and growth the test
 *               releases step by step, `Element.prototype.scrollIntoView` stubbed (jsdom
 *               has none), no timers.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/scrollToHash.ts (the code under test), ui/src/components/Layout.tsx
 *               (mounts it), docs/PREVENTION.md (P-399)
 * Tested by:    ui/src/lib/scrollToHash.test.tsx
 * Touch when:   never for a new repository; the landing rule changes.
 */
import { act, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScrollToHash } from './scrollToHash'

/**
 * The page is driven by the test, not by timers: `shown` is the target arriving after the
 * route, `above` is cards loading in above it. A timer-driven page lets a loaded machine run
 * both timers before the test's first look, so "the first landing" and "the re-landing" are
 * counted together and the assertion that the count grew can never be met.
 */
function Page({ shown, above }: { shown: boolean; above: number }) {
  useScrollToHash()
  return (
    <div>
      {Array.from({ length: above }, (_, i) => (
        <p key={i}>a card above that loaded late</p>
      ))}
      {shown && <section id="invite">Invite an approver</section>}
    </div>
  )
}

function at(path: string, props: { shown: boolean; above: number }) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <Page {...props} />
    </MemoryRouter>
  )
}

describe('useScrollToHash', () => {
  let scrolled: Element[]
  beforeEach(() => {
    scrolled = []
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
      scrolled.push(this)
    })
  })
  afterEach(() => {
    // @ts-expect-error jsdom has none; the stub is removed again
    delete Element.prototype.scrollIntoView
  })

  it('lands on a target that renders after the route, and again when the page above it grows', async () => {
    const { rerender } = render(at('/settings#invite', { shown: false, above: 0 }))
    expect(scrolled).toEqual([])
    // the target arrives after the route
    rerender(at('/settings#invite', { shown: true, above: 0 }))
    await waitFor(() => expect(scrolled.map((e) => e.id)).toEqual(['invite']))
    // the page above it grows: it is brought back
    rerender(at('/settings#invite', { shown: true, above: 3 }))
    await waitFor(() => expect(scrolled.map((e) => e.id)).toEqual(['invite', 'invite']))
  })

  it('a person’s own move stops it', async () => {
    const { rerender } = render(at('/settings#invite', { shown: false, above: 0 }))
    rerender(at('/settings#invite', { shown: true, above: 0 }))
    await waitFor(() => expect(scrolled.length).toBe(1))
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }))
    })
    // the page grows after the person has moved; the mutation callback has had its turn
    rerender(at('/settings#invite', { shown: true, above: 3 }))
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(scrolled.length).toBe(1)
  })

  it('a route with no hash scrolls nothing', async () => {
    const { rerender } = render(at('/settings', { shown: false, above: 0 }))
    rerender(at('/settings', { shown: true, above: 0 }))
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(document.getElementById('invite')).not.toBeNull()
    expect(scrolled).toEqual([])
  })
})
