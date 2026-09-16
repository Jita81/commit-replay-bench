/**
 * 05 — the whole pipeline, mine → build → grade → pack → ledger → map, driven from
 * the UI. Tier 1 replays with the test-only `fixture_gold` builder (it overlays the
 * commit's own source; registered only under CRB_ENABLE_FIXTURE_BUILDER=1, never in
 * production), so the run is hermetic and MUST grade clean. Proves:
 *
 *  - the run page lists the graded task(s) with all four belts ✓ and cost $0;
 *  - the Evidence drawer opens with the belts, the apparatus and the `verified` badge
 *    (the pack's canonical hash re-computed on read equals its key);
 *  - the Ledger page's chain gate is OPEN with false-Q1 = 0 and the rows are listed;
 *  - the Capability page renders the (class × size) cell with its n, its Wilson
 *    interval and the route `calibrate` (n < 10) — never a fabricated cell;
 *  - the Sign-off page refuses to attest a thin cell: under `signoff-policy.v1` the
 *    server's preview lists the failing clauses (`thin_cell`, and the controls escape
 *    04's run found), the gate is CLOSED and the action stays disabled — 08 tells the
 *    whole sign-off story, including a cell that clears the policy.
 *  - Export JSONL downloads a file whose rows verify with `crb ledger verify --path`.
 *
 * Tier 2 with CRB_E2E_BUILDER=claude_code (worker: CRB_CLAUDE_CODE_AUTH=cli) runs a
 * REAL replay (claude-sonnet-5, limit 2, {"auth":"cli"}) and asserts ≥1 ledger row
 * plus builder turns / tokens / cost > 0 on the evidence — not a clean grade, which
 * is the measurement, not a precondition.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 05 (replay with the test-only `fixture_gold` builder), the
 *               spine of the story.
 * What it does: Pins that a replay run grades clean with all four belts ✓ and cost $0; that
 *               the Evidence drawer opens with belts, apparatus and the `verified` badge;
 *               that the Ledger gate is OPEN with false-Q1 = 0 and rows listed; that the
 *               Capability page renders the (class × size) cell with n, Wilson interval and
 *               route `calibrate` (n < 10) — never a fabricated cell; that the Sign-off page
 *               refuses a thin cell with the clauses listed and the action disabled; and
 *               that the JSONL export verifies with `crb ledger verify --path`. Tier 2 with
 *               `CRB_E2E_BUILDER=claude_code` runs a REAL replay instead.
 * How:          `startRun` (kind replay, builder `fixture_gold`); `waitForRun`; then each
 *               screen in turn by its test ids; the export downloaded and verified through
 *               the CLI named by `CRB_E2E_CRB`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md,
 *               docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/e2e/walkthrough/support.ts, src/crb/builders/fixture_gold.py (the
 *               hermetic builder — registered only under `CRB_ENABLE_FIXTURE_BUILDER=1`),
 *               ui/src/screens/Runs/RunDetailPage.tsx, ui/src/screens/Runs/EvidenceDrawer.tsx,
 *               ui/src/screens/Ledger/LedgerPage.tsx, ui/src/screens/Capability/CapabilityPage.tsx,
 *               ui/src/screens/Signoff/SignoffPage.tsx (the screens under test)
 * Tested by:    ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   a screen's test ids change, or the thin-cell refusal wording changes (08
 *               asserts on the same cell's n = 2).
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Locator } from '@playwright/test'
import { env, expect, expectLogAction, field, primary, startRun, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const REAL = env.builder === 'claude_code'
const BUILDER = REAL ? 'claude_code' : 'fixture_gold'
const MODEL = REAL ? 'claude-sonnet-5' : 'gold'
const LIMIT = 2
const RUN_TIMEOUT_MS = REAL ? 25 * 60_000 : 6 * 60_000
const BELTS = ['tests_unmodified', 'target_green', 'no_new_failures', 'source_changed'] as const

/** A StatTile's headline value (label / value / dl). */
const tileValue = (tile: Locator) => tile.locator(':scope > div').nth(1)

test.describe(`05 replay (${BUILDER})`, () => {
  const t = primary()
  let runId = ''
  let cellClass = ''
  let cellSize = ''

  test(`Start run (replay, ${BUILDER}:${MODEL}, limit ${LIMIT}) → succeeded with ledger rows`, async ({ page }) => {
    runId = await startRun(page, t.name, {
      kind: 'replay',
      builder: BUILDER,
      model: MODEL,
      limit: LIMIT,
      ...(REAL ? { builderConfig: { auth: 'cli' } } : {}),
    })
    await expect(page.getByText(`sighted · ${BUILDER} · ${MODEL}`)).toBeVisible()
    await waitForRun(page, 'succeeded', RUN_TIMEOUT_MS)
    await expectLogAction(page, 'build.done')
    await expectLogAction(page, 'grade.belt')
    await expectLogAction(page, 'ledger.append')
    await expectLogAction(page, 'run.done')

    await expect(tileValue(page.getByTestId('tile-rows'))).toHaveText(/^[1-9]\d*$/)
    if (!REAL) {
      // the fixture reproduces the commit by construction: every task clean, nothing spent
      await expect(tileValue(page.getByTestId('tile-clean'))).toHaveText('100.0%')
      await expect(tileValue(page.getByTestId('tile-cost'))).toHaveText('$0.00')
    }
  })

  test('the run page lists the tasks with their belts and cost', async ({ page }) => {
    await page.goto(`/runs/${runId}`)
    const table = page.getByRole('table', { name: 'Per-task outcomes' })
    const rows = table.locator('tbody tr')
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)
    const first = rows.first()
    cellClass = (await first.locator('td').nth(1).textContent())?.trim() ?? ''
    cellSize = (await first.locator('td').nth(2).textContent())?.trim() ?? ''
    expect(cellClass).toMatch(/^[a-z]+\.[a-z.]+$/)
    expect(cellSize).toMatch(/^(XS|S|M|L|XL)$/)
    for (const belt of BELTS) {
      const pill = first.getByTestId(`belt-${belt}`)
      await expect(pill).toBeVisible()
      if (!REAL) await expect(pill, `belt ${belt} held`).toHaveAttribute('aria-label', /: held$/)
    }
    if (!REAL) {
      await expect(first.getByRole('img', { name: 'Clean: every recorded belt held' })).toBeVisible()
      await expect(first).toContainText('$0.00')
    }
    await expect(first.getByRole('button', { name: /^r1 [0-9a-f]{8}$/ })).toBeVisible()
  })

  test('the Evidence drawer shows belts, apparatus and the verified badge', async ({ page }) => {
    await page.goto(`/runs/${runId}`)
    const table = page.getByRole('table', { name: 'Per-task outcomes' })
    await table.locator('tbody tr').first().getByRole('button', { name: /^r1 / }).click()
    const drawer = page.getByTestId('evidence-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByRole('heading', { level: 2, name: /^Task / })).toBeVisible()
    await expect(drawer.getByTestId('pack-verified')).toBeVisible()
    await expect(drawer.getByTestId('pack-unverified')).toHaveCount(0)
    for (const belt of BELTS) await expect(drawer.getByTestId(`belt-${belt}`)).toBeVisible()
    await expect(drawer.getByRole('heading', { name: 'Apparatus' })).toBeVisible()
    await expect(drawer.getByTestId('provenance')).toContainText(/app \d+\.\d+/)
    await expect(drawer).toContainText('grader')
    await expect(drawer.getByRole('heading', { name: 'Builder' })).toBeVisible()
    await expect(drawer).toContainText(BUILDER)
    if (REAL) {
      // a real builder spends: turns, tokens and dollars are all > 0 on the pack
      const builder = drawer.locator('section', { hasText: 'attempts · turns' })
      const text = (await builder.textContent()) ?? ''
      const turns = /attempts · turns\s*\d+ · (\d+)/.exec(text)
      const tokens = /tokens in \/ out\s*([\d,]+) \/ ([\d,]+)/.exec(text)
      const cost = /cost\s*\$([\d.]+)/.exec(text)
      expect(Number(turns?.[1]), `turns in ${text}`).toBeGreaterThan(0)
      expect(Number(tokens?.[1]?.replace(/,/g, '')), `tokens in ${text}`).toBeGreaterThan(0)
      expect(Number(cost?.[1]), `cost in ${text}`).toBeGreaterThan(0)
    } else {
      await expect(drawer.getByRole('img', { name: 'Grade: clean — all four belts held' })).toBeVisible()
      await expect(drawer).toContainText('$0.00')
    }
    await drawer.getByRole('button', { name: 'Close' }).click()
    await expect(drawer).toHaveCount(0)
  })

  test('the Ledger page: chain verifies, false-Q1 = 0, the rows are listed', async ({ page }) => {
    await page.goto(`/ledger?repo=${encodeURIComponent(t.name)}`)
    const gate = page.getByTestId('ledger-gate')
    await expect(gate).toHaveAttribute('data-state', 'OPEN')
    await expect(gate).toContainText('Hash chain verifies')
    await expect(gate).toContainText('false_q1_total = 0')
    await expect(tileValue(page.getByTestId('tile-false-q1-total'))).toHaveText('0')
    const table = page.getByRole('table', { name: 'Ledger rows' })
    const rows = table.locator('tbody tr')
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)
    await expect(rows.first()).toContainText(BUILDER)
    if (!REAL) await expect(rows.first().getByRole('img', { name: 'Clean', exact: true })).toBeVisible()
  })

  test('the Capability page: the measured cell carries n, a Wilson interval and route calibrate', async ({ page }) => {
    await page.goto(`/capability?repo=${encodeURIComponent(t.name)}`)
    await expect(tileValue(page.getByTestId('tile-false-q1'))).toHaveText('0')
    await expect(page.getByTestId('false-q1-alert')).toHaveCount(0)
    await expect(page.getByTestId('cell-false-q1')).toHaveCount(0)
    // the cell of the task the run graded — by its (class × size) key, nothing else
    const cell = page.locator(`[data-testid="cell-measured"][aria-label^="${cellClass} ${cellSize}:"]`)
    await expect(cell, `a measured cell for ${cellClass} × ${cellSize}`).toBeVisible()
    const label = (await cell.getAttribute('aria-label')) ?? ''
    // "<class> <size>: <route>, n <n>, point <pct>, 95% CI <lo> to <hi>, false-Q1 <n>, apparatus <v> · belts <set>"
    // — the whole claim travels in the accessible label (interval + provenance, batch 4)
    const m = /^([a-z.]+) (XS|S|M|L|XL): (\w+), n (\d+), point ([\d.]+%), 95% CI [\d.]+% to [\d.]+%, false-Q1 (\d+), apparatus \S+ · belts \S+$/.exec(label)
    expect(m, `cell aria-label ${label}`).toBeTruthy()
    const n = Number(m![4])
    expect(n).toBeGreaterThanOrEqual(1)
    expect(n).toBeLessThan(10)
    expect(m![3], 'a cell with n < 10 routes to calibrate').toBe('calibrate')
    expect(m![6]).toBe('0')
    await expect(cell).toContainText(`n=${n}`)
    await expect(cell).toContainText(/\[\d+%, \d+%\]/) // the Wilson interval
    await expect(cell.getByRole('img', { name: /^Route: calibrate/ })).toBeVisible()
    // the detail card explains the route with its reason and the policy interval
    await cell.click()
    await expect(page.getByText(`n=${n} < 10`)).toBeVisible()
    await expect(page.getByText('Pass rate', { exact: true })).toBeVisible()
    await expect(page.getByText('Wilson 95%').first()).toBeVisible()
  })

  test('the Sign-off page refuses to attest the thin cell: the policy gate stays CLOSED', async ({ page }) => {
    await page.goto(`/signoff?repo=${encodeURIComponent(t.name)}`)
    const gate = page.getByTestId('signoff-gate')
    await expect(gate).toBeVisible()
    const select = field(page, 'Cell')
    // only MEASURED cells are offered — an unmeasured one cannot be chosen (the server would 409 it)
    await expect.poll(async () => (await select.locator('option').count()) - 1).toBeGreaterThanOrEqual(1)
    await select.selectOption({ value: `${cellClass}|${cellSize}` })
    await expect(gate).toContainText(`Attest ${cellClass} × ${cellSize}`)
    await field(page, 'Attestation statement').fill('walkthrough: attempting to sign off a thin cell')
    // n < 10 (and 04's controls escape): the server's preview refuses, the gate is CLOSED on
    // exactly those criteria, and the action is disabled — nothing is sent, nothing is recorded.
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    const row = (label: string | RegExp) => gate.getByRole('listitem').filter({ hasText: label })
    await expect(row('Cell is measured')).toContainText(/✓\s*satisfied:/)
    await expect(row('false-Q1 = 0')).toContainText(/✓\s*satisfied:/)
    await expect(row('n ≥ 10')).toContainText(/✗\s*not satisfied:/)
    await expect(row('Route = deliver')).toContainText(/✗\s*not satisfied:/)
    await expect(page.getByTestId('signoff-refusals').getByTestId('refusal-thin_cell')).toContainText('observed 2')
    await expect(page.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    await expect(page.getByTestId('signoff-recorded')).toHaveCount(0)
    await expect(page.getByRole('table', { name: `Sign-offs for ${t.name}` })).toContainText('No attestations yet')
  })

  test('Export JSONL downloads the ledger and it verifies with `crb ledger verify`', async ({ page }) => {
    await page.goto('/ledger')
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export JSONL' }).click()])
    expect(download.suggestedFilename()).toMatch(/\.jsonl$/)
    const dir = env.work && existsSync(env.work) ? env.work : mkdtempSync(join(tmpdir(), 'crb-walk-'))
    const path = join(dir, `ledger-${runId.slice(0, 8)}.jsonl`)
    await download.saveAs(path)

    const lines = readFileSync(path, 'utf8').split('\n').filter(Boolean)
    expect(lines.length).toBeGreaterThanOrEqual(1)
    const rows = lines.map((l) => JSON.parse(l) as Record<string, unknown>)
    for (const r of rows) {
      expect(String(r.row_hash)).toMatch(/^[0-9a-f]{64}$/)
      expect(typeof r.prev_hash).toBe('string')
    }
    expect(rows.some((r) => r.builder === BUILDER)).toBeTruthy()

    if (env.crb && existsSync(env.crb)) {
      const out = execFileSync(env.crb, ['ledger', 'verify', '--path', path, '--json'], { encoding: 'utf8' })
      const verdict = JSON.parse(out) as { ok: boolean; rows: number; false_q1: number; chain_ok: boolean }
      expect(verdict.ok, out).toBe(true)
      expect(verdict.chain_ok, out).toBe(true)
      expect(verdict.false_q1, out).toBe(0)
      expect(verdict.rows).toBe(rows.length)
    } else {
      test.info().annotations.push({ type: 'note', description: 'CRB_E2E_CRB not set: chain checked by row_hash presence + row count only' })
    }
  })
})
