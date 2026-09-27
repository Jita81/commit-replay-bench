/**
 * The one way the browser suites run axe: after every CSS transition on the page has finished.
 *
 * axe reads the colours the page shows at that instant, so a control part way through a
 * `transition-colors` change (an outlined link turning filled) is measured as a blend that
 * fails WCAG 2.1 AA although neither end state does. Walkthrough spec 07 failed this way twice
 * on 2026-09-27 (docs/PREVENTION.md P-063). This helper waits for the running transitions
 * first; tests/test_e2e_axe_settles.py refuses a spec that builds its own `AxeBuilder`.
 *
 * Navigation
 * ----------
 * What it is:   The shared axe helper for ui/e2e (the mocked smoke and the live walkthrough).
 * What it does: `axeViolations(page, tags)` waits for every running CSS transition to
 *               finish (never an infinite animation, which would not end), then returns
 *               axe's violations for the WCAG tags given (WCAG 2.1 AA by default).
 * How:          `document.getAnimations()` filtered to `CSSTransition`, each `finished`
 *               awaited (a cancelled one counts as settled) → `new AxeBuilder(...).analyze()`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/smoke.spec.ts and ui/e2e/walkthrough/*.spec.ts (the scans that call it),
 *               tests/test_e2e_axe_settles.py (keeps every scan on this path),
 *               ui/src/components/Button.tsx (the `transition-colors` that met the class),
 *               docs/PREVENTION.md (P-063)
 * Tested by:    tests/test_e2e_axe_settles.py, ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   a scan needs another axe option (add it here, never a second `AxeBuilder`).
 */
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

export const WCAG_21_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

type Violations = Awaited<ReturnType<AxeBuilder['analyze']>>['violations']

/** Wait for the page's running CSS transitions to finish; a cancelled one counts as settled. */
export async function settleTransitions(page: Page): Promise<void> {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a instanceof CSSTransition)
        .map((a) => a.finished.then(() => undefined, () => undefined)),
    ),
  )
}

/** axe's violations for `tags`, read once every CSS transition has settled. */
export async function axeViolations(page: Page, tags: string[] = WCAG_21_AA): Promise<Violations> {
  await settleTransitions(page)
  const results = await new AxeBuilder({ page }).withTags(tags).analyze()
  return results.violations
}
