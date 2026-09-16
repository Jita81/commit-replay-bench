/**
 * Theme: `light` | `dark` | `system`. Stored in localStorage as `crb.theme`;
 * applied as `data-theme` on <html> (removed for `system`, so
 * `prefers-color-scheme` decides — see index.css). The anti-FOUC script in
 * index.html reads the same key before first paint.
 *
 * Navigation
 * ----------
 * What it is:   The theme store (`useTheme`, `applyTheme`, `THEME_KEY`).
 * What it does: Reads and writes `crb.theme` in localStorage, sets or removes `data-theme` on
 *               `<html>` (removed for `system`, so `prefers-color-scheme` decides), and lets
 *               the header's toggle cycle light → dark → system. Private mode (no storage)
 *               degrades to in-memory only, never to an error.
 * How:          A module-level listener set; `useSyncExternalStore` subscribes to it; `write`
 *               persists, applies and notifies.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Layout.tsx (the toggle), ui/public/theme-init.js (reads the
 *               same key before first paint so there is no flash of the wrong theme),
 *               ui/src/index.css (the `[data-theme]` and `prefers-color-scheme` token blocks)
 * Tested by:    ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe runs under the default
 *               theme); the store itself is untested — three lines of localStorage glue
 * Touch when:   the storage key or attribute changes — change ui/public/theme-init.js and
 *               ui/src/index.css in the same commit; never for a new repository.
 */

import { useCallback, useSyncExternalStore } from 'react'

/** `system` = no `data-theme` attribute; the CSS media query decides. */
export type Theme = 'light' | 'dark' | 'system'
/** The localStorage key; `ui/public/theme-init.js` reads the same one before first paint. */
export const THEME_KEY = 'crb.theme'
const THEMES: readonly Theme[] = ['light', 'dark', 'system']

const listeners = new Set<() => void>()

/** Current preference; anything unreadable (private mode, a stray value) is `system`. */
function read(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

/** Set or clear `data-theme` on `<html>` — the only DOM write in this module. */
export function applyTheme(t: Theme): void {
  const el = document.documentElement
  if (t === 'system') el.removeAttribute('data-theme')
  else el.setAttribute('data-theme', t)
}

/** Persist, apply, notify — in that order, so a subscriber re-reads the stored value. */
function write(t: Theme): void {
  try {
    if (t === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, t)
  } catch {
    /* private mode — in-memory only */
  }
  applyTheme(t)
  for (const l of listeners) l()
}

/** `[theme, set, cycle]`; `cycle` walks light → dark → system, the header's one-button toggle. */
export function useTheme(): [Theme, (t: Theme) => void, () => void] {
  const theme = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    read,
    () => 'system' as Theme,
  )
  const set = useCallback((t: Theme) => write(t), [])
  const cycle = useCallback(() => {
    const i = THEMES.indexOf(read())
    write(THEMES[(i + 1) % THEMES.length] ?? 'system')
  }, [])
  return [theme, set, cycle]
}
