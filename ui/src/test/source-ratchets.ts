/**
 * source-ratchets — matchers that read a screen's own source for a pattern it must not use.
 *
 * Navigation
 * ----------
 * What it is:   `queryDataReads(source)`: every place a source reads a query's `data`
 *               directly, in any syntax, rather than through `currentData`.
 * What it does: Backs the "reads every query only through currentData" ratchets. TanStack
 *               Query keeps the last good `data` when a refetch fails, so a direct read shows
 *               an old value as current; `currentData` returns nothing on an error. A ratchet
 *               that matched only `q.data` let `q?.data`, `q['data']` and `const { data } = q`
 *               through (PR #54 review), so the matcher lives here once, with a test of every
 *               syntax, and each page's ratchet calls it instead of carrying its own regex.
 * How:          Three regular expressions over the raw source text: a member read (`.data` or
 *               `?.data` after an identifier, `)` or `]`), a computed read (`['data']` with any
 *               quote, optionally after `?.`), and a destructuring pattern that names `data`
 *               and is assigned (`{ …data… } =`, not `==` or `=>`). Names that merely end in
 *               `Data`, `data-` attributes and object literals are not reads.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`currentData`, the guard the ratchets require),
 *               ui/src/screens/Results/ResultsPage.test.tsx,
 *               ui/src/screens/Capability/CapabilityPage.test.tsx (the ratchets)
 * Tested by:    ui/src/test/source-ratchets.test.ts
 * Touch when:   a syntax for reading a property is found that the matcher misses (add the
 *               case to the test first), or a new screen adopts the ratchet.
 */

const MEMBER = /[\w)\]]\s*\??\.\s*data\b(?!-)/g
const COMPUTED = /(?:\?\.)?\[\s*(['"`])data\1\s*\]/g
const DESTRUCTURED = /\{[^{}]*?(?<![\w-])data\b(?![-\w])[^{}]*\}\s*=(?![=>])/g

/** Every direct read of a query's `data` in `source`, as the matched text (empty when none). */
export function queryDataReads(source: string): string[] {
  return [MEMBER, COMPUTED, DESTRUCTURED].flatMap((re) => source.match(re) ?? [])
}
