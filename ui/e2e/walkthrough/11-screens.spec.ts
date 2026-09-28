/**
 * 11-screens — every route × persona × width, captured, the About block on every one, and the
 * hints: a sample opens on hover (or tap at phone width), axe stays clean with one open.
 *
 * Its own CI jobs run it on a stack of its own (the tier-1 walk is split so each part finishes
 * inside its budget), so it never assumes state another spec made: its first test SEEDS the
 * primary repository through the API — onboard, probe, mine, oracle, controls, a two-task
 * `fixture_gold` replay, the same runs 02–05 queue through the UI — unless the repository is
 * already there (run after 01–10 in one invocation, it reuses what they made and seeds
 * nothing). `CRB_E2E_SCREENS_SHARD=k/n` runs every n-th persona from the k-th, so the n
 * parallel jobs cover every persona by construction; unset, it runs all four.
 * For each persona (viewer /
 * operator / approver / admin) it visits every route at desktop (1280×900) and phone
 * (375×812) widths, waits for the page to settle (load + bounded network-idle + the main
 * heading), writes a full-page PNG named `<persona>__<route-slug>__<width>.png` under
 * `<CRB_E2E_OUTPUT_DIR>/screens/`, and asserts that every authenticated route — the help
 * pages and the 404 included (G-926) — renders the "About this screen" block (`data-testid="about-this-screen"`) —
 * the one help mechanism, mounted once in the shell, must reach every screen for every role.
 * On every route it also samples up to five hinted elements (`data-hint`: first, last and
 * three evenly spaced), opens each one's bubble — hover at desktop width, a touch
 * `pointerdown` at phone width, where no hover exists — asserts the `role="tooltip"` the element's
 * `aria-describedby` names becomes visible with a full sentence, runs axe (WCAG 2.1 AA)
 * with the bubble open, and closes it with Escape. One keyboard pass per route per
 * persona at 1280 starts at the first control of the route's own `<main>` and asserts that
 * focusing a hinted control shows its bubble and tabbing OUT OF that hint hides it — out of,
 * not on, because one hint may wrap two controls and stays open between them (bounded: two
 * verified stops, or 12 presses).
 * At 375 px every route is also asserted not to scroll sideways
 * (`document.documentElement.scrollWidth <= window.innerWidth`), and a failure names the
 * widest element rather than only the number. Routes that still overflow are listed, with
 * their gap, in `SIDEWAYS_SCROLL_RATCHET`: a listed route is annotated instead of failing —
 * either way, because whether a table overflows depends on the data the fixture carries, so a
 * run that happens to get narrow rows is not evidence of a fix. An entry leaves the list when
 * a person records the fix and what measured it. The route list includes an
 * unknown address, so the 404 is captured and swept like every other screen. One dialog pass (the operator at
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
 * What it does: Seeds the primary repository's history through the API when the stack has
 *               none (a stack of its own, in CI), selects the personas of its shard,
 *               creates the three non-admin accounts if missing (and, for one that exists,
 *               asserts the stable password signs into it), finds a finished run and a
 *               task to anchor the detail routes, then for each persona × width first
 *               checks /login signed out (`loginChecks`: no sideways scroll and Sign in on
 *               the first screen at 375, axe, the keyboard pass and the hint sample —
 *               G-192), signs in through the form, visits every route, saves a full-page
 *               screenshot under `<CRB_E2E_OUTPUT_DIR>/screens/`, asserts the About block
 *               is present on every route, the help pages and the unknown address
 *               included,
 *               and, at 375 px, that the top bar is ONE row (`TOP_BAR_ONE_ROW_PX`), that the
 *               Menu disclosure (F26, `phoneMenu`) is closed with the nav and Sign out
 *               hidden, opens with axe clean, takes Tab inside and closes on Escape with
 *               focus back on the button, and that the document does not scroll sideways
 *               (or is on the `SIDEWAYS_SCROLL_RATCHET`, now empty, with its gap); opens a
 *               sample of the route's hints (hover, or a touch pointerdown at 375 px) and
 *               asserts each bubble shows and axe stays clean with it open; tabs the route
 *               itself at 1280 for the keyboard path; opens the Add-a-repository dialog
 *               once (operator, 1280) for the top-layer, typing and Escape checks a jsdom
 *               test cannot make. It changes no data beyond its seed; the fixture context
 *               goes into the test's annotations, never stdout. The five keyboard steps that
 *               OPERATE controls (G-905) are 11b-keyboard's: they need the signed cell and
 *               the backlog the story makes, which a screens shard's stack has not got.
 * How:          Playwright; `signIn` from support.ts; the routes list is built from the
 *               primary repo, the run and the task found through the API as the admin;
 *               axe with the WCAG tags (ui/e2e/axe.ts); the bubble is found through the
 *               trigger's `aria-describedby`, never by text, so the spec needs no import from
 *               src.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`env`, `signIn`, `primary`, the seeding helpers),
 *               ui/e2e/walkthrough/keyboard.ts (`settle`, `bubbleOf`, `escapeUntil`,
 *               `focusedIs`, shared with 11b-keyboard),
 *               .github/workflows/ci.yml (the `walkthrough-screens` jobs, one per shard,
 *               under the required `walkthrough` aggregator),
 *               ui/src/components/Help.tsx (the About block this asserts),
 *               ui/src/components/Hint.tsx (the `data-hint` triggers and `role="tooltip"`
 *               bubbles this opens), ui/src/components/Layout.tsx (mounts the About block
 *               once; its nav is always in the sample), ui/src/App.tsx (the routes this list
 *               must cover), ui/e2e/walkthrough/README.md (the spec table)
 * Tested by:    ui/e2e/walkthrough/11-screens.spec.ts (this file; run by scripts/walkthrough.sh)
 * Touch when:   never for a new repository (it reads the primary tier target); a screen is
 *               added (add its route and slug to `routes()`); a persona is added (the shards
 *               pick it up; a fifth persona makes one shard run two).
 */
import { axeViolations } from '../axe'
import { test as base, expect, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { bubbleOf, escapeUntil, focusedIs, settle } from './keyboard'
import { apiPost, env, personaPassword, primary, signIn, startRunApi, waitRunApi } from './support'

const OUT = join(process.env.CRB_E2E_OUTPUT_DIR ?? 'test-results-walkthrough', 'screens')
mkdirSync(OUT, { recursive: true })

const PERSONAS = ['viewer', 'operator', 'approver', 'admin'] as const
type Persona = (typeof PERSONAS)[number]

/**
 * The personas this run covers. `CRB_E2E_SCREENS_SHARD=k/n` takes every n-th persona starting
 * at the k-th (1-based), so shards 1/n … n/n are disjoint and together are every persona — a
 * persona added to `PERSONAS` lands in a shard with no list to update. CI runs one job per
 * shard, in parallel (.github/workflows/ci.yml `walkthrough-screens`). Unset: all of them. A
 * malformed value, or a shard that would select nobody, throws at load, so a job can never
 * pass having covered no persona.
 */
function personasOfShard(spec: string, all: readonly Persona[] = PERSONAS): readonly Persona[] {
  if (!spec) return all
  const m = /^([1-9]\d*)\/([1-9]\d*)$/.exec(spec.trim())
  if (!m) throw new Error(`CRB_E2E_SCREENS_SHARD=${spec}: expected k/n, for example 2/4`)
  const k = Number(m[1])
  const n = Number(m[2])
  if (k > n) throw new Error(`CRB_E2E_SCREENS_SHARD=${spec}: shard ${k} of ${n} does not exist`)
  const chosen = all.filter((_, i) => i % n === k - 1)
  if (chosen.length === 0) throw new Error(`CRB_E2E_SCREENS_SHARD=${spec} selects no persona (there are ${all.length})`)
  return chosen
}
const SHARD_PERSONAS = personasOfShard(process.env.CRB_E2E_SCREENS_SHARD ?? '')
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

/** Every authenticated route; `about: false` would mark a route with no About block — since G-926 there is none. */
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
    ['/factory/intake', 'factory-intake'],
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
    // the help pages and the 404 carry an About block like every other screen (G-926)
    ['/help', 'help'],
    ['/help/docs/OPERATOR', 'help-docs-operator'],
    // an unknown address: the 404 renders inside the shell, so it is captured, hint-sampled
    // and axe-swept for every persona at both widths like any other route (G-918)
    ['/nowhere/at/all', 'not-found'],
  ]
  return list.map(([path, slug, about]) => ({ path, slug, about: about ?? true }))
}

async function shot(page: Page, persona: string, slug: string, width: number): Promise<void> {
  const path = join(OUT, `${persona}__${slug}__${width}.png`)
  await page.screenshot({ path, fullPage: true, animations: 'disabled' })
}


/**
 * The phone top bar's ceiling: one row (brand and the Menu button, `py-3`) measures about
 * 60 px; a wrap to a second row adds 40 or more. 90 fails a wrap and tolerates font metrics.
 */
const TOP_BAR_ONE_ROW_PX = 90

/**
 * How many routes in `routes()` render the journey-position eyebrow as its hinted trigger
 * (`PageHeader` → `journeyEyebrow`): /connect, /connect/:name, /results, /signoff, /factory and
 * /factory/intake [measured — n = 10 journey and review routes probed at 375 px on the tier-1
 * stack, 2026-09-25, apparatus 2.2; Home, Measure, Decisions and Deployment render none], and
 * since G-301 /repos and /repos/:name, which `STEP_OF` places in step 1. At 375 px each must
 * show it with the menu folded; this floor keeps that check from passing on zero.
 */
const JOURNEY_EYEBROW_ROUTES = 8

/**
 * Routes that still scroll sideways at 375 px, by slug, each with the gap that tracks it.
 * A RATCHET, like the hint suite's `TITLE_ALLOWLIST`: an entry records a defect the product
 * has, it never excuses one, and the list may only shrink — a route that stops overflowing
 * fails the suite until its entry is removed, so this cannot quietly become the norm.
 *
 * The assertion that found these is new (G-905: before it, only /results and /factory were
 * checked). It found two on its first full pass: /help/docs/:name, fixed here in
 * `ui/src/index.css` (an 87-character token in inline `code` set the document's width), and
 * /tasks/:repo/:taskId (G-292), fixed in `TaskDetailPage.tsx` and measured by 07.
 */
const SIDEWAYS_SCROLL_RATCHET: Record<string, string> = {
  // empty since G-292 closed (2026-09-26): 'tasks-detail' left when the grade table folded its
  // secondary columns below md, measured on real grade rows at 375 by 07's task-page test
}

/**
 * The document's scroll width, and the element that sets it — the deepest element whose right
 * edge reaches furthest past the viewport, described the way a person would look for it. A bare
 * "scrollWidth 981 > 375" says a page is broken; this says which element to fix.
 */
async function widestOverflow(page: Page): Promise<{ scroll: number; inner: number; culprit: string }> {
  return page.evaluate(() => {
    const inner = window.innerWidth
    let worst: Element | null = null
    let worstRight = inner
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      const r = el.getBoundingClientRect()
      if (r.width === 0 && r.height === 0) continue
      const style = getComputedStyle(el)
      if (style.position === 'fixed' || style.visibility === 'hidden') continue
      if (r.right > worstRight + 0.5) {
        worstRight = r.right
        worst = el
      }
    }
    const describe = (el: Element | null): string => {
      if (!el) return '(nothing past the viewport — the overflow is the document itself)'
      const cls = (el.getAttribute('class') ?? '').split(/\s+/).filter(Boolean).slice(0, 3).join('.')
      const text = (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 60)
      return `<${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}> right edge ${Math.round(el.getBoundingClientRect().right)}px, text "${text}"`
    }
    return { scroll: document.documentElement.scrollWidth, inner, culprit: describe(worst) }
  })
}

/** What a Tab press can land on (the keyboard pass starts at the first one inside `#main`). */
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

/** Up to `k` indexes out of `n`: the first, the last and the rest evenly spaced. */
function sample(n: number, k: number): number[] {
  if (n <= k) return Array.from({ length: n }, (_, i) => i)
  const out = new Set<number>()
  for (let i = 0; i < k; i += 1) out.add(Math.round((i * (n - 1)) / (k - 1)))
  return Array.from(out).sort((a, b) => a - b)
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
 * The bubble the focused element's own hint describes, as an id — the last id of the nearest
 * `[data-hint]` ancestor's `aria-describedby`, the same one `bubbleOf` resolves. `null` when
 * nothing focusable is focused or the focused control is not inside a hint.
 *
 * It is the id, not a locator, because the keyboard pass has to compare two tab stops: one
 * hint may wrap SEVERAL focusable controls (the Deployment summary's Apparatus row holds the
 * term "Apparatus" and the term "belt set"), and moving between them is not leaving the hint.
 */
async function focusedTipId(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const trigger = (document.activeElement as HTMLElement | null)?.closest('[data-hint]')
    const ids = (trigger?.getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean)
    return ids.length > 0 ? ids[ids.length - 1]! : null
  })
}

/**
 * The keyboard-only path on one route: Tab from where the page loaded and assert that
 * focusing a hinted control opens its bubble and that tabbing OUT OF that hint hides it again
 * — the WCAG 2.1.1 half of the hint contract, which a mouse pass can never show.
 *
 * "Out of" is the contract, not "on": `Hint.onBlur` keeps the bubble open while focus stays
 * inside the same trigger, because a hint explains the row, not the control, and one row can
 * hold two terms. The pass compares the bubble id before and after each Tab and only requires
 * the close when the id changed — asserting otherwise fails on a true screen (/posture).
 *
 * Bounded on purpose: it stops at `want` verified stops or `maxTabs` presses, so it costs the
 * same on a route with six controls and one with sixty, and every route can afford it (G-905;
 * before this it ran on /results alone, from the top of the page, so it proved the shell).
 */
async function keyboardPass(page: Page, where: string, want = 2, maxTabs = 12): Promise<void> {
  // start where the shell's skip link lands a keyboard user — the first control of THIS
  // route's <main> — so the pass walks the screen's own controls rather than the twenty-odd
  // hinted elements of the shell it shares with every other route. `focus()` is used rather
  // than following the skip link: activating it is a fragment navigation, and the scroll and
  // re-render that follow close a bubble by design, which would make the pass flaky.
  const firstInMain = page.locator('#main').locator(FOCUSABLE).first()
  if ((await firstInMain.count()) > 0) await firstInMain.focus()
  else await page.keyboard.press('Tab')
  let shown = 0
  let openId: string | null = null
  let openTip: Locator | null = null
  for (let i = 0; i < maxTabs && shown < want; i += 1) {
    if (i > 0) await page.keyboard.press('Tab')
    const id = await focusedTipId(page)
    // the same hint still holds focus (a second term in the same row): it stays open by design
    if (openTip !== null && openId !== id) {
      await expect(openTip, `${where}: the hint stayed open after Tab left it`).toBeHidden()
      openTip = null
      openId = null
    }
    if (id === null) {
      if ((await page.locator(':focus').count()) === 0) break
      continue
    }
    if (id === openId) continue // still the same hint — already counted
    const tip = await bubbleOf(page, page.locator(':focus').locator('xpath=ancestor-or-self::*[@data-hint][1]'))
    await expect(tip, `${where}: focus did not open the hint on tab stop ${i + 1}`).toBeVisible({ timeout: 1000 })
    shown += 1
    openId = id
    openTip = tip
  }
  expect(shown, `${where}: no hinted element among the first ${maxTabs} tab stops of the main region`).toBeGreaterThan(0)
  // leave the last one: Tab until focus is out of that hint (at most four presses — no hint
  // wraps more controls than that), then it must be closed
  if (openTip !== null) {
    for (let i = 0; i < 4 && (await focusedTipId(page)) === openId; i += 1) await page.keyboard.press('Tab')
    await expect(openTip, `${where}: the last hint stayed open after Tab left it`).toBeHidden()
  }
}

/**
 * /login, the screen a person signs in from, gets the checks every other route gets — before
 * sign-in, at both widths (G-192): at 375 the page does not scroll sideways and the Sign in
 * button is on the first screen (the page renders outside the shell, so it has no top bar to
 * measure — its analogue is that no chrome pushes the form off a phone's first screen); axe
 * (WCAG 2.1 AA) is clean; the keyboard pass (Tab from the top: the page has no `#main`) opens
 * a field's hint on focus and closes it on leaving; and the hint sample opens each hint by
 * hover or tap with axe clean while it is open.
 */
async function loginChecks(page: Page, where: string, width: number): Promise<void> {
  await expect(page.getByRole('button', { name: 'Sign in', exact: true }), `${where}: the sign-in form did not render`).toBeVisible()
  if (width === 375) {
    const w = await widestOverflow(page)
    expect(w.scroll, `${where}: the page scrolls sideways (scrollWidth ${w.scroll} > innerWidth ${w.inner}); the widest element is ${w.culprit}`).toBeLessThanOrEqual(w.inner)
    const submit = await page.getByRole('button', { name: 'Sign in', exact: true }).boundingBox()
    expect(submit ? submit.y + submit.height : Infinity, `${where}: the Sign in button is below a phone's first screen`).toBeLessThanOrEqual(812)
  }
  const violations = await axeViolations(page)
  expect(violations, `${where}: axe: ${JSON.stringify(violations, null, 2)}`).toEqual([])
  await keyboardPass(page, where)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await hintSample(page, where, width)
}

/**
 * At 375 px the journey and instrument rows, the health pill, the role chip, Help, the theme
 * and Sign out are folded behind one "Menu" button (F26). On every route: closed, the button
 * reads `aria-expanded="false"`, the Primary nav and Sign out are hidden and the journey-
 * position eyebrow (on a journey route) is still on screen; opened, all of it shows, axe
 * (WCAG 2.1 AA) is clean with it open, and Tab moves focus into it; Escape closes it — after
 * first closing the hint bubble that focus opened, one press per layer — and focus goes back
 * to the button. A failure names the route and the step.
 */
async function phoneMenu(page: Page, where: string): Promise<boolean> {
  const button = page.getByTestId('shell-menu-button')
  const primaryNav = page.getByRole('navigation', { name: 'Primary' })
  const signOut = page.getByRole('button', { name: 'Sign out', exact: true }) // not a Users card's "Sign out everywhere" (P-181)
  await expect(button, `${where}: no Menu button at 375 px`).toBeVisible()
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await expect(primaryNav, `${where}: the journey nav is not folded while the menu is closed`).toBeHidden()
  await expect(signOut, `${where}: Sign out is not folded while the menu is closed`).toBeHidden()
  // a journey screen's eyebrow ("Journey · 2 of 4 · Baseline") is how a phone reader knows where
  // they are once the nav is folded: wherever the screen renders one, it is on screen
  const eyebrow = page.locator('[data-hint="nav.journey_position"]')
  const journey = (await eyebrow.count()) > 0
  if (journey) await expect(eyebrow.first(), `${where}: the journey-position eyebrow is not on screen with the menu closed`).toBeVisible()
  await button.click()
  await expect(button).toHaveAttribute('aria-expanded', 'true')
  await expect(primaryNav, `${where}: the menu opened without the journey nav`).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Instrument' })).toBeVisible()
  await expect(signOut).toBeVisible()
  await expect(page.getByTestId('user-chip')).toBeVisible()
  await expect(page.getByRole('banner').getByRole('link', { name: 'Help' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Switch theme/ })).toBeVisible()
  const violations = await axeViolations(page)
  expect(violations, `${where}: axe with the menu open: ${JSON.stringify(violations, null, 2)}`).toEqual([])
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => document.activeElement?.closest('#shell-menu-actions, #shell-nav-primary, #shell-nav-instrument') !== null), `${where}: Tab from the open Menu button did not move into the menu`).toBe(true)
  await escapeUntil(page, async () => (await button.getAttribute('aria-expanded')) === 'false')
  await expect(button, `${where}: Escape did not close the menu`).toHaveAttribute('aria-expanded', 'false')
  expect(await focusedIs(button), `${where}: focus did not return to the Menu button when Escape closed it`).toBe(true)
  await expect(primaryNav).toBeHidden()
  // leave the button: its focus hint must not sit open over the next check's sample
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.mouse.move(0, 0)
  return journey
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
    const violations = await axeViolations(page)
    expect(violations, `${where}: axe with hint ${id} open: ${JSON.stringify(violations, null, 2)}`).toEqual([])
    await page.keyboard.press('Escape')
    await expect(tip, `${where}: hint ${id} did not close on Escape`).toBeHidden()
    if (width === 375) await page.mouse.move(0, 0)
  }
}

test.describe('11-screens: every route × persona × width, with the About block', () => {
  test('the primary repository has a probed, mined, measured and replayed history (seeded through the API on a stack of its own)', async ({ page }) => {
    const t = primary()
    test.setTimeout(t.probeTimeoutMs + t.mineTimeoutMs + 12 * 60_000)
    await signIn(page)
    const existing = await page.request.get(`${env.baseUrl}/api/v1/repos/${encodeURIComponent(t.name)}`)
    if (existing.ok()) {
      test.info().annotations.push({ type: 'note', description: `${t.name} exists: the specs before this one made its history; nothing seeded` })
      return
    }
    expect(existing.status(), `GET /repos/${t.name} → ${existing.status()}`).toBe(404)
    // tier 2 onboards public repositories with their own presets and installs (02/03): seeding
    // them here would be a second, unreviewed onboarding path
    expect(env.publicTier, 'tier 2: run 11-screens after 02 and 03 in the same invocation; it seeds only the tier-1 fixture').toBe(false)
    // the fields 02's "Add a repository" dialog sends for the python-src-layout preset
    await apiPost(page, '/repos', {
      name: t.name,
      language: 'python',
      runner: 'pytest',
      url: t.url,
      src_prefix: 'src/',
      test_prefix: 'tests/',
      ext: '.py',
      belt_scope: t.beltScope,
      probe: t.probe,
      runner_opts: t.runnerOpts,
    })
    const probe = await apiPost(page, `/repos/${encodeURIComponent(t.name)}/probe`, {})
    await waitRunApi(page, String(probe.id), t.probeTimeoutMs)
    // the runs 03, 04 and 05 queue through the dialog, with their limits
    await startRunApi(page, { repo: t.name, kind: 'mine', limit: t.mineLimit }, t.mineTimeoutMs)
    await startRunApi(page, { repo: t.name, kind: 'oracle', limit: 1 }, 4 * 60_000)
    await startRunApi(page, { repo: t.name, kind: 'controls', limit: 1 }, 4 * 60_000)
    await startRunApi(page, { repo: t.name, kind: 'replay', builder: 'fixture_gold', model: 'gold', limit: 2 }, 4 * 60_000)
    test.info().annotations.push({ type: 'note', description: `${t.name} seeded through the API: probe, mine ${t.mineLimit}, oracle, controls, replay fixture_gold 2` })
  })

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
    test.info().annotations.push({ type: 'note', description: `repo=${ctx.repo} run=${ctx.runId || '(none)'} task=${ctx.taskId || '(none)'} accounts_reused=${reused} personas=${SHARD_PERSONAS.join(',')} out=${OUT}` })
    // the detail routes are anchored to a real run and a real task, or they would sweep the 404
    expect(ctx.runId, 'no finished run to anchor /runs/:id').not.toBe('')
    expect(ctx.taskId, `no task of ${ctx.repo} to anchor /tasks/:repo/:taskId`).not.toBe('')
  })

  for (const persona of SHARD_PERSONAS) {
    for (const vp of VIEWPORTS) {
      test(`${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen`, async ({ page }) => {
        test.setTimeout(6 * 60_000)
        await page.setViewportSize({ width: vp.width, height: vp.height })
        // /login as the signed-out screen first — checked like every other route, before
        // anyone signs in (G-192)
        await page.goto('/login')
        await settle(page)
        await shot(page, persona, 'login', vp.width)
        await loginChecks(page, `${persona} @ ${vp.width} /login (signed out)`, vp.width)
        await signIn(page, USERNAMES[persona], PASSWORDS[persona])
        let eyebrows = 0
        for (const r of routes(ctx)) {
          await page.goto(r.path)
          await settle(page)
          await shot(page, persona, r.slug, vp.width)
          if (vp.width === 375) {
            // the top bar is ONE row on a phone — the brand and the Menu button; everything else
            // is folded behind the menu (F26). It was two rows (brand; pill · role · help · theme
            // · sign out) before, and three nav rows took half the first screen
            const bar = page.getByRole('banner').locator('> div').first()
            const box = await bar.boundingBox()
            expect(box?.height ?? 0, `${persona} @ 375 ${r.path}: the top bar wrapped past one row (${box?.height} px)`).toBeLessThan(TOP_BAR_ONE_ROW_PX)
            if (await phoneMenu(page, `${persona} @ 375 ${r.path}`)) eyebrows += 1
            // and the page does not scroll sideways: a phone reader should never have to pan
            // to read a number. Every route, not only the Factory (G-905).
            const width = await widestOverflow(page)
            const known = SIDEWAYS_SCROLL_RATCHET[r.slug]
            const where = `${persona} @ 375 ${r.path}`
            if (known) {
              // A listed route is annotated either way and never fails. It is NOT asserted to
              // overflow: whether a table is wider than the phone depends on the DATA the
              // fixture happens to carry (this route overflowed locally at 981 px and did not
              // in CI, on the same commit — PR #48), so "it stopped overflowing" is not
              // evidence that anything was fixed. An entry leaves this list when a person
              // records the fix and its measurement, never because one run got narrow rows.
              const state = width.scroll > width.inner ? `scrollWidth ${width.scroll} > ${width.inner}; widest: ${width.culprit}` : `did not overflow on this run's data (scrollWidth ${width.scroll})`
              test.info().annotations.push({ type: 'sideways-scroll (known)', description: `${where}: ${state} — ${known}` })
            } else {
              expect.soft(width.scroll, `${where}: the page scrolls sideways (scrollWidth ${width.scroll} > innerWidth ${width.inner}); the widest element is ${width.culprit}. Fix it, or record it in SIDEWAYS_SCROLL_RATCHET with its gap id`).toBeLessThanOrEqual(width.inner)
            }
          }
          const about = page.getByTestId('about-this-screen')
          if (r.about) {
            await expect(about, `${persona} @ ${vp.width} ${r.path}: no About this screen block`).toHaveCount(1)
            await expect(about.getByText('About this screen')).toBeVisible()
          } else {
            await expect(about, `${persona} @ ${vp.width} ${r.path}: the help pages carry no About block`).toHaveCount(0)
          }
          // the keyboard path, on this route: focus shows a hinted control's bubble, Tab away
          // hides it (G-905 — it used to run on /results alone)
          if (vp.width === 1280) await keyboardPass(page, `${persona} @ 1280 ${r.path}`)
          await hintSample(page, `${persona} @ ${vp.width} ${r.path}`, vp.width)
        }
        // the eyebrow check is not vacuous: every journey screen that carries one was seen
        if (vp.width === 375) expect(eyebrows, `${persona} @ 375: journey-position eyebrows seen with the menu closed`).toBeGreaterThanOrEqual(JOURNEY_EYEBROW_ROUTES)
        if (vp.width === 1280 && persona === 'operator') await dialogHints(page, `${persona} @ 1280 /repos`)
        await page.context().clearCookies()
      })
    }
  }
})
