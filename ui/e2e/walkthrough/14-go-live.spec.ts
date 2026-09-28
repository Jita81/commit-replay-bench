/**
 * 14 — deploy and go live, walked as the bootstrap admin, and the Deployment page read as a
 * review board reads it: dod.journey.deploy-and-go-live in one spec.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 14 (go-live), tier 1 and tier 2 alike. It changes only its own
 *               account (`walk-golive-approver`), a token it stores and removes, and one
 *               go-live attestation it records and then withdraws, so the stack is left as
 *               it was found.
 * What it does: Settings: the health card lists the probes, the builder token is stored (its
 *               fingerprint only) and removed, the GitHub App is synced or reads not
 *               configured, and an approver is created through the form. Deployment: the
 *               eyebrow names the stream, the journey and step 3 of 4; one row of each of the
 *               five posture groups is read against the deployment's own probes and the
 *               footer's versions; every row names its source; the go-live section reads each
 *               line against this stack — health and ledger proven, the sealed posture
 *               unproven on a local executor with both executors named, the egress test
 *               unproven with no attestation. The admin records the egress test on Settings,
 *               and the Deployment page shows it attested with the admin's name, the day and
 *               the words; the page prints without the shell's header and help; the
 *               attestation is withdrawn and the line reads unproven again. Home's task 7
 *               reads Completed. Both screens are axe-clean in the states the walk leaves.
 * How:          The `test` fixture's page is the signed-in bootstrap admin; `page.emulateMedia`
 *               for the print; `axeViolations` settles transitions first (P-130).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
 * Works with:   ui/e2e/walkthrough/support.ts (`field`, `env`, `personaPassword`, `test`),
 *               ui/e2e/axe.ts, ui/src/screens/Posture/PosturePage.tsx and GoLiveList.tsx,
 *               ui/src/screens/Settings/AttestationsCard.tsx, src/crb/server/golive.py,
 *               docs/dod/journeys/deploy-and-go-live.md (the journey it proves)
 * Tested by:    ui/e2e/walkthrough/14-go-live.spec.ts
 * Touch when:   never for a new repository; a step of the go-live journey changes, a go-live
 *               line is added, or the Deployment page's groups change.
 */
import type { Locator, Page } from '@playwright/test'
import { axeViolations } from '../axe'
import { env, expect, field, personaPassword, test } from './support'

test.describe.configure({ mode: 'serial' })

//: The approver this spec creates through the form; no other spec signs in as it.
const APPROVER = 'walk-golive-approver'
//: A shape-valid fake `claude setup-token` value (never a real credential; tier 1 is offline).
const FAKE_SETUP_TOKEN = 'sk-ant-oat01-' + 'G'.repeat(72) + '-GOL1'
const STATEMENT = 'Egress from worker-0 to 1.1.1.1:443 timed out; the transcript is in change CHG-GOLIVE-14'

/** A task row of Home's list, by its number (1–8). */
function task(page: Page, n: number): Locator {
  return page.getByRole('list', { name: 'Tasks' }).getByRole('listitem').nth(n - 1)
}

/** One summary row of the Deployment page, by its group heading and its key. */
function postureRow(page: Page, group: string, key: string): Locator {
  const section = page.locator('section', { has: page.getByRole('heading', { level: 2, name: group, exact: true }) })
  return section.locator('dl > div, dl > [data-hint]').filter({ has: page.locator('dt', { hasText: new RegExp(`^${key}`) }) })
}

async function axeClean(page: Page, where: string): Promise<void> {
  const violations = await axeViolations(page)
  expect(violations, `${where}: ${JSON.stringify(violations, null, 2)}`).toEqual([])
}

function yesterday(): string {
  const d = new Date(Date.now() - 24 * 3600 * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

test.describe('14 go live', () => {
  test('the admin reads the health, stores the token, syncs or reads the app, and creates an approver through the form', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByText('Run the platform · Deploy and go live · 2 of 4 · Settings')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Instrument health' })).toBeVisible()
    for (const probe of ['db', 'migrations', 'append_only', 'ledger', 'worker']) await expect(page.getByRole('img', { name: new RegExp(`^${probe}: `) })).toBeVisible()

    // the builder token: stored as its fingerprint only, then removed (the stack as it was)
    const status = page.getByTestId('claude-login-status')
    await page.getByTestId('claude-login-token').fill(FAKE_SETUP_TOKEN)
    await page.getByTestId('claude-login-save').click()
    await expect(status).toHaveAttribute('data-present', 'true')
    await expect(status).toContainText('…GOL1')
    expect((await page.locator('main').textContent()) ?? '').not.toContain(FAKE_SETUP_TOKEN)
    await page.getByTestId('claude-login-remove').click()
    await page.getByTestId('claude-login-remove-confirm').getByRole('button', { name: 'Yes, remove it' }).click()
    await expect(status).toHaveAttribute('data-present', 'false')

    // the GitHub App: synced when it is configured, else it says what to set
    const app = page.getByTestId('github-app-status')
    await expect(app).toBeVisible()
    if ((await app.textContent())?.includes('not configured')) {
      await expect(app).toContainText('CRB_GITHUB__APP_ID')
    } else {
      await page.getByRole('button', { name: 'Sync installations' }).click()
      await expect(page.getByTestId('github-sync-said')).toBeVisible()
    }

    // the approver, through the form
    const users = page.getByRole('table', { name: 'Users' })
    await expect(users).toBeVisible()
    if ((await users.getByRole('cell', { name: APPROVER, exact: true }).count()) === 0) {
      await field(page, 'Username').fill(APPROVER)
      await field(page, 'Display name').fill('Walk go-live approver')
      await field(page, 'Email').fill(`${APPROVER}@example.org`)
      await field(page, 'Role').selectOption('approver')
      await field(page, 'Initial password').fill(personaPassword(APPROVER))
      await page.getByRole('button', { name: 'Create local user' }).click()
      await expect(page.getByTestId('users-created')).toContainText(`Account ${APPROVER} created as approver`)
    }
    await expect(users.getByRole('row', { name: new RegExp(APPROVER) })).toContainText('approver')
  })

  test('the Deployment page reads one row of each group against the deployment’s own probes, and every row names its source', async ({ page }) => {
    await page.goto('/posture')
    await expect(page.getByText('Run the platform · Deploy and go live · 3 of 4 · Deployment')).toBeVisible()
    const footer = (await page.getByRole('contentinfo').textContent()) ?? ''
    const version = /crb (\S+) · apparatus (\S+) · policy (\S+)/.exec(footer)
    expect(version, footer).not.toBeNull()
    // Build and apparatus: the version the footer (GET /version) carries
    await expect(postureRow(page, 'Build and apparatus', 'Version')).toContainText(`crb ${version![1]}`)
    await expect(postureRow(page, 'Build and apparatus', 'Policies in force')).toContainText('signoff-policy.v3')
    // Identity and access: this stack signs in locally (no provider configured in tier 1)
    await expect(postureRow(page, 'Identity and access', 'Sign-in')).toContainText(/Local accounts only|OpenID Connect/)
    // Execution and egress: the executor the stack was started with
    await expect(postureRow(page, 'Execution and egress', 'Production posture')).toContainText(/development|sealed|unsealed/)
    // Delivery: the route gate names the policy the footer carries
    await expect(postureRow(page, 'Delivery', 'Route gate')).toContainText(version![3]!)
    // Data and audit: the live verification the ledger route serves
    const verify = (await (await page.request.get('/api/v1/ledger/verify')).json()) as { rows: number; ok: boolean }
    await expect(postureRow(page, 'Data and audit', 'Ledger')).toContainText(`${verify.rows} rows`)
    // every row of the five groups names where its value comes from
    for (const group of ['Build and apparatus', 'Identity and access', 'Execution and egress', 'Delivery', 'Data and audit']) {
      const rows = page.locator('section', { has: page.getByRole('heading', { level: 2, name: group, exact: true }) }).locator('dl > div, dl > [data-hint]')
      const n = await rows.count()
      expect(n, group).toBeGreaterThan(0)
      for (let i = 0; i < n; i += 1) await expect(rows.nth(i), `${group} row ${i}`).toContainText('Source: ')
    }
  })

  test('the go-live section reads each line against this stack, an attestation recorded on Settings shows who, when and what, and the page prints for a review board', async ({ page }) => {
    const health = (await (await page.request.get('/api/v1/health')).json()) as { status: string; posture: { sealed: boolean } }
    await page.goto('/posture')
    const section = page.getByTestId('posture-go-live')
    await expect(section.getByTestId('golive-counts')).toContainText('of 15 go-live lines stand')
    await expect(section.getByTestId('golive-ledger-verified')).toContainText('Proven')
    await expect(section.getByRole('img', { name: /^The health check is green: / })).toHaveAccessibleName(health.status === 'ok' ? /Proven$/ : /Unproven$/)
    if (!health.posture.sealed) await expect(section.getByTestId('golive-sealed-posture')).toContainText(/Unproven.*tests run \S+, the builder runs \S+/)
    await expect(section.getByRole('heading', { name: 'Acts the operator attests' })).toBeVisible()
    for (const act of ['penetration test', 'egress test', 'restore has been rehearsed', 'alert fires', 'released digest']) await expect(section).toContainText(new RegExp(act, 'i'))

    // a rerun against a stack the last run left attested: withdraw first, so the walk starts unproven
    const egress = section.getByTestId('golive-egress-denied')
    await page.goto('/settings#golive-attestations')
    const card = page.locator('#golive-attestations')
    await expect(card.getByTestId('attest-form')).toBeVisible()
    if (await card.getByTestId('withdraw-egress-denied').count()) {
      await card.getByTestId('withdraw-egress-denied').click()
      await card.getByTestId('withdraw-confirm-egress-denied').click()
      await expect(card.getByTestId('attest-done')).toContainText('reads unproven again')
    }
    await page.goto('/posture')
    await expect(egress).toContainText('Unproven')
    await expect(egress).toContainText('no attestation is recorded')
    await axeClean(page, '/posture')

    // the admin records the egress test on Settings; a line the product proves is not offered
    await page.goto('/settings#golive-attestations')
    await expect(card.getByTestId('attest-line').locator('option[value="health-green"]')).toHaveCount(0)
    await card.getByTestId('attest-line').selectOption('egress-denied')
    await card.getByTestId('attest-statement').fill(STATEMENT)
    await card.getByTestId('attest-day').fill(yesterday())
    await card.getByTestId('attest-submit').click()
    await expect(card.getByTestId('attest-done')).toContainText(`was done on ${yesterday()}`)
    await expect(card.getByTestId('attestation-egress-denied')).toContainText('Attested')
    await axeClean(page, '/settings (an attestation recorded)')

    // the review board reads it on the Deployment page: who, the day it was done, what was done
    await page.goto('/posture')
    await expect(egress).toContainText('Attested')
    await expect(section.getByTestId('golive-egress-denied-attestation')).toContainText(`Done on ${yesterday()}, recorded by ${env.user}`)
    await expect(section.getByTestId('golive-egress-denied-attestation')).toContainText(STATEMENT)

    // the page prints: the statement and its versions, without the shell's header or the help
    await expect(page.getByRole('button', { name: 'Print this page' })).toBeVisible()
    await page.emulateMedia({ media: 'print' })
    await expect(page.getByTestId('shell-header')).toBeHidden()
    await expect(page.getByTestId('about-this-screen')).toBeHidden()
    await expect(page.getByRole('button', { name: 'Print this page' })).toBeHidden()
    await expect(section).toBeVisible()
    await expect(page.getByRole('contentinfo')).toBeVisible()
    await page.emulateMedia({ media: 'screen' })

    // withdraw: the line reads unproven again, and the stack is left as it was found
    await page.goto('/settings#golive-attestations')
    await card.getByTestId('withdraw-egress-denied').click()
    await card.getByTestId('withdraw-confirm-egress-denied').click()
    await expect(card.getByTestId('attest-done')).toContainText('reads unproven again')
    await page.goto('/posture')
    await expect(egress).toContainText('Unproven')
  })

  test('Home’s task 7 reads Completed once an approver exists', async ({ page }) => {
    await page.goto('/home')
    await expect(task(page, 7)).toContainText('Invite an approver')
    await expect(task(page, 7)).toContainText('Completed')
  })
})
