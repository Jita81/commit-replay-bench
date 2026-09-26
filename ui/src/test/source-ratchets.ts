/**
 * source-ratchets — matchers that read a screen's own source for a pattern it must not use.
 *
 * Navigation
 * ----------
 * What it is:   `queryDataReads(source)`: every place a source reads a query's `data`
 *               directly, in any form it finds on the TypeScript syntax tree, rather than
 *               through `currentData`.
 * What it does: Backs the "reads every query only through currentData" ratchets. TanStack
 *               Query keeps the last good `data` when a refetch fails, so a direct read shows
 *               an old value as current; `currentData` returns nothing on an error. A ratchet
 *               that matched only `q.data` let `q?.data`, `q['data']` and `const { data } = q`
 *               through (PR #54 review), so the matcher lives here once, with a test of every
 *               syntax, and each page's ratchet calls it instead of carrying its own regex.
 * How:          Parses the source with the TypeScript compiler (as TSX) and walks the tree:
 *               a property access named `data` (`.data`, `?.data`, `!.data`), an element
 *               access whose key is the string `data` (any quote, optionally after `?.`), a
 *               destructuring pattern with a `data` key at any depth, and a destructuring
 *               assignment (`({ data } = q)`). A second review found three forms the earlier
 *               regular expressions missed (`q!.data`, a pattern beside a nested one,
 *               `q.data-1`); reading the syntax tree rather than the text is what stops that
 *               class. Names that merely end in `Data`, `data-` attributes, comments and
 *               object literals are not reads. It does not follow a key held in a variable
 *               (`q[key]`) or a call such as `Reflect.get(q, 'data')`: those need a person.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`currentData`, the guard the ratchets require),
 *               ui/src/screens/Results/ResultsPage.test.tsx,
 *               ui/src/screens/Capability/CapabilityPage.test.tsx (the ratchets)
 * Tested by:    ui/src/test/source-ratchets.test.ts
 * Touch when:   a syntax for reading a property is found that the matcher misses (add the
 *               case to the test first), or a new screen adopts the ratchet.
 */

import * as ts from 'typescript'

/** The key a property access, element access or binding names, when it is a plain name. */
function keyText(node: ts.Node | undefined): string | undefined {
  if (node === undefined) return undefined
  if (ts.isIdentifier(node) || ts.isStringLiteralLike(node)) return node.text
  return undefined
}

/** Every direct read of a query's `data` in `source`, as the matched text (empty when none). */
export function queryDataReads(source: string): string[] {
  const file = ts.createSourceFile(
    'source.tsx',
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  )
  const reads: string[] = []
  const visit = (node: ts.Node): void => {
    if (ts.isPropertyAccessExpression(node) && node.name.text === 'data') {
      // `q.data`, `q?.data`, `q!.data`, `(await q).data`, `q.data-1`
      reads.push(node.getText(file))
    } else if (ts.isElementAccessExpression(node) && keyText(node.argumentExpression) === 'data') {
      // `q['data']`, `q?.["data"]`, `` q[`data`] ``
      reads.push(node.getText(file))
    } else if (ts.isBindingElement(node) && keyText(node.propertyName ?? node.name) === 'data') {
      // `const { data } = q`, `{ data: x }`, and a `data` key at any depth of the pattern
      reads.push(node.parent.getText(file))
    } else if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isObjectLiteralExpression(node.left) &&
      node.left.properties.some((p) => keyText(p.name) === 'data')
    ) {
      // a destructuring assignment: `({ data } = q)`
      reads.push(node.left.getText(file))
    }
    ts.forEachChild(node, visit)
  }
  visit(file)
  return reads
}
