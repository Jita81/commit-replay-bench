/**
 * hints.ts — every hint is a short plain sentence, uses a term only where the screen defines
 * it, and the registry's shape holds.
 *
 * Navigation
 * ----------
 * What it is:   The hint registry's copy lint.
 * What it does: Pins that (1) every id follows the dotted scheme and every value is 40–420
 *               characters, ends in a full stop, and carries no markup, link, URL or path and
 *               no exclamation mark; (2) copy lint — the same `LINT` table as help.test.ts: a
 *               hint on route R uses "cell", "apparatus", "belt", "Wilson", "false-Q1" or
 *               "oracle" only when R's About block lists the term (the route is read from the
 *               id's screen segment; the shared vocabulary and the shell render on every
 *               screen and are held to the glossary alone); (3) `SHARED_IDS` is exactly the
 *               shared vocabulary; (4) `MIN_HINTS` names exactly the screen routes of
 *               App.tsx; (5) `hintText` returns the entry.
 * How:          Pure reads of `HINTS`; `App.tsx` as `?raw` for the route table; no React.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints.ts (the registry under test), ui/src/help/help.ts (the
 *               `terms[]` per route the lint checks against), ui/src/help/help.test.ts (the
 *               same `LINT` table), ui/src/App.tsx (the route table `MIN_HINTS` must cover)
 * Tested by:    ui/src/help/hints.test.ts
 * Touch when:   a screen is added (map its id segment to its route in `SEGMENT_ROUTE`); a
 *               term is added to `LINT` in help.test.ts (mirror it here).
 */
import { describe, expect, it } from 'vitest'
import appSource from '../App.tsx?raw'
import type { TermId } from './glossary'
import { HELP } from './help'
import { HINTS, MIN_HINTS, SHARED_IDS, hintText, type HintId } from './hints'

/** Word → the term id that must be in the route's `terms[]` when the word appears (mirrors help.test.ts). */
const LINT: Array<[RegExp, TermId]> = [
  [/\bcells?\b/i, 'cell'],
  [/\bapparatus\b/i, 'apparatus'],
  [/\bbelts?\b/i, 'belt'],
  [/\bWilson\b/, 'wilson'],
  [/false-Q1/, 'false_q1'],
  [/\boracle\b/i, 'oracle_strength'],
]

/**
 * The shared vocabulary: a two-segment id (`route.deliver`, `belt.target_green`, `run.status`)
 * that a shared component derives itself, plus the two three-segment ids shared components own.
 * The shell's `nav.*` entries are two-segment too but belong to the chrome, not a component,
 * and `tab.evidence` names one screen's tab list.
 */
function isShared(id: string): boolean {
  if (id === 'stat.shared.model_rate' || id === 'nav.journey_position') return true
  return id.split('.').length === 2 && !id.startsWith('nav.') && !id.startsWith('tab.')
}

/**
 * The screen segment of a screen-specific id (`stat.results.x` → `results`) → the route whose
 * About block defines its terms. `null` means the element renders on every screen (the shell)
 * or outside the authenticated routes (login, help, 404): held to the glossary alone.
 */
const SEGMENT_ROUTE: Record<string, string | null> = {
  shell: null,
  shared: null,
  login: null,
  help: null,
  notfound: null,
  home: '/home',
  connect: '/connect',
  github: '/connect',
  walk: '/connect/:name',
  measure: '/connect/:name/measure',
  results: '/results',
  map: '/results',
  cell: '/results',
  decisions: '/decisions',
  signoff: '/signoff',
  factory: '/factory',
  cell_route: '/factory',
  posture: '/posture',
  repos: '/repos',
  repo_new: '/repos',
  repo: '/repos/:name',
  repo_config: '/repos/:name',
  profile: '/repos/:name',
  tasks: '/repos/:name',
  runs: '/runs',
  run_new: '/runs',
  run: '/runs/:id',
  run_tasks: '/runs/:id',
  evidence: '/runs/:id',
  review: '/runs/:id',
  task: '/tasks/:repo/:taskId',
  capability: '/capability',
  routing: '/routing',
  policy: '/routing',
  oracle: '/oracle',
  oracle_cell: '/oracle',
  oracle_task: '/oracle',
  controls: '/oracle',
  learn: '/learn',
  learn_refusals: '/learn',
  learn_strengthen: '/learn',
  learn_remeasure: '/learn',
  ledger: '/ledger',
  settings: '/settings',
}

/** The route an id's copy is linted against, or `null` for shared / shell / unauthenticated ids. */
function routeOf(id: string): string | null {
  const parts = id.split('.')
  if (isShared(id) || parts.length === 2) return null
  const seg = parts[1] ?? ''
  if (!(seg in SEGMENT_ROUTE)) throw new Error(`${id}: unknown screen segment "${seg}" — add it to SEGMENT_ROUTE`)
  return SEGMENT_ROUTE[seg] ?? null
}

/** Every `<Route path="…">` in App.tsx that is a screen (not login, not the help pages, not the catch-all). */
function screenRoutes(): string[] {
  return Array.from(appSource.matchAll(/<Route\s+path="([^"]+)"/g), (m: RegExpMatchArray) => m[1]!).filter((p) => p !== '/login' && p !== '*' && !p.startsWith('/help'))
}

const ENTRIES = Object.entries(HINTS) as Array<[HintId, string]>

describe('HINTS registry', () => {
  it('has a few hundred entries with dotted lower-case ids', () => {
    expect(ENTRIES.length).toBeGreaterThan(600)
    for (const [id] of ENTRIES) expect(id, id).toMatch(/^[a-z_]+(\.[a-z0-9_]+)+$/)
  })

  it('every value is one or two plain sentences: 40–420 characters, a full stop, no markup, link, path or exclamation', () => {
    for (const [id, text] of ENTRIES) {
      expect(text.length, `${id}: ${text.length} chars`).toBeGreaterThanOrEqual(40)
      expect(text.length, `${id}: ${text.length} chars`).toBeLessThanOrEqual(420)
      expect(text, `${id}: must end with a full stop`).toMatch(/\.$/)
      expect(text, `${id}: markup`).not.toMatch(/[<>]/)
      expect(text, `${id}: a link`).not.toMatch(/https?:|docs\//)
      expect(text, `${id}: exclamation mark`).not.toMatch(/!/)
      expect(text.trim(), `${id}: leading or trailing space`).toBe(text)
      expect(text, `${id}: a hint is one or two sentences (at most four)`).not.toMatch(/(?:[.?]\s+[A-Z“][^.?]*){4,}[.?]$/)
    }
  })

  it('copy lint: a term word appears in a screen’s hint only when that screen’s About block lists the term', () => {
    const termsByRoute = new Map(HELP.map((h) => [h.route, h.terms ?? []]))
    for (const [id, text] of ENTRIES) {
      const route = routeOf(id)
      if (route === null) continue
      const terms = termsByRoute.get(route)
      expect(terms, `${id}: no HELP entry for ${route}`).toBeDefined()
      for (const [re, term] of LINT) {
        if (re.test(text)) expect(terms, `${id} on ${route} uses "${re.source}" without term ${term}: ${text}`).toContain(term)
      }
    }
  })

  it('SHARED_IDS is exactly the shared vocabulary: every two-segment id outside nav.*, plus the two a shared component owns', () => {
    const expected = ENTRIES.map(([id]) => id).filter(isShared)
    expect([...SHARED_IDS].sort()).toEqual(expected.sort())
    expect(new Set(SHARED_IDS).size).toBe(SHARED_IDS.length)
  })

  it('MIN_HINTS names exactly the screen routes of App.tsx, each with a positive floor', () => {
    expect(Object.keys(MIN_HINTS).sort()).toEqual(screenRoutes().sort())
    for (const [route, n] of Object.entries(MIN_HINTS)) expect(n, route).toBeGreaterThan(0)
  })

  it('hintText returns the entry', () => {
    expect(hintText('nav.baseline')).toBe(HINTS['nav.baseline'])
  })
})
