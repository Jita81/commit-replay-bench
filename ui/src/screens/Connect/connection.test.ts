/**
 * connection.ts — the walk's stages are derived from what the API knows, never kept.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `stagesFor`, `runningDetail`, `stageSummary` and `nameFromGitUrl`.
 * What it does: Pins that a fresh repository is at "probe"; that a running probe/mine run
 *               marks its stage in progress; that mined counts, an oracle report, a controls
 *               report and measured rows each complete their stage; that a failed controls
 *               report is `failed`, not done; that stages after a not-done stage are
 *               `blocked` (so the walk never offers step 4 before step 3); that the first
 *               measurement is the only stage that spends; that a failed or cancelled
 *               measurement with no rows reads as such, never "not started" (J-ONR-6); that
 *               the polled run turns the ellipsis lines into k of n, counters and spend, and
 *               a queued run into its place in the queue (J-TEL-6); and the GitHub-URL →
 *               name rule.
 * How:          Plain unit tests over hand-built `RepoSummary` shapes.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/connection.ts (under test)
 * Tested by:    ui/src/screens/Connect/connection.test.ts
 * Touch when:   a stage is added or its evidence source changes.
 */

import { describe, expect, it } from 'vitest'
import type { ControlsReport, OracleReport, RepoSummary, Run } from '../../api/types'
import { elapsed, nameFromGitUrl, runningDetail, stageSummary, stagesFor } from './connection'

function repo(over: Partial<RepoSummary> = {}): RepoSummary {
  return {
    name: 'alpha',
    language: 'python',
    runner: 'pytest',
    url: 'https://github.com/acme/alpha',
    clone_path: '',
    probe: { status: 'not_probed', run_id: null, checked: null, detail: '' },
    task_counts: { total: 0, standard: 0, hard: 0, gold_clean: 0, gold_failed: 0, unchecked: 0 },
    last_run: null,
    created: '2026-09-17T00:00:00Z',
    updated: '2026-09-17T00:00:00Z',
    ...over,
  } as RepoSummary
}

const ORACLE = { tasks: [{ task_id: 't1', strength: 0.8 }, { task_id: 't2', strength: 0.6 }] } as unknown as OracleReport
const CONTROLS_OK = { passed: true, n_rows: 42, violations: 0, escapes: 0, not_constructible: 6 } as unknown as ControlsReport
const CONTROLS_BAD = { passed: false, n_rows: 42, violations: 3, escapes: 1, not_constructible: 6 } as unknown as ControlsReport

describe('stagesFor', () => {
  it('a fresh repository is registered and waiting on the probe; later stages are blocked', () => {
    const s = stagesFor({ repo: repo() })
    expect(s.map((x) => `${x.id}:${x.status}`)).toEqual(['register:done', 'probe:todo', 'mine:blocked', 'oracle:blocked', 'controls:blocked', 'measure:blocked'])
    expect(s[0]?.detail).toContain('github.com/acme/alpha')
    expect(stageSummary(s)).toEqual({ label: 'toolchain probed', status: 'todo' })
    // only the first measurement spends
    expect(s.filter((x) => x.spends).map((x) => x.id)).toEqual(['measure'])
  })

  it('a running probe or mine run marks its stage in progress with the run to watch', () => {
    const probing = stagesFor({ repo: repo({ last_run: { id: 'r1', kind: 'probe', status: 'running', finished: null } }) })
    expect(probing[1]).toMatchObject({ status: 'running', runId: 'r1' })
    const mining = stagesFor({ repo: repo({ probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: 'pytest 8' }, last_run: { id: 'r2', kind: 'mine', status: 'queued', finished: null } }) })
    expect(mining[1]).toMatchObject({ status: 'done', detail: 'ok — pytest 8' })
    expect(mining[2]).toMatchObject({ status: 'running', runId: 'r2' })
  })

  it('mined counts, an oracle report, a passed controls report and measured rows complete their stages', () => {
    const r = repo({ probe: { status: 'degraded', run_id: 'r1', checked: 'x', detail: 'go missing' }, task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 } })
    const s = stagesFor({ repo: r, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 22 })
    expect(s.every((x) => x.status === 'done')).toBe(true)
    expect(s[2]?.detail).toBe('12 tasks (10 gold-clean, 1 gold-failed, 1 unchecked)')
    expect(s[3]?.detail).toBe('2 tasks scored')
    expect(s[4]?.detail).toBe('passed · 42 rows · 0 violations · 0 escapes · 6 not constructible')
    expect(s[5]?.detail).toBe('22 rows on the current apparatus')
    expect(stageSummary(s)).toEqual({ label: 'measured', status: 'done' })
  })

  it('a failed controls report is failed (not done) and blocks the measurement', () => {
    const r = repo({ probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: '' }, task_counts: { total: 5, standard: 5, hard: 0, gold_clean: 5, gold_failed: 0, unchecked: 0 } })
    const s = stagesFor({ repo: r, oracle: ORACLE, controls: CONTROLS_BAD })
    expect(s[4]).toMatchObject({ status: 'failed' })
    expect(s[4]?.detail).toContain('FAILED · 42 rows · 3 violations · 1 escapes')
    expect(s[5]?.status).toBe('blocked')
  })

  it('a null oracle/controls (404 = never run) is todo once the earlier stages are done', () => {
    const r = repo({ probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: '' }, task_counts: { total: 5, standard: 5, hard: 0, gold_clean: 5, gold_failed: 0, unchecked: 0 } })
    const s = stagesFor({ repo: r, oracle: null, controls: null })
    expect(s[3]?.status).toBe('todo')
    expect(s[4]?.status).toBe('blocked')
  })
})

describe('stagesFor — an active run outranks done', () => {
  it('a running replay on a measured repository shows as in progress with the run to watch', () => {
    const r = repo({ probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: '' }, task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 }, last_run: { id: 'r9', kind: 'replay', status: 'running', finished: null } })
    const s = stagesFor({ repo: r, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 54 })
    expect(s[5]).toMatchObject({ status: 'running', runId: 'r9' })
    expect(s[5]?.detail).toBe('measuring… (54 rows already on the current apparatus)')
    expect(stageSummary(s)).toEqual({ label: 'first measurement', status: 'running' })
  })
})

const MEASURED = repo({ probe: { status: 'ok', run_id: 'r1', checked: 'x', detail: '' }, task_counts: { total: 12, standard: 9, hard: 3, gold_clean: 10, gold_failed: 1, unchecked: 1 } })

describe('stagesFor — a failed or cancelled measurement never reads as not started (J-ONR-6)', () => {
  it('a failed replay with no rows is failed with the run to open, and offers Retry not a blind spend', () => {
    const s = stagesFor({ repo: { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'failed', finished: 'x' } }, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 0 })
    expect(s[5]).toMatchObject({ status: 'failed', runId: 'r9', detail: 'the last measurement failed — open it for the reason before spending again' })
    expect(stageSummary(s)).toEqual({ label: 'first measurement', status: 'failed' })
  })

  it('a cancelled replay is todo with how many rows landed', () => {
    const s = stagesFor({ repo: { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'cancelled', finished: 'x' } }, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 0 })
    expect(s[5]).toMatchObject({ status: 'todo', runId: 'r9', detail: 'the last measurement was cancelled after 0 rows; start another when you are ready' })
  })

  it('rows on the apparatus still outrank an earlier failed or cancelled run', () => {
    const s = stagesFor({ repo: { ...MEASURED, last_run: { id: 'r9', kind: 'replay', status: 'failed', finished: 'x' } }, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 22 })
    expect(s[5]).toMatchObject({ status: 'done', detail: '22 rows on the current apparatus' })
  })
})

function run(over: Partial<Run>): Run {
  return {
    id: 'r9',
    repo: 'alpha',
    kind: 'replay',
    status: 'running',
    mode: 'sighted',
    builder: 'fixture',
    model: 'gold',
    provider: '',
    ladder: [],
    executor: 'docker',
    timeout: 600,
    pool: '',
    limit: null,
    task_ids: [],
    builder_config: {},
    actor: 'op',
    created: '2026-09-19T10:00:00Z',
    started: '2026-09-19T10:00:20Z',
    finished: null,
    cancel_requested: false,
    error: '',
    cost_usd: 0,
    apparatus_version: '2.2',
    counts: { tasks: 0, clean: 0, disqualified: 0, errors: 0, first_pass_clean: 0, rows: 0 },
    progress: { done: 0, total: 0, current_task_id: null },
    ...over,
  }
}
const NOW = Date.parse('2026-09-19T10:01:00Z')

describe('runningDetail — the live line from the polled run (J-TEL-6)', () => {
  it('falls back to the ellipsis line until the run has loaded', () => {
    expect(runningDetail('mine', undefined)).toBe('mining…')
    expect(runningDetail('measure', undefined)).toBe('measuring…')
  })

  it('a queued run says where it is in the queue, never "in progress"', () => {
    expect(runningDetail('oracle', run({ status: 'queued', started: null }))).toBe('Queued — waiting for a worker')
    expect(runningDetail('oracle', run({ status: 'queued', started: null }), { queuedAhead: 0 })).toBe('Queued — next in line for a worker')
    expect(runningDetail('oracle', run({ status: 'queued', started: null }), { queuedAhead: 1 })).toBe('Queued — 1 run ahead of it')
    expect(runningDetail('oracle', run({ status: 'queued', started: null }), { queuedAhead: 2 })).toBe('Queued — 2 runs ahead of it')
  })

  it('each kind reads its own counter: elapsed, found / examined / target, task k of n, attempt k of n with spend', () => {
    expect(runningDetail('probe', run({ kind: 'probe' }), { now: NOW })).toBe("Probing — running the repository's own suite (started 40 s ago)")
    expect(runningDetail('mine', run({ kind: 'mine', limit: 25, counts: { tasks: 0, clean: 0, disqualified: 0, errors: 0, first_pass_clean: 0, rows: 0, detail: { found: 4, examined: 37 } } }))).toBe('Mining — 4 tasks found · 37 commits examined · target 25')
    expect(runningDetail('mine', run({ kind: 'mine' }), { now: NOW })).toBe('Mining — reading the history (started 40 s ago)')
    expect(runningDetail('oracle', run({ kind: 'oracle', progress: { done: 2, total: 12, current_task_id: 't3' } }))).toBe('Scoring oracles — task 3 of 12')
    expect(runningDetail('controls', run({ kind: 'controls', progress: { done: 4, total: 12, current_task_id: 't5' } }))).toBe('Running the controls — task 5 of 12')
    expect(runningDetail('measure', run({ progress: { done: 2, total: 10, current_task_id: 't3' }, cost_usd: 0.42 }))).toBe('Measuring — attempt 3 of 10 · $0.42 so far, builder-reported')
    expect(runningDetail('measure', run({}))).toBe('Measuring — first attempt starting · $0.00 so far, builder-reported')
  })

  it('stagesFor uses the watched run only when it is the stage\'s own, and flags queued', () => {
    const r = { ...MEASURED, last_run: { id: 'r9', kind: 'replay' as const, status: 'running' as const, finished: null } }
    const s = stagesFor({ repo: r, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 54, watched: run({ progress: { done: 2, total: 10, current_task_id: 't3' }, cost_usd: 0.42 }) })
    expect(s[5]?.detail).toBe('Measuring — attempt 3 of 10 · $0.42 so far, builder-reported (54 rows already on the current apparatus)')
    expect(s[5]?.queued).toBe(false)
    const other = stagesFor({ repo: r, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 54, watched: run({ id: 'stale' }) })
    expect(other[5]?.detail).toBe('measuring… (54 rows already on the current apparatus)')
    const q = stagesFor({ repo: { ...r, last_run: { ...r.last_run, status: 'queued' } }, oracle: ORACLE, controls: CONTROLS_OK, measuredRows: 54, watched: run({ status: 'queued', started: null }), queuedAhead: 2 })
    expect(q[5]).toMatchObject({ status: 'running', queued: true })
    expect(q[5]?.detail).toBe('Queued — 2 runs ahead of it (54 rows already on the current apparatus)')
  })

  it('elapsed rounds to seconds, minutes, then hours', () => {
    expect(elapsed('2026-09-19T10:00:20Z', NOW)).toBe('40 s ago')
    expect(elapsed('2026-09-19T09:58:00Z', NOW)).toBe('3 min ago')
    expect(elapsed('2026-09-19T08:00:00Z', NOW)).toBe('2 h ago')
  })
})

describe('nameFromGitUrl', () => {
  it('derives owner-repo from GitHub, GitLab and Azure DevOps URLs', () => {
    expect(nameFromGitUrl('https://github.com/NHSDigital/mesh-client.git')).toBe('nhsdigital-mesh-client')
    expect(nameFromGitUrl('git@github.com:spf13/cobra.git')).toBe('spf13-cobra')
    expect(nameFromGitUrl('https://gitlab.com/acme/Tools')).toBe('acme-tools')
    expect(nameFromGitUrl('https://dev.azure.com/acme/_git/thing')).toBe('acme-thing')
    expect(nameFromGitUrl('not a url')).toBe('')
  })
})
