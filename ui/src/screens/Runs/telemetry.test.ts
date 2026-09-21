/**
 * ui/src/screens/Runs/telemetry.ts — the run page's derived lines never fabricate.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for the pure helpers behind the Progress card's "Now", stage,
 *               heartbeat and queue lines, the factory header line and the evidence
 *               drawer's headline.
 * What it does: Pins the copy: every estimate names its basis and n; no finished task means
 *               no estimate; a heartbeat older than the worker probe's limit reads stale; a
 *               queued run states its position and what is ahead; a not-clean pack names the
 *               first failed belt and its cause; a field an older server does not send
 *               renders as absent, never as a zero.
 * How:          Fixed `nowMs` values so elapsed and age are deterministic.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Runs/telemetry.ts (the code under test), ui/src/api/types.ts
 *               (`Run`, `StepEvent`, `GradeResult`)
 * Tested by:    ui/src/screens/Runs/telemetry.test.ts
 * Touch when:   a line's copy or basis changes — update the expectation here first.
 */
import { describe, expect, it } from 'vitest'
import type { GradeResult, Run, StepEvent } from '../../api/types'
import { fmtAgo } from '../../lib/format'
import { containerLine, factoryLine, fmtDurationWords, heartbeatLine, nowLine, packHeadline, queueLine, stageLine } from './telemetry'

const T0 = Date.parse('2026-09-13T09:00:00Z')

const RUN: Run = {
  id: 'run-1',
  repo: 'alpha',
  kind: 'replay',
  status: 'running',
  mode: 'sighted',
  builder: 'editblock',
  model: 'gpt-oss-120b',
  provider: 'cerebras',
  ladder: ['r1'],
  executor: 'docker',
  timeout: 900,
  pool: 'standard',
  limit: null,
  task_ids: [],
  builder_config: {},
  actor: 'ada',
  created: '2026-09-13T08:59:00Z',
  started: '2026-09-13T09:00:00Z',
  finished: null,
  cancel_requested: false,
  error: '',
  cost_usd: 0.84,
  apparatus_version: '2.2',
  counts: { tasks: 3, clean: 2, disqualified: 0, errors: 0, first_pass_clean: 2, rows: 3 },
  progress: { done: 3, total: 10, current_task_id: '3f2a9c1b3f2a9c1b' },
  worker_id: 'worker-1',
  heartbeat: '2026-09-13T09:11:54Z',
}

const ev = (over: Partial<StepEvent>): StepEvent => ({
  event_id: 'e1',
  seq: 1,
  timestamp: '2026-09-13T09:12:00Z',
  trace_id: 'run-1',
  step_id: '',
  parent_step_id: '',
  stage: 'build',
  action: 'build.turn',
  status: 'ok',
  actor: '',
  repo: 'alpha',
  task_id: '3f2a9c1b3f2a9c1b',
  input_ref: '',
  output_ref: '',
  error_code: '',
  error_message: '',
  duration_ms: null,
  cost_usd: null,
  payload: {},
  ...over,
})

const grade = (over: Partial<GradeResult> = {}): GradeResult => ({
  task_id: 'a'.repeat(40),
  repo: 'alpha',
  mode: 'sighted',
  clean: true,
  tests_unmodified: true,
  target_green: true,
  no_new_failures: true,
  source_changed: true,
  disqualified: false,
  dq_reason: '',
  error: '',
  note: '',
  new_failures: [],
  tamper_files: [],
  changed_files: ['src/calc/__init__.py'],
  diff: null,
  target_run: null,
  belt_run: null,
  duration_s: 1,
  extra: {},
  ...over,
})

describe('fmtAgo (ui/src/lib/format.ts, shared with the Connection walk) / fmtDurationWords', () => {
  it('reads seconds, minutes and hours ago', () => {
    expect(fmtAgo('2026-09-13T09:11:54Z', T0 + 12 * 60_000)).toBe('6 s ago')
    expect(fmtAgo('2026-09-13T09:00:00Z', T0 + 12 * 60_000)).toBe('12 min ago')
    expect(fmtAgo('2026-09-13T09:00:00Z', T0 + 125 * 60_000)).toBe('2 h 5 min ago')
    expect(fmtAgo(null, T0)).toBeNull()
    expect(fmtAgo('not a date', T0)).toBeNull()
  })
  it('rounds a duration to words', () => {
    expect(fmtDurationWords(30)).toBe('under a minute')
    expect(fmtDurationWords(28 * 60 + 20)).toBe('about 28 minutes')
    expect(fmtDurationWords(65 * 60)).toBe('about 1 hour 5 minutes')
    expect(fmtDurationWords(Number.NaN)).toBe('—')
  })
})

describe('nowLine', () => {
  it('names elapsed, done, spend and an estimate with its basis and n', () => {
    const line = nowLine(RUN, [200, 260, 260], T0 + 12 * 60_000)
    expect(line).toBe('Started 12 min ago · 3 of 10 tasks done · $0.8400 so far · about 28 minutes left if the 7 remaining take the mean of the 3 done (4 min 0 s each) — a planning estimate, not a measurement.')
  })
  it('gives no estimate when no task has finished, and none when nothing remains', () => {
    expect(nowLine({ ...RUN, progress: { done: 0, total: 10, current_task_id: null }, cost_usd: 0 }, [], T0 + 30_000)).toBe('Started 30 s ago · 0 of 10 tasks done · $0.00 so far · no time estimate yet: no task has finished.')
    expect(nowLine({ ...RUN, progress: { done: 10, total: 10, current_task_id: null } }, [200], T0 + 60_000)).toBe('Started 1 min ago · 10 of 10 tasks done · $0.8400 so far.')
  })
  it('reads a finished run as a record, not a forecast', () => {
    expect(nowLine({ ...RUN, status: 'succeeded', finished: '2026-09-13T09:42:00Z', progress: { done: 10, total: 10, current_task_id: null } }, [1, 2], T0 + 99 * 60_000)).toBe('Finished after 42 min 0 s · 10 of 10 tasks done · $0.8400 spent.')
    expect(nowLine({ ...RUN, started: null, status: 'queued' }, [], T0)).toBe('Not started yet.')
  })
})

describe('stageLine', () => {
  it('reads the last event as task · stage · detail', () => {
    expect(stageLine(ev({ payload: { turn: 7, tool_calls: 2 } }), RUN)).toBe('Task 4 of 10 · build · turn 7')
    expect(stageLine(ev({ payload: { turn: 7 } }), { ...RUN, budget: { max_turns: 25 } })).toBe('Task 4 of 10 · build · turn 7 of 25')
    expect(stageLine(ev({ action: 'build.start', payload: { trial: 'r1', rung: 'r1', mode: 'sighted' } }), RUN)).toBe('Task 4 of 10 · build · attempt r1 (rung r1)')
    expect(stageLine(ev({ stage: 'grade', action: 'grade.belt', payload: { belt: 'target_green', value: false } }), RUN)).toBe('Task 4 of 10 · grade · belt target_green ✗')
    expect(stageLine(ev({ stage: 'ledger', action: 'ledger.append', payload: { clean: true } }), RUN)).toBe('Task 4 of 10 · ledger · row appended')
    expect(stageLine(ev({ stage: 'system', action: 'repo.clone.done', payload: {} }), RUN)).toBe('Task 4 of 10 · system · repo.clone.done')
  })
  it('names the item for a factory run and returns null with nothing to read', () => {
    expect(stageLine(ev({ stage: 'factory', action: 'red.proved', task_id: 'I-2', payload: {} }), { ...RUN, kind: 'factory' })).toBe('Item I-2 · factory · red.proved')
    expect(stageLine(undefined, RUN)).toBeNull()
    expect(stageLine(ev({}), { ...RUN, status: 'succeeded' })).toBeNull()
  })
})

describe('heartbeatLine', () => {
  it('reads the age, and stale over the probe limit', () => {
    expect(heartbeatLine(RUN, 120, T0 + 12 * 60_000)).toEqual({ text: 'Worker worker-1 last checked in 6 s ago.', stale: false })
    expect(heartbeatLine({ ...RUN, heartbeat: '2026-09-13T09:09:00Z' }, 120, T0 + 12 * 60_000)).toEqual({
      text: 'Worker worker-1 last checked in 3 min ago — over the 2 min 0 s limit. The queue will hand the run to another worker.',
      stale: true,
    })
  })
  it('does not claim stale without a limit, and says nothing when the server sends no heartbeat', () => {
    expect(heartbeatLine({ ...RUN, heartbeat: '2026-09-13T09:09:00Z' }, null, T0 + 12 * 60_000)).toEqual({ text: 'Worker worker-1 last checked in 3 min ago.', stale: false })
    expect(heartbeatLine({ ...RUN, heartbeat: null }, 120, T0)).toEqual({ text: 'Worker worker-1 has not checked in yet.', stale: false })
    expect(heartbeatLine({ ...RUN, worker_id: undefined, heartbeat: undefined }, 120, T0)).toBeNull()
    expect(heartbeatLine({ ...RUN, status: 'succeeded' }, 120, T0)).toBeNull()
  })
})

describe('containerLine', () => {
  const kill = (seq: number, action: string, container = 'crb-build-a1') => ev({ seq, stage: 'system', action, payload: { container } })
  it('stands between the unconfirmed kill and its reap, and names the by-hand command when the worker gave up', () => {
    expect(containerLine([])).toBeNull()
    expect(containerLine([ev({ stage: 'system', action: 'run.cancel_requested', payload: {} })])).toBeNull()
    expect(containerLine([kill(1, 'run.kill_unconfirmed')])).toEqual({ text: 'A container may still be running (being reaped by the worker).', failed: false })
    expect(containerLine([kill(1, 'run.kill_unconfirmed'), kill(2, 'run.kill_reaped')])).toBeNull()
    expect(containerLine([kill(1, 'run.kill_unconfirmed'), kill(2, 'run.kill_unconfirmed', 'crb-build-b2')])).toEqual({
      text: '2 containers may still be running (being reaped by the worker).',
      failed: false,
    })
    expect(containerLine([kill(1, 'run.kill_unconfirmed'), kill(2, 'run.kill_reap_failed')])).toEqual({
      text: 'A container may still be running — the worker gave up reaping: run `docker rm -f crb-build-a1` on the worker host.',
      failed: true,
    })
    // a later reap of the same name clears even a failure (an operator ran the command)
    expect(containerLine([kill(1, 'run.kill_unconfirmed'), kill(2, 'run.kill_reap_failed'), kill(3, 'run.kill_reaped')])).toBeNull()
    // an event without a container name is not a container
    expect(containerLine([ev({ stage: 'system', action: 'run.kill_unconfirmed', payload: {} })])).toBeNull()
  })
})

describe('queueLine', () => {
  it('states the position, the total and what is ahead', () => {
    expect(queueLine({ ...RUN, status: 'queued', queue_position: 3, queue_kinds_ahead: ['replay', 'mine', 'replay'] }, 7)).toBe('Queued — position 3 of 7 · ahead of it: 2 replay, 1 mine.')
    expect(queueLine({ ...RUN, status: 'queued', queue_position: 1, queue_kinds_ahead: [] }, null)).toBe('Queued — position 1 · next to run.')
  })
  it('does not invent a position an older server did not send', () => {
    expect(queueLine({ ...RUN, status: 'queued' }, 4)).toBe('Queued — waiting for a worker; this server does not report the position.')
  })
})

describe('factoryLine', () => {
  it('names builder, model, ladder and the delivery switch with its override', () => {
    const f = { ...RUN, kind: 'factory' as const, ladder: ['r1', 'r2'] }
    expect(factoryLine({ ...f, factory: { deliver: true, deliver_override_by: 'u2', deliver_override_by_name: 'Grace', backlog_hash: 'abc' } })).toBe('factory · sighted · editblock · gpt-oss-120b · cerebras · ladder r1,r2 · delivery on (override by Grace)')
    expect(factoryLine({ ...f, factory: { deliver: false, deliver_override_by: null, deliver_override_by_name: null, backlog_hash: null } })).toBe('factory · sighted · editblock · gpt-oss-120b · cerebras · ladder r1,r2 · delivery off')
    expect(factoryLine({ ...f, factory: { deliver: true, deliver_override_by: 'u2', deliver_override_by_name: null, backlog_hash: null } })).toContain('delivery on (override by u2)')
  })
  it('omits the delivery switch when the server does not send it', () => {
    expect(factoryLine({ ...RUN, kind: 'factory' })).toBe('factory · sighted · editblock · gpt-oss-120b · cerebras · ladder r1')
  })
})

describe('packHeadline', () => {
  it('clean: the belt count and what verified does not mean', () => {
    expect(packHeadline(grade(), true)).toBe('Clean: all four belts held and the pack’s hash verifies. This says nothing about whether the change is mergeable.')
    expect(packHeadline(grade({ repo_lint_clean: true }), true)).toBe('Clean: all five belts held and the pack’s hash verifies. This says nothing about whether the change is mergeable.')
    expect(packHeadline(grade(), false)).toBe('Clean: all four belts held, but the pack’s hash does not verify — treat this evidence as untrusted.')
  })
  it('not clean: the first failed belt by name and its cause', () => {
    expect(packHeadline(grade({ clean: false, no_new_failures: false, new_failures: ['test_divide_zero', 'test_divide_negative'] }), true)).toBe('Not clean: belt 3 (the repository’s own suite) — 2 new failures: test_divide_zero, test_divide_negative.')
    expect(packHeadline(grade({ clean: false, repo_lint_clean: false, lint_run: { detected: 'gofmt', ok: false, error: '', note: '', steps: [{ tool: 'gofmt', argv: [], rc: 1, verdict: false, timed_out: false, files: ['a.go', 'b.go'], tail: '', duration_s: 1, error: '' }], duration_s: 1 } }), true)).toBe('Not clean: belt 5 (the repository’s linter) — gofmt rejected 2 changed files.')
    expect(packHeadline(grade({ clean: false, target_green: false, target_run: { returncode: 1, failing: ['tests/test_x.py::test_a'], timed_out: false, parse_error: '', tail: '', duration_s: 2 } }), true)).toBe('Not clean: belt 2 (the target test) — still red (rc 1): tests/test_x.py::test_a.')
    expect(packHeadline(grade({ clean: false, target_green: false, target_run: { returncode: -9, failing: [], timed_out: true, parse_error: '', tail: '', duration_s: 900 } }), true)).toBe('Not clean: belt 2 (the target test) — timed out.')
    expect(packHeadline(grade({ clean: false, source_changed: false, note: 'green with no source change' }), true)).toBe('Not clean: belt 4 (source changed) — the build changed no source file, so the green proves nothing.')
    expect(packHeadline(grade({ clean: false, error: 'sandbox unavailable' }), true)).toBe('Not clean: the harness errored — sandbox unavailable. This counts against the instrument, not the builder.')
  })
  it('disqualified: the reason', () => {
    expect(packHeadline(grade({ clean: false, disqualified: true, dq_reason: 'target test file modified — disqualified', tests_unmodified: false, tamper_files: ['tests/test_x.py'] }), true)).toBe('Disqualified: target test file modified — disqualified. The row is excluded from every rate, never counted as a failure.')
  })
})
