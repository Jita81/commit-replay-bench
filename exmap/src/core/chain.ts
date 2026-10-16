// exmap/src/core/chain.ts — design §5.1. Step-zero stub: signatures only; the core module implements the bodies.
import type { DistributiveOmit, EventBody, ExmapEvent, Sha256Fn, Sha256Hex, VerifyResult } from "./types.js";

export const GENESIS_PREV_HASH = "";

/** sha256(canonicalJson(body)); body includes prev_hash, seq, at, session_id, batch_id. */
export function eventHash(body: EventBody, sha256: Sha256Fn): Sha256Hex {
  void body;
  void sha256;
  throw new Error("not implemented: eventHash");
}

export function chainEvent(
  prev: { seq: number; hash: Sha256Hex | "" },
  body: DistributiveOmit<EventBody, "prev_hash" | "seq">,
  sha256: Sha256Fn,
): ExmapEvent {
  void prev;
  void body;
  void sha256;
  throw new Error("not implemented: chainEvent");
}

export function verifyChain(events: readonly ExmapEvent[], sha256: Sha256Fn): VerifyResult {
  void events;
  void sha256;
  throw new Error("not implemented: verifyChain");
}
