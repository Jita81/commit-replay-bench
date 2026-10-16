// exmap/src/web/replay/driver.ts — ReplayDriver (window.__exmap.replay) over the audio controller's replay API
// (design §10.9): playUntil(target) plays in instant mode through the target and waits for the post queue to drain;
// skip(target) advances past the target without emitting; playAll() plays the rest; position follows the controller.
import type { ReplaySpeed, ReplayStatus } from "../audio/types.js";

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
}

export class ReplayDriver {
  readonly #controller: ReplayControllerLike;
  readonly #postQueueIdle: () => Promise<void>;
  readonly #settled: (() => Promise<void>) | null;

  constructor(deps: ReplayDriverDeps) {
    this.#controller = deps.controller;
    this.#postQueueIdle = deps.postQueueIdle;
    this.#settled = deps.settled ?? null;
  }

  async playUntil(target: string | number): Promise<void> {
    await this.#controller.playReplay("instant", { until: target });
    await this.#postQueueIdle();
    if (this.#settled) await this.#settled();
  }

  async skip(target: string | number): Promise<void> {
    this.#controller.skipReplay(target);
    await this.#postQueueIdle();
  }

  async playAll(): Promise<void> {
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
