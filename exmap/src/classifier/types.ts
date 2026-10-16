// exmap/src/classifier/types.ts — re-exports the §4 §11 types and defines ClassifierError (design §6.1–6.2).
// This package imports only types from src/core/types.ts and nothing from src/server.
export type {
  CardDraft, CardIndexEntry, Classifier, ClassifierAmendment, ClassifierCardPatch, ClassifierClarification,
  ClassifierInput, ClassifierIntent, ClassifierOperation, ClassifierProposal, ClassifierProvenance, ClassifierProviderId,
  ClassifierResolves, ClassifierUtterance, HeardIntent, Intent, LastProposalRef, PendingClarification,
} from "../core/types.js";

export type ClassifierErrorCode = "E_CLASSIFIER_UNKNOWN_PROVIDER" | "E_CLASSIFIER_INPUT_INVALID" | "E_PROPOSAL_INVARIANT";

/** A programming error, never a classification outcome; provider failures of the claude provider become provenance instead. */
export class ClassifierError extends Error {
  readonly code: ClassifierErrorCode;
  constructor(code: ClassifierErrorCode, message?: string) {
    super(message ?? code);
    this.name = "ClassifierError";
    this.code = code;
  }
}
