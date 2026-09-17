/**
 * connection.ts — the walk's stages are derived from what the API knows, never kept.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `stagesFor`, `stageSummary` and `nameFromGitUrl`.
 * What it does: Pins that a fresh repository is at "probe"; that a running probe/mine run
 *               marks its stage in progress; that mined counts, an oracle report, a controls
 *               report and measured rows each complete their stage; that a failed controls
 *               report is `failed`, not done; that stages after a not-done stage are
 *               `blocked` (so the walk never offers step 4 before step 3); that the first
 *               measurement is the only stage that spends; and the GitHub-URL → name rule.
 * How:          Plain unit tests over hand-built `RepoSummary` shapes.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/connection.ts (under test)
 * Tested by:    ui/src/screens/Connect/connection.test.ts
 * Touch when:   a stage is added or its evidence source changes.
 */

import { describe, expect, it } from 'vitest'
import type { ControlsReport, OracleReport, RepoSummary } from '../../api/types'
import { nameFromGitUrl, stageSummary, stagesFor } from './connection'

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

describe('nameFromGitUrl', () => {
  it('derives owner-repo from GitHub, GitLab and Azure DevOps URLs', () => {
    expect(nameFromGitUrl('https://github.com/NHSDigital/mesh-client.git')).toBe('nhsdigital-mesh-client')
    expect(nameFromGitUrl('git@github.com:spf13/cobra.git')).toBe('spf13-cobra')
    expect(nameFromGitUrl('https://gitlab.com/acme/Tools')).toBe('acme-tools')
    expect(nameFromGitUrl('https://dev.azure.com/acme/_git/thing')).toBe('acme-thing')
    expect(nameFromGitUrl('not a url')).toBe('')
  })
})
