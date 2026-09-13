import { expect, expectLogAction, startRun, targets, test, waitForRun } from './support'

/**
 * 03 — mining. Proves, for every onboarded repo: "Start a run" (kind mine, task limit)
 * queues a run the worker executes to `succeeded`; the live log shows the miner's
 * RED / gold checks; the repo's Tasks tab then lists at least one replayable task
 * with its size, capability class and gold pill; and the Runs list shows the run.
 */
test.describe.configure({ mode: 'serial' })

for (const t of targets()) {
  test.describe(`mine ${t.name}`, () => {
    test(`Start run (mine, limit ${t.mineLimit}) succeeds`, async ({ page }) => {
      await startRun(page, t.name, { kind: 'mine', limit: t.mineLimit })
      await expect(page.getByText(`Runs · ${t.name} · mine`)).toBeVisible()
      await waitForRun(page, 'succeeded', t.mineTimeoutMs)
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
