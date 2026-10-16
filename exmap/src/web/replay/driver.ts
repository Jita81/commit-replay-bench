// exmap/src/web/replay/driver.ts — ReplayDriver (window.__exmap.replay) over the audio controller's replay API
// (design §10.9): playUntil(target) plays in instant mode through the target and waits for the post queue to drain;
// skip(target) advances past the target without emitting; playAll() plays the rest; position follows the controller.
// Additive: an optional `ready` promise (the fixture is loaded) and an optional `settled` step (the ledger, as this page
// has reduced it, holds every posted utterance with its classification record), so a test that acts after playUntil
// sees the outcome of every utterance it played. RecordingSink + ledgerSettled build that step.
import { select } from "../../core/index.js";
import type { MapState } from "../../core/types.js";
import type { PostOutcome, ReplaySpeed, ReplayStatus, UtteranceSink, UtteranceWire } from "../audio/types.js";

/** The slice of the audio controller the driver needs (§7.7). */
export interface ReplayControllerLike {
  playReplay(speed: ReplaySpeed, opts?: { until?: number | string }): Promise<void>;
  skipReplay(until: number | string): void;
  getState(): { replay: ReplayStatus };
}

export interface ReplayDriverDeps {
  controller: ReplayControllerLike;
  /** controller.idle(): the post queue is empty (every emitted utterance has been posted). */
  postQueueIdle: () => Promise<void>;
  /** Optional: resolves once the ledger has classified every recorded utterance (the web wires the SessionStore here). */
  settled?: () => Promise<void>;
  /** Optional: resolves once the replay fixture is loaded into the controller; every call waits for it first. */
  ready?: Promise<void>;
}

export class ReplayDriver {
  readonly #controller: ReplayControllerLike;
  readonly #postQueueIdle: () => Promise<void>;
  readonly #settled: (() => Promise<void>) | null;
  readonly #ready: Promise<void>;

  constructor(deps: ReplayDriverDeps) {
    this.#controller = deps.controller;
    this.#postQueueIdle = deps.postQueueIdle;
    this.#settled = deps.settled ?? null;
    this.#ready = deps.ready ?? Promise.resolve();
  }

  async playUntil(target: string | number): Promise<void> {
    await this.#ready;
    await this.#controller.playReplay("instant", { until: target });
    await this.#postQueueIdle();
    if (this.#settled) await this.#settled();
  }

  async skip(target: string | number): Promise<void> {
    await this.#ready;
    this.#controller.skipReplay(target);
    await this.#postQueueIdle();
  }

  async playAll(): Promise<void> {
    await this.#ready;
    await this.#controller.playReplay("instant");
    await this.#postQueueIdle();
    if (this.#settled) await this.#settled();
  }

  /** Utterances emitted so far (the controller's replay index). */
  get position(): number {
    return this.#controller.getState().replay.index;
  }

  get status(): ReplayStatus {
    return this.#controller.getState().replay;
  }
}

/** Wraps the audio module's sink and remembers the id of every utterance the server accepted (201, or a 409 duplicate). */
export class RecordingSink implements UtteranceSink {
  readonly #inner: UtteranceSink;
  readonly posted: string[] = [];
  readonly #seen = new Set<string>();

  constructor(inner: UtteranceSink) {
    this.#inner = inner;
  }

  async post(u: UtteranceWire): Promise<PostOutcome> {
    const outcome = await this.#inner.post(u);
    if (outcome.ok && !this.#seen.has(u.id)) {
      this.#seen.add(u.id);
      this.posted.push(u.id);
    }
    return outcome;
  }
}

/** True when every posted id is in the reduced ledger and carries at least one classification record. */
export function ledgerHolds(state: MapState, posted: readonly string[]): boolean {
  if (posted.length === 0) return true;
  const recorded = new Set(state.utterances.map((u) => u.id));
  for (const id of posted) {
    if (!recorded.has(id)) return false;
    if (select.classificationsOf(state, id).length === 0) return false;
  }
  return true;
}

export interface SettleSource {
  getState(): MapState;
  subscribe(fn: () => void): () => void;
  readonly terminal?: boolean;
}

/**
 * A `settled` step for the driver: resolves when the page's reduced ledger holds every utterance the sink posted with
 * its classification record, when the store stopped (a chain error is shown, nothing more will arrive), or after
 * `timeoutMs` (the test's own expectations then fail with what is on screen).
 */
export function ledgerSettled(source: SettleSource, sink: { readonly posted: readonly string[] }, timeoutMs = 60_000): () => Promise<void> {
  return () =>
    new Promise<void>((resolve) => {
      const posted = [...sink.posted];
      const done = () => source.terminal === true || ledgerHolds(source.getState(), posted);
      if (done()) {
        resolve();
        return;
      }
      const timer = setTimeout(finish, timeoutMs);
      const unsubscribe = source.subscribe(() => {
        if (done()) finish();
      });
      function finish() {
        clearTimeout(timer);
        unsubscribe();
        resolve();
      }
    });
}
