/**
 * failed-reads — no screen or component shows a query's fallback while that query has failed.
 *
 * Navigation
 * ----------
 * What it is:   A source ratchet over every screen and component (P-341, G-730).
 * What it does: Fails when a non-test source under ui/src/screens or ui/src/components reads a
 *               query's `data` through a fallback (`q.data ?? …`) or into a derived value
 *               (`q.data?.…`) and never reads that query's failure (`q.isError`, `q.error`), hands
 *               it to a `QueryBoundary` (`query={q}`), or passes it to `failedRead(…)` (the
 *               Connect walk's check of its three stage reads). Such a read shows the fallback
 *               as the answer when the read fails: the Connect row and walk showed "Not started"
 *               and offered a paid Measure, and the Measure page priced a run from the documented
 *               range, each while the read behind it was down. The sources that did this before
 *               the ratchet are listed in `NOT_YET_READ`, and a match that is not a query at all
 *               in `NOT_A_QUERY` with why — lists that only shrink: an entry that no longer
 *               offends must be removed, and a new offender fails. The matcher is
 *               pinned on its own strings, so the ratchet cannot pass by matching nothing.
 * How:          `import.meta.glob` over the sources as `?raw` text; comments stripped; one regex
 *               for the reads and one per way of reading the failure.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/QueryBoundary.tsx (one way a read's failure is answered),
 *               ui/src/components/ErrorState.tsx (how a failed read is said, with Retry),
 *               ui/src/screens/Connect/ConnectPage.tsx (`failedRead`, G-124 and the walk),
 *               ui/src/screens/Connect/MeasurePage.tsx (G-108), docs/PREVENTION.md (P-341)
 * Tested by:    ui/src/test/failed-reads.test.ts
 * Touch when:   never for a new repository; a new way of answering a failed read is added (teach
 *               `answered` it, with a pinned string); an entry of `NOT_YET_READ` is fixed (remove
 *               it).
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['../screens/**/*.tsx', '../screens/**/*.ts', '../components/**/*.tsx', '../components/**/*.ts', '!../**/*.test.ts', '!../**/*.test.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/**
 * The reads the ratchet found when it was built (2026-09-28), each a query whose fallback or
 * derived value may stand in for a failed read. Not yet read one by one (G-732): each is fixed
 * with its failure branch, or shown to be honest and moved to a named exemption. Only shrinks.
 */
const NOT_YET_READ: ReadonlySet<string> = new Set([
  'components/Layout.tsx::health',
  'components/RepoPicker.tsx::repos',
  'screens/Connect/ConnectPage.tsx::gh',
  'screens/Connect/ConnectPage.tsx::watched',
  'screens/Connect/MeasurePage.tsx::active',
  'screens/Connect/MeasurePage.tsx::health',
  'screens/Decisions/useDecisionCount.ts::v',
  'screens/Factory/FactoryPage.tsx::map',
  'screens/Factory/FactoryPage.tsx::runs',
  'screens/Posture/PosturePage.tsx::version',
  'screens/Runs/EvidenceDrawer.tsx::reviews',
  'screens/Runs/EvidenceDrawer.tsx::task',
  'screens/Runs/RunNewDialog.tsx::repos',
  'screens/Runs/RunNewDialog.tsx::settings',
  'screens/Runs/TaskDetailPage.tsx::reviews',
  'screens/Settings/ClaudeCodeLoginCard.tsx::session',
  'screens/Signoff/SignoffPage.tsx::evidence',
  'screens/Signoff/SignoffPage.tsx::map',
])

/** Matches that are not a query's read at all, each with why. Only shrinks. */
const NOT_A_QUERY: ReadonlyMap<string, string> = new Map([
  ['screens/Connect/MeasurePage.tsx::sandbox', 'a `/health` probe object (`health.data?.probes.find(…)`), whose own `data` is the probe payload; the `health` read it comes from is listed above'],
])

/** The queries a source reads through a fallback or into a derived value and never answers when they fail. */
export function unansweredReads(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
  const names = new Set([...code.matchAll(/\b([A-Za-z_$][\w$]*)\.data\s*(?:\?\?|\?\.)/g)].map((m) => m[1]!))
  const passedToFailedRead = new Set(
    [...code.matchAll(/\bfailedRead\s*\(([^)]*)\)/g)].flatMap((m) => m[1]!.split(',').map((a) => a.trim())),
  )
  const answered = (n: string) =>
    new RegExp(`\\b${n}\\.(?:isError|error)\\b`).test(code) || new RegExp(`query=\\{\\s*${n}\\s*\\}`).test(code) || passedToFailedRead.has(n)
  return [...names].filter((n) => !answered(n)).sort()
}

const key = (path: string, name: string) => `${path.replace(/^\.\.\//, '')}::${name}`

describe('failed reads (P-341, G-730)', () => {
  it('the matcher finds a fallback read and a derived read, and each way of answering a failure', () => {
    expect(unansweredReads('const n = map.data?.summary.n_total')).toEqual(['map'])
    expect(unansweredReads('const a = oracle.data ?? null')).toEqual(['oracle'])
    expect(unansweredReads('const a = oracle.data ?? null; if (oracle.isError) return <E />')).toEqual([])
    expect(unansweredReads('const a = q.data?.x; <ErrorState error={q.error} />')).toEqual([])
    expect(unansweredReads('const a = q.data?.x; <QueryBoundary query={q}>')).toEqual([])
    expect(unansweredReads('const n = map.data?.n; const f = failedRead(oracle, controls, map)')).toEqual([])
    expect(unansweredReads('// map.data ?? 0 in a comment')).toEqual([])
    expect(unansweredReads('const v = q.data; if (!v) return null')).toEqual([])
  })

  it('reads the screens and components it guards', () => {
    expect(Object.keys(SOURCES).some((p) => p.endsWith('/Connect/ConnectPage.tsx'))).toBe(true)
    expect(Object.keys(SOURCES).some((p) => p.endsWith('/Connect/MeasurePage.tsx'))).toBe(true)
    expect(Object.keys(SOURCES).some((p) => p.endsWith('.test.tsx'))).toBe(false)
  })

  it('no screen or component shows a fallback for a read that failed, beyond the reads not yet read (a list that only shrinks)', () => {
    const offenders = Object.entries(SOURCES).flatMap(([path, src]) => unansweredReads(src).map((n) => key(path, n)))
    expect(
      offenders.filter((o) => !NOT_YET_READ.has(o) && !NOT_A_QUERY.has(o)),
      'answer the failed read (an isError branch, QueryBoundary or failedRead) before showing its fallback',
    ).toEqual([])
    expect(
      [...NOT_YET_READ, ...NOT_A_QUERY.keys()].filter((o) => !offenders.includes(o)),
      'this read no longer offends: remove it from its list',
    ).toEqual([])
  })
})
