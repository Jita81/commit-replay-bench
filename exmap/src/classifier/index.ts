// exmap/src/classifier/index.ts — createClassifier(), selectProvider(), re-exports (design §6.2).
// selectProvider() reads the environment; createClassifier() builds the chosen provider (design §6.2).
import type { Classifier, ClassifierProviderId } from "../core/types.js";
import type { ModelClient } from "./claude/client.js";
import { createClaudeClassifier } from "./claude/claude-provider.js";
import { createRulesClassifier } from "./rules-v1.js";
import { ClassifierError } from "./types.js";

export * from "./constants.js";
export { ClassifierError };
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
export type { ModelClient, CreateResult } from "./claude/client.js";
export { createRulesClassifier, classifyRules } from "./rules-v1.js";
export { createClaudeClassifier, FORMAT } from "./claude/claude-provider.js";
export { createAnthropicClient } from "./claude/client.js";
export { FROZEN_SYSTEM } from "./claude/system-prompt.js";
export { renderUserMessage } from "./claude/user-message.js";
export { validateModelProposal } from "./claude/validate.js";

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
  const raw = env["EXMAP_CLASSIFIER"];
  const value = raw === undefined ? "" : raw.trim().toLowerCase();
  if (value === "rules.v1" || value === "rules") return "rules.v1";
  if (value === "claude") return "claude";
  if (value !== "") {
    throw new ClassifierError("E_CLASSIFIER_UNKNOWN_PROVIDER", `EXMAP_CLASSIFIER=${JSON.stringify(raw)} is not a classifier provider; allowed values: rules.v1, rules, claude`);
  }
  const key = env["ANTHROPIC_API_KEY"] ?? "";
  const token = env["ANTHROPIC_AUTH_TOKEN"] ?? "";
  return key.trim() !== "" || token.trim() !== "" ? "claude" : "rules.v1";
}

/** createRulesClassifier() or createClaudeClassifier({ client, rules: createRulesClassifier(), onError }) per selectProvider(env). */
export function createClassifier(opts: CreateClassifierOptions = {}): Classifier {
  const provider = selectProvider(opts.env ?? process.env);
  const rules = createRulesClassifier();
  if (provider === "rules.v1") return rules;
  return createClaudeClassifier({ rules, ...(opts.client ? { client: opts.client } : {}), ...(opts.onError ? { onError: opts.onError } : {}) });
}
