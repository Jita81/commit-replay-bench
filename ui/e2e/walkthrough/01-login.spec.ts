/**
 * 01 — the front door. Proves: the stack is up (health), a wrong password renders
 * the API's error envelope (not a blank form), a right one lands in the shell with
 * the RBAC chip reading the bootstrap admin's role, and signing out returns to /login.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 01 (login), the first of the serial story.
 * What it does: Pins that `/health` answers with a database, an append-only ledger with
 *               false-Q1 = 0 and a worker before anything else runs; that a wrong password
 *               renders the API's error envelope (not a blank form); that the right one
 *               lands in the shell with the RBAC chip reading the bootstrap admin's role;
 *               and that signing out returns to `/login`.
 * How:          `stackHealth` for the probes; the login form filled through the UI; the
 *               `user-chip` test id.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`stackHealth`, `signIn`, `env`),
 *               ui/src/screens/Login/LoginPage.tsx and ui/src/components/Layout.tsx (the
 *               screens under test), src/crb/observability/probes.py (the probes asserted)
 * Tested by:    ui/e2e/walkthrough/01-login.spec.ts
 * Touch when:   a health probe is renamed or the login flow changes.
 */
import { expect, test } from '@playwright/test'
import { env, field, signIn, stackHealth } from './support'

test.describe.configure({ mode: 'serial' })

test.describe('01 login', () => {
  test('the stack answers /health with a database, an append-only ledger and a worker', async ({ page }) => {
    const h = await stackHealth(page)
    const byName = Object.fromEntries(h.probes.map((p) => [p.name, p]))
    expect(byName.db?.status, JSON.stringify(byName.db)).toBe('ok')
    expect(byName.append_only?.status, JSON.stringify(byName.append_only)).toBe('ok')
    expect(byName.ledger?.data.false_q1, 'false-Q1 must be 0 before we start').toBe(0)
    expect(byName.worker, 'the worker probe must be present').toBeTruthy()
  })

  test('a wrong password shows the error envelope; the right one shows the ADMIN chip', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { level: 1, name: 'Commit Replay Bench' })).toBeVisible()

    await field(page, 'Username').fill(env.user)
    await field(page, 'Password').fill(`${env.pass}-wrong`)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    const envelope = page.getByTestId('error-state')
    await expect(envelope).toBeVisible()
    await expect(envelope).toContainText('Wrong username or password')
    await expect(envelope).toContainText('HTTP 401')
    await expect(page).toHaveURL(/\/login/)

    await field(page, 'Password').fill(env.pass)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/home$/) // a direct login lands on the journey's first screen
    const chip = page.getByTestId('user-chip')
    await expect(chip).toBeVisible()
    await expect(chip).toContainText(/admin/i)
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
  })

  test('a protected route bounces to /login?next= and comes back after signing in', async ({ page }) => {
    await page.goto('/ledger')
    await expect(page).toHaveURL(/\/login\?next=%2Fledger/)
    await field(page, 'Username').fill(env.user)
    await field(page, 'Password').fill(env.pass)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/ledger$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Ledger' })).toBeVisible()
  })

  test('sign out ends the session', async ({ page }) => {
    await signIn(page)
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/repos')
    await expect(page).toHaveURL(/\/login\?next=/)
  })
})
