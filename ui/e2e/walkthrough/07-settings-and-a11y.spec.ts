/**
 * 07 — the instrument describes itself honestly, and every screen the walkthrough
 * touched is accessible. Proves: the Settings page shows each builder credential as
 * configured yes/no (never a value), the sandbox mode, and the apparatus / policy
 * versions the footer also carries; the Claude Code login card round-trips a
 * (shape-valid, fake) `claude setup-token` value through the UI — status, ≤4-char
 * fingerprint, provenance, remove — without the value ever appearing in the page;
 * then axe (WCAG 2.1 AA) finds 0 violations on Repos, Runs, a Run detail (with real
 * rows), a Task page (with real grade rows), Capability, Ledger, Sign-off and the journey screens (Home, Connection,
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
 *               own controls disabled throughout; and that axe (WCAG 2.1 AA) finds 0
 *               violations on Repos, Runs, a run detail with real rows, a task page with real
 *               grade rows (at 1280 and 375, where its grade table must stay inside the phone:
 *               G-292), Capability, Ledger, Sign-off, Oracle and the journey screens — against
 *               the live data the earlier specs produced.
 * How:          axe with the WCAG tags per screen, once the page settles (ui/e2e/axe.ts);
 *               the fake token is shape-valid and deliberately not real; the persona's
 *               password is `personaPassword`, the same stable value 08 and 11 sign in with,
 *               so this spec leaves the stack in the state the later specs expect.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`personaPassword`, `field`, `env`), ui/e2e/axe.ts,
 *               ui/src/screens/Settings/SettingsPage.tsx,
 *               ui/src/screens/Settings/ClaudeCodeLoginCard.tsx,
 *               ui/src/screens/Settings/UsersCard.tsx and
 *               ui/src/screens/Settings/SetPasswordDialog.tsx (the screens under test),
 *               ui/src/components/Layout.tsx (the footer versions), src/crb/server/routes/admin.py
 *               (the secrets and user routes), ui/e2e/walkthrough/08-signoff.spec.ts (signs in
 *               as the persona this spec sets the password of)
 * Tested by:    ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   never for a new repository (it sweeps the product's own screens); a screen is
 *               added (add it to the axe sweep), the settings fields change, or an account act
 *               is added to the Users card.
 */
import { axeViolations } from '../axe'
import type { Page } from '@playwright/test'
import { env, expect, field, personaPassword, primary, test } from './support'

test.describe.configure({ mode: 'serial' })

//: Shape-valid (prefix, length, alphabet) and deliberately not a real token.
const FAKE_SETUP_TOKEN = 'sk-ant-oat01-' + 'W'.repeat(72) + '-E2E0'
//: The second person 08 signs off as; this spec is where their password is set from the screen.
const APPROVER = 'walk-approver'

/**
 * `<main>`'s text once every card on it has drawn — no query still loading, and the GitHub App
 * card (which has no loading state of its own) answered or failed — so a sweep for something
 * that looks like a key reads the whole page, not the first render (P-782).
 */
async function mainText(page: Page): Promise<string> {
  const main = page.locator('main')
  await expect(main.getByTestId('loading')).toHaveCount(0)
  await expect(main.getByTestId('github-app-status').or(main.getByTestId('error-state')).first()).toBeVisible()
  return (await main.textContent()) ?? ''
}

async function axeClean(page: Page, where: string): Promise<void> {
  const violations = await axeViolations(page)
  expect(violations, `${where}: ${JSON.stringify(violations, null, 2)}`).toEqual([])
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
    await expect(pills.first(), 'the builders card reports at least one builder').toBeVisible()
    for (const name of ['anthropic', 'openai', 'cerebras', 'claude_code_cli']) {
      await expect(builders.getByRole('img', { name: new RegExp(`^${name}: (configured|not configured)$`) }), `builder ${name}`).toBeVisible()
    }
    // never a value: nothing that looks like a key
    const text = await mainText(page)
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
    let text = await mainText(page)
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

    // remove: one click asks (G-922), the second deletes; back to absent, still nothing that
    // looks like a key on the page
    await page.getByTestId('claude-login-remove').click()
    await page.getByTestId('claude-login-remove-confirm').getByRole('button', { name: 'Yes, remove it' }).click()
    await expect(status).toHaveAttribute('data-present', 'false')
    await expect(page.getByTestId('claude-login-verify')).toBeDisabled()
    text = await mainText(page)
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
      // the invitation card asks for a Username too: the form's own name tells them apart
      const create = page.getByRole('form', { name: 'Create a local user' })
      await field(create, 'Username').fill(APPROVER)
      await field(create, 'Display name').fill('Walk approver')
      await field(create, 'Email').fill(`${APPROVER}@example.org`)
      await field(create, 'Role').selectOption('approver')
      await field(create, 'Initial password').fill(pass)
      await create.getByRole('button', { name: 'Create local user' }).click()
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
    expect(await mainText(page)).not.toContain(pass)
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
      // turn one broken assertion into three broken specs (it did, before the toggle was fixed).
      // Read the toggle from a fresh load: one read while a toggle is in flight reads the page
      // before the server answered (P-782)
      await page.goto('/settings')
      await expect(toggle).toBeAttached()
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

  test('a Task page with real grade rows has no WCAG 2.1 AA violations, and at 375 px its grade table stays inside the phone (G-292)', async ({ page }) => {
    // reached the way a reader reaches it: a graded row's task link on the Ledger, so the
    // page carries at least one real grade row (a task picked from the mined list may have none)
    await page.goto(`/ledger?repo=${encodeURIComponent(t.name)}`)
    const ledgerRows = page.getByRole('table', { name: 'Ledger rows' }).locator('tbody tr')
    await expect(ledgerRows.first()).toBeVisible()
    await ledgerRows.first().locator('a[href^="/tasks/"]').first().click()
    await page.waitForURL(/\/tasks\/[^/]+\/[^/]+$/)
    const grades = page.getByRole('table', { name: 'Grade rows for this task' })
    await expect(grades.locator('tbody tr').first()).toBeVisible()
    await expect(grades.getByTestId('row-unreviewed').or(grades.getByTestId('row-review')).first()).toBeVisible()
    // the Review cell reads "not reviewed" until the reviews query answers, then a reviewed row's
    // verdict takes its place: check and measure the answered page, not the first render (P-782)
    // — as many verdicts as the API holds standing reviews for the page's rows
    const [, , taskRepo = '', taskId = ''] = new URL(page.url()).pathname.split('/').map(decodeURIComponent)
    const detail = (await (await page.request.get(`${env.baseUrl}/api/v1/tasks/${encodeURIComponent(taskRepo)}/${encodeURIComponent(taskId)}`)).json()) as { grades: Array<{ row_hash: string }> }
    const reviews = (await (await page.request.get(`${env.baseUrl}/api/v1/reviews?repo=${encodeURIComponent(taskRepo)}&task_id=${encodeURIComponent(taskId)}&limit=200`)).json()) as { items: Array<{ grade_row_hash: string }> }
    const reviewed = new Set(reviews.items.map((r) => r.grade_row_hash))
    await expect(grades.getByTestId('row-review')).toHaveCount(detail.grades.filter((g) => reviewed.has(g.row_hash)).length)
    await axeClean(page, '/tasks/<graded>')
    // the same page at phone width: the document does not scroll sideways, the grade table's
    // region sits inside the viewport, and the table fits that region — no sideways scroll even
    // inside it — with the verdict (Clean) and the evidence on screen and the rest folded
    await page.setViewportSize({ width: 375, height: 812 })
    await expect(grades.locator('tbody tr').first()).toBeVisible()
    await expect(page.getByTestId('grades-narrow-note')).toBeVisible()
    await expect(grades.getByRole('columnheader', { name: /Clean/ })).toBeVisible()
    await expect(grades.getByRole('columnheader', { name: /Evidence/ })).toBeVisible()
    const fit = await page.evaluate(() => {
      const region = document.querySelector<HTMLElement>('[role="region"][aria-label="Grade rows for this task"]')
      const box = region?.getBoundingClientRect()
      return {
        scroll: document.documentElement.scrollWidth,
        inner: window.innerWidth,
        regionRight: box ? Math.round(box.right) : Infinity,
        tableScroll: region?.scrollWidth ?? Infinity,
        tableClient: region?.clientWidth ?? 0,
      }
    })
    expect(fit.scroll, `/tasks/<graded> @ 375: the page scrolls sideways (scrollWidth ${fit.scroll} > ${fit.inner})`).toBeLessThanOrEqual(fit.inner)
    expect(fit.regionRight, '/tasks/<graded> @ 375: the grade table\'s region runs past the viewport').toBeLessThanOrEqual(fit.inner)
    expect(fit.tableScroll, `/tasks/<graded> @ 375: the grade table is wider than its region (${fit.tableScroll} > ${fit.tableClient}), so a phone reader must scroll it sideways`).toBeLessThanOrEqual(fit.tableClient)
    await axeClean(page, '/tasks/<graded> @ 375')
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
    // the connect stream's own flow reading is API-backed content on this screen too
    await expect(page.locator('#flow-connect-and-prove')).toBeVisible()
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
