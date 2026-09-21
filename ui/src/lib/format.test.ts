/**
 * ui/src/lib/format.ts — `kOfN`, the one "k of n" every in-flight line reads.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for `kOfN` (the other formatters are pinned through the tiles).
 * What it does: Pins the ONE meaning of the attempt / task / item number on every screen:
 *               "k of n" names the k-th one, the one running NOW — `done + 1` — so `done = 3`
 *               of 8 reads "4 of 8" on the Baseline banner, the Connection walk, Home and the
 *               run page alike (a reader opening two screens for one run must see one number);
 *               k never passes n (the last one finishing is "n of n", not "n+1"); an unknown
 *               total (`0`, or not a number) is `null`, never "1 of 0".
 * How:          Direct calls.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/format.ts (the code under test), ui/src/screens/Results/ResultsPage.tsx,
 *               ui/src/screens/Connect/ConnectPage.tsx, ui/src/screens/Connect/connection.ts,
 *               ui/src/screens/Home/HomePage.tsx, ui/src/screens/Runs/telemetry.ts,
 *               ui/src/screens/Factory/FactoryPage.tsx (the callers)
 * Tested by:    ui/src/lib/format.test.ts
 * Touch when:   the meaning of the progress number changes — it changes for every screen at once.
 */
import { describe, expect, it } from 'vitest'
import { kOfN } from './format'

describe('kOfN', () => {
  it('names the one running now (done + 1), never past n', () => {
    expect(kOfN(0, 8)).toBe('1 of 8')
    expect(kOfN(3, 8)).toBe('4 of 8')
    expect(kOfN(7, 8)).toBe('8 of 8')
    expect(kOfN(8, 8)).toBe('8 of 8')
    expect(kOfN(12, 8)).toBe('8 of 8')
  })
  it('is null when the total is unknown, and formats large counts', () => {
    expect(kOfN(0, 0)).toBeNull()
    expect(kOfN(3, -1)).toBeNull()
    expect(kOfN(Number.NaN, 8)).toBeNull()
    expect(kOfN(3, Number.NaN)).toBeNull()
    expect(kOfN(999, 1200)).toBe('1,000 of 1,200')
  })
})
