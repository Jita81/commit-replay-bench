/**
 * 13 — recover an account, end to end and timed: the journey dod.journey.recover-an-account
 * walks in one spec, from the wrong password to signing in again.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 13 (recover-an-account), tier 1 and tier 2 alike; it changes
 *               only its own account, `walk-recover`.
 * What it does: A person signs in on one device (the session a lost laptop holds). On a second
 *               device they type a wrong password: `/login` shows the 401 envelope with the
 *               next step inside it — ask an admin of this deployment to set a new password
 *               (G-460). The admin sets a new one from the Users card; the first device's
 *               session is refused on its very next request (#52's revocation); the person
 *               signs in with the new password. The account's History then shows the refused
 *               sign-in, the password set and the new sign-in, each with its actor. The time
 *               from the wrong password to the new sign-in is measured and attached to the
 *               test as a `recovery-ms` annotation, and must stay under `RECOVERY_BUDGET_MS`.
 * How:          The `test` fixture's page is the signed-in bootstrap admin (the History must
 *               name it, not its id); the person uses two fresh browser contexts; the new
 *               password is a fresh per-run value derived with `personaPassword`, never
 *               printed; `performance.now()` brackets the walk.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`field`, `env`, `personaPassword`, `test`),
 *               ui/src/screens/Login/LoginPage.tsx (the envelope and its next step),
 *               ui/src/screens/Settings/UsersCard.tsx and SetPasswordDialog.tsx (the admin's
 *               act and the History), src/crb/server/routes/auth.py (`user.login`,
 *               `user.login_failed`), src/crb/server/auth.py (`set_password` rotates the
 *               session nonce), docs/OPERATOR.md#9-users (the timing it reports)
 * Tested by:    ui/e2e/walkthrough/13-recover-an-account.spec.ts
 * Touch when:   a step of the recovery journey changes, or the Users card's acts do.
 */
import AxeBuilder from '@axe-core/playwright'
import type { Browser } from '@playwright/test'
import { env, expect, field, personaPassword, settled, test } from './support'

test.describe.configure({ mode: 'serial' })

//: The account this spec recovers; no other spec signs in as it.
const PERSON = 'walk-recover'
//: A recovery by the admin door, machine-walked, must finish inside this. The measured time is
//: reported beside it (docs/OPERATOR.md §9); a person reading and typing takes longer.
const RECOVERY_BUDGET_MS = 60_000
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

async function newDevice(browser: Browser) {
  const ctx = await browser.newContext({ baseURL: env.baseUrl })
  return { ctx, page: await ctx.newPage() }
}

test.describe('13 recover an account', () => {
  test('a wrong password names the next step, an admin sets a new one, the old session is refused, and the person signs in again — timed', async ({ browser, page }, testInfo) => {
    const first = personaPassword(PERSON)
    const fresh = personaPassword(`${PERSON}:${Date.now()}`)

    // --- setup (not timed): the account exists and holds `first` --------------------------
    await page.goto('/settings')
    const users = page.getByRole('table', { name: 'Users' })
    await expect(users).toBeVisible()
    const dialog = page.getByTestId('set-password-form')
    const setPassword = async (value: string) => {
      await page.getByTestId(`user-set-password-${PERSON}`).click()
      await expect(dialog).toBeVisible()
      await dialog.getByTestId('set-password-new').fill(value)
      await dialog.getByTestId('set-password-again').fill(value)
      await dialog.getByTestId('set-password-submit').click()
      await expect(page.getByTestId('set-password-done')).toContainText(`Password set for ${PERSON}. Every session that account held has ended`)
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    }
    if ((await users.getByRole('cell', { name: PERSON, exact: true }).count()) === 0) {
      await field(page, 'Username').fill(PERSON)
      await field(page, 'Display name').fill('Walk recover')
      await field(page, 'Email').fill(`${PERSON}@example.org`)
      await field(page, 'Initial password').fill(first)
      await page.getByRole('button', { name: 'Create local user' }).click()
      await expect(page.getByTestId('users-created')).toContainText(`Account ${PERSON} created as viewer`)
    } else {
      await setPassword(first) // a rerun: the last run left the account on its own fresh password
    }

    const laptop = await newDevice(browser)
    const phone = await newDevice(browser)
    try {
      // the session the person already holds (the device they then lose, or forget on)
      await laptop.page.goto('/login')
      await field(laptop.page, 'Username').fill(PERSON)
      await field(laptop.page, 'Password').fill(first)
      await laptop.page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(laptop.page.getByTestId('user-chip')).toBeVisible()

      // --- the recovery, timed ------------------------------------------------------------
      const start = performance.now()

      // 1. /login: a wrong password, and the envelope names who sets a new one
      await phone.page.goto('/login')
      await field(phone.page, 'Username').fill(PERSON)
      await field(phone.page, 'Password').fill(`${first}-forgotten`)
      await phone.page.getByRole('button', { name: 'Sign in', exact: true }).click()
      const envelope = phone.page.getByTestId('error-state')
      await expect(envelope).toContainText('Wrong username or password')
      await expect(envelope.getByTestId('login-next-step')).toContainText('ask an admin of this deployment to set a new one on the Settings screen')

      // 2. /settings: the admin sets a new password from the Users card
      await setPassword(fresh)

      // 3. the session the person held is refused on its very next request
      await laptop.page.goto('/repos')
      await expect(laptop.page).toHaveURL(/\/login/)

      // 4. the person signs in with the new password
      await field(phone.page, 'Password').fill(fresh)
      await phone.page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(phone.page.getByTestId('user-chip')).toContainText('viewer')

      const ms = Math.round(performance.now() - start)
      testInfo.annotations.push({ type: 'recovery-ms', description: String(ms) })
      console.log(`recover-an-account: admin door, machine-walked, ${ms} ms`)
      expect(ms, `the recovery took ${ms} ms`).toBeLessThan(RECOVERY_BUDGET_MS)
    } finally {
      await laptop.ctx.close()
      await phone.ctx.close()
    }

    // --- the audit: the account's History shows every step, with who made it -------------
    await page.goto('/settings')
    await page.getByTestId(`user-history-${PERSON}`).click()
    const history = page.getByTestId('account-history')
    await expect(history).toContainText(`History for ${PERSON}`)
    const newest = history.getByTestId('account-history-event')
    // newest first: the new sign-in, the password set, the refused sign-in
    await expect(newest.nth(0)).toHaveAttribute('data-action', 'user.login')
    // the actor is named as a person reads it, not as the account id the record keeps
    await expect(newest.nth(0)).toContainText(`by ${PERSON}`)
    await expect(newest.nth(1)).toHaveAttribute('data-action', 'user.password_set')
    await expect(newest.nth(1)).toContainText(`by ${env.user}`)
    await expect(newest.nth(2)).toHaveAttribute('data-action', 'user.login_failed')
    await expect(newest.nth(2)).toContainText('by anonymous')
    expect((await page.locator('main').textContent()) ?? '').not.toContain(fresh)
  })

  test('/login with the wrong-password envelope and its next step has no WCAG 2.1 AA violations', async ({ browser }) => {
    const device = await newDevice(browser)
    try {
      await device.page.goto('/login')
      await field(device.page, 'Username').fill(PERSON)
      await field(device.page, 'Password').fill('not-the-password-at-all')
      await device.page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(device.page.getByTestId('login-next-step')).toBeVisible()
      await settled(device.page)
      const results = await new AxeBuilder({ page: device.page }).withTags(TAGS).analyze()
      expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])
    } finally {
      await device.ctx.close()
    }
  })
})
