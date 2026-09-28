/**
 * An amount a person types, read as they typed it — or refused, never read as blank.
 *
 * Navigation
 * ----------
 * What it is:   The one reader of a numeric field's text (a spend cap, a budget cap, a task
 *               limit, a timeout).
 * What it does: `readAmount(text, rule)` says `blank` for blank text, `ok` with the value for
 *               plain digits (a decimal only where the rule allows one) at or above the
 *               rule's floor, and `bad` for anything else — an exponent, a sign, a unit, a
 *               value below the floor. Fields are `type="text"` with `inputMode`, never
 *               `type="number"`: a number input whose text the browser cannot parse (`1e`,
 *               `1e400`) reports '' while the text stays on screen, so a typed spend cap read
 *               as "no cap" (the verifiers of `feat/ns2-h`, docs/PREVENTION.md P-265). This
 *               is also the GOV.UK Design System's advice for numbers.
 * How:          One regular expression per rule, then `Number` on text it has accepted.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md
 * Works with:   ui/src/screens/Runs/RunNewDialog.tsx (the run form's caps, limit and
 *               timeout), ui/src/screens/Factory/FactoryPage.tsx (the factory's spend cap),
 *               ui/src/screens/Connect/MeasurePage.tsx (the measurement's spend cap)
 * Tested by:    ui/src/lib/amount.test.ts (with the ratchet that no source renders a number
 *               input)
 * Touch when:   never for a new repository; a field needs another shape of number (a sign, a unit).
 */

/** What a field accepts: its floor, whether the floor itself is refused, whole numbers only. */
export interface AmountRule {
  min: number
  /** the value must be above `min`, not equal to it (a spend cap of $0 caps nothing) */
  above?: boolean
  /** whole numbers only (turns, tool calls, seconds, a task count) */
  whole?: boolean
}

export type Amount = { kind: 'blank' } | { kind: 'ok'; value: number } | { kind: 'bad' }

const WHOLE = /^\d+$/
const DECIMAL = /^\d+(?:\.\d+)?$/

/** The text of a numeric field, read under `rule`. */
export function readAmount(text: string, rule: AmountRule): Amount {
  const t = text.trim()
  if (t === '') return { kind: 'blank' }
  if (!(rule.whole ? WHOLE : DECIMAL).test(t)) return { kind: 'bad' }
  const value = Number(t)
  if (!Number.isFinite(value)) return { kind: 'bad' }
  if (rule.above ? value <= rule.min : value < rule.min) return { kind: 'bad' }
  return { kind: 'ok', value }
}
