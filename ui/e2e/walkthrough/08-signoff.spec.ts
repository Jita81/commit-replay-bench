/**
 * 08 — a sign-off is a policy decision, refused at write (`signoff-policy.v4`: ADR-0025 as
 * ADR-0026 amends it).
 *
 *  - The primary repo's only measured cell (n = 2 from 05) is REFUSED, and the reason is
 *    visible before the approver tries: the Sign-off page's preview lists every failing
 *    clause with *observed vs threshold* — `thin_cell` (2 vs 10), `controls_escapes`
 *    (1 vs 0), `route_not_deliver:posture_unsealed` (the walkthrough grades on the host, so
 *    its rows license nothing under `routing.v2`), `not_standard:reading_unregistered` (no
 *    registered reading proves a standard arm), `attestation_missing` — the gate is CLOSED
 *    and the action disabled; nothing is recorded. The escape is a REAL finding of 04's
 *    controls run, not a mock: the tier-1 fixture's tests are literal asserts
 *    (`assert opN(1, 2) == 3 + N`), so the `hardcode_cheat` control grades clean on them.
 *  - A cell that clears every other clause is SEEDED THROUGH THE API (`server_seed.py` is a
 *    pytest fixture and is not touched): a second fixture repo whose tests are PARAMETRISED
 *    (the cheat is not constructible → 0 escapes) is built here, served as a bare file://
 *    clone, onboarded, probed, mined, put through a controls run, an ORACLE run (the cell's
 *    oracle strength must be MEASURED) and replayed with `fixture_gold` — 18 clean rows in
 *    one cell. Under `routing.v2` it still routes `calibrate` `posture_unsealed`: tier 1 has
 *    no sealed posture and no registered reading, so no cell of a walkthrough delivers
 *    (G-956). The admin who queued every run is REFUSED by the two-person rule
 *    (`same_actor`) — shown before they try, never overridable. A second person is INVITED
 *    from Settings (`walk-invitee`, G-518): the admin reads the one-time link once, the
 *    approver opens it in their own browser, chooses a password and is active — and the same
 *    link is refused a second time. That approver reads Home task 7 Completed, names an
 *    accepted row and affirms it, and is still refused: the gate names the reading and the
 *    sealed posture, the API answers 409, nothing is written and the map's tier does not move.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 08 (sign-off), the only spec that also seeds through the API.
 * What it does: Pins that the primary repo's only measured cell (n = 2 from 05) is REFUSED with
 *               every failing clause visible before the approver tries — gate CLOSED, action
 *               disabled, nothing recorded; that a second fixture repo with PARAMETRISED tests
 *               (0 escapes; its oracle scores ≥ 0.80 once measured), onboarded, probed, mined,
 *               put through controls, an oracle run and 18 clean `fixture_gold` replays, clears
 *               every clause but the sealed posture and the reading; that the admin who queued
 *               those runs is refused `same_actor` before they try; that an approver invited from
 *               Settings accepts the one-time link (which then refuses a second use) and reads
 *               Home task 7 Completed; and that this second person is refused on the reading
 *               and the posture, with nothing written.
 * How:          Seeding goes through `POST /repos` / `POST /runs` with the CSRF header (the
 *               pytest seed fixture is not touched); the signer is invited through the
 *               Settings form and accepts in its own browser context (skipped on a rerun that
 *               finds the account; the stable `personaPassword`), and `walk-approver` is still
 *               ensured with `POST /users` for 11-screens; the sign-off itself is driven through the form (`attest-row`, `attest-read`,
 *               `attest-statement`, `signoff-recorded`).
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md (item 6)
 * Works with:   ui/e2e/walkthrough/support.ts, ui/src/screens/Settings/InviteApproverCard.tsx,
 *               ui/src/screens/Invite/AcceptInvitePage.tsx, ui/src/screens/Signoff/SignoffPage.tsx and
 *               ui/src/screens/Signoff/contract.ts (the screen under test),
 *               src/crb/core/signoff.py (the clauses asserted), src/crb/server/routes/signoffs.py,
 *               src/crb/builders/fixture_gold.py (the clean rows),
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts
 *               (whose n = 2 cell this spec relies on)
 * Tested by:    ui/e2e/walkthrough/08-signoff.spec.ts
 * Touch when:   never for a new repository (the seeded repository is this spec's own fixture);
 *               a refusal clause or a policy default changes (src/crb/core/signoff.py) — the
 *               expected clause list must follow; when the walkthrough can grade in the sealed
 *               posture and register a reading (G-956), the approver signs again here, reaches the cell
 *               through Decisions → Attest, and revokes and re-signs it (G-478); the invitation
 *               path changes.
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Locator } from '@playwright/test'
import { apiGet, apiPost, csrf, ensurePersona, env, expect, field, personaPassword, primary, signIn, startRunApi, test, waitRunApi } from './support'

test.describe.configure({ mode: 'serial' })

const SIGNABLE_NAME = 'walk-signable'
const N_TASKS = 18 // 16 clean rows already clear Wilson lower ≥ 0.80; two spare
const MIN = 60_000
/** The persona account 07 created and 11-screens uses; it is not the signer here. */
const APPROVER = 'walk-approver'
const APPROVER_PASS = personaPassword(APPROVER)
/** The second person who signs: invited from Settings, arrives through the one-time link (G-518, G-478). */
const INVITEE = 'walk-invitee'
const INVITEE_PASS = personaPassword(INVITEE)
const INVITEE_NAME = 'Walk invitee'

/**
 * A calculator repo whose per-commit tests are parametrised — the negative control
 * `hardcode_cheat` needs a literal `assert f(<literals>) == <literal>` to special-case
 * and finds none, so it is `not_constructible` rather than an escape. Every commit is
 * RED at its parent (the module does not exist) and GREEN with its own source.
 */
function buildSignableRepo(): string {
  const dir = env.work && existsSync(env.work) ? env.work : mkdtempSync(join(tmpdir(), 'crb-walk-'))
  const src = join(dir, 'signable-src')
  const bare = join(dir, 'signable.git')
  const git = (...args: string[]) => execFileSync('git', ['-C', src, '-c', 'user.name=Fixture Bot', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', ...args], { stdio: 'pipe' })
  mkdirSync(join(src, 'src', 'calc'), { recursive: true })
  mkdirSync(join(src, 'tests'), { recursive: true })
  execFileSync('git', ['init', '-q', '-b', 'main', src], { stdio: 'pipe' })
  writeFileSync(join(src, 'pytest.ini'), '[pytest]\ntestpaths = tests\n')
  writeFileSync(join(src, 'src', 'calc', '__init__.py'), '"""A tiny calculator."""\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n')
  writeFileSync(join(src, 'tests', 'test_calc.py'), 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n')
  git('add', '-A')
  git('commit', '-q', '-m', 'chore: scaffold calc')
  for (let i = 0; i < N_TASKS; i += 1) {
    writeFileSync(join(src, 'src', 'calc', `op${i}.py`), `def op${i}(a: int, b: int) -> int:\n    return a + b + ${i}\n`)
    writeFileSync(
      join(src, 'tests', `test_op${i}.py`),
      `import pytest\n\nfrom calc.op${i} import op${i}\n\n\n@pytest.mark.parametrize("a,b", [(1, 2), (3, 4), (-1, 1)])\ndef test_op${i}(a, b):\n    assert op${i}(a, b) == a + b + ${i}\n`,
    )
    git('add', '-A')
    git('commit', '-q', '-m', `feat: add op${i}`)
  }
  execFileSync('git', ['clone', '-q', '--bare', src, bare], { stdio: 'pipe' })
  return `file://${bare}`
}

const gateRow = (gate: Locator, label: string | RegExp) => gate.getByRole('listitem').filter({ hasText: label })

test.describe('08 sign-off policy', () => {
  const t = primary()
  let signableClass = ''
  let signableSize = ''
  let signableN = 0

  test('the primary repo\'s thin cell is REFUSED before the approver tries: every clause, observed vs threshold', async ({ page }) => {
    await page.goto(`/signoff?repo=${encodeURIComponent(t.name)}`)
    const gate = page.getByTestId('signoff-gate')
    await expect(gate).toBeVisible()
    await expect(gate).toContainText('policy signoff-policy.v4')
    const select = field(page, 'Cell')
    await expect.poll(async () => (await select.locator('option').count()) - 1).toBeGreaterThanOrEqual(1)
    const value = await select.locator('option').nth(1).getAttribute('value')
    await select.selectOption({ value: value! })
    const [cls, size] = value!.split('|')
    await expect(gate).toContainText(`Attest ${cls} × ${size}`)

    // the evidence the approver sees: n / point / Wilson-low / false-Q1 / oracle / controls / route
    const evidence = page.getByTestId('signoff-evidence')
    await expect(evidence).toBeVisible()
    await expect(page.getByTestId('signoff-tile-point')).toContainText('100.0%')
    await expect(page.getByTestId('signoff-tile-false-q1')).toContainText('0')
    const controls = page.getByTestId('signoff-controls')
    // 04's controls run: the tier-1 fixture's literal-assert tests let `hardcode_cheat`
    // grade clean (1 escape — a real finding); a public repository's tests may catch every
    // control (0 escapes). The page must say which, and the refusal list must agree.
    const escaped = env.publicTier ? await controls.getByTestId('controls-escaped').count() > 0 : true
    if (escaped) {
      await expect(controls.getByTestId('controls-escaped')).toBeVisible()
      await expect(controls).toContainText('1 escape(s)')
    } else {
      await expect(controls).toContainText('0 escape(s)')
    }
    // routing.v2: the walkthrough grades on the host, and the sealed posture is read first
    await expect(page.getByTestId('signoff-route')).toContainText('posture_unsealed')

    // every failing clause is listed with the number that failed and the bar it missed
    const refusals = page.getByTestId('signoff-refusals')
    await expect(refusals).toBeVisible()
    const thin = refusals.getByTestId('refusal-thin_cell')
    await expect(thin).toContainText('thin cell')
    await expect(thin).toContainText(env.publicTier ? /observed [1-9]\b/ : 'observed 2')
    await expect(thin).toContainText('threshold 10')
    const escape = refusals.getByTestId('refusal-controls_escapes')
    if (escaped) {
      await expect(escape).toContainText('a measurement control escaped the oracle')
      await expect(escape).toContainText('observed 1')
      await expect(escape).toContainText('threshold 0')
    } else {
      await expect(escape).toHaveCount(0)
    }
    await expect(refusals.getByTestId('refusal-route_not_deliver:posture_unsealed')).toContainText('observed calibrate')
    // signoff-policy.v4: only a standard arm a registered reading proved can be signed
    await expect(refusals.getByTestId('refusal-not_standard:reading_unregistered')).toBeVisible()
    await expect(refusals.getByTestId('refusal-attestation_missing')).toContainText('non-overridable')
    // the two-person rule: the admin signed in here queued 05's replay, so every person
    // behind the cell is the would-be approver — refused before they try, non-overridable
    await expect(refusals.getByTestId('refusal-same_actor')).toContainText('a second approver must sign')
    await expect(refusals.getByTestId('refusal-same_actor')).toContainText('non-overridable')
    await expect(gateRow(gate, 'Signed by a second person')).toContainText(/✗\s*not satisfied:/)

    // the gate is CLOSED on exactly those criteria; the action is disabled; nothing is sent
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    await expect(gateRow(gate, 'Cell is measured')).toContainText(/✓\s*satisfied:/)
    await expect(gateRow(gate, 'false-Q1 = 0')).toContainText(/✓\s*satisfied:/)
    await expect(gateRow(gate, 'n ≥ 10')).toContainText(/✗\s*not satisfied:/)
    await expect(gateRow(gate, /Negative controls passed/)).toContainText(escaped ? /✗\s*not satisfied:/ : /✓\s*satisfied:/)
    await expect(gateRow(gate, 'Route = deliver')).toContainText(/✗\s*not satisfied:/)
    await expect(gateRow(gate, 'The standard arm’s registered reading delivers')).toContainText(/✗\s*not satisfied:/)
    // even a named, affirmed row cannot open it
    await field(page, 'Accepted row').selectOption({ index: 1 })
    await page.getByTestId('attest-read').check()
    await field(page, 'Attestation statement').fill('walkthrough: attempting to sign off a thin cell under an escaped gate')
    await expect(page.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    await expect(page.getByTestId('signoff-recorded')).toHaveCount(0)
    await expect(page.getByRole('table', { name: `Sign-offs for ${t.name}` })).toContainText('No attestations yet')
  })

  test(`seed a cell through the API: onboard, probe, mine ${N_TASKS}, controls (0 escapes), oracle (≥ 0.80), replay ${N_TASKS} → calibrate on the sealed posture`, async ({ page }) => {
    test.setTimeout(20 * MIN)
    const url = buildSignableRepo()
    const runnerOpts: Record<string, unknown> = { pythonpath_suffix: '/src' }
    if (env.python) runnerOpts.python = env.python
    await apiPost(page, '/repos', {
      name: SIGNABLE_NAME,
      language: 'python',
      runner: 'pytest',
      url,
      src_prefix: 'src/',
      test_prefix: 'tests/',
      ext: '.py',
      belt_scope: 'AFFECTED_DIRS',
      probe: 'tests/test_calc.py',
      runner_opts: runnerOpts,
    })
    const probe = await apiPost(page, `/repos/${SIGNABLE_NAME}/probe`, {})
    await waitRunApi(page, String(probe.id), 3 * MIN)
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'mine', limit: N_TASKS }, 4 * MIN)
    const tasks = await apiGet(page.request, `/repos/${SIGNABLE_NAME}/tasks?limit=100`)
    expect(Number(tasks.total)).toBeGreaterThanOrEqual(N_TASKS)
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'controls', limit: 1 }, 3 * MIN)
    const controls = await apiGet(page.request, `/oracle/${SIGNABLE_NAME}/controls`)
    expect(controls.passed, JSON.stringify(controls)).toBe(true)
    expect(Number(controls.escapes)).toBe(0) // parametrised tests: the cheat is not constructible
    // signoff-policy.v2: the cell's oracle must be MEASURED — score every task by mutation
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'oracle', limit: N_TASKS }, 8 * MIN)
    const oracle = await apiGet(page.request, `/oracle/${SIGNABLE_NAME}`)
    const scored = (oracle.tasks as Array<Record<string, unknown>>).filter((t) => t.strength !== null)
    expect(scored.length, JSON.stringify(oracle.cells)).toBeGreaterThanOrEqual(16)
    for (const t of scored) expect(Number(t.strength), `task ${t.task_id} strength`).toBeGreaterThanOrEqual(0.5)
    await startRunApi(page, { repo: SIGNABLE_NAME, kind: 'replay', builder: 'fixture_gold', model: 'gold', limit: N_TASKS }, 6 * MIN)

    const map = await apiGet(page.request, `/capability-map?repo=${SIGNABLE_NAME}`)
    const cells = map.cells as Array<Record<string, unknown>>
    const best = cells.reduce((a, b) => (Number(b.n) > Number(a.n) ? b : a))
    signableClass = String(best.capability_class)
    signableSize = String(best.size)
    signableN = Number(best.n)
    expect(signableN, JSON.stringify(best)).toBeGreaterThanOrEqual(16)
    expect(best.false_q1).toBe(0)
    // routing.v2 (ADR-0025 row 3a): host-posture rows never deliver — tier 1 has no sealed
    // posture and no registered reading (G-956)
    expect(best.route, `route ${best.route}: ${best.reason}`).toBe('calibrate')
    expect(best.reason_code).toBe('posture_unsealed')
    expect((map.controls as Record<string, unknown>).state).toBe('passed')
    // … and the oracle of THAT cell, as the sign-off will measure it, clears the bar
    const oracleCell = (oracle.cells as Array<Record<string, unknown>>).find((c) => c.capability_class === signableClass && c.size === signableSize)!
    expect(oracleCell, JSON.stringify(oracle.cells)).toBeTruthy()
    expect(Number(oracleCell.strength_mean), JSON.stringify(oracleCell)).toBeGreaterThanOrEqual(0.8)
    // the second person the sign-off will need (the admin queued every run above)
    await ensurePersona(page, APPROVER, 'approver')
  })

  test('an admin invites an approver from Settings; the approver accepts the one-time link, and it works only once', async ({ browser, page }) => {
    const users = (await apiGet(page.request, '/users')) as { items: Array<{ username: string }> }
    if (!users.items.some((u) => u.username === INVITEE)) {
      await page.goto('/settings')
      const form = page.getByRole('form', { name: 'Invite an approver' })
      await expect(form).toBeVisible()
      await field(form, 'Username').fill(INVITEE)
      await field(form, 'Display name').fill(INVITEE_NAME)
      await field(form, 'Role').selectOption('approver')
      await field(form, 'Link expires in (hours)').fill('24')
      await form.getByRole('button', { name: 'Invite' }).click()
      const shown = page.getByTestId('invitation-link')
      await expect(shown).toContainText(`${INVITEE} is invited as approver`)
      await expect(shown).toContainText('shown once and cannot be recovered')
      await expect(page.getByTestId(`invitation-state-${INVITEE}`)).toHaveText('waiting')
      const link = new URL(((await page.getByTestId('invitation-url').textContent()) ?? '').trim(), env.baseUrl)
      expect(link.pathname).toBe('/invite')
      expect(link.searchParams.get('token') ?? '').not.toBe('')

      // the approver, in their own browser: the link, a password twice, and the account is active
      const theirs = await browser.newContext({ baseURL: env.baseUrl })
      try {
        const them = await theirs.newPage()
        await them.goto(`${link.pathname}${link.search}`)
        await field(them, 'New password').fill(INVITEE_PASS)
        await field(them, 'New password again').fill(INVITEE_PASS)
        await them.getByRole('button', { name: 'Set my password' }).click()
        await expect(them.getByTestId('invite-accepted')).toContainText(`${INVITEE} is now active as approver`)
        // the same link a second time is refused: it worked once
        const again = await theirs.newPage()
        await again.goto(`${link.pathname}${link.search}`)
        await field(again, 'New password').fill(`${INVITEE_PASS}-2`)
        await field(again, 'New password again').fill(`${INVITEE_PASS}-2`)
        await again.getByRole('button', { name: 'Set my password' }).click()
        await expect(again.getByTestId('error-state')).toContainText('This invitation link cannot be used')
        // and they sign in with the password they chose, which nobody else has seen
        await signIn(them, INVITEE, INVITEE_PASS)
      } finally {
        await theirs.close()
      }
      await page.reload()
      await expect(page.getByTestId(`invitation-state-${INVITEE}`)).toHaveText('accepted')
    }
    // the API agrees: the invitation is spent, and the account it made is the second person
    const invitations = (await apiGet(page.request, '/invitations')) as { items: Array<{ username: string; state: string }> }
    expect(invitations.items.find((i) => i.username === INVITEE)?.state).toBe('accepted')
  })

  test('the admin who queued the runs is refused by the two-person rule (same_actor) before trying', async ({ page }) => {
    await page.goto(`/signoff?repo=${SIGNABLE_NAME}`)
    const gate = page.getByTestId('signoff-gate')
    await expect(gate).toBeVisible()
    const select = field(page, 'Cell')
    await expect.poll(async () => (await select.locator('option').count()) - 1).toBeGreaterThanOrEqual(1)
    await select.selectOption({ value: `${signableClass}|${signableSize}` })
    await expect(gate).toContainText(`Attest ${signableClass} × ${signableSize}`)
    // controls passed and the oracle measured: the refusals are the route and the reading
    // (routing.v2: no sealed posture, no registered reading), the attestation and the person —
    // and naming a row does not lift the person
    const refusals = page.getByTestId('signoff-refusals')
    await expect(refusals.getByTestId('refusal-same_actor')).toContainText('non-overridable')
    await expect(refusals.getByTestId('refusal-same_actor')).toContainText('only person behind every accepted row')
    await expect(refusals.getByTestId('refusal-route_not_deliver:posture_unsealed')).toBeVisible()
    await expect(refusals.getByTestId('refusal-not_standard:reading_unregistered')).toBeVisible()
    await expect(refusals.locator('li')).toHaveCount(4)
    await expect(gateRow(gate, 'Signed by a second person')).toContainText(/✗\s*not satisfied:/)
    const picker = field(page, 'Accepted row')
    await expect.poll(async () => (await picker.locator('option').count()) - 1).toBeGreaterThanOrEqual(16)
    const rowHash = await picker.locator('option').nth(1).getAttribute('value')
    await picker.selectOption({ value: rowHash! })
    // the sentence names the run the admin queued, which produced the row they named
    const same = refusals.getByTestId('refusal-same_actor')
    await expect(same).toContainText(/queued run [0-9a-f]{8}, which produced the attested row/)
    await expect(same).toContainText('a second approver must sign')
    await expect(refusals.locator('li')).toHaveCount(3)
    await page.getByTestId('attest-read').check()
    await field(page, 'Attestation statement').fill('walkthrough: the admin who queued the replay trying to sign its result')
    await expect(page.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    await expect(page.getByTestId('signoff-recorded')).toHaveCount(0)
    // the API says the same, without writing: 409 same_actor, nothing recorded
    const res = await page.request.post(`${env.baseUrl}/api/v1/signoffs`, {
      headers: await csrf(page),
      data: { repo: SIGNABLE_NAME, cell: { capability_class: signableClass, size: signableSize }, note: 'walkthrough', attestation: { reviewed_row_hash: rowHash, statement: 'walkthrough: same actor' } },
    })
    expect(res.status(), await res.text()).toBe(409)
    const body = (await res.json()) as { error: { code: string; detail: { code: string; refusals: Array<{ code: string; overridable: boolean }> } } }
    expect(body.error.code).toBe('signoff_refused')
    const codes = body.error.detail.refusals.map((r) => r.code)
    expect(codes).toEqual(['route_not_deliver:posture_unsealed', 'not_standard:reading_unregistered', 'same_actor'])
    expect(body.error.detail.refusals.find((r) => r.code === 'same_actor')!.overridable).toBe(false)
    expect(((await apiGet(page.request, `/signoffs?repo=${SIGNABLE_NAME}`)).items as unknown[]).length).toBe(0)
  })

  test('a second person (the approver) is refused a cell with no proven standard: the gate names the reading and the sealed posture, and nothing is written', async ({ page }) => {
    // the page fixture signed in as the admin who queued the runs: end that session first
    await page.goto('/home')
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page).toHaveURL(/\/login/)
    await signIn(page, INVITEE, INVITEE_PASS)
    // Home task 7 for this repository reads Completed now a second person has arrived
    await page.goto(`/home?repo=${SIGNABLE_NAME}`)
    await expect(page.getByRole('list', { name: 'Tasks' }).getByRole('listitem').nth(6)).toContainText('Completed')
    // no cell of tier 1 clears the bar (G-956), so Decisions offers no Attest: pick the cell
    await page.goto(`/signoff?repo=${SIGNABLE_NAME}`)
    const gate = page.getByTestId('signoff-gate')
    await expect(gate).toBeVisible()
    const select = field(page, 'Cell')
    await expect.poll(async () => (await select.locator('option').count()) - 1).toBeGreaterThanOrEqual(1)
    await select.selectOption({ value: `${signableClass}|${signableSize}` })
    await expect(gate).toContainText(`Attest ${signableClass} × ${signableSize}`)

    // the evidence clears the other bars: n / point / false-Q1 / controls passed / oracle
    await expect(page.getByTestId('signoff-tile-point')).toContainText('100.0%')
    await expect(page.getByTestId('signoff-tile-point')).toContainText(String(signableN))
    await expect(page.getByTestId('signoff-tile-false-q1')).toContainText('0')
    const controls = page.getByTestId('signoff-controls')
    await expect(controls.getByTestId('controls-passed')).toBeVisible()
    await expect(controls).toContainText('0 escape(s)')
    await expect(gateRow(gate, /Oracle strength measured and ≥ 0\.80/)).toContainText(/✓\s*satisfied:/)
    // … but routing.v2 reads the sealed posture and a registered reading first (G-956)
    await expect(page.getByTestId('signoff-route')).toContainText('posture_unsealed')
    await expect(gateRow(gate, 'Route = deliver')).toContainText(/✗\s*not satisfied:/)
    await expect(gateRow(gate, 'The standard arm’s registered reading delivers')).toContainText(/✗\s*not satisfied:/)

    // naming and affirming a row lifts the attestation clause and never the others
    const picker = field(page, 'Accepted row')
    await expect.poll(async () => (await picker.locator('option').count()) - 1).toBeGreaterThanOrEqual(16)
    const first = picker.locator('option').nth(1)
    await expect(first).toContainText(/feat: add op\d+ · [0-9a-f]{10} · /)
    const rowHash = await first.getAttribute('value')
    expect(rowHash).toMatch(/^[0-9a-f]{64}$/)
    await picker.selectOption({ value: rowHash! })
    const refusals = page.getByTestId('signoff-refusals')
    await expect(refusals.getByTestId('refusal-not_standard:reading_unregistered')).toBeVisible()
    await expect(refusals.getByTestId('refusal-same_actor')).toHaveCount(0) // a second person
    await page.getByTestId('attest-read').check()
    await field(page, 'Attestation statement').fill('walkthrough: I read the accepted diff — it adds the op module and its parametrised test, nothing else.')
    await expect(gate).toHaveAttribute('data-state', 'CLOSED')
    await expect(gateRow(gate, 'Signed by a second person')).toContainText(/✓\s*satisfied:/)
    await expect(page.getByRole('button', { name: 'Sign off' })).toBeDisabled()
    await expect(page.getByTestId('signoff-recorded')).toHaveCount(0)

    // the API says the same, without writing: 409 on the route and the reading
    const res = await page.request.post(`${env.baseUrl}/api/v1/signoffs`, {
      headers: await csrf(page),
      data: { repo: SIGNABLE_NAME, cell: { capability_class: signableClass, size: signableSize }, note: 'walkthrough', attestation: { reviewed_row_hash: rowHash, statement: 'walkthrough: no proven standard' } },
    })
    expect(res.status(), await res.text()).toBe(409)
    const body = (await res.json()) as { error: { code: string; detail: { refusals: Array<{ code: string }> } } }
    expect(body.error.code).toBe('signoff_refused')
    expect(body.error.detail.refusals.map((r) => r.code)).toEqual(['route_not_deliver:posture_unsealed', 'not_standard:reading_unregistered'])
    expect(((await apiGet(page.request, `/signoffs?repo=${SIGNABLE_NAME}`)).items as unknown[]).length).toBe(0)
    // the Capability page's tier does not move
    const map = await apiGet(page.request, `/capability-map?repo=${SIGNABLE_NAME}`)
    const cell = (map.cells as Array<Record<string, unknown>>).find((c) => c.capability_class === signableClass && c.size === signableSize)!
    expect(cell.verification_tier).not.toBe('human-verified')
    expect(cell.route).toBe('calibrate')
  })
})
