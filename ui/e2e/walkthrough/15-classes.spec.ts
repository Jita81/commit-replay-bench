/**
 * 15 — an organisation's classes: a sponsor proposes, a labeller labels, a second person signs.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 15 (an organisation's class sets, ADR-0026 item 9) on the tier-1
 *               stack, after 02/03 have onboarded and mined the primary repository.
 * What it does: The admin mines enough of the repository's history for a sample to label
 *               (`CLASS_SAMPLE_MINE`), follows the door from the repository's context library
 *               to Classes of work and proposes a class set through the form, becoming its
 *               sponsor; the version
 *               reads "Routes nothing" because nobody has signed it, the sponsor's own Sign button
 *               is disabled with the reason and the API refuses their signature (409
 *               `class_set_refused`, `same_person`), and the page's back link goes to the
 *               library. The `walk-operator` persona opens a class's page beside the labelling
 *               form — both swept with axe (WCAG 2.1 AA) — and labels the derivation commits,
 *               focus moving to the next commit after each label; the class's page says in
 *               words that feature.add sets no readiness question. The validity report shows
 *               its numbers — κ, the sample, coverage — and fails on too small a sample. The
 *               `walk-approver` persona signs it and hears the result where focus lands; it
 *               still routes nothing, because its report fails (the route line never naming the
 *               points check), and a reading of its class and a run stamped with it are both refused
 *               `class_set_not_routing`. The class's page reads in plain words: what the work
 *               is, the rule, example commits, what a ticket carries and "No proven standard"
 *               per size. Walked at 375 px without sideways scroll, the versions table's Open
 *               button on screen.
 * How:          Playwright; the forms through their labels; the refusals through `page.request`
 *               with the CSRF header; the personas made with `ensurePersona`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 9)
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Classes/ClassesPage.tsx,
 *               src/crb/server/routes/classes.py, ui/e2e/walkthrough/03-mine.spec.ts (the commits
 *               the set describes)
 * Tested by:    ui/e2e/walkthrough/15-classes.spec.ts
 * Touch when:   never for a new repository; the page's forms, the labelling screen or the
 *               two-person rule change.
 */
import { axeViolations } from '../axe'
import { csrf, ensurePersona, env, expect, field, personaPassword, primary, signIn, startRunApi, test } from './support'

test.describe.configure({ mode: 'serial' })

const OPERATOR = 'walk-operator'
const APPROVER = 'walk-approver'
const ORG = `walk${Date.now().toString(36)}`
const VERSION = `${ORG}/classes@v1`
/**
 * Commits the spec mines before proposing, so the labelling screen has a sample. The fixture's
 * commit ids change every run, and so do the split and the set-aside examples: over the 3 to 5
 * commits earlier specs mine, about 1 run in 5 offered nothing to label. At 30, the chance is
 * below 1 in 1,000 (tests/test_walkthrough_routes.py holds that bound; P-687).
 */
const CLASS_SAMPLE_MINE = 30

test('a sponsor proposes a class set, a person labels a sample, a second person signs, and it routes nothing until its report passes', async ({ page }) => {
  const repo = primary().name
  await ensurePersona(page, OPERATOR, 'operator')
  await ensurePersona(page, APPROVER, 'approver')
  // a sample to label: the split is by commit id, so more history is more derivation commits
  await startRunApi(page, { repo, kind: 'mine', limit: CLASS_SAMPLE_MINE }, 10 * 60_000)

  // the door: a repository's context library links to the organisation's classes
  await page.goto(`/library/${encodeURIComponent(repo)}`)
  await page.getByRole('link', { name: 'Your organisation’s classes of work' }).click()
  await expect(page).toHaveURL(/\/classes$/)
  await expect(page.getByTestId('classes-count')).toHaveAttribute('data-ready', 'true')

  // the sponsor proposes
  await field(page, 'Organisation').fill(ORG)
  await field(page, 'Repositories').fill(repo)
  await field(page, 'Classes, one per line').fill(
    'op-add; feature.add; Add an operation; A change that adds a new operation to the calculator; add, op\n' +
      'other-fix; bug.fix; Fix something else; A repair the ticket names as a fix; fix, repair',
  )
  await page.getByRole('button', { name: 'Propose as sponsor' }).click()
  await expect(page.getByTestId('class-set-proposed')).toHaveText(`Proposed ${VERSION}. You are its sponsor; a different approver must sign it.`)

  // unsigned, it routes nothing; the sponsor cannot sign it
  await page.goto(`/classes?org=${ORG}&v=1`)
  await expect(page.getByRole('heading', { name: `Class set ${VERSION}` })).toBeVisible()
  await expect(page.getByTestId('class-set-route')).toHaveText('Routes nothing')
  await expect(page.getByText('No approver other than its sponsor has signed it, so it routes nothing.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign this class set' })).toBeDisabled()
  await expect(page.getByText('You sponsored this class set, so a second person must sign it.')).toBeVisible()
  // the back link returns to the library the page's door is on
  await expect(page.getByRole('link', { name: 'Back to the context library' })).toHaveAttribute('href', `/library/${encodeURIComponent(repo)}`)
  const detail = (await (await page.request.get(`${env.baseUrl}/api/v1/classes/${ORG}/v/1`)).json()) as { digest: string }
  const own = await page.request.post(`${env.baseUrl}/api/v1/classes/${ORG}/v/1/sign`, { data: { digest: detail.digest }, headers: await csrf(page) })
  expect(own.status()).toBe(409)
  const err = (await own.json()) as { error: { code: string; detail: { code: string } } }
  expect([err.error.code, err.error.detail.code]).toEqual(['class_set_refused', 'same_person'])

  // a person labels the derivation commits, blind to the rule and to anyone else's labels
  await signIn(page, OPERATOR, personaPassword(OPERATOR))
  // a class's page and the labelling form, open together, pass axe (P-687)
  await page.goto(`/classes?org=${ORG}&v=1&class=op-add`)
  await expect(page.getByRole('heading', { name: 'Class: Add an operation' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Label a sample' })).toBeVisible()
  await expect(page.getByTestId('label-definitions')).toContainText('Add an operation (op-add): A change that adds a new operation to the calculator')
  // feature.add sets no readiness question: the page says so, never an empty heading
  await expect(page.getByTestId('class-no-slots')).toContainText('No readiness question is set for feature.add yet')
  const violations = await axeViolations(page)
  expect(violations, `the class page with the label form open: ${JSON.stringify(violations, null, 2)}`).toEqual([])
  let pressed = 0
  for (let i = 0; i < 80; i++) {
    const message = page.getByTestId('label-message')
    if (!(await message.isVisible())) break
    const said = (await message.textContent()) ?? ''
    await page.getByLabel('Which class is it?').selectOption(/\badd\b/.test(said) ? 'op-add' : /\bfix\b/.test(said) ? 'other-fix' : '(unclassified)')
    await page.getByRole('button', { name: 'Save label' }).click()
    // the next commit replaces this one (or the queue is done) before the next label is chosen
    await expect.poll(async () => ((await message.isVisible()) ? await message.textContent() : '')).not.toBe(said)
    await expect(page.getByTestId('class-labelled')).toContainText(`Saved: “${said.trim()}”`)
    if (await message.isVisible()) await expect(page.getByTestId('label-next')).toBeFocused()
    pressed++
  }
  expect(pressed, 'the mined repository gives the version at least one derivation commit to label').toBeGreaterThan(0)
  await expect(page.getByTestId('label-done')).toContainText('You have labelled every derivation commit this version offers.')
  const queue = (await (await page.request.get(`${env.baseUrl}/api/v1/classes/${ORG}/v/1/label-queue`)).json()) as { labelled_by_me: number; items: unknown[] }
  expect(queue.labelled_by_me).toBe(queue.items.length)

  // the report shows its numbers: κ over the sample, which is too small to pass
  const report = page.getByRole('table', { name: `Validity report of ${VERSION}` })
  const agreement = report.getByRole('row').filter({ hasText: 'Agreement with a person (κ)' })
  await expect(agreement).toContainText(String(queue.labelled_by_me))
  await expect(agreement.getByTestId('measure-agreement')).toHaveText('fail')
  await expect(agreement).toContainText('the sample needs')
  await expect(report.getByRole('row').filter({ hasText: 'Coverage' })).toContainText('%')

  // a second person signs; it still routes nothing, because its report fails
  await signIn(page, APPROVER, personaPassword(APPROVER))
  await page.goto(`/classes?org=${ORG}&v=1`)
  await page.getByRole('button', { name: 'Sign this class set' }).click()
  await expect(page.getByTestId('class-set-status')).toHaveText('signed')
  await expect(page.getByTestId('class-set-route')).toHaveText('Routes nothing')
  const failing = /Its validity report does not pass \(.*agreement.*\), so it routes nothing\./
  // the route line names only the checks that stop routing: never the points check (P-688)
  const routeLine = page.getByText(failing).and(page.locator(':not([role="status"])'))
  await expect(routeLine).toBeVisible()
  await expect(routeLine).not.toContainText('size agreement')
  // the signature's result is said where focus lands, with why it still routes nothing (P-687)
  const signed = page.getByTestId('class-set-signed')
  await expect(signed).toContainText(`You signed ${VERSION}.`)
  await expect(signed).toContainText(failing)
  await expect(signed).toBeFocused()

  // routing nothing: no reading of its classes, no run stamped with it
  const reading = await page.request.post(`${env.baseUrl}/api/v1/readings`, {
    data: {
      repo,
      cell: { process_step: 'replay', capability_class: 'feature.add', size: 'XS', language: 'python', builder: 'fixture_gold', model: 'gold', provider: '' },
      hierarchy: ['S3'],
      posture_class: 'docker/copy/sealed',
      taxonomy: VERSION,
      org_class: 'op-add',
    },
    headers: await csrf(page),
  })
  expect(reading.status()).toBe(409)
  expect(((await reading.json()) as { error: { code: string } }).error.code).toBe('class_set_not_routing')

  // the class's page, in plain words
  await page.getByRole('row').filter({ hasText: 'op-add' }).getByRole('button', { name: 'Read its page' }).click()
  await expect(page.getByRole('heading', { name: 'Class: Add an operation' })).toBeVisible()
  // the definition read on the class's own card (the label form, open beside it, repeats it)
  await expect(page.locator('#class').getByText('A change that adds a new operation to the calculator')).toBeVisible()
  await expect(page.getByTestId('class-rule')).toContainText('A ticket is in this class when the ticket’s text says “add” or “op”.')
  await expect(page.getByRole('table', { name: 'Proven standard per size for op-add' })).toContainText('No proven standard')
  await expect(page.getByRole('link', { name: new RegExp(`the ${repo} library’s feature.add page`) })).toBeVisible()

  // a phone reads it without sideways scroll
  await page.setViewportSize({ width: 375, height: 800 })
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Class: Add an operation' })).toBeVisible()
  // the class's card is one of four sections, each drawn from its own read: measure the page
  // once all four are there, not when the first answers (P-782)
  await expect(page.getByRole('table', { name: 'Class-set versions' })).toBeVisible()
  await expect(page.getByRole('heading', { name: `Class set ${VERSION}` })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Label a sample' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, 'no sideways scroll at 375 px').toBeLessThanOrEqual(1)
  // the only way to switch version is on screen, not scrolled off inside its table
  const open = page.getByRole('table', { name: 'Class-set versions' }).getByRole('button', { name: 'Open' }).first()
  const box = await open.boundingBox()
  expect(box, 'the Open button renders at 375 px').not.toBeNull()
  expect(box!.x + box!.width, 'the Open button sits inside the 375 px screen, not off its right edge').toBeLessThanOrEqual(375)
})
