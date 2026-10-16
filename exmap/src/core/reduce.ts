// exmap/src/core/reduce.ts — design §5.3. The reducer is pure, total over ExmapEvent, never mutates its input and never
// hashes: it sets `after`, bookkeeps history and derives bookkeeping fields; all judgement lives in apply().
// It imports neither chain.ts nor revision.ts.
import { applyEffects, distinct, primaryTargets, snapshotOf } from "./effects.js";
import type {
  Clarification, ClarificationAnswer, ExmapEvent, MapState, ProposalId, ProposalRecord, Revision, RevisionCause,
} from "./types.js";

/** The hash of the empty canonical state; equals revision.ts#GENESIS_REVISION_HASH (asserted by a unit test). */
const GENESIS_HASH = "8e97e07bb7573b0849c4f8894c845ce76472f2c9f0eda7a7db37004bc269f675";

export function initialState(session_id: string): MapState {
  const genesis: Revision = {
    seq: 0, hash: GENESIS_HASH, event_id: null, at: null, cause: "genesis", batch_id: null, source_utterance_ids: [], snapshot: {},
  };
  return {
    schema: "exmap.state.v1",
    session_id,
    head: { seq: 0, hash: "", event_id: null },
    utterances: [],
    classifications: [],
    cards: {},
    card_order: [],
    proposals: {},
    proposal_order: [],
    clarifications: {},
    clarification_order: [],
    revisions: [genesis],
    signoffs: [],
    export_options: [],
  };
}

function patchProposal(next: MapState, id: ProposalId, patch: Partial<ProposalRecord>): void {
  const existing = next.proposals[id];
  if (!existing) return; // totality: an unknown proposal is a no-op for that record
  next.proposals = { ...next.proposals, [id]: { ...existing, ...patch } };
}

function patchClarification(next: MapState, id: string, patch: Partial<Clarification>): Clarification | null {
  const existing = next.clarifications[id];
  if (!existing) return null;
  const updated = { ...existing, ...patch };
  next.clarifications = { ...next.clarifications, [id]: updated };
  return updated;
}

function pushRevision(next: MapState, event: ExmapEvent & { revision: { seq: number; hash: string } }, cause: RevisionCause, proposalId: ProposalId): void {
  const last = next.revisions[next.revisions.length - 1];
  const revision: Revision = {
    seq: (last ? last.seq : 0) + 1,
    hash: event.revision.hash,
    event_id: event.id,
    at: event.at,
    cause,
    batch_id: event.batch_id,
    source_utterance_ids: [...(next.proposals[proposalId]?.proposal.source_utterance_ids ?? [])],
    snapshot: snapshotOf(next.cards),
  };
  next.revisions = [...next.revisions, revision];
}

function withEffects(next: MapState, event: ExmapEvent & { effects: MapState["proposals"][string]["effects"] }): void {
  const applied = applyEffects(next.cards, next.card_order, event.effects, event.id);
  next.cards = applied.cards;
  next.card_order = applied.card_order;
}

function textAnswerOf(clarification: Clarification): ClarificationAnswer | null {
  const last = clarification.text_answers[clarification.text_answers.length - 1];
  return last ? { kind: "text", text: last.text, utterance_id: last.utterance_id } : null;
}

/** Pure, total over ExmapEvent, never mutates its input, never hashes. */
export function reduce(state: MapState, event: ExmapEvent): MapState {
  const next: MapState = { ...state, head: { seq: event.seq, hash: event.hash, event_id: event.id } };
  switch (event.type) {
    case "utterance.recorded":
      next.utterances = [...state.utterances, event.utterance];
      break;
    case "utterance.classified":
      next.classifications = [
        ...state.classifications,
        {
          utterance_id: event.utterance_id, event_id: event.id, intent: event.intent, heard_intent: event.heard_intent,
          classifier: event.classifier, confidence: event.confidence, rationale: event.rationale, proposal_ids: event.proposal_ids,
          refused: event.refused, error: event.error,
        },
      ];
      break;
    case "proposal.made": {
      const proposal = event.proposal;
      next.proposals = {
        ...state.proposals,
        [proposal.id]: {
          proposal, status: proposal.needs_clarification ? "clarifying" : "pending", made_event_id: event.id,
          outcome_event_id: null, effects: [], affected_card_ids: [],
        },
      };
      next.proposal_order = state.proposal_order.includes(proposal.id) ? state.proposal_order : [...state.proposal_order, proposal.id];
      withEffects(next, event);
      if (proposal.resolves_clarification_id !== null) {
        const clarification = next.clarifications[proposal.resolves_clarification_id];
        if (clarification) {
          patchClarification(next, clarification.id, {
            status: "answered",
            resolved_by_proposal_id: proposal.id,
            answered_event_id: clarification.answered_event_id ?? event.id,
            answer: clarification.answer ?? textAnswerOf(clarification),
          });
          patchProposal(next, clarification.proposal_id, { status: "answered" });
        }
      }
      break;
    }
    case "proposal.applied":
      withEffects(next, event);
      patchProposal(next, event.proposal_id, {
        status: "applied", outcome_event_id: event.id, effects: event.effects, affected_card_ids: primaryTargets(event.operation, event.effects),
      });
      pushRevision(next, event, "proposal.applied", event.proposal_id);
      break;
    case "proposal.rejected":
      withEffects(next, event);
      patchProposal(next, event.rejected_proposal_id, { status: "rejected" });
      patchProposal(next, event.proposal_id, {
        status: "applied", outcome_event_id: event.id, effects: event.effects, affected_card_ids: distinct(event.effects.map((e) => e.card_id)),
      });
      pushRevision(next, event, "proposal.rejected", event.proposal_id);
      break;
    case "proposal.confirmed":
      withEffects(next, event);
      patchProposal(next, event.proposal_id, {
        status: "applied", outcome_event_id: event.id, effects: event.effects, affected_card_ids: [...event.card_ids],
      });
      for (const id of event.confirms_proposal_ids) patchProposal(next, id, { status: "confirmed" });
      break;
    case "undo.applied":
      withEffects(next, event);
      patchProposal(next, event.proposal_id, {
        status: "applied", outcome_event_id: event.id, effects: event.effects, affected_card_ids: distinct(event.effects.map((e) => e.card_id)),
      });
      pushRevision(next, event, "undo.applied", event.proposal_id);
      break;
    case "clarification.asked":
      next.clarifications = {
        ...state.clarifications,
        [event.clarification_id]: {
          id: event.clarification_id, proposal_id: event.proposal_id, question: event.question, candidates: event.candidates,
          template: event.template, pending_operation: event.pending_operation, status: "open", asked_event_id: event.id,
          text_answers: [], answer: null, answered_event_id: null, resolved_by_proposal_id: null,
        },
      };
      next.clarification_order = state.clarification_order.includes(event.clarification_id)
        ? state.clarification_order
        : [...state.clarification_order, event.clarification_id];
      patchProposal(next, event.proposal_id, { outcome_event_id: event.id });
      break;
    case "clarification.answered": {
      const clarification = state.clarifications[event.clarification_id];
      if (!clarification) break;
      const answer = event.answer;
      if (answer.kind === "text") {
        patchClarification(next, clarification.id, {
          text_answers: [...clarification.text_answers, { text: answer.text, utterance_id: answer.utterance_id, actor: event.actor, event_id: event.id }],
        });
      } else if (answer.kind === "dismiss") {
        patchClarification(next, clarification.id, { status: "dismissed", answer, answered_event_id: event.id });
        patchProposal(next, clarification.proposal_id, { status: "dismissed" });
      } else {
        patchClarification(next, clarification.id, {
          status: "answered", answer, answered_event_id: event.id, resolved_by_proposal_id: event.resolved_by_proposal_id,
        });
        patchProposal(next, clarification.proposal_id, { status: "answered" });
      }
      break;
    }
    case "question.accepted_outstanding":
      withEffects(next, event);
      break;
    case "signoff.recorded":
      next.signoffs = [...state.signoffs, { ...event.signoff, event_id: event.id, at: event.at, status: "active", invalidated: null }];
      break;
    case "signoff.invalidated":
      next.signoffs = state.signoffs.map((s) =>
        s.id === event.signoff_id
          ? { ...s, status: "invalidated" as const, invalidated: { event_id: event.id, by_event_id: event.by_event_id, to_revision: event.to_revision } }
          : s,
      );
      break;
    case "export.options_set":
      next.export_options = [...state.export_options, event.options];
      break;
  }
  return next;
}
