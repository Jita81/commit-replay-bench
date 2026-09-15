/**
 * 08 — a sign-off is a policy decision, refused at write (`signoff-policy.v2`).
 *
 *  - The primary repo's only measured cell (n = 2 from 05) is REFUSED, and the reason is
 *    visible before the approver tries: the Sign-off page's preview lists every failing
 *    clause with *observed vs threshold* — `thin_cell` (2 vs 10), `controls_escapes`
 *    (1 vs 0), `route_not_deliver:n_below_min`, `attestation_missing` — the gate is
 *    CLOSED and the action disabled; nothing is recorded. The escape is a REAL finding
 *    of 04's controls run, not a mock: the tier-1 fixture's tests are literal asserts
 *    (`assert opN(1, 2) == 3 + N`), so the `hardcode_cheat` control grades clean on
 *    them — the oracle cannot tell an implementation from a lookup table.
 *  - A cell that satisfies the policy is SEEDED THROUGH THE API (`server_seed.py` is a
 *    pytest fixture and is not touched): a second fixture repo whose tests are
 *    PARAMETRISED (no literal fact to special-case → the cheat is not constructible →
 *    0 escapes) is built here, served as a bare file:// clone, onboarded, probed, mined,
 *    put through a controls run, an ORACLE run (`signoff-policy.v2`: the cell's oracle
 *    strength must be MEASURED on its tasks — an unscored cell is `oracle_unmeasured`,
 *    a refusal no deployment knob can waive; the parametrised tests kill every
 *    arithmetic/return mutant, so the cell scores ≥ 0.80) and replayed with
 *    `fixture_gold` — 18 clean rows in one cell → point 100 %, Wilson lower 80.6 % ≥
 *    80 % → route `deliver`. The approver picks the cell, names an accepted row, ticks
 *    "I have read this accepted diff", writes the statement, signs — and the record
 *    lists the snapshot (n, point, lower, false-Q1, oracle, policy, route, controls k of
 *    N / escapes / run, the attested row).
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 08 (sign-off), the only spec that also seeds through the API.
 * What it does: Pins that the primary repo's only measured cell (n = 2 from 05) is REFUSED with
 *               every failing clause visible before the approver tries — `thin_cell` (2 vs
 *               10), the real `controls_escapes` 04 found (the fixture's literal asserts let
 *               the hardcode-cheat control grade clean), `route_not_deliver`,
 *               `attestation_missing` — gate CLOSED, action disabled, nothing recorded; and
 *               that a second fixture repo with PARAMETRISED tests (the cheat is not
 *               constructible → 0 escapes; its oracle scores ≥ 0.80 once measured), built
 *               and served as a bare file:// clone, onboarded, probed, mined, put through
 *               controls, an oracle run and 18 clean `fixture_gold` replays, routes
 *               `deliver` — and the approver signs it through the UI, the record carrying
 *               the whole snapshot.
 * How:          Seeding goes through `POST /repos` / `POST /runs` with the CSRF header (the
 *               pytest seed fixture is not touched); the sign-off itself is driven through
 *               the form (`attest-row`, `attest-read`, `attest-statement`, `signoff-recorded`).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Signoff/SignoffPage.tsx and
 *               ui/src/screens/Signoff/contract.ts (the screen under test),
 *               src/crb/core/signoff.py (the clauses asserted), src/crb/server/routes/signoffs.py,
 *               src/crb/builders/fixture_gold.py (the clean rows),
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts
 *               (whose n = 2 cell this spec relies on)
 * Tested by:    ui/e2e/walkthrough/08-signoff.spec.ts
 * Touch when:   a refusal clause or a policy default changes (src/crb/core/signoff.py) — the
 *               expected clause list and the 18-row seed must follow.
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { APIRequestContext, Locator, Page } from '@playwright/test'
import { env, expect, field, primary, test } from './support'

test.describe.configure({ mode: 'serial' })

const SIGNABLE_NAME = 'walk-signable'
const N_TASKS = 18 // 16 clean rows already clear Wilson lower ≥ 0.80; two spare
const MIN = 60_000

/** The CSRF header the API requires on writes (double-submit cookie `crb_csrf`). */
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

/** Poll the run until terminal; assert it succeeded. */
async function waitRun(page: Page, runId: string, timeoutMs: number): Promise<void> {
  await expect
    .poll(async () => String((await apiGet(page.request, `/runs/${runId}`)).status), { timeout: timeoutMs, intervals: [500, 1000, 2000], message: `run ${runId} did not finish` })
    .toMatch(/^(succeeded|failed|cancelled)$/)
  const run = await apiGet(page.request, `/runs/${runId}`)
  expect(run.status, `run ${runId} (${run.kind}) ended ${run.status}: ${run.error ?? ''}`).toBe('succeeded')
}

async function startRunApi(page: Page, body: Record<string, unknown>, timeoutMs: number): Promise<string> {
  const run = await apiPost(page, '/runs', body)
  const id = String(run.id)
  await waitRun(page, id, timeoutMs)
  return id
}

/**
 * A calculator repo whose per-commit tests are parametrised — the negative control
 * `hardcode_cheat` needs a literal `assert f(<literals>) == <literal>` to special-case
 * and finds none, so it is `not_constructible` rather than an escape. Every commit is
 * RED at its parent (the module does not exist) and GREEN with its own source.
 */
function buildSignableRepo(): string {
  const dir = env.work && existsSync(env.work) ? env.work : mkdtempSync(join(tmpdir(), 'crb-walk-'))
  const src = join(dir, 'signable-src')
  const bare = join(dir, 'signable.git')
  const git = (...args: string[]) => execFileSync('git', ['-C', src, '-c', 'user.name=Fixture Bot', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', ...args], { stdio: 'pipe' })
  mkdirSync(join(src, 'src', 'calc'), { recursive: true })
  mkdirSync(join(src, 'tests'), { recursive: true })
  execFileSync('git', ['init', '-q', '-b', 'main', src], { stdio: 'pipe' })
  writeFileSync(join(src, 'pytest.ini'), '[pytest]\ntestpaths = tests\n')
  writeFileSync(join(src, 'src', 'calc', '__init__.py'), '"""A tiny calculator."""\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n')
  writeFileSync(join(src, 'tests', 'test_calc.py'), 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n')
  git('add', '-A')
  git('commit', '-q', '-m', 'chore: scaffold calc')
  for (let i = 0; i < N_TASKS; i += 1) {
    writeFileSync(join(src, 'src', 'calc', `op${i}.py`), `def op${i}(a: int, b: int) -> int:\n    return a + b + ${i}\n`)
    writeFileSync(
      join(src, 'tests', `test_op${i}.py`),
      `import pytest\n\nfrom calc.op${i} import op${i}\n\n\n@pytest.mark.parametrize("a,b", [(1, 2), (3, 4), (-1, 1)])\ndef test_op${i}(a, b):\n    assert op${i}(a, b) == a + b + ${i}\n`,
    )
    git('add', '-A')
    git('commit', '-q', '-m', `feat: add op${i}`)
  }
  execFileSync('git', ['clone', '-q', '--bare', src, bare], { stdio: 'pipe' })
  return `file://${bare}`
}

const gateRow = (gate: Locator, label: string | RegExp) => gate.getByRole('listitem').filter({ hasText: label })

test.describe('08 sign-off policy', () => {
  const t = primary()
  let signableClass = ''
  let signableSize = ''
  let signableN = 0

  test('the primary repo\'s thin cell is REFUSED before the approver tries: every clause, observed vs threshold', async ({ page }) => {
    await page.goto(`/signoff?repo=${encodeURIComponent(t.name)}`)
    const gate = page.getByTestId('signoff-gate')
    await expect(gate).toBeVisible()
    await expect(gate).toContainText('policy signoff-policy.v2')
    const select = field(page, 'Cell')
    await expect.poll(async () => (await select.locator('option').count()) - 1).toBeGreaterThanOrEqual(1)
    const value = await select.locator('option').nth(1).getAttribute('value')
    await select.selectOption({ value: value! })
    const [cls, size] = value!.split('|')
    await expect(gate).toContainText(`Attest ${cls} × ${size}`)

    // the evidence the approver sees: n / point / Wilson-low / false-Q1 / oracle / controls / route
    const evidence = page.getByTestId('signoff-evidence')
    await expect(evidence).toBeVisible()
    await expect(page.getByTestId('signoff-tile-point')).toContainText('100.0%')
    await expect(page.getByTestId('signoff-tile-false-q1')).toContainText('0')
    const controls = page.getByTestId('signoff-controls')
    await expect(controls.getByTestId('controls-escaped')).toBeVisible() // 04's real finding
    await expect(controls).toContainText('1 escape(s)')
    await expect(page.getByTestId('signoff-route')).toContainText('n_below_min')

    // every failing clause is listed with the number that failed and the bar it missed
    const refusals = page.getByTestId('signoff-refusals')
    await expect(refusals).toBeVisible()
    const thin = refusals.getByTestId('refusal-thin_cell')
    await expect(thin).toContainText('thin cell')
    await expect(thin).toContainText('observed 2')
    await expect(thin).toContainText('threshold 10')
    const escape = refusals.getByTestId('refusal-controls_escapes')
    await expect(escape).toContainText('a measurement control escaped the oracle')
    await expect(escape).toContainText('observed 1')
    await expect(escape).toContainText('threshold 0')
    await expect(refusals.getByTestId('refusal-route_not_deliver:n_below_min')).toContainText('observed calibrate')
    await expect(refusals.getByTestId('refusal-attestation_missing')).toContainText('non-overridable')

    // the gate is CLOSED on exactly those criteria; the action is disabled; nothing is sent
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    await expect(gateRow(gate, 'Cell is measured')).toContainText(/✓\s*satisfied:/)
    await expect(gateRow(gate, 'false-Q1 = 0')).toContainText(/✓\s*satisfied:/)
    await expect(gateRow(gate, 'n ≥ 10')).toContainText(/✗\s*not satisfied:/)
    await expect(gateRow(gate, /Negative controls passed/)).toContainText(/✗\s*not satisfied:/)
    await expect(gateRow(gate, 'Route = deliver')).toContainText(/✗\s*not satisfied:/)
    // even a named, affirmed row cannot open it
    await field(page, 'Accepted row').selectOption({ index: 1 })
    await page.getByTestId('attest-read').check()
    await field(page, 'Attestation statement').fill('walkthrough: attempting to sign off a thin cell under an escaped gate')
    await expect(page.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    await expect(page.getByTestId('signoff-recorded')).toHaveCount(0)
    await expect(page.getByRole('table', { name: `Sign-offs for ${t.name}` })).toContainText('No attestations yet')
  })

  test(`seed a policy-satisfying cell through the API: onboard, probe, mine ${N_TASKS}, controls (0 escapes), oracle (≥ 0.80), replay ${N_TASKS} → deliver`, async ({ page }) => {
    test.setTimeout(20 * MIN)
    const url = buildSignableRepo()
    const runnerOpts: Record<string, unknown> = { pythonpath_suffix: '/src' }
    if (env.python) runnerOpts.python = env.python
    await apiPost(page, '/repos', {
      name: SIGNABLE_NAME,
      language: 'python',
      runner: 'pytest',
      url,
      src_prefix: 'src/',
      test_prefix: 'tests/',
      ext: '.py',
      belt_scope: 'AFFECTED_DIRS',
      probe: 'tests/test_calc.py',
      runner_opts: runnerOpts,
    })
    const probe = await apiPost(page, `/repos/${SIGNABLE_NAME}/probe`, {})
    await waitRun(page, String(probe.id), 3 * MIN)
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'mine', limit: N_TASKS }, 4 * MIN)
    const tasks = await apiGet(page.request, `/repos/${SIGNABLE_NAME}/tasks?limit=100`)
    expect(Number(tasks.total)).toBeGreaterThanOrEqual(N_TASKS)
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'controls', limit: 1 }, 3 * MIN)
    const controls = await apiGet(page.request, `/oracle/${SIGNABLE_NAME}/controls`)
    expect(controls.passed, JSON.stringify(controls)).toBe(true)
    expect(Number(controls.escapes)).toBe(0) // parametrised tests: the cheat is not constructible
    // signoff-policy.v2: the cell's oracle must be MEASURED — score every task by mutation
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'oracle', limit: N_TASKS }, 8 * MIN)
    const oracle = await apiGet(page.request, `/oracle/${SIGNABLE_NAME}`)
    const scored = (oracle.tasks as Array<Record<string, unknown>>).filter((t) => t.strength !== null)
    expect(scored.length, JSON.stringify(oracle.cells)).toBeGreaterThanOrEqual(16)
    for (const t of scored) expect(Number(t.strength), `task ${t.task_id} strength`).toBeGreaterThanOrEqual(0.5)
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'replay', builder: 'fixture_gold', model: 'gold', limit: N_TASKS }, 6 * MIN)

    const map = await apiGet(page.request, `/capability-map?repo=${SIGNABLE_NAME}`)
    const cells = map.cells as Array<Record<string, unknown>>
    const best = cells.reduce((a, b) => (Number(b.n) > Number(a.n) ? b : a))
    signableClass = String(best.capability_class)
    signableSize = String(best.size)
    signableN = Number(best.n)
    expect(signableN, JSON.stringify(best)).toBeGreaterThanOrEqual(16)
    expect(best.false_q1).toBe(0)
    expect(best.route, `route ${best.route}: ${best.reason}`).toBe('deliver')
    expect((map.controls as Record<string, unknown>).state).toBe('passed')
    // … and the oracle of THAT cell, as the sign-off will measure it, clears the bar
    const oracleCell = (oracle.cells as Array<Record<string, unknown>>).find((c) => c.capability_class === signableClass && c.size === signableSize)!
    expect(oracleCell, JSON.stringify(oracle.cells)).toBeTruthy()
    expect(Number(oracleCell.strength_mean), JSON.stringify(oracleCell)).toBeGreaterThanOrEqual(0.8)
  })

  test('the approver signs the deliver cell with an attestation; the record shows the snapshot', async ({ page }) => {
    await page.goto(`/signoff?repo=${SIGNABLE_NAME}`)
    const gate = page.getByTestId('signoff-gate')
    await expect(gate).toBeVisible()
    const select = field(page, 'Cell')
    await expect.poll(async () => (await select.locator('option').count()) - 1).toBeGreaterThanOrEqual(1)
    await select.selectOption({ value: `${signableClass}|${signableSize}` })
    await expect(gate).toContainText(`Attest ${signableClass} × ${signableSize}`)

    // the bar, before the button: n / point / lower / false-Q1 / controls passed / route deliver
    await expect(page.getByTestId('signoff-tile-point')).toContainText('100.0%')
    await expect(page.getByTestId('signoff-tile-point')).toContainText(String(signableN))
    await expect(page.getByTestId('signoff-tile-false-q1')).toContainText('0')
    const controls = page.getByTestId('signoff-controls')
    await expect(controls.getByTestId('controls-passed')).toBeVisible()
    await expect(controls).toContainText('0 escape(s)')
    await expect(page.getByTestId('signoff-route')).toContainText('deliver')
    // the oracle is measured on the cell's tasks (never "—" here) and clears the bar
    const oracleTile = page.getByTestId('signoff-tile-oracle')
    await expect(oracleTile).toContainText(/^Oracle strength(0\.[89]\d|1\.00)/) // the value, never "—"
    await expect(oracleTile).toContainText(/\d+ of \d+ task\(s\) scored/)
    await expect(gateRow(gate, /Oracle strength measured and ≥ 0\.80/)).toContainText(/✓\s*satisfied:/)
    // only the attestation is missing
    const refusals = page.getByTestId('signoff-refusals')
    await expect(refusals.getByTestId('refusal-attestation_missing')).toBeVisible()
    await expect(refusals.locator('li')).toHaveCount(1)
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    const submit = page.getByRole('button', { name: 'Sign off' })
    await expect(submit).toBeDisabled()

    // the picker offers the cell's accepted rows: subject · row hash · date
    const picker = field(page, 'Accepted row')
    await expect.poll(async () => (await picker.locator('option').count()) - 1).toBeGreaterThanOrEqual(16)
    const first = picker.locator('option').nth(1)
    await expect(first).toContainText(/feat: add op\d+ · [0-9a-f]{10} · /)
    const rowHash = await first.getAttribute('value')
    expect(rowHash).toMatch(/^[0-9a-f]{64}$/)
    await picker.selectOption({ value: rowHash! })
    // the preview re-fetched with the named row: no refusal left, but the affirmation is still needed
    await expect(page.getByTestId('signoff-refusals')).toHaveCount(0)
    await expect(submit).toBeDisabled()
    await page.getByTestId('attest-read').check()
    await field(page, 'Attestation statement').fill('walkthrough: I read the accepted diff — it adds the op module and its parametrised test, nothing else.')
    await field(page, 'Note').fill('walkthrough: 18 fixture_gold rows, controls passed with 0 escapes')
    await expect(gate).toHaveAttribute('data-state', 'OPEN')
    await expect(gateRow(gate, 'Accepted row read and affirmed')).toContainText(/✓\s*satisfied:/)
    await expect(submit).toBeEnabled()

    await submit.click()
    await expect(page.getByTestId('signoff-recorded')).toContainText('signoff-policy.v2')
    // the record: evidence at signing, policy · route · controls, the attested row
    const table = page.getByRole('table', { name: `Sign-offs for ${SIGNABLE_NAME}` })
    await expect(table.getByTestId('signoff-row-evidence')).toContainText(`n=${signableN} · 100.0% · lower `)
    await expect(table.getByTestId('signoff-row-evidence')).toContainText('fQ1 0')
    await expect(table.getByTestId('signoff-row-evidence')).toContainText(/oracle (0\.[89]\d|1\.00)/)
    await expect(table.getByTestId('signoff-row-policy')).toContainText('signoff-policy.v2 · deliver (deliver) · controls passed')
    await expect(table.getByTestId('signoff-row-policy')).toContainText('esc 0')
    await expect(table.getByTestId('signoff-row-attestation')).toContainText(rowHash!.slice(0, 10))
    await expect(table.getByRole('img', { name: 'Active attestation' })).toBeVisible()

    // and the API serves the same snapshot, hash-chained
    const list = await apiGet(page.request, `/signoffs?repo=${SIGNABLE_NAME}`)
    const [rec] = list.items as Array<Record<string, unknown>>
    expect(rec.policy_version).toBe('signoff-policy.v2')
    expect((rec.policy_thresholds as Record<string, unknown>).require_oracle_measured).toBe(true)
    expect(Number((rec.evidence as Record<string, unknown>).oracle_strength)).toBeGreaterThanOrEqual(0.8)
    expect((rec.route as Record<string, unknown>).reason_code).toBe('deliver')
    expect((rec.controls as Record<string, unknown>).escapes).toBe(0)
    expect((rec.attestation as Record<string, unknown>).reviewed_row_hash).toBe(rowHash)
    expect(String(rec.row_hash)).toMatch(/^[0-9a-f]{64}$/)
    // the Capability page now shows the cell as human-verified
    const map = await apiGet(page.request, `/capability-map?repo=${SIGNABLE_NAME}`)
    const cell = (map.cells as Array<Record<string, unknown>>).find((c) => c.capability_class === signableClass && c.size === signableSize)!
    expect(cell.verification_tier).toBe('human-verified')
    expect(cell.route).toBe('deliver') // a tier never moves a route
  })
})
