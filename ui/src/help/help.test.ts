/**
 * help.ts — the ratchet: every route has help, every anchor resolves, every term exists.
 *
 * Navigation
 * ----------
 * What it is:   The help registry's ratchet test.
 * What it does: Pins that (1) every path in the app's route table except the pre-session
 *               screens (`/login`, `/invite`) and `*`
 *               has a `helpFor()` hit and the two help routes have none; (2) every
 *               `readMore.to` and every term's `readMore` names a bundled guide and, when it
 *               carries a slug, a heading in that file slugifies to it; (3) every `terms[]` id
 *               is in `TERMS`; (4) copy lint — purpose / next / numbers use "cell",
 *               "apparatus", "belt", "Wilson", "false-Q1" or "oracle" only when that term is
 *               in the screen's `terms[]`; every string is plain (no exclamation mark) and
 *               `next.viewer` always exists.
 * How:          Reads `ui/src/App.tsx` and the eight guides as `?raw` text so the ratchet
 *               needs no React; `matchPath` through `helpFor`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/help.ts, ui/src/App.tsx (the route table it reads),
 *               ui/src/help/glossary.ts, ui/src/help/docs.ts (`slugify`, `isDocName`)
 * Tested by:    ui/src/help/help.test.ts
 * Touch when:   a screen is added — it needs a `HELP` entry before this passes.
 */
import { describe, expect, it } from 'vitest'
import appSource from '../App.tsx?raw'
import { isDocName, slugify, type DocAnchor } from './docs'
import { TERMS, type TermId } from './glossary'
import { HELP, helpFor } from './help'

/** The guides' text, eagerly, keyed by file name — the same files ui/src/help/docs.ts bundles. */
const DOC_TEXT = import.meta.glob('../../../docs/{ONBOARDING-A-REPO,OPERATOR,EVIDENCE-AND-CLAIMS,GITHUB-APP,SECURITY,DATA-RETENTION,LEARNING-LOOP,DEPLOYMENT}.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Every `<Route path="…">` in App.tsx, read from the source so the ratchet cannot drift from the table. */
function appRoutePaths(): string[] {
  return Array.from(appSource.matchAll(/<Route\s+path="([^"]+)"/g), (m: RegExpMatchArray) => m[1]!)
}

/** A concrete pathname for a react-router pattern (`/runs/:id` → `/runs/x`). */
function concrete(pattern: string): string {
  return pattern.replace(/:[A-Za-z]+/g, 'x')
}

/** The heading slugs of a bundled doc, with GitHub's -1/-2 suffixes for duplicates. */
function headingSlugs(name: string): Set<string> {
  const text = DOC_TEXT[`../../../docs/${name}.md`] ?? ''
  const seen = new Map<string, number>()
  const out = new Set<string>()
  let fence = false
  for (const line of text.split('\n')) {
    if (/^```/.test(line)) {
      fence = !fence
      continue
    }
    if (fence) continue
    const m = /^#{1,6}\s+(.*?)\s*#*$/.exec(line)
    if (!m) continue
    const base = slugify(m[1]!)
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    out.add(n === 0 ? base : `${base}-${n}`)
  }
  return out
}

function expectAnchorResolves(anchor: DocAnchor, where: string): void {
  const [name, slug] = anchor.split('#')
  expect(isDocName(name ?? ''), `${where}: ${anchor} is not a bundled guide`).toBe(true)
  if (slug) expect(headingSlugs(name!).has(slug), `${where}: no heading in docs/${name}.md slugifies to #${slug}`).toBe(true)
}

/** Word → the term id that must be in `terms[]` when the word appears in copy. */
const LINT: Array<[RegExp, TermId]> = [
  [/\bcells?\b/i, 'cell'],
  [/\bapparatus\b/i, 'apparatus'],
  [/\bbelts?\b/i, 'belt'],
  [/\bWilson\b/, 'wilson'],
  [/false-Q1/, 'false_q1'],
  [/\boracle\b/i, 'oracle_strength'],
]

describe('HELP ratchet', () => {
  it('every route in App.tsx except the two pre-session screens and * has an entry; the help routes have none', () => {
    const paths = appRoutePaths()
    expect(paths.length).toBeGreaterThan(20)
    for (const p of paths) {
      // /login and /invite render outside the shell, so there is no Help panel to open on
      // them: both explain themselves in their own copy and carry hints the ratchet enforces
      if (p === '/login' || p === '/invite' || p === '*') continue
      if (p.startsWith('/help')) {
        expect(helpFor(concrete(p)), p).toBeUndefined()
        continue
      }
      expect(helpFor(concrete(p)), `no HELP entry matches ${p}`).toBeDefined()
    }
    expect(helpFor('/nowhere')).toBeUndefined()
  })

  it('helpFor matches in declaration order and returns the most specific declared entry', () => {
    expect(helpFor('/connect/cobra/measure')?.route).toBe('/connect/:name/measure')
    expect(helpFor('/connect/cobra')?.route).toBe('/connect/:name')
    expect(helpFor('/connect')?.route).toBe('/connect')
    expect(helpFor('/runs/abc')?.route).toBe('/runs/:id')
  })

  it('every readMore anchor (screens and terms) names a bundled guide and a real heading', () => {
    for (const h of HELP) {
      expect(h.readMore.length, `${h.route}: readMore is empty`).toBeGreaterThan(0)
      for (const r of h.readMore) {
        expect(r.label.trim().length, `${h.route}: readMore label`).toBeGreaterThan(0)
        expectAnchorResolves(r.to, h.route)
      }
    }
    for (const [id, t] of Object.entries(TERMS)) {
      if (t.readMore) expectAnchorResolves(t.readMore, `term ${id}`)
    }
  })

  it('every terms[] id exists and is not repeated', () => {
    for (const h of HELP) {
      const ids = h.terms ?? []
      for (const id of ids) expect(TERMS[id], `${h.route}: unknown term ${id}`).toBeDefined()
      expect(new Set(ids).size, `${h.route}: repeated term`).toBe(ids.length)
    }
  })

  it('copy lint: a term word appears only when the term is on the screen; plain English throughout', () => {
    for (const h of HELP) {
      const strings = [h.purpose, ...Object.values(h.next), h.numbers ?? '']
      expect(h.next.viewer.trim().length, `${h.route}: next.viewer`).toBeGreaterThan(0)
      for (const s of strings) {
        expect(s, `${h.route}: exclamation mark`).not.toMatch(/!/)
        expect(s.split(/(?<=[.?])\s+(?=[A-Z"])/).length, `${h.route}: more than 6 sentences: ${s}`).toBeLessThanOrEqual(6)
        for (const [re, id] of LINT) {
          if (re.test(s)) expect(h.terms ?? [], `${h.route}: uses "${re.source}" without term ${id}: ${s}`).toContain(id)
        }
      }
    }
  })
})
