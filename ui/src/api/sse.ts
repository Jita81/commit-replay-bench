/**
 * Server-Sent Events client for `GET /runs/{id}/events`.
 *
 * Wire shape (docs/API.md "SSE event shape"):
 *     event: step
 *     data: {"event_id": …, "seq": 12, …}
 *   …and `event: done` when the run is terminal.
 *
 * Behaviour:
 *   - resumes with `?after=<last seq>` on every (re)connect, so a dropped
 *     connection never replays or loses an event;
 *   - reconnects with capped exponential backoff until `done` or `close()`;
 *   - keeps a bounded buffer (ring, newest wins) so an all-night run cannot
 *     exhaust the tab;
 *   - never parses a malformed frame into the buffer — it is counted and
 *     surfaced as `dropped` (fail closed, honestly).
 *
 * The browser `EventSource` is injectable so tests can drive it.
 */

import type { StepEvent } from './types'
import { API_BASE } from './client'

export type SseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'done' | 'closed'

export interface SseSnapshot {
  status: SseStatus
  events: StepEvent[]
  lastSeq: number
  reconnects: number
  dropped: number
  error: string | null
}

export interface EventSourceLike {
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void
  close(): void
  onerror: ((ev: Event) => void) | null
  onopen: ((ev: Event) => void) | null
}

export type EventSourceFactory = (url: string) => EventSourceLike

export interface RunEventStreamOptions {
  /** Buffer size; older events are dropped first. Default 5,000. */
  maxEvents?: number
  /** Start after this seq (resume). Default 0 = from the beginning. */
  after?: number
  /** Injected for tests. Default: `window.EventSource` with credentials. */
  factory?: EventSourceFactory
  /** Backoff bounds in ms. */
  minBackoffMs?: number
  maxBackoffMs?: number
}

export function runEventsUrl(runId: string, after: number): string {
  const q = after > 0 ? `?after=${encodeURIComponent(String(after))}` : ''
  return `${API_BASE}/runs/${encodeURIComponent(runId)}/events${q}`
}

const defaultFactory: EventSourceFactory = (url) => new EventSource(url, { withCredentials: true })

export function parseStepEvent(raw: string): StepEvent | null {
  let obj: unknown
  try {
    obj = JSON.parse(raw)
  } catch {
    return null
  }
  if (!obj || typeof obj !== 'object') return null
  const e = obj as Record<string, unknown>
  if (typeof e.seq !== 'number' || typeof e.action !== 'string' || typeof e.stage !== 'string') return null
  return {
    event_id: String(e.event_id ?? ''),
    seq: e.seq,
    timestamp: String(e.timestamp ?? ''),
    trace_id: String(e.trace_id ?? ''),
    step_id: String(e.step_id ?? ''),
    parent_step_id: String(e.parent_step_id ?? ''),
    stage: e.stage as StepEvent['stage'],
    action: e.action,
    status: (typeof e.status === 'string' ? e.status : 'ok') as StepEvent['status'],
    actor: String(e.actor ?? ''),
    repo: String(e.repo ?? ''),
    task_id: String(e.task_id ?? ''),
    input_ref: String(e.input_ref ?? ''),
    output_ref: String(e.output_ref ?? ''),
    error_code: String(e.error_code ?? ''),
    error_message: String(e.error_message ?? ''),
    duration_ms: typeof e.duration_ms === 'number' ? e.duration_ms : null,
    cost_usd: typeof e.cost_usd === 'number' ? e.cost_usd : null,
    payload: e.payload && typeof e.payload === 'object' ? (e.payload as Record<string, unknown>) : {},
  }
}

/**
 * A subscribable stream. `subscribe(listener)` is called with a fresh
 * snapshot after every change; the snapshot object is replaced (never
 * mutated) so React can compare by identity.
 */
export class RunEventStream {
  private snapshot: SseSnapshot
  private listeners = new Set<(s: SseSnapshot) => void>()
  private source: EventSourceLike | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private backoff: number
  private readonly maxEvents: number
  private readonly minBackoff: number
  private readonly maxBackoff: number
  private readonly factory: EventSourceFactory
  private closed = false

  constructor(
    private readonly runId: string,
    options: RunEventStreamOptions = {},
  ) {
    this.maxEvents = options.maxEvents ?? 5_000
    this.minBackoff = options.minBackoffMs ?? 1_000
    this.maxBackoff = options.maxBackoffMs ?? 15_000
    this.backoff = this.minBackoff
    this.factory = options.factory ?? defaultFactory
    this.snapshot = {
      status: 'idle',
      events: [],
      lastSeq: options.after ?? 0,
      reconnects: 0,
      dropped: 0,
      error: null,
    }
  }

  getSnapshot(): SseSnapshot {
    return this.snapshot
  }

  subscribe(listener: (s: SseSnapshot) => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private set(patch: Partial<SseSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch }
    for (const l of this.listeners) l(this.snapshot)
  }

  open(): void {
    if (this.closed) return
    this.connect(false)
  }

  private connect(isReconnect: boolean): void {
    if (this.closed) return
    this.set({ status: isReconnect ? 'reconnecting' : 'connecting' })
    let es: EventSourceLike
    try {
      es = this.factory(runEventsUrl(this.runId, this.snapshot.lastSeq))
    } catch (err) {
      this.set({ error: err instanceof Error ? err.message : String(err) })
      this.scheduleReconnect()
      return
    }
    this.source = es
    es.onopen = () => {
      this.backoff = this.minBackoff
      this.set({ status: 'open', error: null })
    }
    es.addEventListener('step', (ev) => this.onStep(String(ev.data)))
    es.addEventListener('done', () => this.finish())
    es.onerror = () => {
      if (this.closed || this.snapshot.status === 'done') return
      this.teardownSource()
      this.set({ status: 'reconnecting', error: 'Event stream interrupted — reconnecting.' })
      this.scheduleReconnect()
    }
  }

  private onStep(raw: string): void {
    const ev = parseStepEvent(raw)
    if (!ev) {
      this.set({ dropped: this.snapshot.dropped + 1 })
      return
    }
    if (ev.seq <= this.snapshot.lastSeq && this.snapshot.events.length > 0) return // duplicate on resume
    let events = this.snapshot.events.concat(ev)
    if (events.length > this.maxEvents) events = events.slice(events.length - this.maxEvents)
    this.set({ events, lastSeq: Math.max(this.snapshot.lastSeq, ev.seq) })
  }

  private scheduleReconnect(): void {
    if (this.closed) return
    const delay = this.backoff
    this.backoff = Math.min(this.backoff * 2, this.maxBackoff)
    this.timer = setTimeout(() => {
      this.timer = null
      this.set({ reconnects: this.snapshot.reconnects + 1 })
      this.connect(true)
    }, delay)
  }

  private finish(): void {
    this.teardownSource()
    this.set({ status: 'done', error: null })
  }

  private teardownSource(): void {
    if (this.source) {
      try {
        this.source.close()
      } catch {
        /* ignore */
      }
      this.source = null
    }
  }

  close(): void {
    this.closed = true
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    this.teardownSource()
    if (this.snapshot.status !== 'done') this.set({ status: 'closed' })
  }
}
