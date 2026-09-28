/**
 * One Escape closes one layer — every document- or window-level keydown listener is declared
 * with the layer it closes, and a layer that sits UNDER others checks where focus is first.
 *
 * Navigation
 * ----------
 * What it is:   A source-level ratchet (P-170) over `ui/src`: each non-test file that adds a
 *               `keydown` listener to `document` or `window` is named here with its layer —
 *               `innermost` (spends the press: `preventDefault` and `stopPropagation`),
 *               `top` (a modal layer that holds focus) or `under` (a layer others open on
 *               top of, which must skip a spent press and a press made with focus elsewhere).
 * What it does: Catches the class of defect found on the phone Menu in stream A1: the menu's
 *               document listener closed on any Escape that was not default-prevented, so
 *               one press that closed the evidence drawer (a window listener that does not
 *               spend the press) closed the menu under it too and moved focus. A new global
 *               listener fails here until it is declared, and an `under` listener fails
 *               unless its source skips a spent press (`defaultPrevented`) and asks where
 *               focus is (`activeElement`).
 * How:          Reads the sources as text through Vite's `import.meta.glob(..., '?raw')`;
 *               `findings()` is pure and is also run on a synthetic violation (the negative
 *               control) so the ratchet is shown to fail on the defect it guards.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Layout.tsx (the phone Menu: `under`, with
 *               `focusIsOnTheMenu`), ui/src/components/Hint.tsx (the bubble: `innermost`),
 *               ui/src/screens/Runs/EvidenceDrawer.tsx (the drawer: `top`),
 *               ui/src/components/Layout.test.tsx (the behaviour: a drawer's Escape leaves
 *               the menu open), docs/PREVENTION.md (row P-170)
 * Tested by:    itself (the negative control below)
 * Touch when:   never for a new repository; a component listens for keys on `document` or `window`
 *               — declare its layer below, and if others can open on top of it, check focus before
 *               it acts.
 */
import { describe, expect, it } from 'vitest'

/** Every source file of the app as text — Vite's own raw import, so this needs no node types. */
const SOURCES = import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

type LayerKind = 'innermost' | 'top' | 'under'

/** Each file with a global keydown listener → the layer it closes, and why. */
const DECLARED: Record<string, { layer: LayerKind; why: string }> = {
  './components/Hint.tsx': { layer: 'innermost', why: 'a hint bubble is the innermost thing on any screen: it spends the press in the capture phase' },
  './screens/Runs/EvidenceDrawer.tsx': { layer: 'top', why: 'a modal drawer that takes focus when it opens; nothing but a hint opens on top of it' },
  './components/Layout.tsx': { layer: 'under', why: 'the phone Menu: the drawer, a dialog or a hint can open over it' },
}

const isTest = (path: string) => /\.test\.tsx?$/.test(path)
const GLOBAL_KEYDOWN = /\b(?:document|window)\.addEventListener\(\s*['"]keydown['"]/

/** What is wrong with the sources against the declarations; empty when the ratchet holds. */
function findings(sources: Record<string, string>, declared: Record<string, { layer: LayerKind }>): string[] {
  const out: string[] = []
  for (const [path, text] of Object.entries(sources)) {
    if (isTest(path) || !GLOBAL_KEYDOWN.test(text)) continue
    const d = declared[path]
    if (!d) {
      out.push(`${path} listens for keys on document or window and declares no layer`)
      continue
    }
    if (d.layer === 'innermost' && !(/\bstopPropagation\(/.test(text) && /\bpreventDefault\(/.test(text))) {
      out.push(`${path} is innermost but does not spend the press`)
    }
    if (d.layer === 'under' && !(/\bdefaultPrevented\b/.test(text) && /\bactiveElement\b/.test(text))) {
      out.push(`${path} sits under other layers but acts without checking a spent press and where focus is`)
    }
  }
  for (const path of Object.keys(declared)) {
    if (!(path in sources) || !GLOBAL_KEYDOWN.test(sources[path]!)) out.push(`${path} is declared but has no global keydown listener`)
  }
  return out
}

describe('one Escape closes one layer (P-170)', () => {
  it('finds the sources', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50)
  })

  it('every global keydown listener is declared with its layer, and an under layer checks focus', () => {
    expect(findings(SOURCES, DECLARED)).toEqual([])
  })

  it('negative control: an undeclared listener and an under layer that ignores focus are both caught', () => {
    const bad = {
      './components/Menu.tsx': "document.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.defaultPrevented) return; close() })",
      './components/Toast.tsx': "window.addEventListener('keydown', (e) => { if (e.key === 'Escape') close() })",
    }
    expect(findings(bad, { './components/Menu.tsx': { layer: 'under' } })).toEqual([
      './components/Menu.tsx sits under other layers but acts without checking a spent press and where focus is',
      './components/Toast.tsx listens for keys on document or window and declares no layer',
    ])
  })
})
