// TEST-PLAN §1 cases 51–52: every classification is ledgered and the counts follow.
import { describe, expect, it } from "vitest";
import * as select from "../../../src/core/select.js";
import { aiProposal, classify, propose, refused, run, scenario, signoff, smallMap, stamps, utterance } from "./fixtures.js";

describe("classification.record", () => {
  it("51. appends utterance.classified and the counts follow; CLASSIFICATION_PROPOSAL_MISMATCH; never substantive, never invalidates", () => {
    const { ctx, state, rule } = smallMap();
    const u1 = run(state, { kind: "utterance.record", utterance: utterance("utt_1", "Right, let's start.") }, ctx).state;
    const u2 = run(u1, { kind: "utterance.record", utterance: utterance("utt_2", "Delete the rule.") }, ctx).state;
    const base = select.counts(u2);
    expect(base).toMatchObject({ utterances: 2, classified: 0, actionable: 0, classifier_errors: 0, fallbacks: 0 });
    const none = run(u2, classify("utt_1", "none"), ctx);
    expect(none.events.map((e) => e.type)).toEqual(["utterance.classified"]);
    expect(select.counts(none.state)).toMatchObject({ classified: 1, actionable: 0 });
    expect(none.state.revisions.length).toBe(u2.revisions.length);
    const pid = ctx.nextId("prop");
    const proposed = run(none.state, propose(aiProposal(pid, { kind: "card.remove", card_id: rule }, { utts: ["utt_2"] })), ctx).state;
    expect(select.counts(proposed)).toMatchObject({ classified: 1, actionable: 1 });
    const cited = run(proposed, classify("utt_2", "remove", [pid]), ctx).state;
    expect(select.counts(cited)).toMatchObject({ classified: 2, actionable: 1 });
    const fallback = run(cited, classify("utt_1", "none", [], { classifier: stamps.fallback("CLASSIFIER_ERROR") }), ctx).state;
    expect(select.counts(fallback)).toMatchObject({ classified: 2, fallbacks: 1 });
    const errored = run(fallback, classify("utt_1", "none", [], { error: { code: "CLASSIFIER_ERROR", message: "boom" } }), ctx).state;
    expect(select.counts(errored)).toMatchObject({ classifier_errors: 1, classified: 2 });
    expect(select.classificationsOf(errored, "utt_1").length).toBe(3);
    expect(refused(errored, classify("utt_2", "remove", [pid], { error: { code: "X", message: "y" } }), ctx).reason).toBe("CLASSIFICATION_PROPOSAL_MISMATCH");
    expect(refused(errored, classify("utt_1", "remove", [pid]), ctx).reason).toBe("CLASSIFICATION_PROPOSAL_MISMATCH");
    expect(refused(errored, classify("utt_1", "remove", ["prop_404"]), ctx).reason).toBe("PROPOSAL_NOT_FOUND");
    expect(refused(errored, classify("utt_404", "none"), ctx).reason).toBe("UTTERANCE_UNKNOWN");
    expect(refused(errored, classify("utt_1", "shout" as never), ctx).reason).toBe("INVALID_ENUM");
    expect(refused(errored, classify("utt_1", "none", [], { classifier: stamps.human("Sam") as never }), ctx).reason).toBe("INVALID_ENUM");
    expect(refused(errored, classify("utt_1", "none", [], { confidence: 0.123 }), ctx).reason).toBe("INVALID_CONFIDENCE");
    // after a sign-off a classification does not invalidate it
    const s = scenario();
    const signed = s.stateAfter("signoff");
    const after = run(signed, classify(s.ids.u20!, "none", [], { rationale: "re-run" }), s.ctx);
    expect(after.events.map((e) => e.type)).toEqual(["utterance.classified"]);
    expect(select.activeSignoff(after.state)?.id).toBe(s.ids.sig1);
    expect(signoff(after.state).kind).toBe("signoff.record");
  });

  it("52. heard_intent: { intent: none, heard_intent: confirm } is stored and read back; { intent: add, heard_intent: confirm } -> BAD_SHAPE", () => {
    const { ctx, state } = smallMap();
    const u1 = run(state, { kind: "utterance.record", utterance: utterance("utt_1", "Yes.") }, ctx).state;
    const heard = run(u1, classify("utt_1", "none", [], { heard_intent: "confirm", rationale: "nothing to confirm" }), ctx).state;
    const record = select.classificationsOf(heard, "utt_1")[0]!;
    expect(record.intent).toBe("none");
    expect(record.heard_intent).toBe("confirm");
    expect(record.rationale).toBe("nothing to confirm");
    expect(record.event_id).toBe(heard.head.event_id);
    const bad = refused(heard, classify("utt_1", "add", [], { heard_intent: "confirm" }), ctx);
    expect(bad.reason).toBe("BAD_SHAPE");
    expect(bad.detail).toContain("heard_intent");
    expect(refused(heard, classify("utt_1", "none", [], { heard_intent: "shout" as never }), ctx).reason).toBe("INVALID_ENUM");
  });
});
