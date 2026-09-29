/**
 * Shared plumbing for the live-stack walkthrough.
 *
 * Everything the specs ASSERT goes THROUGH THE UI (forms, clicks, the status pill).
 * `stackHealth()` reads `/api/v1/health` so a spec can say WHY the stack is unusable (no
 * worker, sandbox down) instead of timing out; the API helpers at the end (`apiPost`,
 * `startRunApi`, `ensurePersona` …) only SEED state a spec needs and does not itself prove
 * (08's second repository, the persona accounts, 11-screens on a stack of its own).
 *
 * Configuration comes from `CRB_E2E_*`, exported by `scripts/walkthrough.sh`:
 *
 *   CRB_E2E_BASE_URL   the API+UI origin (required)
 *   CRB_E2E_USER/PASS  the bootstrap admin (required)
 *   CRB_E2E_REPO_URL   tier 1: the bare file:// clone of tests/fixtures/pyrepo.py
 *   CRB_E2E_REPO_NAME  tier 1: the ledger key to register it under (default walk-pyrepo)
 *   CRB_E2E_PYTHON     tier 1: an interpreter that has pytest — pinned as runner_opts.python
 *                      so the probe needs no `pip install` (hermetic)
 *   CRB_E2E_CRB        path to the `crb` CLI (`crb ledger verify --path` on the export)
 *   CRB_E2E_WORK       a scratch directory for downloads
 *   CRB_E2E_PUBLIC=1   tier 2: onboard github.com/spf13/cobra + pallets/click instead
 *   CRB_E2E_BUILDER    tier 2: `claude_code` → 05 runs a REAL replay (auth=cli, limit 2)
 *
 * Navigation
 * ----------
 * What it is:   The walkthrough's fixtures and helpers: `env` (the `CRB_E2E_*` contract),
 *               `targets()` / `primary()` (the repos per tier), the signed-in `test`, `field`,
 *               `signIn`, `signOut`, `personaPassword`, `startRun` (from the repo page, or from
 *               the Runs page's own button with `{from: 'runs'}`), `waitForRun`, `runStatus`,
 *               `expectLogAction`, `stackHealth` (an axe sweep runs through ui/e2e/axe.ts),
 *               `exportAndVerifyLedger` (Export JSONL → `crb ledger verify`), `workDir`,
 *               `buildCalcRepo` (a calculator fixture with literal or parametrised tests, served
 *               as a bare `file://` clone — 04b's `walk-door` and 08's `walk-signable`); the
 *               seeding helpers `csrf`, `apiGet`, `apiPost`, `startRunApi`, `waitRunApi`,
 *               `ensurePersona`.
 * What it does: Makes every spec drive a REAL stack through the UI — sign-in through the
 *               form (never cookie injection), runs queued through the dialog, completion
 *               awaited by watching the status pill the page itself polls (never a fixed
 *               sleep). `/health` is read directly so a spec can say WHY the stack is
 *               unusable; the API helpers seed what a spec needs but does not prove, so no
 *               spec relies on state another spec (or another CI job) created. `field()`
 *               matches a label exactly with or without the required marker so "Source"
 *               never matches "Source prefix".
 * How:          Playwright `test.extend` signs in before every test; helpers wrap the
 *               selectors documented in ui/e2e/walkthrough/README.md.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   scripts/walkthrough.sh (boots the stack and exports `CRB_E2E_*`),
 *               ui/src/screens/Runs/RunsPage.tsx (its "Start run" button, `startRun` from 'runs'),
 *               ui/src/screens/Ledger/LedgerPage.tsx (the Export JSONL link `exportAndVerifyLedger`
 *               follows),
 *               ui/playwright.walkthrough.config.ts (the config that runs these specs in
 *               order), ui/e2e/walkthrough/README.md (tiers, variables, selectors),
 *               tests/fixtures/pyrepo.py (the tier-1 fixture repository),
 *               ui/src/components/Field.tsx (the `Label *` rendering `field()` matches),
 *               ui/src/components/Layout.tsx (the user chip — display name and role, never
 *               the username, which is why `signIn` records who it signed in as; below
 *               640 px the chip and Sign out are folded behind the "Menu" button, F26, so
 *               "signed in" is the chip OR that button and `signOut` opens the menu first),
 *               ui/src/screens/Runs/RunNewDialog.tsx (what `startRun` fills)
 * Tested by:    every spec under ui/e2e/walkthrough (they all import this)
 * Touch when:   for a new repository in tier 2, add a `RepoTarget` to `publicTargets()`; a
 *               walkthrough variable, a tier target or a form label changes.
 */

import { expect, request as playwrightRequest, test as base, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHmac } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export type BeltPolicy = 'TARGET_ONLY' | 'AFFECTED_DIRS' | 'BARE'

export interface RepoTarget {
  /** Ledger key (lowercase). */
  name: string
  url: string
  /** `lib/repoPresets.ts` id chosen in the Add-repo dialog. */
  preset: string
  language: 'python' | 'go' | 'javascript' | 'jvm' | 'rust'
  /** Known-green probe scope. */
  probe: string
  /** Runner options JSON typed into the dialog (null = keep the preset's). */
  runnerOpts: Record<string, unknown> | null
  beltScope: BeltPolicy
  /** What the probe pill's detail must contain once green (the runner's own summary). */
  probeSummary: RegExp
  /** Task limit for the mine run (03). */
  mineLimit: number
  /** Upper bounds for waiting on runs, in ms. */
  probeTimeoutMs: number
  mineTimeoutMs: number
}

function required(name: string): string {
  const v = process.env[name]
  if (!v) throw new Error(`${name} is not set — run the walkthrough through scripts/walkthrough.sh`)
  return v
}

export const env = {
  baseUrl: required('CRB_E2E_BASE_URL'),
  user: required('CRB_E2E_USER'),
  pass: required('CRB_E2E_PASS'),
  repoUrl: process.env.CRB_E2E_REPO_URL ?? '',
  repoName: process.env.CRB_E2E_REPO_NAME ?? 'walk-pyrepo',
  python: process.env.CRB_E2E_PYTHON ?? '',
  crb: process.env.CRB_E2E_CRB ?? '',
  work: process.env.CRB_E2E_WORK ?? '',
  publicTier: process.env.CRB_E2E_PUBLIC === '1',
  builder: process.env.CRB_E2E_BUILDER ?? '',
  /** The fake tracker's board file (ADR-0017). Tier 1 seeds and reads it directly; no
   *  real Azure DevOps or Jira is contacted by any spec or by CI. */
  board: process.env.CRB_E2E_BOARD ?? '',
} as const

const MIN = 60_000

/** Tier 1: the fixture repo served over file://. */
function fixtureTarget(): RepoTarget {
  if (!env.repoUrl) throw new Error('CRB_E2E_REPO_URL is not set (tier 1 needs the fixture bare repo)')
  const runnerOpts: Record<string, unknown> = { pythonpath_suffix: '/src' }
  // Pin the interpreter: `environment_ready` is then true and the probe never installs.
  if (env.python) runnerOpts.python = env.python
  return {
    name: env.repoName,
    url: env.repoUrl,
    preset: 'python-src-layout',
    language: 'python',
    probe: 'tests/test_calc.py',
    runnerOpts,
    beltScope: 'AFFECTED_DIRS',
    probeSummary: /\d+ passed/,
    mineLimit: 3,
    probeTimeoutMs: 2 * MIN,
    mineTimeoutMs: 3 * MIN,
  }
}

/** Tier 2: two public repos, one Go and one Python (src layout), as the operator asked. */
function publicTargets(): RepoTarget[] {
  return [
    {
      name: 'cobra',
      url: 'https://github.com/spf13/cobra.git',
      preset: 'go',
      language: 'go',
      probe: './...',
      runnerOpts: null,
      beltScope: 'AFFECTED_DIRS',
      probeSummary: /ok|PASS/,
      mineLimit: 3,
      probeTimeoutMs: 20 * MIN,
      mineTimeoutMs: 25 * MIN,
    },
    {
      name: 'click',
      url: 'https://github.com/pallets/click.git',
      preset: 'python-src-layout',
      language: 'python',
      probe: 'tests/test_basic.py',
      runnerOpts: { pythonpath_suffix: '/src', pip: ['click', 'pytest'], uninstall: ['click'] },
      beltScope: 'TARGET_ONLY',
      probeSummary: /\d+ passed/,
      mineLimit: 3,
      probeTimeoutMs: 20 * MIN,
      mineTimeoutMs: 25 * MIN,
    },
  ]
}

/** The repos 02/03 onboard and mine. */
export function targets(): RepoTarget[] {
  return env.publicTier ? publicTargets() : [fixtureTarget()]
}

/** The repo 04–06 measure: the Python one (mutation oracle + controls + replay all run on it). */
export function primary(): RepoTarget {
  const all = targets()
  return all.find((t) => t.language === 'python') ?? all[0]!
}

// --- health (the one direct API read) -------------------------------------------------

export interface StackHealth {
  status: string
  probes: Array<{ name: string; status: string; detail: string; data: Record<string, unknown> }>
}

export async function stackHealth(page: Page): Promise<StackHealth> {
  const res = await page.request.get(`${env.baseUrl}/api/v1/health`)
  expect(res.ok(), `GET /api/v1/health → ${res.status()}`).toBeTruthy()
  return (await res.json()) as StackHealth
}

// --- form fields ------------------------------------------------------------------------

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * A form control by its label, exactly. Required fields render their label as
 * "<label> *" (the asterisk is aria-hidden but part of the label text), so a plain
 * exact match would miss them and a substring match would confuse "Source" with
 * "Source prefix"; this accepts the label with or without the marker and nothing else.
 */
export function field(scope: Page | Locator, label: string): Locator {
  return scope.getByLabel(new RegExp(`^${escapeRe(label)}( \\*)?$`))
}

// --- session ----------------------------------------------------------------------------

/**
 * The login name `signIn` last typed on a page, per page.
 *
 * The signed-in identity cannot be read back: the chip renders `display_name || email` and
 * the role and never the username (ui/src/components/Layout.tsx), the name is `hidden` below
 * `sm` so at 375 px the chip is the role alone, and `GET /auth/me` serves a `Principal`
 * (id, display_name, email, role, issuer — src/crb/server/deps.py) with no username either;
 * the one route that reports a username, `GET /users`, is admin-only. So the early return
 * is keyed on what this helper itself typed, which is knowledge, not an inference from
 * presentation. A page it has not signed in on — or has signed out of — is somebody else's
 * session and is signed out before the form is filled.
 */
const signedInAs = new WeakMap<Page, string>()

/**
 * Sign in through the login form (never by cookie injection).
 *
 * Safe to call on a page that is already signed in — including the `test` fixture's page,
 * which signs in before the test body runs. `/login` redirects an authenticated person
 * away, so a naive second sign-in waits for a form that never renders and only fails when
 * the whole test times out, minutes later. This ends the existing session first when it
 * belongs to somebody else, and returns immediately when it is already the person asked
 * for, so no spec can lose four minutes to that mistake again.
 */
export async function signIn(page: Page, user = env.user, pass = env.pass): Promise<void> {
  await page.goto('/login')
  const shell = signedInShell(page)
  const username = field(page, 'Username')
  // /login either renders the form or redirects: wait for whichever arrives, so this never
  // races the redirect and then blocks on a form that is no longer coming.
  await expect(shell.or(username).first()).toBeVisible()
  if (await shell.isVisible()) {
    if (signedInAs.get(page) === user) return
    await signOut(page)
    await expect(username).toBeVisible()
  }
  await username.fill(user)
  await field(page, 'Password').fill(pass)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(shell).toBeVisible()
  signedInAs.set(page, user)
}

/**
 * What a signed-in page shows at any width: the role chip, or — below 640 px, where the chip
 * is folded into the shell's "Menu" disclosure (F26) — the Menu button. `:visible` because
 * both are always in the DOM and only one is shown at a time.
 */
export function signedInShell(page: Page): Locator {
  return page.locator('[data-testid="user-chip"]:visible, [data-testid="shell-menu-button"]:visible').first()
}

/** Sign out through the shell at any width: on a phone, open the Menu first (F26). */
export async function signOut(page: Page): Promise<void> {
  const button = page.getByRole('button', { name: 'Sign out', exact: true })
  if (!(await button.isVisible())) await page.getByTestId('shell-menu-button').click()
  await button.click()
  signedInAs.delete(page)
}

/**
 * The password of a walkthrough persona account (`walk-viewer`, `walk-operator`, `walk-approver`):
 * STABLE across runs and processes against one stack, so a rerun signs into the account an
 * earlier run created instead of failing on a password it never knew. Derived, never stored:
 * HMAC-SHA256 of the username keyed by the stack's own bootstrap admin password (`CRB_E2E_PASS`),
 * so it is test-only, no easier to guess than the admin secret, never printed, and different on
 * every stack. 24 base64url characters + prefix satisfies `MIN_PASSWORD_LENGTH` (12).
 */
export function personaPassword(username: string): string {
  return `Walk-${createHmac('sha256', env.pass).update(username).digest('base64url').slice(0, 24)}`
}

/** `test` with a signed-in page: every spec but the login one uses it. */
export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => {
    await signIn(page)
    await use(page)
  },
})

export { expect }

// --- runs -------------------------------------------------------------------------------

export const TERMINAL = ['succeeded', 'failed', 'cancelled'] as const
export type RunStatus = 'queued' | 'running' | (typeof TERMINAL)[number]

export function runIdFromUrl(page: Page): string {
  const m = /\/runs\/([0-9a-f]{32})/.exec(page.url())
  if (!m) throw new Error(`not on a run page: ${page.url()}`)
  return m[1]!
}

/** The run page's status pill (aria-label "Status: <status>"). */
export async function runStatus(page: Page): Promise<RunStatus | ''> {
  const label = await page.getByTestId('run-status').getAttribute('aria-label')
  return (label?.replace(/^Status: /, '') ?? '') as RunStatus | ''
}

/**
 * Wait — by watching the status pill the page itself polls, never a fixed sleep —
 * until the run is terminal, then assert it ended in `expected`. On a `failed` run
 * the page's error text is part of the failure message.
 */
export async function waitForRun(page: Page, expected: RunStatus | RunStatus[], timeoutMs: number): Promise<RunStatus> {
  const want = Array.isArray(expected) ? expected : [expected]
  await expect
    .poll(async () => runStatus(page), { timeout: timeoutMs, intervals: [500, 1000, 2000], message: `run ${runIdFromUrl(page)} did not reach a terminal status` })
    .toMatch(/^(succeeded|failed|cancelled)$/)
  const got = (await runStatus(page)) as RunStatus
  if (!want.includes(got)) {
    const err = (await page.getByRole('alert').first().textContent().catch(() => '')) ?? ''
    throw new Error(`run ${runIdFromUrl(page)} ended ${got} (wanted ${want.join('|')})${err ? `: ${err.trim()}` : ''}`)
  }
  return got
}

/** The virtualised live log; rows carry the action name as visible text. */
export function liveLog(page: Page): Locator {
  return page.getByTestId('live-log')
}

export async function expectLogAction(page: Page, action: string): Promise<void> {
  await expect(liveLog(page).getByText(action, { exact: true }).first(), `live log should show ${action}`).toBeVisible()
}

export interface StartRunOptions {
  kind: 'mine' | 'replay' | 'blind' | 'oracle' | 'controls' | 'probe' | 'setup'
  /**
   * Where the dialog is opened from: the repository page's "Start a run" (the default), or the
   * Runs page's own "Start run" with the repository carried by `?repo=` (G-268) — the dialog
   * then arrives with the Repo preset and locked, which the helper asserts.
   */
  from?: 'repo' | 'runs'
  limit?: number
  builder?: string
  model?: string
  builderConfig?: Record<string, unknown>
  /** Click the dialog's "Blind budget sweep 25 → 50 → 100 tool calls" preset (replaces the ladder with three object rungs). */
  blindSweep?: boolean
  /** Run-level caps typed into the Budget section (blank fields keep the builder's defaults). */
  budget?: Partial<Record<'max_turns' | 'max_tool_calls' | 'max_tokens' | 'max_cost_usd' | 'wall_clock_s', number>>
}

const BUDGET_FIELD_LABELS = {
  max_turns: 'Max turns',
  max_tool_calls: 'Max tool calls',
  max_tokens: 'Max tokens',
  max_cost_usd: 'Max cost (USD)',
  wall_clock_s: 'Wall clock (s)',
} as const

/**
 * Open the repo page (or, with `from: 'runs'`, the Runs page filtered to the repository) and
 * click its start button; fill the dialog and queue it. Resolves once the app has navigated
 * to the new run's page; returns the run id.
 */
export async function startRun(page: Page, repo: string, opts: StartRunOptions): Promise<string> {
  if (opts.from === 'runs') {
    await page.goto(`/runs?repo=${encodeURIComponent(repo)}`)
    await page.getByRole('button', { name: 'Start run', exact: true }).click()
  } else {
    await page.goto(`/repos/${encodeURIComponent(repo)}`)
    await page.getByRole('button', { name: 'Start a run' }).click()
  }
  const dialog = page.getByRole('dialog', { name: 'Start a run' })
  await expect(dialog).toBeVisible()
  if (opts.from === 'runs') {
    // the Runs page carried the repository into the dialog: preset, and not offered for change
    await expect(field(dialog, 'Repo')).toHaveValue(repo)
    await expect(field(dialog, 'Repo')).toBeDisabled()
  }
  await field(dialog, 'Kind').selectOption(opts.kind)
  if (opts.kind === 'replay' || opts.kind === 'blind') {
    await field(dialog, 'Builder').fill(opts.builder ?? '')
    if (opts.model) await field(dialog, 'Model').fill(opts.model)
    if (opts.builderConfig) await field(dialog, 'Builder config (JSON, optional)').fill(JSON.stringify(opts.builderConfig, null, 2))
    for (const [key, value] of Object.entries(opts.budget ?? {})) {
      if (value !== undefined) await dialog.getByTestId('run-budget').getByLabel(BUDGET_FIELD_LABELS[key as keyof typeof BUDGET_FIELD_LABELS]).fill(String(value))
    }
    if (opts.blindSweep) await dialog.getByRole('button', { name: 'Blind budget sweep 25 → 50 → 100 tool calls' }).click()
  }
  if (opts.limit !== undefined) await field(dialog, 'Task limit').fill(String(opts.limit))
  await dialog.getByRole('button', { name: 'Queue run' }).click()
  await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
  return runIdFromUrl(page)
}

// --- downloads and fixtures ------------------------------------------------------------------

/** Where downloads and built fixture repositories land: `CRB_E2E_WORK`, else a temp dir. */
export function workDir(): string {
  return env.work && existsSync(env.work) ? env.work : mkdtempSync(join(tmpdir(), 'crb-walk-'))
}

export interface LedgerExport {
  path: string
  rows: Array<Record<string, unknown>>
  /** `crb ledger verify --json`'s verdict, or `null` when `CRB_E2E_CRB` is not set (annotated). */
  verdict: { ok: boolean; rows: number; false_q1: number; chain_ok: boolean } | null
}

/**
 * From /ledger, press Export JSONL, save the file as `ledger-<tag>.jsonl`, and verify it: every
 * row carries a 64-hex `row_hash` and a string `prev_hash`, and — when the CLI is available —
 * `crb ledger verify --path … --json` answers `ok`, `chain_ok`, `false_q1 = 0` and the row count
 * the file has. The one export-and-verify every spec that proves the chain shares (05, 06).
 */
export async function exportAndVerifyLedger(page: Page, tag: string): Promise<LedgerExport> {
  await page.goto('/ledger')
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export JSONL' }).click()])
  expect(download.suggestedFilename()).toMatch(/\.jsonl$/)
  const path = join(workDir(), `ledger-${tag}.jsonl`)
  await download.saveAs(path)
  const lines = readFileSync(path, 'utf8').split('\n').filter(Boolean)
  expect(lines.length).toBeGreaterThanOrEqual(1)
  const rows = lines.map((l) => JSON.parse(l) as Record<string, unknown>)
  for (const r of rows) {
    expect(String(r.row_hash)).toMatch(/^[0-9a-f]{64}$/)
    expect(typeof r.prev_hash).toBe('string')
  }
  let verdict: LedgerExport['verdict'] = null
  if (env.crb && existsSync(env.crb)) {
    const out = execFileSync(env.crb, ['ledger', 'verify', '--path', path, '--json'], { encoding: 'utf8' })
    verdict = JSON.parse(out) as NonNullable<LedgerExport['verdict']>
    expect(verdict.ok, out).toBe(true)
    expect(verdict.chain_ok, out).toBe(true)
    expect(verdict.false_q1, out).toBe(0)
    expect(verdict.rows).toBe(rows.length)
  } else {
    base.info().annotations.push({ type: 'note', description: 'CRB_E2E_CRB not set: chain checked by row_hash presence + row count only' })
  }
  return { path, rows, verdict }
}

export type CalcTests = 'literal' | 'parametrised'

/**
 * A calculator repository of `n` coupled src+test commits after a scaffold, built with `git init`
 * under `workDir()` and served as a bare `file://` clone. Every commit is RED at its parent (the
 * module does not exist) and GREEN with its own source — the shape the miner admits. The tests'
 * shape decides what the negative controls find, deterministically:
 *
 *  - `literal`: `assert opN(1, 2) == <literal>` — the `hardcode_cheat` control can special-case
 *    it and grades clean, so the controls report carries ≥ 1 escape (the tier-1 fixture's own
 *    finding; 04b walks it on `walk-door`);
 *  - `parametrised`: three `(a, b)` cases — the cheat finds no literal to special-case and is
 *    `not_constructible`, so the report has 0 escapes (08's `walk-signable`).
 */
export function buildCalcRepo(slug: string, n: number, tests: CalcTests): string {
  const dir = workDir()
  const src = join(dir, `${slug}-src`)
  const bare = join(dir, `${slug}.git`)
  const git = (...args: string[]) => execFileSync('git', ['-C', src, '-c', 'user.name=Fixture Bot', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', ...args], { stdio: 'pipe' })
  mkdirSync(join(src, 'src', 'calc'), { recursive: true })
  mkdirSync(join(src, 'tests'), { recursive: true })
  execFileSync('git', ['init', '-q', '-b', 'main', src], { stdio: 'pipe' })
  writeFileSync(join(src, 'pytest.ini'), '[pytest]\ntestpaths = tests\n')
  writeFileSync(join(src, 'src', 'calc', '__init__.py'), '"""A tiny calculator."""\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n')
  writeFileSync(join(src, 'tests', 'test_calc.py'), 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n')
  git('add', '-A')
  git('commit', '-q', '-m', 'chore: scaffold calc')
  for (let i = 0; i < n; i += 1) {
    writeFileSync(join(src, 'src', 'calc', `op${i}.py`), `def op${i}(a: int, b: int) -> int:\n    return a + b + ${i}\n`)
    writeFileSync(
      join(src, 'tests', `test_op${i}.py`),
      tests === 'parametrised'
        ? `import pytest\n\nfrom calc.op${i} import op${i}\n\n\n@pytest.mark.parametrize("a,b", [(1, 2), (3, 4), (-1, 1)])\ndef test_op${i}(a, b):\n    assert op${i}(a, b) == a + b + ${i}\n`
        : `from calc.op${i} import op${i}\n\n\ndef test_op${i}():\n    assert op${i}(1, 2) == ${3 + i}\n`,
    )
    git('add', '-A')
    git('commit', '-q', '-m', `feat: add op${i}`)
  }
  execFileSync('git', ['clone', '-q', '--bare', src, bare], { stdio: 'pipe' })
  return `file://${bare}`
}

// --- the API, for seeding (never for what a spec asserts about a screen) ------------------

/** The CSRF header the API requires on writes (double-submit cookie `crb_csrf`). */
export async function csrf(page: Page): Promise<Record<string, string>> {
  const cookie = (await page.context().cookies()).find((c) => c.name === 'crb_csrf')
  if (!cookie) throw new Error('no crb_csrf cookie — is the page signed in?')
  return { 'X-CSRF-Token': cookie.value }
}

/** `POST /api/v1<path>` as the page's signed-in person; asserts a 2xx and returns the body. */
export async function apiPost(page: Page, path: string, data: unknown): Promise<Record<string, unknown>> {
  const res = await page.request.post(`${env.baseUrl}/api/v1${path}`, { data, headers: await csrf(page) })
  expect(res.status(), `POST ${path} → ${res.status()} ${await res.text()}`).toBeLessThan(300)
  return (await res.json()) as Record<string, unknown>
}

/** `GET /api/v1<path>`; asserts a 2xx and returns the body. */
export async function apiGet(req: APIRequestContext, path: string): Promise<Record<string, unknown>> {
  const res = await req.get(`${env.baseUrl}/api/v1${path}`)
  expect(res.ok(), `GET ${path} → ${res.status()}`).toBeTruthy()
  return (await res.json()) as Record<string, unknown>
}

/** Poll a run through the API until it is terminal; assert it succeeded. */
export async function waitRunApi(page: Page, runId: string, timeoutMs: number): Promise<void> {
  await expect
    .poll(async () => String((await apiGet(page.request, `/runs/${runId}`)).status), { timeout: timeoutMs, intervals: [500, 1000, 2000], message: `run ${runId} did not finish` })
    .toMatch(/^(succeeded|failed|cancelled)$/)
  const run = await apiGet(page.request, `/runs/${runId}`)
  expect(run.status, `run ${runId} (${run.kind}) ended ${run.status}: ${run.error ?? ''}`).toBe('succeeded')
}

/** Queue a run through the API (`POST /runs`) and wait for it to succeed; returns its id. */
export async function startRunApi(page: Page, body: Record<string, unknown>, timeoutMs: number): Promise<string> {
  const run = await apiPost(page, '/runs', body)
  const id = String(run.id)
  await waitRunApi(page, id, timeoutMs)
  return id
}

/**
 * Make a walkthrough persona account exist — `walk-viewer`, `walk-operator` or `walk-approver`
 * with its stable `personaPassword` — as the admin signed in on `page`. When an earlier spec or
 * run created it, the stable password must open it, so every spec that signs in as a persona
 * owns that precondition instead of relying on the spec that happened to run before it (12's
 * viewer relied on 11-screens until the two ran in different CI jobs).
 */
export async function ensurePersona(page: Page, username: string, role: 'viewer' | 'operator' | 'approver'): Promise<void> {
  const password = personaPassword(username)
  const users = (await apiGet(page.request, '/users')) as { items: Array<{ username: string }> }
  if (users.items.some((u) => u.username === username)) {
    // its own cookie jar: signing in here must not replace the admin session on `page`
    const own = await playwrightRequest.newContext()
    try {
      const login = await own.post(`${env.baseUrl}/api/v1/auth/login`, { data: { username, password } })
      expect(login.status(), `POST /auth/login as existing ${username} with the stable password → ${login.status()}`).toBe(200)
    } finally {
      await own.dispose()
    }
    return
  }
  await apiPost(page, '/users', { username, password, role, display_name: `Walk ${role}` })
}
