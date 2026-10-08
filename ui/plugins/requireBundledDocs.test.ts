// @vitest-environment node
/**
 * requireBundledDocs — `vite build` refuses a context without the docs the UI bundles.
 *
 * Navigation
 * ----------
 * What it is:   Behavioural tests for the build plugin in ui/plugins/requireBundledDocs.ts, and
 *               for its wiring into ui/vite.config.ts.
 * What it does: Runs the plugin's `buildStart` against temporary docs directories and pins
 *               that it passes with every guide `DOC_NAMES` lists and every record
 *               `ADR_TITLES` lists, and fails naming what is missing when one guide is gone,
 *               when one listed record is gone though another is present (P-422), when
 *               docs/adr is empty or absent, and when `DOC_NAMES` or `ADR_TITLES` cannot be
 *               read; that it passes on this
 *               repository's own docs; and that the config vite builds with lists it — so the
 *               refusal P-173 relies on is proven by what it does, not by the words in the
 *               config (the grep this replaced survived its `if (false)` mutation).
 * How:          `mkdtempSync` trees; `buildStart` called with a `this` whose `error` throws, as
 *               Rollup's does; the config imported and its plugins' names read.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-073)
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

/**
 * A temporary tree: `docs/` with `guides` and `adrs`, a `docs.ts` declaring `names`, and an
 * `adrs.ts` declaring `adrNumbers` (by default the numbers of the `adrs` files, or `0001`).
 */
function tree(opts: { names: string[]; guides: string[]; adrs?: string[] | null; registry?: string; adrNumbers?: string[]; adrRegistry?: string }) {
  const root = mkdtempSync(join(tmpdir(), 'crb-docs-'))
  made.push(root)
  mkdirSync(join(root, 'docs'))
  for (const g of opts.guides) {
    if (g.includes('/')) mkdirSync(join(root, 'docs', g.split('/')[0]!), { recursive: true })
    writeFileSync(join(root, 'docs', `${g}.md`), `# ${g}\n`)
  }
  if (opts.adrs !== null) {
    mkdirSync(join(root, 'docs', 'adr'))
    for (const a of opts.adrs ?? []) writeFileSync(join(root, 'docs', 'adr', a), '# ADR\n')
  }
  const registry = opts.registry ?? `export const DOC_NAMES = [${opts.names.map((n) => `'${n}'`).join(', ')}] as const\n`
  writeFileSync(join(root, 'docs.ts'), registry)
  const fromFiles = (opts.adrs ?? []).map((a) => /^(\d{4})-/.exec(a)?.[1]).filter((n): n is string => Boolean(n))
  const numbers = opts.adrNumbers ?? (fromFiles.length ? fromFiles : ['0001'])
  const adrRegistry = opts.adrRegistry ?? `export const ADR_TITLES: ReadonlyArray<readonly [string, string]> = [\n${numbers.map((n) => `  ['${n}', 'Title ${n}'],`).join('\n')}\n]\n`
  writeFileSync(join(root, 'adrs.ts'), adrRegistry)
  return { docs: pathToFileURL(join(root, 'docs') + '/'), registry: pathToFileURL(join(root, 'docs.ts')), adrRegistry: pathToFileURL(join(root, 'adrs.ts')) }
}

/** Runs `buildStart` as Rollup would: `this.error` throws. */
function build(where: { docs: URL; registry: URL; adrRegistry: URL }): void {
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

  it('follows a guide kept below docs/ to its own path, and names that path when it is missing (G-481)', () => {
    const registry = "export const DOC_NAMES = ['OPERATOR', 'HUMAN-REVIEW-GUIDE'] as const\nconst NESTED: Partial<Record<DocName, string>> = { 'HUMAN-REVIEW-GUIDE': 'reviews/human-review-guide' }\n"
    const gone = tree({ names: [], guides: ['OPERATOR'], adrs: ['0001-x.md'], registry })
    expect(() => build(gone)).toThrow(/missing docs\/reviews\/human-review-guide\.md/)
    const here = tree({ names: [], guides: ['OPERATOR', 'reviews/human-review-guide'], adrs: ['0001-x.md'], registry })
    expect(() => build(here)).not.toThrow()
  })

  it('fails the build naming the guide that is missing', () => {
    expect(() => build(tree({ names: ['OPERATOR', 'SECURITY'], guides: ['OPERATOR'], adrs: ['0001-x.md'] }))).toThrow(/missing docs\/SECURITY\.md/)
  })

  it('fails the build when there is no decision record, or no docs/adr at all', () => {
    expect(() => build(tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: ['README.md'] }))).toThrow(/docs\/adr\/\*\.md/)
    expect(() => build(tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: null }))).toThrow(/docs\/adr\/\*\.md/)
  })

  it('fails the build naming every decision record /help lists that the context lacks, even when another is present (P-422)', () => {
    // one record present is not the list present: /help links every ADR_TITLES row, and a
    // row whose file the build cannot see is a link that fails to load
    const partial = tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: ['0001-x.md'], adrNumbers: ['0001', '0002', '0015'] })
    expect(() => build(partial)).toThrow(/missing docs\/adr\/0002-\*\.md, docs\/adr\/0015-\*\.md/)
    expect(() => build(tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: ['0001-x.md', '0002-y.md'], adrNumbers: ['0001', '0002'] }))).not.toThrow()
  })

  it('fails the build when ADR_TITLES cannot be read, rather than checking no record', () => {
    expect(() => build(tree({ names: ['OPERATOR'], guides: ['OPERATOR'], adrs: ['0001-x.md'], adrRegistry: 'export const RECORDS = []\n' }))).toThrow(/could not read ADR_TITLES/)
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
