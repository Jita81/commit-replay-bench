// exmap/src/core/replay.ts — design §5.3: verifyChain -> initialState(events[0].session_id) -> fold reduce, re-checking
// every revision stamp against computeRevision of the reduced cards. The only module composing chain, revision and reduce.
import { verifyChain } from "./chain.js";
import { initialState, reduce } from "./reduce.js";
import { computeRevision } from "./revision.js";
import type { ExmapEvent, MapState, ReplayError, ReplayResult, Sha256Fn } from "./types.js";

/** verifyChain -> initialState -> fold reduce, checking every revision hash, then that the ledger does not end inside a batch. An empty ledger is EMPTY_LEDGER. */
export function replay(events: readonly ExmapEvent[], sha256: Sha256Fn, opts: { requireComplete?: boolean } = {}): ReplayResult {
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
  const torn = opts.requireComplete === false ? null : incompleteBatch(events, state);
  if (torn) return { ok: false, error: torn };
  return { ok: true, state };
}

/**
 * A chain cut at a line boundary inside a batch (a partial flush, or a hand truncation) verifies, yet leaves a state no
 * completed apply() can leave: a card still proposed, a proposal still pending, a clarifying proposal whose question was
 * never asked, or an active sign-off on a revision that is no longer current (its signoff.invalidated was cut off).
 * Returns the first event of the earliest such batch, so the ledger can be truncated back to the batch boundary.
 */
export function incompleteBatch(events: readonly ExmapEvent[], state: MapState): Extract<ReplayError, { code: "INCOMPLETE_BATCH" }> | null {
  const byId = new Map(events.map((e) => [e.id, e] as const));
  const found: Array<{ eventId: string; why: string }> = [];
  for (const id of state.card_order) {
    const card = state.cards[id];
    if (card?.status === "proposed") found.push({ eventId: card.created.event_id, why: `card ${id} is still proposed` });
  }
  const asked = new Set(Object.values(state.clarifications).map((c) => c.proposal_id));
  for (const id of state.proposal_order) {
    const record = state.proposals[id];
    if (!record) continue;
    if (record.status === "pending") found.push({ eventId: record.made_event_id, why: `proposal ${id} is still pending` });
    else if (record.status === "clarifying" && !asked.has(id)) found.push({ eventId: record.made_event_id, why: `proposal ${id} asks a question that was never recorded` });
  }
  const signoff = state.signoffs[state.signoffs.length - 1];
  const current = state.revisions[state.revisions.length - 1];
  if (signoff?.status === "active" && current && signoff.revision.seq !== current.seq) {
    const by = state.revisions.find((r) => r.seq > signoff.revision.seq);
    if (by?.event_id) found.push({ eventId: by.event_id, why: `sign-off ${signoff.id} is still active on revision ${signoff.revision.seq}, not the current ${current.seq}` });
  }
  let first: { event: ExmapEvent; why: string } | null = null;
  for (const f of found) {
    const event = byId.get(f.eventId);
    const start = event ? byId.get(event.batch_id) ?? event : undefined;
    if (start && (first === null || start.seq < first.event.seq)) first = { event: start, why: f.why };
  }
  if (first === null) return null;
  return {
    code: "INCOMPLETE_BATCH", seq: first.event.seq, event_id: first.event.id,
    detail: `the ledger ends inside an unfinished batch that starts at seq ${first.event.seq} (event ${first.event.id}): ${first.why}`,
  };
}
