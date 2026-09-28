/**
 * 14 — the context library: propose as a sponsor, sign as a second person, read the work type.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 14 (the context library, ADR-0026 item 10) on the tier-1 stack,
 *               after 02/03 have onboarded and mined the primary repository.
 * What it does: The admin opens the repository's Context library from its page, picks the first
 *               work type, proposes a convention scoped to it through the form and is told they
 *               are its sponsor; their own Sign button is disabled with the reason, and the API
 *               refuses their signature (409 `library_refused`, `same_person`) and records the
 *               refusal. A second person — the `walk-approver` persona — finds it on Decisions
 *               ("waits for a second person to sign it"), follows Sign to the library and signs
 *               it from the index; the entry reads signed, and the work type's page lists it as signed
 *               context with the sponsor, the signer and an `unmeasured` effect, says every
 *               size has no proven standard with the next measurement, and says nothing reaches
 *               a brief. Walked at 1280 and at 375 without sideways scroll. The pass from the
 *               repository's page to the signed entry on the work type's page is timed, printed
 *               and attached to the report — the figure OPERATOR §14 quotes (G-737). Then the
 *               admin proposes from the repository's files (G-677): the miners' proposals arrive
 *               with no sponsor and none signed, a Sponsor adopts one, and the same commit again
 *               proposes nothing new.
 * How:          Playwright; the form through its labels; the refusal through `page.request`
 *               with the CSRF header; the approver persona created with `POST /users` as 08 does.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 10)
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Library/LibraryPage.tsx,
 *               src/crb/server/routes/library.py, src/crb/core/miners.py (the miners' run),
 *               ui/e2e/walkthrough/03-mine.spec.ts (the tasks whose work types the page lists)
 * Tested by:    ui/e2e/walkthrough/14-library.spec.ts
 * Touch when:   never for a new repository; the page's form, its acts or the two-person rule
 *               change.
 */
import type { Page } from '@playwright/test'
import { env, expect, field, personaPassword, primary, signIn, test } from './support'

test.describe.configure({ mode: 'serial' })

const APPROVER = 'walk-approver'
const SLUG = `walk-${Date.now().toString(36)}`
const ENTRY = `convention/${SLUG}`

async function csrf(page: Page): Promise<Record<string, string>> {
  const cookie = (await page.context().cookies()).find((c) => c.name === 'crb_csrf')
  if (!cookie) throw new Error('no crb_csrf cookie — is the page signed in?')
  return { 'X-CSRF-Token': cookie.value }
}

/** Create the approver persona unless an earlier spec or run did. */
async function ensureApprover(page: Page): Promise<void> {
  const res = await page.request.get(`${env.baseUrl}/api/v1/users`)
  const users = (await res.json()) as { items: Array<{ username: string }> }
  if (users.items.some((u) => u.username === APPROVER)) return
  const made = await page.request.post(`${env.baseUrl}/api/v1/users`, {
    data: { username: APPROVER, password: personaPassword(APPROVER), role: 'approver', display_name: 'Walk approver' },
    headers: await csrf(page),
  })
  expect(made.status(), await made.text()).toBeLessThan(300)
}

function row(page: Page, id: string) {
  return page.getByRole('table', { name: /^Library entries for/ }).getByRole('row').filter({ hasText: id })
}

test('a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context', async ({ page }) => {
  const repo = primary().name
  await ensureApprover(page)
  const started = Date.now()
  // the door: the repository's page links to its library
  await page.goto(`/repos/${encodeURIComponent(repo)}`)
  await page.getByRole('link', { name: 'Context library' }).click()
  await expect(page).toHaveURL(new RegExp(`/library/${repo}`))
  await expect(page.getByTestId('library-count')).toHaveAttribute('data-ready', 'true')
  const first = page.getByRole('list', { name: 'Work types' }).getByRole('button').first()
  const workType = ((await first.textContent()) ?? '').split(' · ')[0]!.trim()
  expect(workType, 'the mined tasks give the page at least one work type').not.toBe('')
  await first.click()
  await expect(page.getByRole('heading', { name: `Work type: ${workType}` })).toBeVisible()

  // propose, as the sponsor
  await field(page, 'Short name (slug)').fill(SLUG)
  await field(page, 'Title').fill('Wrap errors with the operation')
  await field(page, 'Statement').fill('Every returned error names the operation that failed.')
  await field(page, 'Work types it applies to').fill(workType)
  await page.getByRole('button', { name: 'Propose as sponsor' }).click()
  await expect(page.getByTestId('library-proposed')).toContainText(`Proposed ${ENTRY}. You are its sponsor; a different approver must sign it.`)
  await expect(row(page, ENTRY).getByTestId(`status-${ENTRY}`)).toHaveText('proposed')

  // the same person cannot both sponsor and sign: the button says so, and the API refuses
  const own = row(page, ENTRY)
  await expect(own.getByRole('button', { name: 'Sign' })).toBeDisabled()
  await expect(own).toContainText('You sponsored this entry, so a second person must sign it.')
  const index = (await (await page.request.get(`${env.baseUrl}/api/v1/library/${repo}`)).json()) as { entries: Array<{ entry_id: string; version: string }> }
  const version = index.entries.find((e) => e.entry_id === ENTRY)!.version
  const refused = await page.request.post(`${env.baseUrl}/api/v1/library/${repo}/entries/convention/${SLUG}/sign`, { data: { version }, headers: await csrf(page) })
  expect(refused.status()).toBe(409)
  const err = (await refused.json()) as { error: { code: string; detail: { code: string } } }
  expect([err.error.code, err.error.detail.code]).toEqual(['library_refused', 'same_person'])

  // a second person finds it on Decisions and signs it from the library
  await signIn(page, APPROVER, personaPassword(APPROVER))
  await page.goto('/decisions')
  const waiting = page.getByRole('listitem').filter({ hasText: `${ENTRY} waits for a second person to sign it` })
  await expect(waiting).toContainText('Library entry to sign')
  await waiting.getByRole('link', { name: 'Sign' }).click()
  await expect(page).toHaveURL(new RegExp(`/library/${repo}#index$`))
  await page.getByRole('list', { name: 'Work types' }).getByRole('button').filter({ hasText: `${workType} · ` }).first().click()
  await row(page, ENTRY).getByRole('button', { name: 'Sign' }).click()
  await expect(row(page, ENTRY).getByTestId(`status-${ENTRY}`)).toHaveText('signed')

  // the work type's page lists it as signed context, with both people and no measured effect
  const context = page.getByRole('table', { name: `Signed context for ${workType}` })
  const signed = context.getByRole('row').filter({ hasText: ENTRY })
  await expect(signed).toContainText('Walk approver')
  await expect(signed).toContainText('unmeasured')
  await expect(page.getByRole('table', { name: `Proven standard per size for ${workType}` })).toContainText('No proven standard')
  await expect(page.getByText('Reaches no brief').first()).toBeVisible()
  // the recorded pass the operator guide quotes (G-737): a scripted pass, not a person reading
  const seconds = ((Date.now() - started) / 1000).toFixed(1)
  test.info().annotations.push({ type: 'library-pass-seconds', description: seconds })
  console.log(`[14-library] one scripted pass — propose, refused, sign, read: ${seconds} s, £0 (no model call)`)

  // a phone reads it without sideways scroll
  await page.setViewportSize({ width: 375, height: 800 })
  await page.reload()
  await expect(page.getByRole('heading', { name: `Work type: ${workType}` })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, 'no sideways scroll at 375 px').toBeLessThanOrEqual(1)
})

test('an operator proposes from the repository’s files; each proposal waits for a person, and the same commit proposes nothing new', async ({ page }) => {
  const repo = primary().name
  await page.goto(`/library/${encodeURIComponent(repo)}`)
  await expect(page.getByTestId('library-count')).toHaveAttribute('data-ready', 'true')
  const summary = page.getByTestId('library-mined')
  const before = await page.request.get(`${env.baseUrl}/api/v1/library/${repo}`)
  const known = ((await before.json()) as { entries: Array<{ entry_id: string }> }).entries.length
  await page.getByRole('button', { name: 'Propose from the files' }).click()
  // the fixture repository has tests under tests/ and a src/calc package: at least those
  await expect(summary).toContainText(/Read .+ at [0-9a-f]{12}: [1-9]\d* proposed/)
  await expect(summary).toContainText('Each proposal waits for a person to sponsor it and a different approver to sign it.')
  const mined = page.getByRole('table', { name: /^Library entries for/ }).getByRole('row').filter({ hasText: 'none yet — proposed by mined:' })
  await expect(mined.first()).toBeVisible()
  const after = ((await (await page.request.get(`${env.baseUrl}/api/v1/library/${repo}`)).json()) as { entries: Array<{ entry_id: string; status: string; sponsor: string }> }).entries
  expect(after.length).toBeGreaterThan(known)
  expect(after.filter((e) => e.status === 'signed' && !e.sponsor)).toEqual([]) // no miner signs
  // a person adopts one; nothing is signed until a different approver signs it
  const unadopted = await mined.count()
  await mined.first().getByRole('button', { name: 'Sponsor' }).click()
  await expect(mined).toHaveCount(unadopted - 1)
  // the same commit again: nothing new
  await page.getByRole('button', { name: 'Propose from the files' }).click()
  await expect(summary).toContainText(': 0 proposed,')
  await expect(summary).toContainText('Nothing new at this commit.')
})
