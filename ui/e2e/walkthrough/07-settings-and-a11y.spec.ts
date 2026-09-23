/**
 * 07 — the instrument describes itself honestly, and every screen the walkthrough
 * touched is accessible. Proves: the Settings page shows each builder credential as
 * configured yes/no (never a value), the sandbox mode, and the apparatus / policy
 * versions the footer also carries; the Claude Code login card round-trips a
 * (shape-valid, fake) `claude setup-token` value through the UI — status, ≤4-char
 * fingerprint, provenance, remove — without the value ever appearing in the page;
 * then axe (WCAG 2.1 AA) finds 0 violations on Repos, Runs, a Run detail (with real
 * rows), Capability, Ledger, Sign-off and the journey screens (Home, Connection,
 * Measure, Results, Decisions, Factory, Deployment) — against the live data these
 * specs produced, not fixtures.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 07 (settings and accessibility).
 * What it does: Pins that the Settings page shows each builder credential as configured
 *               yes / no (never a value), the sandbox mode and the apparatus / policy
 *               versions the footer also carries; that the Claude Code login card
 *               round-trips a shape-valid FAKE `claude setup-token` value — status, ≤ 4-char
 *               fingerprint, provenance, remove — without the value ever appearing in the
 *               page; that the ACCOUNT LIFECYCLE works from the screen (F23) — an admin sets
 *               the walk-approver persona's password, that persona (in its own browser context)
 *               meets the envelope on a wrong password, signs in with the new one, is refused on
 *               its very next request once the admin sets the password again, and signs in again
 *               — then the account is deactivated and reactivated, with the last active admin's
 *               own controls disabled throughout; and that axe (WCAG 2.1 AA) finds 0 violations on
 *               Repos, Runs, a run detail with real rows, Capability, Ledger and Sign-off —
 *               against the live data the earlier specs produced.
 * How:          `AxeBuilder` with the WCAG tags per screen; the fake token is shape-valid and
 *               deliberately not real; the persona's password is `personaPassword`, the same
 *               stable value 08 and 11 sign in with, so this spec leaves the stack in the
 *               state the later specs expect.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`personaPassword`, `field`, `env`),
 *               ui/src/screens/Settings/SettingsPage.tsx,
 *               ui/src/screens/Settings/ClaudeCodeLoginCard.tsx,
 *               ui/src/screens/Settings/UsersCard.tsx and
 *               ui/src/screens/Settings/SetPasswordDialog.tsx (the screens under test),
 *               ui/src/components/Layout.tsx (the footer versions), src/crb/server/routes/admin.py
 *               (the secrets and user routes), ui/e2e/walkthrough/08-signoff.spec.ts (signs in
 *               as the persona this spec sets the password of)
 * Tested by:    ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   a screen is added (add it to the axe sweep), the settings fields change, or an
 *               account act is added to the Users card.
 */
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { env, expect, field, personaPassword, primary, test } from './support'

test.describe.configure({ mode: 'serial' })

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
//: Shape-valid (prefix, length, alphabet) and deliberately not a real token.
const FAKE_SETUP_TOKEN = 'sk-ant-oat01-' + 'W'.repeat(72) + '-E2E0'
//: The second person 08 signs off as; this spec is where their password is set from the screen.
const APPROVER = 'walk-approver'

async function axeClean(page: Page, where: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze()
  expect(results.violations, `${where}: ${JSON.stringify(results.violations, null, 2)}`).toEqual([])
}

test.describe('07 settings + accessibility', () => {
  const t = primary()

  test('Settings shows builders configured yes/no, the sandbox mode and the versions', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
    // instrument health with the probes the API reports
    await expect(page.getByRole('heading', { name: 'Instrument health' })).toBeVisible()
    for (const probe of ['db', 'append_only', 'ledger', 'sandbox', 'toolchains', 'builders', 'worker']) {
      await expect(page.getByText(probe, { exact: true }).first(), `probe ${probe}`).toBeVisible()
    }
    // configuration (admin): non-secret, redacted
    await expect(page.getByTestId('settings-sandbox-mode')).toHaveText(/^(local|docker)$/)
    await expect(page.getByTestId('settings-ledger-backend')).toHaveText(/^(sqlite|postgresql)$/)
    await expect(page.getByTestId('settings-apparatus')).toHaveText(/^\d+\.\d+$/)
    await expect(page.getByTestId('settings-policy')).toHaveText(/^routing\.v\d+$/)
    const builders = page.getByTestId('settings-builders')
    await expect(builders).toBeVisible()
    const pills = builders.getByRole('img', { name: /: (configured|not configured)$/ })
    expect(await pills.count()).toBeGreaterThanOrEqual(1)
    for (const name of ['anthropic', 'openai', 'cerebras', 'claude_code_cli']) {
      await expect(builders.getByRole('img', { name: new RegExp(`^${name}: (configured|not configured)$`) }), `builder ${name}`).toBeVisible()
    }
    // never a value: nothing that looks like a key
    const text = (await page.locator('main').textContent()) ?? ''
    expect(text).not.toMatch(/sk-ant-|sk-[A-Za-z0-9]{20,}|csk-/)
    // the footer carries the same apparatus + policy as the settings
    const apparatus = (await page.getByTestId('settings-apparatus').textContent())?.trim()
    const policy = (await page.getByTestId('settings-policy').textContent())?.trim()
    await expect(page.locator('footer')).toContainText(`apparatus ${apparatus}`)
    await expect(page.locator('footer')).toContainText(`policy ${policy}`)
    await axeClean(page, '/settings')
  })

  test('Claude Code login: paste → stored (fingerprint only) → remove, never the value', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: 'Claude Code login' })).toBeVisible()
    await expect(page.getByTestId('claude-login-instructions')).toContainText(
      'Sign in with your Claude account below (the API host runs claude setup-token for you), or run it on any machine and paste the token; either way it is stored owner-only on the API host under CRB_HOME/secrets and forwarded to builders only in auth: cli mode.',
    )
    const status = page.getByTestId('claude-login-status')
    await expect(status).toHaveAttribute('data-present', 'false')
    await expect(page.getByTestId('claude-login-verify')).toBeDisabled()
    await expect(page.getByTestId('claude-login-remove')).toBeDisabled()

    // a wrong shape is refused by the server and reported without echoing it
    const field = page.getByTestId('claude-login-token')
    await expect(field).toHaveAttribute('type', 'password')
    await field.fill('sk-ant-api03-' + 'x'.repeat(40))
    await page.getByTestId('claude-login-save').click()
    await expect(page.getByText(/starts with 'sk-ant-oat01-'/)).toBeVisible()
    await expect(status).toHaveAttribute('data-present', 'false')

    // the real shape is stored: status flips, the field is cleared, only …E2E0 is shown
    await field.fill(FAKE_SETUP_TOKEN)
    await page.getByTestId('claude-login-save').click()
    await expect(status).toHaveAttribute('data-present', 'true')
    await expect(status).toContainText('…E2E0')
    await expect(page.getByTestId('claude-login-provenance')).toContainText(`set by ${env.user}`)
    await expect(field).toHaveValue('')
    let text = (await page.locator('main').textContent()) ?? ''
    expect(text).not.toContain(FAKE_SETUP_TOKEN)
    expect(text).not.toContain('W'.repeat(20))
    expect(text).not.toMatch(/sk-ant-|sk-[A-Za-z0-9]{20,}|csk-/)

    // verify: tier 1 is offline by contract, so only prove the control is live; tier 2
    // may call out — a fake token can only come back invalid (or cli_missing on a host
    // without the CLI), never ok
    await expect(page.getByTestId('claude-login-verify')).toBeEnabled()
    if (env.publicTier) {
      await page.getByTestId('claude-login-verify').click()
      const result = page.getByTestId('claude-login-verify-result')
      await expect(result).toBeVisible({ timeout: 90_000 })
      await expect(result).toHaveAttribute('data-status', /^(invalid|cli_missing|error|timeout)$/)
    }
    await axeClean(page, '/settings (token stored)')

    // remove: back to absent, still nothing that looks like a key on the page
    await page.getByTestId('claude-login-remove').click()
    await expect(status).toHaveAttribute('data-present', 'false')
    await expect(page.getByTestId('claude-login-verify')).toBeDisabled()
    text = (await page.locator('main').textContent()) ?? ''
    expect(text).not.toMatch(/sk-ant-|sk-[A-Za-z0-9]{20,}|csk-/)
  })

  // F23 — the account lifecycle from the screen. The persona's password is the STABLE
  // `personaPassword` value 08 and 11 sign in with, so the stack is left as they expect it.
  test('an admin sets the approver persona’s password, that persona signs in with it, the old session is refused, then the account is deactivated and reactivated', async ({ browser, page }) => {
    const pass = personaPassword(APPROVER)

    await page.goto('/settings')
    const users = page.getByRole('table', { name: 'Users' })
    await expect(users).toBeVisible()

    // the persona may already exist (a rerun, or 11-screens on an earlier run): create it once
    if ((await users.getByRole('cell', { name: APPROVER, exact: true }).count()) === 0) {
      await field(page, 'Username').fill(APPROVER)
      await field(page, 'Display name').fill('Walk approver')
      await field(page, 'Email').fill(`${APPROVER}@example.org`)
      await field(page, 'Role').selectOption('approver')
      await field(page, 'Initial password').fill(pass)
      await page.getByRole('button', { name: 'Create local user' }).click()
      await expect(page.getByTestId('users-created')).toContainText(`Account ${APPROVER} created as approver`)
    }

    // the bootstrap admin is the only active admin, so ITS OWN controls are refused up front
    await expect(page.getByTestId(`user-active-${env.user}`)).toBeDisabled()
    await expect(page.getByTestId(`user-role-${env.user}`)).toBeDisabled()

    // an admin sets the persona's password; the value never appears on the page
    await page.getByTestId(`user-set-password-${APPROVER}`).click()
    const dialog = page.getByTestId('set-password-form')
    await expect(dialog).toBeVisible()
    await dialog.getByTestId('set-password-new').fill(pass)
    await dialog.getByTestId('set-password-again').fill(pass)
    await dialog.getByTestId('set-password-submit').click()
    await expect(page.getByTestId('set-password-done')).toContainText(`Password set for ${APPROVER}. Every session that account held has ended`)
    expect((await page.locator('main').textContent()) ?? '').not.toContain(pass)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()

    // The persona's own browser walks the journey end to end, in its own context so the admin's
    // session is never the one being revoked: wrong password -> the envelope; the new password ->
    // in; the admin sets the password again -> this session is refused on its very next request;
    // sign in again with the new one.
    const personaCtx = await browser.newContext({ baseURL: env.baseUrl })
    try {
      const persona = await personaCtx.newPage()
      await persona.goto('/login')
      await field(persona, 'Username').fill(APPROVER)
      await field(persona, 'Password').fill(`${pass}-wrong`)
      await persona.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(persona.getByTestId('error-state')).toContainText('Wrong username or password')

      await field(persona, 'Password').fill(pass)
      await persona.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(persona.getByTestId('user-chip')).toContainText('approver')

      // the admin sets it again: the session this browser holds ends on its next request
      await page.getByTestId(`user-set-password-${APPROVER}`).click()
      await dialog.getByTestId('set-password-new').fill(pass)
      await dialog.getByTestId('set-password-again').fill(pass)
      await dialog.getByTestId('set-password-submit').click()
      await expect(page.getByTestId('set-password-done')).toBeVisible()
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()

      await persona.goto('/repos')
      await expect(persona).toHaveURL(/\/login/)
      await field(persona, 'Username').fill(APPROVER)
      await field(persona, 'Password').fill(pass)
      await persona.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(persona.getByTestId('user-chip')).toContainText('approver')
    } finally {
      await personaCtx.close()
    }

    // still the admin in this browser: deactivate, then reactivate, each saying what it did
    await page.goto('/settings')
    const toggle = page.getByTestId(`user-active-${APPROVER}`)
    try {
      await expect(toggle).toBeChecked()
      await toggle.uncheck()
      await expect(page.getByTestId('users-said')).toContainText(`${APPROVER} is deactivated and is refused on its very next request.`)
      await expect(toggle).not.toBeChecked()
      await toggle.check()
      await expect(page.getByTestId('users-said')).toContainText(`${APPROVER} is active again and can sign in.`)
      await expect(toggle).toBeChecked()
    } finally {
      // 08 and 11 sign in as this account: a failure above must not leave it deactivated and
      // turn one broken assertion into three broken specs (it did, before the toggle was fixed)
      if (!(await toggle.isChecked())) await toggle.check()
    }

    // and the account's own audit trail shows every one of those acts, with who made it
    await page.getByTestId(`user-history-${APPROVER}`).click()
    const history = page.getByTestId('account-history')
    await expect(history).toContainText(`History for ${APPROVER}`)
    // `.first()`: the password was set twice on this path, so `user.password_set` is two rows
    for (const action of ['user.activated', 'user.deactivated', 'user.password_set', 'user.created']) {
      await expect(history.locator(`[data-action="${action}"]`).first(), `history row ${action}`).toBeVisible()
    }
    await axeClean(page, '/settings (users)')
  })

  test('Repos and Runs have no WCAG 2.1 AA violations', async ({ page }) => {
    await page.goto('/repos')
    await expect(page.getByRole('link', { name: t.name, exact: true })).toBeVisible()
    await axeClean(page, '/repos')
    await page.goto(`/repos/${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('repo-probe')).toBeVisible()
    await axeClean(page, `/repos/${t.name}`)
    await page.goto('/runs')
    await expect(page.getByRole('table', { name: 'Runs' }).locator('tbody tr').first()).toBeVisible()
    await axeClean(page, '/runs')
  })

  test('a Run detail with real rows has no WCAG 2.1 AA violations', async ({ page }) => {
    await page.goto(`/runs?repo=${encodeURIComponent(t.name)}&kind=replay`)
    const table = page.getByRole('table', { name: 'Runs' })
    await table.locator('tbody tr').first().getByRole('link').first().click()
    await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
    await expect(page.getByRole('table', { name: 'Per-task outcomes' }).locator('tbody tr').first()).toBeVisible()
    await expect(page.getByTestId('live-log')).toContainText(/\d+ events/)
    await axeClean(page, '/runs/<replay>')
  })

  test('Capability, Ledger and Sign-off have no WCAG 2.1 AA violations', async ({ page }) => {
    await page.goto(`/capability?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('cell-measured').first()).toBeVisible()
    await axeClean(page, '/capability')
    await page.goto(`/ledger?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('ledger-gate')).toHaveAttribute('data-state', 'OPEN')
    await expect(page.getByRole('table', { name: 'Ledger rows' }).locator('tbody tr').first()).toBeVisible()
    await axeClean(page, '/ledger')
    await page.goto(`/signoff?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('signoff-gate')).toBeVisible()
    await axeClean(page, '/signoff')
    await page.goto(`/oracle?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByRole('table', { name: 'Negative-control rows' })).toBeVisible()
    await axeClean(page, '/oracle')
  })

  test('the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations', async ({ page }) => {
    await page.goto('/home')
    await expect(page.getByRole('list', { name: 'Tasks' })).toBeVisible()
    await axeClean(page, '/home')
    await page.goto('/connect')
    await expect(page.getByRole('link', { name: t.name, exact: true })).toBeVisible()
    await axeClean(page, '/connect')
    // each wait is for API-backed content, not the heading: the loaded screen is what axe reads
    await page.goto(`/connect/${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('stage-measure')).toBeVisible()
    await axeClean(page, `/connect/${t.name}`)
    await page.goto(`/connect/${encodeURIComponent(t.name)}/measure`)
    await expect(page.getByTestId('before-you-start')).toContainText(/attempts/)
    await axeClean(page, `/connect/${t.name}/measure`)
    await page.goto(`/results?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByRole('table', { name: `Capability map for ${t.name}` })).toBeVisible()
    await axeClean(page, '/results')
    await page.goto('/decisions')
    // page-level readiness: every repository's map, sign-off and task queries have settled
    await expect(page.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true')
    await axeClean(page, '/decisions')
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('factory-no-backlog').or(page.getByTestId('factory-run-controls'))).toBeVisible()
    await axeClean(page, '/factory')
    await page.goto('/posture')
    await expect(page.getByText(/^crb \d/)).toBeVisible()
    await expect(page.getByText(/Append-only, hash-chained/)).toBeVisible()
    await axeClean(page, '/posture')
  })
})
