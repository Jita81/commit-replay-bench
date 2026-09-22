/**
 * 11-screens — every route × persona × width, captured, the About block on every one, and the
 * hints: a sample opens on hover (or tap at phone width), axe stays clean with one open.
 *
 * Runs after 01–09 so the stack carries the data they produced. For each persona (viewer /
 * operator / approver / admin) it visits every route at desktop (1280×900) and phone
 * (375×812) widths, waits for the page to settle (load + bounded network-idle + the main
 * heading), writes a full-page PNG named `<persona>__<route-slug>__<width>.png` under
 * `<CRB_E2E_OUTPUT_DIR>/screens/`, and asserts that every authenticated route except the
 * help pages renders the "About this screen" block (`data-testid="about-this-screen"`) —
 * the one help mechanism, mounted once in the shell, must reach every screen for every role.
 * On every route it also samples up to five hinted elements (`data-hint`: first, last and
 * three evenly spaced), opens each one's bubble — hover at desktop width, a touch
 * `pointerdown` at phone width, where no hover exists — asserts the `role="tooltip"` the element's
 * `aria-describedby` names becomes visible with a full sentence, runs axe (WCAG 2.1 AA)
 * with the bubble open, and closes it with Escape. One keyboard pass per persona at 1280
 * tabs through the first twenty focusable elements of /results and asserts that focusing a
 * hinted one shows its bubble and tabbing away hides it. One dialog pass (the operator at
 * 1280) opens "Add a repository" and asserts a field's bubble paints above the modal's top
 * layer (`elementFromPoint`), closes on the first keystroke, and that one Escape closes the
 * bubble but not the dialog.
 *
 * Accounts: the viewer / operator / approver are created through the API as the admin
 * (POST /users, CSRF double-submit) if missing. Their passwords are STABLE per stack
 * (`personaPassword`: derived from the bootstrap admin password, test-only, never printed), so
 * a rerun against a stack that already has the accounts signs into them; when an account
 * already exists the setup proves that by signing into it through the API before any persona
 * test runs. Nothing here calls a model or spends.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 11 (screens) — the visual record of every route for every
 *               role at two widths, and the About-block ratchet on the live stack.
 * What it does: Creates the three non-admin accounts if missing (and, for one that exists,
 *               asserts the stable password signs into it), finds a finished run and a
 *               task to anchor the detail routes, then for each persona × width signs in
 *               through the form, visits every route, saves a full-page screenshot under
 *               `<CRB_E2E_OUTPUT_DIR>/screens/`, asserts the About block is present on
 *               every route that is not /help and, at 375 px, that the top bar is at most
 *               two rows (a wrapped "Sign out" is a phone-width defect); opens a sample of
 *               the route's hints (hover, or a touch pointerdown at 375 px) and asserts each bubble shows and axe stays
 *               clean with it open; tabs through /results at 1280 for the keyboard path;
 *               opens the Add-a-repository dialog once (operator, 1280) for the top-layer,
 *               typing and Escape checks a jsdom test cannot make. It
 *               changes no data; the fixture context goes into the test's annotations, never
 *               stdout.
 * How:          Playwright; `signIn` from support.ts; the routes list is built from the
 *               primary repo, the run and the task found through the API as the admin;
 *               `AxeBuilder` with the WCAG tags; the bubble is found through the trigger's
 *               `aria-describedby`, never by text, so the spec needs no import from src.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`env`, `signIn`, `primary`),
 *               ui/src/components/Help.tsx (the About block this asserts),
 *               ui/src/components/Hint.tsx (the `data-hint` triggers and `role="tooltip"`
 *               bubbles this opens), ui/src/components/Layout.tsx (mounts the About block
 *               once; its nav is always in the sample), ui/src/App.tsx (the routes this list
 *               must cover), ui/e2e/walkthrough/README.md (the spec table)
 * Tested by:    ui/e2e/walkthrough/11-screens.spec.ts (this file; run by scripts/walkthrough.sh)
 * Touch when:   a screen is added (add its route and slug to `routes()`); a persona is added.
 */
import AxeBuilder from '@axe-core/playwright'
import { test as base, expect, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { env, personaPassword, primary, signIn } from './support'

const OUT = join(process.env.CRB_E2E_OUTPUT_DIR ?? 'test-results-walkthrough', 'screens')
mkdirSync(OUT, { recursive: true })

const PERSONAS = ['viewer', 'operator', 'approver', 'admin'] as const
type Persona = (typeof PERSONAS)[number]
const VIEWPORTS = [
  { width: 1280, height: 900 },
  { width: 375, height: 812 },
] as const

const test = base
test.describe.configure({ mode: 'serial' })

const USERNAMES: Record<Persona, string> = {
  viewer: 'walk-viewer',
  operator: 'walk-operator',
  approver: 'walk-approver',
  admin: env.user,
}
// stable per stack (never per run — a rerun must sign into the accounts an earlier run created); never logged
const PASSWORDS: Record<Persona, string> = {
  viewer: personaPassword(USERNAMES.viewer),
  operator: personaPassword(USERNAMES.operator),
  approver: personaPassword(USERNAMES.approver),
  admin: env.pass,
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies()
  const csrf = cookies.find((c) => c.name === 'crb_csrf')?.value ?? ''
  return { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }
}

interface Ctx {
  repo: string
  runId: string
  taskId: string
}

const ctx: Ctx = { repo: primary().name, runId: '', taskId: '' }

/** Every authenticated route; `about: false` marks the help pages, which are the help and carry no About block. */
function routes(c: Ctx): Array<{ path: string; slug: string; about: boolean }> {
  const r = c.repo
  const list: Array<[string, string, boolean?]> = [
    ['/home', 'home'],
    ['/connect', 'connect'],
    [`/connect/${r}`, 'connect-repo'],
    [`/connect/${r}/measure`, 'connect-repo-measure'],
    ['/results', 'results'],
    ['/decisions', 'decisions'],
    ['/signoff', 'signoff'],
    ['/factory', 'factory'],
    ['/posture', 'posture'],
    ['/runs', 'runs'],
    [c.runId ? `/runs/${c.runId}` : '/runs/none', 'runs-detail'],
    [c.taskId ? `/tasks/${r}/${c.taskId}` : `/tasks/${r}/none`, 'tasks-detail'],
    ['/repos', 'repos'],
    [`/repos/${r}`, 'repos-detail'],
    ['/capability', 'capability'],
    ['/routing', 'routing'],
    ['/oracle', 'oracle'],
    ['/learn', 'learn'],
    ['/ledger', 'ledger'],
    ['/settings', 'settings'],
    ['/help', 'help', false],
    ['/help/docs/OPERATOR', 'help-docs-operator', false],
  ]
  return list.map(([path, slug, about]) => ({ path, slug, about: about ?? true }))
}

/** load → bounded network-idle (pages that poll never go idle) → main heading → a beat. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('load').catch(() => undefined)
  await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => undefined)
  await page
    .getByRole('heading', { level: 1 })
    .first()
    .waitFor({ state: 'visible', timeout: 6000 })
    .catch(() => undefined)
  // let TanStack Query paint the first response and any skeletons resolve
  await page.waitForTimeout(700)
}

async function shot(page: Page, persona: string, slug: string, width: number): Promise<void> {
  const path = join(OUT, `${persona}__${slug}__${width}.png`)
  await page.screenshot({ path, fullPage: true, animations: 'disabled' })
}

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

/** Up to `k` indexes out of `n`: the first, the last and the rest evenly spaced. */
function sample(n: number, k: number): number[] {
  if (n <= k) return Array.from({ length: n }, (_, i) => i)
  const out = new Set<number>()
  for (let i = 0; i < k; i += 1) out.add(Math.round((i * (n - 1)) / (k - 1)))
  return Array.from(out).sort((a, b) => a - b)
}

/** The `role="tooltip"` a hinted element's `aria-describedby` names (the last id: a field lists its description first). */
async function bubbleOf(page: Page, el: Locator): Promise<Locator> {
  const ids = ((await el.getAttribute('aria-describedby')) ?? '').split(' ').filter(Boolean)
  expect(ids.length, 'a hinted element carries aria-describedby').toBeGreaterThan(0)
  return page.locator(`#${ids[ids.length - 1]!.replace(/([:.])/g, '\\$1')}`)
}

/**
 * A hint inside a modal dialog: a native `<dialog>` opened with `showModal()` paints in the
 * browser's top layer, above any z-index, so a bubble portalled to `<body>` is invisible
 * there even though `toBeVisible()` and jsdom say otherwise (verifier, 2026-09-22). This
 * opens "Add a repository", hovers the Name field, and asserts with `elementFromPoint` — which
 * honours the top layer — that the bubble is what paints at its own centre; then that the
 * first keystroke closes it (so it does not cover the next field), and that one Escape with
 * a bubble open closes the bubble and NOT the dialog (the typed value survives).
 */
async function dialogHints(page: Page, where: string): Promise<void> {
  await page.goto('/repos')
  await settle(page)
  await page.getByRole('button', { name: 'Add repo' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a repository' })
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((d) => d.matches(':modal')), `${where}: the dialog is modal (top layer)`).toBe(true)
  const name = dialog.getByLabel(/^Name/)
  await name.hover()
  const tip = await bubbleOf(page, name)
  await expect(tip, `${where}: the Name field's hint did not open on hover`).toBeVisible({ timeout: 1000 })
  await expect(tip).toHaveCSS('opacity', '1')
  const painted = await tip.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    return { onTop: hit === el || el.contains(hit), inDialog: el.closest('dialog') !== null }
  })
  expect(painted.inDialog, `${where}: the bubble is portalled into the dialog, not <body>`).toBe(true)
  expect(painted.onTop, `${where}: the dialog paints over the bubble (elementFromPoint at the bubble's centre is not the bubble)`).toBe(true)
  // typing closes it: the bubble sat under the field, over the next label — and a pointer
  // over the field while typing does not bring it back
  await name.focus()
  await page.keyboard.type('probe')
  await expect(tip, `${where}: the first keystroke did not close the field's hint`).toBeHidden()
  await expect(name).toHaveValue('probe')
  await page.mouse.move(0, 0)
  await name.hover()
  await page.waitForTimeout(250)
  await expect(tip, `${where}: the hint came back over the next field while typing`).toBeHidden()
  // Tab to the next field: its bubble opens on focus; one Escape closes that bubble and
  // NOT the dialog (the typed value survives); a second Escape, with nothing open, closes it
  await page.keyboard.press('Tab')
  const next = page.locator(':focus')
  const nextTip = await bubbleOf(page, next.locator('xpath=ancestor-or-self::*[@data-hint][1]'))
  await expect(nextTip, `${where}: the next field's hint did not open on focus`).toBeVisible({ timeout: 1000 })
  await page.keyboard.press('Escape')
  await expect(nextTip).toBeHidden()
  await expect(dialog, `${where}: Escape with a hint open also closed the dialog`).toBeVisible()
  await expect(name).toHaveValue('probe')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
}

/**
 * Open a sample of the route's hints — hover at desktop width, a touch pointerdown at phone
 * width, where no hover exists — and assert each bubble shows a full sentence, axe stays
 * clean with it open, and Escape closes it.
 */
async function hintSample(page: Page, where: string, width: number): Promise<void> {
  const hinted = page.locator('[data-hint]')
  const n = await hinted.count()
  expect(n, `${where}: no hinted element`).toBeGreaterThan(0)
  for (const i of sample(n, 5)) {
    const el = hinted.nth(i)
    const id = await el.getAttribute('data-hint')
    if (!(await el.isVisible())) continue // a hidden-below-md column header at 375 px
    await el.scrollIntoViewIfNeeded()
    // the scroll event that scrollIntoView queues lands on the next frame and would close a
    // bubble that opened before it (a bubble closes on scroll by design): let it pass first
    await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))))
    // a phone has no hover: the touch path is the `pointerdown` a tap begins with, dispatched
    // on the trigger itself — a full tap would also click, and a hinted nav link or table row
    // would navigate away from the route under test
    if (width === 375) await el.dispatchEvent('pointerdown', { pointerType: 'touch', isPrimary: true, bubbles: true, cancelable: true })
    else await el.hover()
    const tip = await bubbleOf(page, el)
    await expect(tip, `${where}: hint ${id} did not open on ${width === 375 ? 'tap' : 'hover'}`).toBeVisible({ timeout: 1000 })
    await expect(tip).toHaveAttribute('role', 'tooltip')
    // let the 120 ms fade finish: axe samples the blended colour of a half-faded bubble as a contrast failure
    await expect(tip).toHaveCSS('opacity', '1')
    const text = (await tip.textContent()) ?? ''
    expect(text.length, `${where}: hint ${id} is too short to explain anything`).toBeGreaterThanOrEqual(40)
    expect(text.trim().endsWith('.'), `${where}: hint ${id} is not a sentence`).toBe(true)
    expect(await tip.locator('a').count(), `${where}: hint ${id} contains a link`).toBe(0)
    const a11y = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
    expect(a11y.violations, `${where}: axe with hint ${id} open: ${JSON.stringify(a11y.violations, null, 2)}`).toEqual([])
    await page.keyboard.press('Escape')
    await expect(tip, `${where}: hint ${id} did not close on Escape`).toBeHidden()
    if (width === 375) await page.mouse.move(0, 0)
  }
}

test.describe('11-screens: every route × persona × width, with the About block', () => {
  test('accounts exist and the run / task anchors are known (admin, via the API)', async ({ page, request }) => {
    await signIn(page)
    const headers = await csrfHeaders(page)
    const existing = await page.request.get(`${env.baseUrl}/api/v1/users`)
    expect(existing.ok(), `GET /users → ${existing.status()}`).toBeTruthy()
    const items = ((await existing.json()) as { items: Array<{ username: string; role: string }> }).items
    let reused = 0
    for (const p of ['viewer', 'operator', 'approver'] as const) {
      if (items.some((u) => u.username === USERNAMES[p])) {
        // an earlier run (another process) created it: the stable password must open it, or
        // every persona test below fails on a hash the stack never held. `request` is its own
        // cookie jar, so the admin session on `page` is untouched.
        const login = await request.post(`${env.baseUrl}/api/v1/auth/login`, { data: { username: USERNAMES[p], password: PASSWORDS[p] } })
        expect(login.status(), `POST /auth/login as existing ${USERNAMES[p]} with the stable password → ${login.status()}`).toBe(200)
        reused += 1
        continue
      }
      const res = await page.request.post(`${env.baseUrl}/api/v1/users`, {
        headers,
        data: { username: USERNAMES[p], password: PASSWORDS[p], role: p, display_name: `Walk ${p}` },
      })
      expect(res.status(), `POST /users (${p}) → ${res.status()} ${await res.text()}`).toBe(201)
    }
    // a finished run (prefer succeeded)
    const runs = await page.request.get(`${env.baseUrl}/api/v1/runs?limit=50`)
    if (runs.ok()) {
      const rj = (await runs.json()) as { items: Array<{ run_id?: string; id?: string; status: string; repo?: string }> }
      const done = rj.items.find((x) => x.status === 'succeeded') ?? rj.items.find((x) => ['failed', 'cancelled'].includes(x.status))
      ctx.runId = (done?.run_id ?? done?.id ?? '') as string
    }
    const tasks = await page.request.get(`${env.baseUrl}/api/v1/repos/${encodeURIComponent(ctx.repo)}/tasks?limit=5`)
    if (tasks.ok()) {
      const tj = (await tasks.json()) as { items: Array<{ task_id?: string; id?: string }> }
      ctx.taskId = (tj.items[0]?.task_id ?? tj.items[0]?.id ?? '') as string
    }
    test.info().annotations.push({ type: 'note', description: `repo=${ctx.repo} run=${ctx.runId || '(none)'} task=${ctx.taskId || '(none)'} accounts_reused=${reused} out=${OUT}` })
  })

  for (const persona of PERSONAS) {
    for (const vp of VIEWPORTS) {
      test(`${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen`, async ({ page }) => {
        test.setTimeout(6 * 60_000)
        await page.setViewportSize({ width: vp.width, height: vp.height })
        // /login as the signed-out screen first
        await page.goto('/login')
        await settle(page)
        await shot(page, persona, 'login', vp.width)
        await signIn(page, USERNAMES[persona], PASSWORDS[persona])
        for (const r of routes(ctx)) {
          await page.goto(r.path)
          await settle(page)
          await shot(page, persona, r.slug, vp.width)
          if (vp.width === 375) {
            // the top bar is two rows on a phone (brand; pill · role · help · theme · sign out) —
            // never three: a third row is ~400 px of chrome before the content
            const bar = page.getByRole('banner').locator('> div').first()
            const box = await bar.boundingBox()
            expect(box?.height ?? 0, `${persona} @ 375 ${r.path}: the top bar wrapped past two rows (${box?.height} px)`).toBeLessThan(130)
          }
          const about = page.getByTestId('about-this-screen')
          if (r.about) {
            await expect(about, `${persona} @ ${vp.width} ${r.path}: no About this screen block`).toHaveCount(1)
            await expect(about.getByText('About this screen')).toBeVisible()
          } else {
            await expect(about, `${persona} @ ${vp.width} ${r.path}: the help pages carry no About block`).toHaveCount(0)
          }
          await hintSample(page, `${persona} @ ${vp.width} ${r.path}`, vp.width)
        }
        if (vp.width === 1280) {
          // the keyboard path: focus shows a hinted control's bubble, Tab away hides it
          await page.goto('/results')
          await settle(page)
          let shown = 0
          let previous: Locator | null = null
          for (let i = 0; i < 20; i += 1) {
            await page.keyboard.press('Tab')
            if (previous) await expect(previous, `${persona} @ 1280 /results: the hint stayed open after Tab moved on`).toBeHidden()
            previous = null
            const active = page.locator(':focus')
            if ((await active.count()) === 0) break
            const trigger = active.locator('xpath=ancestor-or-self::*[@data-hint][1]')
            if ((await trigger.count()) === 0) continue
            const tip = await bubbleOf(page, trigger)
            await expect(tip, `${persona} @ 1280 /results: focus did not open the hint on tab stop ${i + 1}`).toBeVisible({ timeout: 1000 })
            shown += 1
            previous = tip
          }
          expect(shown, `${persona} @ 1280 /results: no hinted element among the first 20 tab stops`).toBeGreaterThan(0)
        }
        if (vp.width === 1280 && persona === 'operator') await dialogHints(page, `${persona} @ 1280 /repos`)
        await page.context().clearCookies()
      })
    }
  }
})
