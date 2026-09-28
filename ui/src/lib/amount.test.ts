/**
 * An amount a person types is read as they typed it, or refused — never read as blank.
 *
 * Navigation
 * ----------
 * What it is:   The tests of ui/src/lib/amount.ts and a source-level ratchet (P-265) over
 *               `ui/src`: no screen or component renders an `<input type="number">`.
 * What it does: Pins that `readAmount` takes plain digits only (a decimal where the field
 *               allows one), refuses an exponent, a sign, a unit or a value below the field's
 *               floor, and reads blank only for blank text. The ratchet catches the class of
 *               defect the verifiers of `feat/ns2-h` reproduced in Chromium: a number input
 *               whose text the browser cannot parse (`1e`, `1e400`) reports its value as ''
 *               while the text stays on screen, so a typed spend cap read as "no cap" and the
 *               run queued uncapped. With `type="text"` and `inputMode` the page reads what
 *               is on screen; the negative control shows the ratchet fails on the defect.
 * How:          Plain calls; the sources as text through Vite's `import.meta.glob(…, '?raw')`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md
 * Works with:   ui/src/lib/amount.ts (under test), ui/src/screens/Runs/RunNewDialog.tsx (the
 *               run form's caps, limit and timeout), ui/src/screens/Factory/FactoryPage.tsx
 *               (the factory's spend cap), ui/src/screens/Connect/MeasurePage.tsx (the
 *               measurement's spend cap), docs/PREVENTION.md (row P-265)
 * Tested by:    itself (the negative control below)
 * Touch when:   never for a new repository; a field takes a number: read it with `readAmount`,
 *               never `type="number"`.
 */
import { describe, expect, it } from 'vitest'
import { readAmount } from './amount'

const SOURCES = import.meta.glob(['../components/**/*.tsx', '../screens/**/*.tsx', '../App.tsx', '!**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

const NUMBER_INPUT = /\btype\s*=\s*\{?\s*['"]number['"]|\btype\s*:\s*['"]number['"]/

/** Each source that renders a number input. */
function numberInputs(sources: Record<string, string>): string[] {
  return Object.entries(sources)
    .filter(([, text]) => NUMBER_INPUT.test(text))
    .map(([path]) => path)
}

describe('readAmount', () => {
  it('reads blank only for blank text', () => {
    expect(readAmount('', { min: 0 })).toEqual({ kind: 'blank' })
    expect(readAmount('   ', { min: 0 })).toEqual({ kind: 'blank' })
  })

  it('reads plain digits, and a decimal where the field allows one', () => {
    expect(readAmount('12.5', { min: 0, above: true })).toEqual({ kind: 'ok', value: 12.5 })
    expect(readAmount(' 25 ', { min: 1, whole: true })).toEqual({ kind: 'ok', value: 25 })
    expect(readAmount('0', { min: 0 })).toEqual({ kind: 'ok', value: 0 })
  })

  it('refuses what a number input would have read as blank, and anything below the floor', () => {
    for (const text of ['1e', '1e400', '1e3', '-1', '+2', '$5', '5..5', '5.', '.5', 'abc', 'Infinity', 'NaN', '0x10']) {
      expect(readAmount(text, { min: 0 }), text).toEqual({ kind: 'bad' })
    }
    expect(readAmount('1.5', { min: 1, whole: true })).toEqual({ kind: 'bad' })
    expect(readAmount('0', { min: 1, whole: true })).toEqual({ kind: 'bad' })
    expect(readAmount('0', { min: 0, above: true })).toEqual({ kind: 'bad' })
    expect(readAmount('0.00', { min: 0, above: true })).toEqual({ kind: 'bad' })
  })
})

describe('no number input (P-265)', () => {
  it('finds the sources', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50)
  })

  it('no screen or component renders a number input', () => {
    expect(numberInputs(SOURCES)).toEqual([])
  })

  it('the negative control: each spelling of a number input is caught', () => {
    const planted = {
      a: '<TextField type="number" value={x} />',
      b: "<input type='number' />",
      c: "const props = { type: 'number' }",
      d: '<input type={"number"} />',
      e: '<input type="text" inputMode="decimal" />',
    }
    expect(numberInputs(planted)).toEqual(['a', 'b', 'c', 'd'])
  })
})
