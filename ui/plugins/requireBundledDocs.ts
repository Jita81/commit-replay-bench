/**
 * The build's refusal to ship a Help with no guides: `vite build` fails when the docs the UI
 * bundles are not in its context.
 *
 * Navigation
 * ----------
 * What it is:   `requireBundledDocs()` — a Vite plugin (build only) that ui/vite.config.ts runs.
 * What it does: At `buildStart`, reads `DOC_NAMES` from ui/src/help/docs.ts and the numbers of
 *               `ADR_TITLES` from ui/src/help/adrs.ts as text (so neither list can drift from
 *               it), and fails the build naming every missing file when a listed guide is not
 *               under docs/ or a listed decision record has no `docs/adr/nnnn-*.md` — every
 *               one, since one record present is not the list present (P-422). A glob that
 *               matches nothing is not an error to Vite, so without this the bundle builds
 *               green and every guide reads as missing — what the image shipped while deploy/Dockerfile.dockerignore dropped
 *               `docs` (docs/PREVENTION.md P-173). An unreadable `DOC_NAMES` or `ADR_TITLES`
 *               fails too, rather than checking nothing.
 * How:          `existsSync` / `readdirSync` over file URLs; `this.error` (Rollup's) to fail.
 *               The locations are parameters with this repository's paths as defaults, so the
 *               tests run it against temporary trees.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-073)
 * Works with:   ui/vite.config.ts (runs it), ui/src/help/docs.ts (`DOC_NAMES`, read as text),
 *               ui/src/help/adrs.ts (`ADR_TITLES`, read as text, and the records' glob), deploy/Dockerfile.dockerignore (the
 *               context it guards), deploy/Dockerfile (the image's `npm run build`)
 * Tested by:    ui/plugins/requireBundledDocs.test.ts
 * Touch when:   the UI bundles a new kind of repository document.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import type { Plugin } from 'vite'

export function requireBundledDocs({
  docs = new URL('../../docs/', import.meta.url),
  registry = new URL('../src/help/docs.ts', import.meta.url),
  adrRegistry = new URL('../src/help/adrs.ts', import.meta.url),
}: { docs?: URL; registry?: URL; adrRegistry?: URL } = {}): Plugin {
  return {
    name: 'crb-require-bundled-docs',
    apply: 'build',
    buildStart() {
      const text = readFileSync(registry, 'utf8')
      const names = Array.from(/DOC_NAMES = \[([^\]]*)\]/.exec(text)?.[1]?.matchAll(/'([^']+)'/g) ?? [], (m) => m[1]!)
      if (names.length === 0) this.error('requireBundledDocs: could not read DOC_NAMES from ui/src/help/docs.ts')
      // a guide kept below docs/ is mapped in `NESTED` (`'HUMAN-REVIEW-GUIDE': 'reviews/human-review-guide'`, G-481)
      const nested = new Map(Array.from(/NESTED[^=]*=\s*\{([^}]*)\}/.exec(text)?.[1]?.matchAll(/'([^']+)':\s*'([^']+)'/g) ?? [], (m) => [m[1]!, m[2]!] as const))
      const pathOf = (n: string) => nested.get(n) ?? n
      // every record /help links (ADR_TITLES), not "some record": one present file is not the
      // list present, and a listed record the build cannot see is a link that fails (P-422)
      const adrText = readFileSync(adrRegistry, 'utf8')
      const listed = Array.from(/ADR_TITLES[^=]*=\s*\[([\s\S]*?)\n\]/.exec(adrText)?.[1]?.matchAll(/\[\s*'(\d{4})'/g) ?? [], (m) => m[1]!)
      if (listed.length === 0) this.error('requireBundledDocs: could not read ADR_TITLES from ui/src/help/adrs.ts')
      const missing = names.filter((n) => !existsSync(new URL(`${pathOf(n)}.md`, docs))).map((n) => `docs/${pathOf(n)}.md`)
      const adrDir = new URL('adr/', docs)
      const adrs = existsSync(adrDir) ? readdirSync(adrDir).filter((f) => /^\d{4}-.*\.md$/.test(f)) : []
      if (adrs.length === 0) missing.push('docs/adr/*.md')
      for (const num of listed) if (!adrs.some((f) => f.startsWith(`${num}-`))) missing.push(`docs/adr/${num}-*.md`)
      if (missing.length > 0) {
        this.error(`the UI bundles repository docs, and the build cannot see them: missing ${missing.join(', ')} — is docs/ in the build context? (deploy/Dockerfile.dockerignore, docs/PREVENTION.md P-173, P-422)`)
      }
    },
  }
}
