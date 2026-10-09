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
 *               J-FAC-1/2/3 — and no spend cap on the whole run until one is typed, F5b) and —
 *               ADR-0026 item 8 — that neither item can be built, the tier-1
 *               stack having no proven context standard; an approver funds one calibration
 *               build of I-1 from its row; names `fixture_gold` as the builder (every knob —
 *               the deployment's default would be a real model) and presses Run the factory
 *               (J-FAC-1 — the 422 a run without a builder met); waits on the run page's status
 *               pill; asserts the item chain: I-1 assessed, RED proved, built as the calibration
 *               build under the belts but NOT clean (the fixture overlays the commit's own
 *               sources and a factory item has none — an honest not-clean, never a fabricated
 *               pass), its Evidence button opening the drawer with the pack (F15), its run
 *               link; I-2 not built — no proven standard — with its gap named and the way
 *               forward (J-FAC-4 / J-FAC-15); that the Runs list names the factory kind; that
 *               the approver (a second persona, signed in as themselves) signs I-2's
 *               structural gap and the evidence chain records it under their id, with no
 *               lift of the sign-off clause offered while delivery is not linked (G-143); and that
 *               /factory does not scroll sideways at 375 px (J-FAC-14).
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
 * Touch when:   never for a new repository; a step is added to the loop; the freeze dialog's labels
 *               change; stream R's readings land on the tier-1 stack (then a cell may have a
 *               proven standard); the fixture builder learns to build a factory item (then I-1
 *               grades clean and the delivery step, not the build step, is the one to assert).
 */
import type { Page } from '@playwright/test'
import { env, expect, personaPassword, primary, runIdFromUrl, signIn, test, waitForRun } from './support'

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

/** The second person: the persona 08 and 11 use, so a rerun reuses it (created through `POST /users`). */
const APPROVER = 'walk-approver'
const APPROVER_PASS = personaPassword(APPROVER)

/** Create the approver persona unless an earlier spec did; the page must be signed in as the admin. */
async function ensureApprover(page: Page): Promise<void> {
  const users = await page.request.get(`${env.baseUrl}/api/v1/users?limit=500`)
  expect(users.status(), 'GET /users as the admin').toBe(200)
  if (((await users.json()) as { items: Array<{ username: string }> }).items.some((u) => u.username === APPROVER)) return
  const cookie = (await page.context().cookies()).find((c) => c.name === 'crb_csrf')
  if (!cookie) throw new Error('no crb_csrf cookie — is the page signed in?')
  const res = await page.request.post(`${env.baseUrl}/api/v1/users`, {
    data: { username: APPROVER, password: APPROVER_PASS, role: 'approver', display_name: 'Walk approver' },
    headers: { 'X-CSRF-Token': cookie.value },
  })
  expect(res.status(), `POST /users → ${res.status()} ${await res.text()}`).toBeLessThan(300)
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

    // the items before any run: not built — the entry gate the next run's pre-build check
    // applies (ADR-0026 item 8) — and each cell's route from the signed map
    for (const id of ['I-1', 'I-2']) {
      await expect(page.getByTestId(`step-${id}-readiness`)).toContainText('Not built — no context standard is proven')
      // the pill's text after its glyph (✓ / ⊘ / ○) is the short route phrase; the n · point [interval] · apparatus sit in the span after it
      await expect(page.getByTestId(`cell-route-${id}`)).toHaveText(/^[^a-z]*(routes (deliver|calibrate|human|granularize)( · no pull request)?|not measured · not built)$/)
      // a measured cell carries its n · point [interval] · apparatus beside the pill (J-FAC-14); an unmeasured one has no span
      const prov = page.getByTestId(`cell-route-${id}-prov`)
      if ((await prov.count()) > 0) await expect(prov).toHaveText(/^n = \d+ · \d+ % \[\d+ %, \d+ %\] · apparatus /)
      else await expect(page.getByTestId(`cell-route-${id}`)).toContainText('not measured')
    }
    // tier 1 cannot sign the fixture, so nothing is deliverable: no cell routes deliver, and
    // under ADR-0018 a signed cell is needed as well (README: the escape)
    await expect(page.getByTestId('factory-deliverable-count')).toContainText('0 of 2 items sit in a cell this deployment would deliver from today')

    // ADR-0026 item 8 — before any run the page says what the next run's entry gate will:
    // no cell here has a proven context standard, so neither item can be built
    await expect(page.getByTestId('entry-I-1')).toContainText('Not built · no_proven_standard')
    await expect(page.getByTestId('entry-I-2')).toContainText('Not built · no_proven_standard')

    // J-FAC-2/3 — what the run will spend and where it would deliver, before the button
    const box = page.getByTestId('before-you-start')
    await expect(box).toContainText('0 of 2 can be built')
    await expect(box.getByTestId('factory-not-built-limit')).toContainText('is not built. An approver’s calibration build is recorded as one and never delivers.')
    // nothing can be built yet, so nothing is estimated (the range appears once an item can be)
    await expect(box).toContainText('nothing — no item can be built')
    await expect(box).toContainText('not linked — no pull request')
    await expect(box).toContainText('it is connected by URL, not through the GitHub App')
    await expect(box.getByRole('checkbox', { name: /Open pull requests/ })).toBeDisabled()
    // F5b — the run can be told to stop at an amount: blank means no cap on the whole run
    await expect(box).toContainText('none on the whole run — set one under Stop the run at')
    await expect(box.getByLabel('Stop the run at (USD)')).toHaveValue('')
    await expect(box).toContainText('You can cancel the run at any point. Items already built are still charged.')
  })

  test('an approver funds one calibration build of I-1 — recorded, and never a pull request (ADR-0026 item 8)', async ({ page }) => {
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}&item=I-1`)
    const i1 = page.getByTestId('factory-item-I-1')
    const form = i1.getByRole('form', { name: 'Fund a calibration build of I-1' })
    await form.getByLabel('Why fund a calibration build').fill('walk the loop once on the fixture')
    await form.getByRole('button', { name: 'Fund a calibration build' }).click()
    await expect(i1.getByTestId('calibration-I-1')).toContainText('the next factory run builds it, and it never opens a pull request')
    const box = page.getByTestId('before-you-start')
    await expect(box).toContainText('1 of 2 can be built')
    // J-FAC-2 — the funded item is estimated, with the provenance of the number
    await expect(box).toContainText(/a planning range, not a measured interval|measured mean over n = \d+ attempts with a known cost at apparatus/)
  })

  // ADR-0026 item 8 — a second person writes the held-out acceptance tests the calibration build's
  // first attempt is graded on: the approver persona, who neither wrote I-1 nor funded its build
  // (the admin did both, and runs it), from the ticket alone — never its failing test
  test('a second person writes I-1’s held-out acceptance tests from the ticket alone', async ({ page, browser }) => {
    await ensureApprover(page)
    // the admin wrote the ticket and funded the build: the page says why they may not
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}&item=I-1`)
    // before anyone writes them, the item says a run now would build it without them
    await expect(page.getByTestId('acceptance-state-I-1')).toContainText('Held-out tests are not written yet')
    await page.getByTestId('acceptance-link-I-1').click()
    await expect(page).toHaveURL(/\/factory\/acceptance\?repo=/)
    await expect(page.getByTestId('acceptance-why-I-1')).toContainText(/ticket.s author/)
    const context = await browser.newContext()
    const second = await context.newPage()
    try {
      await signIn(second, APPROVER, APPROVER_PASS)
      await second.goto(`/factory/acceptance?repo=${encodeURIComponent(t.name)}`)
      const card = second.getByTestId('acceptance-I-1')
      await expect(card).toContainText('calc needs a multiply(a, b) function.')
      await expect(second.getByTestId('acceptance-status-I-1')).toContainText('tests needed')
      // the ticket's own failing test is never on the page
      await expect(card).not.toContainText('assert multiply(3, 4) == 12')
      // no forward reading is registered on this cell in the walk: the page says none will count them
      await expect(card).toContainText('no reading will count the result')
      const form = card.getByRole('form', { name: 'Write the held-out tests for I-1' })
      await form.getByLabel('Test file').fill('tests/test_multiply_held_out.py')
      await form.getByLabel('Held-out acceptance tests').fill('from calc import multiply\n\n\ndef test_multiply_held_out():\n    assert multiply(7, 6) == 42\n')
      await form.getByRole('button', { name: 'Save the held-out tests' }).click()
      await expect(second.getByTestId('acceptance-saved-I-1')).toContainText('The builder never sees them')
      await expect(second.getByTestId('acceptance-status-I-1')).toContainText('tests written')
    } finally {
      await context.close()
    }
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

  test('the item chain: one calibration build (not clean, with its evidence), one not built — no proven standard — with its gap and the way forward', async ({ page }) => {
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}&item=I-2`)
    await expect(page.getByTestId('factory-last-run')).toContainText(/Factory run [0-9a-f]+ succeeded/)

    // I-1: assessed → RED proved → built under the belts, not clean (the fixture has no
    // source to overlay for a factory item) → the outcome says so; no delivery attempted
    const i1 = page.getByTestId('factory-item-I-1')
    // the grant is spent: the run built it as a calibration build
    await expect(i1.getByTestId('calibration-I-1')).toHaveCount(0)
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

    // ADR-0026 item 8 — the calibration build's first attempt was graded on the second person's
    // held-out tests and stamped S2 inside its row; it opened no pull request (step-I-1-delivery
    // above), and the page reads the result (the fixture builds no source, so it fails them)
    const chain = (await (await page.request.get(`${env.baseUrl}/api/v1/factory/${encodeURIComponent(t.name)}/evidence?item_id=I-1`)).json()) as {
      items: Array<{ kind: string; payload: { row_hash?: string; result?: string; oracle_commit?: string } }>
    }
    const graded = chain.items.filter((e) => e.kind === 'acceptance.graded')
    expect(graded).toHaveLength(1)
    const build = chain.items.find((e) => e.kind === 'build.graded' && e.payload.row_hash === graded[0]!.payload.row_hash)!
    const grades = (await (await page.request.get(`${env.baseUrl}/api/v1/grades?repo=${encodeURIComponent(t.name)}&task_id=${build.payload.oracle_commit}`)).json()) as {
      items: Array<{ row_hash: string; trial: string; labels: Record<string, string> }>
    }
    const row = grades.items.find((g) => g.row_hash === graded[0]!.payload.row_hash)!
    expect(row.trial).toBe('r1')
    expect(row.labels.context_arm).toBe('S2')
    expect(row.labels.acceptance).toBe('held_out')
    expect(row.labels.acceptance_result).toBe(graded[0]!.payload.result)
    expect(chain.items.some((e) => e.kind === 'delivery.opened')).toBe(false)
    await page.goto(`/factory/acceptance?repo=${encodeURIComponent(t.name)}`)
    await expect(page.getByTestId('acceptance-status-I-1')).toContainText('graded')
    await expect(page.getByTestId('acceptance-I-1')).toContainText('First attempt')
    await expect(page.getByTestId('acceptance-I-1')).toContainText('No forward reading counts it')
    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}&item=I-2`)

    // I-2: the entry gate stopped it before any spend — NOT BUILT, and the sentence says the
    // way forward (measure the cell, or an approver's calibration build); its unsigned gap
    // is still named and signable
    const i2 = page.getByTestId('factory-item-I-2')
    await expect(i2.getByTestId('step-I-2-readiness')).toContainText('Not built — no context standard is proven for the backend.route.add S and M cells')
    await expect(i2.getByTestId('item-status-I-2')).toHaveText('Not built — no proven standard')
    await expect(i2.getByTestId('refusal-I-2')).toContainText('Not built: no context standard is proven')
    await expect(i2.getByTestId('refusal-I-2')).toContainText('an approver may fund one calibration build, which never opens a pull request')
    await expect(i2.getByTestId('step-I-2-red')).toContainText('not run')
    await expect(i2.getByTestId('evidence-I-2')).toHaveCount(0)
    // J-FAC-16 — the approver's gap form asks the catalogue's question
    const form = i2.getByRole('form', { name: 'Sign a structural gap for I-2' })
    await expect(form.getByRole('combobox')).toContainText(/\(method_path\)/)
  })

  // G-143 — the approver's own acts, walked live as the approver: signing the structural gap
  // (the chain records it under their id), and lifting the sign-off clause, which is offered only
  // where delivery is linked — never on this stack, so it must not be offered here
  test('the approver signs I-2’s structural gap; the chain records it under their id; no override is offered while delivery is not linked', async ({ page }) => {
    await ensureApprover(page)
    await page.goto('/home')
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page).toHaveURL(/\/login/)
    await signIn(page, APPROVER, APPROVER_PASS)
    const me = (await (await page.request.get(`${env.baseUrl}/api/v1/auth/me`)).json()) as { id: string; role: string }
    expect(me.role).toBe('approver')

    await page.goto(`/factory?repo=${encodeURIComponent(t.name)}&item=I-2`)
    const i2 = page.getByTestId('factory-item-I-2')
    const form = i2.getByRole('form', { name: 'Sign a structural gap for I-2' })
    await expect(form).toBeVisible()
    await form.getByRole('combobox').selectOption({ value: 'method_path' })
    await form.getByLabel('Your answer (the structural fact)').fill('GET /health')
    await form.getByRole('button', { name: 'Sign the gap' }).click()
    await expect(form).toContainText(`Signed by ${me.id}`)
    await expect(form).toContainText('on the chain')

    // the evidence chain holds the signature under the approver's id, and still verifies
    const chain = (await (await page.request.get(`${env.baseUrl}/api/v1/factory/${encodeURIComponent(t.name)}/evidence`)).json()) as {
      verified: boolean
      items: Array<{ kind: string; item_id: string; actor: string; payload: { record?: { slot?: string; verifier?: string } } }>
    }
    expect(chain.verified).toBe(true)
    const signed = chain.items.filter((e) => e.kind === 'gap.signoff' && e.item_id === 'I-2')
    expect(signed.at(-1)?.actor).toBe(me.id)
    expect(signed.at(-1)?.payload.record?.slot).toBe('method_path')
    expect(signed.at(-1)?.payload.record?.verifier).toBe(me.id)

    // the override is the approver's, but only over a delivery that can happen: not linked here
    const box = page.getByTestId('before-you-start')
    await expect(box).toBeVisible()
    await expect(box.getByRole('checkbox', { name: /Open pull requests/ })).toBeDisabled()
    await expect(box.getByText(/Lift the sign-off clause|Override the route gate/)).toHaveCount(0)
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
      // measure the whole page, not the first card to draw: the readiness checklist, the flow
      // tiles and every loading card have answered (P-782)
      await expect(page.getByTestId('before-you-start')).toBeVisible()
      // the flow card draws only for a stream the reading holds, and only once it has answered
      const flow = (await (await page.request.get(`${env.baseUrl}/api/v1/flow?repo=${encodeURIComponent(t.name)}`)).json()) as { streams: Array<{ stream: string }> }
      if (flow.streams.some((x) => x.stream === 'manufacture-and-deliver')) await expect(page.locator('#flow-manufacture-and-deliver')).toBeVisible()
      await expect(page.getByText('Loading…')).toHaveCount(0)
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
