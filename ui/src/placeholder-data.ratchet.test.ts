/**
 * A placeholder is never a verdict — every query that keeps an old answer on screen while the
 * next one loads is declared, and every screen that reads it separates the two.
 *
 * Navigation
 * ----------
 * What it is:   A source-level ratchet (P-102) over `ui/src`: each file that gives a query
 *               `placeholderData` (or `keepPreviousData`) is named here with the hook it
 *               exports, and every non-test file that calls that hook reads
 *               `isPlaceholderData`.
 * What it does: Catches the class of defect found on `/signoff` in stream A1: to keep the
 *               Accepted row select enabled under keyboard focus, the preview query kept the
 *               previous row's answer as a placeholder, and the gate, the refusals and
 *               `signable` read it as the new row's — the gate showed OPEN and Sign off was
 *               enabled for a row nothing had judged. A placeholder can keep a control and
 *               its options on screen; it cannot say what the server would do. A new
 *               placeholder, or a new caller of a declared hook, fails here until its
 *               author says how the caller keeps the placeholder out of its verdicts.
 * How:          Reads the sources as text through Vite's `import.meta.glob(..., '?raw')`;
 *               `findings()` is pure and is also run on a synthetic violation (the negative
 *               control) so the ratchet is shown to fail on the defect it guards.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Signoff/contract.ts (`useSignoffPreview`, the one declared
 *               placeholder), ui/src/screens/Signoff/SignoffPage.tsx (its `current`, built
 *               without the placeholder), ui/src/screens/Signoff/SignoffPage.test.tsx (the
 *               behaviour: the gate is pending while a newly named row loads),
 *               ui/src/App.reachability.test.ts (the same raw-source pattern),
 *               docs/PREVENTION.md (row P-102)
 * Tested by:    itself (the negative control below)
 * Touch when:   a query is given `placeholderData` — declare it below with its hook and make
 *               every caller read `isPlaceholderData` before it builds a gate or a verdict.
 */
import { describe, expect, it } from 'vitest'

/** Every source file of the app as text — Vite's own raw import, so this needs no node types. */
const SOURCES = import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Each file that sets a placeholder → the hook it exports and why the placeholder is there. */
const DECLARED: Record<string, { hook: string; why: string }> = {
  './screens/Signoff/contract.ts': {
    hook: 'useSignoffPreview',
    why: 'keeps the Accepted row select and its rows enabled while a newly named row of the same cell loads (G-905)',
  },
}

const isTest = (path: string) => /\.test\.tsx?$/.test(path)
const PLACEHOLDER = /\bplaceholderData\s*:|\bkeepPreviousData\b/

/** What is wrong with the sources against the declarations; empty when the ratchet holds. */
function findings(sources: Record<string, string>, declared: Record<string, { hook: string }>): string[] {
  const out: string[] = []
  const app = Object.entries(sources).filter(([path]) => !isTest(path))
  for (const [path, text] of app) {
    if (PLACEHOLDER.test(text) && !(path in declared)) out.push(`${path} sets a placeholder that is not declared`)
  }
  for (const [path, { hook }] of Object.entries(declared)) {
    const text = sources[path]
    if (text === undefined || !PLACEHOLDER.test(text)) {
      out.push(`${path} is declared but sets no placeholder`)
      continue
    }
    const call = new RegExp(`\\b${hook}\\(`)
    for (const [caller, body] of app) {
      if (caller === path || !call.test(body)) continue
      if (!/\bisPlaceholderData\b/.test(body)) out.push(`${caller} calls ${hook} and never reads isPlaceholderData`)
    }
  }
  return out
}

describe('a placeholder is never a verdict (P-102)', () => {
  it('finds the sources', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50)
  })

  it('every placeholder is declared, and every caller of a declared hook reads isPlaceholderData', () => {
    expect(findings(SOURCES, DECLARED)).toEqual([])
  })

  it('negative control: an undeclared placeholder and a caller that ignores it are both caught', () => {
    const bad = {
      './screens/X/contract.ts': "export function useX() { return useQuery({ queryKey: ['x'], placeholderData: (p) => p }) }",
      './screens/Y/contract.ts': "export function useY() { return useQuery({ queryKey: ['y'], placeholderData: (p) => p }) }",
      './screens/Y/YPage.tsx': 'const y = useY(); const ok = Boolean(y.data?.signable)',
    }
    expect(findings(bad, { './screens/Y/contract.ts': { hook: 'useY' } })).toEqual([
      './screens/X/contract.ts sets a placeholder that is not declared',
      './screens/Y/YPage.tsx calls useY and never reads isPlaceholderData',
    ])
  })
})
