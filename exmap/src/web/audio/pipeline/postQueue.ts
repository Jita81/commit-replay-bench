// exmap/src/web/audio/pipeline/postQueue.ts — FIFO of utterances to the sink (design §7.5): up to three in flight,
// transient outcomes retried with backoff 0.5 → 1 → 2 → 4 → 8 s (cap, indefinitely while the page is open), refused
// outcomes surfaced once and never retried. Utterances are posted in production order.
import type { PostOutcome, RefusedUtterance, UtteranceSink, UtteranceWire } from "../types.js";

export const POST_BACKOFF_MS = [500, 1000, 2000, 4000, 8000] as const;
export const DEFAULT_MAX_IN_FLIGHT = 3;

export interface PostQueueEvents {
  onPosted?(u: UtteranceWire, outcome: Extract<PostOutcome, { ok: true }>): void;
  onRefused?(u: UtteranceWire, outcome: Extract<PostOutcome, { kind: "refused" }>): void;
  /** After three consecutive transient failures of one utterance (never for a timeout that resolves as duplicate). */
  onLastError?(u: UtteranceWire, outcome: Extract<PostOutcome, { kind: "transient" }>): void;
  onChange?(): void;
}

export interface PostQueueOptions {
  sink: UtteranceSink;
  maxInFlight?: number;
  timers?: { setTimeout(fn: () => void, ms: number): unknown; clearTimeout(h: unknown): void };
  events?: PostQueueEvents;
}

interface Item {
  u: UtteranceWire;
  attempts: number; // transient failures so far
  timer: unknown;
}

export class PostQueue {
  readonly #sink: UtteranceSink;
  readonly #max: number;
  readonly #timers: NonNullable<PostQueueOptions["timers"]>;
  readonly #events: PostQueueEvents;
  #waiting: Item[] = [];
  #inFlight = new Set<Item>();
  #retrying = new Set<Item>();
  readonly refused: RefusedUtterance[] = [];
  retries = 0;
  posted = 0;
  #idleWaiters: Array<() => void> = [];

  constructor(opts: PostQueueOptions) {
    this.#sink = opts.sink;
    this.#max = opts.maxInFlight ?? DEFAULT_MAX_IN_FLIGHT;
    this.#timers = opts.timers ?? { setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) };
    this.#events = opts.events ?? {};
  }

  get unsent(): number {
    return this.#waiting.length + this.#inFlight.size + this.#retrying.size;
  }

  get inFlight(): number {
    return this.#inFlight.size;
  }

  get waiting(): number {
    return this.#waiting.length;
  }

  enqueue(u: UtteranceWire): void {
    this.#waiting.push({ u, attempts: 0, timer: null });
    this.#events.onChange?.();
    this.#pump();
  }

  /** Resolves when nothing is waiting, in flight or scheduled for a retry. */
  idle(): Promise<void> {
    if (this.unsent === 0) return Promise.resolve();
    return new Promise((resolve) => this.#idleWaiters.push(resolve));
  }

  dispose(): void {
    for (const it of this.#retrying) this.#timers.clearTimeout(it.timer);
    this.#retrying.clear();
    this.#waiting = [];
  }

  #pump(): void {
    while (this.#inFlight.size < this.#max && this.#waiting.length > 0) {
      const item = this.#waiting.shift()!;
      this.#inFlight.add(item);
      void this.#send(item);
    }
    this.#checkIdle();
  }

  async #send(item: Item): Promise<void> {
    let outcome: PostOutcome;
    try {
      outcome = await this.#sink.post(item.u);
    } catch (e) {
      outcome = { ok: false, kind: "transient", status: null, message: String((e as Error)?.message ?? e) };
    }
    this.#inFlight.delete(item);
    if (outcome.ok) {
      this.posted++;
      this.#events.onPosted?.(item.u, outcome);
    } else if (outcome.kind === "refused") {
      this.refused.push({ id: item.u.id, text: item.u.text, status: outcome.status, reason: outcome.reason, detail: outcome.detail });
      this.#events.onRefused?.(item.u, outcome);
    } else {
      item.attempts++;
      this.retries++;
      if (item.attempts === 3) this.#events.onLastError?.(item.u, outcome);
      const delay = POST_BACKOFF_MS[Math.min(item.attempts, POST_BACKOFF_MS.length) - 1] ?? 8000;
      this.#retrying.add(item);
      item.timer = this.#timers.setTimeout(() => {
        this.#retrying.delete(item);
        // a retry goes to the front so production order is kept as far as possible
        this.#waiting.unshift(item);
        this.#pump();
      }, delay);
    }
    this.#events.onChange?.();
    this.#pump();
  }

  #checkIdle(): void {
    if (this.unsent === 0 && this.#idleWaiters.length > 0) {
      const ws = this.#idleWaiters;
      this.#idleWaiters = [];
      for (const w of ws) w();
    }
  }
}
