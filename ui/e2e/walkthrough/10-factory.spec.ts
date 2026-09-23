/**
 * 10 — the factory journey, end to end, on the tier-1 stack: freeze a backlog through the
 * dialog, read what the run will spend and where it would deliver, press Run the factory
 * with the test-only `fixture_gold` builder, watch the chain move, read every refusal's
 * reason on the item row and open the built item's evidence.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 10 (the factory: /factory → /runs/:id → the drawer), tier 1
 *               only — the fixture builder spends nothing and calls no model.
 * What it does: Freezes a two-item backlog (I-1 with its structural fact and an operator-
 *               authored test that fails today; I-2 with an unsigned structural gap); asserts
 *               the readiness and cell-route pills BEFORE the run and the "Before you run"
 *               facts (builder, items, estimate with its provenance, delivery not linked —
 *               J-FAC-1/2/3); names `fixture_gold` as the builder (every knob — the deployment's
 *               default would be a real model) and presses Run the factory (J-FAC-1 — the 422
 *               a run without a builder met); waits on the run page's status pill; asserts the
 *               item chain: I-1 assessed, RED proved, built under the belts but NOT clean (the
 *               fixture overlays the commit's own sources and a factory item has none — an
 *               honest not-clean, never a fabricated pass), its Evidence button opening the
 *               drawer with the pack (F15), its run link; I-2 refused at readiness with the
 *               gap named and the way forward (J-FAC-4 / J-FAC-15); that the Runs list names
 *               the factory kind; and that /factory does not scroll sideways at 375 px
 *               (J-FAC-14).
 * How:          `signIn` (the fixture), the freeze dialog's JSON mode (the only way to attach
 *               an authored test in the UI), `waitForRun` on the status pill, then the item
 *               rows' test ids (`factory-item-<id>`, `step-<id>-<step>`, `cell-route-<id>`,
 *               `refusal-<id>`, `evidence-<id>`).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md (the route gate)
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Factory/FactoryPage.tsx (under
 *               test), src/crb/server/routes/factory.py and src/crb/server/factory_state.py
 *               (the fold it reads), src/crb/factory/loop.py (the refusals it asserts),
 *               src/crb/builders/fixture_gold.py (the builder), ui/e2e/walkthrough/README.md
 * Tested by:    scripts/walkthrough.sh (runs it, tier 1)
 * Touch when:   a step is added to the loop; the freeze dialog's labels change; the fixture
 *               builder learns to build a factory item (then I-1 grades clean and the
 *               delivery step, not the build step, is the one to assert).
 */
import { env, expect, primary, runIdFromUrl, signIn, test, waitForRun } from './support'

test.describe.configure({ mode: 'serial' })

const RUN_TIMEOUT_MS = 6 * 60_000

/** The backlog as the dialog's JSON mode takes it: one item ready with an authored test, one with a structural gap. */
const BACKLOG = {
  items: [
    {
      id: 'I-1',
      title: 'Add multiply to calc',
      kind: 'code',
      description: 'calc needs a multiply(a, b) function.',
      capability_class: 'bug.fix',
      size_estimate: 'XS',
      // every catalogued slot filled (the value slot too), so readiness routes `build`
      structural_facts: ['reproduction: `from calc import multiply` raises ImportError', 'expected_behaviour: calc exposes multiply(a: int, b: int) -> int', 'exact_value: multiply(3, 4) == 12'],
    },
    {
      id: 'I-2',
      title: 'Add a /health route',
      kind: 'code',
      description: 'The service needs a health route.',
      capability_class: 'backend.route.add',
      size_estimate: 'S',
      // every structural slot but `method_path`: the one unsigned gap the run stops on
      structural_facts: ['request_shape: no body', 'response_shape: {"status": "ok"}', 'error_contract: none — the route cannot fail'],
    },
  ],
  authored: {
    'I-1': { path: 'tests/test_multiply.py', content: 'from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n' },
  },
}

test.describe('10 factory (fixture_gold)', () => {
  test.skip(env.publicTier, 'tier 1 only: the fixture builder drives the loop without a model')
  const t = primary()
  let runId = ''

  test('freeze a two-item backlog through the dialog; the pills and the before-you-run facts read from the stack', async ({ page }) => {
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('factory-no-backlog')).toBeVisible()
    await page.getByRole('button', { name: 'Freeze a backlog…' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Freeze a backlog' })
    await expect(dialog).toBeVisible()
    // the form asks the class's questions; the authored test needs the JSON view
    await expect(dialog.getByTestId('backlog-form')).toBeVisible()
    await dialog.getByRole('button', { name: 'Advanced: paste JSON instead' }).click()
    await dialog.getByLabel('Backlog JSON').fill(JSON.stringify(BACKLOG, null, 2))
    await dialog.getByRole('button', { name: /^Freeze/ }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText('frozen', { exact: true })).toBeVisible()
    await expect(page.getByText('2 items', { exact: true })).toBeVisible()

    // the items before any run: not assessed, and each cell's route from the signed map
    for (const id of ['I-1', 'I-2']) {
      await expect(page.getByTestId(`step-${id}-readiness`)).toContainText('not assessed')
      // the pill's text after its glyph (✓ / ⊘ / ○) is the short route phrase; the n · point [interval] · apparatus sit in the span after it
      await expect(page.getByTestId(`cell-route-${id}`)).toHaveText(/^[^a-z]*(routes (deliver|calibrate|human|granularize)( · withheld)?|not measured · withheld)$/)
      // a measured cell carries its n · point [interval] · apparatus beside the pill (J-FAC-14); an unmeasured one has no span
      const prov = page.getByTestId(`cell-route-${id}-prov`)
      if ((await prov.count()) > 0) await expect(prov).toHaveText(/^n = \d+ · \d+ % \[\d+ %, \d+ %\] · apparatus /)
      else await expect(page.getByTestId(`cell-route-${id}`)).toContainText('not measured')
    }
    // tier 1 cannot sign the fixture, so nothing is deliverable: no cell routes deliver, and
    // under ADR-0018 a signed cell is needed as well (README: the escape)
    await expect(page.getByTestId('factory-deliverable-count')).toContainText('0 of 2 items sit in a cell this deployment would deliver from today')

    // J-FAC-2/3 — what the run will spend and where it would deliver, before the button
    const box = page.getByTestId('before-you-start')
    await expect(box).toContainText('2 of 2 will be worked')
    await expect(box).toContainText(/a planning range, not a measured interval|measured mean over n = \d+ attempts at apparatus/)
    await expect(box).toContainText('not linked — no pull request')
    await expect(box).toContainText('it is connected by URL, not through the GitHub App')
    await expect(box.getByRole('checkbox', { name: /Open pull requests/ })).toBeDisabled()
    await expect(box).toContainText('no spend cap yet')
    await expect(box).toContainText('You can cancel the run at any point. Items already built are still charged.')
  })

  test('Run the factory with the fixture builder → the run succeeds and the chain moves', async ({ page }) => {
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}`)
    const box = page.getByTestId('before-you-start')
    await expect(box).toBeVisible()
    // the deployment's default builder would be a real model: name the fixture instead
    await box.getByText('Use a different builder').click()
    await box.getByLabel('Builder', { exact: true }).fill('fixture_gold')
    await box.getByLabel('Model', { exact: true }).fill('gold')
    await expect(box).toContainText('fixture_gold · gold — named by you')
    await box.getByRole('button', { name: /^Run the factory/ }).click()
    // J-FAC-5 — the banner names the run; the controls step aside
    const banner = page.getByTestId('factory-active-run')
    await expect(banner).toBeVisible({ timeout: 30_000 })
    await expect(banner).toContainText('is working the backlog')
    await expect(box).toBeHidden()
    await banner.getByRole('link', { name: 'Open the run' }).click()
    await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
    runId = runIdFromUrl(page)
    await waitForRun(page, 'succeeded', RUN_TIMEOUT_MS)
  })

  test('the item chain: one built (not clean, with its evidence), one refused at readiness with the gap and the way forward', async ({ page }) => {
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}&item=I-2`)
    await expect(page.getByTestId('factory-last-run')).toContainText(/Factory run [0-9a-f]+ succeeded/)

    // I-1: assessed → RED proved → built under the belts, not clean (the fixture has no
    // source to overlay for a factory item) → the outcome says so; no delivery attempted
    const i1 = page.getByTestId('factory-item-I-1')
    await expect(i1.getByTestId('step-I-1-readiness')).toContainText('route build')
    await expect(i1.getByTestId('step-I-1-red')).toContainText('the authored test fails before the change')
    await expect(i1.getByTestId('step-I-1-build')).toContainText('not clean')
    await expect(i1.getByTestId('step-I-1-delivery')).toContainText('not yet')
    await expect(i1.getByTestId('item-status-I-1')).toHaveText('Build not clean')
    // F15 — the run link and the Evidence button, from the build event's ids
    await expect(i1.getByRole('link', { name: `run ${runId.slice(0, 10)}` })).toHaveAttribute('href', `/runs/${runId}`)
    await i1.getByTestId('evidence-I-1').click()
    const drawer = page.getByTestId('evidence-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByTestId('pack-verified')).toBeVisible()
    await expect(drawer).toContainText('fixture_gold')
    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()

    // I-2: refused at readiness — the gap is named, the sentence says the way forward
    const i2 = page.getByTestId('factory-item-I-2')
    await expect(i2.getByTestId('step-I-2-readiness')).toContainText('1 structural gap unsigned: method_path')
    await expect(i2.getByTestId('item-status-I-2')).toHaveText('Waiting on a signature')
    await expect(i2.getByTestId('refusal-I-2')).toContainText('This item goes to a person:')
    await expect(i2.getByTestId('refusal-I-2')).toContainText('register an evolution that supersedes this item (the frozen hash stays; the old chain is kept)')
    await expect(i2.getByTestId('step-I-2-red')).toContainText('not run')
    await expect(i2.getByTestId('evidence-I-2')).toHaveCount(0)
    // J-FAC-16 — the approver's gap form asks the catalogue's question
    const form = i2.getByRole('form', { name: 'Sign a structural gap for I-2' })
    await expect(form.getByRole('combobox')).toContainText(/\(method_path\)/)
  })

  test('the Runs list names the factory kind', async ({ page }) => {
    await page.goto('/runs')
    const table = page.getByRole('table', { name: 'Runs' })
    const row = table.getByRole('row').filter({ has: page.getByRole('link', { name: runId.slice(0, 8) }) })
    await expect(row.first()).toContainText('factory')
  })

  test('at 375 px the factory does not scroll sideways (J-FAC-14)', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 375, height: 812 } })
    const page = await context.newPage()
    try {
      await signIn(page)
      await page.goto(`/factory?repo=${encodeURIComponent(t.name)}`)
      await expect(page.getByTestId('factory-item-I-2')).toBeVisible()
      // on failure, name the elements whose right edge passes the viewport — the culprit, not a number
      const widths = await page.evaluate(() => {
        const inner = window.innerWidth
        const wide = Array.from(document.querySelectorAll('body *'))
          .map((el) => ({ el, right: el.getBoundingClientRect().right }))
          .filter(({ right }) => right > inner + 1)
          .sort((a, b) => b.right - a.right)
          .slice(0, 6)
          .map(({ el, right }) => `${el.tagName.toLowerCase()}${el.getAttribute('data-testid') ? `[${el.getAttribute('data-testid')}]` : ''}.${String(el.className).split(' ').slice(0, 3).join('.')} right=${Math.round(right)}`)
        return { scroll: document.documentElement.scrollWidth, inner, wide }
      })
      expect(widths.scroll, `document.scrollWidth ${widths.scroll} > innerWidth ${widths.inner}; past the edge: ${widths.wide.join(' | ') || '(none — a scrollable ancestor?)'}`).toBeLessThanOrEqual(widths.inner)
    } finally {
      await context.close()
    }
  })
})
