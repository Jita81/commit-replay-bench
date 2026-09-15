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
 *
 * Navigation
 * ----------
 * What it is:   The SSE client: `RunEventStream` (a subscribable, reconnecting `EventSource`
 *               wrapper), `parseStepEvent` and `runEventsUrl`.
 * What it does: Streams a run's `StepEvent`s into a bounded ring buffer (5,000, oldest
 *               dropped), resumes with `?after=<last seq>` on every reconnect so a drop never
 *               replays or loses an event, backs off exponentially (1 s → 15 s) until the
 *               server's `done` or `close()`, and counts a malformed frame as `dropped`
 *               rather than parsing it into the buffer.
 * How:          `open()` → the injected factory builds the source at the resume URL →
 *               `step` frames go through `parseStepEvent` (seq / action / stage required,
 *               duplicates below `lastSeq` skipped) → each change replaces the snapshot object
 *               and notifies subscribers → `onerror` tears the source down and schedules a
 *               reconnect; `done` finishes.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useRunEvents` owns one stream per run and adapts it
 *               with `useSyncExternalStore`), ui/src/api/types.ts (`StepEvent`),
 *               ui/src/components/LiveLog.tsx (renders the snapshot), src/crb/server/routes/runs.py
 *               (the `text/event-stream` route and its `event: done`),
 *               src/crb/observability/events.py (the envelope the frames carry)
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx (a fake EventSource drives the
 *               stream through the page), ui/e2e/walkthrough/03-mine.spec.ts (live log
 *               against a real worker)
 * Touch when:   the SSE wire shape changes (docs/API.md "SSE event shape") or `StepEvent`
 *               gains a field — update `parseStepEvent` and ui/src/api/types.ts together;
 *               never for a new repository.
 */

import type { StepEvent } from './types'
import { API_BASE } from './client'

/** The stream's lifecycle; `done` is the server's verdict (run terminal), `closed` is ours (unmount). */
export type SseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'done' | 'closed'

/** What the screen sees. Replaced wholesale on every change so React compares by identity. */
export interface SseSnapshot {
  status: SseStatus
  events: StepEvent[]
  lastSeq: number
  reconnects: number
  dropped: number
  error: string | null
}

/** The subset of the browser `EventSource` the stream needs — small enough to fake in tests. */
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

/** The stream URL with `?after=<seq>` when resuming — the server replays only what follows. */
export function runEventsUrl(runId: string, after: number): string {
  const q = after > 0 ? `?after=${encodeURIComponent(String(after))}` : ''
  return `${API_BASE}/runs/${encodeURIComponent(runId)}/events${q}`
}

/** `withCredentials` so the cookie session reaches the stream (it is a cross-origin request under the dev proxy). */
const defaultFactory: EventSourceFactory = (url) => new EventSource(url, { withCredentials: true })

/** One `data:` frame → a `StepEvent`, or `null` when it is not one. Only `seq`, `action` and `stage` are required; everything else defaults so an older server's frame still renders. A `null` is COUNTED by the caller (`dropped`), never silently skipped. */
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

  /** The current snapshot (stable identity until the next change). */
  getSnapshot(): SseSnapshot {
    return this.snapshot
  }

  /** Register a change listener; returns the unsubscribe. Shaped for `useSyncExternalStore`. */
  subscribe(listener: (s: SseSnapshot) => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  /** Replace the snapshot (never mutate it) and notify; the one place state changes. */
  private set(patch: Partial<SseSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch }
    for (const l of this.listeners) l(this.snapshot)
  }

  /** Start streaming. A closed stream stays closed — `close()` is final. */
  open(): void {
    if (this.closed) return
    this.connect(false)
  }

  /**
   * Build a source at the resume URL and wire its callbacks. Reconnection is ours, not the
   * browser's: a native EventSource would retry the ORIGINAL URL, without `?after=`, so on
   * error the source is torn down and rebuilt from `lastSeq` under our own backoff.
   */
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
      // The server closes the socket after `event: done`; the browser reports that as an
      // error, which must not trigger a reconnect loop on a finished run.
      if (this.closed || this.snapshot.status === 'done') return
      this.teardownSource()
      this.set({ status: 'reconnecting', error: 'Event stream interrupted — reconnecting.' })
      this.scheduleReconnect()
    }
  }

  /** One `step` frame: parse, drop-or-append, trim the ring, advance `lastSeq`. */
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

  /** Exponential backoff, doubled per attempt and capped; reset to the minimum on `onopen`. */
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

  /** The server's `event: done`: the run is terminal, nothing more will arrive. */
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

  /** Stop for good (unmount / run id change); a `done` status is kept, anything else becomes `closed`. */
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
