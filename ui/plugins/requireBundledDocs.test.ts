// @vitest-environment node
/**
 * requireBundledDocs — `vite build` refuses a context without the docs the UI bundles.
 *
 * Navigation
 * ----------
 * What it is:   Behavioural tests for the build plugin in ui/plugins/requireBundledDocs.ts, and
 *               for its wiring into ui/vite.config.ts.
 * What it does: Runs the plugin's `buildStart` against temporary docs directories and pins
 *               that it passes with every guide `DOC_NAMES` lists and a decision record, and
 *               fails naming what is missing when one guide is gone, when docs/adr is empty
 *               or absent, and when `DOC_NAMES` cannot be read; that it passes on this
 *               repository's own docs; and that the config vite builds with lists it — so the
 *               refusal P-173 relies on is proven by what it does, not by the words in the
 *               config (the grep this replaced survived its `if (false)` mutation).
 * How:          `mkdtempSync` trees; `buildStart` called with a `this` whose `error` throws, as
 *               Rollup's does; the config imported and its plugins' names read.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-074)
 * Works with:   ui/plugins/requireBundledDocs.ts, ui/vite.config.ts, ui/src/help/docs.ts
 *               (`DOC_NAMES`), deploy/Dockerfile.dockerignore (the context the refusal guards),
 *               tests/test_image_bundles_docs.py (the ignore file's half), docs/PREVENTION.md P-173
 * Tested by:    ui/plugins/requireBundledDocs.test.ts
 * Touch when:   the bundled docs change shape (a new kind of document the UI imports).
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { afterEach, describe, expect, it } from 'vitest'
import { requireBundledDocs } from './requireBundledDocs'

const made: string[] = []
afterEach(() => {
  while (made.length) rmSync(made.pop()!, { recursive: true, force: true })
})

/** A temporary tree: `docs/` with `guides` and `adrs`, and a `docs.ts` declaring `names`. */
function tree(opts: { names: string[]; guides: string[]; adrs?: string[] | null; registry?: string }) {
  const root = mkdtempSync(join(tmpdir(), 'crb-docs-'))
  made.push(root)
  mkdirSync(join(root, 'docs'))
  for (const g of opts.guides) writeFileSync(join(root, 'docs', `${g}.md`), `# ${g}\n`)
  if (opts.adrs !== null) {
    mkdirSync(join(root, 'docs', 'adr'))
    for (const a of opts.adrs ?? []) writeFileSync(join(root, 'docs', 'adr', a), '# ADR\n')
  }
  const registry = opts.registry ?? `export const DOC_NAMES = [${opts.names.map((n) => `'${n}'`).join(', ')}] as const\n`
  writeFileSync(join(root, 'docs.ts'), registry)
  return { docs: pathToFileURL(join(root, 'docs') + '/'), registry: pathToFileURL(join(root, 'docs.ts')) }
}

/** Runs `buildStart` as Rollup would: `this.error` throws. */
function build(where: { docs: URL; registry: URL }): void {
  const plugin = requireBundledDocs(where)
  const ctx = {
    error(message: string): never {
      throw new Error(message)
    },
  }
  ;(plugin.buildStart as (this: typeof ctx) => void).call(ctx)
}

describe('requireBundledDocs', () => {
  it('passes when every listed guide and a decision record are in the context', () => {
    expect(() => build(tree({ names: ['OPERATOR', 'SECURITY'], guides: ['OPERATOR', 'SECURITY'], adrs: ['0001-x.md'] }))).not.toThrow()
  })

  it('fails the build naming the guide that is missing', () => {
    expect(() => build(tree({ names: ['OPERATOR', 'SECURITY'], guides: ['OPERATOR'], adrs: ['0001-x.md'] }))).toThrow(/missing docs\/SECURITY\.md/)
  })

  it('fails the build when there is no decision record, or no docs/adr at all', () => {
    expect(() => build(tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: ['README.md'] }))).toThrow(/docs\/adr\/\*\.md/)
    expect(() => build(tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: null }))).toThrow(/docs\/adr\/\*\.md/)
  })

  it('fails the build when DOC_NAMES cannot be read, rather than checking nothing', () => {
    expect(() => build(tree({ names: [], guides: [], adrs: ['0001-x.md'], registry: 'export const GUIDES = []\n' }))).toThrow(/could not read DOC_NAMES/)
  })

  it('passes on this repository’s own docs (the defaults)', () => {
    const plugin = requireBundledDocs()
    expect(() => (plugin.buildStart as (this: { error: (m: string) => never }) => void).call({ error: (m) => { throw new Error(m) } })).not.toThrow()
  })

  it('is in the plugins the UI build runs with', async () => {
    const config = (await import('../vite.config')).default as { plugins?: unknown[] }
    const names = (config.plugins ?? []).flat(3).map((p) => (p as { name?: string } | null)?.name)
    expect(names).toContain('crb-require-bundled-docs')
  })
})
