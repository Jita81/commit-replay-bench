// exmap/src/classifier/index.ts — createClassifier(), selectProvider(), re-exports (design §6.2).
// Step-zero stubs: the two factories throw; the re-exports are real.
import type { Classifier, ClassifierProviderId } from "../core/types.js";
import type { ModelClient } from "./claude/client.js";

export * from "./constants.js";
export { ClassifierError } from "./types.js";
export type { ClassifierErrorCode } from "./types.js";
export type {
  CardDraft, CardIndexEntry, Classifier, ClassifierAmendment, ClassifierCardPatch, ClassifierClarification,
  ClassifierInput, ClassifierIntent, ClassifierOperation, ClassifierProposal, ClassifierProvenance, ClassifierProviderId,
  ClassifierResolves, ClassifierUtterance, HeardIntent, Intent, LastProposalRef, PendingClarification,
} from "./types.js";
export {
  CHOICE, IntentSchema, ClassifierIntentSchema, CardDraftSchema, CardPatchSchema, AmendmentSchema, OperationSchema,
  ClarificationSchema, ResolvesSchema, ModelProposalSchema, ProposalSchema, ProvenanceSchema, ClassifierInputSchema,
  assertProposalInvariants, draftsOf,
} from "./schema.js";
export type { ModelClient } from "./claude/client.js";

export interface ClassifierErrorEvent {
  code: string;
  message: string;
}

export interface CreateClassifierOptions {
  env?: NodeJS.ProcessEnv;
  client?: ModelClient;
  onError?: (e: ClassifierErrorEvent) => void;
}

/**
 * EXMAP_CLASSIFIER "rules.v1" | "rules" -> rules.v1 (explicit off wins); "claude" -> claude; any other value ->
 * ClassifierError("E_CLASSIFIER_UNKNOWN_PROVIDER"); unset -> claude iff ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is non-empty.
 */
export function selectProvider(env: NodeJS.ProcessEnv): ClassifierProviderId {
  void env;
  throw new Error("not implemented: selectProvider");
}

/** createRulesClassifier() or createClaudeClassifier({ client, rules: createRulesClassifier(), onError }) per selectProvider(env). */
export function createClassifier(opts: CreateClassifierOptions = {}): Classifier {
  void opts;
  throw new Error("not implemented: createClassifier");
}
