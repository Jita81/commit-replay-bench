// exmap/src/classifier/schema.ts — zod mirrors of the §4 §11 types (design §6.1). The schemas are real;
// assertProposalInvariants() and draftsOf() are step-zero stubs the classifier module implements.
// ModelProposalSchema is what the model fills: no optional(), no min/max (the SDK's grammar transform drops
// enum/const/minimum/maximum into descriptions, so enums are spelled out in the system prompt and an off-enum value
// fails zod client-side). ProposalSchema extends it with confidence in [0,1], heard_intent, classifier, source_utterance_ids.
import { z } from "zod";
import type { CardDraft, ClassifierInput, ClassifierProposal } from "../core/types.js";

/** The sentinel for a target still to be chosen (choose_target clarifications). */
export const CHOICE = "$choice";

export const IntentSchema = z.enum(["add", "amend", "remove", "replace", "clarify", "reject", "confirm", "undo"]);
export const ClassifierIntentSchema = z.enum([...IntentSchema.options, "none"]);
export const CardKindSchema = z.enum(["story", "rule", "example", "question"]);
export const CardStatusSchema = z.enum(["proposed", "applied", "confirmed", "rejected", "superseded"]);
export const LaneSchema = z.enum(["remote", "me", "manual"]);
export const OperationKindSchema = z.enum([
  "card.create", "card.update", "card.remove", "card.replace", "definition.refine", "interpretation.reject", "confirm", "undo",
]);

export const CardDraftSchema = z.object({
  kind: CardKindSchema,
  text: z.string(),
  rule_id: z.string().nullable(),
  about_card_id: z.string().nullable(),
});

export const CardPatchSchema = z.object({
  text: z.string().nullable(),
  text_append: z.string().nullable(),
  answer: z.string().nullable(),
  rule_id: z.string().nullable(),
  about_card_id: z.string().nullable(),
});

export const AmendmentSchema = z.object({
  from: z.string().nullable(),
  to: z.string(),
  scope: z.string().nullable(),
});

export const OperationSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("card.create"), card: CardDraftSchema }),
  z.object({ kind: z.literal("card.update"), card_id: z.string(), patch: CardPatchSchema, amendment: AmendmentSchema.nullable() }),
  z.object({ kind: z.literal("card.remove"), card_id: z.string(), reason: z.string() }),
  z.object({
    kind: z.literal("card.replace"),
    card_id: z.string(),
    replacement: z.object({ text: z.string() }).nullable(),
    replacement_card_id: z.string().nullable(),
  }),
  z.object({ kind: z.literal("definition.refine"), card_id: z.string(), term: z.string(), definition: z.string() }),
  z.object({ kind: z.literal("interpretation.reject"), proposal_id: z.string() }),
  z.object({ kind: z.literal("confirm"), card_ids: z.array(z.string()) }),
  z.object({ kind: z.literal("undo"), steps: z.number() }),
]);

export const CandidateRefSchema = z.object({ card_id: z.string(), label: z.string() });

export const ClarificationSchema = z.object({
  kind: z.enum(["choose_target", "confirm_intent"]),
  question: z.string(),
  candidates: z.array(CandidateRefSchema),
  pending_operations: z.array(OperationSchema),
});

export const ResolvesSchema = z.object({
  proposal_id: z.string(),
  chosen_card_ids: z.array(z.string()),
  dismissed: z.boolean(),
});

/** The model-fillable subset: no optional(), no min/max. */
export const ModelProposalSchema = z.object({
  intent: ClassifierIntentSchema,
  operations: z.array(OperationSchema),
  target_card_ids: z.array(z.string()),
  confidence: z.number(),
  needs_clarification: z.boolean(),
  clarification: ClarificationSchema.nullable(),
  resolves: ResolvesSchema.nullable(),
  rationale: z.string(),
});

export const ProvenanceSchema = z.object({
  provider: z.enum(["rules.v1", "claude"]),
  model: z.string().nullable(),
  prompt_version: z.string().nullable(),
  fallback_from: z.literal("claude").nullable(),
  error: z.string().nullable(),
});

/** What either provider returns; z.infer of this is mutually assignable with ClassifierProposal (checked in tests/unit/core/types.test.ts). */
export const ProposalSchema = ModelProposalSchema.extend({
  confidence: z.number().min(0).max(1),
  heard_intent: IntentSchema.nullable(),
  classifier: ProvenanceSchema,
  source_utterance_ids: z.array(z.string()).min(1),
});

export const ClassifierUtteranceSchema = z.object({
  id: z.string(),
  text: z.string(),
  lane: LaneSchema,
  speaker: z.string().nullable(),
});

export const CardIndexEntrySchema = z.object({
  id: z.string(),
  kind: CardKindSchema,
  title: z.string(),
  text: z.string(),
  status: CardStatusSchema,
  links: z.object({ rule_id: z.string().nullable(), about_card_id: z.string().nullable() }),
  answer: z.string().nullable(),
  seq: z.number().int(),
  last_utterance_id: z.string().nullable(),
  last_speaker: z.string().nullable(),
  proposal_id: z.string().nullable(),
});

export const LastProposalRefSchema = z.object({
  id: z.string(),
  intent: IntentSchema,
  op: OperationKindSchema,
  kind: CardKindSchema.nullable(),
  status: z.enum(["applied", "confirmed"]),
  card_ids: z.array(z.string()),
  utterance_id: z.string(),
  rejectable: z.boolean(),
});

export const PendingClarificationSchema = z.object({
  proposal_id: z.string(),
  kind: z.enum(["choose_target", "confirm_intent"]),
  question: z.string(),
  candidates: z.array(CandidateRefSchema),
  pending_operations: z.array(OperationSchema),
  intent: IntentSchema,
  asked_by_utterance_id: z.string(),
  source_utterance_ids: z.array(z.string()),
  classifier: ProvenanceSchema,
});

export const ClassifierInputSchema = z.object({
  utterance: ClassifierUtteranceSchema,
  recent: z.array(ClassifierUtteranceSchema),
  cards: z.array(CardIndexEntrySchema),
  last_proposal: LastProposalRefSchema.nullable(),
  last_rejectable: LastProposalRefSchema.nullable(),
  pending_clarification: PendingClarificationSchema.nullable(),
});

export type ModelProposal = z.infer<typeof ModelProposalSchema>;
export type ProposalFromSchema = z.infer<typeof ProposalSchema>;
export type ClassifierInputFromSchema = z.infer<typeof ClassifierInputSchema>;

/** Enforces invariants I1–I10 (design §6.1) before either provider returns; a violation throws ClassifierError("E_PROPOSAL_INVARIANT"). */
export function assertProposalInvariants(p: ClassifierProposal, input: ClassifierInput): void {
  void p;
  void input;
  throw new Error("not implemented: assertProposalInvariants");
}

/** The card drafts a proposal would create (its card.create operations plus any in pending_operations). */
export function draftsOf(p: ClassifierProposal): CardDraft[] {
  void p;
  throw new Error("not implemented: draftsOf");
}
