// TEST-PLAN §1 cases 72–73: the selectors the bridge relies on; apply is atomic and agrees with replay.
import { describe, expect, it } from "vitest";
import { apply } from "../../../src/core/apply.js";
import { createEngine } from "../../../src/core/index.js";
import { replay } from "../../../src/core/replay.js";
import * as select from "../../../src/core/select.js";
import type { Command, Counts } from "../../../src/core/types.js";
import { sha256 } from "../../../src/server/hash.js";
import { aiProposal, humanProposal, propose, refused, run, scenario, smallMap, testCtx, utterance } from "./fixtures.js";

describe("select", () => {
  it("72. lastAppliedProposal, isRejectable and counts over the scenario", () => {
    const s = scenario();
    const afterVoice = s.stateAfter("confirm_voice");
    // default: the latest applied AI proposal, skipping human ones (confirm_click is human; confirm_voice is applied AI)
    expect(select.lastAppliedProposal(afterVoice)?.proposal.id).toBe(s.ids.p_confirm_voice);
    const afterClick = s.stateAfter("confirm_click");
    expect(select.lastAppliedProposal(afterClick)?.proposal.id).toBe(s.ids.p_undo2);
    expect(select.lastAppliedProposal(afterClick, { aiOnly: false })?.proposal.id).toBe(s.ids.p_confirm_click);
    // statuses applied | confirmed returns a confirmed one when it is the latest
    const afterReview = s.stateAfter("review_again");
    expect(select.lastAppliedProposal(afterReview, { statuses: ["applied", "confirmed"] })?.proposal.id).toBe(s.ids.p_amend2);
    expect(select.lastAppliedProposal(afterReview)?.proposal.id).toBe(s.ids.p_q_twice);
    expect(select.lastAppliedProposal(s.stateAfter("u1"))).toBeNull();
    // isRejectable
    expect(select.isRejectable(afterReview, s.ids.p_amend2!)).toBe(false); // confirmed
    expect(select.isRejectable(afterReview, s.ids.p_confirm_voice!)).toBe(false); // confirm proposal
    expect(select.isRejectable(afterReview, s.ids.p_story!)).toBe(false); // human (its card is confirmed anyway)
    expect(select.isRejectable(afterReview, s.ids.p_remove_nurse!)).toBe(false); // rejected
    expect(select.isRejectable(afterReview, s.ids.p_q_twice!)).toBe(true);
    expect(select.isRejectable(afterReview, s.ids.p_ex_gp!)).toBe(false); // its card was removed since
    const afterAmend = s.stateAfter("amend");
    expect(select.isRejectable(afterAmend, s.ids.p_amend!)).toBe(true);
    expect(select.isRejectable(s.stateAfter("amend2"), s.ids.p_amend!)).toBe(false); // updated since
    expect(select.isRejectable(afterReview, "prop_404")).toBe(false);
    // a human proposal is rejectable by the rules when applied and latest
    const { ctx, state, rule } = smallMap();
    expect(select.isRejectable(state, state.cards[rule]!.created.proposal_id)).toBe(true);
    expect(select.isRejectable(run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule], proposal_ids: [] })), ctx).state, state.cards[rule]!.created.proposal_id)).toBe(false);
    // counts, hand-counted over the final scenario state
    const expected: Counts = {
      utterances: 21, classified: 20, actionable: 20, classifier_errors: 0, fallbacks: 0,
      cards_live: 4, by_kind: { story: 1, rule: 1, example: 1, question: 1 }, needs_review: 0, open_questions: 1, accepted_questions: 1,
      open_clarifications: 0, unreviewed_acts: 0, revision_seq: s.state.revisions.length - 1, events: s.events.length,
    };
    expect(select.counts(s.state)).toEqual(expected);
    expect(select.counts(s.stateAfter("clar_remove"))).toMatchObject({ open_clarifications: 1, cards_live: 5, by_kind: { story: 1, rule: 1, example: 2, question: 1 } });
    expect(select.counts(s.stateAfter("amend"))).toMatchObject({ needs_review: 1 });
    expect(select.counts(s.stateAfter("undo2"))).toMatchObject({ unreviewed_acts: 4 });
    // the other selectors
    expect(select.story(s.state)?.id).toBe(s.ids.story);
    expect(select.cardsByKind(s.state, "example").map((c) => c.id)).toEqual([s.ids.ex_nurse2]);
    expect(select.examplesOf(s.state, s.ids.rule!).map((c) => c.id)).toEqual([s.ids.ex_nurse2]);
    expect(select.questionsAbout(s.state, s.ids.rule!).map((c) => c.id)).toEqual([s.ids.q_twice]);
    expect(select.liveCards(s.state).map((c) => c.id)).toEqual([s.ids.story, s.ids.rule, s.ids.ex_nurse2, s.ids.q_twice]);
    expect(select.pendingProposals(s.state)).toEqual([]);
    expect(select.examplesNeedingReview(s.stateAfter("amend2")).map((c) => c.id)).toEqual([s.ids.ex_nurse2]);
    expect(select.revisions(s.state).every((r) => !("snapshot" in r))).toBe(true);
    expect(select.revisions(s.state).length).toBe(s.state.revisions.length);
    expect(select.classificationsOf(s.state, s.ids.u8!)).toEqual([]);
    expect(select.classificationsOf(s.state, s.ids.u11!).length).toBe(1);
  });

  it("73. apply is atomic: every refusal returns no events, leaves the state identical and calls nextId zero times; every success equals replay(prior + new)", () => {
    const s = scenario();
    for (const step of s.steps) {
      const prior = s.eventsUpTo(step.label).slice(0, -step.events.length);
      const replayed = replay([...prior, ...step.events], sha256);
      expect(replayed.ok, step.label).toBe(true);
      if (replayed.ok) expect(replayed.state, step.label).toEqual(step.state);
    }
    const { ctx, calls, state, rule } = smallMap();
    const removed = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    const frozen = structuredClone(removed);
    const refusals: Command[] = [
      propose(humanProposal("prop_r1", { kind: "card.update", card_id: rule, patch: { text: "x" } })),
      propose(humanProposal("prop_r2", { kind: "confirm", card_ids: [rule], proposal_ids: [] })),
      { kind: "clarification.answer", clarification_id: "clar_404", answer: { kind: "yes" }, actor: "Sam" },
      { kind: "question.accept", question_id: rule, by: "Sam", reason: "r" },
      { kind: "signoff.record", reviewer: { name: "Sam" }, confirmation_text: "nope", cited_revision_hash: "" },
      { kind: "export.options_set", options: { capability_class: "", kind: "code", size_estimate: "S", facts: [], by: "Sam" } },
      { kind: "utterance.record", utterance: utterance("utt_1", "") },
      propose(aiProposal("prop_r3", { kind: "undo", to_revision_seq: 99 }, { utts: [] })),
      { kind: "bogus" } as never,
    ];
    for (const command of refusals) {
      const before = calls.nextId;
      const result = refused(removed, command, ctx);
      expect(Object.keys(result).sort()).toEqual(result.checks ? ["checks", "detail", "ok", "reason"] : ["detail", "ok", "reason"]);
      expect(calls.nextId).toBe(before);
      expect(removed).toEqual(frozen);
    }
    // createEngine binds the dependencies to the same functions
    const { ctx: c2 } = testCtx();
    const engine = createEngine({ sha256, now: c2.now, nextId: c2.nextId });
    const command = propose(humanProposal("prop_e", { kind: "card.create", card: { kind: "story", text: "S" } }));
    const viaEngine = engine.apply(state, command);
    const { ctx: c3 } = testCtx();
    const direct = apply(state, command, c3);
    expect(viaEngine).toEqual(direct);
    if (viaEngine.ok) {
      expect(engine.revisionOf(viaEngine.state)).toBe(viaEngine.state.revisions[viaEngine.state.revisions.length - 1]!.hash);
      expect(engine.verifyChain(viaEngine.events).ok).toBe(true);
    }
  });
});
