// exmap/src/core/select.ts — design §5.10 selectors. Every number the UI shows comes from counts(state); the bridge's
// flags (lastAppliedProposal, isRejectable, undoTarget) are the same functions apply() uses, so they cannot drift.
import { isLive, rejectability } from "./effects.js";
import type {
  Card, CardId, CardKind, Clarification, ClassificationRecord, Counts, ExampleCard, ExportOptions, MapState, OperationKind,
  ProposalId, ProposalRecord, ProposalStatus, QuestionCard, Revision, Signoff, StoryCard, UtteranceId,
} from "./types.js";

export type StatusLabel = "applied" | "confirmed" | "removed" | "interpretation rejected" | "undone" | "superseded";

/** The acts a person reviews per proposal rather than per card (DoD check 3). */
export const ACT_KINDS: readonly OperationKind[] = ["card.remove", "undo", "interpretation.reject"];

function cardsInOrder(state: MapState): Card[] {
  const out: Card[] = [];
  for (const id of state.card_order) {
    const card = state.cards[id];
    if (card) out.push(card);
  }
  return out;
}

/** Live cards (status applied | confirmed) in card_order. */
export function liveCards(state: MapState): Card[] {
  return cardsInOrder(state).filter(isLive);
}

export function cardsByKind<K extends CardKind>(state: MapState, kind: K): Extract<Card, { kind: K }>[] {
  return liveCards(state).filter((c): c is Extract<Card, { kind: K }> => c.kind === kind);
}

export function story(state: MapState): StoryCard | null {
  return cardsByKind(state, "story")[0] ?? null;
}

export function examplesOf(state: MapState, rule_id: CardId): ExampleCard[] {
  return cardsByKind(state, "example").filter((e) => e.rule_id === rule_id);
}

export function questionsAbout(state: MapState, card_id: CardId): QuestionCard[] {
  return cardsByKind(state, "question").filter((q) => q.about_card_id === card_id);
}

export function currentRevision(state: MapState): Revision {
  const current = state.revisions[state.revisions.length - 1];
  if (!current) throw new Error("state has no revisions; initialState() always provides genesis");
  return current;
}

/** Every revision without its snapshot. */
export function revisions(state: MapState): Omit<Revision, "snapshot">[] {
  return state.revisions.map(({ snapshot: _snapshot, ...rest }) => rest);
}

/** Walks back `steps` distinct steps (§5.9: a step = consecutive revisions sharing a batch_id); the seq of the revision just before the earliest, or null. */
export function undoTarget(state: MapState, steps: number): number | null {
  if (!Number.isInteger(steps) || steps < 1) return null;
  let i = state.revisions.length - 1;
  for (let s = 0; s < steps; s++) {
    if (i < 1) return null;
    const batch = state.revisions[i]!.batch_id;
    while (i >= 1 && state.revisions[i]!.batch_id === batch) i--;
  }
  return state.revisions[i]!.seq;
}

export function lastSignoff(state: MapState): Signoff | null {
  return state.signoffs[state.signoffs.length - 1] ?? null;
}

export function activeSignoff(state: MapState): Signoff | null {
  const last = lastSignoff(state);
  return last && last.status === "active" ? last : null;
}

export function openClarifications(state: MapState): Clarification[] {
  const out: Clarification[] = [];
  for (const id of state.clarification_order) {
    const c = state.clarifications[id];
    if (c && c.status === "open") out.push(c);
  }
  return out;
}

function proposalsInOrder(state: MapState): ProposalRecord[] {
  const out: ProposalRecord[] = [];
  for (const id of state.proposal_order) {
    const p = state.proposals[id];
    if (p) out.push(p);
  }
  return out;
}

export function pendingProposals(state: MapState): ProposalRecord[] {
  return proposalsInOrder(state).filter((p) => p.status === "pending");
}

/** Defaults: aiOnly true (provider != human and non-empty source_utterance_ids), statuses ["applied"]. */
export function lastAppliedProposal(state: MapState, opts?: { aiOnly?: boolean; statuses?: ProposalStatus[] }): ProposalRecord | null {
  const aiOnly = opts?.aiOnly ?? true;
  const statuses = opts?.statuses ?? ["applied"];
  const all = proposalsInOrder(state);
  for (let i = all.length - 1; i >= 0; i--) {
    const record = all[i]!;
    if (!statuses.includes(record.status)) continue;
    if (aiOnly && (record.proposal.classifier.provider === "human" || record.proposal.source_utterance_ids.length === 0)) continue;
    return record;
  }
  return null;
}

/** Exactly the interpretation.reject preconditions of §5.4. */
export function isRejectable(state: MapState, proposal_id: ProposalId): boolean {
  return rejectability(state, proposal_id).ok;
}

/** The DoD check-3 list: applied AI acts (actor null; card.remove / undo / interpretation.reject) not yet reviewed. */
export function unreviewedActs(state: MapState): ProposalRecord[] {
  return proposalsInOrder(state).filter(
    (p) => p.status === "applied" && p.proposal.classifier.actor === null && p.proposal.operation !== null && ACT_KINDS.includes(p.proposal.operation.kind),
  );
}

export function classificationsOf(state: MapState, utterance_id: UtteranceId): ClassificationRecord[] {
  return state.classifications.filter((c) => c.utterance_id === utterance_id);
}

/** Consumers never print bare "rejected". A transient `proposed` card (between made and applied) labels as "applied". */
export function statusLabel(card: Card): StatusLabel {
  switch (card.status) {
    case "confirmed":
      return "confirmed";
    case "superseded":
      return "superseded";
    case "rejected":
      switch (card.rejection?.kind) {
        case "interpretation_rejected":
          return "interpretation rejected";
        case "undone":
          return "undone";
        default:
          return "removed";
      }
    case "applied":
    case "proposed":
      return "applied";
  }
}

export function examplesNeedingReview(state: MapState): ExampleCard[] {
  return cardsByKind(state, "example").filter((e) => e.needs_review !== null);
}

/** Live questions without a recorded answer (an accepted question is still open: it stays unanswered). */
export function openQuestions(state: MapState): QuestionCard[] {
  return cardsByKind(state, "question").filter((q) => q.answer === null);
}

/** The current export options or null. */
export function exportOptions(state: MapState): ExportOptions | null {
  return state.export_options[state.export_options.length - 1] ?? null;
}

/** Every number the UI shows comes from here. */
export function counts(state: MapState): Counts {
  const classified = new Set(state.classifications.map((c) => c.utterance_id));
  const cited = new Set<UtteranceId>();
  for (const record of Object.values(state.proposals)) for (const u of record.proposal.source_utterance_ids) cited.add(u);
  const live = liveCards(state);
  const by_kind: Record<CardKind, number> = { story: 0, rule: 0, example: 0, question: 0 };
  for (const card of live) by_kind[card.kind] += 1;
  const questions = cardsByKind(state, "question");
  return {
    utterances: state.utterances.length,
    classified: state.utterances.filter((u) => classified.has(u.id)).length,
    actionable: state.utterances.filter((u) => cited.has(u.id)).length,
    classifier_errors: state.classifications.filter((c) => c.error !== null).length,
    fallbacks: state.classifications.filter((c) => c.classifier.fallback_from !== null).length,
    cards_live: live.length,
    by_kind,
    needs_review: examplesNeedingReview(state).length,
    open_questions: questions.filter((q) => q.answer === null).length,
    accepted_questions: questions.filter((q) => q.accepted_outstanding !== null).length,
    open_clarifications: openClarifications(state).length,
    unreviewed_acts: unreviewedActs(state).length,
    revision_seq: currentRevision(state).seq,
    events: state.head.seq,
  };
}
