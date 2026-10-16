// exmap/src/server/ids.ts — id minting (design §8.2). nextId is the one ApplyContext["nextId"] passed to core and the routes.
import { randomUUID } from "node:crypto";
import type { IdPrefix } from "../core/types.js";

export const SESSION_ID_RE = /^ses_[a-z0-9]{6,12}_[a-f0-9]{6}$/;

export function nextId(prefix: IdPrefix): string {
  return `${prefix}_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
}

/** ses_<base36 ms>_<6 hex> */
export function newSessionId(now: number = Date.now()): string {
  return `ses_${now.toString(36)}_${randomUUID().replaceAll("-", "").slice(0, 6)}`;
}

/** Validated on every :id before any filesystem access. */
export function isSessionId(id: string): boolean {
  return SESSION_ID_RE.test(id);
}
