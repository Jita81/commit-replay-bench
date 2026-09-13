import { expect, expectLogAction, field, liveLog, targets, test, waitForRun, type RepoTarget } from './support'

/**
 * 02 — onboarding a repository by URL. Proves, for every target repo: the Add-repo
 * dialog (preset + runner options JSON) creates the repo and lands on its page; the
 * worker clones it on the first run (`repo.clone.done` on the probe's live log),
 * prepares the environment when it must (`setup.auto` → `setup.done`), and the probe
 * turns green (`probe.done`); back on the repo page the probe pill reads OK with the
 * runner's own summary ("N passed").
 *
 * Tier 1: tests/fixtures/pyrepo.py over file://. Tier 2 (CRB_E2E_PUBLIC=1): cobra + click.
 */
test.describe.configure({ mode: 'serial' })

async function addRepo(page: import('@playwright/test').Page, t: RepoTarget): Promise<void> {
  await page.goto('/repos')
  await page.getByRole('button', { name: 'Add repo' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a repository' })
  await expect(dialog).toBeVisible()

  await field(dialog, 'Name').fill(t.name)
  await field(dialog, 'Preset').selectOption(t.preset)
  // The preset filled language / runner / layout; check it did, then override what the target needs.
  await expect(field(dialog, 'Language')).toHaveValue(t.language)
  await expect(field(dialog, 'Source')).toHaveValue('url')
  await field(dialog, 'Git URL').fill(t.url)
  await field(dialog, 'Belt scope').selectOption(t.beltScope)
  await field(dialog, 'Probe scope').fill(t.probe)
  if (t.runnerOpts) await field(dialog, 'Runner options (JSON)').fill(JSON.stringify(t.runnerOpts, null, 2))

  const submit = dialog.getByRole('button', { name: 'Add repo' })
  await expect(submit).toBeEnabled()
  await submit.click()
  await page.waitForURL(new RegExp(`/repos/${t.name}$`))
  await expect(page.getByRole('heading', { level: 1, name: t.name })).toBeVisible()
}

for (const t of targets()) {
  test.describe(`repo ${t.name}`, () => {
    test('Add repo via URL with a preset and runner options; the detail page shows it not yet probed', async ({ page }) => {
      await addRepo(page, t)
      await expect(page.getByTestId('repo-probe')).toHaveAttribute('aria-label', 'Probe: not yet run')
      // the config tab carries what we typed
      await page.getByRole('tab', { name: 'Config' }).click()
      const config = page.getByRole('tabpanel')
      await expect(config).toContainText(t.url)
      await expect(config).toContainText(t.probe)
      if (t.runnerOpts) {
        for (const key of Object.keys(t.runnerOpts)) await expect(config).toContainText(key)
      }
      // it is listed
      await page.goto('/repos')
      await expect(page.getByRole('link', { name: t.name, exact: true })).toBeVisible()
    })

    test('Probe now → run page: clone, (setup), probe on the live log; the run succeeds', async ({ page }) => {
      await page.goto(`/repos/${encodeURIComponent(t.name)}`)
      await page.getByRole('button', { name: 'Probe now' }).click()
      await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
      await expect(page.getByRole('heading', { level: 1, name: /^Run [0-9a-f]{8}/ })).toBeVisible()
      await expect(page.locator('h1')).toHaveCount(1)

      await waitForRun(page, 'succeeded', t.probeTimeoutMs)

      const log = liveLog(page)
      await expect(log.getByText('run.claimed', { exact: true })).toBeVisible()
      await expectLogAction(page, 'repo.clone.start')
      await expectLogAction(page, 'repo.clone.done')
      // The environment phase runs only when the runner says the host is not ready
      // (a pinned interpreter is ready; a fresh public clone is not).
      if ((await log.getByText('setup.auto', { exact: true }).count()) > 0) {
        await expectLogAction(page, 'setup.done')
      }
      await expectLogAction(page, 'probe.start')
      await expectLogAction(page, 'probe.done')
      // the clone URL on the log never carries credentials, and the done row reports a head sha
      const cloneDone = log.locator('div', { hasText: 'repo.clone.done' }).last()
      await expect(cloneDone).toContainText('head=')
      await expect(cloneDone).not.toContainText('@')
    })

    test('back on the repo page the probe pill is OK with the runner summary', async ({ page }) => {
      await page.goto(`/repos/${encodeURIComponent(t.name)}`)
      await expect(page.getByTestId('repo-probe')).toHaveAttribute('aria-label', 'Probe: ok')
      await expect(page.getByTestId('repo-probe')).toHaveText(/OK/)
      await expect(page.getByTestId('repo-probe-detail')).toHaveText(t.probeSummary)
      await expect(page.getByRole('link', { name: /^run [0-9a-f]{8}$/ })).toBeVisible()
      // and the list shows the same pill
      await page.goto('/repos')
      const row = page.getByRole('row', { name: new RegExp(`\\b${t.name}\\b`) })
      await expect(row).toBeVisible()
      await expect(row.getByRole('img', { name: /^Probe: ok/ })).toBeVisible()
    })
  })
}
