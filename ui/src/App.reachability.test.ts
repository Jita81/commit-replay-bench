/**
 * Every screen has a door — no route is reachable only by typing its URL.
 *
 * Navigation
 * ----------
 * What it is:   A source-level ratchet over `ui/src/App.tsx`: each route it mounts must be
 *               linked to from somewhere in the app, or be named here as a deliberate
 *               exception with the reason.
 * What it does: Catches the class of defect where a screen ships complete, tested and
 *               documented, and nothing in the product links to it — which happened to
 *               `/factory/intake`, the front door of the factory: it was absent from the
 *               journey nav, the instrument row and every screen, so the only ways in were
 *               a bookmark or the raw path the guides had to print. Every other test
 *               navigated by `page.goto` or `renderApp`, so none of them could notice.
 * How:          Reads the sources as text through Vite's `import.meta.glob(..., '?raw')` — not
 *               the DOM, and no node types — collects `<Route path=...>` and every `to=` /
 *               `href=` target in `ui/src`, and matches a route against the static prefix of a
 *               link (so a `/runs/` link is the door of `/runs/:id`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
 * Works with:   ui/src/App.tsx (the routes), ui/src/components/Layout.tsx (the journey nav
 *               and instrument row), ui/src/help/hints-ratchet.instrument.tsx (the per-route
 *               hint ratchet, which does NOT check reachability)
 * Tested by:    itself
 * Touch when:   a route is added — link to it from a screen or the nav, or add it below with
 *               the reason it has no door.
 */
import { describe, expect, it } from 'vitest'

/** Every source file of the app as text — Vite's own raw import, so this needs no node types. */
const SOURCES = import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Routes with no in-app link, each with the reason that is correct rather than an oversight. */
const NO_DOOR: Record<string, string> = {
  '/login': 'reached by being signed out (every route redirects here), never by a link',
  '*': 'the not-found catch-all: it is what an unknown path renders, not a destination',
  '/repos': 'the flat repositories list the Connection journey replaced; kept routable for a bookmark and for the links the docs already print, and every repository page is reached from Connection',
}

describe('every route has a door', () => {
  const app = SOURCES['./App.tsx']!
  const routes = [...app.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]!)
  // every link target in the app, App.tsx aside (its own paths are the routes, not the doors)
  // `to="/x"`, `to={`/x?...`}`, `navigate(`/x/${id}`)` and the nav tables' `to: '/x'`: only the
  // STATIC head of the target is read, which is all a door needs to be recognised by
  const links = Object.entries(SOURCES)
    .filter(([path]) => path !== './App.tsx' && !/\.test\.tsx?$/.test(path))
    .flatMap(([, text]) => [
      ...text.matchAll(/\b(?:to|href)\s*[=:]\s*[{('"`]*(\/[A-Za-z0-9/_.:-]*)/g),
      // a helper that BUILDS an href (`docHref`) is a door too
      ...text.matchAll(/return[^\n]*?[`'"](\/[A-Za-z0-9/_.:-]*)/g),
    ])
    .map((m) => m[1]!.trim())

  it('finds the routes and the links', () => {
    expect(routes.length).toBeGreaterThan(20)
    expect(links.length).toBeGreaterThan(20)
  })

  for (const route of routes) {
    const why = NO_DOOR[route]
    it(`${route} ${why ? 'is deliberately unlinked' : 'is linked to from the app'}`, () => {
      if (why) {
        expect(why.length).toBeGreaterThan(20)
        return
      }
      // the door of `/runs/:id` is a link starting `/runs/` — the id comes from the data
      const prefix = route.split('/:')[0]!
      const exact = route.includes('/:') ? `${prefix}/` : prefix
      const hit = links.some((l) => l === exact || l === prefix || l.startsWith(`${exact}?`) || l.startsWith(`${exact}#`) || (route.includes('/:') && l.startsWith(exact)))
      expect(hit, `nothing in ui/src links to ${route} — add a link or name it in NO_DOOR with the reason`).toBe(true)
    })
  }
})
