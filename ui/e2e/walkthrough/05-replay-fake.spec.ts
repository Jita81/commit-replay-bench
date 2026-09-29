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
 *    interval and the route `calibrate` — never a fabricated cell; under `routing.v2`
 *    (ADR-0025) the host-posture rows of a walkthrough license nothing, and the detail card
 *    says the cell's rows were not graded in the sealed posture;
 *  - the Sign-off page refuses to attest a thin cell: under `signoff-policy.v1` the
 *    server's preview lists the failing clauses (`thin_cell`, and the controls escape
 *    04's run found), the gate is CLOSED and the action stays disabled — 08 tells the
 *    whole sign-off story, including a cell that clears the policy.
 *  - Export JSONL downloads a file whose rows verify with `crb ledger verify --path`;
 *    Export CSV has `row_hash` and `builder` columns, and Export abstract carries no
 *    `fixture_gold` row and no key outside ADR-0007's allowlist.
 *  - The map is read through its own doors as one persona: Baseline → All decisions →
 *    Open the full map → Every route with its reason, one number per page equal to its API.
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
 * What it does: Pins that the money page's red button (/connect/:name/measure — the test-only
 *               fixture named test-only, priced at a known $0.00) queues the replay and the walk
 *               watches it; that the run grades clean with all four belts ✓ and cost $0; that
 *               the Evidence drawer opens with belts, apparatus and the `verified` badge;
 *               that the Ledger gate is OPEN with false-Q1 = 0 and rows listed; that the
 *               Capability page renders the (class × size) cell with n, Wilson interval and
 *               route `calibrate` (n < 10) — never a fabricated cell; that the Sign-off page
 *               refuses a thin cell with the clauses listed and the action disabled; and
 *               that the JSONL export verifies with `crb ledger verify --path`, the CSV has its
 *               columns and the abstract export carries no fixture row; and that the four
 *               map pages are walked through their doors with one number each equal to its
 *               API. Tier 2 with `CRB_E2E_BUILDER=claude_code` runs a REAL replay instead
 *               (through the dialog — the money page offers the deployment's credentialed
 *               builder, and tier 1 refuses to press the button when one is credentialed:
 *               nothing is spent by accident).
 * How:          The Measure page's red button (tier 1; `startRun` with `claude_code` in tier
 *               2); the walk's stage watched; `waitForRun`; then each screen in turn by its
 *               test ids; the exports downloaded and verified through the CLI named by
 *               `CRB_E2E_CRB` (`exportAndVerifyLedger`).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md,
 *               docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/e2e/walkthrough/support.ts, src/crb/builders/fixture_gold.py (the
 *               hermetic builder — registered only under `CRB_ENABLE_FIXTURE_BUILDER=1`),
 *               ui/src/screens/Runs/RunDetailPage.tsx, ui/src/screens/Runs/EvidenceDrawer.tsx,
 *               ui/src/screens/Ledger/LedgerPage.tsx, ui/src/screens/Capability/CapabilityPage.tsx,
 *               ui/src/screens/Signoff/SignoffPage.tsx, ui/src/screens/Connect/MeasurePage.tsx
 *               (the red button), ui/src/screens/Results/ResultsPage.tsx, ui/src/screens/Decisions/DecisionsPage.tsx,
 *               ui/src/screens/Routing/RoutingPage.tsx (the doors), src/crb/core/federated.py
 *               (the abstract allowlist the export test mirrors) — the screens under test; the
 *               Baseline's flow card is checked in 06b, after the read 06b must see first
 * Tested by:    ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   never for a new repository; a screen's test ids change, or the thin-cell refusal
 *               wording changes (08 asserts on the same cell's n).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { apiGet, env, expect, expectLogAction, exportAndVerifyLedger, field, primary, runIdFromUrl, stackHealth, startRun, test, waitForRun, workDir } from './support'

test.describe.configure({ mode: 'serial' })

const REAL = env.builder === 'claude_code'
const BUILDER = REAL ? 'claude_code' : 'fixture_gold'
const MODEL = REAL ? 'claude-sonnet-5' : 'gold'
const LIMIT = 2
const RUN_TIMEOUT_MS = REAL ? 25 * 60_000 : 6 * 60_000
const BELTS = ['tests_unmodified', 'target_green', 'no_new_failures', 'source_changed'] as const

/** A StatTile's headline value (label / value / dl). */
const tileValue = (tile: Locator) => tile.locator(':scope > div').nth(1)
/** A StatTile's `n =` reading (the first `dd` of its dl). */
const tileN = (tile: Locator) => tile.locator('dd').first()
/** A StatTile by its label text, for tiles that carry no test id. */
const tileLabelled = (page: Page, label: string) => page.locator('[data-component="stat-tile"]').filter({ has: page.locator('.label', { hasText: label }) })
/** A route tile on /results: fac's `tile-route-<route>` test id once it lands, else the StatTile whose label is the route. */
const routeTile = (page: Page, route: string) => page.getByTestId(`tile-route-${route}`).or(tileLabelled(page, route))

/** ADR-0007: the ONLY keys an abstract cell may carry (src/crb/core/federated.py `ABSTRACT_ALLOWLIST`). */
const ABSTRACT_ALLOWLIST = new Set(['process_step', 'capability_class', 'size', 'language', 'builder', 'model', 'provider', 'n', 'clean', 'false_q1', 'point', 'ci_low', 'ci_high', 'cost_usd_mean', 'latency_s_mean'])

test.describe(`05 replay (${BUILDER})`, () => {
  const t = primary()
  let runId = ''
  let cellN = 0 // the graded cell's n, read from the map; the sign-off test asserts the same number
  let cellClass = ''
  let cellSize = ''

  test('the red button on Measure queues the replay; the walk watches it; it succeeds with ledger rows', async ({ page }) => {
    if (REAL) {
      // tier 2: a real, priced replay is a deliberate act through the full form
      runId = await startRun(page, t.name, { kind: 'replay', builder: BUILDER, model: MODEL, limit: LIMIT, builderConfig: { auth: 'cli' } })
    } else {
      // tier 1 is hermetic: the money page must offer the test-only fixture and nothing else.
      // A stack that credentials a real builder (a key in the API's environment, a `claude`
      // on its PATH) would make the red button spend — refuse before pressing anything.
      const builders = (await stackHealth(page)).probes.find((p) => p.name === 'builders')
      expect(builders?.data.fixture_gold, 'tier 1 needs the test-only fixture registered (CRB_ENABLE_FIXTURE_BUILDER=1, CRB_ENV=dev)').toBe(true)
      for (const key of ['anthropic', 'openai', 'azure_openai', 'cerebras', 'claude_code_cli']) {
        expect(builders?.data[key], `tier 1 is hermetic: the stack credentials ${key}, so the money page would offer a real builder — nothing was pressed`).not.toBe(true)
      }
      await page.goto(`/connect/${encodeURIComponent(t.name)}/measure`)
      const box = page.getByTestId('before-you-start')
      await expect(box).toBeVisible()
      // the Builder row names the fixture for what it is, and the estimate is its known $0
      await expect(box).toContainText('fixture_gold · gold · test-only instrument check')
      await expect(box).toContainText('never a builder measurement')
      await expect(box).toContainText('$0.00 to $0.00')
      // the regex survives a cap or a limit phrase on the button (ns2-h)
      await page.getByRole('button', { name: /^Start the run — estimated/ }).click()
      // the walk resumes on the repository, watching the run it queued
      await page.waitForURL(new RegExp(`/connect/${t.name}$`))
      const stage = page.getByTestId('stage-measure')
      await expect(stage.getByRole('img', { name: /^First measurement: (Queued|In progress|Done)$/ })).toBeVisible()
      await expect
        .poll(async () => (await stage.getByRole('img', { name: /^First measurement: / }).getAttribute('aria-label')) ?? '', { timeout: RUN_TIMEOUT_MS, intervals: [500, 1000, 2000], message: 'the measure stage did not finish' })
        .toMatch(/: (Done|Failed)$/)
      await expect(stage.getByRole('img', { name: 'First measurement: Done' })).toBeVisible()
      // the stage's own door to the run: the rest of the spec reads that run
      await stage.getByRole('link', { name: 'open run' }).click()
      await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
      runId = runIdFromUrl(page)
    }
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
    // "<class> <size>: <route>, n <n>, point <pct>, 95% CI <lo> to <hi>, false-Q1 <n>, apparatus <v> · belts <set>,
    //  cost <value | not shown: reason>, latency <value | not shown: reason>"
    // — the whole claim travels in the accessible label (interval + provenance, batch 4; a dash's reason, F35)
    const m = /^([a-z.]+) (XS|S|M|L|XL): (\w+), n (\d+), point ([\d.]+%), 95% CI [\d.]+% to [\d.]+%, false-Q1 (\d+), apparatus \S+ · belts \S+, cost (\$[\d.]+|not shown: .+), latency ([\d.]+ ?\w+|not shown: .+)$/.exec(label)
    expect(m, `cell aria-label ${label}`).toBeTruthy()
    const n = Number(m![4])
    cellN = n
    expect(n).toBeGreaterThanOrEqual(1)
    expect(n).toBeLessThan(10)
    expect(m![3], 'host-posture rows with no registered reading route calibrate').toBe('calibrate')
    expect(m![6]).toBe('0')
    await expect(cell).toContainText(`n=${n}`)
    await expect(cell).toContainText(/\[\d+%, \d+%\]/) // the Wilson interval
    await expect(cell.getByRole('img', { name: /^Route: calibrate/ })).toBeVisible()
    // the detail card explains the route with its reason (routing.v2: the sealed posture
    // comes first — ADR-0025 row 3a) and the interval
    await cell.click()
    await expect(page.getByText(/were not graded in the sealed posture/).first()).toBeVisible()
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
    // the cell's own n (2 in tier 1, where both tasks share a cell; whatever the real mine
    // produced in tier 2 — the two graded tasks may land in different cells)
    await expect(page.getByTestId('signoff-refusals').getByTestId('refusal-thin_cell')).toContainText(`observed ${cellN}`)
    await expect(page.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    await expect(page.getByTestId('signoff-recorded')).toHaveCount(0)
    await expect(page.getByRole('table', { name: `Sign-offs for ${t.name}` })).toContainText('No attestations yet')
  })

  test('the map read through its doors: Baseline → All decisions → Open the full map → Every route with its reason', async ({ page }) => {
    const q = `repo=${encodeURIComponent(t.name)}`
    // what the API says, read once, so every number on every page is compared with its source
    const map = await apiGet(page.request, `/capability-map?${q}`)
    const controls = (await apiGet(page.request, `/oracle/${encodeURIComponent(t.name)}/controls`)) as { verdict: { state: string; escapes: number } }
    const oracle = (await apiGet(page.request, `/oracle/${encodeURIComponent(t.name)}`)) as { tasks: Array<{ strength: number | null }> }
    const routes = (await apiGet(page.request, `/routes?${q}`)) as { policy: { version: string }; decisions: Array<{ cell: Record<string, string>; route: string; reason_code?: string; policy_version: string; n: number }> }
    const summary = map.summary as { false_q1_total: number; n_total: number }
    const cells = map.cells as Array<{ capability_class: string; size: string; n: number; route: string }>
    const mapCell = cells.find((c) => c.capability_class === cellClass && c.size === cellSize)
    expect(mapCell, `the graded cell ${cellClass} × ${cellSize} on the map`).toBeTruthy()
    expect(mapCell!.n).toBe(cellN)
    const calibrate = cells.filter((c) => c.route === 'calibrate')
    expect(calibrate.length, 'the walkthrough grades on the host: every measured cell routes calibrate').toBeGreaterThanOrEqual(1)
    const calibrateN = calibrate.reduce((a, c) => a + c.n, 0)

    // door 0: the Baseline, from the walk's own button — the repository carried
    await page.goto(`/connect/${encodeURIComponent(t.name)}`)
    await page.getByRole('link', { name: 'Baseline' }).click()
    await page.waitForURL(new RegExp(`/results\\?${q}$`))
    // the gate tiles equal their APIs
    await expect(tileValue(page.getByTestId('tile-negative-controls'))).toHaveText(controls.verdict.state)
    await expect(page.getByTestId('tile-negative-controls')).toContainText(`${controls.verdict.escapes} escapes`)
    await expect(tileN(page.getByTestId('tile-oracle-strength'))).toHaveText(String(oracle.tasks.length))
    expect(summary.false_q1_total, 'false-Q1 is refused at write').toBe(0)
    await expect(tileValue(tileLabelled(page, 'False-Q1'))).toHaveText('0')
    // the calibrate route tile: its cells and its n are the map's
    const tile = routeTile(page, 'calibrate')
    await expect(tileValue(tile)).toHaveText(String(calibrate.length))
    await expect(tileN(tile)).toHaveText(String(calibrateN))
    // the decisions panel's count for this repository is carried to the next door
    const eyebrow = page.getByText(/^\d+ for this repository$/)
    await expect(eyebrow).toBeVisible()
    const waitingN = Number(/^(\d+) /.exec((await eyebrow.textContent()) ?? '')![1])

    // door 1: All decisions — the repository's own section, with the same count (or no section
    // when nothing waits on a person: a calibrate cell asks nobody to decide)
    await page.getByRole('link', { name: 'All decisions' }).click()
    await page.waitForURL(/\/decisions$/)
    await expect(page.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true')
    const section = page.getByRole('list', { name: `Decisions for ${t.name}` })
    if (waitingN > 0) {
      await expect(section).toBeVisible()
      await expect(section.locator(':scope > li')).toHaveCount(waitingN)
    } else {
      await expect(section).toHaveCount(0)
    }

    // door 2: Open the full map carries the repository; the cell's n is the map's
    await page.goto(`/results?${q}`)
    await page.getByRole('link', { name: 'Open the full map' }).click()
    await page.waitForURL(new RegExp(`/capability\\?${q}`))
    const cell = page.locator(`[data-testid="cell-measured"][aria-label^="${cellClass} ${cellSize}:"]`)
    await expect(cell).toContainText(`n=${mapCell!.n}`)

    // door 3: Every route with its reason carries the repository; the decision equals GET /routes
    await page.goto(`/results?${q}`)
    await page.getByRole('link', { name: 'Every route with its reason' }).click()
    await page.waitForURL(new RegExp(`/routing\\?${q}`))
    const decision = routes.decisions.find((d) => d.cell.capability_class === cellClass && d.cell.size === cellSize)
    expect(decision, `a route decision for ${cellClass} × ${cellSize}`).toBeTruthy()
    expect(decision!.route).toBe('calibrate')
    await expect(page.getByTestId('policy-rule')).toContainText(routes.policy.version)
    const table = page.getByRole('table', { name: `Route decisions for ${t.name}` })
    const row = table.locator('tbody tr').filter({ hasText: cellClass }).filter({ hasText: cellSize })
    await expect(row).toHaveCount(1)
    await expect(row.getByRole('img', { name: /^Route: calibrate/ })).toBeVisible()
    if (decision!.reason_code) await expect(row).toContainText(decision!.reason_code)
    await expect(row).toContainText(decision!.policy_version)
  })

  test('Export JSONL downloads the ledger and it verifies with `crb ledger verify`', async ({ page }) => {
    const { rows } = await exportAndVerifyLedger(page, runId.slice(0, 8))
    expect(rows.some((r) => r.builder === BUILDER)).toBeTruthy()
  })

  test('Export CSV and Export abstract download; the abstract carries no fixture row', async ({ page }) => {
    await page.goto('/ledger')
    const dir = workDir()
    // the CSV, by its accessible name: a header with the chain's key and the builder column
    const [csv] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export CSV' }).click()])
    expect(csv.suggestedFilename()).toMatch(/\.csv$/)
    const csvPath = join(dir, `ledger-${runId.slice(0, 8)}.csv`)
    await csv.saveAs(csvPath)
    const [header, ...body] = readFileSync(csvPath, 'utf8').split('\n').filter(Boolean)
    const columns = (header ?? '').split(',')
    expect(columns).toContain('row_hash')
    expect(columns).toContain('builder')
    expect(body.length).toBeGreaterThanOrEqual(1)
    // the abstract (ADR-0007): cells only, never a fixture row, never a key outside the allowlist
    const [abstract] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export abstract' }).click()])
    expect(abstract.suggestedFilename()).toMatch(/\.jsonl$/)
    const abstractPath = join(dir, `abstract-${runId.slice(0, 8)}.jsonl`)
    await abstract.saveAs(abstractPath)
    const cellsOut = readFileSync(abstractPath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l) as Record<string, unknown>)
    for (const c of cellsOut) {
      expect(c.builder, JSON.stringify(c)).not.toBe('fixture_gold')
      for (const key of Object.keys(c)) expect(ABSTRACT_ALLOWLIST.has(key), `abstract key ${key} is outside the ADR-0007 allowlist`).toBe(true)
    }
    // tier 1 has measured with the fixture and nothing else: the abstract is honestly empty
    if (!REAL) expect(cellsOut, 'no fixture row leaves the boundary').toEqual([])
  })
})
