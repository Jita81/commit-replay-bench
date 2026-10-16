// TEST-PLAN §1 case 0 (compile-time; checked by `tsc -p tsconfig.test.json --noEmit` in `npm run typecheck`, never run).
import type { z } from "zod";
import { chainEvent } from "../../../src/core/chain.js";
import { REFUSAL } from "../../../src/core/refusals.js";
import type { ProposalSchema } from "../../../src/classifier/schema.js";
import type { CardRecord, ClassifierProposal, EventBody, ExmapEvent, Proposal, RefusalCode, Sha256Fn } from "../../../src/core/types.js";

type Assert<T extends true> = T;
type MutuallyAssignable<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;

// EventBody keeps every payload's fields
declare const proposal: Proposal;
const madeBody: EventBody = { type: "proposal.made", proposal, effects: [], id: "evt_1", seq: 1, at: "2026-01-01T00:00:00.000Z", session_id: "s", batch_id: "evt_1", prev_hash: "" };
export type _MadeBody = typeof madeBody;

// chainEvent(prev, { type: "proposal.applied", … }, sha) compiles and is assignable to ExmapEvent
declare const sha: Sha256Fn;
const applied: ExmapEvent = chainEvent(
  { seq: 0, hash: "" },
  { type: "proposal.applied", proposal_id: "prop_1", operation: { kind: "card.remove", card_id: "card_1" }, effects: [], revision: { seq: 1, hash: "" }, id: "evt_2", at: "2026-01-01T00:00:00.000Z", session_id: "s", batch_id: "evt_2" },
  sha,
);
export type _Applied = typeof applied;

// CardRecord for an example keeps rule_id
export type _ExampleRecordKeepsRuleId = Assert<Extract<CardRecord, { kind: "example" }> extends { rule_id: string | null; needs_review: unknown } ? true : false>;
// z.infer<typeof ProposalSchema> and ClassifierProposal are mutually assignable
export type _ProposalSchemaMatches = Assert<MutuallyAssignable<z.infer<typeof ProposalSchema>, ClassifierProposal>>;
// REFUSAL is { readonly [K in RefusalCode]: K }
export type _RefusalShape = Assert<typeof REFUSAL extends { readonly [K in RefusalCode]: K } ? true : false>;
export type _RefusalKeys = Assert<keyof typeof REFUSAL extends RefusalCode ? true : false>;
