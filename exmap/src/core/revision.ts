// exmap/src/core/revision.ts — design §5.2. Step-zero stub: signatures only; the core module implements the bodies.
import type { CanonicalState, CardId, CardRecord, Sha256Fn, Sha256Hex } from "./types.js";

/** = sha256('{"cards":[],"schema":"exmap.revision.v1"}') */
export const GENESIS_REVISION_HASH = "8e97e07bb7573b0849c4f8894c845ce76472f2c9f0eda7a7db37004bc269f675";

/** Live cards (status applied | confirmed), sorted by id, as CanonicalCard. Accepts the state's card map or a card list. */
export function canonicalState(cards: Readonly<Record<CardId, CardRecord>> | readonly CardRecord[]): CanonicalState {
  void cards;
  throw new Error("not implemented: canonicalState");
}

export function computeRevision(cards: Readonly<Record<CardId, CardRecord>> | readonly CardRecord[], sha256: Sha256Fn): Sha256Hex {
  void cards;
  void sha256;
  throw new Error("not implemented: computeRevision");
}
