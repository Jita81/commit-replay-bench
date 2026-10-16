// TEST-PLAN §1 cases 40–42: a multi-proposal batch is one step, atomic, and invalidates a sign-off once.
import { describe, expect, it } from "vitest";
import * as select from "../../../src/core/select.js";
import type { ExmapEvent } from "../../../src/core/types.js";
import { aiProposal, createdCardId, humanProposal, propose, refused, run, scenario, signoff, smallMap, utterance } from "./fixtures.js";

describe("batches", () => {
  it("40. proposal.propose with two proposals is one batch: [made, rejected, made, applied], one batch_id, two revisions, undoTarget before both", () => {
    const s = scenario();
    const step = s.step("batch");
    expect(step.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.rejected", "proposal.made", "proposal.applied"]);
    const batchId = step.events[0]!.id;
    for (const e of step.events) expect(e.batch_id).toBe(batchId);
    const revisions = step.state.revisions.slice(-2);
    expect(revisions.map((r) => r.batch_id)).toEqual([batchId, batchId]);
    expect(revisions.map((r) => r.cause)).toEqual(["proposal.rejected", "proposal.applied"]);
    expect(select.undoTarget(step.state, 1)).toBe(step.before.revisions[step.before.revisions.length - 1]!.seq);
    expect(select.undoTarget(step.state, 1)).toBe(step.state.revisions.length - 3);
    expect(revisions.every((r) => r.source_utterance_ids.length === 1 && r.source_utterance_ids[0] === s.ids.u11)).toBe(true);
  });

  it("41. a batch is all or nothing: proposal 2 refused -> no events, nextId not called, detail starts 'proposal 2 of 2'; proposal 2 sees proposal 1's result", () => {
    const { ctx, calls, state, rule } = smallMap();
    const removed = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    const withUtt = run(removed, { kind: "utterance.record", utterance: utterance("utt_b", "No. Delete it.") }, ctx).state;
    const command = propose(
      aiProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "A new rule." } }, { utts: ["utt_b"] }),
      aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { utts: ["utt_b"] }),
    );
    const before = calls.nextId;
    const result = refused(withUtt, command, ctx);
    expect(result.reason).toBe("CARD_NOT_LIVE");
    expect(result.detail.startsWith("proposal 2 of 2: ")).toBe(true);
    expect(calls.nextId).toBe(before);
    // proposal 2 is validated against the state after proposal 1: an update then an identical update -> NO_CHANGE at 2 of 2
    const created = run(withUtt, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Created." } })), ctx);
    const ruleId = createdCardId(created.events);
    const identical = refused(created.state, propose(
      aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: ruleId, patch: { text: "Amended." } }, { utts: ["utt_b"] }),
      aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: ruleId, patch: { text: "Amended." } }, { utts: ["utt_b"] }),
    ), ctx);
    expect(identical.reason).toBe("NO_CHANGE");
    expect(identical.detail.startsWith("proposal 2 of 2: ")).toBe(true);
    const ok = run(created.state, propose(
      aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: ruleId, patch: { text: "Amended." } }, { utts: ["utt_b"] }),
      aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: ruleId, patch: { text: "Amended twice." } }, { utts: ["utt_b"] }),
    ), ctx);
    expect(ok.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "proposal.made", "proposal.applied"]);
    expect(ok.state.cards[ruleId]!.text).toBe("Amended twice.");
    expect(ok.state.cards[ruleId]!.version).toBe(3);
    expect(ok.events.every((e) => e.batch_id === ok.events[0]!.id)).toBe(true);
    // ids are minted in pass 2 only, so a batch cannot name a card its own earlier proposal creates (INTEGRATION-NOTES)
    expect(refused(created.state, propose(
      aiProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Another." } }, { utts: ["utt_b"] }),
      aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: ruleId.replace(/\d+$/, (n) => String(Number(n) + 1)), patch: { text: "x" } }, { utts: ["utt_b"] }),
    ), ctx).reason).toBe("CARD_NOT_FOUND");
    // a one-proposal refusal carries no prefix
    expect(refused(withUtt, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { utts: ["utt_b"] })), ctx).detail.startsWith("proposal ")).toBe(false);
  });

  it("42. signoff.invalidated is appended once per batch, after the first revision-creating event", () => {
    const s = scenario();
    const { ctx } = s;
    const signed = s.stateAfter("signoff");
    expect(select.activeSignoff(signed)?.id).toBe(s.ids.sig1);
    const withUtt = run(signed, { kind: "utterance.record", utterance: utterance("utt_x", "No, and delete the question.") }, ctx).state;
    const batch = run(withUtt, propose(
      aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: s.ids.rule!, patch: { text: "Changed after sign-off." } }, { utts: ["utt_x"] }),
      aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: s.ids.q_twice! }, { utts: ["utt_x"] }),
    ), ctx);
    expect(batch.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "signoff.invalidated", "proposal.made", "proposal.applied"]);
    const inv = batch.events[2] as Extract<ExmapEvent, { type: "signoff.invalidated" }>;
    const first = batch.events[1] as Extract<ExmapEvent, { type: "proposal.applied" }>;
    expect(inv.signoff_id).toBe(s.ids.sig1);
    expect(inv.by_event_id).toBe(first.id);
    expect(inv.from_revision).toEqual(signed.signoffs[0]!.revision);
    expect(inv.to_revision).toEqual(first.revision);
    expect(inv.batch_id).toBe(batch.events[0]!.id);
    expect(batch.state.signoffs[0]!.status).toBe("invalidated");
    expect(batch.state.signoffs[0]!.invalidated).toEqual({ event_id: inv.id, by_event_id: first.id, to_revision: first.revision });
    // the scenario's own invalidation sits inside the amend2 batch
    expect(s.step("amend2").events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "signoff.invalidated"]);
    // after re-sign-off the earlier one stays invalidated and only the last is active
    expect(s.state.signoffs.map((x) => x.status)).toEqual(["invalidated", "active"]);
    expect(refused(s.state, signoff(s.state), ctx).reason).toBe("SIGNOFF_ALREADY_ACTIVE");
  });
});
