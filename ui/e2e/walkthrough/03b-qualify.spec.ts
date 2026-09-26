/**
 * 03b — qualify (ADR-0019). Proves, for every onboarded repo: the repository's Posture panel
 * offers the operator "Qualify for this posture — no model spend"; pressing it queues a
 * `qualify` run the worker executes to `succeeded` for $0 with `qualify.task` and
 * `qualify.done` in its log; and the panel then reads "N of M" with N ≥ 1.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 03b (qualify), for every tier target, after 03's mine.
 * What it does: Presses the Posture panel's Qualify button as the operator, follows the run to
 *               `succeeded`, asserts its log names the qualification events and that nothing was
 *               spent, and reads qualified N of M back on /repos/:name.
 * How:          The panel's button → the run page (`waitForRun`, `expectLogAction`) → back to
 *               the repository's Overview and the `stat.repo.qualified` tile.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0019-qualification-is-posture-relative.md
 * Works with:   ui/e2e/walkthrough/support.ts (the fixtures, targets and run helpers),
 *               ui/src/screens/Repos/PosturePanel.tsx (the panel under test),
 *               src/crb/server/worker.py (`_run_qualify`), src/crb/core/qualify.py
 *               (`qualify_task`, whose events are asserted)
 * Tested by:    ui/e2e/walkthrough/03b-qualify.spec.ts
 * Touch when:   the Posture panel's button or tile changes, or a qualify event is renamed.
 */
import { expect, expectLogAction, targets, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

for (const t of targets()) {
  test.describe(`qualify ${t.name}`, () => {
    test('Qualify for this posture — no model spend → succeeded, then N of M on the Posture panel', async ({ page }) => {
      await page.goto(`/repos/${encodeURIComponent(t.name)}`)
      await expect(page.getByRole('heading', { name: 'Posture' })).toBeVisible()
      await page.getByRole('button', { name: 'Qualify for this posture — no model spend' }).click()
      await page.waitForURL(/\/runs\/[0-9a-f]{32}/)
      await waitForRun(page, 'succeeded', t.mineTimeoutMs)
      await expectLogAction(page, 'qualify.task')
      await expectLogAction(page, 'qualify.done')
      await page.goto(`/repos/${encodeURIComponent(t.name)}`)
      const tile = page.locator('[data-hint="stat.repo.qualified"]')
      await expect(tile).toBeVisible()
      await expect.poll(async () => {
        const m = /(\d+) of (\d+)/.exec((await tile.textContent()) ?? '')
        return m ? Number(m[1]) : 0
      }).toBeGreaterThanOrEqual(1)
      await expect(page.getByTestId('posture-class')).not.toHaveText('none recorded')
    })
  })
}
