import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { expect, primary, test } from './support'

/**
 * 07 — the instrument describes itself honestly, and every screen the walkthrough
 * touched is accessible. Proves: the Settings page shows each builder credential as
 * configured yes/no (never a value), the sandbox mode, and the apparatus / policy
 * versions the footer also carries; then axe (WCAG 2.1 AA) finds 0 violations on
 * Repos, Runs, a Run detail (with real rows), Capability, Ledger and Sign-off —
 * against the live data these specs produced, not fixtures.
 */
test.describe.configure({ mode: 'serial' })

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

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
})
