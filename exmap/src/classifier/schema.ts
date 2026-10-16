// exmap/src/classifier/schema.ts — zod mirrors of the §4 §11 types (design §6.1). The schemas are real;
// assertProposalInvariants() enforces I1–I10 and draftsOf() lists the drafts a proposal would create.
// ModelProposalSchema is what the model fills: no optional(), no min/max (the SDK's grammar transform drops
// enum/const/minimum/maximum into descriptions, so enums are spelled out in the system prompt and an off-enum value
// fails zod client-side). ProposalSchema extends it with confidence in [0,1], heard_intent, classifier, source_utterance_ids.
import { z } from "zod";
import type { CardDraft, ClassifierInput, ClassifierOperation, ClassifierProposal, Intent } from "../core/types.js";
import { MIN_CONFIDENCE, RATIONALE_MAX } from "./constants.js";
import { ClassifierError } from "./types.js";

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

/** The intent each operation kind belongs to (design §6.1 I2). */
export const INTENT_OF_OP: Record<ClassifierOperation["kind"], Intent> = {
  "card.create": "add", "card.update": "amend", "card.remove": "remove", "card.replace": "replace",
  "definition.refine": "clarify", "interpretation.reject": "reject", "confirm": "confirm", "undo": "undo",
};

/** Every card id an operation references (card_id, card_ids, rule_id, about_card_id, replacement_card_id), "$choice" excluded. */
export function idsOfOperation(op: ClassifierOperation): string[] {
  const ids: string[] = [];
  switch (op.kind) {
    case "card.create":
      if (op.card.rule_id) ids.push(op.card.rule_id);
      if (op.card.about_card_id) ids.push(op.card.about_card_id);
      break;
    case "card.update":
      ids.push(op.card_id);
      if (op.patch.rule_id) ids.push(op.patch.rule_id);
      if (op.patch.about_card_id) ids.push(op.patch.about_card_id);
      break;
    case "card.remove":
    case "definition.refine":
      ids.push(op.card_id);
      break;
    case "card.replace":
      ids.push(op.card_id);
      if (op.replacement_card_id) ids.push(op.replacement_card_id);
      break;
    case "confirm":
      ids.push(...op.card_ids);
      break;
    case "interpretation.reject":
    case "undo":
      break;
  }
  return ids.filter((id) => id !== CHOICE);
}

/** I3: the ordered unique card ids referenced by operations, pending_operations and candidates. */
export function targetCardIds(p: Pick<ClassifierProposal, "operations" | "clarification">): string[] {
  const out: string[] = [];
  const push = (id: string): void => { if (!out.includes(id)) out.push(id); };
  for (const op of p.operations) for (const id of idsOfOperation(op)) push(id);
  if (p.clarification) {
    for (const op of p.clarification.pending_operations) for (const id of idsOfOperation(op)) push(id);
    for (const c of p.clarification.candidates) push(c.card_id);
  }
  return out;
}

function violation(code: string, detail: string): never {
  throw new ClassifierError("E_PROPOSAL_INVARIANT", `${code}: ${detail}`);
}

/** I2: the operation list binds to the intent — one leading reject/confirm prefix allowed; remove may carry several card.remove. */
function checkOpsBindIntent(intent: Intent, ops: ClassifierOperation[], where: string): void {
  if (ops.length === 0) violation("I2", `${where}: no operation for intent ${intent}`);
  let i = 0;
  const first = ops[0]!;
  if (ops.length > 1 && (first.kind === "interpretation.reject" || first.kind === "confirm") && INTENT_OF_OP[first.kind] !== intent) i = 1;
  const rest = ops.slice(i);
  if (rest.length === 0) violation("I2", `${where}: only a prefix operation`);
  for (const op of rest) {
    if (INTENT_OF_OP[op.kind] !== intent) violation("I2", `${where}: ${op.kind} does not belong to intent ${intent}`);
  }
  if (rest.length > 1 && intent !== "remove") violation("I2", `${where}: several operations for intent ${intent}`);
}

/** Enforces invariants I1–I10 (design §6.1) before either provider returns; a violation throws ClassifierError("E_PROPOSAL_INVARIANT"). */
export function assertProposalInvariants(p: ClassifierProposal, input: ClassifierInput): void {
  const parsed = ProposalSchema.safeParse(p);
  if (!parsed.success) violation("SCHEMA", parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
  const index = new Map(input.cards.map((c) => [c.id, c] as const));
  // I1
  if (p.needs_clarification !== (p.clarification !== null)) violation("I1", "needs_clarification must equal clarification !== null");
  if (p.needs_clarification && (p.operations.length !== 0 || p.intent === "none")) violation("I1", "a clarification has no operations and an intent");
  // I9
  if (p.heard_intent !== null && p.intent !== "none") violation("I9", "heard_intent only on intent none");
  if (p.intent === "none" && (p.operations.length !== 0 || p.needs_clarification)) violation("I9", "intent none has no operations and no clarification");
  // I2
  if (p.intent !== "none" && !p.needs_clarification) checkOpsBindIntent(p.intent, p.operations, "operations");
  if (p.clarification && p.intent !== "none") checkOpsBindIntent(p.intent, p.clarification.pending_operations, "pending_operations");
  // I3
  const expected = targetCardIds(p);
  if (expected.length !== p.target_card_ids.length || expected.some((id, i) => p.target_card_ids[i] !== id)) {
    violation("I3", `target_card_ids ${JSON.stringify(p.target_card_ids)} != ${JSON.stringify(expected)}`);
  }
  // I4
  for (const id of expected) if (!index.has(id)) violation("I4", `unknown card id ${id}`);
  const allOps = [...p.operations, ...(p.clarification?.pending_operations ?? [])];
  const indexProposalIds = new Set(input.cards.map((c) => c.proposal_id).filter((x): x is string => x !== null));
  for (const op of allOps) {
    if (op.kind === "interpretation.reject") {
      const ok = op.proposal_id === CHOICE || (input.last_rejectable !== null && op.proposal_id === input.last_rejectable.id) || indexProposalIds.has(op.proposal_id);
      if (!ok) violation("I4", `interpretation.reject names an unknown proposal ${op.proposal_id}`);
    }
    if (op.kind === "card.replace") {
      if ((op.replacement === null) === (op.replacement_card_id === null)) violation("I4", "card.replace needs exactly one replacement form");
      if (op.replacement_card_id !== null && op.replacement_card_id === op.card_id) violation("I4", "card.replace cannot replace a card with itself");
    }
    if (op.kind === "confirm" && op.card_ids.length === 0) {
      const lp = input.last_proposal;
      const ok = lp !== null && lp.status === "applied" && (lp.op === "card.remove" || lp.op === "undo" || lp.op === "interpretation.reject");
      if (!ok) violation("I4", "confirm with no card ids needs a last proposal that is a removal, undo or rejection");
    }
    // I10
    if (op.kind === "card.update") {
      const fields = [op.patch.text, op.patch.text_append, op.patch.answer, op.patch.rule_id, op.patch.about_card_id];
      if (!fields.some((f) => f !== null)) violation("I10", "card.update patch is empty");
      if (op.patch.text !== null && op.patch.text_append !== null) violation("I10", "card.update patch has both text and text_append");
      const target = index.get(op.card_id);
      if (target) {
        if (op.patch.answer !== null && target.kind !== "question") violation("I10", "answer only on a question");
        if (op.patch.rule_id !== null && target.kind !== "example") violation("I10", "rule_id only on an example");
        if (op.patch.about_card_id !== null && target.kind !== "question") violation("I10", "about_card_id only on a question");
      }
    }
    if (op.kind === "undo" && (!Number.isInteger(op.steps) || op.steps < 1)) violation("I4", "undo.steps must be a positive integer");
  }
  // I5
  if (p.clarification) {
    const c = p.clarification;
    const hasChoice = JSON.stringify(c.pending_operations).includes(`"${CHOICE}"`);
    if (c.kind === "choose_target" && (c.candidates.length < 2 || !hasChoice)) violation("I5", "choose_target needs >= 2 candidates and a $choice");
    if (c.kind === "confirm_intent" && (c.candidates.length !== 0 || c.pending_operations.length !== 1 || hasChoice)) violation("I5", "confirm_intent needs exactly one complete operation and no candidates");
    if (!c.question.trim()) violation("I5", "a clarification needs a question");
  }
  if (!p.needs_clarification && JSON.stringify(p.operations).includes(`"${CHOICE}"`)) violation("I5", "$choice outside a clarification");
  // I6
  if (!p.needs_clarification && p.intent !== "none" && p.confidence < MIN_CONFIDENCE) violation("I6", `confidence ${p.confidence} below ${MIN_CONFIDENCE}`);
  if (Math.round(p.confidence * 100) / 100 !== p.confidence) violation("I6", "confidence must have at most two decimals");
  // I7
  if (p.source_utterance_ids[0] !== input.utterance.id) violation("I7", "source_utterance_ids[0] must be the utterance");
  if (p.resolves) {
    const pc = input.pending_clarification;
    if (!pc) violation("I7", "resolves without a pending clarification");
    if (!p.source_utterance_ids.includes(pc.asked_by_utterance_id)) violation("I7", "resolves must cite the asking utterance");
    if (p.resolves.proposal_id !== pc.proposal_id) violation("I7", "resolves must name the pending clarification's proposal");
  }
  // I8
  if (p.rationale.trim().length === 0 || p.rationale.length > RATIONALE_MAX) violation("I8", "rationale must be non-empty and <= 200 chars");
}

/** The card drafts a proposal would create (its card.create operations plus any in pending_operations). */
export function draftsOf(p: ClassifierProposal): CardDraft[] {
  const out: CardDraft[] = [];
  for (const op of [...p.operations, ...(p.clarification?.pending_operations ?? [])]) {
    if (op.kind === "card.create") out.push(op.card);
  }
  return out;
}
