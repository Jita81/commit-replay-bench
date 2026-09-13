import { defineConfig, devices } from '@playwright/test'

/**
 * The full-browser WALKTHROUGH against a LIVE crb stack (API + worker + built UI).
 *
 * Nothing here is mocked: `scripts/walkthrough.sh` boots a fresh stack in a temp
 * `CRB_HOME`, exports `CRB_E2E_*`, runs this config and tears the stack down. The
 * specs are one story told in order (login → onboard → mine → oracle → replay →
 * cancel → settings/a11y), so files run serially on a single worker; each file is
 * `test.describe.configure({ mode: 'serial' })` as well. Run it with
 * `npm run walkthrough` — never with the mocked smoke config, which excludes this
 * directory. See e2e/walkthrough/README.md for the two tiers and expected durations.
 */
const baseURL = process.env.CRB_E2E_BASE_URL
if (!baseURL) {
  throw new Error('CRB_E2E_BASE_URL is not set — run the walkthrough through scripts/walkthrough.sh (it boots the stack and exports CRB_E2E_*)')
}

const publicTier = process.env.CRB_E2E_PUBLIC === '1'
const reportDir = process.env.CRB_E2E_REPORT_DIR ?? 'playwright-report-walkthrough'

export default defineConfig({
  testDir: './e2e/walkthrough',
  // Tier 1 waits on real (short) runs; tier 2 clones + installs public repos and may build with a model.
  timeout: publicTier ? 30 * 60_000 : 4 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0, // the story is stateful: a retry would replay against a stack the first attempt already changed
  reporter: [['list'], ['html', { open: 'never', outputFolder: reportDir }]],
  outputDir: process.env.CRB_E2E_OUTPUT_DIR ?? 'test-results-walkthrough',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    // Downloads (the ledger export) must be accepted; the spec verifies the file.
    acceptDownloads: true,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
