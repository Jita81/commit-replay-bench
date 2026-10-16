// exmap/src/core/select.ts — design §5.10 selectors. Step-zero stubs: signatures only; the core module implements the bodies.
import type {
  Card, CardId, CardKind, Clarification, ClassificationRecord, Counts, ExampleCard, ExportOptions, MapState,
  ProposalId, ProposalRecord, ProposalStatus, QuestionCard, Revision, Signoff, StoryCard, UtteranceId,
} from "./types.js";

export type StatusLabel = "applied" | "confirmed" | "removed" | "interpretation rejected" | "undone" | "superseded";

function notImplemented(name: string): never {
  throw new Error(`not implemented: ${name}`);
}

/** Live cards (status applied | confirmed) in card_order. */
export function liveCards(state: MapState): Card[] { void state; return notImplemented("select.liveCards"); }
export function cardsByKind<K extends CardKind>(state: MapState, kind: K): Extract<Card, { kind: K }>[] { void state; void kind; return notImplemented("select.cardsByKind"); }
export function story(state: MapState): StoryCard | null { void state; return notImplemented("select.story"); }
export function examplesOf(state: MapState, rule_id: CardId): ExampleCard[] { void state; void rule_id; return notImplemented("select.examplesOf"); }
export function questionsAbout(state: MapState, card_id: CardId): QuestionCard[] { void state; void card_id; return notImplemented("select.questionsAbout"); }
export function currentRevision(state: MapState): Revision { void state; return notImplemented("select.currentRevision"); }
/** Every revision without its snapshot. */
export function revisions(state: MapState): Omit<Revision, "snapshot">[] { void state; return notImplemented("select.revisions"); }
/** Walks back `steps` distinct steps (§5.9); the seq of the revision just before the earliest, or null. */
export function undoTarget(state: MapState, steps: number): number | null { void state; void steps; return notImplemented("select.undoTarget"); }
export function activeSignoff(state: MapState): Signoff | null { void state; return notImplemented("select.activeSignoff"); }
export function lastSignoff(state: MapState): Signoff | null { void state; return notImplemented("select.lastSignoff"); }
export function openClarifications(state: MapState): Clarification[] { void state; return notImplemented("select.openClarifications"); }
export function pendingProposals(state: MapState): ProposalRecord[] { void state; return notImplemented("select.pendingProposals"); }
/** Defaults: aiOnly true (provider != human and non-empty source_utterance_ids), statuses ["applied"]. */
export function lastAppliedProposal(state: MapState, opts?: { aiOnly?: boolean; statuses?: ProposalStatus[] }): ProposalRecord | null { void state; void opts; return notImplemented("select.lastAppliedProposal"); }
/** Exactly the interpretation.reject preconditions of §5.4. */
export function isRejectable(state: MapState, proposal_id: ProposalId): boolean { void state; void proposal_id; return notImplemented("select.isRejectable"); }
/** The DoD check-3 list. */
export function unreviewedActs(state: MapState): ProposalRecord[] { void state; return notImplemented("select.unreviewedActs"); }
export function classificationsOf(state: MapState, utterance_id: UtteranceId): ClassificationRecord[] { void state; void utterance_id; return notImplemented("select.classificationsOf"); }
/** Consumers never print bare "rejected". */
export function statusLabel(card: Card): StatusLabel { void card; return notImplemented("select.statusLabel"); }
export function examplesNeedingReview(state: MapState): ExampleCard[] { void state; return notImplemented("select.examplesNeedingReview"); }
export function openQuestions(state: MapState): QuestionCard[] { void state; return notImplemented("select.openQuestions"); }
/** The current export options or null. */
export function exportOptions(state: MapState): ExportOptions | null { void state; return notImplemented("select.exportOptions"); }
/** Every number the UI shows comes from here. */
export function counts(state: MapState): Counts { void state; return notImplemented("select.counts"); }
