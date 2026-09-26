/**
 * 13 — sign in and find your way: the shell walked as ONE journey against the live stack.
 *
 * Before this spec the journey was proven in pieces — sign-in in 01, the index redirect in the
 * mocked smoke, Home for axe in 07 and for capture in 11, one guide in 11 — with no path
 * between them (G-413), only OPERATOR of the eight guides was ever opened on the served bundle
 * (G-149), and Home's task tags were proven on mocks alone (G-166).
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 13 (orient: /login → / → /home → /help →
 *               /help/docs/:name → an unknown address → sign out), tier 1 and tier 2
 *               alike; it spends nothing, calls no model and writes nothing but a session
 *               and one baseline-read record.
 * What it does: (1) Walks the six steps in order as one persona (the bootstrap admin),
 *               starting signed out: `/` bounces to `/login?next=%2F`, whose About block says
 *               what the page is for; signing in returns to `/`, which replaces itself with
 *               `/home`; Home lists its eight tasks and names the next one; the About block's
 *               first term opens its glossary entry on /help; that entry's Read more opens
 *               the guide AT the heading it names; an unknown address says so, with its own
 *               About block, and leads back to Home; Sign out ends the session. Every screen
 *               on the way carries "About this screen" (G-926). The pass is timed and the
 *               time is printed and attached to the report — the figure the onboarding guide
 *               quotes (G-414). (2) Opens all eight bundled guides on the served bundle and
 *               asserts each renders its own first heading, the file's, and never an error or
 *               "No guide with that name"; then opens a decision record from /help (G-149,
 *               G-156). (3) Reads Home's task tags for the repository 02–05 onboarded and
 *               measured — Choose a repository, Confirm its shape and Measure read Completed —
 *               then opens that repository's baseline and finds task 6 "Read the baseline"
 *               Completed on the server's record of the read (G-166, G-165).
 * How:          @playwright/test's own `test` (the journey starts signed out, so it does not
 *               use support.ts's signed-in fixture); `field` / `primary` / `env` from
 *               support.ts; the guides' first headings read from docs/ with Node's `fs`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-077, DL-078)
 * Works with:   ui/src/screens/Home/HomePage.tsx (the task list), ui/src/screens/Help/HelpPage.tsx
 *               and DocPage.tsx (the glossary, the guides and the records), ui/src/help/help.ts
 *               (the About blocks it asserts), ui/src/screens/Login/LoginPage.tsx (the About
 *               block it mounts), ui/src/help/docs.ts (`DOC_NAMES`), ui/e2e/walkthrough/support.ts,
 *               docs/dod/journeys/orient.md (the journey this walks)
 * Tested by:    scripts/walkthrough.sh (CI job `walkthrough`)
 * Touch when:   a step of the orient journey changes (docs/dod/journeys/orient.md first), or a
 *               guide is added to `DOC_NAMES`.
 */
import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { env, field, primary } from './support'

test.describe.configure({ mode: 'serial' })

/** The eight guides the UI bundles, in /help's order (ui/src/help/docs.ts `DOC_NAMES`). */
const GUIDES = ['ONBOARDING-A-REPO', 'OPERATOR', 'EVIDENCE-AND-CLAIMS', 'GITHUB-APP', 'SECURITY', 'DATA-RETENTION', 'LEARNING-LOOP', 'DEPLOYMENT'] as const

/** The first heading of `docs/<name>.md`, as the file says it — what the page must render. */
function firstHeading(name: string): string {
  const text = readFileSync(new URL(`../../../docs/${name}.md`, import.meta.url), 'utf8')
  const line = text.split('\n').find((l) => l.startsWith('# '))
  expect(line, `docs/${name}.md has no first heading`).toBeTruthy()
  return line!.slice(2).trim()
}

/** The About block on the current screen, opened; asserts it is there and says `purpose`. */
async function about(page: Page, purpose: string | RegExp): Promise<void> {
  const block = page.getByTestId('about-this-screen')
  await expect(block, `${page.url()}: no About this screen block`).toHaveCount(1)
  const summary = block.getByText('About this screen')
  const open = await block.locator('details').evaluate((d) => (d as HTMLDetailsElement).open)
  if (!open) await summary.click()
  await expect(block).toContainText(purpose)
}

/** A task row of Home's list, by its number (1–8). */
function task(page: Page, n: number) {
  return page.getByRole('list', { name: 'Tasks' }).getByRole('listitem').nth(n - 1)
}

test.describe('13 orient — sign in and find your way', () => {
  test('one persona walks the shell as a journey: sign-in, the index, Home, a term, its guide heading, an unknown address, sign out', async ({ page }) => {
    const started = Date.now()

    // (1) a signed-out visit to the index bounces to sign-in, carrying where it was going
    await page.goto('/')
    await expect(page).toHaveURL(/\/login\?next=%2F$/)
    await expect(page.getByText('Measures what an AI builder can be trusted to change in your repository, graded by your own tests.', { exact: true })).toBeVisible()
    await about(page, 'This is where you sign in.')
    await field(page, 'Username').fill(env.user)
    await field(page, 'Password').fill(env.pass)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()

    // (2) the index has nothing to read: it replaces itself with Home, so Back cannot return to it
    await expect(page).toHaveURL(/\/home$/)
    await expect(page.getByTestId('user-chip')).toContainText(/admin/i)

    // (3) Home: where the deployment has got to, the eight tasks, and the next one named
    await expect(page.getByRole('heading', { level: 1, name: 'Get started' })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Tasks' }).getByRole('listitem')).toHaveCount(8)
    await expect(page.getByText(/You have completed \d of 8 tasks\./)).toBeVisible()
    await expect(page.getByRole('link', { name: /^Continue to (task \d: |the factory)/ })).toBeVisible()
    await about(page, 'This is where the deployment is on the way from an empty install')

    // (4) a term the About block names opens its own entry in the glossary
    const term = page.getByTestId('about-this-screen').locator('dl').first().getByRole('link').first()
    const termHref = (await term.getAttribute('href')) ?? ''
    expect(termHref).toMatch(/^\/help#[a-z_]+$/)
    const termId = termHref.split('#')[1]!
    await term.click()
    await expect(page).toHaveURL(new RegExp(`/help#${termId}$`))
    const entry = page.locator(`[id="${termId}"]`)
    await expect(entry).toBeInViewport()
    await about(page, 'Every term the screens use, in plain English')

    // (5) its Read more opens the guide AT the heading it names, not at the top
    const readMore = entry.getByRole('link', { name: 'Read more' })
    const guideHref = (await readMore.getAttribute('href')) ?? ''
    expect(guideHref).toMatch(/^\/help\/docs\/[A-Z-]+(#.+)?$/)
    await readMore.click()
    await expect(page).toHaveURL(new RegExp(`${guideHref.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`))
    await expect(page.getByRole('article')).toBeVisible()
    const slug = guideHref.split('#')[1]
    if (slug) {
      const heading = page.locator(`article [id="${slug}"]`)
      await expect(heading).toHaveCount(1)
      await expect(heading).toBeInViewport()
    }
    await expect(page.getByText('Read-only: it is changed in the repository, not here.')).toBeVisible()
    await about(page, 'copied into this deployment when it was built')

    // (6) an address that does not exist says so, inside the shell, and leads back to Home
    await page.goto('/nowhere/at/all')
    await expect(page.getByRole('heading', { level: 1, name: 'This page does not exist' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
    await about(page, 'Nothing lives at the address you asked for.')
    await page.getByRole('button', { name: 'Back to Home' }).or(page.getByRole('link', { name: 'Back to Home' })).first().click()
    await expect(page).toHaveURL(/\/home$/)

    // and out: sign-out ends the session; a protected screen bounces again
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/home')
    await expect(page).toHaveURL(/\/login\?next=%2Fhome$/)

    // the recorded pass the onboarding guide quotes (G-414): a scripted pass, not a person reading
    const seconds = ((Date.now() - started) / 1000).toFixed(1)
    test.info().annotations.push({ type: 'orient-pass-seconds', description: seconds })
    console.log(`[13-orient] one scripted pass of the six steps: ${seconds} s, £0 (no model call)`)
  })

  test('all eight bundled guides and a decision record open on the served bundle, each with its own text', async ({ page }) => {
    await page.goto('/login')
    await field(page, 'Username').fill(env.user)
    await field(page, 'Password').fill(env.pass)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByTestId('user-chip')).toBeVisible()

    for (const name of GUIDES) {
      await page.goto(`/help/docs/${name}`)
      const article = page.getByRole('article')
      await expect(article, `${name}: the guide did not render`).toBeVisible()
      await expect(article.getByRole('heading', { level: 1 }).first(), name).toHaveText(firstHeading(name))
      await expect(page.getByText('No guide with that name'), name).toHaveCount(0)
      await expect(page.getByTestId('error-state'), name).toHaveCount(0)
    }

    // a decision record, followed from the Help page's list (G-156)
    await page.goto('/help')
    const decisions = page.getByRole('region', { name: 'Decisions (ADRs)' })
    await decisions.getByRole('link', { name: /^ADR-0015 — / }).click()
    await expect(page).toHaveURL(/\/help\/docs\/ADR-0015$/)
    await expect(page.getByRole('heading', { level: 1, name: /^ADR-0015 — A sign-off expires with the apparatus/ })).toBeVisible()
    await expect(page.getByRole('article').getByRole('heading', { level: 1 }).first()).toContainText('ADR-0015')
  })

  test('Home’s task tags agree with the live stack, and reading the baseline completes task 6', async ({ page }) => {
    const repo = primary().name
    await page.goto('/login')
    await field(page, 'Username').fill(env.user)
    await field(page, 'Password').fill(env.pass)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByTestId('user-chip')).toBeVisible()

    // 02 onboarded and probed the repository; 05 replayed it, so its map has rows
    await page.goto(`/home?repo=${encodeURIComponent(repo)}`)
    await expect(page.getByText(new RegExp(`^${repo} · measured$`))).toBeVisible()
    await expect(task(page, 2)).toContainText('Choose a repository')
    await expect(task(page, 2)).toContainText('Completed')
    await expect(task(page, 3)).toContainText('Completed')
    await expect(task(page, 5)).toContainText('Measure — spends money')
    await expect(task(page, 5)).toContainText('Completed')
    // rows exist, so the baseline can be read: never "Cannot start yet", never a failed read
    await expect(task(page, 6)).not.toContainText('Cannot start yet')
    await expect(task(page, 6)).not.toContainText('Unavailable')
    await expect(page.getByTestId('error-state')).toHaveCount(0)

    // open the baseline: the Baseline screen tells the server it was read (DL-078) ...
    const recorded = page.waitForResponse((r) => r.url().endsWith(`/api/v1/repos/${encodeURIComponent(repo)}/baseline-read`) && r.request().method() === 'POST')
    await page.goto(`/results?repo=${encodeURIComponent(repo)}`)
    expect([200, 201]).toContain((await recorded).status())

    // ... and Home's task 6 reads Completed on that record
    await page.goto(`/home?repo=${encodeURIComponent(repo)}`)
    await expect(task(page, 6)).toContainText('Read the baseline')
    await expect(task(page, 6)).toContainText('Completed')
  })
})
