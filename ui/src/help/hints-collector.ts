/**
 * The hint collector — every element a reader meets that does not resolve to a registry id.
 *
 * Navigation
 * ----------
 * What it is:   `unhinted(root)`: the elements under `root` the mechanism requires a hint on
 *               (tiles, pills, column headers, fields, primary buttons, nav links, gate
 *               criteria, card eyebrows that are a count) that sit under no `data-hint` the
 *               registry knows, each described in
 *               one line (`column header <th> 'Wilson lower' in table 'Route decisions'`).
 * What it does: One walk, shared by the ratchet and by every screen test that asserts its
 *               own screen is fully hinted, so the two can never disagree about what counts.
 *               It lives outside the ratchet's test file so a screen test can import it
 *               without pulling the ratchet's suite into its own run.
 * How:          A selector table (`REQUIRED`); the trigger may be the element itself, an
 *               ancestor (a field's root) or a descendant (a header's sort button, a
 *               criterion's label); a column header with no text carries nothing to explain.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints.ts (`HINTS` — the ids that resolve), ui/src/components/Hint.tsx
 *               (the `data-hint` attribute it looks for), ui/src/help/hints-ratchet.test.tsx
 *               (re-exports it and runs it on every enforced route), ui/src/screens/**\/*.test.tsx
 *               (each on-ramp screen test asserts `unhinted(container)` is empty)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx (the collector reports a StatTile and a
 *               column without a hint)
 * Touch when:   the mechanism adds a kind of element that must carry a hint — add its
 *               selector here and a case to the ratchet's collector test.
 */
import { HINTS } from './hints'

/** The elements the mechanism requires a hint on — each selector names what a reader meets. */
export const REQUIRED: Array<[string, string]> = [
  ['[data-component="stat-tile"]', 'tile'],
  ['[data-component="pill"]', 'pill'],
  ['th[scope="col"]', 'column header'],
  ['input:not([type=hidden]), select, textarea', 'field'],
  ['button[data-primary], a[data-primary]', 'primary button'],
  ['nav a', 'nav link'],
  ['[data-component="gate"] li', 'gate criterion'],
  ['[data-eyebrow]', 'count eyebrow'],
]

/** A one-line description of an element for the failure message. */
function describe_(el: Element, kind: string): string {
  const text = (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)
  const table = el.closest('table')?.querySelector('caption')?.textContent?.trim()
  const label = el.id ? el.ownerDocument.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : undefined
  return `${kind} <${el.tagName.toLowerCase()}> '${label ?? text}'${table ? ` in table '${table}'` : ''}`
}

/** Every required element in `root` that does not sit under a `data-hint` the registry knows. */
export function unhinted(root: ParentNode): string[] {
  const out: string[] = []
  for (const [selector, kind] of REQUIRED) {
    for (const el of Array.from(root.querySelectorAll(selector))) {
      // a column header whose text is empty carries nothing to explain
      if (kind === 'column header' && !(el.textContent ?? '').trim()) continue
      // a card eyebrow is a number only when it starts with one ("2 waiting"); a descriptive eyebrow is prose
      if (kind === 'count eyebrow' && !/^\d/.test((el.textContent ?? '').trim())) continue
      // the trigger is the element itself, an ancestor (a field's root) or a descendant (a header's sort button, a criterion's label)
      const wrapper = el.closest('[data-hint]') ?? el.querySelector('[data-hint]')
      const id = wrapper?.getAttribute('data-hint') ?? ''
      if (!wrapper || !(id in HINTS)) out.push(describe_(el, kind))
    }
  }
  return out
}
