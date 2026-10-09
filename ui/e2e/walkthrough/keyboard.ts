/**
 * The keyboard and settling helpers the walkthrough's screen specs share: `settle` (a page is
 * painted), `bubbleOf` (the hint bubble a trigger names), `tabTo` (reach a control by Tab
 * alone), `escapeUntil`, `focusedIs`, `chooseByKeyboard`, and `countPointer` with
 * `pointerEvents` (the guard that the pointer never reached the page).
 *
 * 11-screens sweeps every route for every persona on a stack of its own (its CI jobs are
 * sharded by persona); 11b-keyboard operates the five controls a keyboard person has to use,
 * in the stateful story after 08 and 10 made what they operate. Both drive the page the same
 * way, so the helpers live here once.
 *
 * Navigation
 * ----------
 * What it is:   Shared Playwright helpers for ui/e2e/walkthrough/11-screens.spec.ts and
 *               ui/e2e/walkthrough/11b-keyboard.spec.ts.
 * What it does: Waits for a page to settle; finds a trigger's `role="tooltip"` bubble through
 *               its `aria-describedby`; presses Tab (or Shift+Tab) until focus reaches a
 *               selector, failing with the path focus took; presses Escape once per open
 *               layer; answers whether focus is on or inside an element; chooses a select's
 *               first real option by type-ahead; records every pointer event that reaches a
 *               page, in every document it loads, so a keyboard spec can require none (P-781).
 * How:          `page.keyboard` only — never `focus()` or a click — so a control is proven
 *               reachable, not only operable once something else focused it.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/11-screens.spec.ts and ui/e2e/walkthrough/11b-keyboard.spec.ts
 *               (the callers), ui/src/components/Hint.tsx (the bubbles `bubbleOf` finds),
 *               ui/src/components/Layout.tsx (the skip link `tabTo` starts from)
 * Tested by:    ui/e2e/walkthrough/11b-keyboard.spec.ts (its negative controls prove `tabTo`
 *               fails on a control that cannot take focus, and the pointer guard sees a pointer)
 * Touch when:   never for a new repository; a screen spec needs another way to drive the page
 *               by keyboard (add it here, with a negative control in 11b).
 */
import { expect, type Locator, type Page } from '@playwright/test'

/** load → bounded network-idle (pages that poll never go idle) → main heading → a beat. */
export async function settle(page: Page): Promise<void> {
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

/** The `role="tooltip"` a hinted element's `aria-describedby` names (the last id: a field lists its description first). */
export async function bubbleOf(page: Page, el: Locator): Promise<Locator> {
  const ids = ((await el.getAttribute('aria-describedby')) ?? '').split(' ').filter(Boolean)
  expect(ids.length, 'a hinted element carries aria-describedby').toBeGreaterThan(0)
  return page.locator(`#${ids[ids.length - 1]!.replace(/([:.])/g, '\\$1')}`)
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
 * in 11b-keyboard proves. Returns the number of presses it took.
 */
export async function tabTo(page: Page, selector: string, where: string, opts: { fromTop?: boolean; backwards?: boolean; maxTabs?: number } = {}): Promise<number> {
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
 * never more than two here. That count holds only while no pointer is on the page: a hint
 * under a resting pointer can open between two presses and spend the second (P-781), which is
 * why 11b signs in by keyboard and `countPointer` fails a step the pointer reached.
 */
export async function escapeUntil(page: Page, done: () => Promise<boolean>, max = 2): Promise<void> {
  for (let i = 0; i < max && !(await done()); i += 1) await page.keyboard.press('Escape')
}

/** The pointer events `countPointer` has recorded on each page it armed, oldest first. */
const pointerSeen = new WeakMap<Page, string[]>()

/**
 * Arm `page` to record every pointer event that reaches it — in every document it loads, so
 * one that arrives before a navigation still counts — for `pointerEvents` to report. A
 * keyboard spec requires none: a pointer resting on the page is sent mouseover events as Tab
 * scrolls the page under it (a click-based sign-in left one at 640, 466 on PR #58's CI), the
 * hint it rests on opens, and that bubble spends an Escape the step meant for its control.
 * Call it before the first navigation.
 */
export async function countPointer(page: Page): Promise<void> {
  const seen: string[] = []
  pointerSeen.set(page, seen)
  await page.exposeFunction('__crbPointerSeen', (type: string) => {
    seen.push(type)
  })
  await page.addInitScript(() => {
    const w = window as unknown as { __crbPointerSeen?: (type: string) => Promise<void> }
    for (const type of ['pointerover', 'pointermove', 'pointerdown', 'mouseover', 'mousemove', 'mousedown']) {
      window.addEventListener(type, () => void w.__crbPointerSeen?.(type), { capture: true, passive: true })
    }
  })
}

/**
 * The pointer events recorded on `page` since `countPointer` armed it, oldest first. A
 * round trip to the page first, so a report still in flight from it has arrived.
 */
export async function pointerEvents(page: Page): Promise<readonly string[]> {
  await page.evaluate(() => 0).catch(() => undefined)
  return [...(pointerSeen.get(page) ?? [])]
}

/** Whether focus is on `locator`'s element or inside it (a dialog, a menu, a confirmation). */
export async function focusedIs(locator: Locator): Promise<boolean> {
  return locator.evaluate((el) => el === document.activeElement || el.contains(document.activeElement))
}

/**
 * Choose the first real option of the focused `<select>` from the keyboard, by typing the start
 * of its label — the type-ahead a closed select answers on every platform (ArrowDown changes the
 * value on Linux but opens the picker on macOS, so it would prove a different thing on each) —
 * and assert the value changed, so a select a keyboard person cannot operate fails.
 */
export async function chooseByKeyboard(page: Page, where: string): Promise<void> {
  const { before, prefix } = await page.evaluate(() => {
    const sel = document.activeElement as HTMLSelectElement | null
    const first = sel ? Array.from(sel.options).find((o) => o.value !== '') : undefined
    return { before: sel?.value ?? '', prefix: (first?.textContent ?? '').trim().split(/\s/)[0] ?? '' }
  })
  expect(prefix, `${where}: the focused control is not a select with an option to choose`).not.toBe('')
  await page.keyboard.type(prefix)
  await expect.poll(() => page.evaluate(() => (document.activeElement as HTMLSelectElement | null)?.value ?? ''), { message: `${where}: typing "${prefix}" did not choose an option` }).not.toBe(before)
}
