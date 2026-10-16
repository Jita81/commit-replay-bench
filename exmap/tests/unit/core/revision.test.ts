// TEST-PLAN §1 cases 11–15: what the requirement revision does and does not depend on.
import { describe, expect, it } from "vitest";
import { initialState } from "../../../src/core/reduce.js";
import { canonicalState, computeRevision, GENESIS_REVISION_HASH } from "../../../src/core/revision.js";
import { sha256 } from "../../../src/server/hash.js";
import type { ApplyContext, Command, MapState } from "../../../src/core/types.js";
import {
  classify, createdCardId, humanProposal, propose, revisionHash, run, RULE_TEXT, scenario, smallMap, STORY_TEXT, testCtx, utterance,
} from "./fixtures.js";

function runAll(state: MapState, ctx: ApplyContext, commands: Command[]): MapState {
  for (const c of commands) state = run(state, c, ctx).state;
  return state;
}

describe("revision", () => {
  it("11. the revision is GENESIS_REVISION_HASH for an empty map", () => {
    const state = initialState("sess_empty");
    expect(revisionHash(state)).toBe(GENESIS_REVISION_HASH);
    expect(GENESIS_REVISION_HASH).toMatch(/^8e97e07b.*9f675$/);
    expect(computeRevision(state.cards, sha256)).toBe(GENESIS_REVISION_HASH);
    expect(computeRevision([], sha256)).toBe(GENESIS_REVISION_HASH);
    expect(canonicalState({})).toEqual({ schema: "exmap.revision.v1", cards: [] });
  });

  it("12. the revision ignores timestamps, utterances, classifications and export options", () => {
    const build = (start: string, extras: boolean): MapState => {
      const { ctx } = testCtx(start);
      let state = initialState("sess_a");
      const commands: Command[] = [];
      if (extras) commands.push({ kind: "utterance.record", utterance: utterance("utt_x", "Some chatter", { t_start_ms: 100 }) });
      commands.push(propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "story", text: STORY_TEXT } })));
      if (extras) commands.push(classify("utt_x", "none"));
      commands.push(propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: RULE_TEXT } })));
      if (extras) {
        commands.push({ kind: "export.options_set", options: { capability_class: "bug.fix", kind: "code", size_estimate: "S", facts: [], by: "Sam" } });
      }
      state = runAll(state, ctx, commands);
      return state;
    };
    const a = build("2026-10-16T12:00:00.000Z", false);
    const b = build("2030-01-01T00:00:00.000Z", true);
    expect(revisionHash(a)).toBe(revisionHash(b));
    expect(a.head.hash).not.toBe(b.head.hash); // the chain differs; the meaning does not
  });

  it("13. the revision changes when a rule's text changes and reverts to the earlier hash after undo", () => {
    const { ctx, state, rule } = smallMap();
    const before = revisionHash(state);
    const updated = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: RULE_TEXT + " Amended." } })), ctx).state;
    expect(revisionHash(updated)).not.toBe(before);
    const undone = run(updated, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: null })), ctx).state;
    expect(revisionHash(undone)).toBe(before);
    expect(undone.revisions.length).toBe(updated.revisions.length + 1);
  });

  it("14. the revision ignores confirmation, needs_review, acceptance and supersedes links", () => {
    const { ctx, state, rule } = smallMap();
    const withExample = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "Ex one", rule_id: rule } })), ctx);
    const example = createdCardId(withExample.events);
    const withQuestion = run(withExample.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Why?", about_card_id: rule } })), ctx);
    const question = createdCardId(withQuestion.events);
    const base = revisionHash(withQuestion.state);
    // confirm (confirmation) and accept (acceptance): no revision at all
    const confirmed = run(withQuestion.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [example, rule], proposal_ids: [] })), ctx).state;
    const accepted = run(confirmed, { kind: "question.accept", question_id: question, by: "Sam", reason: "later" }, ctx).state;
    expect(revisionHash(accepted)).toBe(base);
    expect(accepted.revisions.length).toBe(withQuestion.state.revisions.length);
    // a supersedes link alone (replace by an existing card) changes the live set, so compare against the same live set
    // built directly: the hash of live cards' content is independent of the link fields
    const liveA = canonicalState(accepted.cards);
    const liveB = canonicalState(Object.values(accepted.cards).map((c) => ({ ...c, supersedes: "card_x", confirmation: null, status: "applied" as const })));
    expect(liveB).toEqual(liveA);
    // needs_review is review state: flag the example by updating the rule, then compare with a map that reached the same content differently
    const flagged = run(accepted, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: RULE_TEXT + " v2" } })), ctx).state;
    expect(flagged.cards[example]!.kind === "example" && (flagged.cards[example] as { needs_review: unknown }).needs_review).not.toBeNull();
    const cleared = run(flagged, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [example], proposal_ids: [] })), ctx).state;
    expect(revisionHash(cleared)).toBe(revisionHash(flagged));
  });

  it("15. the revision excludes rejected, superseded and proposed cards", () => {
    const s = scenario();
    // after the GP example was removed (answer_candidate), the hash equals a map that never had it
    const afterRemove = s.stateAfter("answer_candidate");
    const liveOnly = Object.values(afterRemove.cards).filter((c) => c.status === "applied" || c.status === "confirmed");
    expect(computeRevision(liveOnly, sha256)).toBe(revisionHash(afterRemove));
    expect(canonicalState(afterRemove.cards).cards.map((c) => c.id)).not.toContain(s.ids.ex_gp);
    // a superseded card is excluded too
    const afterReplace = s.stateAfter("replace_id");
    expect(afterReplace.cards[s.ids.ex_nurse!]!.status).toBe("superseded");
    expect(canonicalState(afterReplace.cards).cards.map((c) => c.id)).not.toContain(s.ids.ex_nurse);
    // the proposed record inside proposal.made is not live
    expect(canonicalState([{ ...afterReplace.cards[s.ids.rule!]!, status: "proposed" }]).cards).toEqual([]);
    // live cards are sorted by id in the canonical state
    const ids = canonicalState(s.state.cards).cards.map((c) => c.id);
    expect(ids).toEqual([...ids].sort());
  });
});
