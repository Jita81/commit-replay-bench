/**
 * 11-screens — every route × persona × width, captured, and the About block on every one.
 *
 * Runs after 01–09 so the stack carries the data they produced. For each persona (viewer /
 * operator / approver / admin) it visits every route at desktop (1280×900) and phone
 * (375×812) widths, waits for the page to settle (load + bounded network-idle + the main
 * heading), writes a full-page PNG named `<persona>__<route-slug>__<width>.png` under
 * `<CRB_E2E_OUTPUT_DIR>/screens/`, and asserts that every authenticated route except the
 * help pages renders the "About this screen" block (`data-testid="about-this-screen"`) —
 * the one help mechanism, mounted once in the shell, must reach every screen for every role.
 *
 * Accounts: the viewer / operator / approver are created through the API as the admin
 * (POST /users, CSRF double-submit) if missing. Passwords are generated per run and never
 * printed. Nothing here calls a model or spends.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 11 (screens) — the visual record of every route for every
 *               role at two widths, and the About-block ratchet on the live stack.
 * What it does: Creates the three non-admin accounts if missing, finds a finished run and a
 *               task to anchor the detail routes, then for each persona × width signs in
 *               through the form, visits every route, saves a full-page screenshot under
 *               `<CRB_E2E_OUTPUT_DIR>/screens/` and asserts the About block is present on
 *               every route that is not /help. It changes no data.
 * How:          Playwright; `signIn` from support.ts; the routes list is built from the
 *               primary repo, the run and the task found through the API as the admin.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`env`, `signIn`, `primary`),
 *               ui/src/components/Help.tsx (the About block this asserts),
 *               ui/src/components/Layout.tsx (mounts it once), ui/src/App.tsx (the routes
 *               this list must cover), ui/e2e/walkthrough/README.md (the spec table)
 * Tested by:    ui/e2e/walkthrough/11-screens.spec.ts (this file; run by scripts/walkthrough.sh)
 * Touch when:   a screen is added (add its route and slug to `routes()`); a persona is added.
 */
import { test as base, expect, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { env, primary, signIn } from './support'

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

// per-run passwords for the created accounts (never logged)
const PASSWORDS: Record<Persona, string> = {
  viewer: `Wv-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`,
  operator: `Wo-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`,
  approver: `Wa-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`,
  admin: env.pass,
}
const USERNAMES: Record<Persona, string> = {
  viewer: 'walk-viewer',
  operator: 'walk-operator',
  approver: 'walk-approver',
  admin: env.user,
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

test.describe('11-screens: every route × persona × width, with the About block', () => {
  test('accounts exist and the run / task anchors are known (admin, via the API)', async ({ page }) => {
    await signIn(page)
    const headers = await csrfHeaders(page)
    const existing = await page.request.get(`${env.baseUrl}/api/v1/users`)
    expect(existing.ok(), `GET /users → ${existing.status()}`).toBeTruthy()
    const items = ((await existing.json()) as { items: Array<{ username: string; role: string }> }).items
    for (const p of ['viewer', 'operator', 'approver'] as const) {
      if (items.some((u) => u.username === USERNAMES[p])) continue
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
    console.log(`11-screens: repo=${ctx.repo} run=${ctx.runId || '(none)'} task=${ctx.taskId || '(none)'} out=${OUT}`)
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
          const about = page.getByTestId('about-this-screen')
          if (r.about) {
            await expect(about, `${persona} @ ${vp.width} ${r.path}: no About this screen block`).toHaveCount(1)
            await expect(about.getByText('About this screen')).toBeVisible()
          } else {
            await expect(about, `${persona} @ ${vp.width} ${r.path}: the help pages carry no About block`).toHaveCount(0)
          }
        }
        await page.context().clearCookies()
      })
    }
  }
})
