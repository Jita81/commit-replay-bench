/**
 * ResultsPage — reading the Baseline costs nothing and says how long it takes (G-447).
 *
 * Navigation
 * ----------
 * What it is:   The time-and-cost guard on the Baseline screen (`/results`): the About block's
 *               copy and the page's own source.
 * What it does: Pins that the About block (the `/results` entry of the help registry, which the
 *               About panel renders) says reading the map costs £0 and how long a first reading
 *               takes, and marks the minutes as an estimate; and that the page offers no control
 *               that starts a run — neither `ResultsPage.tsx` nor `MapTable.tsx` names any hook
 *               in `api/hooks.ts` that posts a run, so "costs £0" stays true by construction.
 * How:          `HELP` read directly; the page, the map table and the hooks module read as
 *               `?raw` text; the run-creating hooks are found in the hooks source (every
 *               exported function whose body posts to `/runs` or a repository's `/probe`), so a
 *               hook added later is caught without editing this test.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/help.ts (the `/results` About copy), ui/src/screens/Results/
 *               ResultsPage.tsx and MapTable.tsx (the Baseline), ui/src/api/hooks.ts (the hooks
 *               that start a run), docs/ONBOARDING-A-REPO.md (Step 5 says the same, pinned by
 *               tests/test_onboarding_step_costs.py)
 * Tested by:    ui/src/screens/Results/ResultsPage.cost.test.tsx
 * Touch when:   never for a new repository; the Baseline gains an action (if it starts a run,
 *               Step 5 and the About block stop being £0 and must say what it costs).
 */
import { describe, expect, it } from 'vitest'
import hooksSource from '../../api/hooks.ts?raw'
import { HELP } from '../../help/help'
import mapTableSource from './MapTable.tsx?raw'
import resultsSource from './ResultsPage.tsx?raw'

/** Every exported hook in `api/hooks.ts` whose body posts a run: `POST /runs` or a repository's probe. */
function runCreatingHooks(): string[] {
  const out: string[] = []
  for (const part of hooksSource.split(/\nexport function /).slice(1)) {
    const name = /^(\w+)/.exec(part)?.[1] ?? ''
    const body = part.split(/\nexport /)[0] ?? ''
    if (/['`]\/runs['`],\s*\{\s*method:\s*'POST'/.test(body) || /\/probe`,\s*\{\s*method:\s*'POST'/.test(body)) out.push(name)
  }
  return out
}

describe('ResultsPage: time and cost (G-447)', () => {
  it('the Baseline About block says reading it costs nothing and how long a first reading takes', () => {
    const about = HELP.find((h) => h.route === '/results')
    expect(about).toBeDefined()
    const purpose = about!.purpose
    expect(purpose).toContain('costs £0')
    expect(purpose).toContain('calls no model and starts no run')
    expect(purpose).toMatch(/about ten minutes/)
    // the minutes are an estimate, and the copy says nobody has timed them
    expect(purpose).toContain('an estimate nobody has timed yet')
  })

  it('the Baseline offers no button that starts a run', () => {
    const hooks = runCreatingHooks()
    // the finder itself works: the three hooks that start a run today are found
    expect(hooks).toEqual(expect.arrayContaining(['useCreateRun', 'useQualifyRepo', 'useProbeRepo']))
    for (const [file, source] of [
      ['ResultsPage.tsx', resultsSource],
      ['MapTable.tsx', mapTableSource],
    ] as const) {
      for (const hook of hooks) expect(source, `${file} uses ${hook}, which starts a run`).not.toMatch(new RegExp(`\\b${hook}\\b`))
      expect(source, `${file} posts to /runs`).not.toMatch(/['`]\/runs['`],\s*\{\s*method:\s*'POST'/)
    }
  })
})
