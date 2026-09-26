/**
 * 13 — the learning loop acts from the page (G-532, G-913, G-349, G-175, G-176, G-916).
 *
 *  - A real refusal is made on the live stack: a `fixture_gold` replay queued through the
 *    Runs dialog with `builder_config {"attempt": "git log -p"}` puts that command to the
 *    REAL shell guard, which refuses it, so the rows land as `protocol` exactly as an agentic
 *    builder's would (every attempt refused, so the run itself ends `failed` and says why).
 *    Nothing is seeded around the product.
 *  - A cell is held for its oracle the only honest way: more fixture replays of the primary
 *    repository through the API until the cell reaches the routing rule's n, where 04's
 *    controls escape (or a weak oracle) holds it — so the strengthen report has a row.
 *  - The operator (`walk-operator`, a real operator account) reads the loop's position line,
 *    the register card with the refused class on it, the refusal tile with its n and
 *    interval, the refusal row, the strengthening row and the re-measurement plan; decides
 *    the refusal (refused, with a note) and reads what it wrote and under whose name;
 *    registers the strengthening item and follows the Factory link to the item it
 *    registered; follows the Re-score hand-off to a Runs dialog with the kind and the task
 *    filled in; and walks to the Oracle screen and a task and back to the plan.
 *  - A viewer reads the same reports and is offered none of the decisions.
 *  - axe (WCAG 2.1 AA) is clean on `/learn?repo=<primary>` with every card rendered and a
 *    hint open, for every persona at 1280 and 375, the top bar at most two rows and no
 *    sideways scroll at 375.
 *
 * Tier 1 only: the fixture builder and the free replays are the hermetic tier's.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 13 (learn: /learn with real rows → a decision, a
 *               registration and the hand-offs), tier 1 only.
 * What it does: Makes a genuine guard refusal and an oracle-held cell through the product,
 *               then walks the Learn page as an operator (read, decide, register, hand off,
 *               Oracle and back), as a viewer (no decision offered) and under axe for every
 *               persona at both widths with a hint open.
 * How:          `startRun` for the refusal (the Runs dialog's builder config), `POST /runs`
 *               for the extra replays, `waitRun` on the API; persona accounts are ensured
 *               through `POST /users` as the admin, with `personaPassword`; `AxeBuilder`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
 * Works with:   ui/e2e/walkthrough/support.ts (`startRun`, `signIn`, `personaPassword`),
 *               ui/src/screens/Learn/LearnPage.tsx and PreventionSection.tsx (the screen
 *               under test), src/crb/server/routes/learn.py (the reads and the three writes),
 *               src/crb/builders/fixture_gold.py (`attempt` — the real guard refusal),
 *               ui/e2e/walkthrough/11-screens.spec.ts (creates the same persona accounts)
 * Tested by:    scripts/walkthrough.sh (runs it, tier 1)
 * Touch when:   a Learn control's name or test id changes; the fixture's `attempt` changes; a
 *               persona is added.
 */
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import type { Browser, Page } from '@playwright/test'
import { env, expect, personaPassword, primary, signIn, startRun, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const MIN = 60_000
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
/** Where the captured screens go — beside 11-screens' `<persona>__<route>__<width>.png`. */
const OUT = join(process.env.CRB_E2E_OUTPUT_DIR ?? 'test-results-walkthrough', 'screens')
mkdirSync(OUT, { recursive: true })
const PERSONAS = ['viewer', 'operator', 'approver'] as const
const USERNAME = (p: string) => `walk-${p}`
/** The command the fixture puts to the guard: history access, refused as archaeology. */
const REFUSED = 'git log -p'
/** An apparatus no stack runs yet: the what-if plan against it makes every row stale. */
const WHAT_IF = '99.0'

async function csrf(page: Page): Promise<Record<string, string>> {
  const cookie = (await page.context().cookies()).find((c) => c.name === 'crb_csrf')
  if (!cookie) throw new Error('no crb_csrf cookie — is the page signed in?')
  return { 'X-CSRF-Token': cookie.value }
}

async function apiGet(page: Page, path: string): Promise<Record<string, unknown>> {
  const res = await page.request.get(`${env.baseUrl}/api/v1${path}`)
  expect(res.ok(), `GET ${path} → ${res.status()}`).toBeTruthy()
  return (await res.json()) as Record<string, unknown>
}

async function apiPost(page: Page, path: string, data: unknown): Promise<Record<string, unknown>> {
  const res = await page.request.post(`${env.baseUrl}/api/v1${path}`, { data, headers: await csrf(page) })
  expect(res.status(), `POST ${path} → ${res.status()} ${await res.text()}`).toBeLessThan(300)
  return (await res.json()) as Record<string, unknown>
}

async function waitRun(page: Page, runId: string, timeoutMs: number): Promise<void> {
  await expect
    .poll(async () => String((await apiGet(page, `/runs/${runId}`)).status), { timeout: timeoutMs, intervals: [500, 1000, 2000], message: `run ${runId} did not finish` })
    .toMatch(/^(succeeded|failed|cancelled)$/)
  const run = await apiGet(page, `/runs/${runId}`)
  expect(run.status, `run ${runId} ended ${run.status}: ${run.error ?? ''}`).toBe('succeeded')
}

/** The persona accounts 11-screens creates; made here too so this spec can run on its own. */
async function ensurePersonas(page: Page): Promise<void> {
  const users = (await apiGet(page, '/users')).items as Array<{ username: string }>
  for (const p of PERSONAS) {
    if (users.some((u) => u.username === USERNAME(p))) continue
    await apiPost(page, '/users', { username: USERNAME(p), password: personaPassword(USERNAME(p)), role: p, display_name: `Walk ${p}` })
  }
}

/**
 * A page signed in as a persona in its OWN browser context. Switching accounts on the
 * fixture's page (signed in as the admin) raced the sign-out on the first walkthrough; a
 * fresh context has no session to end, so the persona's sign-in is the only one on it.
 */
async function personaPage(browser: Browser, persona: string, viewport?: { width: number; height: number }): Promise<Page> {
  const context = await browser.newContext({ baseURL: env.baseUrl, ...(viewport ? { viewport } : {}) })
  const page = await context.newPage()
  await signIn(page, USERNAME(persona), personaPassword(USERNAME(persona)))
  return page
}

/** The bootstrap admin, the same way: its own context at the viewport under test. */
async function personaPageAdmin(browser: Browser, viewport: { width: number; height: number }): Promise<Page> {
  const context = await browser.newContext({ baseURL: env.baseUrl, viewport })
  const page = await context.newPage()
  await signIn(page)
  return page
}

/** Every card of the page has painted: the four eyebrows and each report's table or empty state. */
async function learnRendered(page: Page): Promise<void> {
  for (const eyebrow of ['Prevention', 'Refusals', 'Weak oracles', 'Stale evidence']) await expect(page.getByText(eyebrow, { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('table', { name: /Refusal classes/ })).toBeVisible()
  await expect(page.getByRole('table', { name: /Strengthening backlog/ })).toBeVisible()
  await expect(page.getByRole('table', { name: /predates the current apparatus/ })).toBeVisible()
  await expect(page.getByText(/^Deriving /)).toHaveCount(0)
}

test.describe('13 learn: the loop acts from the page', () => {
  const t = primary()
  test.skip(env.publicTier, 'tier 1 only: the fixture builder makes the refusal and the free replays hold the cell')

  test('a real guard refusal: a fixture replay whose attempted command the guard refuses', async ({ page }) => {
    test.setTimeout(6 * MIN)
    await startRun(page, t.name, { kind: 'replay', builder: 'fixture_gold', model: 'gold', limit: 2, builderConfig: { attempt: REFUSED } })
    // every attempt was refused, so the run ends failed and says why — the rows are written
    await waitForRun(page, 'failed', 5 * MIN)
    await expect(page.getByRole('alert').first()).toContainText('protocol violation: archaeology')
    const report = await apiGet(page, `/learn/refusals?repo=${encodeURIComponent(t.name)}`)
    const groups = report.groups as Array<{ prefix: string; shape: string; n: number }>
    const ours = groups.find((g) => g.prefix === 'archaeology' && g.shape.startsWith('git log'))
    expect(ours, `an archaeology class for "${REFUSED}" in ${JSON.stringify(groups)}`).toBeTruthy()
    expect(ours!.n).toBeGreaterThanOrEqual(1)
  })

  test('a cell held for its oracle: replays until the primary cell reaches the rule’s n', async ({ page }) => {
    test.setTimeout(14 * MIN)
    await ensurePersonas(page)
    const items = async () => ((await apiGet(page, `/learn/strengthen?repo=${encodeURIComponent(t.name)}`)).items as unknown[]).length
    // bounded: each replay adds one row per task to the cell; 04's escape holds it once n ≥ min_n
    for (let i = 0; i < 6 && (await items()) === 0; i += 1) {
      const run = await apiPost(page, '/runs', { repo: t.name, kind: 'replay', builder: 'fixture_gold', model: 'gold', limit: 3 })
      await waitRun(page, String(run.id), 4 * MIN)
    }
    expect(await items(), 'the strengthen report holds a cell of the primary repository').toBeGreaterThanOrEqual(1)
  })

  test('the operator reads the loop, the register, the refusal tile and a row of each report that has one', async ({ browser }) => {
    const page = await personaPage(browser, 'operator')
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
    await learnRendered(page)
    await expect(page.getByTestId('learn-loop')).toContainText('You are in the learning loop')
    // the register card, after the worker's tick, shows the class the refusal opened (G-175)
    const register = page.getByRole('table', { name: 'Bug classes and the change that removes them' })
    await expect(register.getByRole('row').filter({ hasText: /protocol:archaeology/ }).first()).toBeVisible()
    // the refusal tile: one apparatus, its n and its Wilson interval (G-913)
    const tile = page.locator('[data-hint="stat.learn.refusal_share"]')
    await expect(tile).toContainText(/n =\s*\d+/)
    await expect(tile).toContainText(/95% CI\s*\[\d+\.\d%, \d+\.\d%\]/)
    await expect(tile).toContainText(/apparatus \d+\.\d+ · failure_kind = protocol/)
    // a row of the refusals and of the strengthening backlog, from this stack's own rows
    await expect(page.getByRole('table', { name: /Refusal classes/ }).getByRole('row').filter({ hasText: 'git log' }).first()).toBeVisible()
    await expect(page.getByRole('table', { name: /Strengthening backlog/ }).locator('tbody tr').first()).toContainText(/strengthen-/)
    // the plan: a fresh stack's rows all carry the running apparatus, so it says so, with its n
    const plan = page.locator('#remeasure')
    await expect(plan.getByText('Nothing stale')).toBeVisible()
    await expect(page.locator('[data-hint="stat.learn.stale_rows"]')).toContainText(/n =\s*\d+/)
    // and read against a future apparatus (what a bump would cost, G-983) every row is stale:
    // a row of the plan, naming the runs it would queue — and no Queue control on a preview
    await plan.getByLabel(/^Plan against apparatus/).fill(WHAT_IF)
    await plan.getByRole('button', { name: 'Plan', exact: true }).click()
    await expect(plan.getByTestId('learn-plan-whatif')).toContainText(`planned against apparatus ${WHAT_IF}`)
    const planRow = plan.getByRole('table', { name: /predates the current apparatus/ }).locator('tbody tr').first()
    await expect(planRow).toBeVisible()
    await expect(planRow).toContainText(/\S+\|\S+/)
    await expect(plan.getByRole('button', { name: 'Queue runs' })).toHaveCount(0)
  })

  test('the operator decides the refusal class and reads what it wrote, under their name', async ({ browser }) => {
    const page = await personaPage(browser, 'operator')
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
    const row = page.getByRole('table', { name: /Refusal classes/ }).getByRole('row').filter({ hasText: 'git log' }).first()
    await row.getByRole('button', { name: 'Decide' }).click()
    const dialog = page.getByRole('dialog', { name: 'Decide this refusal class' })
    await expect(dialog.getByTestId('learn-decide-summary')).toContainText('archaeology')
    await dialog.getByLabel(/Your verdict/).selectOption('refuse')
    await dialog.getByLabel(/Why/).fill('walkthrough: history access is archaeology')
    await dialog.getByRole('button', { name: 'Record this decision' }).click()
    const done = page.getByRole('dialog', { name: 'Decision recorded' }).getByRole('status')
    await expect(done).toContainText('Recorded as refuse by Walk operator')
    await expect(done).toContainText('shell_corpus_refused.txt')
    await page.getByRole('button', { name: 'Close', exact: true }).click()
    // the row now reads the decision and who made it, and is not offered the form again
    await expect(row).toContainText('refuse')
    await expect(row).toContainText('by Walk operator')
    await expect(row.getByRole('button', { name: 'Decide' })).toHaveCount(0)
    // the record is the event: its actor is the signed-in account, never a field of the body
    const decisions = (await apiGet(page, `/learn/refusals?repo=${encodeURIComponent(t.name)}`)).decisions as Array<{ verdict: string; decided_by: string; decided_by_id: string }>
    expect(decisions.some((d) => d.verdict === 'refuse' && d.decided_by === 'Walk operator' && d.decided_by_id.length > 0)).toBe(true)
  })

  test('the operator registers the strengthening item and the Factory opens on it', async ({ browser }) => {
    const page = await personaPage(browser, 'operator')
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
    const card = page.locator('#strengthen')
    await card.getByRole('button', { name: 'Register' }).first().click()
    const done = card.getByRole('status').filter({ hasText: /registered|frozen backlog/ })
    await expect(done).toContainText(/strengthen-[0-9a-f]+/)
    const id = /strengthen-[0-9a-f]+(?:-v\d+)?/.exec((await done.textContent()) ?? '')![0]
    await card.getByRole('link', { name: 'Factory' }).click()
    await page.waitForURL(new RegExp(`/factory\\?repo=${t.name}&item=${id}`))
    await expect(page.locator(`#item-${id}`)).toBeVisible()
  })

  test('the loop walks on: Re-score opens Runs pre-filled, then Oracle, a task and back to the plan', async ({ browser }) => {
    const page = await personaPage(browser, 'operator')
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
    const card = page.locator('#strengthen')
    const rescore = card.getByRole('link', { name: 'Re-score' }).first()
    const href = (await rescore.getAttribute('href')) ?? ''
    expect(href).toContain(`/runs?repo=${t.name}&new=oracle`)
    await rescore.click()
    const dialog = page.getByRole('dialog', { name: 'Start a run' })
    await expect(dialog.getByLabel(/^Kind/)).toHaveValue('oracle')
    await expect(dialog.getByTestId('run-new-learn-step')).toContainText('Learning loop, step 4 of 6')
    const tasks = new URL(href, env.baseUrl).searchParams.get('tasks') ?? ''
    if (tasks) await expect(dialog.getByLabel(/^Only these tasks/)).toHaveValue(tasks)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    // back to the report, then its Oracle link to the weakest task's page
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
    await page.locator('[data-hint="link.learn.oracle"]').click()
    await page.waitForURL(new RegExp(`/oracle\\?repo=${t.name}`))
    await page.getByRole('table', { name: 'Oracle strength per task' }).locator('tbody tr a').first().click()
    await page.waitForURL(new RegExp(`/tasks/${t.name}/[0-9a-f]{7,64}`))
    // back to the plan, which names the runs a bump would queue (G-349)
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}#remeasure`)
    const plan = page.locator('#remeasure')
    await plan.getByLabel(/^Plan against apparatus/).fill(WHAT_IF)
    await plan.getByRole('button', { name: 'Plan', exact: true }).click()
    const runs = plan.getByRole('table', { name: /predates the current apparatus/ }).locator('tbody tr').first()
    await expect(runs).toBeVisible()
    await expect(page.locator('[data-hint="stat.learn.needed"]')).toContainText(/n =\s*[1-9]/)
  })

  test('a viewer reads the reports and is offered none of the decisions', async ({ browser }) => {
    const page = await personaPage(browser, 'viewer')
    await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
    await learnRendered(page)
    for (const name of ['Decide', 'Register', 'Queue runs']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
    for (const name of ['Re-qualify', 'Re-score', 'Re-run controls']) await expect(page.getByRole('link', { name, exact: true })).toHaveCount(0)
    await expect(page.getByText('An operator records the verdict.')).toBeVisible()
  })

  for (const persona of [...PERSONAS, 'admin'] as const) {
    for (const vp of [
      { width: 1280, height: 900 },
      { width: 375, height: 812 },
    ]) {
      test(`axe: /learn with every card rendered is clean for ${persona} @ ${vp.width}, with a hint open`, async ({ browser }) => {
        const page = persona === 'admin' ? await personaPageAdmin(browser, vp) : await personaPage(browser, persona, vp)
        await page.goto(`/learn?repo=${encodeURIComponent(t.name)}`)
        await learnRendered(page)
        const where = `${persona} @ ${vp.width} /learn?repo=${t.name}`
        // the register card with a class expanded (G-176)
        const summary = page.locator('details[data-class] > summary').first()
        await summary.scrollIntoViewIfNeeded()
        await summary.click()
        await expect(page.locator('details[data-class][open]').first()).toBeVisible()
        await page.screenshot({ path: join(OUT, `${persona}__learn-repo__${vp.width}.png`), fullPage: true, animations: 'disabled' })
        // one hint open while axe runs: the refusal tile's (hover, or the touch pointerdown a tap begins with)
        const tile = page.locator('[data-hint="stat.learn.refusal_share"]')
        await tile.scrollIntoViewIfNeeded()
        await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))))
        if (vp.width === 375) await tile.dispatchEvent('pointerdown', { pointerType: 'touch', isPrimary: true, bubbles: true, cancelable: true })
        else await tile.hover()
        const ids = ((await tile.getAttribute('aria-describedby')) ?? '').split(' ').filter(Boolean)
        const tip = page.locator(`#${ids[ids.length - 1]!.replace(/([:.])/g, '\\$1')}`)
        await expect(tip, `${where}: the tile's hint did not open`).toBeVisible({ timeout: 1000 })
        await expect(tip).toHaveCSS('opacity', '1')
        const a11y = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
        expect(a11y.violations, `${where}: ${JSON.stringify(a11y.violations, null, 2)}`).toEqual([])
        await page.keyboard.press('Escape')
        if (vp.width === 375) {
          const bar = page.getByRole('banner').locator('> div').first()
          const box = await bar.boundingBox()
          expect(box?.height ?? 0, `${where}: the top bar wrapped past two rows`).toBeLessThan(130)
          const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }))
          expect(widths.scroll, `${where}: the page scrolls sideways (${widths.scroll} > ${widths.inner})`).toBeLessThanOrEqual(widths.inner)
        }
      })
    }
  }
})
