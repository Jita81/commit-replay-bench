/**
 * repo-config — editing a repository's configuration from the UI. Proves, on a repo this
 * spec registers from the tier-1 fixture with a deliberately bare config:
 *
 *   1. the Configuration tab edits every RepoConfig field; switching the language limits
 *      the runner and swaps the runner-options sub-form (jest: extra_args + env, no pytest
 *      keys); an explicit belt-scope list has a row editor; Save sends ONLY the changed
 *      fields (asserted on the PUT body) and the audit trail shows the redacted diff event;
 *   2. the edit persists across a reload, and the raw-JSON view round-trips the sub-form;
 *   3. switching back to the Python shape with the interpreter pinned, then "Run probe now"
 *      from the save toast: the probe run goes green and the result is shown inline;
 *   4. a viewer sees the same tab read-only; the tab has no WCAG 2.1 AA violations.
 *
 * Runs after 01–07 (file order) on the same stack; it touches only its own repo.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec for the Configuration tab, on a repo it registers itself
 *               from the tier-1 fixture with a deliberately bare config.
 * What it does: Pins that the tab edits every `RepoConfig` field; that switching the
 *               language limits the runner and swaps the runner-options sub-form; that an
 *               explicit belt-scope list has a row editor; that Save sends ONLY the changed
 *               fields (asserted on the PUT body) and the audit trail shows the redacted diff
 *               event; that the edit persists across a reload and the raw-JSON view
 *               round-trips; that "Run probe now" from the save toast goes green with the
 *               result inline; and that a viewer sees the tab read-only with no WCAG 2.1 AA
 *               violations.
 * How:          Runs after 01–07 on the same stack and touches only its own repo; the PUT
 *               body is captured through Playwright's request interception.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Repos/RepoConfigTab.tsx,
 *               ui/src/screens/Repos/RepoConfigForm.tsx and ui/src/screens/Repos/RunnerOptsEditor.tsx
 *               (the code under test), src/crb/server/routes/repos.py (the PUT and the
 *               audit event)
 * Tested by:    ui/e2e/walkthrough/repo-config.spec.ts
 * Touch when:   a `RepoConfig` field is added (assert its round-trip here) or the audit
 *               event payload changes.
 */
import AxeBuilder from '@axe-core/playwright'
import type { Page, Request } from '@playwright/test'
import { env, expect, field, signIn, test } from './support'

test.describe.configure({ mode: 'serial' })

const NAME = `${env.repoName}-cfg`
const MIN = 60_000

async function openConfig(page: Page): Promise<void> {
  await page.goto(`/repos/${encodeURIComponent(NAME)}`)
  await page.getByRole('tab', { name: 'Configuration' }).click()
  await expect(page.getByTestId('repo-config-form')).toBeVisible()
}

/** The next `PUT /repos/{NAME}` body the page sends. */
function nextPut(page: Page): Promise<Record<string, unknown>> {
  return page
    .waitForRequest((r: Request) => r.method() === 'PUT' && r.url().endsWith(`/api/v1/repos/${encodeURIComponent(NAME)}`))
    .then((r) => JSON.parse(r.postData() ?? '{}') as Record<string, unknown>)
}

async function addRow(page: Page, listTestId: string, label: string, values: string[]): Promise<void> {
  for (const [i, v] of values.entries()) {
    await page.getByTestId(`${listTestId}-add`).click()
    await page.getByLabel(`${label} ${i + 1}`, { exact: true }).fill(v)
  }
}

test.describe('repo configuration editing', () => {
  test('register a repo with a bare config (no runner options, TARGET_ONLY belt)', async ({ page }) => {
    if (!env.repoUrl) throw new Error('CRB_E2E_REPO_URL is not set (tier 1 fixture required)')
    await page.goto('/repos')
    await page.getByRole('button', { name: 'Add repo' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add a repository' })
    await field(dialog, 'Name').fill(NAME)
    await field(dialog, 'Git URL').fill(env.repoUrl)
    await field(dialog, 'Source prefix').fill('src/')
    await field(dialog, 'Test prefix').fill('tests/')
    await field(dialog, 'Probe scope').fill('tests/test_calc.py')
    // the runner select only offers what runs Python
    const runnerOptions = await field(dialog, 'Runner').locator('option').allTextContents()
    expect(runnerOptions).toEqual(['(default for language)', 'pytest'])
    await dialog.getByRole('button', { name: 'Add repo' }).click()
    await page.waitForURL(new RegExp(`/repos/${NAME}$`))
    await expect(page.getByTestId('repo-probe')).toHaveAttribute('aria-label', 'Probe: not yet run')
  })

  test('Configuration tab: jest shape with extra_args + an explicit belt list; the PUT carries only the changed fields; the audit trail shows the diff', async ({ page }) => {
    await openConfig(page)
    await expect(page.getByTestId('repo-config-save')).toBeDisabled()
    await expect(page.getByTestId('repo-config-runner')).toHaveValue('pytest')
    await expect(page.getByLabel('Python interpreter', { exact: true })).toBeVisible()
    // the audit trail already carries the creation event
    const trail = page.getByTestId('repo-config-audit')
    await expect(trail.getByTestId('repo-config-audit-event')).toHaveCount(1)
    await expect(trail.getByTestId('repo-config-audit-event').first()).toHaveAttribute('data-action', 'repo.created')

    await page.getByTestId('repo-config-language').selectOption('javascript')
    const runner = page.getByTestId('repo-config-runner')
    expect(await runner.locator('option').allTextContents()).toEqual(['node', 'vitest', 'jest', 'mocha'])
    await runner.selectOption('jest')
    // the sub-form swapped: jest keys, no pytest keys
    await expect(page.getByLabel('npm binary', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Python interpreter', { exact: true })).toHaveCount(0)
    await page.getByTestId('repo-config-ext').fill('.js|.ts|.tsx')
    await page.getByTestId('repo-config-test-mode').selectOption('suffix')
    await expect(page.getByTestId('repo-config-save')).toBeDisabled() // suffix mode without suffixes: the server's 422, refused here
    await expect(page.getByText("test_mode='suffix' requires test_suffix")).toBeVisible()
    await page.getByTestId('repo-config-test-suffix').fill('.test.js|.test.ts|.test.tsx|.snap')
    await page.getByTestId('repo-config-belt-LIST').check()
    await addRow(page, 'repo-config-belt-list', 'Belt scope', ['tests/', 'packages/'])
    await addRow(page, 'runner-opt-extra_args', 'Extra arguments', ['--selectProjects', 'unit'])
    await page.getByTestId('runner-opt-env-add').click()
    await page.getByLabel('Environment variables name 1', { exact: true }).fill('PATH')
    await page.getByLabel('Environment variables value 1', { exact: true }).fill('/opt/node@24/bin:/usr/bin:/bin')
    await expect(page.getByTestId('repo-config-pending')).toContainText('belt_scope, ext, language, runner, runner_opts, test_mode, test_suffix')

    const put = nextPut(page)
    await page.getByTestId('repo-config-save').click()
    expect(await put).toEqual({
      language: 'javascript',
      runner: 'jest',
      ext: '.js|.ts|.tsx',
      test_mode: 'suffix',
      test_suffix: '.test.js|.test.ts|.test.tsx|.snap',
      belt_scope: ['tests/', 'packages/'],
      runner_opts: { extra_args: ['--selectProjects', 'unit'], env: { PATH: '/opt/node@24/bin:/usr/bin:/bin' } },
    })
    const toast = page.getByTestId('repo-config-toast')
    await expect(toast).toBeVisible()
    await expect(toast).toContainText('Saved belt_scope, ext, language, runner, runner_opts, test_mode, test_suffix')
    await expect(page.getByTestId('repo-config-save')).toBeDisabled()
    // the audit trail gained the diff event, newest first, with the changed fields
    await expect(trail.getByTestId('repo-config-audit-event')).toHaveCount(2)
    const newest = trail.getByTestId('repo-config-audit-event').first()
    await expect(newest).toHaveAttribute('data-action', 'repo.updated')
    await expect(newest.getByTestId('repo-config-audit-fields')).toContainText('belt_scope')
    await expect(newest.getByTestId('repo-config-audit-fields')).toContainText('runner_opts')
    await newest.getByText('Diff (redacted at write)').click()
    await expect(newest).toContainText('"from": "TARGET_ONLY"') // the belt_scope diff, as stored
    await expect(newest).toContainText('"to": "jest"')
    await expect(newest).toContainText('--selectProjects') // runner_opts.to.extra_args
  })

  test('the edit persisted; raw JSON round-trips the sub-form', async ({ page }) => {
    await openConfig(page)
    await expect(page.getByTestId('repo-config-language')).toHaveValue('javascript')
    await expect(page.getByTestId('repo-config-runner')).toHaveValue('jest')
    await expect(page.getByTestId('repo-config-belt-LIST')).toBeChecked()
    await expect(page.getByLabel('Belt scope 2', { exact: true })).toHaveValue('packages/')
    await expect(page.getByLabel('Extra arguments 2', { exact: true })).toHaveValue('unit')
    await page.getByTestId('runner-opts-mode-json').click()
    const json = page.getByTestId('runner-opts-json')
    expect(JSON.parse(await json.inputValue())).toEqual({ extra_args: ['--selectProjects', 'unit'], env: { PATH: '/opt/node@24/bin:/usr/bin:/bin' } })
    await json.fill(JSON.stringify({ extra_args: ['--selectProjects', 'unit', '--ci'], env: { PATH: '/opt/node@24/bin:/usr/bin:/bin' } }))
    await page.getByTestId('runner-opts-mode-form').click()
    await expect(page.getByLabel('Extra arguments 3', { exact: true })).toHaveValue('--ci')
    await expect(page.getByTestId('repo-config-pending')).toContainText('runner_opts')
    await page.getByTestId('repo-config-reset').click()
    await expect(page.getByTestId('repo-config-save')).toBeDisabled()
    await expect(page.getByLabel('Extra arguments 3', { exact: true })).toHaveCount(0)
  })

  test('back to the Python shape with the interpreter pinned; save; Run probe now → green inline', async ({ page }) => {
    await openConfig(page)
    await page.getByTestId('repo-config-language').selectOption('python')
    await expect(page.getByTestId('repo-config-runner')).toHaveValue('pytest')
    await page.getByTestId('repo-config-ext').fill('.py')
    await page.getByTestId('repo-config-test-mode').selectOption('prefix')
    await expect(page.getByTestId('repo-config-test-prefix')).toHaveValue('tests/')
    await page.getByTestId('repo-config-belt-list-remove-1').click() // drop packages/, keep tests/
    // the jest-only key is kept but listed as unread (env is read by pytest too, so it stays a
    // sub-form field); drop both, then pin the interpreter
    const extra = page.getByTestId('runner-opts-extra')
    await expect(extra).toContainText('extra_args')
    await expect(extra).not.toContainText('env')
    await page.getByTestId('runner-opts-extra-remove-extra_args').click()
    await expect(page.getByTestId('runner-opts-extra')).toHaveCount(0)
    await expect(page.getByLabel('Environment variables name 1', { exact: true })).toHaveValue('PATH')
    await page.getByTestId('runner-opt-env-remove-0').click()
    if (env.python) await page.getByLabel('Python interpreter', { exact: true }).fill(env.python)
    await page.getByLabel('PYTHONPATH suffix', { exact: true }).fill('/src')

    const put = nextPut(page)
    await page.getByTestId('repo-config-save').click()
    const body = await put
    expect(Object.keys(body).sort()).toEqual(['belt_scope', 'ext', 'language', 'runner', 'runner_opts', 'test_mode'])
    expect(body.belt_scope).toEqual(['tests/'])
    expect(body.runner_opts).toEqual(env.python ? { python: env.python, pythonpath_suffix: '/src' } : { pythonpath_suffix: '/src' })

    await page.getByTestId('repo-config-toast-probe').click()
    const result = page.getByTestId('repo-config-probe-result')
    await expect(result).toBeVisible()
    await expect.poll(async () => result.getAttribute('data-outcome'), { timeout: 2 * MIN, intervals: [1000, 2000] }).not.toBe('pending')
    await expect(result).toHaveAttribute('data-outcome', 'green')
    await expect(page.getByTestId('repo-config-probe-reason')).toHaveText(/\d+ passed/)
    await expect(result.getByRole('link', { name: /^run [0-9a-f]{8}$/ })).toBeVisible()
    // three events now: created + two updates
    await expect(page.getByTestId('repo-config-audit').getByTestId('repo-config-audit-event')).toHaveCount(3)
    // and the overview agrees
    await page.getByRole('tab', { name: 'Overview' }).click()
    await expect(page.getByTestId('repo-probe')).toHaveAttribute('aria-label', 'Probe: ok')
  })

  test('a viewer reads the configuration but cannot edit it; the tab is WCAG 2.1 AA clean', async ({ page, browser }) => {
    // create a viewer through the Settings screen (admin), then sign in as them elsewhere
    const viewer = `cfg-viewer-${Date.now().toString(36)}`
    const password = `Vw-${Date.now().toString(36)}-x9Q`
    await page.goto('/settings')
    const users = page.locator('section', { hasText: 'Create local user' })
    await field(users, 'Username').fill(viewer)
    await field(users, 'Display name').fill('Config Viewer')
    await field(users, 'Email').fill(`${viewer}@example.org`)
    await field(users, 'Role').selectOption('viewer')
    await field(users, 'Initial password').fill(password)
    await users.getByRole('button', { name: 'Create local user' }).click()
    await expect(users.getByText(`${viewer}@example.org`, { exact: true })).toBeVisible()

    // the operator's own tab is accessible
    await openConfig(page)
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])

    const ctx = await browser.newContext()
    const other = await ctx.newPage()
    await signIn(other, viewer, password)
    await openConfig(other)
    await expect(other.getByTestId('repo-config-readonly')).toContainText('viewer')
    await expect(other.getByTestId('repo-config-language')).toBeDisabled()
    await expect(other.getByTestId('repo-config-probe')).toBeDisabled()
    await expect(other.getByTestId('repo-config-save')).toHaveCount(0)
    await expect(other.getByTestId('repo-config-probe-run')).toHaveCount(0)
    await expect(other.getByTestId('repo-config-belt-list-add')).toHaveCount(0)
    // the viewer still reads the audit trail and the stored config
    await expect(other.getByTestId('repo-config-audit').getByTestId('repo-config-audit-event')).toHaveCount(3)
    await ctx.close()
  })
})
