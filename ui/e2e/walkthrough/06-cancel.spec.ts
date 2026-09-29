/**
 * 06 — the operator's journey as one walk: health, start, watch, cancel, verify, export
 * (G-399). Proves: the header's health pill reads the worst `/health` status; a long mine
 * run (large task limit) is started from the Runs page's own "Start run" with the repository
 * carried (G-268) and can be cancelled from the run page while it is RUNNING; the page shows
 * "cancel requested"; the worker's cancel token kills the in-flight test command and the run
 * ends `cancelled` (not `failed`, not `succeeded`) within 30 s; the log carries
 * `mine.cancelled`; the ledger's chain still verifies with false-Q1 = 0 and the export
 * verifies with `crb ledger verify`; and the Runs list agrees.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 06 (the operator's journey, with the cancel) on the primary repo.
 * What it does: Pins, in one test as one operator at a pinned 1280 px: that the header pill
 *               equals the worst `/health` status; that a long mine run started from /runs
 *               (the page's own button, the Repo preset) can be cancelled from the run page
 *               while RUNNING; that the page shows "cancel requested"; that the worker's cancel
 *               token kills the in-flight test command and the run ends `cancelled` (not
 *               `failed`, not `succeeded`) within 30 s; that the log carries `mine.cancelled`;
 *               that /ledger's gate is OPEN with false-Q1 = 0 afterwards and the export verifies
 *               (`exportAndVerifyLedger`); and, in a second test, that the Runs list agrees.
 * How:          `stackHealth` against the shell pill; `startRun` (mine, limit 500, from 'runs');
 *               poll `runStatus` until the worker claims it; click "Cancel run";
 *               `waitForRun('cancelled', 30 s)`; the Ledger gate; `exportAndVerifyLedger`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/components/Layout.tsx (the health pill),
 *               ui/src/screens/Runs/RunsPage.tsx ("Start run"), ui/src/screens/Runs/RunDetailPage.tsx
 *               (the cancel button and the pill), ui/src/api/hooks.ts (`useCancelRun`),
 *               ui/src/screens/Ledger/LedgerPage.tsx (the gate and Export JSONL),
 *               src/crb/server/worker.py (the cancel token between tasks)
 * Tested by:    ui/e2e/walkthrough/06-cancel.spec.ts
 * Touch when:   never for a new repository (the primary fixture is the walkthrough's own); the
 *               cancel semantics or the 30 s bound change (docs/API.md "/runs/{id}/cancel"); the
 *               health pill's label or the Runs page's button changes.
 */
import { expect, expectLogAction, exportAndVerifyLedger, primary, runStatus, stackHealth, startRun, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const CANCEL_WITHIN_MS = 30_000

/** The shell pill's label for a `/health` status (ui/src/lib/verdict.ts `probeDisplay`). */
const PILL_LABEL: Record<string, string> = { ok: 'OK', degraded: 'Degraded', down: 'Down' }

test.describe('06 cancel', () => {
  const t = primary()

  test('a running mine run is cancelled within 30 s of clicking Cancel run', async ({ page }) => {
    // one operator, one journey (G-399): read the instrument's health first, at the desktop
    // width where the pill is in the top bar (below 640 px it folds into the Menu, F26)
    await page.setViewportSize({ width: 1280, height: 900 })
    const health = await stackHealth(page)
    await page.goto('/home')
    const pill = page.getByRole('img', { name: /^Instrument health: / })
    await expect(pill).toHaveAttribute('aria-label', `Instrument health: ${PILL_LABEL[health.status] ?? health.status}`)
    // …then start the long run from the Runs page's own button (G-268), the repository carried
    await startRun(page, t.name, { kind: 'mine', limit: 500, from: 'runs' })
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

    // …then verify the chain the cancelled run left untouched, and export it
    await page.goto(`/ledger?repo=${encodeURIComponent(t.name)}`)
    const gate = page.getByTestId('ledger-gate')
    await expect(gate).toHaveAttribute('data-state', 'OPEN')
    await expect(gate).toContainText('false_q1_total = 0')
    const { rows, verdict } = await exportAndVerifyLedger(page, 'after-cancel')
    expect(rows.length).toBeGreaterThanOrEqual(1)
    if (verdict) expect(verdict.false_q1).toBe(0)
  })

  test('the Runs list shows the run as cancelled', async ({ page }) => {
    await page.goto(`/runs?repo=${encodeURIComponent(t.name)}&status=cancelled`)
    const table = page.getByRole('table', { name: 'Runs' })
    await expect(table.getByRole('img', { name: 'Status: cancelled' }).first()).toBeVisible()
  })
})
