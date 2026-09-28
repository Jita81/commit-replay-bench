/**
 * 03 — mining. Proves, for every onboarded repo: "Start a run" (kind mine, task limit)
 * queues a run the worker executes to `succeeded`; the live log shows the miner's
 * RED / gold checks; the repo's Tasks tab then lists at least one replayable task
 * with its size, capability class and gold pill; and the Runs list shows the run.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 03 (mining), for every tier target.
 * What it does: Pins that "Start a run" (kind mine, a task limit) queues a run the worker
 *               executes to `succeeded`; that the live log shows `mine.task` and `mine.done`;
 *               that the progress bar reports found / target from the run's own counts; that
 *               the repo's Tasks tab lists at least one task with size, class and gold pill;
 *               that the mine run's duration, read from the API's own `started` / `finished`
 *               stamps, is attached to the test (G-430); and that the Runs list shows the run.
 * How:          `startRun` through the dialog; `waitForRun`; `expectLogAction`; the
 *               `progressbar` role's `aria-valuemax`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Runs/RunDetailPage.tsx and
 *               ui/src/screens/Repos/RepoDetail.tsx (the screens under test),
 *               ui/src/components/LiveLog.tsx (the log rows asserted), src/crb/core/mine.py
 *               (the miner whose events are asserted)
 * Tested by:    ui/e2e/walkthrough/03-mine.spec.ts
 * Touch when:   a new client repository is onboarded as a tier target (its mine limit and
 *               timeout live in ui/e2e/walkthrough/support.ts); a miner event is renamed or the
 *               Tasks tab columns change; the run API's `started` / `finished` stamps change
 *               (the mine run's timing, G-430).
 */
import { env, expect, expectLogAction, runIdFromUrl, startRun, targets, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

/**
 * G-430 — how long this run took, from the API's own `started` and `finished` stamps, attached
 * to the test as an annotation (and printed, so the walkthrough's output carries it). The same
 * stamps are what `GET /flow` folds into the connect stream's per-run median.
 */
async function timeRun(page: import('@playwright/test').Page, kind: string, timeoutMs: number): Promise<number> {
  const id = runIdFromUrl(page)
  const res = await page.request.get(`${env.baseUrl}/api/v1/runs/${id}`)
  expect(res.ok(), `GET /runs/${id} → ${res.status()}`).toBeTruthy()
  const run = (await res.json()) as { started: string | null; finished: string | null; apparatus_version: string }
  const seconds = (Date.parse(run.finished ?? '') - Date.parse(run.started ?? '')) / 1000
  expect(Number.isFinite(seconds) && seconds >= 0, `run ${id} has a readable started and finished stamp`).toBe(true)
  const description = `${seconds.toFixed(1)} s · run ${id} · apparatus ${run.apparatus_version} · method: finished − started from GET /runs/{id}`
  test.info().annotations.push({ type: `${kind}-run-duration`, description })
  console.log(`[G-430] ${kind} run: ${description}`)
  expect(seconds * 1000, `the ${kind} run stayed within the tier's timeout`).toBeLessThanOrEqual(timeoutMs)
  return seconds
}

for (const t of targets()) {
  test.describe(`mine ${t.name}`, () => {
    test(`Start run (mine, limit ${t.mineLimit}) succeeds`, async ({ page }) => {
      await startRun(page, t.name, { kind: 'mine', limit: t.mineLimit })
      await expect(page.getByText(`Runs · ${t.name} · mine`)).toBeVisible()
      await waitForRun(page, 'succeeded', t.mineTimeoutMs)
      await timeRun(page, 'mine', t.mineTimeoutMs)
      await expectLogAction(page, 'mine.task')
      await expectLogAction(page, 'mine.done')
      // the progress bar reports found/target from the run's own counts
      const bar = page.getByRole('progressbar').first()
      await expect(bar).toHaveAttribute('aria-valuemax', String(t.mineLimit))
      expect(Number(await bar.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(1)
    })

    test('the repo Tasks tab lists ≥1 task with size / class / gold pills', async ({ page }) => {
      await page.goto(`/repos/${encodeURIComponent(t.name)}`)
      // the overview tiles count the mined tasks
      await expect(page.getByText('Replayable tasks')).toBeVisible()
      await page.getByRole('tab', { name: 'Tasks' }).click()
      const table = page.getByRole('table', { name: `Mined tasks for ${t.name}` })
      await expect(table).toBeVisible()
      const rows = table.locator('tbody tr')
      await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)
      const first = rows.first()
      // size tier and class are the cell key the capability map is built on
      await expect(first.getByText(/^(XS|S|M|L|XL)$/)).toBeVisible()
      await expect(first.getByText(/^[a-z]+\.[a-z.]+$/)).toBeVisible()
      // gold: the commit's own patch was replayed and graded before the task was admitted
      await expect(first.getByRole('img', { name: /^Gold status: (clean|failed|unchecked)/ })).toBeVisible()
      // at least one task is gold-clean (only those are replayed)
      await expect(table.getByRole('img', { name: 'Gold status: clean' }).first()).toBeVisible()
    })

    test('the Runs page lists the mine run as succeeded', async ({ page }) => {
      await page.goto(`/runs?repo=${encodeURIComponent(t.name)}&kind=mine`)
      const table = page.getByRole('table', { name: 'Runs' })
      await expect(table.locator('tbody tr').first()).toBeVisible()
      await expect(table.getByRole('img', { name: 'Status: succeeded' }).first()).toBeVisible()
    })
  })
}
