/**
 * 09 — a human's verdict on an accepted patch has a place to live, and it is anchored
 * to the bytes the reviewer read (critical-friend review §5 plays 05/07, action #3).
 *
 *  - A replay run queued with `retain: {worktrees, transcripts}` (the switch shipped in
 *    655e732) leaves the graded worktree behind. The Evidence drawer's **Patch** tab
 *    fetches it as a unified diff computed on demand, hashes the served bytes in the
 *    browser and shows "hash matches pack" — the pack's `diff_sha256` is the anchor, the
 *    patch is never stored twice — with the file list and +/− counts that agree with the
 *    pack's own `diff` stats.
 *  - The **Review** panel stays disabled until that tab was loaded in this session; the
 *    reviewer picks a *Defect* finding with a note, says "not mergeable", writes the
 *    statement and records it. The POST carries the sha256 the browser computed; the
 *    server accepts it only because it equals the pack's anchor (a wrong hash is 422).
 *  - The reviews list shows the record; `GET /reviews` serves it hash-chained;
 *    `/reviews/verify` says the chain holds and every verdict is anchored; the cell's
 *    `n_reviewed` / `n_review_defects` go 0 → 1; the task page shows the verdict.
 *  - The Transcript tab reports honestly: the fixture builder writes no transcript.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 09 (review) — the retained patch, the browser-side hash and
 *               the review record, end to end on a live stack.
 * What it does: Pins that a replay queued with `retain: {worktrees, transcripts}` leaves the
 *               graded worktree behind; that the Evidence drawer's Patch tab fetches it as a
 *               unified diff computed on demand, hashes the served bytes in the browser and
 *               shows "hash matches pack" with file list and +/− counts that agree with the
 *               pack; that the Review panel stays disabled until that tab was loaded, then
 *               records a Defect finding with a note, "not mergeable" and a statement — the
 *               POST carrying the sha256 the browser computed, accepted only because it
 *               equals the pack's anchor; that `GET /reviews` serves it hash-chained and
 *               `/reviews/verify` says the chain holds and every verdict is anchored; that
 *               the cell's `n_reviewed` / `n_review_defects` go 0 → 1 and the task page shows
 *               the verdict; and that the Transcript tab reports honestly that the fixture
 *               builder writes none.
 * How:          `startRun` with retention on; the drawer's tabs by test id; the reviews API
 *               read directly for the chain assertions.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Runs/EvidenceDrawer.tsx,
 *               ui/src/screens/Runs/ReviewPanel.tsx and ui/src/screens/Runs/contract.ts (the
 *               code under test), ui/src/screens/Runs/TaskDetailPage.tsx (the verdict column),
 *               src/crb/server/routes/grades.py (the patch route) and
 *               src/crb/server/routes/reviews.py
 * Tested by:    ui/e2e/walkthrough/09-review.spec.ts
 * Touch when:   the patch headers, the review write boundary or the drawer's test ids change.
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { env, expect, primary, test } from './support'

test.describe.configure({ mode: 'serial' })

const MIN = 60_000

async function csrf(page: Page): Promise<Record<string, string>> {
  const cookie = (await page.context().cookies()).find((c) => c.name === 'crb_csrf')
  if (!cookie) throw new Error('no crb_csrf cookie — is the page signed in?')
  return { 'X-CSRF-Token': cookie.value }
}

async function apiPost(page: Page, path: string, data: unknown): Promise<Record<string, unknown>> {
  const res = await page.request.post(`${env.baseUrl}/api/v1${path}`, { data, headers: await csrf(page) })
  expect(res.status(), `POST ${path} → ${res.status()} ${await res.text()}`).toBeLessThan(300)
  return (await res.json()) as Record<string, unknown>
}

async function apiGet(req: APIRequestContext, path: string): Promise<Record<string, unknown>> {
  const res = await req.get(`${env.baseUrl}/api/v1${path}`)
  expect(res.ok(), `GET ${path} → ${res.status()}`).toBeTruthy()
  return (await res.json()) as Record<string, unknown>
}

async function waitRun(page: Page, runId: string, timeoutMs: number): Promise<void> {
  await expect
    .poll(async () => String((await apiGet(page.request, `/runs/${runId}`)).status), { timeout: timeoutMs, intervals: [500, 1000, 2000], message: `run ${runId} did not finish` })
    .toMatch(/^(succeeded|failed|cancelled)$/)
  const run = await apiGet(page.request, `/runs/${runId}`)
  expect(run.status, `run ${runId} ended ${run.status}: ${run.error ?? ''}`).toBe('succeeded')
}

interface Cell {
  capability_class: string
  size: string
  n_rows: number
  n_reviewed: number
  n_review_defects: number
}

async function cellStats(req: APIRequestContext, repo: string, cls: string, size: string): Promise<Cell> {
  const stats = await apiGet(req, `/reviews/stats?repo=${encodeURIComponent(repo)}&by=class,size`)
  const cell = (stats.cells as Cell[]).find((c) => c.capability_class === cls && c.size === size)
  expect(cell, `a review-stats cell for ${cls} × ${size} in ${JSON.stringify(stats)}`).toBeTruthy()
  return cell!
}

test.describe('09 human review of a retained patch', () => {
  const t = primary()
  let runId = ''
  let rowHash = ''
  let taskId = ''
  let diffSha = ''
  let cellClass = ''
  let cellSize = ''

  test('a replay run with retain.worktrees leaves the graded worktree behind', async ({ page }) => {
    test.setTimeout(8 * MIN)
    const run = await apiPost(page, '/runs', {
      repo: t.name,
      kind: 'replay',
      builder: 'fixture_gold',
      model: 'gold',
      limit: 1,
      retain: { worktrees: true, transcripts: true },
    })
    runId = String(run.id)
    expect((run.retain as Record<string, boolean>).worktrees).toBe(true)
    await waitRun(page, runId, 6 * MIN)
    const grades = await apiGet(page.request, `/grades?run_id=${runId}`)
    const items = grades.items as Array<Record<string, unknown>>
    expect(items.length).toBeGreaterThanOrEqual(1)
    const row = items.find((g) => g.clean === true) ?? items[0]!
    rowHash = String(row.row_hash)
    taskId = String(row.task_id)
    cellClass = String(row.capability_class)
    cellSize = String(row.size)
    const retained = await apiGet(page.request, `/grades/${rowHash}/retained`)
    expect(retained.retain_worktrees).toBe(true)
    expect(retained.patch_available, JSON.stringify(retained)).toBe(true)
    diffSha = String(retained.diff_sha256)
    expect(diffSha).toMatch(/^[0-9a-f]{64}$/)
    // nothing reviewed yet in this cell
    const before = await cellStats(page.request, t.name, cellClass, cellSize)
    expect(before.n_reviewed).toBe(0)
    expect(before.n_review_defects).toBe(0)
  })

  test('the Patch tab shows the diff and its hash matches the pack; the transcript reports honestly', async ({ page }) => {
    await page.goto(`/runs/${runId}`)
    const table = page.getByRole('table', { name: 'Per-task outcomes' })
    await table.locator('tbody tr').first().getByRole('button', { name: /^r1 / }).click()
    const drawer = page.getByTestId('evidence-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByTestId('pack-verified')).toBeVisible()
    await drawer.getByTestId('tab-patch').click()
    await expect(drawer.getByTestId('patch-verified')).toBeVisible()
    await expect(drawer.getByTestId('patch-mismatch')).toHaveCount(0)
    await expect(drawer.getByTestId('patch-warning')).toHaveCount(0)
    await expect(drawer.getByTestId('patch-counts')).toHaveAttribute('data-state', 'match')
    const files = drawer.getByTestId('patch-files').getByRole('listitem')
    await expect.poll(() => files.count()).toBeGreaterThanOrEqual(1)
    await expect(files.first()).toContainText(/\+\d+/)
    // the diff itself: a coloured added line from the fixture's own source
    const added = drawer.locator('[data-testid="patch-file"] [data-kind="add"]')
    await expect.poll(() => added.count()).toBeGreaterThanOrEqual(1)
    await expect(drawer).toContainText(`sha256 ${diffSha.slice(0, 16)}`)

    await drawer.getByTestId('tab-transcript').click()
    await expect(drawer.getByTestId('transcript-unavailable')).toContainText(/not retained|no longer exists/)
  })

  test('a Defect review is recorded against the row, anchored to the loaded patch', async ({ page }) => {
    await page.goto(`/runs/${runId}`)
    const table = page.getByRole('table', { name: 'Per-task outcomes' })
    await table.locator('tbody tr').first().getByRole('button', { name: /^r1 / }).click()
    const drawer = page.getByTestId('evidence-drawer')
    await drawer.getByTestId('tab-review').click()
    const submit = drawer.getByTestId('review-submit')
    await expect(submit).toBeDisabled()
    await expect(drawer.getByTestId('review-anchor')).toHaveAttribute('data-state', 'unanchored')
    await expect(drawer.getByTestId('reviews-empty')).toBeVisible()
    // the patch must be loaded in THIS session before a review can attest to it
    await drawer.getByRole('button', { name: 'Open the Patch tab' }).click()
    await expect(drawer.getByTestId('patch-verified')).toBeVisible()
    await drawer.getByTestId('tab-review').click()
    await expect(drawer.getByTestId('review-anchor')).toHaveAttribute('data-state', 'anchored')

    await drawer.getByTestId('finding-chip-defect').click()
    await expect(drawer.getByTestId('review-verdict-defect')).toBeVisible()
    await drawer.getByLabel(/Defect — note/).fill('walkthrough: the reproduced change omits the docstring the maintainer wrote')
    await drawer.getByLabel(/^File/).fill('src/calc/__init__.py')
    await drawer.getByLabel('Not mergeable').check()
    await drawer.getByLabel(/^Statement/).fill('walkthrough: read the whole diff against the pack hash; mechanically clean, not the PR a maintainer would merge as-is')
    await expect(submit).toBeEnabled()
    await submit.click()
    await expect(drawer.getByTestId('review-recorded')).toContainText('Recorded Defect')
    await expect(drawer.getByTestId('review-refused')).toHaveCount(0)
    const list = drawer.getByTestId('reviews-list')
    await expect(list.getByTestId('review-item')).toHaveCount(1)
    await expect(list.getByTestId('review-verdict-defect')).toBeVisible()
    await expect(list).toContainText('not mergeable')
    await expect(list).toContainText('omits the docstring')
    await expect(list).toContainText(`attested patch ${diffSha.slice(0, 16)}`)
  })

  test('the API serves the review hash-chained; verify holds; the cell counts it; the task page shows it', async ({ page }) => {
    const reviews = await apiGet(page.request, `/reviews?repo=${encodeURIComponent(t.name)}&grade_row_hash=${rowHash}`)
    expect(Number(reviews.total)).toBe(1)
    const r = (reviews.items as Array<Record<string, unknown>>)[0]!
    expect(r.verdict).toBe('defect')
    expect(r.mergeable).toBe(false)
    expect(r.patch_sha256_reviewed).toBe(diffSha)
    expect(r.grade_row_hash).toBe(rowHash)
    expect(String(r.row_hash)).toMatch(/^[0-9a-f]{64}$/)
    expect(String(r.prev_hash)).toMatch(/^[0-9a-f]{64}$/)
    expect((r.findings as Array<Record<string, unknown>>)[0]).toMatchObject({ kind: 'defect', file: 'src/calc/__init__.py' })

    const verify = await apiGet(page.request, '/reviews/verify')
    expect(verify.ok, JSON.stringify(verify)).toBe(true)
    expect(verify.chain_ok).toBe(true)
    expect(Number(verify.anchored)).toBeGreaterThanOrEqual(1)
    expect(Number(verify.unanchored)).toBe(0)

    const after = await cellStats(page.request, t.name, cellClass, cellSize)
    expect(after.n_reviewed).toBe(1)
    expect(after.n_review_defects).toBe(1)

    // a wrong hash is refused at write: nothing is recorded
    const res = await page.request.post(`${env.baseUrl}/api/v1/reviews`, {
      data: { grade_row_hash: rowHash, statement: 'walkthrough: wrong hash', findings: [], patch_sha256: 'f'.repeat(64) },
      headers: await csrf(page),
    })
    expect(res.status()).toBe(422)
    const body = (await res.json()) as { error: { code: string; detail: { code: string } } }
    expect(body.error.code).toBe('review_refused')
    expect(body.error.detail.code).toBe('patch_hash_mismatch')
    expect(Number((await apiGet(page.request, `/reviews?grade_row_hash=${rowHash}`)).total)).toBe(1)

    await page.goto(`/tasks/${encodeURIComponent(t.name)}/${taskId}`)
    const rows = page.getByRole('table', { name: 'Grade rows for this task' }).locator('tbody tr')
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)
    await expect(page.getByTestId('row-review').first()).toBeVisible()
    await expect(page.getByTestId('review-verdict-defect').first()).toBeVisible()
  })
})
