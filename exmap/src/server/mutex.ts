// exmap/src/server/mutex.ts — Mutex (a promise chain; design §9). One write mutex and one classification chain per session.
// run(fn) appends fn to the chain synchronously, so two calls made in order run in that order; a rejected fn never breaks
// the chain for the next one.
const noop = (): void => undefined;

export class Mutex {
  #tail: Promise<void> = Promise.resolve();
  #queued = 0;

  run<T>(fn: () => Promise<T> | T): Promise<T> {
    this.#queued++;
    const result = this.#tail.then(() => fn());
    this.#tail = result.then(noop, noop).finally(() => {
      this.#queued--;
    });
    return result;
  }

  /** Number of runs queued or in progress. */
  get queued(): number {
    return this.#queued;
  }

  /** Resolves once everything queued so far has settled. */
  idle(): Promise<void> {
    return this.#tail;
  }
}
