/**
 * The one way the browser suites run axe: after every CSS transition on the page has finished.
 *
 * axe reads the colours the page shows at that instant, so a control part way through a
 * `transition-colors` change (an outlined link turning filled) is measured as a blend that
 * fails WCAG 2.1 AA although neither end state does. Walkthrough spec 07 failed this way twice
 * on 2026-09-27 (docs/PREVENTION.md P-130). This helper waits for the running transitions
 * first; tests/test_e2e_axe_settles.py refuses a spec that builds its own `AxeBuilder`.
 *
 * Navigation
 * ----------
 * What it is:   The shared axe helper for ui/e2e (the mocked smoke and the live walkthrough).
 * What it does: `axeViolations(page, tags)` settles the page (`settleTransitions`: running
 *               transitions finished, the network idle, then a quiet window with no DOM
 *               change), then returns axe's violations for the WCAG tags given (WCAG 2.1 AA
 *               by default).
 * How:          `document.getAnimations()` (CSS transitions and finite animations), each
 *               `finished` awaited (a cancelled one counts as settled) → `networkidle`,
 *               bounded → a `MutationObserver` quiet window → `new AxeBuilder(...).analyze()`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/smoke.spec.ts and ui/e2e/walkthrough/*.spec.ts (the scans that call it),
 *               tests/test_e2e_axe_settles.py (keeps every scan on this path),
 *               ui/src/components/Button.tsx (the `transition-colors` that met the class),
 *               docs/PREVENTION.md (P-130, P-152, P-166, P-167 — one class, met by four streams)
 * Tested by:    tests/test_e2e_axe_settles.py, tests/test_walkthrough_axe_scan.py,
 *               tests/test_walkthrough_axe_settles.py, ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   never for a new repository; a scan needs another axe option (add it here, never a
 *               second `AxeBuilder`).
 */
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

export const WCAG_21_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

type Violations = Awaited<ReturnType<AxeBuilder['analyze']>>['violations']

/**
 * Wait until the page has settled, so a scan reads the colours a person sees rather than a
 * frame in between. Three streams met this class in parallel and each wait is kept: the
 * running CSS transitions and finite animations are awaited to their `finished` (P-130,
 * P-152; a cancelled one counts as settled, and an infinite one — a spinner — is never waited
 * on); then, because on 2026-09-27 that wait returned, the stage answered and a transition
 * began during the scan (3.19:1, P-167), the settle also waits, bounded, for the network to go
 * idle and for a quiet window of `quietMs` in which no transition runs and nothing in the DOM
 * changes. A page still changing after `timeoutMs` is left to axe, which reports what it reads.
 */
export async function settleTransitions(page: Page, timeoutMs = 3_000, quietMs = 300): Promise<void> {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a instanceof CSSTransition || a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.then(() => undefined, () => undefined)),
    ),
  )
  await page.waitForLoadState('networkidle', { timeout: timeoutMs }).catch(() => undefined)
  await page.evaluate(
    ({ quiet, limit }) =>
      new Promise<void>((resolve) => {
        const start = performance.now()
        let last = start
        const mo = new MutationObserver(() => {
          last = performance.now()
        })
        mo.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true })
        const tick = () => {
          const now = performance.now()
          if (document.getAnimations().some((a) => a instanceof CSSTransition && a.playState === 'running')) last = now
          if (now - last >= quiet || now - start >= limit) {
            mo.disconnect()
            resolve()
          } else requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      }),
    { quiet: quietMs, limit: timeoutMs },
  )
}

/** axe's violations for `tags`, read once every CSS transition has settled. */
export async function axeViolations(page: Page, tags: string[] = WCAG_21_AA): Promise<Violations> {
  await settleTransitions(page)
  const results = await new AxeBuilder({ page }).withTags(tags).analyze()
  return results.violations
}
