/**
 * The build's refusal to ship a Help with no guides: `vite build` fails when the docs the UI
 * bundles are not in its context.
 *
 * Navigation
 * ----------
 * What it is:   `requireBundledDocs()` — a Vite plugin (build only) that ui/vite.config.ts runs.
 * What it does: At `buildStart`, reads `DOC_NAMES` from ui/src/help/docs.ts as text (so this
 *               list cannot drift from it), and fails the build naming every missing file when a
 *               listed guide is not under docs/ or docs/adr holds no decision record
 *               (`nnnn-*.md`, ui/src/help/adrs.ts). A glob that matches nothing is not an error
 *               to Vite, so without this the bundle builds green and every guide reads as
 *               missing — what the image shipped while deploy/Dockerfile.dockerignore dropped
 *               `docs` (docs/PREVENTION.md P-173). An unreadable `DOC_NAMES` fails too, rather
 *               than checking nothing.
 * How:          `existsSync` / `readdirSync` over file URLs; `this.error` (Rollup's) to fail.
 *               The locations are parameters with this repository's paths as defaults, so the
 *               tests run it against temporary trees.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-074)
 * Works with:   ui/vite.config.ts (runs it), ui/src/help/docs.ts (`DOC_NAMES`, read as text),
 *               ui/src/help/adrs.ts (the records' glob), deploy/Dockerfile.dockerignore (the
 *               context it guards), deploy/Dockerfile (the image's `npm run build`)
 * Tested by:    ui/plugins/requireBundledDocs.test.ts
 * Touch when:   the UI bundles a new kind of repository document.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import type { Plugin } from 'vite'

export function requireBundledDocs({
  docs = new URL('../../docs/', import.meta.url),
  registry = new URL('../src/help/docs.ts', import.meta.url),
}: { docs?: URL; registry?: URL } = {}): Plugin {
  return {
    name: 'crb-require-bundled-docs',
    apply: 'build',
    buildStart() {
      const text = readFileSync(registry, 'utf8')
      const names = Array.from(/DOC_NAMES = \[([^\]]*)\]/.exec(text)?.[1]?.matchAll(/'([^']+)'/g) ?? [], (m) => m[1]!)
      if (names.length === 0) this.error('requireBundledDocs: could not read DOC_NAMES from ui/src/help/docs.ts')
      const missing = names.filter((n) => !existsSync(new URL(`${n}.md`, docs)))
      const adrDir = new URL('adr/', docs)
      const adrs = existsSync(adrDir) ? readdirSync(adrDir).filter((f) => /^\d{4}-.*\.md$/.test(f)) : []
      if (missing.length > 0 || adrs.length === 0) {
        this.error(`the UI bundles repository docs, and the build cannot see them: missing ${[...missing.map((n) => `docs/${n}.md`), ...(adrs.length === 0 ? ['docs/adr/*.md'] : [])].join(', ')} — is docs/ in the build context? (deploy/Dockerfile.dockerignore, docs/PREVENTION.md P-173)`)
      }
    },
  }
}
