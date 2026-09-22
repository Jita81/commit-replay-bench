/**
 * Smoke: the login page renders against a mocked API, the brand is present,
 * the OIDC button points at the contract's start URL, and the page has no
 * WCAG 2.1 AA violations (axe). Then a logged-in shell renders the nav.
 *
 * Navigation
 * ----------
 * What it is:   The hermetic Playwright smoke suite (`npm run e2e`) over the built bundle
 *               served by `vite preview`.
 * What it does: Pins that the login page renders with the brand, links to the contract's
 *               OIDC start URL and passes axe; that a protected route redirects to `/login`
 *               with `?next=`; that the index route `/` — the address a person types or
 *               bookmarks — lands on `/login?next=%2F` with no session and on `/home` with
 *               one (G-921: until this pair existed no test visited `/` at all); that a
 *               logged-in shell shows the nav, the user chip with its role and the ledger
 *               gate, and passes axe; and that an unknown route renders the 404 inside the
 *               shell. No server is contacted.
 * How:          `page.route` intercepts every `/api/v1` request and answers from inline
 *               fixtures (`/auth/me` 401 or a principal, `/ledger/verify`, `/health`,
 *               `/version`); `AxeBuilder` with the WCAG 2.1 AA tags.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/playwright.config.ts (builds, serves `dist/` and ignores the walkthrough),
 *               ui/src/screens/Login/LoginPage.tsx and ui/src/components/Layout.tsx (the
 *               screens under test), ui/src/lib/auth.tsx (the redirect and the
 *               index route's `RequireAuth`), ui/src/App.tsx (the `<Route index>` this
 *               visits), .github/workflows/ci.yml (the `ui-smoke` job that runs this)
 * Tested by:    ui/e2e/smoke.spec.ts
 * Touch when:   the login page, the shell's nav, the index route or the auth redirect
 *               changes; never for a new repository.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const envelope = (status: number, code: string, message: string) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify({ error: { code, message, detail: {} } }),
})

async function mockApi(page: Page, loggedIn: boolean) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api\/v1/, '')
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/me') {
      return loggedIn
        ? json({ id: 'u1', display_name: 'Ada Lovelace', email: 'ada@example.org', role: 'approver', issuer: 'local' })
        : route.fulfill(envelope(401, 'unauthenticated', 'not signed in'))
    }
    if (path === '/health') return json({ status: 'ok', probes: [{ name: 'db', status: 'ok', detail: 'append-only triggers present', data: {} }] })
    if (path === '/version') return json({ crb: '2.0.0', apparatus: '2.0', policy: 'routing.v1', oidc_enabled: true })
    if (path === '/repos') return json({ items: [], total: 0, limit: 50, offset: 0 })
    if (path === '/ledger/verify') return json({ rows: 0, ok: true, false_q1_total: 0 })
    return route.fulfill(envelope(404, 'not_found', `no fixture for ${path}`))
  })
}

test.describe('login page', () => {
  test('renders, links to OIDC start, and has no WCAG 2.1 AA violations', async ({ page }) => {
    await mockApi(page, false)
    await page.goto('/login')

    await expect(page.getByRole('heading', { level: 1, name: 'Commit Replay Bench' })).toBeVisible()
    await expect(page.getByLabel('Username')).toBeVisible()
    await expect(page.getByLabel('Password')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
    const oidc = page.getByRole('link', { name: 'Sign in with organisation account' })
    await expect(oidc).toHaveAttribute('href', /^\/api\/v1\/auth\/oidc\/start/)

    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])
  })

  test('a protected route redirects to /login with ?next=', async ({ page }) => {
    await mockApi(page, false)
    await page.goto('/capability?repo=x')
    await expect(page).toHaveURL(/\/login\?next=%2Fcapability%3Frepo%3Dx/)
  })
})

// The index route (`<Route index>` in App.tsx) is the address a person types or bookmarks.
// It is inside RequireAuth and redirects to /home, so it has two answers — and until this
// pair existed no test visited `/` at all (the login spec asserts the LoginPage default,
// which is a different line of code).
test.describe('the index route', () => {
  test('signed out, / lands on /login?next=%2F', async ({ page }) => {
    await mockApi(page, false)
    await page.goto('/')
    await expect(page).toHaveURL(/\/login\?next=%2F$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Commit Replay Bench' })).toBeVisible()
  })

  test('signed in, / lands on /home inside the shell', async ({ page }) => {
    await mockApi(page, true)
    await page.goto('/')
    await expect(page).toHaveURL(/\/home$/)
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
  })
})

test.describe('shell', () => {
  test('logged-in shell shows the nav, user chip with role, and the ledger gate; axe clean', async ({ page }) => {
    await mockApi(page, true)
    await page.goto('/ledger')
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
    // an approver sees the journey and, of the instrument row, only the ledger
    for (const label of ['Home', 'Connection', 'Baseline', 'Factory', 'Deployment', 'Ledger']) {
      await expect(page.getByRole('link', { name: label, exact: true })).toBeVisible()
    }
    // Decisions carries the waiting-count badge, so its accessible name is the label and the
    // count ("Decisions0" with nothing connected) — not the bare word
    await expect(page.getByRole('link', { name: /^Decisions/ })).toBeVisible()
    await expect(page.getByTestId('user-chip')).toContainText('approver')
    await expect(page.getByTestId('ledger-gate')).toHaveAttribute('data-state', 'OPEN')
    await expect(page.getByRole('link', { name: 'Export JSONL' })).toHaveAttribute('href', '/api/v1/ledger/export?format=jsonl')

    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])
  })

  test('unknown routes render the 404 inside the shell', async ({ page }) => {
    await mockApi(page, true)
    await page.goto('/nope/here')
    await expect(page.getByRole('heading', { level: 1, name: 'This page does not exist' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
  })
})
