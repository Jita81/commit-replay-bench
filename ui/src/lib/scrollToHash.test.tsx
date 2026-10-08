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
 * How:          A MemoryRouter at a hashed path, a component that renders its target late,
 *               `Element.prototype.scrollIntoView` stubbed (jsdom has none), fake timers off.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/scrollToHash.ts (the code under test), ui/src/components/Layout.tsx
 *               (mounts it), docs/PREVENTION.md (P-399)
 * Tested by:    ui/src/lib/scrollToHash.test.tsx
 * Touch when:   never for a new repository; the landing rule changes.
 */
import { act, render, waitFor } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScrollToHash } from './scrollToHash'

function Page({ late, grow }: { late: number; grow?: number }) {
  useScrollToHash()
  const [shown, setShown] = useState(false)
  const [above, setAbove] = useState(0)
  useEffect(() => {
    const t = setTimeout(() => setShown(true), late)
    const g = grow ? setTimeout(() => setAbove(3), late + grow) : undefined
    return () => {
      clearTimeout(t)
      if (g) clearTimeout(g)
    }
  }, [late, grow])
  return (
    <div>
      {Array.from({ length: above }, (_, i) => (
        <p key={i}>a card above that loaded late</p>
      ))}
      {shown && <section id="invite">Invite an approver</section>}
    </div>
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
    render(
      <MemoryRouter initialEntries={['/settings#invite']}>
        <Page late={20} grow={30} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(scrolled.some((e) => e.id === 'invite')).toBe(true))
    const first = scrolled.length
    await waitFor(() => expect(scrolled.length).toBeGreaterThan(first))
  })

  it('a person’s own move stops it', async () => {
    render(
      <MemoryRouter initialEntries={['/settings#invite']}>
        <Page late={10} grow={60} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(scrolled.length).toBe(1))
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }))
    })
    await new Promise((r) => setTimeout(r, 120))
    expect(scrolled.length).toBe(1)
  })

  it('a route with no hash scrolls nothing', async () => {
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Page late={5} />
      </MemoryRouter>,
    )
    await new Promise((r) => setTimeout(r, 40))
    expect(scrolled).toEqual([])
  })
})
