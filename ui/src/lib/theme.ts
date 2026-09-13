/**
 * Theme: `light` | `dark` | `system`. Stored in localStorage as `crb.theme`;
 * applied as `data-theme` on <html> (removed for `system`, so
 * `prefers-color-scheme` decides — see index.css). The anti-FOUC script in
 * index.html reads the same key before first paint.
 */

import { useCallback, useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark' | 'system'
export const THEME_KEY = 'crb.theme'
const THEMES: readonly Theme[] = ['light', 'dark', 'system']

const listeners = new Set<() => void>()

function read(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(t: Theme): void {
  const el = document.documentElement
  if (t === 'system') el.removeAttribute('data-theme')
  else el.setAttribute('data-theme', t)
}

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
