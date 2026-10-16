// exmap/src/core/replay.ts — design §5.3: verifyChain -> initialState(events[0].session_id) -> fold reduce, re-checking
// every revision stamp against computeRevision of the reduced cards. The only module composing chain, revision and reduce.
import { verifyChain } from "./chain.js";
import { initialState, reduce } from "./reduce.js";
import { computeRevision } from "./revision.js";
import type { ExmapEvent, ReplayResult, Sha256Fn } from "./types.js";

/** verifyChain -> initialState -> fold reduce, checking every revision hash. An empty ledger is EMPTY_LEDGER. */
export function replay(events: readonly ExmapEvent[], sha256: Sha256Fn): ReplayResult {
  const first = events[0];
  if (!first) return { ok: false, error: { code: "EMPTY_LEDGER" } };
  const verified = verifyChain(events, sha256);
  if (!verified.ok) return { ok: false, error: verified.error };
  let state = initialState(first.session_id);
  for (const event of events) {
    state = reduce(state, event);
    if (event.type === "proposal.applied" || event.type === "proposal.rejected" || event.type === "undo.applied") {
      const current = state.revisions[state.revisions.length - 1]!;
      const actual = computeRevision(state.cards, sha256);
      if (actual !== event.revision.hash || current.seq !== event.revision.seq) {
        return { ok: false, error: { code: "REVISION_MISMATCH", seq: event.seq, expected: event.revision.hash, actual } };
      }
    }
  }
  return { ok: true, state };
}
