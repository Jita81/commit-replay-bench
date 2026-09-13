import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end smoke against the built bundle served by `vite preview`. The
 * API is never contacted: each spec intercepts `/api/v1/**` with
 * `page.route` and answers from fixtures, so the suite is hermetic and runs
 * in CI without a server. Browsers: `npm run e2e:install` once.
 */
const PORT = Number(process.env.CRB_UI_E2E_PORT ?? 4173)

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run build && npx vite preview --port ${PORT} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}/login`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
