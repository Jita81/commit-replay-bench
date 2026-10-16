// exmap/src/web/audio/pipeline/transcriptionQueue.ts — the segment FIFO (design §7.5): one in flight across both
// lanes, nothing dropped; a provider error pauses the queue, asks the controller to restart the provider once and
// retries the same segment once; a second failure sets the segment aside in failed[] (Retry re-enqueues).
import { ProviderError } from "../errors.js";
import type { Segment, TranscribeResult, TranscriptionProvider } from "../types.js";

export interface TranscriptionQueueDeps {
  provider(lane: Segment["lane"]): TranscriptionProvider | null;
  onText(segment: Segment, result: TranscribeResult): void;
  onError(segment: Segment, error: ProviderError, final: boolean): void;
  /** Asked once per failure cycle; resolves true when the provider is usable again. */
  restartProvider?(lane: Segment["lane"], error: ProviderError): Promise<boolean>;
  onChange?(): void;
}

interface Item {
  segment: Segment;
  retried: boolean;
}

export class TranscriptionQueue {
  readonly #deps: TranscriptionQueueDeps;
  #waiting: Item[] = [];
  #current: Item | null = null;
  #paused = false;
  #abort: AbortController | null = null;
  readonly failed: Segment[] = [];
  restarts = 0;
  #idleWaiters: Array<() => void> = [];
  #disposed = false;

  constructor(deps: TranscriptionQueueDeps) {
    this.#deps = deps;
  }

  get segmentsWaiting(): number {
    return this.#waiting.length;
  }

  get inFlight(): number {
    return this.#current ? 1 : 0;
  }

  get paused(): boolean {
    return this.#paused;
  }

  get speechWaitingMs(): number {
    return this.#waiting.reduce((acc, it) => acc + it.segment.speechMs, 0);
  }

  get oldestWaitingMs(): number {
    return this.#waiting[0]?.segment.startedAt ?? 0;
  }

  /** Returns false without queueing when the lane's provider is null or push-mode. */
  enqueue(segment: Segment): boolean {
    const p = this.#deps.provider(segment.lane);
    if (!p || p.mode !== "segment") return false;
    this.#waiting.push({ segment, retried: false });
    this.#deps.onChange?.();
    this.#pump();
    return true;
  }

  retryFailed(): void {
    const items = this.failed.splice(0, this.failed.length);
    for (const s of items) this.#waiting.push({ segment: s, retried: false });
    this.#paused = false;
    this.#deps.onChange?.();
    this.#pump();
  }

  /** Holds the queue (the model is not loaded yet); segments keep accumulating. */
  pause(): void {
    this.#paused = true;
    this.#deps.onChange?.();
  }

  /** Lifts a pause set by a failure or by pause() (the provider was restarted, loaded or re-selected by hand). */
  resume(): void {
    this.#paused = false;
    this.#deps.onChange?.();
    this.#pump();
  }

  /** Moves every waiting segment to failed[] (the person declined the model download); nothing is dropped. */
  failWaiting(): Segment[] {
    const items = this.#waiting.splice(0, this.#waiting.length).map((it) => it.segment);
    this.failed.push(...items);
    this.#deps.onChange?.();
    this.#checkIdle();
    return items;
  }

  idle(): Promise<void> {
    if (this.#waiting.length === 0 && !this.#current) return Promise.resolve();
    return new Promise((resolve) => this.#idleWaiters.push(resolve));
  }

  dispose(): void {
    this.#disposed = true;
    this.#abort?.abort();
    this.#waiting = [];
  }

  #pump(): void {
    if (this.#disposed || this.#paused || this.#current) {
      this.#checkIdle();
      return;
    }
    const item = this.#waiting.shift();
    if (!item) {
      this.#checkIdle();
      return;
    }
    this.#current = item;
    this.#abort = new AbortController();
    this.#deps.onChange?.();
    void this.#run(item, this.#abort.signal);
  }

  async #run(item: Item, signal: AbortSignal): Promise<void> {
    const provider = this.#deps.provider(item.segment.lane);
    if (!provider || provider.mode !== "segment") {
      // the lane's provider changed while the segment waited: there is nothing to transcribe it with
      this.#current = null;
      this.#deps.onError(item.segment, new ProviderError("NOT_SEGMENT_PROVIDER", "the lane no longer has a segment provider"), true);
      this.failed.push(item.segment);
      this.#deps.onChange?.();
      this.#pump();
      return;
    }
    let result: TranscribeResult | null = null;
    let error: ProviderError | null = null;
    try {
      result = await provider.transcribe(item.segment, { signal });
    } catch (e) {
      error = e instanceof ProviderError ? e : new ProviderError("TRANSCRIBE_FAILED", String((e as Error)?.message ?? e));
    }
    this.#current = null;
    this.#abort = null;
    if (this.#disposed) return;
    if (result) {
      this.#deps.onText(item.segment, result);
      this.#deps.onChange?.();
      this.#pump();
      return;
    }
    const err = error ?? new ProviderError("TRANSCRIBE_FAILED", "no result");
    if (!item.retried) {
      // first failure: pause, restart the provider once, retry the same segment once
      this.#paused = true;
      this.#deps.onError(item.segment, err, false);
      this.#deps.onChange?.();
      this.restarts++;
      let ok = false;
      try {
        ok = this.#deps.restartProvider ? await this.#deps.restartProvider(item.segment.lane, err) : true;
      } catch {
        ok = false;
      }
      if (this.#disposed) return;
      this.#waiting.unshift({ segment: item.segment, retried: true });
      if (ok) this.#paused = false;
      this.#deps.onChange?.();
      this.#pump();
      return;
    }
    // second failure: set aside; the queue stays paused until Retry or a provider change
    this.failed.push(item.segment);
    this.#paused = true;
    this.#deps.onError(item.segment, err, true);
    this.#deps.onChange?.();
    this.#checkIdle();
  }

  #checkIdle(): void {
    if (this.#waiting.length === 0 && !this.#current && this.#idleWaiters.length > 0) {
      const ws = this.#idleWaiters;
      this.#idleWaiters = [];
      for (const w of ws) w();
    }
  }
}
