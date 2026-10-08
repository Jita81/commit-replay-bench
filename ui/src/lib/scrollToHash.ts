/**
 * A deep link lands where it points: the shell scrolls to `location.hash` once its target
 * exists, and keeps it there while the page above it is still filling in.
 *
 * Navigation
 * ----------
 * What it is:   `useScrollToHash`, mounted once in the shell (`Layout`), so every deep link
 *               (`/settings#golive-attestations`, `/settings#invite`, `/library/:repo#index`)
 *               lands on its target, not at the top of the page (P-399).
 * What it does: On each navigation that carries a hash, waits for the element with that id
 *               (a single-page app renders it after the route, often after its data), scrolls
 *               it to the top of the viewport, and scrolls it back there each time the page
 *               above it grows, until the page has been still for a moment, a few seconds have
 *               passed, or the person scrolls, types or clicks themselves — their own move
 *               always wins.
 * How:          `useLocation` for the hash; a `MutationObserver` on `<body>` for "the target
 *               exists" and "the page moved"; `scrollIntoView` (optional in jsdom).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Layout.tsx (mounts it), ui/src/screens/Posture/GoLiveList.tsx
 *               and ui/src/screens/Home/HomePage.tsx (links to /settings#…),
 *               ui/src/screens/Decisions/decisions.ts (links to /library/:repo#index),
 *               docs/PREVENTION.md (P-399)
 * Tested by:    ui/src/lib/scrollToHash.test.tsx
 * Touch when:   never for a new repository; a page needs a deep link to land somewhere the id
 *               of an element cannot name.
 */
import { useEffect } from 'react'
import { useLocation } from 'react-router'

/** How long the target is held in view while the page settles, at most (ms). */
export const SETTLE_MAX_MS = 4000
/** How long the page must be still before the target is left alone (ms). */
export const SETTLE_QUIET_MS = 600

const USER_MOVES = ['wheel', 'touchstart', 'keydown', 'mousedown'] as const

export function useScrollToHash(): void {
  const { pathname, hash, key } = useLocation()
  useEffect(() => {
    let id = ''
    try {
      id = decodeURIComponent(hash.replace(/^#/, ''))
    } catch {
      id = hash.replace(/^#/, '')
    }
    if (!id || typeof document === 'undefined') return
    let stopped = false
    let quiet: number | undefined
    const land = (): boolean => {
      const el = document.getElementById(id)
      if (!el) return false
      el.scrollIntoView?.({ block: 'start' })
      return true
    }
    const stop = () => {
      if (stopped) return
      stopped = true
      obs.disconnect()
      window.clearTimeout(max)
      window.clearTimeout(quiet)
      for (const ev of USER_MOVES) window.removeEventListener(ev, stop, true)
    }
    const settle = () => {
      window.clearTimeout(quiet)
      quiet = window.setTimeout(stop, SETTLE_QUIET_MS)
    }
    const obs = new MutationObserver(() => {
      if (stopped) return
      if (land()) settle()
    })
    const max = window.setTimeout(stop, SETTLE_MAX_MS)
    for (const ev of USER_MOVES) window.addEventListener(ev, stop, true)
    obs.observe(document.body, { childList: true, subtree: true })
    if (land()) settle()
    return stop
  }, [pathname, hash, key])
}
