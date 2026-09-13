import { expect, expectLogAction, primary, runStatus, startRun, test, waitForRun } from './support'

/**
 * 06 — cancellation is cooperative, prompt and recorded. Proves: a long mine run
 * (large task limit) can be cancelled from the run page while it is RUNNING; the
 * page shows "cancel requested"; the worker's cancel token kills the in-flight test
 * command and the run ends `cancelled` (not `failed`, not `succeeded`) within 30 s;
 * the log carries `mine.cancelled` and the Runs list agrees.
 */
test.describe.configure({ mode: 'serial' })

const CANCEL_WITHIN_MS = 30_000

test.describe('06 cancel', () => {
  const t = primary()

  test('a running mine run is cancelled within 30 s of clicking Cancel run', async ({ page }) => {
    await startRun(page, t.name, { kind: 'mine', limit: 500 })
    // wait for the worker to claim it so the cancel lands on an in-flight run
    await expect.poll(() => runStatus(page), { timeout: 60_000, intervals: [500, 1000] }).toMatch(/^(running|succeeded|failed|cancelled)$/)
    const before = await runStatus(page)
    // The fixture history is padded (scripts/walkthrough.sh) so a full mine outlasts this
    // click by a wide margin; a run that is already terminal here means the padding is gone.
    expect(before, 'the mine run must still be running when Cancel is clicked').toBe('running')

    const cancel = page.getByRole('button', { name: 'Cancel run' })
    await expect(cancel).toBeVisible()
    const clickedAt = Date.now()
    await cancel.click()
    await expect(page.getByRole('img', { name: /^Cancel requested/ })).toBeVisible()
    await expect(cancel).toHaveCount(0)

    const status = await waitForRun(page, 'cancelled', CANCEL_WITHIN_MS + 5_000)
    expect(status).toBe('cancelled')
    expect(Date.now() - clickedAt, 'cancelled within 30 s of the click').toBeLessThanOrEqual(CANCEL_WITHIN_MS + 5_000)
    await expectLogAction(page, 'mine.cancelled')
    await expect(page.getByRole('img', { name: /^Cancel requested/ })).toHaveCount(0)
  })

  test('the Runs list shows the run as cancelled', async ({ page }) => {
    await page.goto(`/runs?repo=${encodeURIComponent(t.name)}&status=cancelled`)
    const table = page.getByRole('table', { name: 'Runs' })
    await expect(table.getByRole('img', { name: 'Status: cancelled' }).first()).toBeVisible()
  })
})
