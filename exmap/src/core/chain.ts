// exmap/src/core/chain.ts — design §5.1. The hash chain: every event's `hash` is sha256(canonicalJson(event sans hash)),
// `prev_hash` is the previous event's hash ("" at genesis). verifyChain proves a ledger unbroken; it never repairs.
import { canonicalJson } from "./canonical.js";
import type { ChainErrorCode, DistributiveOmit, EventBody, ExmapEvent, Sha256Fn, Sha256Hex, VerifyResult } from "./types.js";

export const GENESIS_PREV_HASH = "";

/** sha256(canonicalJson(body)); body includes prev_hash, seq, at, session_id, batch_id. A stray `hash` key is ignored. */
export function eventHash(body: EventBody, sha256: Sha256Fn): Sha256Hex {
  const { hash: _ignored, ...rest } = body as EventBody & { hash?: unknown };
  return sha256(canonicalJson(rest));
}

export function chainEvent(
  prev: { seq: number; hash: Sha256Hex | "" },
  body: DistributiveOmit<EventBody, "prev_hash" | "seq">,
  sha256: Sha256Fn,
): ExmapEvent {
  const full = { ...body, prev_hash: prev.hash, seq: prev.seq + 1 } as unknown as EventBody;
  return { ...full, hash: eventHash(full, sha256) } as ExmapEvent;
}

function failure(code: ChainErrorCode, event: ExmapEvent, detail: string): VerifyResult {
  return { ok: false, error: { code, seq: event.seq, event_id: event.id, detail } };
}

/**
 * Walks from prev = "", seq = 0: seq === prev + 1 (SEQ_MISMATCH), prev_hash === prev (PREV_HASH_MISMATCH),
 * session_id === events[0].session_id (SESSION_MISMATCH), recomputed hash === hash (HASH_MISMATCH). The first failure is
 * returned with the failing event's own `seq` and `id`; `detail` names its position. An empty list is ok with head "".
 */
export function verifyChain(events: readonly ExmapEvent[], sha256: Sha256Fn): VerifyResult {
  let prev: Sha256Hex | "" = GENESIS_PREV_HASH;
  let seq = 0;
  const session = events[0]?.session_id;
  for (let i = 0; i < events.length; i++) {
    const event = events[i]!;
    const position = i + 1;
    if (event.seq !== seq + 1) {
      return failure("SEQ_MISMATCH", event, `event ${event.id} at position ${position} carries seq ${event.seq}; expected ${seq + 1}`);
    }
    if (event.prev_hash !== prev) {
      return failure("PREV_HASH_MISMATCH", event, `event ${event.id} (seq ${event.seq}) names prev_hash ${short(event.prev_hash)}; the previous event's hash is ${short(prev)}`);
    }
    if (event.session_id !== session) {
      return failure("SESSION_MISMATCH", event, `event ${event.id} (seq ${event.seq}) belongs to session ${event.session_id}, not ${session}`);
    }
    const { hash, ...body } = event;
    const actual = eventHash(body as EventBody, sha256);
    if (actual !== hash) {
      return failure("HASH_MISMATCH", event, `event ${event.id} (seq ${event.seq}) hashes to ${short(actual)}, not the recorded ${short(hash)}`);
    }
    prev = hash;
    seq = event.seq;
  }
  return { ok: true, count: events.length, head: prev };
}

function short(hash: string): string {
  return hash === "" ? '""' : hash.slice(0, 12) + "…";
}
