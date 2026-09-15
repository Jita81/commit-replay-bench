/**
 * 09 — the budget is a measured variable, not a fixed cap (C8; NHS review §3: 6 of 8
 * blind misses were `budget` at the fixed 25/25/900 — a blind rate quoted without its
 * budget tier is not a claim).
 *
 * The run dialog's preset **Blind budget sweep 25 → 50 → 100 tool calls** queues the SAME
 * builder + model as three object rungs `{builder, model, budget: {max_tool_calls: n}}`,
 * one attempt per rung until an attempt grades clean; the worker stamps every ledger row
 * with the tier it ran under (`labels.budget_tier`, `labels.rung_index`). Proves, from
 * the UI alone:
 *
 *  - the run header names the three declared rungs with their caps
 *    (`fixture_gold:gold [max_tool_calls=25],… [max_tool_calls=50],… [max_tool_calls=100]`);
 *  - the fixture is clean on rung 1, so every task has exactly ONE trial (`r1`) — the
 *    ladder climbs only on a red attempt, rungs 2 and 3 never run — clean 100 %, $0.00;
 *  - the run's Evidence drawer opens on the r1 attempt with the verified badge.
 *
 * Runs LAST: it adds rows to the primary repo's only cell, whose `n = 2` 05 and 08 assert
 * on (thin-cell refusal, observed 2 vs threshold 10). Tier 2 skips it — a real sweep spends
 * up to three rungs per task and is a deliberate, priced run, not a walkthrough side effect.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 09 (budget sweep), run LAST because it adds rows to the
 *               primary cell that 05 and 08 assert on (n = 2).
 * What it does: Pins, from the UI alone, that the run dialog's "Blind budget sweep 25 → 50 →
 *               100 tool calls" preset queues the SAME builder + model as three object rungs;
 *               that the run header names the three declared rungs with their caps; that the
 *               fixture is clean on rung 1 so every task has exactly ONE trial (the ladder
 *               climbs only on a red attempt) — clean 100 %, $0.00; and that the Evidence
 *               drawer opens on the r1 attempt with the verified badge. Tier 2 skips it (a
 *               real sweep spends money).
 * How:          `startRun` with the preset; `waitForRun`; assertions on the header's ladder
 *               text (`ladderEntryLabel`) and the task table.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Runs/RunNewDialog.tsx (the
 *               preset), ui/src/screens/Runs/RunDetailPage.tsx (the header and table),
 *               ui/src/api/types.ts (`ladderEntryLabel`), src/crb/server/worker.py (stamps
 *               `labels.budget_tier` per attempt)
 * Tested by:    ui/e2e/walkthrough/09-budget-sweep.spec.ts
 * Touch when:   the preset's caps or the rung label format change (docs/API.md "POST /runs:
 *               ladder", "The budget is a measured variable").
 */
import type { Locator } from '@playwright/test'
import { env, expect, expectLogAction, primary, startRun, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const REAL = env.builder === 'claude_code'
const BUILDER = 'fixture_gold'
const MODEL = 'gold'
const LIMIT = 2
const RUN_TIMEOUT_MS = 6 * 60_000
const SWEEP = [25, 50, 100] as const

/** A StatTile's headline value (label / value / dl). */
const tileValue = (tile: Locator) => tile.locator(':scope > div').nth(1)

test.describe('09 blind budget sweep (fixture_gold)', () => {
  const t = primary()
  let runId = ''

  test(`Start run (blind, preset 25 → 50 → 100 tool calls, ${BUILDER}:${MODEL}, limit ${LIMIT}) → three declared rungs`, async ({ page }) => {
    test.skip(REAL, 'a real blind budget sweep is a deliberate, priced run')
    runId = await startRun(page, t.name, { kind: 'blind', builder: BUILDER, model: MODEL, limit: LIMIT, blindSweep: true })
    await expect(page.getByText(`blind · ${BUILDER} · ${MODEL}`)).toBeVisible()
    await expect(page.getByText(/· ladder /)).toContainText(SWEEP.map((n) => `${BUILDER}:${MODEL} [max_tool_calls=${n}]`).join(','))
    await waitForRun(page, 'succeeded', RUN_TIMEOUT_MS)
    await expectLogAction(page, 'build.done')
    await expectLogAction(page, 'ledger.append')
    await expectLogAction(page, 'run.done')
    await expect(tileValue(page.getByTestId('tile-clean'))).toHaveText('100.0%')
    await expect(tileValue(page.getByTestId('tile-cost'))).toHaveText('$0.00')
  })

  test('clean on rung 1 → exactly one trial per task; rungs 2 and 3 never ran', async ({ page }) => {
    test.skip(REAL, 'a real blind budget sweep is a deliberate, priced run')
    await page.goto(`/runs/${runId}`)
    const rows = page.getByRole('table', { name: 'Per-task outcomes' }).locator('tbody tr')
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)
    // rows == tasks: the ladder declares three rungs but only r1 ever ran
    await expect(tileValue(page.getByTestId('tile-rows'))).toHaveText(String(await rows.count()))
    for (const row of await rows.all()) {
      await expect(row.locator('td').nth(3)).toHaveText('1') // Trials
      await expect(row.getByRole('button', { name: /^r1 [0-9a-f]{8}$/ })).toBeVisible()
    }
    await expect(page.getByRole('button', { name: /^r2 / })).toHaveCount(0)
    // the r1 attempt's evidence pack is there and verifies
    await rows.first().getByRole('button', { name: /^r1 / }).click()
    const drawer = page.getByTestId('evidence-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByTestId('pack-verified')).toBeVisible()
    await expect(drawer).toContainText(BUILDER)
    await drawer.getByRole('button', { name: 'Close' }).click()
  })
})
