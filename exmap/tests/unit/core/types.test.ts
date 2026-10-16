// Step-zero smoke test for the node project: the refusal constants exist and the compile-time guards of design §4 hold.
import { describe, expect, it } from "vitest";
import type { z } from "zod";
import { REFUSAL } from "../../../src/core/refusals.js";
import { DOD_OPTIONS, SIGNOFF_CONFIRMATION_TEXT } from "../../../src/core/dod.js";
import { GENESIS_PREV_HASH } from "../../../src/core/chain.js";
import { GENESIS_REVISION_HASH } from "../../../src/core/revision.js";
import type { CardRecord, ClassifierProposal, EventBody, RefusalCode } from "../../../src/core/types.js";
import type { ProposalSchema } from "../../../src/classifier/schema.js";
import { sha256 } from "../../../src/server/hash.js";

/* ───── compile-time guards (design §4, "Compile-time guards") ───── */
type Assert<T extends true> = T;
type MutuallyAssignable<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
// EventBody keeps every payload's own fields
type _EventBodyKeepsPayload = Assert<Extract<EventBody, { type: "proposal.applied" }> extends { revision: unknown; effects: unknown } ? true : false>;
// CardRecord of an example keeps rule_id
type _CardRecordKeepsRuleId = Assert<Extract<CardRecord, { kind: "example" }> extends { rule_id: unknown; needs_review: unknown } ? true : false>;
// z.infer<typeof ProposalSchema> is mutually assignable with ClassifierProposal
type _ProposalSchemaMatches = Assert<MutuallyAssignable<z.infer<typeof ProposalSchema>, ClassifierProposal>>;
// REFUSAL is { readonly [K in RefusalCode]: K }
type _RefusalShape = Assert<typeof REFUSAL extends { readonly [K in RefusalCode]: K } ? true : false>;

describe("core step zero", () => {
  it("REFUSAL maps every RefusalCode to itself", () => {
    const entries = Object.entries(REFUSAL);
    expect(entries.length).toBe(44);
    for (const [key, value] of entries) expect(value).toBe(key);
    expect(REFUSAL.BAD_SHAPE).toBe("BAD_SHAPE");
    expect(REFUSAL.SIGNOFF_DOD_FAILED).toBe("SIGNOFF_DOD_FAILED");
  });

  it("exposes the DoD and chain constants of design §5", () => {
    expect(SIGNOFF_CONFIRMATION_TEXT).toBe("I have reviewed the complete requirement and confirm it represents the agreed intent.");
    expect(DOD_OPTIONS).toEqual({ requireHumanConfirm: false });
    expect(GENESIS_PREV_HASH).toBe("");
    expect(GENESIS_REVISION_HASH).toBe(sha256('{"cards":[],"schema":"exmap.revision.v1"}'));
  });

  it("server sha256 adapter matches the §5 vectors", () => {
    expect(sha256("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});
