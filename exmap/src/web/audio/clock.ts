// exmap/src/web/audio/clock.ts — the session-relative clock every provider stamps times with (design §7.5):
// nowMs() = max(0, round(Date.now() − Date.parse(session.created_at))).
import type { SessionClock } from "./types.js";

export function createSessionClock(createdAt: string, now: () => number = () => Date.now()): SessionClock {
  const base = Date.parse(createdAt);
  if (Number.isNaN(base)) throw new Error(`createSessionClock: created_at is not an ISO timestamp: ${createdAt}`);
  return {
    nowMs: () => Math.max(0, Math.round(now() - base)),
  };
}

/** A clock whose value a test sets by hand. */
export function fixedClock(initialMs = 0): SessionClock & { set(ms: number): void; advance(ms: number): void } {
  let t = initialMs;
  return {
    nowMs: () => t,
    set: (ms) => {
      t = ms;
    },
    advance: (ms) => {
      t += ms;
    },
  };
}
