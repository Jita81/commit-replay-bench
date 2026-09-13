import { act, screen, waitFor } from '@testing-library/react'
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
