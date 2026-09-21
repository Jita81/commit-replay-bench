/**
 * 04 — how much a green is worth. Proves: an oracle run scores mutation strength per
 * task and the Oracle page shows each task's strength, band and the gate it licenses;
 * a controls run drives the seven negative controls through the real grader and the
 * page renders every control with its verdict — gold ok, noop stays red, a tampered
 * test is disqualified (caught), and NO verdict is a VIOLATION (an instrument bug).
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 04 (oracle adequacy and negative controls) on the primary
 *               repo.
 * What it does: Pins that an oracle run scores every mined task (`oracle.mutation.scored`)
 *               and the Oracle page shows each task's strength, band and gate; and that a
 *               controls run drives the seven negative controls through the real grader and
 *               the page renders every control with its verdict — gold ok, noop red, a
 *               tampered test disqualified (caught) — with NO verdict a VIOLATION (which
 *               would be an instrument bug).
 * How:          `startRun` for `oracle` then `controls`; `waitForRun`; assertions per control
 *               name on the Oracle page's tables.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0009-text-level-mutators.md, docs/adr/0010-polyglot-negative-controls.md
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Oracle/OraclePage.tsx (the
 *               screen under test), src/crb/core/oracle/mutation.py and
 *               src/crb/core/oracle/controls.py (the runs whose results are asserted)
 * Tested by:    ui/e2e/walkthrough/04-oracle-and-controls.spec.ts
 * Touch when:   a control is added to the matrix (`CONTROLS` here must match
 *               src/crb/core/oracle/controls.py) or the Oracle page's columns change.
 */
import { env, expect, expectLogAction, primary, startRun, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const CONTROLS = ['gold', 'noop', 'test_tamper', 'stub', 'regression', 'hardcode_cheat', 'env_poison'] as const
const RUN_TIMEOUT_MS = 6 * 60_000

test.describe('04 oracle + controls', () => {
  const t = primary()

  test('an oracle run scores every mined task; the Oracle page shows strength, band and gate', async ({ page }) => {
    await startRun(page, t.name, { kind: 'oracle', limit: 1 })
    await waitForRun(page, 'succeeded', RUN_TIMEOUT_MS)
    await expectLogAction(page, 'oracle.mutation.scored')
    await expectLogAction(page, 'oracle.score')

    await page.goto(`/oracle?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByRole('heading', { level: 1, name: 'Oracle' })).toBeVisible()
    // tiles carry n and the policy version
    await expect(page.getByText('Mean strength')).toBeVisible()
    await expect(page.getByText(/adequacy\.v\d+/).first()).toBeVisible()

    const perTask = page.getByRole('table', { name: 'Oracle strength per task' })
    const rows = perTask.locator('tbody tr')
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)
    const first = rows.first()
    // strength is a ratio (or "—" for an unscoreable oracle), killed / mutants are integers
    await expect(first).toContainText(/\d+ \/ \d+/)
    await expect(first.getByRole('img', { name: /^Oracle strength: (strong|adequate|weak|unscoreable)/ })).toBeVisible()
    await expect(first.getByRole('img', { name: /^Gate: (clears the oracle bar|review-gated|needs a human)/i })).toBeVisible()

    const perCell = page.getByRole('table', { name: 'Oracle strength per cell' })
    await expect(perCell.locator('tbody tr').first()).toBeVisible()
    await expect(perCell.locator('tbody tr').first().getByText(/^(XS|S|M|L|XL)$/)).toBeVisible()
  })

  test('a controls run renders the seven negative controls with their verdicts', async ({ page }) => {
    await startRun(page, t.name, { kind: 'controls', limit: 1 })
    await waitForRun(page, 'succeeded', RUN_TIMEOUT_MS)
    await expectLogAction(page, 'controls.report')

    await page.goto(`/oracle?repo=${encodeURIComponent(t.name)}`)
    const banner = page.getByTestId('gate-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toContainText('Negative controls')
    await expect(banner).toContainText('0 violation(s)')
    // The gate's state is the API's routing verdict (the reduction the capability map and
    // the routes gate on), rendered — never derived in the UI from the counts: OPEN only
    // when the verdict is `passed`. On the one-task fixture the verdict is `thin` (fewer
    // than half the controls constructible) or `escaped` — the fixture's `hardcode_cheat`
    // grades clean by construction (one assertion cannot tell a hard-coded return from an
    // implementation; tests/test_oracle_controls.py pins it as the measured escape): a
    // finding, not a violation. Both keep the gate CLOSED, exactly as routing withholds
    // deliver under them. Before batch 4 the banner derived OPEN from "no violations"
    // alone and hid that.
    const res = await page.request.get(`${env.baseUrl}/api/v1/oracle/${encodeURIComponent(t.name)}/controls`)
    expect(res.ok(), `GET /oracle/{repo}/controls → ${res.status()}`).toBeTruthy()
    const verdict = ((await res.json()) as { verdict: { state: string; violations?: number } }).verdict
    expect(verdict.state, 'the fixture has no violations; the verdict is passed, thin or escaped').toMatch(/^(passed|thin|escaped)$/)
    await expect(banner).toHaveAttribute('data-state', verdict.state === 'passed' ? 'OPEN' : 'CLOSED')
    await expect(banner).toContainText(`Routing verdict (from the API)`)
    await expect(banner).toContainText(verdict.state)

    const table = page.getByRole('table', { name: 'Negative-control rows' })
    const rows = table.locator('tbody tr')
    await expect(rows).toHaveCount(CONTROLS.length)
    for (const c of CONTROLS) {
      await expect(table.getByText(c, { exact: true }).first(), `control ${c} listed`).toBeVisible()
    }
    // gold reproduces the commit and grades clean; the tampered test is caught (disqualified)
    const rowFor = (control: string) => rows.filter({ has: page.getByRole('cell', { name: control, exact: true }) })
    const gold = rowFor('gold')
    await expect(gold).toContainText('clean')
    await expect(gold.getByRole('img', { name: /^Verdict: ok/ })).toBeVisible()
    const tamper = rowFor('test_tamper')
    await expect(tamper).toContainText('disqualified')
    await expect(tamper.getByRole('img', { name: /^Verdict: ok/ })).toBeVisible()
    const noop = rowFor('noop')
    await expect(noop).toContainText('red')
    await expect(noop.getByRole('img', { name: /^Verdict: ok/ })).toBeVisible()
    // never a VIOLATION anywhere
    await expect(table.getByRole('img', { name: /^Verdict: VIOLATION/ })).toHaveCount(0)
  })
})
