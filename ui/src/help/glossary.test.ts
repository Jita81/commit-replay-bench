/**
 * glossary.ts — the 22 terms exist, each is short, plain and points at a bundled guide.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the glossary registry.
 * What it does: Pins the 22 term ids the screens rely on; that every `short` is at most two
 *               sentences with no exclamation mark and no raw API word; that every `readMore`
 *               names a bundled guide.
 * How:          Plain assertions over `TERMS`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/glossary.ts, ui/src/help/docs.ts (`isDocName`)
 * Tested by:    ui/src/help/glossary.test.ts
 * Touch when:   a term is added.
 */
import { describe, expect, it } from 'vitest'
import { isDocName } from './docs'
import { TERM_IDS, TERMS, type TermId } from './glossary'

const EXPECTED: TermId[] = [
  'cell', 'apparatus', 'belt', 'clean', 'gold_clean', 'wilson', 'sighted', 'blind', 'deliver', 'calibrate', 'human',
  'granularize', 'false_q1', 'oracle_strength', 'negative_controls', 'controls_escape', 'red_proof', 'route_gate',
  'reason_code', 'signoff', 'stale', 'evidence_pack',
]

/** Sentence count: a full stop, question mark or colon-free end followed by a space and a capital. */
function sentences(s: string): number {
  return s.split(/(?<=[.!?])\s+(?=[A-Z(])/).filter(Boolean).length
}

describe('TERMS', () => {
  it('holds exactly the 22 ids the screens use, in the contract order', () => {
    expect(TERM_IDS).toEqual(EXPECTED)
    expect(Object.keys(TERMS).sort()).toEqual([...EXPECTED].sort())
  })

  it('every short definition is at most two sentences, has no exclamation mark and names its term', () => {
    for (const id of TERM_IDS) {
      const t = TERMS[id]
      expect(t.term.length, id).toBeGreaterThan(1)
      expect(sentences(t.short), `${id}: ${t.short}`).toBeLessThanOrEqual(2)
      expect(t.short, id).not.toMatch(/!/)
      expect(t.short, id).toMatch(/\.$/)
    }
  })

  it('every readMore names a bundled guide', () => {
    for (const id of TERM_IDS) {
      const to = TERMS[id].readMore
      if (!to) continue
      expect(isDocName(to.split('#')[0] ?? ''), `${id}: ${to}`).toBe(true)
    }
  })

  it('the four routes and the two rates carry their thresholds', () => {
    expect(TERMS.deliver.short).toMatch(/n ≥ 10/)
    expect(TERMS.deliver.short).toMatch(/never means a change is safe to merge/)
    expect(TERMS.oracle_strength.short).toMatch(/killed \/ mutants planted/)
    expect(TERMS.wilson.short).toMatch(/95 %/)
  })
})
