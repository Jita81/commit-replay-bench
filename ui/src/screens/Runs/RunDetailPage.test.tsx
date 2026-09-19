/**
 * ui/src/screens/Runs/RunDetailPage.tsx and ui/src/api/sse.ts — the live log follows the stream,
 * and the split tiles never fabricate.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the SSE primitives and the run-detail screen, against a mocked API
 *               and a controllable `FakeEventSource`.
 * What it does: Pins that the resume URL carries `?after=`, that malformed frames are
 *               rejected (counted, not buffered), that a dropped stream reconnects from
 *               `lastSeq` and stops on `done`, that the buffer is bounded; that the page opens
 *               the stream and appends step events into the live log; and — after A2 — that
 *               the run's split tiles show the all-rows rate, the model rate, instrument and
 *               budget counts with cost-known, that a v5 task row shows five belt pills and a
 *               v4 row four (belt 5 never as failed), and that a failing split endpoint is
 *               reported instead of zero-filled.
 * How:          `RunEventStream` driven directly with the fake; `renderApp` at `/runs/:id` with
 *               `eventSourceFactory` injected; assertions on `live-log`, `tile-*` and
 *               `belt-*` test ids.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Runs/RunDetailPage.tsx and ui/src/api/sse.ts (the code under
 *               test), ui/src/screens/Capability/contract.ts (`useFailureSplit`'s shape),
 *               ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx
 * Touch when:   the SSE wire shape or a run-detail tile changes (docs/API.md) — extend the
 *               fake frames or the tile assertions.
 */
import { act, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EventSourceLike } from '../../api/sse'
import { RunEventStream, parseStepEvent, runEventsUrl } from '../../api/sse'
import type { Run } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { RunDetailPage } from './RunDetailPage'

/** A controllable EventSource double. */
class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = []
  listeners = new Map<string, Array<(ev: MessageEvent) => void>>()
  onerror: ((ev: Event) => void) | null = null
  onopen: ((ev: Event) => void) | null = null
  closed = false
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, l: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), l])
  }
  close() {
    this.closed = true
  }
  open() {
    this.onopen?.(new Event('open'))
  }
  emit(type: string, data: unknown) {
    for (const l of this.listeners.get(type) ?? []) l(new MessageEvent(type, { data: typeof data === 'string' ? data : JSON.stringify(data) }))
  }
  fail() {
    this.onerror?.(new Event('error'))
  }
}

const step = (seq: number, over: Record<string, unknown> = {}) => ({
  event_id: `e${seq}`,
  seq,
  timestamp: '2026-09-13T10:00:00.000Z',
  trace_id: 'run-1',
  stage: 'grade',
  action: 'grade.belt',
  status: 'ok',
  task_id: 'abc1234567890',
  payload: { belt: 'target_green', value: true },
  ...over,
})

const RUN: Run = {
  id: 'run-1',
  repo: 'sqlalchemy',
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
  created: '2026-09-13T09:00:00Z',
  started: '2026-09-13T09:01:00Z',
  finished: null,
  cancel_requested: false,
  error: '',
  cost_usd: 0.4,
  apparatus_version: '2.0',
  counts: { tasks: 10, clean: 8, disqualified: 1, errors: 0, first_pass_clean: 7, rows: 11 },
  progress: { done: 10, total: 40, current_task_id: 'abc1234567890' },
}

describe('sse primitives', () => {
  it('builds the resume URL', () => {
    expect(runEventsUrl('run-1', 0)).toBe('/api/v1/runs/run-1/events')
    expect(runEventsUrl('run-1', 12)).toBe('/api/v1/runs/run-1/events?after=12')
  })
  it('rejects malformed frames', () => {
    expect(parseStepEvent('not json')).toBeNull()
    expect(parseStepEvent('{"seq":"x"}')).toBeNull()
    expect(parseStepEvent(JSON.stringify(step(1)))?.seq).toBe(1)
  })
  it('reconnects with ?after=<lastSeq> and stops on done', async () => {
    vi.useFakeTimers()
    FakeEventSource.instances = []
    const s = new RunEventStream('run-1', { factory: (u) => new FakeEventSource(u), minBackoffMs: 10, maxBackoffMs: 20 })
    s.open()
    const es1 = FakeEventSource.instances[0]!
    es1.open()
    es1.emit('step', step(1))
    es1.emit('step', step(2))
    es1.fail()
    expect(s.getSnapshot().status).toBe('reconnecting')
    await vi.advanceTimersByTimeAsync(15)
    const es2 = FakeEventSource.instances[1]!
    expect(es2.url).toBe('/api/v1/runs/run-1/events?after=2')
    es2.open()
    es2.emit('step', step(2)) // duplicate on resume → ignored
    es2.emit('step', step(3))
    es2.emit('done', '')
    const snap = s.getSnapshot()
    expect(snap.status).toBe('done')
    expect(snap.events.map((e) => e.seq)).toEqual([1, 2, 3])
    expect(snap.reconnects).toBe(1)
    expect(es2.closed).toBe(true)
    vi.useRealTimers()
  })
  it('bounds the buffer', () => {
    const s = new RunEventStream('r', { factory: (u) => new FakeEventSource(u), maxEvents: 3 })
    s.open()
    const es = FakeEventSource.instances[FakeEventSource.instances.length - 1]!
    for (let i = 1; i <= 5; i++) es.emit('step', step(i))
    expect(s.getSnapshot().events.map((e) => e.seq)).toEqual([3, 4, 5])
    s.close()
  })
})

describe('RunDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeEventSource.instances = []
  })

  it('opens the SSE stream and appends step events into the live log', async () => {
    FakeEventSource.instances = []
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': RUN,
      'GET /runs/run-1/tasks': { items: [], total: 0, limit: 500, offset: 0 },
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} />, { route: '/runs/run-1', path: '/runs/:id' })

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const es = FakeEventSource.instances[0]!
    expect(es.url).toBe('/api/v1/runs/run-1/events')

    await act(async () => {
      es.open()
      es.emit('step', step(1))
      es.emit('step', step(2, { action: 'build.turn', stage: 'build', cost_usd: 0.0021, duration_ms: 812 }))
      es.emit('step', 'garbage{')
    })

    const log = screen.getByRole('log', { name: 'Run events' })
    expect(log.textContent).toContain('grade.belt')
    expect(log.textContent).toContain('build.turn')
    expect(log.textContent).toContain('$0.0021')
    expect(screen.getByTestId('live-log').textContent).toContain('2 events')
    expect(screen.getByTestId('live-log').textContent).toContain('1 malformed frame dropped')
    expect(screen.getByTestId('live-log').textContent).toContain('Live')

    // Header + tiles: counts with n and apparatus.
    await waitFor(() => expect(screen.getByTestId('tile-clean')).toBeInTheDocument())
    const tile = screen.getByTestId('tile-clean')
    expect(tile.textContent).toContain('80.0%')
    expect(tile.textContent).toContain('n =')
    expect(tile.textContent).toContain('apparatus 2.0')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '10')

    await act(async () => {
      es.emit('done', '')
    })
    expect(screen.getByTestId('live-log').textContent).toContain('Complete')
  })
})

describe('RunDetailPage — the failure split (A2)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeEventSource.instances = []
  })

  it('shows the run\'s split tiles: all-rows rate, model rate, instrument, budget, cost known', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': { ...RUN, status: 'succeeded', finished: '2026-09-13T09:30:00Z' },
      'GET /runs/run-1/tasks': { items: [], total: 0, limit: 500, offset: 0 },
      'GET /failure-split': {
        repo: 'sqlalchemy',
        run_id: 'run-1',
        n: 11,
        clean: 6,
        builder_red: 1,
        budget: 1,
        protocol: 1,
        harness: 2,
        disqualified: 1,
        rows: 12,
        point: 0.5455,
        ci_low: 0.28,
        ci_high: 0.787,
        model_n: 7,
        model_point: 0.8571,
        model_ci_low: 0.487,
        model_ci_high: 0.974,
        cost_known: 8,
        cost_unknown: 3,
        kinds: ['', 'builder_red', 'budget', 'protocol', 'harness', 'disqualified'],
      },
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} />, { route: '/runs/run-1', path: '/runs/:id' })
    await waitFor(() => expect(screen.getByTestId('tile-split-point')).toBeInTheDocument())

    expect(screen.getByTestId('tile-split-point').textContent).toContain('54.5%')
    expect(screen.getByTestId('tile-split-point').textContent).toContain('the rate that routes')
    expect(screen.getByTestId('tile-split-model').textContent).toContain('85.7%')
    expect(screen.getByTestId('tile-split-model').textContent).toContain('6 clean of 7 finished attempts')
    expect(screen.getByTestId('tile-split-instrument').textContent).toContain('3')
    expect(screen.getByTestId('tile-split-budget').textContent).toContain('1')
    expect(screen.getByTestId('tile-split-cost-known').textContent).toContain('8 / 11')
    expect(screen.getByTestId('run-split').getAttribute('aria-label')).toBe('red 1, lint 0, budget 1, protocol 1, harness 2, outage 0, DQ 1')
    expect(screen.queryByTestId('split-unavailable')).toBeNull()
  })

  it('renders five belt pills for a v5 task row and four for a v4 row (belt 5 never shown as failed)', async () => {
    const base = {
      capability_class: 'bug.fix',
      size: 'XS',
      pool: 'standard',
      language: 'go',
      trials: 1,
      clean: false,
      first_pass_clean: false,
      disqualified: false,
      error: '',
      cost_usd: 0.1,
      latency_s: 3,
      pack_hashes: [],
      row_ids: [],
    }
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': { ...RUN, status: 'succeeded', finished: '2026-09-13T09:30:00Z' },
      'GET /runs/run-1/tasks': {
        items: [
          {
            ...base,
            task_id: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
            belt_set: 'v5',
            belts: { tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true, repo_lint_clean: false },
          },
          {
            ...base,
            task_id: 'b1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
            belt_set: 'v4',
            belts: { tests_unmodified: true, target_green: false, no_new_failures: null, source_changed: null, repo_lint_clean: null },
          },
        ],
        total: 2,
        limit: 500,
        offset: 0,
      },
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} />, { route: '/runs/run-1', path: '/runs/:id' })
    const lists = await screen.findAllByRole('list', { name: /belts$/i })
    expect(lists.map((l) => l.getAttribute('data-belt-count'))).toEqual(['5', '4'])
    const b5 = screen.getAllByTestId('belt-repo_lint_clean')
    expect(b5).toHaveLength(1)
    expect(b5[0]).toHaveAttribute('aria-label', "Belt 5 — repo's own lint clean: failed")
  })

  it('says so when the split endpoint fails instead of fabricating zeros', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': RUN,
      'GET /runs/run-1/tasks': { items: [], total: 0, limit: 500, offset: 0 },
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} />, { route: '/runs/run-1', path: '/runs/:id' })
    const status = await screen.findByTestId('split-unavailable')
    expect(status.textContent).toContain('Failure split unavailable')
    expect(screen.queryByTestId('tile-split-point')).toBeNull()
  })
})

describe('RunDetailPage — telemetry on the Progress card and the live log (T2)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeEventSource.instances = []
  })

  /** The page's clock, fixed 12 minutes after RUN.started so elapsed and ages are deterministic. */
  const clock = () => Date.parse('2026-09-13T09:13:00Z')
  const HEALTH = { status: 'ok', probes: [{ name: 'worker', status: 'ok', detail: '1 running', data: { running: 1, queued: 4, stale: [], stale_after_s: 120 } }] }
  const tasksPage = (latencies: number[]) => ({
    items: latencies.map((latency_s, i) => ({
      task_id: `${i}`.repeat(40),
      capability_class: 'bug.fix',
      size: 'XS',
      pool: 'standard',
      language: 'python',
      trials: 1,
      clean: true,
      first_pass_clean: true,
      disqualified: false,
      error: '',
      cost_usd: 0.1,
      latency_s,
      belt_set: 'v5',
      belts: { tests_unmodified: true, target_green: true, no_new_failures: true, source_changed: true, repo_lint_clean: null },
      pack_hashes: [],
      row_ids: [],
    })),
    total: latencies.length,
    limit: 500,
    offset: 0,
  })

  it('shows the Now line (elapsed, spend, estimate with its basis), the stage from the last event, the heartbeat and the Terms', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /health': HEALTH,
      'GET /runs/run-1': { ...RUN, progress: { done: 3, total: 10, current_task_id: 'abc1234567890' }, cost_usd: 0.84, worker_id: 'worker-1', heartbeat: '2026-09-13T09:12:54Z' },
      'GET /runs/run-1/tasks': tasksPage([200, 260, 260]),
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} clock={clock} />, { route: '/runs/run-1', path: '/runs/:id' })
    const now = await screen.findByTestId('run-now')
    await waitFor(() => expect(now.textContent).toContain('about 28 minutes left if the 7 remaining take the mean of the 3 done (4 min 0 s each)'))
    expect(now.textContent).toContain('Started 12 min ago · 3 of 10 tasks done · $0.8400 so far')
    expect(now.textContent).toContain('a planning estimate, not a measurement')

    const hb = await screen.findByTestId('run-heartbeat')
    await waitFor(() => expect(hb.textContent).toBe('Worker worker-1 last checked in 6 s ago.'))
    expect(hb).not.toHaveAttribute('role', 'status')

    // No event yet: the stage line waits for the stream rather than guessing.
    expect(screen.queryByTestId('run-stage')).toBeNull()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const es = FakeEventSource.instances[0]!
    await act(async () => {
      es.open()
      es.emit('step', step(1, { stage: 'build', action: 'build.turn', payload: { turn: 7, tool_calls: 1 } }))
    })
    expect(screen.getByTestId('run-stage').textContent).toBe('Task 4 of 10 · build · turn 7')
    await act(async () => {
      es.emit('step', step(2, { payload: { belt: 'no_new_failures', value: false, new: ['test_divide_zero', 'test_divide_negative'] } }))
    })
    expect(screen.getByTestId('run-stage').textContent).toBe('Task 4 of 10 · grade · belt no_new_failures ✗')

    // The Terms on the card are real buttons that open a definition inline.
    const terms = screen.getByTestId('progress-terms')
    const belt = within(terms).getByRole('button', { name: /belt/ })
    expect(belt).toHaveAttribute('aria-expanded', 'false')
    within(terms).getByRole('button', { name: /sighted/ })
    within(terms).getByRole('button', { name: /evidence pack/ })
  })

  it('reads a stale heartbeat as a status against the worker probe limit', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /health': HEALTH,
      'GET /runs/run-1': { ...RUN, worker_id: 'worker-1', heartbeat: '2026-09-13T09:10:00Z' },
      'GET /runs/run-1/tasks': tasksPage([]),
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} clock={clock} />, { route: '/runs/run-1', path: '/runs/:id' })
    const hb = await screen.findByTestId('run-heartbeat')
    await waitFor(() => expect(hb.textContent).toContain('over the 2 min 0 s limit'))
    expect(hb).toHaveAttribute('role', 'status')
    expect(hb.textContent).toContain('The queue will hand the run to another worker.')
  })

  it('a queued run says its position and what is ahead; an older server gets no invented position', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /health': HEALTH,
      'GET /runs/run-1': { ...RUN, status: 'queued', started: null, queue_position: 3, queue_kinds_ahead: ['replay', 'mine', 'replay'] },
      'GET /runs/run-1/tasks': tasksPage([]),
    })
    const { unmount } = renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} clock={clock} />, { route: '/runs/run-1', path: '/runs/:id' })
    const q = await screen.findByTestId('run-queue')
    await waitFor(() => expect(q.textContent).toBe('Queued — position 3 of 4 · ahead of it: 2 replay, 1 mine.'))
    expect(screen.getByTestId('run-now').textContent).toBe('Not started yet.')
    unmount()
    vi.unstubAllGlobals()

    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': { ...RUN, status: 'queued', started: null },
      'GET /runs/run-1/tasks': tasksPage([]),
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} clock={clock} />, { route: '/runs/run-1', path: '/runs/:id' })
    const q2 = await screen.findByTestId('run-queue')
    expect(q2.textContent).toBe('Queued — waiting for a worker; this server does not report the position.')
  })

  it('a factory run’s header names builder, model, ladder and the delivery switch with its override', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': { ...RUN, kind: 'factory', ladder: ['r1', 'r2'], factory: { deliver: true, deliver_override_by: 'u2', deliver_override_by_name: 'Grace', backlog_hash: 'f'.repeat(64) } },
      'GET /runs/run-1/tasks': tasksPage([]),
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} clock={clock} />, { route: '/runs/run-1', path: '/runs/:id' })
    const line = await screen.findByTestId('run-identity')
    expect(line.textContent).toBe('factory · sighted · editblock · gpt-oss-120b · cerebras · ladder r1,r2 · delivery on (override by Grace)')
  })

  it('live log: a failed belt and an error row carry the red glyph, and every row explains its action', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /runs/run-1': RUN,
      'GET /runs/run-1/tasks': tasksPage([]),
    })
    renderApp(<RunDetailPage eventSourceFactory={(u) => new FakeEventSource(u)} clock={clock} />, { route: '/runs/run-1', path: '/runs/:id' })
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const es = FakeEventSource.instances[0]!
    await act(async () => {
      es.open()
      es.emit('step', step(1, { payload: { belt: 'tests_unmodified', value: true } }))
      es.emit('step', step(2, { payload: { belt: 'no_new_failures', value: false, new: ['test_divide_zero', 'test_divide_negative'] } }))
      es.emit('step', step(3, { stage: 'build', action: 'build.done', status: 'ok', error_message: 'builder: rate limited', payload: { builder: 'editblock' } }))
    })
    const rows = screen.getAllByTestId('log-row')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.textContent).toContain('tests_unmodified ✓')
    expect(within(rows[0]!).getByRole('img', { name: 'ok' })).toBeInTheDocument()
    expect(rows[1]!.textContent).toContain('no_new_failures ✗ — 2 new failures')
    expect(within(rows[1]!).getByRole('img', { name: 'belt failed' })).toBeInTheDocument()
    expect(within(rows[2]!).getByRole('img', { name: 'error' })).toBeInTheDocument()
    expect(rows[2]!.textContent).toContain('builder: rate limited')
    // The explanation line: one plain sentence per action, muted, on every row.
    expect(rows[0]!.textContent).toContain('One belt was evaluated; the value says whether it held.')
    expect(rows[2]!.textContent).toContain('The attempt finished with its turns, tokens and builder-reported cost.')
    // The explanations can be switched off; the rows stay.
    const toggle = screen.getByRole('checkbox', { name: 'Explain each row' })
    expect(toggle).toBeChecked()
    await act(async () => {
      toggle.click()
    })
    expect(screen.getAllByTestId('log-row')[0]!.textContent).not.toContain('One belt was evaluated')
  })
})
