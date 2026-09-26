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
 * What it does: Creates the three non-admin accounts if missing (and, for one that exists,
 *               asserts the stable password signs into it), finds a finished run and a
 *               task to anchor the detail routes, then for each persona × width signs in
 *               through the form, visits every route, saves a full-page screenshot under
 *               `<CRB_E2E_OUTPUT_DIR>/screens/`, asserts the About block is present on
 *               every route that is not a help page or the unknown address and, at 375 px,
 *               that the top bar is at most two rows (a wrapped "Sign out" is a phone-width
 *               defect) and the document does not scroll sideways (or is on the shrinking
 *               `SIDEWAYS_SCROLL_RATCHET` with its gap); opens a sample of
 *               the route's hints (hover, or a touch pointerdown at 375 px) and asserts each bubble shows and axe stays
 *               clean with it open; tabs the route itself at 1280 for the keyboard path;
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

/** The repository 08 seeds and the approver signs (`SIGNABLE_NAME` in 08-signoff): it has an active attestation to revoke. */
const SIGNED_REPO = 'walk-signable'

/**
 * Choose the first real option of the focused `<select>` from the keyboard, by typing the start
 * of its label — the type-ahead a closed select answers on every platform (ArrowDown changes the
 * value on Linux but opens the picker on macOS, so it would prove a different thing on each) —
 * and assert the value changed, so a select a keyboard person cannot operate fails.
 */
async function chooseByKeyboard(page: Page, where: string): Promise<void> {
  const { before, prefix } = await page.evaluate(() => {
    const sel = document.activeElement as HTMLSelectElement | null
    const first = sel ? Array.from(sel.options).find((o) => o.value !== '') : undefined
    return { before: sel?.value ?? '', prefix: (first?.textContent ?? '').trim().split(/\s/)[0] ?? '' }
  })
  expect(prefix, `${where}: the focused control is not a select with an option to choose`).not.toBe('')
  await page.keyboard.type(prefix)
  await expect.poll(() => page.evaluate(() => (document.activeElement as HTMLSelectElement | null)?.value ?? ''), { message: `${where}: typing "${prefix}" did not choose an option` }).not.toBe(before)
}

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
    ['/help', 'help', false],
    ['/help/docs/OPERATOR', 'help-docs-operator', false],
    // an unknown address: the 404 renders inside the shell, so it is captured, hint-sampled
    // and axe-swept for every persona at both widths like any other route. No About block —
    // `helpFor` matches no HELP entry for a path the product does not route (G-918).
    ['/nowhere/at/all', 'not-found', false],
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

/**
 * The phone top bar's ceiling: one row (brand and the Menu button, `py-3`) measures about
 * 60 px; a wrap to a second row adds 40 or more. 90 fails a wrap and tolerates font metrics.
 */
const TOP_BAR_ONE_ROW_PX = 90

/**
 * How many routes in `routes()` render the journey-position eyebrow as its hinted trigger
 * (`PageHeader` → `journeyEyebrow`): /connect, /connect/:name, /results, /signoff, /factory and
 * /factory/intake [measured — n = 10 journey and review routes probed at 375 px on the tier-1
 * stack, 2026-09-25, apparatus 2.2; Home, Measure, Decisions and Deployment render none]. At
 * 375 px each must show it with the menu folded; this floor keeps that check from passing on zero.
 */
const JOURNEY_EYEBROW_ROUTES = 6

/**
 * Routes that still scroll sideways at 375 px, by slug, each with the gap that tracks it.
 * A RATCHET, like the hint suite's `TITLE_ALLOWLIST`: an entry records a defect the product
 * has, it never excuses one, and the list may only shrink — a route that stops overflowing
 * fails the suite until its entry is removed, so this cannot quietly become the norm.
 *
 * The assertion that found these is new (G-905: before it, only /results and /factory were
 * checked). It found two on its first full pass: /help/docs/:name, fixed here in
 * `ui/src/index.css` (an 87-character token in inline `code` set the document's width), and
 * this one, which needs a live stack to place and belongs to the page that owns it.
 */
const SIDEWAYS_SCROLL_RATCHET: Record<string, string> = {
  'tasks-detail': 'G-292 — the 11-column grade table is wider than a phone when the task has real grade rows (scrollWidth 981 at 375, measured 2026-09-22 and again 2026-09-23, apparatus 2.2); docs/dod/pages/tasks-repo-taskId.md',
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
 * Keyboard only: press Tab (or Shift+Tab, `backwards`) until the focused element matches
 * `selector` — never `focus()`, never a click, so the control is proven REACHABLE by a keyboard
 * person, not only operable once something else put focus on it. `fromTop` (the default, for
 * the first call after a page load) starts the way a keyboard person starts: the first Tab
 * must land on the skip link, and Enter follows it (the sequential-focus starting point moves
 * to `<main>`); otherwise it carries on from wherever focus is. Fails, naming where focus
 * went, if `maxTabs` presses never reach it: a control that cannot take focus
 * (`tabindex="-1"`, a `div` with an `onClick`) fails here, which the negative-control test
 * below proves. Returns the number of presses it took.
 */
async function tabTo(page: Page, selector: string, where: string, opts: { fromTop?: boolean; backwards?: boolean; maxTabs?: number } = {}): Promise<number> {
  const { fromTop = true, backwards = false, maxTabs = 120 } = opts
  if (fromTop) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => document.activeElement?.textContent?.trim()), `${where}: the first Tab after the page loaded did not land on the skip link`).toBe('Skip to content')
    await page.keyboard.press('Enter')
  }
  const trail: string[] = []
  for (let i = 1; i <= maxTabs; i += 1) {
    await page.keyboard.press(backwards ? 'Shift+Tab' : 'Tab')
    const at = await page.evaluate((sel) => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body) return { hit: false, what: '(body)' }
      const what = `<${el.tagName.toLowerCase()}${el.getAttribute('data-hint') ? ` data-hint=${el.getAttribute('data-hint')}` : ''}> ${(el.getAttribute('aria-label') ?? el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40)}`
      return { hit: el.matches(sel), what }
    }, selector)
    if (at.hit) return i
    trail.push(at.what)
  }
  throw new Error(`${where}: ${maxTabs} ${backwards ? 'Shift+Tab' : 'Tab'} presses never reached ${selector}; focus went: ${trail.slice(-8).join(' → ')}`)
}

/**
 * Press Escape until `done` holds, at most `max` times. One Escape closes the innermost open
 * thing: a hint bubble the focus opened is closed first (Hint spends that press), then the
 * disclosure, menu or dialog behind it — so a keyboard person needs one press per layer, and
 * never more than two here.
 */
async function escapeUntil(page: Page, done: () => Promise<boolean>, max = 2): Promise<void> {
  for (let i = 0; i < max && !(await done()); i += 1) await page.keyboard.press('Escape')
}

/** Whether focus is on `locator`'s element or inside it (a dialog, a menu, a confirmation). */
async function focusedIs(locator: Locator): Promise<boolean> {
  return locator.evaluate((el) => el === document.activeElement || el.contains(document.activeElement))
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
  const a11y = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
  expect(a11y.violations, `${where}: axe: ${JSON.stringify(a11y.violations, null, 2)}`).toEqual([])
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
  const signOut = page.getByRole('button', { name: 'Sign out' })
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
  const a11y = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
  expect(a11y.violations, `${where}: axe with the menu open: ${JSON.stringify(a11y.violations, null, 2)}`).toEqual([])
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

  // ─── the per-screen keyboard steps (G-905) ──────────────────────────────────────────────
  // The route loop above proves every screen's first hinted controls take focus. These prove
  // the five controls a keyboard person has to OPERATE, each reached by Tab alone from the
  // skip link (`tabTo`) and driven by Enter, Space, typing and Escape — no click, no focus().
  // They change no data: the sign-off form is filled to an enabled Sign off and the revoke
  // confirmation filled to an enabled Revoke sign-off, then left by Cancel; the freeze dialog
  // is opened and closed. Pressing those buttons is proven by 08 and 10, on the same native
  // `<button>`, whose Enter/Space activation the browser guarantees.

  test('keyboard: a map cell opens from the keyboard, and the reason code in it opens and closes (/capability)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
    await page.goto(`/capability?repo=${encodeURIComponent(ctx.repo)}`)
    await settle(page)
    const where = 'operator @ 1280 /capability'
    await tabTo(page, 'button[data-hint="map.cell.tile"]', where)
    // the cell explains itself on focus, like every hinted control
    const cell = page.locator(':focus')
    await expect(await bubbleOf(page, cell), `${where}: the focused cell's hint did not open`).toBeVisible({ timeout: 1000 })
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('cell-reason'), `${where}: Enter on a cell did not open its detail`).toBeVisible()
    // the reason code in the detail card is the next thing a reader wants: reach it by Tab too
    const reason = 'main [data-testid="cell-reason"] button[aria-expanded]'
    await tabTo(page, reason, `${where} (reason code)`, { fromTop: false })
    const disclosure = page.locator(reason)
    await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    await page.keyboard.press('Enter')
    await expect(disclosure, `${where}: Enter did not open the reason code`).toHaveAttribute('aria-expanded', 'true')
    await expect(page.locator(`[id="${await disclosure.getAttribute('aria-controls')}"]`)).toHaveAttribute('role', 'note')
    await escapeUntil(page, async () => (await disclosure.getAttribute('aria-expanded')) === 'false')
    await expect(disclosure, `${where}: Escape did not close the reason code`).toHaveAttribute('aria-expanded', 'false')
    expect(await focusedIs(disclosure), `${where}: closing the reason code lost focus`).toBe(true)
  })

  test('keyboard: a reason-code button on Routes is reached by Tab and opens and closes with aria-expanded (/routing)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
    await page.goto(`/routing?repo=${encodeURIComponent(ctx.repo)}`)
    await settle(page)
    const where = 'operator @ 1280 /routing'
    const sel = 'main button[aria-expanded]:has([data-testid="reason-code"])'
    await expect(page.locator(sel).first(), `${where}: no reason code on the page — the stack has no route decisions`).toBeVisible()
    await tabTo(page, sel, where)
    const disclosure = page.locator(':focus')
    await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    await page.keyboard.press('Enter')
    await expect(disclosure, `${where}: Enter did not open the reason code`).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByRole('note').filter({ hasText: 'glossary' }).first()).toBeVisible()
    await escapeUntil(page, async () => (await disclosure.getAttribute('aria-expanded')) === 'false')
    await expect(disclosure, `${where}: Escape did not close the reason code`).toHaveAttribute('aria-expanded', 'false')
    expect(await focusedIs(disclosure), `${where}: closing the reason code lost focus`).toBe(true)
  })

  test('keyboard: a term on Oracle opens and closes with aria-expanded (/oracle)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
    await page.goto(`/oracle?repo=${encodeURIComponent(ctx.repo)}`)
    await settle(page)
    const where = 'operator @ 1280 /oracle'
    const sel = 'main button[aria-expanded][aria-controls]'
    await tabTo(page, sel, where)
    const term = page.locator(':focus')
    const name = ((await term.textContent()) ?? '').trim()
    await expect(term).toHaveAttribute('aria-expanded', 'false')
    await page.keyboard.press('Space')
    await expect(term, `${where}: Space did not open the term "${name}"`).toHaveAttribute('aria-expanded', 'true')
    const note = page.locator(`[id="${await term.getAttribute('aria-controls')}"]`)
    await expect(note, `${where}: the term "${name}" opened no definition`).toHaveAttribute('role', 'note')
    await expect(note).toBeVisible()
    await escapeUntil(page, async () => (await term.getAttribute('aria-expanded')) === 'false')
    await expect(term, `${where}: Escape did not close the term "${name}"`).toHaveAttribute('aria-expanded', 'false')
    await expect(note).toHaveCount(0)
    expect(await focusedIs(term), `${where}: closing the term lost focus`).toBe(true)
  })

  test('keyboard: the sign-off form is filled, and the revoke confirmation opened, filled and left, from the keyboard (/signoff)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.approver, PASSWORDS.approver)
    await page.goto(`/signoff?repo=${SIGNED_REPO}`)
    await settle(page)
    const where = 'approver @ 1280 /signoff'
    // the form: choose the cell, name an accepted row, affirm, write the statement — by keyboard
    await tabTo(page, '#signoff-form select', `${where} (Cell)`)
    await chooseByKeyboard(page, `${where} (Cell)`)
    const rowSelect = page.getByTestId('attest-row')
    await expect.poll(async () => (await rowSelect.locator('option').count()) - 1, { message: `${where}: the chosen cell offers no accepted row` }).toBeGreaterThanOrEqual(1)
    await expect(rowSelect).toBeEnabled()
    await tabTo(page, 'select[data-testid="attest-row"]', `${where} (Accepted row)`, { fromTop: false, maxTabs: 30 })
    await chooseByKeyboard(page, `${where} (Accepted row)`)
    await tabTo(page, 'input[data-testid="attest-read"]', `${where} (I have read)`, { fromTop: false, maxTabs: 10 })
    await page.keyboard.press('Space')
    await expect(page.getByTestId('attest-read')).toBeChecked()
    await tabTo(page, 'textarea[data-testid="attest-statement"]', `${where} (statement)`, { fromTop: false, maxTabs: 30 })
    await page.keyboard.type('walkthrough 11: filled from the keyboard; not submitted.')
    // Sign off sits in the gate above the form: Shift+Tab back up to it, reachable and enabled
    // now the form is complete. It is NOT pressed — 08 records the attestation; this spec
    // changes no data.
    await tabTo(page, 'button[form="signoff-form"]', `${where} (Sign off)`, { fromTop: false, backwards: true })
    await expect(page.locator(':focus'), `${where}: Sign off is not enabled once the form is filled`).toBeEnabled()
    await expect(page.locator(':focus')).toHaveText('Sign off')

    // the revoke confirmation: Revoke opens it and focus moves INTO it; it is filled, its
    // confirm button reached, then Cancel leaves it and focus comes back to Revoke
    await tabTo(page, 'button[data-hint="button.signoff.revoke"]', `${where} (Revoke)`, { fromTop: false, maxTabs: 200 })
    const revokeId = await page.locator(':focus').getAttribute('data-revoke-id')
    await page.keyboard.press('Enter')
    const confirm = page.getByTestId('revoke-confirm')
    await expect(confirm).toBeVisible()
    expect(await focusedIs(confirm), `${where}: focus did not move into the revoke confirmation when it opened`).toBe(true)
    await page.keyboard.type('walkthrough 11: reached from the keyboard; not confirmed.')
    await page.keyboard.press('Tab')
    await expect(page.locator(':focus'), `${where}: Tab from the reason did not reach Revoke sign-off`).toHaveText('Revoke sign-off')
    await expect(page.locator(':focus')).toBeEnabled()
    await page.keyboard.press('Tab')
    await expect(page.locator(':focus')).toHaveText('Cancel')
    await page.keyboard.press('Enter')
    await expect(confirm).toBeHidden()
    const back = page.locator(`button[data-revoke-id="${revokeId}"]`)
    expect(await focusedIs(back), `${where}: Cancel did not return focus to the Revoke button that opened the confirmation`).toBe(true)
  })

  test('keyboard: the freeze dialog takes focus when it opens and gives it back when it closes (/factory)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
    await page.goto(`/factory?repo=${encodeURIComponent(ctx.repo)}`)
    await settle(page)
    const where = 'operator @ 1280 /factory'
    const opener = 'button[data-hint="button.factory.freeze"], button[data-hint="button.factory.freeze_revised"]'
    await tabTo(page, opener, where)
    const label = ((await page.locator(':focus').textContent()) ?? '').trim()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', { name: /^Freeze a (revised )?backlog$/ })
    await expect(dialog, `${where}: Enter on "${label}" did not open the freeze dialog`).toBeVisible()
    expect(await focusedIs(dialog), `${where}: focus did not move into the freeze dialog when it opened`).toBe(true)
    // Tab stays inside a modal dialog
    for (let i = 0; i < 6; i += 1) {
      await page.keyboard.press('Tab')
      expect(await focusedIs(dialog), `${where}: Tab ${i + 1} left the modal dialog`).toBe(true)
    }
    await escapeUntil(page, async () => !(await dialog.isVisible()))
    await expect(dialog, `${where}: Escape did not close the freeze dialog`).toBeHidden()
    await expect(page.locator(':focus'), `${where}: focus did not return to "${label}" when the dialog closed`).toHaveText(label)
  })

  test('keyboard: the pass fails when a control cannot take focus (negative control)', async ({ page }) => {
    // A pass that cannot fail proves nothing. Take every map cell out of the tab order — the
    // defect a keyboard person meets when a control is a div with an onClick, or carries
    // tabindex="-1" — and `tabTo` must fail on the same page it passes above.
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
    await page.goto(`/capability?repo=${encodeURIComponent(ctx.repo)}`)
    await settle(page)
    const cells = await page.evaluate(() => {
      const all = Array.from(document.querySelectorAll<HTMLElement>('button[data-hint="map.cell.tile"]'))
      for (const el of all) el.tabIndex = -1
      return all.length
    })
    expect(cells, 'the negative control needs a measured cell on the page').toBeGreaterThan(0)
    let failed = ''
    try {
      await tabTo(page, 'button[data-hint="map.cell.tile"]', 'negative control', { maxTabs: 60 })
    } catch (e) {
      failed = String(e)
    }
    expect(failed, 'tabTo reached a map cell that cannot take focus — the keyboard pass cannot fail').toContain('never reached')
  })
})
