/**
 * 06b — Home's task tags on the live stack, and the read that completes task 6.
 *
 * Home's task tags were proven on mocks alone (G-166), and task 6 "Read the baseline" completed
 * only on a sign-off, never on a read (G-165). This spec proves both on real data, and proves
 * the transition, not only its end state: it runs after 05 has given the primary repository
 * rows and before anything opens that repository's baseline (07 is the first spec that does,
 * and 08's sign-offs land on another repository) — so task 6 must read Incomplete first.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 06b (baseline read), tier 1 and tier 2 alike; it spends
 *               nothing, calls no model and writes nothing but a session and one
 *               `repo.baseline_read` event.
 * What it does: Reads Home's task tags for the repository 02–05 onboarded and measured —
 *               Choose a repository, Confirm its shape and Measure read Completed, and no
 *               read failed — then finds task 6 "Read the baseline" Incomplete (rows exist,
 *               nobody has read them, nobody has signed); opens the Baseline screen, which
 *               tells the server it was read (`POST /repos/{name}/baseline-read` answers 201
 *               with `recorded: true` — the first read by this person); and finds task 6
 *               Completed on that record (G-166, G-165, DL-075). Then it reads the Baseline's
 *               flow card for the measure stream (stream M, G-925): a measured lead time with
 *               its n and a spend that names the rows it covers. That check lived in 05 until
 *               the integration found it recorded the read before this spec could see it
 *               (P-180); tests/test_walkthrough_order.py now refuses a Baseline visit before 06b.
 * How:          support.ts's signed-in `test` (the bootstrap admin); `primary()`; the POST is
 *               awaited as the page's own response, never sent by the spec.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-075)
 * Works with:   ui/src/screens/Home/HomePage.tsx (the task list), ui/src/screens/Results/
 *               ResultsPage.tsx (the page that records the read), src/crb/server/routes/repos.py
 *               (`record_baseline_read`, `baseline_read` on the detail), ui/e2e/walkthrough/
 *               support.ts, ui/e2e/walkthrough/05-replay-fake.spec.ts (the rows it stands on),
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (the first later spec to open
 *               the baseline — this one must run before it), ui/src/components/FlowPanel.tsx
 * Tested by:    scripts/walkthrough.sh (CI job `walkthrough`)
 * Touch when:   never for a new repository; a task's derivation on Home changes, or a spec before
 *               07 starts opening the primary repository's baseline (then this spec's "Incomplete
 *               first" no longer holds and must move earlier).
 */
import { expect, primary, test } from './support'
import type { Locator, Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

/** A StatTile's headline value (label / value / dl). */
const tileValue = (tile: Locator) => tile.locator(':scope > div').nth(1)
/** A StatTile's n: the `dd` beside its `n =` term. */
const tileN = (tile: Locator) => tile.locator('dt', { hasText: /^n =$/ }).locator('xpath=following-sibling::dd[1]')

/** A task row of Home's list, by its number (1–8). */
function task(page: Page, n: number) {
  return page.getByRole('list', { name: 'Tasks' }).getByRole('listitem').nth(n - 1)
}

test.describe('06b baseline read', () => {
  test('Home’s task tags agree with the live stack, and reading the baseline completes task 6', async ({ page }) => {
    const repo = primary().name
    const home = `/home?repo=${encodeURIComponent(repo)}`

    // 02 onboarded and probed the repository; 05 replayed it, so its map has rows
    await page.goto(home)
    await expect(page.getByText(new RegExp(`^${repo} · measured$`))).toBeVisible()
    await expect(task(page, 2)).toContainText('Choose a repository')
    await expect(task(page, 2)).toContainText('Completed')
    await expect(task(page, 3)).toContainText('Completed')
    await expect(task(page, 5)).toContainText('Measure — spends money')
    await expect(task(page, 5)).toContainText('Completed')
    await expect(page.getByTestId('error-state')).toHaveCount(0)

    // before the read: rows exist, nobody has opened them and nobody has signed — Incomplete
    await expect(task(page, 6)).toContainText('Read the baseline')
    await expect(task(page, 6)).toContainText('Incomplete')

    // open the baseline: the Baseline screen tells the server it was read, for the first time (DL-075)
    const recorded = page.waitForResponse((r) => r.url().endsWith(`/api/v1/repos/${encodeURIComponent(repo)}/baseline-read`) && r.request().method() === 'POST')
    await page.goto(`/results?repo=${encodeURIComponent(repo)}`)
    const res = await recorded
    expect(res.status(), 'the first read of this baseline by this person is recorded').toBe(201)
    expect(((await res.json()) as { recorded: boolean }).recorded).toBe(true)

    // ... and Home's task 6 reads Completed on that record
    await page.goto(home)
    await expect(task(page, 6)).toContainText('Read the baseline')
    await expect(task(page, 6)).toContainText('Completed')
  })

  test('the Baseline carries the measure stream’s own flow: a lead time with its n, and a spend that says whether it is a floor', async ({ page }) => {
    await page.goto(`/results?repo=${encodeURIComponent(primary().name)}`)
    const card = page.locator('#flow-measure')
    await expect(card).toBeVisible()
    // the figures are a fold over records already kept, and the card says so
    await expect(card).toContainText('derived from the stored')
    // the run this spec queued was graded, so queued → graded is measured, not a dash
    const lead = page.getByTestId('flow-queued_to_graded')
    await expect(lead).toBeVisible()
    await expect(tileValue(lead)).not.toHaveText('—')
    // its n is the runs that graded a row — the same number the counts list beside it
    await expect(tileN(lead)).toHaveText(/^[1-9]\d*$/)
    const runsGraded = card.locator('dt', { hasText: /^runs graded$/ }).locator('xpath=following-sibling::dd[1]')
    expect(await tileN(lead).textContent()).toBe(await runsGraded.textContent())
    // the spend names which rows it covers and whether any reported no price: a sum with an
    // unpriced row says it is a floor; one without says every row was priced
    const spend = page.getByTestId('flow-spend-measure')
    await expect(spend).toContainText('the replay and blind attempts graded for this repository')
    await expect(spend).toContainText(
      /\d+ row\(s\) reported no price and are not counted as zero, so this is a floor\.|Every row counted here reported its own price\./,
    )
    // and the repository's cumulative spend, every graded row once, stands beside it (DL-067)
    await expect(page.getByTestId('flow-spend-total')).toContainText('every graded row counted once')
    // and the counts are counts: the rows this repository has graded
    await expect(card).toContainText('graded rows')
  })
})
