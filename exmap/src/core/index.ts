// exmap/src/core/index.ts — the public API of the engine (design §5.10). src/core imports nothing from outside itself.
import { apply } from "./apply.js";
import { verifyChain } from "./chain.js";
import { replay } from "./replay.js";
import { computeRevision } from "./revision.js";
import type { ApplyContext, ApplyResult, Command, ExmapEvent, IsoTimestamp, MapState, ReplayResult, Sha256Fn, Sha256Hex, VerifyResult } from "./types.js";

export { canonicalJson, CanonicalError } from "./canonical.js";
export { GENESIS_PREV_HASH, eventHash, chainEvent, verifyChain } from "./chain.js";
export { GENESIS_REVISION_HASH, canonicalState, computeRevision } from "./revision.js";
export { initialState, reduce } from "./reduce.js";
export { replay } from "./replay.js";
export { apply } from "./apply.js";
export { SIGNOFF_CONFIRMATION_TEXT, DOD_OPTIONS, dodReport, isHumanVerified } from "./dod.js";
export { REFUSAL } from "./refusals.js";
export * as select from "./select.js";
export type * from "./types.js";

export interface Engine {
  apply: (state: MapState, command: Command) => ApplyResult;
  replay: (events: readonly ExmapEvent[]) => ReplayResult;
  verifyChain: (events: readonly ExmapEvent[]) => VerifyResult;
  revisionOf: (state: MapState) => Sha256Hex;
}

/** Binds the injected sha256 / clock / id minter to the pure functions above. */
export function createEngine(deps: { sha256: Sha256Fn; now: () => IsoTimestamp; nextId: ApplyContext["nextId"] }): Engine {
  const ctx: ApplyContext = { now: deps.now, nextId: deps.nextId, sha256: deps.sha256 };
  return {
    apply: (state, command) => apply(state, command, ctx),
    replay: (events) => replay(events, deps.sha256),
    verifyChain: (events) => verifyChain(events, deps.sha256),
    revisionOf: (state) => computeRevision(state.cards, deps.sha256),
  };
}
