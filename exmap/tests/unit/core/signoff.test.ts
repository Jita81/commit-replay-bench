// TEST-PLAN §1 cases 64–70: the sign-off, the gate, invalidation and re-verification.
import { describe, expect, it } from "vitest";
import { dodReport, isHumanVerified, SIGNOFF_CONFIRMATION_TEXT } from "../../../src/core/dod.js";
import * as select from "../../../src/core/select.js";
import type { ExmapEvent, MapState } from "../../../src/core/types.js";
import { aiProposal, classify, clarifying, humanProposal, propose, refused, revisionHash, run, scenario, signoff, utterance } from "./fixtures.js";

const s = scenario();
const signed = s.stateAfter("signoff");

describe("signoff", () => {
  it("64. sign-off requires the exact sentence and a reviewer name", () => {
    const ready = s.stateBefore("signoff");
    expect(refused(ready, signoff(ready, "Sam", "I reviewed it."), s.ctx).reason).toBe("SIGNOFF_CONFIRMATION_TEXT_MISMATCH");
    expect(refused(ready, signoff(ready, "  ", SIGNOFF_CONFIRMATION_TEXT), s.ctx).reason).toBe("SIGNOFF_REVIEWER_REQUIRED");
    expect(run(ready, signoff(ready, "Sam", `  ${SIGNOFF_CONFIRMATION_TEXT}\n`), s.ctx).events[0]!.type).toBe("signoff.recorded");
  });

  it("65. sign-off with a stale revision hash -> SIGNOFF_STALE_REVISION", () => {
    const ready = s.stateBefore("signoff");
    const stale = { ...signoff(ready), cited_revision_hash: ready.revisions[1]!.hash } as Extract<ReturnType<typeof signoff>, { kind: "signoff.record" }>;
    const result = refused(ready, stale, s.ctx);
    expect(result.reason).toBe("SIGNOFF_STALE_REVISION");
    expect(result.detail).toContain(revisionHash(ready));
  });

  it("66. sign-off records reviewer, revision stamp, evidence head and the five checks; isHumanVerified becomes true", () => {
    const step = s.step("signoff");
    const event = step.events[0] as Extract<ExmapEvent, { type: "signoff.recorded" }>;
    expect(step.events.length).toBe(1);
    expect(event.signoff.id).toBe(s.ids.sig1);
    expect(event.signoff.reviewer).toEqual({ name: "Sam" });
    expect(event.signoff.confirmation_text).toBe(SIGNOFF_CONFIRMATION_TEXT);
    expect(event.signoff.revision).toEqual({ seq: step.before.revisions.length - 1, hash: revisionHash(step.before) });
    expect(event.signoff.evidence).toEqual({ head_seq: step.before.head.seq, head_hash: step.before.head.hash });
    expect(event.signoff.checks.pass).toBe(true);
    expect(event.signoff.checks.checks.map((c) => c.id)).toEqual(["story_rules_confirmed", "examples_reviewed", "changes_resolved", "questions_resolved", "final_version_recorded"]);
    const recorded = signed.signoffs[0]!;
    expect(recorded.status).toBe("active");
    expect(recorded.event_id).toBe(event.id);
    expect(recorded.at).toBe(event.at);
    expect(recorded.invalidated).toBeNull();
    expect(select.activeSignoff(signed)).toBe(recorded);
    expect(isHumanVerified(signed)).toBe(true);
    expect(isHumanVerified(step.before)).toBe(false);
    expect(signed.revisions.length).toBe(step.before.revisions.length);
  });

  it("67. a later content change emits signoff.invalidated in the same batch and isHumanVerified becomes false: update, remove, replace (both forms), refine, reject, undo", () => {
    const { ctx } = s;
    const rule = s.ids.rule!;
    const ex = s.ids.ex_nurse2!;
    const withUtt = run(signed, { kind: "utterance.record", utterance: utterance("utt_z", "Change it.") }, ctx).state;
    const cases: Array<[string, MapState, Parameters<typeof propose>[0]]> = [
      ["update", withUtt, humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "Changed." } })],
      ["remove", withUtt, humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: ex })],
      ["replace by text", withUtt, humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule, replacement: { text: "Replaced." } })],
      ["refine", withUtt, humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: "GP", definition: "general practitioner" })],
      ["undo", withUtt, humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: null })],
    ];
    for (const [name, state, proposal] of cases) {
      const result = run(state, propose(proposal), ctx);
      const types = result.events.map((e) => e.type);
      expect(types, name).toContain("signoff.invalidated");
      expect(types.indexOf("signoff.invalidated"), name).toBe(2);
      expect(isHumanVerified(result.state), name).toBe(false);
      expect(result.state.signoffs[0]!.status, name).toBe("invalidated");
      expect(result.state.signoffs[0]!.invalidated?.by_event_id, name).toBe(result.events[1]!.id);
    }
    // replace by an existing card: add a second example first (that create itself invalidates), re-sign, then replace
    const e2 = run(withUtt, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "Another example.", rule_id: rule } })), ctx);
    expect(e2.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "signoff.invalidated"]);
    const newId = e2.events[0]!.type === "proposal.made" ? e2.events[0]!.effects[0]!.card_id : "";
    const reviewed = run(e2.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [newId], proposal_ids: [] })), ctx).state;
    const resigned = run(reviewed, signoff(reviewed), ctx).state;
    expect(isHumanVerified(resigned)).toBe(true);
    const byId = run(resigned, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: ex, replacement_card_id: newId })), ctx);
    expect(byId.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "signoff.invalidated"]);
    expect(isHumanVerified(byId.state)).toBe(false);
    // reject of an applied AI act after sign-off
    const aiUpd = ctx.nextId("prop");
    const aiUpdated = run(resigned, propose(aiProposal(aiUpd, { kind: "card.update", card_id: rule, patch: { text: "AI changed it." } }, { utts: ["utt_z"] })), ctx);
    expect(aiUpdated.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "signoff.invalidated"]);
    const rejected = run(aiUpdated.state, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: aiUpd })), ctx);
    expect(rejected.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.rejected"]); // nothing active to invalidate
    expect(isHumanVerified(rejected.state)).toBe(false);
    // once every card an AI update touched is confirmed the update is confirmed too, so after a valid sign-off the only
    // rejectable proposal is a replace by an already-confirmed existing card (its effects leave nothing to confirm)
    const replacePid = ctx.nextId("prop");
    const replacedById = run(resigned, propose(aiProposal(replacePid, { kind: "card.replace", card_id: ex, replacement_card_id: newId }, { utts: ["utt_z"] })), ctx).state;
    expect(replacedById.proposals[replacePid]!.status).toBe("applied");
    expect(dodReport(replacedById).pass).toBe(true);
    const resigned2 = run(replacedById, signoff(replacedById), ctx).state;
    expect(isHumanVerified(resigned2)).toBe(true);
    expect(select.isRejectable(resigned2, replacePid)).toBe(true);
    const rejectedAfter = run(resigned2, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: replacePid })), ctx);
    expect(rejectedAfter.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.rejected", "signoff.invalidated"]);
    expect(isHumanVerified(rejectedAfter.state)).toBe(false);
    expect(rejectedAfter.state.cards[ex]!.status).toBe("confirmed");
  });

  it("68. a new utterance, a classification, a proposal.made alone, a confirm, a question acceptance or an export-options change does not invalidate", () => {
    const { ctx } = s;
    const u = run(signed, { kind: "utterance.record", utterance: utterance("utt_n", "Hello again.") }, ctx);
    expect(u.events.map((e) => e.type)).toEqual(["utterance.recorded"]);
    const c = run(u.state, classify("utt_n", "none"), ctx);
    expect(c.events.map((e) => e.type)).toEqual(["utterance.classified"]);
    const asked = run(c.state, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, utts: ["utt_n"] })), ctx);
    expect(asked.events.map((e) => e.type)).toEqual(["proposal.made", "clarification.asked"]);
    expect(select.activeSignoff(asked.state)?.id).toBe(s.ids.sig1);
    const q2 = run(signed, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [s.ids.q_twice!], proposal_ids: [] })), ctx);
    expect(q2.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.confirmed"]);
    expect(isHumanVerified(q2.state)).toBe(true);
    const options = run(q2.state, { kind: "export.options_set", options: { capability_class: "bug.fix", kind: "code", size_estimate: "S", facts: [], by: "Sam" } }, ctx);
    expect(options.events.map((e) => e.type)).toEqual(["export.options_set"]);
    expect(isHumanVerified(options.state)).toBe(true);
    // a question acceptance (on a fresh unaccepted question) does not invalidate either
    const beforeAccept = s.stateBefore("accept_question");
    const accepted = run(beforeAccept, { kind: "question.accept", question_id: s.ids.q_twice!, by: "Sam", reason: "later" }, ctx);
    expect(accepted.events.map((e) => e.type)).toEqual(["question.accepted_outstanding"]);
    expect(accepted.state.revisions.length).toBe(beforeAccept.revisions.length);
  });

  it("69. a needs_clarification proposal after sign-off does not invalidate but makes isHumanVerified false; dismissing it makes it true again; the same for an AI removal applied-then-rejected", () => {
    const { ctx } = s;
    const withUtt = run(signed, { kind: "utterance.record", utterance: utterance("utt_k", "Delete that one.") }, ctx).state;
    const asked = run(withUtt, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, candidates: [{ card_id: s.ids.ex_nurse2!, label: "n" }], utts: ["utt_k"] })), ctx);
    expect(asked.events.map((e) => e.type)).toEqual(["proposal.made", "clarification.asked"]);
    expect(select.activeSignoff(asked.state)?.status).toBe("active");
    expect(isHumanVerified(asked.state)).toBe(false);
    expect(dodReport(asked.state).checks[2]!.pass).toBe(false);
    const clarId = select.openClarifications(asked.state)[0]!.id;
    const dismissed = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "dismiss", reason: "Nothing to delete." }, actor: "Sam" }, ctx).state;
    expect(isHumanVerified(dismissed)).toBe(true);
    expect(dismissed.signoffs.length).toBe(1);
    // an AI removal applied then rejected: the reject is itself an unreviewed AI act when the AI proposed it
    const rm = ctx.nextId("prop");
    const removed = run(withUtt, propose(aiProposal(rm, { kind: "card.remove", card_id: s.ids.ex_nurse2! }, { utts: ["utt_k"] })), ctx);
    expect(removed.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied", "signoff.invalidated"]);
    const rj = ctx.nextId("prop");
    const rejected = run(removed.state, propose(aiProposal(rj, { kind: "interpretation.reject", proposal_id: rm }, { utts: ["utt_k"] })), ctx).state;
    expect(revisionHash(rejected)).toBe(revisionHash(signed));
    expect(isHumanVerified(rejected)).toBe(false); // the sign-off was invalidated by the removal
    const resigned = run(run(rejected, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [rj] })), ctx).state, signoff(rejected), ctx).state;
    expect(isHumanVerified(resigned)).toBe(true);
    // with an active sign-off: AI undo-then-reject by voice leaves the gate false until the reject act is reviewed
    const undoId = ctx.nextId("prop");
    const undone = run(resigned, propose(aiProposal(undoId, { kind: "undo", to_revision_seq: null }, { utts: ["utt_k"] })), ctx).state;
    expect(isHumanVerified(undone)).toBe(false);
    const rejUndo = ctx.nextId("prop");
    const back = run(undone, propose(aiProposal(rejUndo, { kind: "interpretation.reject", proposal_id: undoId }, { utts: ["utt_k"] })), ctx).state;
    expect(revisionHash(back)).toBe(revisionHash(resigned));
    expect(select.activeSignoff(back)).toBeNull();
    expect(select.unreviewedActs(back).map((p) => p.proposal.id)).toEqual([rejUndo]);
    const reviewedBack = run(back, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [rejUndo] })), ctx).state;
    expect(dodReport(reviewedBack).pass).toBe(true);
    expect(isHumanVerified(reviewedBack)).toBe(false); // a revision happened: it needs a new sign-off
    expect(isHumanVerified(run(reviewedBack, signoff(reviewedBack), ctx).state)).toBe(true);
  });

  it("70. re-sign-off after invalidation succeeds; the old sign-off stays invalidated with by_event_id; a second sign-off on the same revision -> SIGNOFF_ALREADY_ACTIVE", () => {
    const step = s.step("signoff2");
    expect(step.events.map((e) => e.type)).toEqual(["signoff.recorded"]);
    expect(s.state.signoffs.map((x) => [x.id, x.status])).toEqual([[s.ids.sig1, "invalidated"], [s.ids.sig2, "active"]]);
    const old = s.state.signoffs[0]!;
    const amend = s.step("amend2");
    expect(old.invalidated?.by_event_id).toBe(amend.events[1]!.id);
    expect(old.invalidated?.event_id).toBe(amend.events[2]!.id);
    expect(old.invalidated?.to_revision).toEqual((amend.events[1] as Extract<ExmapEvent, { type: "proposal.applied" }>).revision);
    expect(select.lastSignoff(s.state)?.id).toBe(s.ids.sig2);
    expect(select.activeSignoff(s.state)?.id).toBe(s.ids.sig2);
    expect(isHumanVerified(s.state)).toBe(true);
    expect(refused(s.state, signoff(s.state, "Priya"), s.ctx).reason).toBe("SIGNOFF_ALREADY_ACTIVE");
    expect(isHumanVerified(s.stateAfter("amend2"))).toBe(false);
    expect(isHumanVerified(s.stateAfter("review_again"))).toBe(false);
  });
});
