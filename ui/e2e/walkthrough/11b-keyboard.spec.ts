/**
 * 11b-keyboard — the five controls a keyboard person has to OPERATE, by Tab and keys alone
 * (G-905): a map cell and its reason code (/capability), a reason code on Routes, a term on
 * Oracle (each opening and closing with `aria-expanded`), the sign-off form filled to a Sign
 * off that stays closed on a cell with no proven standard (routing.v2; the walk of an enabled
 * Sign off and of the revoke confirmation waits on G-956), and the freeze dialog with focus in, kept in and back (/factory) — plus
 * two negative controls: one takes the map cells out of the tab order and requires the same
 * step to fail, one puts the pointer on the page and requires the pointer guard to see it.
 *
 * No step lets the pointer reach the page. Every one signs in by keyboard, and `afterEach`
 * fails a step whose page saw a pointer event: a pointer left resting on the page by a click
 * is sent mouseover events as Tab scrolls under it, the hint it rests on opens, and that
 * bubble spends an Escape the step meant for its control (P-781, PR #58's CI, 8 October).
 *
 * It runs in the stateful story, after the specs that make what it operates: 08 seeds
 * `walk-signable` (every clause but the sealed posture and the reading holds), 05 and 04 give the
 * primary repository a measured cell, route decisions and an oracle report, and 10 gives the
 * factory a backlog to freeze. (The five steps were written into 11-screens; when that spec was
 * split out to run by persona on stacks of their own, the steps moved here, where that state
 * exists.) It presses neither Sign off, Revoke sign-off, Freeze nor Run (G-992, G-993), so it
 * changes no data.
 *
 * Navigation
 * ----------
 * What it is:   The tier-1 walkthrough's keyboard-operation spec.
 * What it does: Makes sure the operator and approver personas exist (the same stable
 *               passwords 08 and 11-screens sign in with), then for each of the five controls
 *               signs in as the persona who uses it, loads the page, reaches the control from
 *               the skip link by Tab alone and drives it with Enter, Space, typing and Escape,
 *               asserting `aria-expanded`, where focus goes and that it comes back; fails
 *               any step whose page a pointer event reached; the negative controls prove
 *               `tabTo` fails on a control that cannot take focus and the guard sees a pointer.
 * How:          Playwright; `signIn` (by keyboard), `ensurePersona` and `primary` from
 *               support.ts; the keyboard helpers from keyboard.ts; never `focus()`, never a
 *               click, never the pointer.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/keyboard.ts (`tabTo`, `escapeUntil`, `focusedIs`,
 *               `chooseByKeyboard`, `settle`, `bubbleOf`, `countPointer`, `pointerEvents`),
 *               ui/e2e/walkthrough/support.ts,
 *               ui/e2e/walkthrough/08-signoff.spec.ts (seeds and signs `walk-signable`),
 *               ui/e2e/walkthrough/10-factory.spec.ts (the backlog the freeze dialog opens on),
 *               .github/workflows/ci.yml (the `walkthrough-story` job runs it),
 *               ui/e2e/walkthrough/README.md (the spec table)
 * Tested by:    ui/e2e/walkthrough/11b-keyboard.spec.ts (this file; run by scripts/walkthrough.sh)
 * Touch when:   never for a new repository (it reads the primary tier target); a control a
 *               keyboard person must operate is added to a screen (add its step here, reached
 *               by Tab from the skip link).
 */
import { expect, test } from '@playwright/test'
import { bubbleOf, chooseByKeyboard, countPointer, escapeUntil, focusedIs, pointerEvents, settle, tabTo } from './keyboard'
import { ensurePersona, env, personaPassword, primary, signIn } from './support'

test.describe.configure({ mode: 'serial' })

/** The tag of the one test that puts the pointer on the page on purpose (the guard's negative control). */
const POINTER = '@pointer'

// Arm every test's page before its first navigation, and fail a test whose page a pointer
// event reached (P-781): only the guard's own negative control, tagged POINTER, may.
test.beforeEach(async ({ page }) => {
  await countPointer(page)
})
test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.tags.includes(POINTER)) return
  expect(
    await pointerEvents(page),
    'the pointer reached the page: a hint under a resting pointer opens on hover as Tab scrolls, and its bubble spends an Escape meant for the control (P-781)',
  ).toEqual([])
})

/** The primary repository the story onboarded, measured and froze a backlog on. */
const REPO = primary().name

/** The repository 08 seeds (`SIGNABLE_NAME` in 08-signoff): every clause but the sealed posture and the reading holds (G-956). */
const SIGNED_REPO = 'walk-signable'

const USERNAMES = { operator: 'walk-operator', approver: 'walk-approver' } as const
// stable per stack (never per run), the same values 08 and 11-screens use; never logged
const PASSWORDS = { operator: personaPassword(USERNAMES.operator), approver: personaPassword(USERNAMES.approver) } as const

test.describe('11b-keyboard: the controls a keyboard person has to operate', () => {
  test('the operator and approver accounts exist (admin, via the API)', async ({ page }) => {
    await signIn(page, env.user, env.pass, { by: 'keyboard' })
    await ensurePersona(page, USERNAMES.operator, 'operator')
    await ensurePersona(page, USERNAMES.approver, 'approver')
  })

  // ─── the per-screen keyboard steps (G-905) ──────────────────────────────────────────────
  // 11-screens proves every screen's first hinted controls take focus. These prove
  // the five controls a keyboard person has to OPERATE, each reached by Tab alone from the
  // skip link (`tabTo`) and driven by Enter, Space, typing and Escape — no click, no focus().
  // They change no data: the sign-off form is filled and Sign off stays closed (no walkthrough
  // cell has a proven standard under routing.v2 — G-956); the freeze dialog is opened and
  // closed. Pressing those buttons is proven by 08 and 10, on the same native
  // `<button>`, whose Enter/Space activation the browser guarantees.

  test('keyboard: a map cell opens from the keyboard, and the reason code in it opens and closes (/capability)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator, { by: 'keyboard' })
    await page.goto(`/capability?repo=${encodeURIComponent(REPO)}`)
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
    await expect.poll(() => focusedIs(disclosure), { message: `${where}: closing the reason code lost focus` }).toBe(true)
  })

  test('keyboard: a reason-code button on Routes is reached by Tab and opens and closes with aria-expanded (/routing)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator, { by: 'keyboard' })
    await page.goto(`/routing?repo=${encodeURIComponent(REPO)}`)
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
    await expect.poll(() => focusedIs(disclosure), { message: `${where}: closing the reason code lost focus` }).toBe(true)
  })

  test('keyboard: a term on Oracle opens and closes with aria-expanded (/oracle)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator, { by: 'keyboard' })
    await page.goto(`/oracle?repo=${encodeURIComponent(REPO)}`)
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
    await expect.poll(() => focusedIs(term), { message: `${where}: closing the term lost focus` }).toBe(true)
  })

  test('keyboard: the sign-off form is filled from the keyboard, and Sign off stays closed on a cell with no proven standard (/signoff)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.approver, PASSWORDS.approver, { by: 'keyboard' })
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
    // routing.v2: a walkthrough cell has no proven standard (host posture, no registered
    // reading — G-956), so the complete form leaves Sign off disabled and the gate names the
    // reading; the keyboard walk of an enabled Sign off and of the revoke confirmation waits
    // on G-956 (the revoke's focus is unit-tested in SignoffPage.test.tsx)
    await expect(page.locator('button[form="signoff-form"]'), `${where}: Sign off opened on a cell with no proven standard`).toBeDisabled()
    await expect(page.getByTestId('signoff-refusals').getByTestId('refusal-not_standard:reading_unregistered')).toBeVisible()
  })

  test('keyboard: the freeze dialog takes focus when it opens and gives it back when it closes (/factory)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator, { by: 'keyboard' })
    await page.goto(`/factory?repo=${encodeURIComponent(REPO)}`)
    await settle(page)
    const where = 'operator @ 1280 /factory'
    const opener = 'button[data-hint="button.factory.freeze"], button[data-hint="button.factory.freeze_revised"]'
    await tabTo(page, opener, where)
    const label = ((await page.locator(':focus').textContent()) ?? '').trim()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', { name: /^Freeze a (revised )?backlog$/ })
    await expect(dialog, `${where}: Enter on "${label}" did not open the freeze dialog`).toBeVisible()
    await expect.poll(() => focusedIs(dialog), { message: `${where}: focus did not move into the freeze dialog when it opened` }).toBe(true)
    // Tab stays inside a modal dialog
    for (let i = 0; i < 6; i += 1) {
      await page.keyboard.press('Tab')
      await expect.poll(() => focusedIs(dialog), { message: `${where}: Tab ${i + 1} left the modal dialog` }).toBe(true)
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
    await signIn(page, USERNAMES.operator, PASSWORDS.operator, { by: 'keyboard' })
    await page.goto(`/capability?repo=${encodeURIComponent(REPO)}`)
    await settle(page)
    // the cells come from a query: take them out of the tab order only once they are drawn,
    // or the control measures a page with none and proves nothing (P-782)
    await expect(page.locator('button[data-hint="map.cell.tile"]').first(), 'the negative control needs a measured cell on the page').toBeAttached()
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

  test('keyboard: the pointer guard sees a pointer that reaches the page (negative control)', { tag: POINTER }, async ({ page }) => {
    // A guard that cannot fail proves nothing. Sign in the way every step above does, then do
    // what the click-based sign-in did on PR #58's CI (P-781): put the pointer on the page
    // where Sign in was. The guard must see it, though no hint has to open for it to count.
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator, { by: 'keyboard' })
    await page.goto(`/capability?repo=${encodeURIComponent(REPO)}`)
    await settle(page)
    expect(await pointerEvents(page), 'the keyboard sign-in let the pointer reach the page').toEqual([])
    await page.mouse.move(640, 466)
    await expect
      .poll(async () => (await pointerEvents(page)).length, { message: 'the guard did not see a pointer on the page — it cannot fail' })
      .toBeGreaterThan(0)
  })
})
