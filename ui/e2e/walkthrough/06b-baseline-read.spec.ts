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
 *               Completed on that record (G-166, G-165, DL-074).
 * How:          support.ts's signed-in `test` (the bootstrap admin); `primary()`; the POST is
 *               awaited as the page's own response, never sent by the spec.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-074)
 * Works with:   ui/src/screens/Home/HomePage.tsx (the task list), ui/src/screens/Results/
 *               ResultsPage.tsx (the page that records the read), src/crb/server/routes/repos.py
 *               (`record_baseline_read`, `baseline_read` on the detail), ui/e2e/walkthrough/
 *               support.ts, ui/e2e/walkthrough/05-replay-fake.spec.ts (the rows it stands on),
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (the first later spec to open
 *               the baseline — this one must run before it)
 * Tested by:    scripts/walkthrough.sh (CI job `walkthrough`)
 * Touch when:   a task's derivation on Home changes, or a spec before 07 starts opening the
 *               primary repository's baseline (then this spec's "Incomplete first" no longer
 *               holds and must move earlier).
 */
import { expect, primary, test } from './support'
import type { Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

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

    // open the baseline: the Baseline screen tells the server it was read, for the first time (DL-074)
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
})
