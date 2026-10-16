// TEST-PLAN §1 cases 16–18, 20: the reducer is pure and total; history bookkeeping; no proposed card in a reduced state.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { chainEvent } from "../../../src/core/chain.js";
import { initialState, reduce } from "../../../src/core/reduce.js";
import { GENESIS_REVISION_HASH } from "../../../src/core/revision.js";
import type { CardRecord, EventPayload, ExmapEvent, MapState } from "../../../src/core/types.js";
import { sha256 } from "../../../src/server/hash.js";
import { createdCardId, deepFreeze, humanProposal, propose, run, scenario, smallMap, stamps } from "./fixtures.js";

const s = scenario();

function unknownCard(id: string): CardRecord {
  const prov = { proposal_id: "prop_x", event_id: "evt_x", utterance_ids: [], classifier: "human" as const };
  return {
    id, kind: "rule", text: "ghost", definitions: [], status: "applied", version: 1, supersedes: null, superseded_by: null, rejection: null,
    confirmation: null, created: prov, changed: prov, restored_by: null,
  };
}

describe("reduce", () => {
  it("16. never mutates its input (deep-frozen state; every event type)", () => {
    let state = deepFreeze(initialState(s.session_id));
    const seen = new Set<string>();
    for (const event of s.events) {
      seen.add(event.type);
      state = deepFreeze(reduce(state, deepFreeze(structuredClone(event))));
    }
    expect(seen.size).toBe(13);
    expect(state.head).toEqual(s.state.head);
  });

  it("17. is total for every event type: standalone events naming unknown ids reduce without throwing (§5.3)", () => {
    const base = initialState("sess_total");
    const stamp = stamps.rules();
    const payloads: EventPayload[] = [
      { type: "utterance.recorded", utterance: { id: "utt_a", text: "x", lane: "me", speaker: null, provider: "manual", model: null, t_start_ms: 0, t_end_ms: 0, is_local: true, confidence: null } },
      { type: "utterance.classified", utterance_id: "utt_zz", intent: "none", heard_intent: "confirm", classifier: stamp, confidence: 0, rationale: "", proposal_ids: [], refused: [], error: null },
      { type: "proposal.made", proposal: { ...humanProposal("prop_m", { kind: "card.remove", card_id: "card_zz" }), resolves_clarification_id: "clar_zz" }, effects: [] },
      { type: "proposal.applied", proposal_id: "prop_zz", operation: { kind: "card.update", card_id: "card_g", patch: { text: "y" } }, effects: [{ card_id: "card_g", before: null, after: unknownCard("card_g") }], revision: { seq: 1, hash: "a".repeat(64) } },
      { type: "proposal.rejected", proposal_id: "prop_zz", rejected_proposal_id: "prop_yy", effects: [{ card_id: "card_g", before: unknownCard("card_g"), after: { ...unknownCard("card_g"), version: 2 } }], revision: { seq: 2, hash: "b".repeat(64) } },
      { type: "proposal.confirmed", proposal_id: "prop_zz", card_ids: ["card_zz"], proposal_ids: ["prop_yy"], confirms_proposal_ids: ["prop_yy"], effects: [] },
      { type: "undo.applied", proposal_id: "prop_zz", from_revision: { seq: 2, hash: "b".repeat(64) }, to_revision: { seq: 0, hash: GENESIS_REVISION_HASH }, effects: [], revision: { seq: 3, hash: "c".repeat(64) } },
      { type: "clarification.asked", clarification_id: "clar_a", proposal_id: "prop_zz", question: "?", candidates: [], template: null, pending_operation: null },
      { type: "clarification.answered", clarification_id: "clar_zz", answer: { kind: "yes" }, actor: "Sam", resolved_by_proposal_id: "prop_q" },
      { type: "question.accepted_outstanding", question_id: "card_zz", by: "Sam", reason: "r", effects: [] },
      { type: "signoff.recorded", signoff: { id: "sig_a", reviewer: { name: "Sam" }, confirmation_text: "", revision: { seq: 0, hash: GENESIS_REVISION_HASH }, evidence: { head_seq: 0, head_hash: "" }, checks: { pass: false, checks: [] } } },
      { type: "signoff.invalidated", signoff_id: "sig_zz", by_event_id: "evt_zz", from_revision: { seq: 0, hash: "" }, to_revision: { seq: 1, hash: "" } },
      { type: "export.options_set", options: { capability_class: "bug.fix", kind: "code", size_estimate: "XS", facts: [], by: "Sam", seq: 1, at: "2026-01-01T00:00:00.000Z" } },
    ];
    expect(new Set(payloads.map((p) => p.type)).size).toBe(13);
    let state = base;
    let seq = 1;
    for (const payload of payloads) {
      const event = chainEvent({ seq: state.head.seq, hash: state.head.hash }, { ...payload, id: `evt_${seq}`, at: "2026-01-01T00:00:00.000Z", session_id: "sess_total", batch_id: `evt_${seq}` }, sha256);
      const before = state;
      expect(() => (state = reduce(state, event))).not.toThrow();
      expect(state.head).toEqual({ seq, hash: event.hash, event_id: event.id });
      expect(before.head.seq).toBe(seq - 1); // input untouched
      seq++;
    }
    expect(state.utterances.map((u) => u.id)).toEqual(["utt_a"]);
    expect(state.classifications[0]?.heard_intent).toBe("confirm");
    expect(state.cards.card_g?.version).toBe(2);
    expect(state.cards.card_g?.history.length).toBe(1);
    expect(state.card_order).toEqual(["card_g"]);
    expect(state.revisions.map((r) => r.seq)).toEqual([0, 1, 2, 3]);
    expect(state.revisions[3]!.cause).toBe("undo.applied");
    expect(state.proposals.prop_m?.status).toBe("pending");
    expect(state.proposals.prop_zz).toBeUndefined();
    expect(state.clarifications.clar_a?.status).toBe("open");
    expect(state.clarifications.clar_zz).toBeUndefined();
    expect(state.signoffs.map((x) => x.status)).toEqual(["active"]);
    expect(state.export_options.length).toBe(1);
  });

  it("18. history is appended only on version bumps: confirm (no bump) vs update (bump); a replace by existing card bumps neither", () => {
    const { ctx, state, rule } = smallMap();
    const confirmed = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule], proposal_ids: [] })), ctx).state;
    expect(confirmed.cards[rule]!.version).toBe(1);
    expect(confirmed.cards[rule]!.history).toEqual([]);
    const updated = run(confirmed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "Changed." } })), ctx);
    const card = updated.state.cards[rule]!;
    expect(card.version).toBe(2);
    expect(card.history.length).toBe(1);
    expect(card.history[0]!.version).toBe(1);
    expect(card.history[0]!.record.status).toBe("confirmed");
    expect(card.history[0]!.replaced_by_event_id).toBe(updated.events[1]!.id);
    expect("history" in card.history[0]!.record).toBe(false);
    // replace by an existing card
    const afterReplace = s.stateAfter("replace_id");
    const old = afterReplace.cards[s.ids.ex_nurse!]!;
    const replacement = afterReplace.cards[s.ids.ex_nurse2!]!;
    const beforeReplace = s.stateBefore("replace_id");
    expect(old.version).toBe(beforeReplace.cards[old.id]!.version);
    expect(replacement.version).toBe(beforeReplace.cards[replacement.id]!.version);
    expect(old.history.length).toBe(beforeReplace.cards[old.id]!.history.length);
    expect(replacement.history.length).toBe(beforeReplace.cards[replacement.id]!.history.length);
  });

  it("20. no reduced state ever contains a proposed card; a create's proposal.made does carry a proposed effect", () => {
    const states: MapState[] = s.steps.map((step) => step.state);
    for (const state of states) for (const card of Object.values(state.cards)) expect(card.status).not.toBe("proposed");
    const create = s.step("rule");
    const made = create.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>;
    expect(made.type).toBe("proposal.made");
    expect(made.effects[0]!.before).toBeNull();
    expect(made.effects[0]!.after.status).toBe("proposed");
    expect(made.effects[0]!.card_id).toBe(createdCardId(create.events));
    const applied = create.events[1] as Extract<ExmapEvent, { type: "proposal.applied" }>;
    expect(applied.effects[0]!.before?.status).toBe("proposed");
    expect(applied.effects[0]!.after.status).toBe("applied");
  });

  it("reduce.ts repeats the genesis hash literally (it imports no hashing module); the two constants agree", () => {
    const source = readFileSync(fileURLToPath(new URL("../../../src/core/reduce.ts", import.meta.url)), "utf8");
    expect(source).toContain(GENESIS_REVISION_HASH);
    expect(initialState("x").revisions[0]!.hash).toBe(GENESIS_REVISION_HASH);
  });
});
