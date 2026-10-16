// TEST-PLAN §1 cases 31–39: confirm, interpretation.reject, shape/intent refusals, the closed status machine, restores.
import { describe, expect, it } from "vitest";
import { apply } from "../../../src/core/apply.js";
import * as select from "../../../src/core/select.js";
import type { Card, CardStatus, ExampleCard, ExmapEvent } from "../../../src/core/types.js";
import {
  aiProposal, clarifying, createdCardId, humanProposal, propose, refused, revisionHash, run, scenario, smallMap, stamps, testCtx, utterance,
} from "./fixtures.js";
import { initialState } from "../../../src/core/reduce.js";

const example = (c: Card | undefined): ExampleCard => {
  if (!c || c.kind !== "example") throw new Error("not an example");
  return c;
};

describe("confirm", () => {
  it("31. confirm sets confirmed with confirmation.version and by; marks the producing proposal confirmed; NOTHING_TO_CONFIRM; mixed lists; by for click and voice", () => {
    const { ctx, state, rule, story } = smallMap();
    const pid = ctx.nextId("prop");
    const confirmed = run(state, propose(humanProposal(pid, { kind: "confirm", card_ids: [rule], proposal_ids: [] }, "Ana")), ctx);
    const card = confirmed.state.cards[rule]!;
    expect(card.status).toBe("confirmed");
    expect(card.confirmation).toEqual({ proposal_id: pid, event_id: confirmed.events[1]!.id, version: 1, by: { provider: "human", actor: "Ana", confidence: 1 } });
    expect(card.version).toBe(1);
    expect(confirmed.state.proposals[card.changed.proposal_id]!.status).toBe("confirmed");
    const event = confirmed.events[1] as Extract<ExmapEvent, { type: "proposal.confirmed" }>;
    expect(event.confirms_proposal_ids).toEqual([card.changed.proposal_id]);
    expect(confirmed.state.proposals[pid]!.status).toBe("applied");
    expect(confirmed.state.proposals[pid]!.affected_card_ids).toEqual([rule]);
    expect(confirmed.state.revisions.length).toBe(state.revisions.length);
    expect(refused(confirmed.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule], proposal_ids: [] })), ctx).reason).toBe("NOTHING_TO_CONFIRM");
    const mixed = run(confirmed.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule, story], proposal_ids: [] })), ctx);
    const mixedEvent = mixed.events[1] as Extract<ExmapEvent, { type: "proposal.confirmed" }>;
    expect(mixedEvent.effects.map((e) => e.card_id)).toEqual([story]);
    expect(mixedEvent.card_ids).toEqual([rule, story]);
    // a voice confirm copies the AI stamp
    const withUtt = run(mixed.state, { kind: "utterance.record", utterance: utterance("utt_yes", "Yes.", { speaker: "Priya" }) }, ctx).state;
    const e1 = run(withUtt, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E", rule_id: rule } })), ctx);
    const ex = createdCardId(e1.events);
    const voice = run(e1.state, propose(aiProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [ex], proposal_ids: [] }, { utts: ["utt_yes"], confidence: 0.5, stamp: stamps.rules("Priya") })), ctx);
    expect(voice.state.cards[ex]!.confirmation?.by).toEqual({ provider: "rules.v1", actor: "Priya", confidence: 0.5 });
    expect(refused(voice.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: ["card_404"], proposal_ids: [] })), ctx).reason).toBe("CARD_NOT_FOUND");
  });

  it("32. confirms_proposal_ids is filtered by affected cards: replace a rule with two examples", () => {
    const { ctx, state, rule } = smallMap();
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const e2 = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E2", rule_id: rule } })), ctx);
    const [ex1, ex2] = [createdCardId(e1.events), createdCardId(e2.events)];
    const pid = ctx.nextId("prop");
    const replaced = run(e2.state, propose(humanProposal(pid, { kind: "card.replace", card_id: rule, replacement: { text: "New rule." } })), ctx);
    const newId = createdCardId(replaced.events);
    const first = run(replaced.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [newId], proposal_ids: [] })), ctx);
    expect((first.events[1] as Extract<ExmapEvent, { type: "proposal.confirmed" }>).confirms_proposal_ids).toEqual([]);
    expect(first.state.proposals[pid]!.status).toBe("applied");
    const second = run(first.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [ex1, ex2], proposal_ids: [] })), ctx);
    expect((second.events[1] as Extract<ExmapEvent, { type: "proposal.confirmed" }>).confirms_proposal_ids).toEqual([pid]);
    expect(second.state.proposals[pid]!.status).toBe("confirmed");
    expect(example(second.state.cards[ex1]).needs_review).toBeNull();
  });

  it("33. confirm by proposal_ids reviews an act; create / clarifying -> PROPOSAL_NOT_CONFIRMABLE; both empty -> EMPTY_TARGET; already confirmed act -> NOTHING_TO_CONFIRM", () => {
    const { ctx, state, rule } = smallMap();
    const withUtt = run(state, { kind: "utterance.record", utterance: utterance("utt_rm", "Delete that rule.") }, ctx).state;
    const pid = ctx.nextId("prop");
    const removed = run(withUtt, propose(aiProposal(pid, { kind: "card.remove", card_id: rule }, { utts: ["utt_rm"], confidence: 0.5 })), ctx);
    expect(select.unreviewedActs(removed.state).map((p) => p.proposal.id)).toEqual([pid]);
    const reviewed = run(removed.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [pid] })), ctx);
    const event = reviewed.events[1] as Extract<ExmapEvent, { type: "proposal.confirmed" }>;
    expect(event.type).toBe("proposal.confirmed");
    expect(event.confirms_proposal_ids).toEqual([pid]);
    expect(event.effects).toEqual([]);
    expect(reviewed.state.proposals[pid]!.status).toBe("confirmed");
    expect(select.unreviewedActs(reviewed.state)).toEqual([]);
    const createPid = reviewed.state.cards[rule]!.created.proposal_id;
    expect(refused(reviewed.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [createPid] })), ctx).reason).toBe("PROPOSAL_NOT_CONFIRMABLE");
    const clarId = ctx.nextId("prop");
    const asked = run(reviewed.state, propose(clarifying(clarId, "remove", { template: { kind: "card.remove" }, utts: ["utt_rm"] })), ctx).state;
    expect(refused(asked, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [clarId] })), ctx).reason).toBe("PROPOSAL_NOT_CONFIRMABLE");
    expect(refused(asked, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [] })), ctx).reason).toBe("EMPTY_TARGET");
    expect(refused(asked, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [pid] })), ctx).reason).toBe("NOTHING_TO_CONFIRM");
    expect(refused(asked, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: ["prop_404"] })), ctx).reason).toBe("PROPOSAL_NOT_FOUND");
    expect(refused(asked, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [pid, pid] })), ctx).reason).toBe("BAD_SHAPE");
  });
});

describe("interpretation.reject", () => {
  it("34. reject of a create -> rejected/interpretation_rejected; of an update -> previous content, status, confirmation and changed restored at version+1; of a replace (either form) -> old card live, replacement's supersedes null", () => {
    const { ctx, state, rule } = smallMap();
    const withUtt = run(state, { kind: "utterance.record", utterance: utterance("utt_a", "Add a rule.") }, ctx).state;
    const createPid = ctx.nextId("prop");
    const created = run(withUtt, propose(aiProposal(createPid, { kind: "card.create", card: { kind: "rule", text: "AI rule." } }, { utts: ["utt_a"] })), ctx);
    const aiRule = createdCardId(created.events);
    const rejectPid = ctx.nextId("prop");
    const rejected = run(created.state, propose(humanProposal(rejectPid, { kind: "interpretation.reject", proposal_id: createPid })), ctx);
    expect(rejected.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.rejected"]);
    const card = rejected.state.cards[aiRule]!;
    expect(card.status).toBe("rejected");
    expect(card.rejection).toEqual({ kind: "interpretation_rejected", proposal_id: rejectPid, event_id: rejected.events[1]!.id });
    expect(rejected.state.proposals[createPid]!.status).toBe("rejected");
    expect(rejected.state.proposals[rejectPid]!.status).toBe("applied");
    expect(rejected.state.proposals[rejectPid]!.affected_card_ids).toEqual([aiRule]);
    expect(rejected.state.revisions.length).toBe(created.state.revisions.length + 1);
    expect(revisionHash(rejected.state)).toBe(revisionHash(withUtt));
    // update
    const confirmed = run(rejected.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule], proposal_ids: [] }, "Ana")), ctx).state;
    const updatePid = ctx.nextId("prop");
    const updated = run(confirmed, propose(aiProposal(updatePid, { kind: "card.update", card_id: rule, patch: { text: "Changed by AI." } }, { utts: ["utt_a"] })), ctx);
    const reject2 = ctx.nextId("prop");
    const restored = run(updated.state, propose(humanProposal(reject2, { kind: "interpretation.reject", proposal_id: updatePid })), ctx);
    const r = restored.state.cards[rule]!;
    expect(r.text).toBe(confirmed.cards[rule]!.text);
    expect(r.status).toBe("confirmed");
    expect(r.confirmation).toEqual(confirmed.cards[rule]!.confirmation);
    expect(r.changed).toEqual(confirmed.cards[rule]!.changed);
    expect(r.version).toBe(3);
    expect(r.restored_by?.proposal_id).toBe(reject2);
    expect(r.history.length).toBe(2);
    expect(revisionHash(restored.state)).toBe(revisionHash(confirmed));
    // replace by text
    const replacePid = ctx.nextId("prop");
    const replaced = run(restored.state, propose(aiProposal(replacePid, { kind: "card.replace", card_id: rule, replacement: { text: "Replacement." } }, { utts: ["utt_a"] })), ctx);
    const newId = createdCardId(replaced.events);
    const unreplaced = run(replaced.state, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: replacePid })), ctx).state;
    expect(unreplaced.cards[rule]!.status).toBe("confirmed");
    expect(unreplaced.cards[rule]!.superseded_by).toBeNull();
    expect(unreplaced.cards[newId]!.status).toBe("rejected");
    expect(unreplaced.cards[newId]!.rejection?.kind).toBe("interpretation_rejected");
    expect(revisionHash(unreplaced)).toBe(revisionHash(restored.state));
    // replace by an existing card
    const r2 = run(unreplaced, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Rule two." } })), ctx);
    const rule2 = createdCardId(r2.events);
    const replaceId = ctx.nextId("prop");
    const replaced2 = run(r2.state, propose(aiProposal(replaceId, { kind: "card.replace", card_id: rule, replacement_card_id: rule2 }, { utts: ["utt_a"] })), ctx);
    expect(replaced2.state.cards[rule2]!.supersedes).toBe(rule);
    const back = run(replaced2.state, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: replaceId })), ctx).state;
    expect(back.cards[rule]!.status).toBe("confirmed");
    expect(back.cards[rule2]!.supersedes).toBeNull();
    expect(back.cards[rule2]!.status).toBe("applied");
    expect(back.cards[rule2]!.version).toBe(1);
    expect(revisionHash(back)).toBe(revisionHash(r2.state));
  });

  it("35. reject refuses confirmed / pending / rejected proposals (PROPOSAL_NOT_REJECTABLE) and confirm proposals (PROPOSAL_KIND_NOT_REJECTABLE); rejecting an undo restores the pre-undo hash; rejecting a reject re-applies the update", () => {
    const s = scenario();
    const { ctx } = s;
    const afterConfirm = s.stateAfter("confirm_click");
    const rejectOf = (pid: string) => propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: pid }));
    expect(refused(afterConfirm, rejectOf(s.ids.p_amend!), ctx).reason).toBe("PROPOSAL_NOT_REJECTABLE"); // confirmed via the rule
    expect(refused(afterConfirm, rejectOf(s.ids.p_amend!), ctx).detail).toContain("confirmed");
    expect(refused(afterConfirm, rejectOf(s.ids.p_remove_nurse!), ctx).reason).toBe("PROPOSAL_NOT_REJECTABLE"); // rejected
    expect(refused(afterConfirm, rejectOf(s.ids.p_clar_amend!), ctx).reason).toBe("PROPOSAL_NOT_REJECTABLE"); // dismissed
    expect(refused(afterConfirm, rejectOf(s.ids.p_confirm_click!), ctx).reason).toBe("PROPOSAL_KIND_NOT_REJECTABLE");
    expect(refused(afterConfirm, rejectOf("prop_404"), ctx).reason).toBe("PROPOSAL_NOT_FOUND");
    // a pending proposal: proposal.made reduced on its own
    const pending = { ...afterConfirm, proposals: { ...afterConfirm.proposals, prop_p: { ...afterConfirm.proposals[s.ids.p_amend!]!, status: "pending" as const } } };
    expect(refused(pending, rejectOf("prop_p"), ctx).reason).toBe("PROPOSAL_NOT_REJECTABLE");
    // rejecting an undo restores the pre-undo hash
    const afterUndo1 = s.stateAfter("undo1");
    const beforeUndo1 = s.stateBefore("undo1");
    const rejectedUndo = run(afterUndo1, rejectOf(s.ids.p_undo1!), ctx).state;
    expect(revisionHash(rejectedUndo)).toBe(revisionHash(beforeUndo1));
    expect(rejectedUndo.cards[s.ids.ex_nurse!]!.status).toBe("superseded");
    expect(rejectedUndo.cards[s.ids.ex_nurse2!]!.supersedes).toBe(s.ids.ex_nurse);
    // rejecting a reject re-applies the update
    const { ctx: c2, state, rule } = smallMap();
    const updPid = c2.nextId("prop");
    const updated = run(state, propose(humanProposal(updPid, { kind: "card.update", card_id: rule, patch: { text: "v2" } })), c2);
    const rejPid = c2.nextId("prop");
    const rejected = run(updated.state, propose(humanProposal(rejPid, { kind: "interpretation.reject", proposal_id: updPid })), c2);
    expect(rejected.state.cards[rule]!.text).toBe(state.cards[rule]!.text);
    const reapplied = run(rejected.state, propose(humanProposal(c2.nextId("prop"), { kind: "interpretation.reject", proposal_id: rejPid })), c2).state;
    expect(reapplied.cards[rule]!.text).toBe("v2");
    expect(reapplied.cards[rule]!.version).toBe(4);
    expect(reapplied.cards[rule]!.changed.proposal_id).toBe(updPid);
    expect(revisionHash(reapplied)).toBe(revisionHash(updated.state));
    expect(reapplied.proposals[rejPid]!.status).toBe("rejected");
  });

  it("36. reject refuses when a later proposal touched an affected card (REJECT_NOT_LATEST); a rule update whose flagged example was confirmed in between is rejectable", () => {
    const { ctx, state, rule } = smallMap();
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const p1 = ctx.nextId("prop");
    const u1 = run(e1.state, propose(humanProposal(p1, { kind: "card.update", card_id: rule, patch: { text: "v2" } })), ctx);
    const u2 = run(u1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "v3" } })), ctx);
    const result = refused(u2.state, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: p1 })), ctx);
    expect(result.reason).toBe("REJECT_NOT_LATEST");
    expect(result.detail).toContain(rule);
    expect(select.isRejectable(u2.state, p1)).toBe(false);
    // the flagged example confirmed in between does not block
    const p2 = ctx.nextId("prop");
    const u3 = run(u2.state, propose(humanProposal(p2, { kind: "card.update", card_id: rule, patch: { text: "v4" } })), ctx);
    expect(example(u3.state.cards[ex1]).needs_review).not.toBeNull();
    const confirmedEx = run(u3.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [ex1], proposal_ids: [] })), ctx).state;
    expect(select.isRejectable(confirmedEx, p2)).toBe(true);
    const back = run(confirmedEx, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: p2 })), ctx).state;
    expect(back.cards[rule]!.text).toBe("v3");
    expect(example(back.cards[ex1]).status).toBe("confirmed");
    expect(example(back.cards[ex1]).confirmation).toEqual(confirmedEx.cards[ex1]!.confirmation);
    expect(example(back.cards[ex1]).needs_review).toBeNull();
    // a removal after the update also blocks it
    const removed = run(back, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    const latestUpdate = back.cards[rule]!.changed.proposal_id;
    expect(select.isRejectable(removed, latestUpdate)).toBe(false);
  });

  it("37. shape and intent refusals: INTENT_OPERATION_MISMATCH, DUPLICATE_ID, UTTERANCE_UNKNOWN, BAD_SHAPE naming the path, INVALID_CONFIDENCE never rounded", () => {
    const { ctx, state, rule } = smallMap();
    expect(refused(state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { intent: "add" })), ctx).reason).toBe("INTENT_OPERATION_MISMATCH");
    const existing = state.cards[rule]!.created.proposal_id;
    expect(refused(state, propose(humanProposal(existing, { kind: "card.remove", card_id: rule })), ctx).reason).toBe("DUPLICATE_ID");
    const twice = humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule });
    expect(refused(state, propose(twice, { ...twice }), ctx).reason).toBe("DUPLICATE_ID");
    expect(refused(state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { utts: ["utt_404"] })), ctx).reason).toBe("UTTERANCE_UNKNOWN");
    const extra = { ...humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }), bogus: 1 };
    const badKey = refused(state, propose(extra as never), ctx);
    expect(badKey.reason).toBe("BAD_SHAPE");
    expect(badKey.detail).toContain("command.proposals[0].bogus");
    const noLocal = { kind: "utterance.record", utterance: { ...utterance("utt_1", "x"), is_local: undefined } } as never;
    const missing = refused(state, noLocal, ctx);
    expect(missing.reason).toBe("BAD_SHAPE");
    expect(missing.detail).toContain("command.utterance.is_local");
    const unknownKind = refused(state, { kind: "nope" } as never, ctx);
    expect(unknownKind.reason).toBe("BAD_SHAPE");
    expect(unknownKind.detail).toContain("command.kind");
    expect(refused(state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { confidence: 0.333 })), ctx).reason).toBe("INVALID_CONFIDENCE");
    expect(refused(state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { confidence: 1.5 })), ctx).reason).toBe("INVALID_CONFIDENCE");
    expect(refused(state, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, candidates: [{ card_id: rule, label: "r", score: 1.5 }] })), ctx).reason).toBe("INVALID_CONFIDENCE");
    expect(refused(state, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, candidates: [{ card_id: rule, label: "r", score: 0.125 }] })), ctx).reason).toBe("INVALID_CONFIDENCE");
    expect(run(state, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, candidates: [{ card_id: rule, label: "r", score: 0.57 }] })), ctx).events.length).toBe(2);
    expect(refused(state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { intent: "destroy" as never })), ctx).reason).toBe("INVALID_ENUM");
    expect(refused(state, { kind: "utterance.record", utterance: utterance("utt_2", "x", { lane: "phone" as never }) }, ctx).reason).toBe("INVALID_ENUM");
    expect(refused(state, { kind: "utterance.record", utterance: utterance("utt_2", "x", { t_start_ms: 10, t_end_ms: 5 }) }, ctx).reason).toBe("INVALID_TIMING");
    expect(refused(state, { kind: "utterance.record", utterance: utterance("utt_2", "x", { t_start_ms: 1.5 }) }, ctx).reason).toBe("INVALID_TIMING");
    expect(refused(state, { kind: "utterance.record", utterance: utterance("utt_2", "   ") }, ctx).reason).toBe("EMPTY_TEXT");
    expect(refused(state, { kind: "utterance.record", utterance: utterance("utt_2", "x", { confidence: 0.999 }) }, ctx).reason).toBe("INVALID_CONFIDENCE");
    expect(refused(state, { kind: "utterance.record", utterance: utterance("", "x") }, ctx).reason).toBe("DUPLICATE_ID");
    const recorded = run(state, { kind: "utterance.record", utterance: utterance("utt_2", "x", { confidence: 0.99 }) }, ctx);
    expect(refused(recorded.state, { kind: "utterance.record", utterance: utterance("utt_2", "again") }, ctx).reason).toBe("DUPLICATE_ID");
    expect(Object.keys((recorded.events[0] as Extract<ExmapEvent, { type: "utterance.recorded" }>).utterance).length).toBe(10);
    // a human proposal must name its actor
    expect(refused(state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { stamp: { ...stamps.human("Sam"), actor: null } })), ctx).reason).toBe("ACTOR_REQUIRED");
  });

  it("38. the status machine is closed: every transition observed over the scenario is allowed; rejected/superseded are left only through proposal.rejected or undo.applied", () => {
    const s = scenario();
    const allowed = new Set([
      "proposed→applied", "applied→confirmed", "confirmed→applied", "applied→rejected", "confirmed→rejected", "applied→superseded", "confirmed→superseded",
      "rejected→applied", "rejected→confirmed", "superseded→applied", "superseded→confirmed",
    ]);
    const seen = new Set<string>();
    for (const event of s.events) {
      if (!("effects" in event)) continue;
      for (const effect of event.effects) {
        const from: CardStatus | null = effect.before?.status ?? null;
        if (from === null || from === effect.after.status) continue;
        const transition = `${from}→${effect.after.status}`;
        seen.add(transition);
        expect(allowed, `${transition} in ${event.type} ${event.id}`).toContain(transition);
        if (from === "rejected" || from === "superseded") expect(["proposal.rejected", "undo.applied"]).toContain(event.type);
        if (from === "proposed") expect(event.type).toBe("proposal.applied");
      }
    }
    expect(seen.size).toBeGreaterThanOrEqual(7);
    expect(seen).toContain("superseded→applied");
    expect(seen).toContain("rejected→applied");
  });

  it("39. restored_by and changed: after a reject that restores an earlier version, changed is the original author and restored_by the reject; a following update clears restored_by", () => {
    const { ctx, state, rule } = smallMap();
    const author = state.cards[rule]!.changed.proposal_id;
    const upd = ctx.nextId("prop");
    const updated = run(state, propose(humanProposal(upd, { kind: "card.update", card_id: rule, patch: { text: "v2" } })), ctx).state;
    const rej = ctx.nextId("prop");
    const restored = run(updated, propose(humanProposal(rej, { kind: "interpretation.reject", proposal_id: upd })), ctx);
    const card = restored.state.cards[rule]!;
    expect(card.changed.proposal_id).toBe(author);
    expect(card.restored_by).toEqual({ proposal_id: rej, event_id: restored.events[1]!.id, utterance_ids: [], classifier: "human" });
    const next = ctx.nextId("prop");
    const again = run(restored.state, propose(humanProposal(next, { kind: "card.update", card_id: rule, patch: { text: "v3" } })), ctx).state;
    expect(again.cards[rule]!.restored_by).toBeNull();
    expect(again.cards[rule]!.changed.proposal_id).toBe(next);
    // the scenario: the undone restore keeps the original author
    const s = scenario();
    const nurse2 = s.state.cards[s.ids.ex_nurse2!]!;
    expect(nurse2.changed.proposal_id).toBe(s.ids.p_ex_nurse2);
    expect(nurse2.restored_by?.proposal_id).toBe(s.ids.p_undo2);
  });

  it("apply is a pure function of (state, command, ctx): the same call twice yields the same events", () => {
    const { ctx: a } = testCtx();
    const { ctx: b } = testCtx();
    const command = propose(humanProposal("prop_1", { kind: "card.create", card: { kind: "story", text: "S" } }));
    const ra = apply(initialState("x"), command, a);
    const rb = apply(initialState("x"), command, b);
    expect(ra).toEqual(rb);
  });
});
