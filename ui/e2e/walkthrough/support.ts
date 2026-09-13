/**
 * Shared plumbing for the live-stack walkthrough.
 *
 * Everything the specs do goes THROUGH THE UI (forms, clicks, the status pill).
 * The one exception is `stackHealth()`, which reads `/api/v1/health` so a spec can
 * say WHY the stack is unusable (no worker, sandbox down) instead of timing out.
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
 */

import { expect, test as base, type Locator, type Page } from '@playwright/test'

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

/** Sign in through the login form (never by cookie injection). */
export async function signIn(page: Page, user = env.user, pass = env.pass): Promise<void> {
  await page.goto('/login')
  await field(page, 'Username').fill(user)
  await field(page, 'Password').fill(pass)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByTestId('user-chip')).toBeVisible()
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
  limit?: number
  builder?: string
  model?: string
  builderConfig?: Record<string, unknown>
}

/**
 * Open the repo page, click "Start a run", fill the dialog and queue it. Resolves
 * once the app has navigated to the new run's page; returns the run id.
 */
export async function startRun(page: Page, repo: string, opts: StartRunOptions): Promise<string> {
  await page.goto(`/repos/${encodeURIComponent(repo)}`)
  await page.getByRole('button', { name: 'Start a run' }).click()
  const dialog = page.getByRole('dialog', { name: 'Start a run' })
  await expect(dialog).toBeVisible()
  await field(dialog, 'Kind').selectOption(opts.kind)
  if (opts.kind === 'replay' || opts.kind === 'blind') {
    await field(dialog, 'Builder').fill(opts.builder ?? '')
    if (opts.model) await field(dialog, 'Model').fill(opts.model)
    if (opts.builderConfig) await field(dialog, 'Builder config (JSON, optional)').fill(JSON.stringify(opts.builderConfig, null, 2))
  }
  if (opts.limit !== undefined) await field(dialog, 'Task limit').fill(String(opts.limit))
  await dialog.getByRole('button', { name: 'Queue run' }).click()
  await page.waitForURL(/\/runs\/[0-9a-f]{32}$/)
  return runIdFromUrl(page)
}
