// TEST-PLAN §1 cases 58–63: the Definition of Done report, its details, acts, questions, statusLabel.
import { describe, expect, it } from "vitest";
import { dodReport } from "../../../src/core/dod.js";
import * as select from "../../../src/core/select.js";
import type { DodCheckId, MapState } from "../../../src/core/types.js";
import { aiProposal, clarifying, createdCardId, humanProposal, propose, refused, run, scenario, smallMap, stamps, utterance } from "./fixtures.js";

function check(state: MapState, id: DodCheckId, opts?: { requireHumanConfirm: boolean }) {
  const report = dodReport(state, opts);
  return report.checks.find((c) => c.id === id)!;
}

describe("dodReport", () => {
  it("58. names failing ids: unconfirmed rule, flagged example, dangling link, unanswered question, open clarification, unreviewed AI removal each fail exactly their check", () => {
    const { ctx, state, rule, story } = smallMap();
    const report = dodReport(state);
    expect(report.checks.map((c) => c.id)).toEqual(["story_rules_confirmed", "examples_reviewed", "changes_resolved", "questions_resolved", "final_version_recorded"]);
    expect(report.checks.map((c) => c.pass)).toEqual([false, true, true, true, true]);
    expect(check(state, "story_rules_confirmed").details).toEqual([`story ${story} is applied, not confirmed`, `rule ${rule} is applied, not confirmed`]);
    const confirmed = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [story, rule], proposal_ids: [] }, "Ana")), ctx).state;
    expect(check(confirmed, "story_rules_confirmed")).toMatchObject({ pass: true, details: [`story ${story} confirmed by Ana`, `rule ${rule} confirmed by Ana`] });
    expect(dodReport(confirmed).pass).toBe(true);
    // a flagged example
    const e1 = run(confirmed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const flagged = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "v2" } })), ctx);
    expect(check(flagged.state, "examples_reviewed").pass).toBe(false);
    expect(check(flagged.state, "examples_reviewed").details).toEqual([`example ${ex1} needs review: rule changed (event ${flagged.events[1]!.id})`]);
    expect(check(flagged.state, "changes_resolved").pass).toBe(true);
    // a dangling example link
    const unattached = run(flagged.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E2", rule_id: null } })), ctx);
    const ex2 = createdCardId(unattached.events);
    expect(check(unattached.state, "changes_resolved").details).toContain(`example ${ex2} is not attached to a rule`);
    expect(check(unattached.state, "changes_resolved").pass).toBe(false);
    // an unanswered question
    const q = run(unattached.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q?", about_card_id: rule } })), ctx);
    const qid = createdCardId(q.events);
    expect(check(q.state, "questions_resolved")).toMatchObject({ pass: false, details: [`question ${qid} is unanswered`] });
    // an open clarification
    const withUtt = run(q.state, { kind: "utterance.record", utterance: utterance("utt_1", "Delete that.") }, ctx).state;
    const asked = run(withUtt, propose(clarifying(ctx.nextId("prop"), "remove", { question: "Which example do you mean?", template: { kind: "card.remove" }, candidates: [{ card_id: ex1, label: "E1" }], utts: ["utt_1"] })), ctx).state;
    const clarId = select.openClarifications(asked)[0]!.id;
    expect(check(asked, "changes_resolved").details).toContain(`clarification ${clarId} is open: "Which example do you mean?"`);
    // an unreviewed AI removal
    const rm = ctx.nextId("prop");
    const removed = run(asked, propose(aiProposal(rm, { kind: "card.remove", card_id: ex2 }, { utts: ["utt_1"], confidence: 0.5 })), ctx).state;
    expect(check(removed, "changes_resolved").details).toContain(`removal ${rm} of example ${ex2} (rules.v1, 0.5) is not reviewed`);
    expect(check(removed, "changes_resolved").details).not.toContain(`example ${ex2} is not attached to a rule`); // no longer live
    // every detail names an id
    for (const c of dodReport(removed).checks) for (const d of c.details) expect(d).toMatch(/(card|prop|clar|sig|evt|revision)_?\d*/);
    // voice-confirmed rule detail and requireHumanConfirm
    const voice = run(removed, propose(aiProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [ex1], proposal_ids: [] }, { utts: ["utt_1"], confidence: 0.5, stamp: stamps.rules("Priya") })), ctx).state;
    expect(check(voice, "examples_reviewed").details).toEqual([`example ${ex1} confirmed by voice (rules.v1, 0.5, speaker Priya)`]);
    expect(check(voice, "examples_reviewed").pass).toBe(true);
    expect(check(voice, "examples_reviewed", { requireHumanConfirm: true }).pass).toBe(false);
    expect(check(voice, "examples_reviewed", { requireHumanConfirm: true }).details[0]).toContain("a person's confirmation is required");
    const voiceRule = run(voice, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "R2" } })), ctx);
    const rule2 = createdCardId(voiceRule.events);
    const voiceRuleConfirmed = run(voiceRule.state, propose(aiProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule2], proposal_ids: [] }, { utts: ["utt_1"], confidence: 0.5, stamp: stamps.rules(null) })), ctx).state;
    expect(check(voiceRuleConfirmed, "story_rules_confirmed").details).toContain(`rule ${rule2} confirmed by voice (rules.v1, 0.5, speaker unlabelled)`);
    expect(check(voiceRuleConfirmed, "story_rules_confirmed", { requireHumanConfirm: true }).pass).toBe(false);
    expect(check(voiceRuleConfirmed, "story_rules_confirmed").pass).toBe(false); // the first rule is applied again after v2
  });

  it("59. an AI removal, undo or reject blocks check 3 until confirmed by proposal id or rejected; a human removal does not; one resolved from a clarification by a person does not", () => {
    const s = scenario();
    const afterUndo2 = s.stateAfter("undo2");
    const unreviewed = select.unreviewedActs(afterUndo2).map((p) => p.proposal.id);
    expect(unreviewed).toEqual([s.ids.p_reject_prefix, s.ids.p_reject_replace, s.ids.p_undo1, s.ids.p_undo2]);
    expect(check(afterUndo2, "changes_resolved").pass).toBe(false);
    expect(check(afterUndo2, "changes_resolved").details).toContain(`undo ${s.ids.p_undo1} (one step back) (rules.v1, 1) is not reviewed`);
    expect(check(afterUndo2, "changes_resolved").details).toContain(`rejection ${s.ids.p_reject_prefix} of proposal ${s.ids.p_remove_nurse} (rules.v1, 1) is not reviewed`);
    expect(check(afterUndo2, "changes_resolved").details).toContain(`removal ${s.ids.p_remove_q} of question ${s.ids.q_inprogress} (rules.v1, 1) is reviewed`); // reviewed by voice
    expect(unreviewed).not.toContain(s.ids.p_resolved_remove); // resolved from a clarification by Sam
    expect(unreviewed).not.toContain(s.ids.p_remove_nurse); // rejected
    const afterAccept = s.stateAfter("accept_acts");
    expect(select.unreviewedActs(afterAccept)).toEqual([]);
    expect(check(afterAccept, "changes_resolved").pass).toBe(true);
    // a human removal needs no review; rejecting an AI act clears it too
    const { ctx, state, rule } = smallMap();
    const human = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    expect(select.unreviewedActs(human)).toEqual([]);
    const withUtt = run(state, { kind: "utterance.record", utterance: utterance("utt_1", "Delete that.") }, ctx).state;
    const rm = ctx.nextId("prop");
    const ai = run(withUtt, propose(aiProposal(rm, { kind: "card.remove", card_id: rule }, { utts: ["utt_1"] })), ctx).state;
    expect(select.unreviewedActs(ai).map((p) => p.proposal.id)).toEqual([rm]);
    const rejected = run(ai, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: rm })), ctx).state;
    expect(select.unreviewedActs(rejected)).toEqual([]);
    expect(check(rejected, "changes_resolved").pass).toBe(true);
    // an AI undo blocks until reviewed
    const upd = run(rejected, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "v2" } })), ctx).state;
    const undoId = ctx.nextId("prop");
    const undone = run(upd, propose(aiProposal(undoId, { kind: "undo", to_revision_seq: null }, { utts: ["utt_1"], stamp: stamps.claude(), confidence: 0.8 })), ctx).state;
    expect(check(undone, "changes_resolved").details).toContain(`undo ${undoId} (one step back) (claude, 0.8) is not reviewed`);
    const reviewed = run(undone, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [], proposal_ids: [undoId] })), ctx).state;
    expect(check(reviewed, "changes_resolved").pass).toBe(true);
  });

  it("60. an AI-recorded answer does not resolve a question until the card is confirmed", () => {
    const { ctx, state, rule } = smallMap();
    const q = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q?", about_card_id: rule } })), ctx);
    const qid = createdCardId(q.events);
    const withUtt = run(q.state, { kind: "utterance.record", utterance: utterance("utt_1", "Yes, they can.") }, ctx).state;
    const answered = run(withUtt, propose(aiProposal(ctx.nextId("prop"), { kind: "card.update", card_id: qid, patch: { answer: "Yes, they can." } }, { utts: ["utt_1"] })), ctx).state;
    expect(check(answered, "questions_resolved").pass).toBe(false);
    expect(check(answered, "questions_resolved").details).toEqual([`question ${qid} is answered but applied, not confirmed`]);
    const confirmed = run(answered, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [qid], proposal_ids: [] }, "Sam")), ctx).state;
    expect(check(confirmed, "questions_resolved")).toMatchObject({ pass: true, details: [`question ${qid} answered and confirmed by Sam`] });
    const voice = run(answered, propose(aiProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [qid], proposal_ids: [] }, { utts: ["utt_1"], stamp: stamps.rules("Priya"), confidence: 0.5 })), ctx).state;
    expect(check(voice, "questions_resolved").pass).toBe(true);
    expect(check(voice, "questions_resolved", { requireHumanConfirm: true }).pass).toBe(false);
  });

  it("61. accepting a question resolves check 4 with 'accepted outstanding', never 'answered'; QUESTION_ALREADY_RESOLVED; REASON_REQUIRED", () => {
    const { ctx, state, rule } = smallMap();
    const q = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q?", about_card_id: rule } })), ctx);
    const qid = createdCardId(q.events);
    const accepted = run(q.state, { kind: "question.accept", question_id: qid, by: "Sam", reason: "To be settled with the practice manager" }, ctx);
    expect(accepted.events.map((e) => e.type)).toEqual(["question.accepted_outstanding"]);
    expect(accepted.state.revisions.length).toBe(q.state.revisions.length);
    const card = accepted.state.cards[qid]!;
    expect(card.kind === "question" && card.answer).toBeNull();
    expect(card.version).toBe(1);
    expect(card.kind === "question" && card.accepted_outstanding).toEqual({ by: "Sam", reason: "To be settled with the practice manager", event_id: accepted.events[0]!.id });
    const c4 = check(accepted.state, "questions_resolved");
    expect(c4.pass).toBe(true);
    expect(c4.details).toEqual([`question ${qid} accepted outstanding by Sam: To be settled with the practice manager`]);
    expect(c4.details.join(" ")).not.toContain("answered");
    expect(select.openQuestions(accepted.state).map((x) => x.id)).toEqual([qid]); // still unanswered
    expect(select.counts(accepted.state)).toMatchObject({ open_questions: 1, accepted_questions: 1 });
    expect(refused(accepted.state, { kind: "question.accept", question_id: qid, by: "Sam", reason: "again" }, ctx).reason).toBe("QUESTION_ALREADY_RESOLVED");
    const answered = run(q.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: qid, patch: { answer: "No." } })), ctx).state;
    expect(refused(answered, { kind: "question.accept", question_id: qid, by: "Sam", reason: "r" }, ctx).reason).toBe("QUESTION_ALREADY_RESOLVED");
    expect(refused(q.state, { kind: "question.accept", question_id: qid, by: "Sam", reason: "  " }, ctx).reason).toBe("REASON_REQUIRED");
    expect(refused(q.state, { kind: "question.accept", question_id: qid, by: "", reason: "r" }, ctx).reason).toBe("ACTOR_REQUIRED");
    expect(refused(q.state, { kind: "question.accept", question_id: rule, by: "Sam", reason: "r" }, ctx).reason).toBe("KIND_MISMATCH");
    expect(refused(q.state, { kind: "question.accept", question_id: "card_404", by: "Sam", reason: "r" }, ctx).reason).toBe("CARD_NOT_FOUND");
    const removed = run(q.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: qid })), ctx).state;
    expect(refused(removed, { kind: "question.accept", question_id: qid, by: "Sam", reason: "r" }, ctx).reason).toBe("CARD_NOT_LIVE");
  });

  it("62. sign-off is refused with the failing checks: SIGNOFF_DOD_FAILED carries checks; no events", () => {
    const { ctx, calls, state } = smallMap();
    const before = calls.nextId;
    const result = refused(state, { kind: "signoff.record", reviewer: { name: "Sam" }, confirmation_text: "I have reviewed the complete requirement and confirm it represents the agreed intent.", cited_revision_hash: state.revisions[state.revisions.length - 1]!.hash }, ctx);
    expect(result.reason).toBe("SIGNOFF_DOD_FAILED");
    expect(result.checks?.pass).toBe(false);
    expect(result.checks?.checks.length).toBe(5);
    expect(result.checks?.checks[0]!.pass).toBe(false);
    expect(result.detail).toContain("story_rules_confirmed");
    expect(calls.nextId).toBe(before);
    expect("events" in result).toBe(false);
  });

  it("63. statusLabel never returns 'rejected': every rejected card in the scenario labels as removed / interpretation rejected / undone", () => {
    const s = scenario();
    const labels = new Set<string>();
    for (const card of Object.values(s.state.cards)) {
      const label = select.statusLabel(card);
      labels.add(label);
      expect(label).not.toBe("rejected");
      if (card.status === "rejected") expect(["removed", "interpretation rejected", "undone"]).toContain(label);
    }
    expect(select.statusLabel(s.state.cards[s.ids.ex_gp!]!)).toBe("removed");
    expect(select.statusLabel(s.state.cards[s.ids.ex_gp2!]!)).toBe("interpretation rejected");
    expect(select.statusLabel(s.state.cards[s.ids.ex_nurse!]!)).toBe("superseded");
    expect(select.statusLabel(s.state.cards[s.ids.rule!]!)).toBe("confirmed");
    expect(select.statusLabel(s.state.cards[s.ids.q_twice!]!)).toBe("applied");
    expect(labels).toContain("superseded");
    const undone = s.stateAfter("undo1");
    for (const step of s.steps) for (const card of Object.values(step.state.cards)) expect(select.statusLabel(card)).not.toBe("rejected");
    expect(undone.cards[s.ids.ex_nurse!]!.status).toBe("applied");
  });
});
