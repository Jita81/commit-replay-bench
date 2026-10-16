// exmap/tests/unit/classifier/referents.test.ts — TEST-PLAN §2 referents rows 4–6.
import { describe, expect, it } from "vitest";
import { askTarget, maskReferents, parseReferent, resolveReferent } from "../../../src/classifier/referents.js";
import { card, input, utt } from "./helpers.js";

describe("referents", () => {
  it("4. parseReferent: kinds, named topics, paraphrases, bare demonstratives, exclusions", () => {
    expect(parseReferent("delete that example")).toMatchObject({ kind: "example", topic: null, bare: false });
    expect(parseReferent("the GP one")).toMatchObject({ kind: null, topic: { text: "gp", named: true } });
    expect(parseReferent("delete the example about dentists")).toMatchObject({ kind: "example", topic: { text: "dentists", named: true } });
    expect(parseReferent("change that limit to 24 hours")).toMatchObject({ kind: null, topic: { text: "limit", named: false } });
    expect(parseReferent("that limit")).toMatchObject({ topic: { text: "limit", named: false } });
    expect(parseReferent("make the GP window 3 hours")).toMatchObject({ topic: { text: "gp window", named: false } });
    expect(parseReferent("the GP window")).toMatchObject({ topic: { text: "gp window", named: false } });
    expect(parseReferent("make that 24 hours")).toMatchObject({ kind: null, topic: null, ordinal: null, bare: true });
    expect(parseReferent("change it to 48 hours")).toMatchObject({ bare: true });
    expect(parseReferent("use this example instead")).toBeNull();
    expect(parseReferent("it is refused")).toBeNull();
    expect(parseReferent("the 24 hour rule")).toMatchObject({ kind: "rule", topic: { text: "24 hour", named: true } });
    expect(parseReferent("the old nurse one")).toMatchObject({ kind: null, topic: { text: "old nurse", named: true } });
    expect(parseReferent("the second one")).toMatchObject({ ordinal: 2 });
    expect(parseReferent("the story")).toMatchObject({ kind: "story" });
    expect(parseReferent("when the cancellation fails because the system is down")).toBeNull();
    expect(parseReferent("no, that is not what i said")).toBeNull();
    expect(parseReferent("that one is allowed because it is more than 2 hours")).toMatchObject({ bare: true, span: [0, 8] });
  });

  it("5. maskReferents replaces every referent span with <ref>", () => {
    expect(maskReferents("delete that example, it duplicates the gp one")).toBe("delete <ref>, it duplicates <ref>");
    expect(maskReferents("for a nurse appointment, say it is at 10am and they cancel at 8am, that one is allowed")).toBe("for a nurse appointment, say it is at 10am and they cancel at 8am, <ref> is allowed");
    expect(maskReferents("we also need an error case, when the cancellation fails because the system is down")).toBe("we also need an error case, when the cancellation fails because the system is down");
  });

  it("6. resolveReferent degenerate cases: empty pool, one card, paraphrase miss, named miss", () => {
    const e1 = card("card_e1", "example", "A GP appointment at 10am cancelled at 9am is refused.", { seq: 3, last_utterance_id: "utt_3", last_speaker: "Sam" });
    const none = resolveReferent(parseReferent("delete that example"), input({ utterance: "delete that example" }), {});
    expect(none).toMatchObject({ kind: "none" });
    const one = resolveReferent(parseReferent("delete that example"), input({ utterance: "delete that example", cards: [e1] }), {});
    expect(one).toMatchObject({ kind: "resolved", card: { id: "card_e1" }, how: "the only example" });
    const paraphrase = resolveReferent(parseReferent("change that limit to 24"), input({ utterance: "change that limit to 24", cards: [e1] }), {});
    expect(paraphrase).toMatchObject({ kind: "resolved", card: { id: "card_e1" } });
    const named = resolveReferent(parseReferent("delete the example about dentists"), input({ utterance: "delete the example about dentists", cards: [e1] }), {});
    expect(named).toMatchObject({ kind: "ambiguous", candidates: [{ id: "card_e1" }] });
    expect(named.kind === "ambiguous" ? named.why : "").toBe("no example about 'dentists'");
    const ask = askTarget(named, { kind: "card.remove", card_id: "$choice", reason: "" }, "remove", "remove", input({ utterance: utt("utt_4", "delete the example about dentists"), cards: [e1] }));
    expect(ask).toMatchObject({ kind: "clarification", clarification: { kind: "confirm_intent", candidates: [], pending_operations: [{ kind: "card.remove", card_id: "card_e1" }] } });
    expect(ask.kind === "clarification" ? ask.clarification.question : "").toBe("Did you mean to remove A GP appointment at 10am cancelled at 9am is refused. (example, Sam)? (no example about 'dentists')");
  });
});
