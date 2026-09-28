/**
 * paged-reads — no screen or component lists repositories from the first page of `GET /repos`.
 *
 * Navigation
 * ----------
 * What it is:   A source ratchet over every screen and component (P-338).
 * What it does: Fails when any non-test source under ui/src/screens or ui/src/components calls
 *               `useRepos(` — the hook that reads one page of `GET /repos` (the server's default
 *               page size) — instead of `useAllRepos(`, which walks every page. A list or a picker
 *               built on the first page silently drops every repository past it: the Repos
 *               screen did (G-229), and so did the run dialog's repository select. The matcher
 *               is also pinned on its own strings, so the ratchet cannot pass by matching nothing.
 * How:          `import.meta.glob` over the sources as `?raw` text; a word-boundary regex.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useRepos`, `useAllRepos`, `fetchAllRepos`),
 *               ui/src/screens/Repos/ReposPage.tsx (the list that read one page, G-229),
 *               ui/src/screens/Runs/RunNewDialog.tsx (the select that did too),
 *               docs/PREVENTION.md (P-338)
 * Tested by:    ui/src/test/paged-reads.test.ts
 * Touch when:   never for a new repository; a new paged list hook is added (give it the same
 *               ratchet, or an all-pages twin).
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['../screens/**/*.tsx', '../screens/**/*.ts', '../components/**/*.tsx', '../components/**/*.ts', '!../**/*.test.ts', '!../**/*.test.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** Calls of the first-page hook (a comment naming it is not a call). */
function firstPageRepoReads(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
  return code.match(/\buseRepos\s*\(/g) ?? []
}

describe('paged reads (P-338)', () => {
  it('the matcher finds a call and ignores a comment and the all-pages hook', () => {
    expect(firstPageRepoReads('const repos = useRepos()')).toHaveLength(1)
    expect(firstPageRepoReads('const repos = useRepos ( )')).toHaveLength(1)
    expect(firstPageRepoReads('const repos = useAllRepos()')).toEqual([])
    expect(firstPageRepoReads('// useRepos() reads one page')).toEqual([])
    expect(firstPageRepoReads('/* useRepos() */ const a = 1')).toEqual([])
  })

  it('reads the screens and components it guards', () => {
    expect(Object.keys(SOURCES).some((p) => p.endsWith('/Repos/ReposPage.tsx'))).toBe(true)
    expect(Object.keys(SOURCES).some((p) => p.endsWith('/Runs/RunNewDialog.tsx'))).toBe(true)
    expect(Object.keys(SOURCES).some((p) => p.endsWith('.test.tsx'))).toBe(false)
  })

  it('no screen or component lists repositories from the first page only', () => {
    const offenders = Object.entries(SOURCES)
      .filter(([, src]) => firstPageRepoReads(src).length > 0)
      .map(([path]) => path)
    expect(offenders, 'use useAllRepos(): a first-page read drops every repository past the default page').toEqual([])
  })
})
