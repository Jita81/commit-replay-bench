// exmap/src/web/audio/providers/replay.ts — the scripted replay provider (design §7.4): one fixture, timed or instant
// playback, breakpoints (until / step / skip), timers injectable. A push provider: it emits drafts itself.
import { ProviderError } from "../errors.js";
import type { CaptureLaneId, ProviderContext, ReplayFixture, ReplaySpeed, ReplayStatus, ReplayUtterance, Segment, TranscribeResult, TranscriptionProvider, WireLane } from "../types.js";

const TOP_KEYS = new Set(["version", "title", "story", "speakers", "utterances", "ui"]);
const ROW_KEYS = new Set(["label", "atMs", "lane", "speaker", "text", "durationMs", "expect"]);
const LANES: ReadonlySet<string> = new Set(["remote", "me", "manual"]);

function invalid(index: number | string, field: string, why: string): ProviderError {
  return new ProviderError("REPLAY_FIXTURE_INVALID", `${index}: ${field}: ${why}`);
}

/** Tolerates exactly story/speakers/ui at the top and label/expect per row; refuses any other unknown key. */
export function parseReplayFixture(json: unknown): ReplayFixture {
  if (typeof json !== "object" || json === null || Array.isArray(json)) throw invalid("fixture", "root", "must be an object");
  const o = json as Record<string, unknown>;
  for (const k of Object.keys(o)) if (!TOP_KEYS.has(k)) throw invalid("fixture", k, "unknown key");
  if (o["version"] !== 1) throw invalid("fixture", "version", "must be 1");
  if (typeof o["title"] !== "string" || o["title"].trim().length === 0) throw invalid("fixture", "title", "must be a non-empty string");
  if (o["story"] !== undefined && typeof o["story"] !== "string") throw invalid("fixture", "story", "must be a string");
  if (o["speakers"] !== undefined) {
    const sp = o["speakers"];
    if (typeof sp !== "object" || sp === null || Array.isArray(sp)) throw invalid("fixture", "speakers", "must be an object");
    for (const [k, v] of Object.entries(sp as Record<string, unknown>)) {
      if (k !== "remote" && k !== "me") throw invalid("fixture", `speakers.${k}`, "unknown lane");
      if (typeof v !== "string") throw invalid("fixture", `speakers.${k}`, "must be a string");
    }
  }
  const rows = o["utterances"];
  if (!Array.isArray(rows)) throw invalid("fixture", "utterances", "must be an array");
  const labels = new Set<string>();
  let prevAt = Number.NEGATIVE_INFINITY;
  const utterances: ReplayUtterance[] = rows.map((row, i) => {
    if (typeof row !== "object" || row === null || Array.isArray(row)) throw invalid(i, "row", "must be an object");
    const r = row as Record<string, unknown>;
    for (const k of Object.keys(r)) if (!ROW_KEYS.has(k)) throw invalid(i, k, "unknown key");
    if (typeof r["atMs"] !== "number" || !Number.isFinite(r["atMs"]) || r["atMs"] < 0) throw invalid(i, "atMs", "must be a non-negative number");
    if (r["atMs"] < prevAt) throw invalid(i, "atMs", `must be non-decreasing (previous ${prevAt})`);
    prevAt = r["atMs"];
    if (typeof r["lane"] !== "string" || !LANES.has(r["lane"])) throw invalid(i, "lane", "must be remote | me | manual");
    if (r["speaker"] !== null && typeof r["speaker"] !== "string") throw invalid(i, "speaker", "must be a string or null");
    if (typeof r["text"] !== "string" || r["text"].trim().length === 0) throw invalid(i, "text", "must be a non-empty string");
    if (r["durationMs"] !== undefined && (typeof r["durationMs"] !== "number" || r["durationMs"] < 0)) throw invalid(i, "durationMs", "must be a non-negative number");
    if (r["label"] !== undefined) {
      if (typeof r["label"] !== "string" || r["label"].length === 0) throw invalid(i, "label", "must be a non-empty string");
      if (labels.has(r["label"])) throw invalid(i, "label", `duplicate label ${r["label"]}`);
      labels.add(r["label"]);
    }
    const u: ReplayUtterance = { atMs: r["atMs"], lane: r["lane"] as WireLane, speaker: (r["speaker"] as string | null) ?? null, text: r["text"] };
    if (r["label"] !== undefined) u.label = r["label"] as string;
    if (r["durationMs"] !== undefined) u.durationMs = r["durationMs"] as number;
    if (r["expect"] !== undefined) u.expect = r["expect"];
    return u;
  });
  const out: ReplayFixture = { version: 1, title: o["title"], utterances };
  if (o["story"] !== undefined) out.story = o["story"] as string;
  if (o["speakers"] !== undefined) out.speakers = o["speakers"] as ReplayFixture["speakers"];
  if (o["ui"] !== undefined) out.ui = o["ui"];
  return out;
}

export function estimateDurationMs(text: string): number {
  const words = text.split(/\s+/).filter((w) => w.length > 0).length;
  return 250 + 60 * words;
}

export interface ReplayTimers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  now(): number;
}

const realTimers: ReplayTimers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
  now: () => Date.now(),
};

export const REPLAY_SPEEDS: readonly ReplaySpeed[] = [0.5, 1, 2, 4, "instant"] as const;

interface ReplayWaiter {
  target: number;
  resolve: () => void;
}

export class ReplayProvider implements TranscriptionProvider {
  readonly id = "replay" as const;
  readonly label = "Replay";
  readonly isLocal = true;
  readonly lanes: CaptureLaneId[] = ["remote", "me"];
  readonly mode = "push" as const;
  readonly model = null;

  #ctx: ProviderContext | null = null;
  #fixture: ReplayFixture | null = null;
  #name: string | null = null;
  #index = 0;
  #state: ReplayStatus["state"] = "empty";
  #speed: ReplaySpeed = 1;
  #until: number | null = null;
  #playStartMs: number | null = null;
  #timer: unknown = null;
  #timerDueAt = 0; // timers.now() when the pending timer fires
  #remainingMs = 0; // what was left when paused
  #waiters: ReplayWaiter[] = [];
  #onStatus: (() => void) | null = null;
  readonly #timers: ReplayTimers;

  constructor(deps: { timers?: ReplayTimers; onStatus?: () => void } = {}) {
    this.#timers = deps.timers ?? realTimers;
    this.#onStatus = deps.onStatus ?? null;
  }

  async start(ctx: ProviderContext): Promise<void> {
    this.#ctx = ctx;
  }

  transcribe(_segment: Segment): Promise<TranscribeResult> {
    return Promise.reject(new ProviderError("NOT_SEGMENT_PROVIDER", "replay emits drafts itself"));
  }

  async stop(): Promise<void> {
    this.#clearTimer();
    if (this.#state === "playing") this.#setState("paused");
    this.#settleWaiters(true);
  }

  get status(): ReplayStatus {
    return {
      fixture: this.#name,
      state: this.#state,
      index: this.#index,
      total: this.#fixture?.utterances.length ?? 0,
      speed: this.#speed,
      until: this.#until,
    };
  }

  get fixture(): ReplayFixture | null {
    return this.#fixture;
  }

  load(fixture: ReplayFixture, name: string): void {
    this.#clearTimer();
    this.#fixture = fixture;
    this.#name = name;
    this.#index = 0;
    this.#until = null;
    this.#playStartMs = null;
    this.#settleWaiters(true);
    this.#setState(fixture.utterances.length > 0 ? "ready" : "done");
  }

  reset(): void {
    this.#clearTimer();
    this.#index = 0;
    this.#until = null;
    this.#playStartMs = null;
    this.#settleWaiters(true);
    this.#setState(this.#fixture && this.#fixture.utterances.length > 0 ? "ready" : this.#fixture ? "done" : "empty");
  }

  /** Resolves when the last utterance <= until has been emitted (or the fixture ends). */
  play(speed: ReplaySpeed, opts: { until?: number | string } = {}): Promise<void> {
    const fixture = this.#fixture;
    if (!fixture) return Promise.reject(new ProviderError("REPLAY_FIXTURE_INVALID", "no fixture loaded"));
    if (!this.#ctx) return Promise.reject(new ProviderError("REPLAY_FIXTURE_INVALID", "provider not started"));
    let until: number | null = null;
    if (opts.until !== undefined) {
      try {
        until = this.#resolveIndex(opts.until);
      } catch (e) {
        return Promise.reject(e);
      }
    }
    if (!(REPLAY_SPEEDS as readonly unknown[]).includes(speed)) return Promise.reject(new ProviderError("REPLAY_FIXTURE_INVALID", `unknown speed ${String(speed)}`));
    this.#speed = speed;
    this.#until = until;
    this.#clearTimer();
    this.#remainingMs = 0;
    if (this.#playStartMs === null) this.#playStartMs = this.#ctx.clock.nowMs();
    const target = until === null ? fixture.utterances.length - 1 : until;
    if (this.#index > target) {
      // already past the breakpoint: nothing to emit
      this.#setState(this.#index >= fixture.utterances.length ? "done" : "paused");
      return Promise.resolve();
    }
    const done = new Promise<void>((resolve) => this.#waiters.push({ target, resolve }));
    this.#setState("playing");
    if (speed === "instant") this.#runInstant();
    else this.#scheduleNext(0);
    return done;
  }

  /** Emits exactly one utterance and stays paused. */
  step(): void {
    const fixture = this.#fixture;
    if (!fixture || !this.#ctx) return;
    if (this.#index >= fixture.utterances.length) return;
    this.#clearTimer();
    if (this.#playStartMs === null) this.#playStartMs = this.#ctx.clock.nowMs();
    this.#emitAt(this.#index);
    this.#afterEmit("paused");
  }

  /** Advances past `until` without emitting. */
  skip(until: number | string): void {
    const fixture = this.#fixture;
    if (!fixture) throw new ProviderError("REPLAY_FIXTURE_INVALID", "no fixture loaded");
    const target = this.#resolveIndex(until);
    this.#clearTimer();
    if (target + 1 > this.#index) this.#index = target + 1;
    this.#settleWaiters(false);
    this.#setState(this.#index >= fixture.utterances.length ? "done" : "paused");
  }

  pause(): void {
    if (this.#state !== "playing") return;
    if (this.#timer !== null) {
      this.#remainingMs = Math.max(0, this.#timerDueAt - this.#timers.now());
      this.#clearTimer();
    }
    this.#setState("paused");
  }

  /** Continues at the current speed with the breakpoint cleared. */
  resume(): void {
    const fixture = this.#fixture;
    if (!fixture || !this.#ctx) return;
    if (this.#state !== "paused") return;
    if (this.#index >= fixture.utterances.length) {
      this.#setState("done");
      return;
    }
    this.#until = null;
    this.#setState("playing");
    if (this.#speed === "instant") this.#runInstant();
    else this.#scheduleNext(this.#remainingMs);
    this.#remainingMs = 0;
  }

  /* ───── internals ───── */

  #resolveIndex(until: number | string): number {
    const fixture = this.#fixture;
    if (!fixture) throw new ProviderError("REPLAY_FIXTURE_INVALID", "no fixture loaded");
    if (typeof until === "number") {
      if (!Number.isInteger(until) || until < 0 || until >= fixture.utterances.length) throw new ProviderError("REPLAY_FIXTURE_INVALID", `until: index ${until} is out of range`);
      return until;
    }
    const i = fixture.utterances.findIndex((u) => u.label === until);
    if (i < 0) throw new ProviderError("REPLAY_FIXTURE_INVALID", `until: unknown label ${until}`);
    return i;
  }

  #runInstant(): void {
    const fixture = this.#fixture;
    if (!fixture) return;
    const target = this.#until === null ? fixture.utterances.length - 1 : this.#until;
    while (this.#state === "playing" && this.#index <= target && this.#index < fixture.utterances.length) {
      this.#emitAt(this.#index);
      this.#afterEmit("playing");
    }
  }

  /** Timed mode: a setTimeout chain at (atMs − prevAtMs) / speed. `delayOverride` is the remainder after a pause. */
  #scheduleNext(delayOverride: number | null): void {
    const fixture = this.#fixture;
    if (!fixture || this.#state !== "playing") return;
    const i = this.#index;
    const u = fixture.utterances[i];
    if (!u) {
      this.#afterEmit("playing");
      return;
    }
    const speed = typeof this.#speed === "number" ? this.#speed : 1;
    let delay: number;
    if (delayOverride !== null && delayOverride > 0) delay = delayOverride;
    else if (i === 0) delay = 0;
    else {
      const prev = fixture.utterances[i - 1];
      delay = Math.max(0, (u.atMs - (prev?.atMs ?? u.atMs)) / speed);
    }
    this.#timerDueAt = this.#timers.now() + delay;
    this.#timer = this.#timers.setTimeout(() => {
      this.#timer = null;
      if (this.#state !== "playing") return;
      this.#emitAt(i);
      this.#afterEmit("playing");
      if (this.#state === "playing") this.#scheduleNext(null);
    }, delay);
  }

  /** Bookkeeping after an emit: the index moved; settle waiters; land on paused / done / keep playing. */
  #afterEmit(continuing: "playing" | "paused"): void {
    const fixture = this.#fixture;
    if (!fixture) return;
    const total = fixture.utterances.length;
    this.#settleWaiters(false);
    if (this.#index >= total) {
      this.#until = null;
      this.#setState("done");
      return;
    }
    if (this.#until !== null && this.#index > this.#until) {
      this.#until = null;
      this.#setState("paused");
      return;
    }
    if (continuing === "paused") this.#setState("paused");
  }

  #emitAt(i: number): void {
    const fixture = this.#fixture;
    const ctx = this.#ctx;
    if (!fixture || !ctx) return;
    const u = fixture.utterances[i];
    if (!u) return;
    this.#index = i + 1;
    const first = fixture.utterances[0]?.atMs ?? 0;
    const base = this.#playStartMs ?? ctx.clock.nowMs();
    const tStartMs = base + (u.atMs - first);
    const tEndMs = tStartMs + (u.durationMs ?? estimateDurationMs(u.text));
    ctx.emit({
      text: u.text,
      lane: u.lane,
      speaker: u.speaker ?? ctx.speakers.get(u.lane),
      provider: "replay",
      model: null,
      isLocal: true,
      confidence: null,
      tStartMs,
      tEndMs,
    });
    this.#onStatus?.();
  }

  #settleWaiters(all: boolean): void {
    const keep: ReplayWaiter[] = [];
    for (const w of this.#waiters) {
      if (all || this.#index > w.target) w.resolve();
      else keep.push(w);
    }
    this.#waiters = keep;
  }

  #clearTimer(): void {
    if (this.#timer !== null) {
      this.#timers.clearTimeout(this.#timer);
      this.#timer = null;
    }
  }

  #setState(state: ReplayStatus["state"]): void {
    this.#state = state;
    this.#onStatus?.();
  }
}
