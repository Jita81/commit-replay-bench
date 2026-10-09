/**
 * 06c — the map read through its own doors as one persona (G-446, G-238, G-256):
 * the walk's *Baseline* → *All decisions* → *Open the full map* → *Every route with its
 * reason*, one number per page equal to its API, the repository carried on every door.
 *
 * Runs AFTER 06b on purpose: opening the Baseline records the read 06b exists to see happen
 * (Incomplete → Completed), and tests/test_walkthrough_order.py refuses a Baseline visit in
 * any spec that sorts before 06b. This check first lived in 05, where it broke that order
 * (docs/PREVENTION.md P-180's class) and located the door by its accessible name — which two
 * links share on the walk (the shell's nav and the walk's own button), a strict-mode
 * violation. The door is now the walk's own button by its hint id, never the nav.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 06c (the map's doors) on the primary repository, after 06b.
 * What it does: Reads the API once (`/capability-map`, `/oracle/{repo}/controls`,
 *               `/oracle/{repo}`, `/routes`) and picks the primary repository's measured cell
 *               with the largest n — 05's replay rows; then walks: the walk's *Baseline* button
 *               (`button.walk.baseline`) → the gate tiles equal their APIs, False-Q1 reads 0
 *               and the calibrate route tile's cells and n are the map's, the decisions
 *               panel's count carried → *All decisions* (the repository's own section has that
 *               count, or no section when nothing waits on a person) → *Open the full map*
 *               (the cell's n) → *Every route with its reason* (route `calibrate`, the reason
 *               code and the policy version equal `GET /routes`).
 * How:          `apiGet` for the numbers the screens must equal; the doors by their hint ids
 *               and names, scoped to the page's main content where a name is shared.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/e2e/walkthrough/support.ts (`apiGet`, `primary`), ui/src/screens/Connect/
 *               ConnectPage.tsx (the walk's Baseline button), ui/src/screens/Results/
 *               ResultsPage.tsx (the gate tiles, the route tiles, the doors), ui/src/screens/
 *               Decisions/DecisionsPage.tsx and ui/src/screens/Decisions/decisions.ts
 *               (`decisionsFor`, the one rule both pages read), ui/src/screens/Capability/
 *               CapabilityPage.tsx (the cell), ui/src/screens/Routing/RoutingPage.tsx (the
 *               decision row), ui/e2e/walkthrough/06b-baseline-read.spec.ts (the read this
 *               spec must follow), tests/test_walkthrough_order.py (the gate on that order)
 * Tested by:    ui/e2e/walkthrough/06c-map-doors.spec.ts
 * Touch when:   never for a new repository; a door's label or hint id changes, a tile's test
 *               id changes, or the policy version stops being shown on the Routing card.
 */
import type { Locator, Page } from '@playwright/test'
import { apiGet, expect, primary, test } from './support'

test.describe.configure({ mode: 'serial' })

/** A StatTile's headline value (label / value / dl). */
const tileValue = (tile: Locator) => tile.locator(':scope > div').nth(1)
/** A StatTile's `n =` reading (the first `dd` of its dl). */
const tileN = (tile: Locator) => tile.locator('dd').first()
/** A StatTile by its label text, for tiles that carry no test id. */
const tileLabelled = (page: Page, label: string) => page.locator('[data-component="stat-tile"]').filter({ has: page.locator('.label', { hasText: label }) })
/** A route tile on /results: fac's `tile-route-<route>` test id once it lands, else the StatTile whose label is the route. */
const routeTile = (page: Page, route: string) => page.getByTestId(`tile-route-${route}`).or(tileLabelled(page, route))

interface MapCell {
  capability_class: string
  size: string
  n: number
  route: string
}

test.describe('06c the map through its doors', () => {
  const t = primary()

  test('the map read through its doors: Baseline → All decisions → Open the full map → Every route with its reason', async ({ page }) => {
    const q = `repo=${encodeURIComponent(t.name)}`
    // what the API says, read once, so every number on every page is compared with its source
    const map = await apiGet(page.request, `/capability-map?${q}`)
    const controls = (await apiGet(page.request, `/oracle/${encodeURIComponent(t.name)}/controls`)) as { verdict: { state: string; escapes: number } }
    const oracle = (await apiGet(page.request, `/oracle/${encodeURIComponent(t.name)}`)) as { tasks: Array<{ strength: number | null }> }
    const routes = (await apiGet(page.request, `/routes?${q}`)) as { policy: { version: string }; decisions: Array<{ cell: Record<string, string>; route: string; reason_code?: string; policy_version: string; n: number }> }
    const summary = map.summary as { false_q1_total: number; n_total: number }
    const cells = map.cells as MapCell[]
    // the cell 05 measured: the repository's measured cell with the most rows (one attempt per
    // gold-clean task — never a literal, and never carried from another spec's memory)
    const measured = cells.filter((c) => c.n >= 1)
    expect(measured.length, 'a measured cell on the map after 05').toBeGreaterThanOrEqual(1)
    const mapCell = measured.reduce((a, c) => (c.n > a.n ? c : a))
    const { capability_class: cellClass, size: cellSize } = mapCell
    const calibrate = cells.filter((c) => c.route === 'calibrate')
    expect(calibrate.length, 'the walkthrough grades on the host: every measured cell routes calibrate').toBeGreaterThanOrEqual(1)
    const calibrateN = calibrate.reduce((a, c) => a + c.n, 0)

    // door 0: the Baseline, from the walk's OWN button — the repository carried. By its hint
    // id: the shell's nav link is named Baseline too, so a name would match both.
    await page.goto(`/connect/${encodeURIComponent(t.name)}`)
    await page.locator('a[data-hint="button.walk.baseline"]').click()
    await page.waitForURL(new RegExp(`/results\\?${q}$`))
    // the gate tiles equal their APIs
    await expect(tileValue(page.getByTestId('tile-negative-controls'))).toHaveText(controls.verdict.state)
    await expect(page.getByTestId('tile-negative-controls')).toContainText(`${controls.verdict.escapes} escapes`)
    await expect(tileN(page.getByTestId('tile-oracle-strength'))).toHaveText(String(oracle.tasks.length))
    expect(summary.false_q1_total, 'false-Q1 is refused at write').toBe(0)
    await expect(tileValue(tileLabelled(page, 'False-Q1'))).toHaveText('0')
    // the calibrate route tile: its cells and its n are the map's
    const tile = routeTile(page, 'calibrate')
    await expect(tileValue(tile)).toHaveText(String(calibrate.length))
    await expect(tileN(tile)).toHaveText(String(calibrateN))
    // the decisions panel's count for this repository is carried to the next door
    const eyebrow = page.getByText(/^\d+ for this repository$/)
    await expect(eyebrow).toBeVisible()
    const waitingN = Number(/^(\d+) /.exec((await eyebrow.textContent()) ?? '')![1])

    // door 1: All decisions — the repository's own section, with the same count (or no section
    // when nothing waits on a person: a calibrate cell asks nobody to decide)
    await page.getByRole('link', { name: 'All decisions', exact: true }).click()
    await page.waitForURL(/\/decisions$/)
    await expect(page.getByTestId('decisions-count')).toHaveAttribute('data-ready', 'true')
    const section = page.getByRole('list', { name: `Decisions for ${t.name}` })
    if (waitingN > 0) {
      await expect(section).toBeVisible()
      await expect(section.locator(':scope > li')).toHaveCount(waitingN)
    } else {
      await expect(section).toHaveCount(0)
    }

    // door 2: Open the full map carries the repository; the cell's n is the map's
    await page.goto(`/results?${q}`)
    await page.getByRole('link', { name: 'Open the full map', exact: true }).click()
    await page.waitForURL(new RegExp(`/capability\\?${q}`))
    const cell = page.locator(`[data-testid="cell-measured"][aria-label^="${cellClass} ${cellSize}:"]`)
    await expect(cell).toContainText(`n=${mapCell.n}`)

    // door 3: Every route with its reason carries the repository; the decision equals GET /routes
    await page.goto(`/results?${q}`)
    await page.getByRole('link', { name: 'Every route with its reason', exact: true }).click()
    await page.waitForURL(new RegExp(`/routing\\?${q}`))
    const decision = routes.decisions.find((d) => d.cell.capability_class === cellClass && d.cell.size === cellSize)
    expect(decision, `a route decision for ${cellClass} × ${cellSize}`).toBeTruthy()
    expect(decision!.route).toBe('calibrate')
    // the policy in force: its version on the card's eyebrow, its rule word for word
    await expect(page.getByTestId('policy-rule')).toBeVisible()
    await expect(page.getByText(routes.policy.version).first()).toBeVisible()
    const table = page.getByRole('table', { name: `Route decisions for ${t.name}` })
    const row = table.locator('tbody tr').filter({ hasText: cellClass }).filter({ hasText: new RegExp(`\\b${cellSize}\\b`) })
    await expect(row).toHaveCount(1)
    await expect(row.getByRole('img', { name: /^Route: calibrate/ })).toBeVisible()
    if (decision!.reason_code) await expect(row).toContainText(decision!.reason_code)
    await expect(row).toContainText(decision!.policy_version)
  })
})
