/**
 * 04b — the connect-and-prove journey through its OWN doors, on a repository of its own
 * (`walk-door`, two coupled commits with literal-assert tests, built here and served as a
 * bare `file://` clone — never the primary repository, whose n 05 and 08 depend on). Proves:
 *
 *  - `/connect` → *Connect by URL* lands on the walk (`/connect/:name`) with stage 1 Done and
 *    stage 2 Not started; the walk's own Run on the probe stage queues the probe, the card
 *    watches it, and stage 2 reads Done (G-300, G-125, G-119);
 *  - Configuration → Save → *Run probe now* goes green inline and back on the walk stage 2
 *    reads Done with the NEW run's door (G-300);
 *  - Run on stages 3, 4 and 5 (mine, oracle, controls) queues each kind from the walk, each
 *    card watches its run, and the controls stage ends amber — *Done, with a finding* with
 *    the `passed with K escape(s)` line, K read from `GET /oracle/{repo}/controls` (never
 *    hard-coded; the literal asserts let `hardcode_cheat` grade clean, so K ≥ 1 by
 *    construction) and the *Strengthen the tests on Learn* door; the run behind it succeeded
 *    with `controls.report` on its log; and `/oracle`'s gate state is the API's verdict
 *    (G-428).
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 04b (the walk's own doors) on its own two-commit fixture.
 * What it does: Pins that Connect by URL lands on the walk; that the walk's Run on the probe
 *               stage turns it Done; that Configuration → Save → Run probe now re-probes and the
 *               walk reads the new run; that Run on stages 3–5 queues mine, oracle and controls
 *               from the walk with each card watched; that the controls stage reads amber with
 *               the API's escape count and the Learn door; that the controls run succeeded with
 *               `controls.report`; and that /oracle's gate matches the API's verdict.
 * How:          `buildCalcRepo('walk-door', 2, 'literal')`; the Add-repository dialog from
 *               /connect; the stage pills' `aria-label` (`<title>: <status>`) polled until a
 *               terminal reading; the repository's Configuration form; `apiGet` for the escape
 *               count and the verdict the screens must equal.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`buildCalcRepo`, `field`, `waitForRun`, `apiGet`),
 *               ui/src/screens/Connect/ConnectPage.tsx (the list, the dialog door and the walk),
 *               ui/src/screens/Connect/connection.ts (the stage lines asserted),
 *               ui/src/api/hooks.ts (`useCreateRun` — the walk watches the run it queued),
 *               ui/src/screens/Repos/RepoConfigForm.tsx (Save and Run probe now),
 *               ui/src/screens/Oracle/OraclePage.tsx (the gate banner),
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts and 08-signoff.spec.ts (the primary
 *               repository this spec leaves alone)
 * Tested by:    ui/e2e/walkthrough/04b-connect-walk.spec.ts
 * Touch when:   never for a new repository (this spec builds its own); a stage title, its status
 *               wording or the Configuration form's test ids change; the controls finding's
 *               sentence changes (ui/src/screens/Connect/connection.ts `controlsFinding`).
 */
import type { Page } from '@playwright/test'
import { apiGet, buildCalcRepo, env, expect, expectLogAction, field, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const NAME = 'walk-door'
const N_COMMITS = 2
const MIN = 60_000
type StageId = 'register' | 'probe' | 'mine' | 'oracle' | 'controls' | 'measure'
const STATUS = /: (Done|Done, with a finding|In progress|Not started|Failed|Waiting|Queued)$/

/** The stage's status pill: `aria-label` is `<title>: <status>` (ui/src/screens/Connect/ConnectPage.tsx). */
function stagePill(page: Page, id: StageId) {
  return page.getByTestId(`stage-${id}`).getByRole('img', { name: STATUS })
}

/** The status part of the pill's label — `Done`, `Queued`, `In progress`, `Done, with a finding` … */
async function stageStatus(page: Page, id: StageId): Promise<string> {
  const label = (await stagePill(page, id).getAttribute('aria-label')) ?? ''
  return label.replace(/^[^:]*: /, '')
}

/** Watch a stage the walk queued until it is terminal; assert it did not fail. */
async function watchStage(page: Page, id: StageId, timeoutMs: number): Promise<string> {
  await expect
    .poll(() => stageStatus(page, id), { timeout: timeoutMs, intervals: [500, 1000, 2000], message: `stage ${id} did not reach a terminal reading` })
    .toMatch(/^(Done|Done, with a finding|Failed)$/)
  const got = await stageStatus(page, id)
  expect(got, `stage ${id} ended ${got}`).not.toBe('Failed')
  return got
}

/** Press the walk's own Run on a stage and watch the card: Queued or In progress first, then terminal. */
async function runStage(page: Page, id: StageId, timeoutMs: number): Promise<string> {
  const stage = page.getByTestId(`stage-${id}`)
  await expect(stagePill(page, id)).toHaveAttribute('aria-label', /: Not started$/)
  await stage.getByRole('button', { name: 'Run', exact: true }).click()
  // the card watches the run it queued (the repository is read again on success — G-428)
  await expect(stagePill(page, id)).toHaveAttribute('aria-label', /: (Queued|In progress|Done|Done, with a finding)$/, { timeout: 30_000 })
  return watchStage(page, id, timeoutMs)
}

test.describe('04b the walk through its own doors', () => {
  test.skip(env.publicTier, '04b walks the hermetic fixture; tier 2 onboards its repositories in 02')

  test('/connect → Connect by URL lands on the walk; Run on the probe stage turns it Done on the walk', async ({ page }) => {
    test.setTimeout(6 * MIN)
    const url = buildCalcRepo(NAME, N_COMMITS, 'literal')
    await page.goto('/connect')
    await page.getByRole('button', { name: 'Connect by URL' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add a repository' })
    await expect(dialog).toBeVisible()
    await field(dialog, 'Name').fill(NAME)
    await field(dialog, 'Preset').selectOption('python-src-layout')
    await expect(field(dialog, 'Language')).toHaveValue('python')
    await expect(field(dialog, 'Source')).toHaveValue('url')
    await field(dialog, 'Git URL').fill(url)
    await field(dialog, 'Belt scope').selectOption('AFFECTED_DIRS')
    await field(dialog, 'Probe scope').fill('tests/test_calc.py')
    // the interpreter is pinned later, from Configuration: this door registers the shape only
    await field(dialog, 'Runner options (JSON)').fill(JSON.stringify({ pythonpath_suffix: '/src' }, null, 2))
    await dialog.getByRole('button', { name: 'Add repo' }).click()
    // this door lands on the walk, not on the technical repository page
    await page.waitForURL(new RegExp(`/connect/${NAME}$`))
    await expect(page.getByRole('list', { name: 'Connection stages' })).toBeVisible()
    await expect(stagePill(page, 'register')).toHaveAttribute('aria-label', 'Repository registered: Done')
    await expect(stagePill(page, 'probe')).toHaveAttribute('aria-label', 'Toolchain probed: Not started')
    await expect(stagePill(page, 'mine')).toHaveAttribute('aria-label', 'Commits mined into tasks: Waiting')
    // the walk's own Run on stage 2: the card watches the probe and reads Done
    if (env.python) {
      // tier 1 pins the interpreter so the probe never installs (the same pin 02 types)
      await page.getByRole('link', { name: 'Configuration' }).click()
      await page.waitForURL(new RegExp(`/repos/${NAME}$`))
      await page.getByRole('tab', { name: 'Configuration' }).click()
      await page.getByLabel('Python interpreter', { exact: true }).fill(env.python)
      await page.getByTestId('repo-config-save').click()
      await expect(page.getByTestId('repo-config-toast-probe')).toBeVisible()
      await page.goto(`/connect/${NAME}`)
    }
    const got = await runStage(page, 'probe', 3 * MIN)
    expect(got).toBe('Done')
    await expect(page.getByTestId('stage-probe')).toContainText(/\d+ passed/)
    // and the repository's own page agrees
    await page.goto(`/repos/${NAME}`)
    await expect(page.getByTestId('repo-probe')).toHaveAttribute('aria-label', 'Probe: ok')
  })

  test('Configuration → Save → Run probe now → back on the walk stage 2 reads Done with the new run', async ({ page }) => {
    test.setTimeout(6 * MIN)
    await page.goto(`/connect/${NAME}`)
    const door = page.getByTestId('stage-probe').getByRole('link', { name: 'open run' })
    await expect(door).toHaveAttribute('href', /\/runs\/[0-9a-f]{32}$/)
    const before = (await door.getAttribute('href'))!
    // the walk's Configuration door, then a real change: the belt scope to the tests directory
    await page.getByRole('link', { name: 'Configuration' }).click()
    await page.waitForURL(new RegExp(`/repos/${NAME}$`))
    await page.getByRole('tab', { name: 'Configuration' }).click()
    await page.getByLabel('PYTHONPATH suffix', { exact: true }).fill('/src/')
    await page.getByTestId('repo-config-save').click()
    // the save toast offers the probe; it goes green inline with the runner's own summary
    await page.getByTestId('repo-config-toast-probe').click()
    const result = page.getByTestId('repo-config-probe-result')
    await expect(result).toBeVisible()
    await expect.poll(async () => result.getAttribute('data-outcome'), { timeout: 3 * MIN, intervals: [1000, 2000] }).not.toBe('pending')
    await expect(result).toHaveAttribute('data-outcome', 'green')
    await expect(page.getByTestId('repo-config-probe-reason')).toHaveText(/\d+ passed/)
    // back on the walk: stage 2 reads Done, and its door is the NEW run's
    await page.goto(`/connect/${NAME}`)
    await expect(stagePill(page, 'probe')).toHaveAttribute('aria-label', 'Toolchain probed: Done')
    await expect(door, 'the walk reads the re-probe, not the first probe').not.toHaveAttribute('href', before)
    await expect(door).toHaveAttribute('href', /\/runs\/[0-9a-f]{32}$/)
  })

  test('presses Run on stages 3, 4 and 5 of the walk, watches each, and reads the amber controls line before /oracle', async ({ page }) => {
    test.setTimeout(20 * MIN)
    await page.goto(`/connect/${NAME}`)
    // stage 3: mine — the two coupled commits become tasks
    expect(await runStage(page, 'mine', 4 * MIN)).toBe('Done')
    await expect(page.getByTestId('stage-mine')).toContainText(new RegExp(`\\b${N_COMMITS} task`))
    // stage 4: the oracle — mutants on the changed lines
    expect(await runStage(page, 'oracle', 8 * MIN)).toBe('Done')
    await expect(page.getByTestId('stage-oracle')).toContainText(/\d+ tasks? scored/)
    // stage 5: the negative controls — amber by construction: the literal asserts let the
    // hard-code cheat grade clean, so the report carries an escape, a finding the person must
    // answer before spending
    const got = await runStage(page, 'controls', 8 * MIN)
    const report = (await apiGet(page.request, `/oracle/${NAME}/controls`)) as { passed: boolean; escapes: number; verdict: { state: string; escapes: number } }
    const escapes = Number(report.escapes)
    expect(escapes, JSON.stringify(report.verdict)).toBeGreaterThanOrEqual(1)
    expect(report.passed, 'no violation: the report passed, with a finding').toBe(true)
    expect(got).toBe('Done, with a finding')
    const stage = page.getByTestId('stage-controls')
    await expect(stage).toContainText(new RegExp(`passed with ${escapes} escapes?\\b`))
    await expect(stage).toContainText('deliver is withheld until the tests are hardened and the controls re-run')
    await expect(stage).toContainText(`${escapes} escape`)
    // the way forward is on the card
    await expect(stage.getByRole('link', { name: 'Strengthen the tests on Learn' })).toHaveAttribute('href', `/learn?repo=${NAME}#strengthen`)
    // the run behind the finding: succeeded, with the report on its log
    await stage.getByRole('link', { name: 'open run' }).click()
    await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
    await waitForRun(page, 'succeeded', MIN)
    await expectLogAction(page, 'controls.report')
    // and /oracle's gate is the API's verdict, never derived from the counts in the UI
    await page.goto(`/oracle?repo=${NAME}`)
    const banner = page.getByTestId('gate-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toHaveAttribute('data-state', report.verdict.state === 'passed' ? 'OPEN' : 'CLOSED')
    await expect(banner).toContainText(report.verdict.state)
  })
})
