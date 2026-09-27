/**
 * 11b-keyboard — the five controls a keyboard person has to OPERATE, by Tab and keys alone
 * (G-905): a map cell and its reason code (/capability), a reason code on Routes, a term on
 * Oracle (each opening and closing with `aria-expanded`), the sign-off form filled to an
 * enabled Sign off and the revoke confirmation filled to an enabled Revoke sign-off, then left
 * by Cancel (/signoff), and the freeze dialog with focus in, kept in and back (/factory) — plus
 * a negative control that takes the map cells out of the tab order and requires the same step
 * to fail.
 *
 * It runs in the stateful story, after the specs that make what it operates: 08 seeds and signs
 * `walk-signable` (the attestation it opens a revoke confirmation on), 05 and 04 give the
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
 *               asserting `aria-expanded`, where focus goes and that it comes back; the
 *               negative control proves `tabTo` fails on a control that cannot take focus.
 * How:          Playwright; `signIn`, `ensurePersona` and `primary` from support.ts; the
 *               keyboard helpers from keyboard.ts; never `focus()` and never a click.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/keyboard.ts (`tabTo`, `escapeUntil`, `focusedIs`,
 *               `chooseByKeyboard`, `settle`, `bubbleOf`), ui/e2e/walkthrough/support.ts,
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
import { bubbleOf, chooseByKeyboard, escapeUntil, focusedIs, settle, tabTo } from './keyboard'
import { ensurePersona, env, personaPassword, primary, signIn } from './support'

test.describe.configure({ mode: 'serial' })

/** The primary repository the story onboarded, measured and froze a backlog on. */
const REPO = primary().name

/** The repository 08 seeds and the approver signs (`SIGNABLE_NAME` in 08-signoff): it has an active attestation to revoke. */
const SIGNED_REPO = 'walk-signable'

const USERNAMES = { operator: 'walk-operator', approver: 'walk-approver' } as const
// stable per stack (never per run), the same values 08 and 11-screens use; never logged
const PASSWORDS = { operator: personaPassword(USERNAMES.operator), approver: personaPassword(USERNAMES.approver) } as const

test.describe('11b-keyboard: the controls a keyboard person has to operate', () => {
  test('the operator and approver accounts exist (admin, via the API)', async ({ page }) => {
    await signIn(page, env.user, env.pass)
    await ensurePersona(page, USERNAMES.operator, 'operator')
    await ensurePersona(page, USERNAMES.approver, 'approver')
  })

  // ─── the per-screen keyboard steps (G-905) ──────────────────────────────────────────────
  // 11-screens proves every screen's first hinted controls take focus. These prove
  // the five controls a keyboard person has to OPERATE, each reached by Tab alone from the
  // skip link (`tabTo`) and driven by Enter, Space, typing and Escape — no click, no focus().
  // They change no data: the sign-off form is filled to an enabled Sign off and the revoke
  // confirmation filled to an enabled Revoke sign-off, then left by Cancel; the freeze dialog
  // is opened and closed. Pressing those buttons is proven by 08 and 10, on the same native
  // `<button>`, whose Enter/Space activation the browser guarantees.

  test('keyboard: a map cell opens from the keyboard, and the reason code in it opens and closes (/capability)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
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
    expect(await focusedIs(disclosure), `${where}: closing the reason code lost focus`).toBe(true)
  })

  test('keyboard: a reason-code button on Routes is reached by Tab and opens and closes with aria-expanded (/routing)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
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
    expect(await focusedIs(disclosure), `${where}: closing the reason code lost focus`).toBe(true)
  })

  test('keyboard: a term on Oracle opens and closes with aria-expanded (/oracle)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await signIn(page, USERNAMES.operator, PASSWORDS.operator)
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
    await page.goto(`/factory?repo=${encodeURIComponent(REPO)}`)
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
    await page.goto(`/capability?repo=${encodeURIComponent(REPO)}`)
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
