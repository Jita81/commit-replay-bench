/**
 * source-ratchets — the `<query>.data` matcher finds every way to read a query's data.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `queryDataReads`, the matcher behind the "reads every query only
 *               through currentData" ratchets on the Results and Capability pages.
 * What it does: Pins that a direct read (`q.data`), an optional read (`q?.data`), a computed
 *               read (`q['data']`, `q?.["data"]`, `` q[`data`] ``) and a destructured read
 *               (`const { data } = q`, `const { data: x, isError } = q`) are all found, so a
 *               ratchet built on it cannot be passed by changing the syntax (PR #54 review);
 *               and, from the second review, `q!.data`, a pattern beside a nested one,
 *               `q.data-1`, a destructuring assignment and a `data` key deeper in a pattern;
 *               and that what is not a read — `currentData(q)`, a `mapData` name, a
 *               `data-testid` attribute, an object literal with a `data` key — is not.
 * How:          Pure string cases; no React, no DOM.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/test/source-ratchets.ts (under test),
 *               ui/src/screens/Results/ResultsPage.test.tsx and
 *               ui/src/screens/Capability/CapabilityPage.test.tsx (the ratchets that use it)
 * Tested by:    (this is a test file)
 * Touch when:   a new syntax for reading a property appears in TypeScript, or the matcher
 *               is found to miss one (add the case here first).
 */
import { describe, expect, it } from 'vitest'
import { queryDataReads } from './source-ratchets'

describe('queryDataReads', () => {
  it.each([
    ['direct', 'const v = run.data'],
    ['optional', 'const v = run?.data?.status'],
    ['computed', "const v = run['data']"],
    ['computed, double quotes', 'const v = run["data"]'],
    ['computed, template', 'const v = run[`data`]'],
    ['optional computed', "const v = run?.['data']"],
    ['destructured', 'const { data } = run'],
    ['destructured and renamed', 'const { data: current, isError } = run'],
    ['destructured over lines', 'const {\n  isError,\n  data,\n} = run'],
    // second review of PR #54: three forms the first matcher let through
    ['non-null asserted', 'const v = run!.data'],
    ['destructured beside a nested pattern', 'const { data, error: { message } } = run'],
    ['unspaced arithmetic', 'const n = run.data-1'],
    ['destructuring assignment', 'let data; ({ data } = run)'],
    ['destructured at depth', 'const { result: { data } } = run'],
  ])('finds a %s read', (_, source) => {
    expect(queryDataReads(source)).toHaveLength(1)
  })

  it.each([
    ['the guard itself', 'const v = currentData(run)'],
    ['a name that ends in Data', 'const v = runData?.status ?? mapData.cells'],
    ['a data- attribute', '<div data-testid="tile" data-hint="x" />'],
    ['an object literal with a data key', 'return { data: rows, total }'],
    ['a comparison, not an assignment', 'if ({ data } == x) {}'],
    ['a prose mention', '// a `<query>.data` read shows an old value'],
  ])('does not flag %s', (_, source) => {
    expect(queryDataReads(source)).toEqual([])
  })
})
