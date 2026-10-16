// TEST-PLAN §1 cases 21–30: every card operation, its effects and its refusals.
import { describe, expect, it } from "vitest";
import type { Card, ExampleCard, ExmapEvent, QuestionCard } from "../../../src/core/types.js";
import { createdCardId, humanProposal, propose, refused, run, RULE_TEXT, scenario, smallMap, STORY_TEXT } from "./fixtures.js";

const example = (c: Card | undefined): ExampleCard => {
  if (!c || c.kind !== "example") throw new Error("not an example");
  return c;
};
const question = (c: Card | undefined): QuestionCard => {
  if (!c || c.kind !== "question") throw new Error("not a question");
  return c;
};

describe("card operations", () => {
  it("21. card.create story -> proposed in proposal.made, applied in proposal.applied; version 1; created === changed; restored_by null", () => {
    const { ctx, state } = smallMap();
    const fresh = run({ ...state, cards: {}, card_order: [] }, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "story", text: "  A story\r\n" } })), ctx);
    const [made, applied] = fresh.events as [Extract<ExmapEvent, { type: "proposal.made" }>, Extract<ExmapEvent, { type: "proposal.applied" }>];
    expect(made.type).toBe("proposal.made");
    expect(made.effects[0]!.after.status).toBe("proposed");
    expect(applied.type).toBe("proposal.applied");
    expect(applied.effects[0]!.after.status).toBe("applied");
    expect(applied.revision.seq).toBe(fresh.state.revisions.length - 1);
    const card = fresh.state.cards[createdCardId(fresh.events)]!;
    expect(card.kind).toBe("story");
    expect(card.text).toBe("A story"); // trimmed, CRLF -> LF
    expect(card.version).toBe(1);
    expect(card.created).toEqual(card.changed);
    expect(card.created.event_id).toBe(made.id);
    expect(card.restored_by).toBeNull();
    expect(card.history).toEqual([]);
    expect(card.status).toBe("applied");
    expect(fresh.state.proposals[made.proposal.id]!.affected_card_ids).toEqual([card.id]);
  });

  it("22. a second live story is refused STORY_ALREADY_EXISTS; no events; nextId not called", () => {
    const { ctx, calls, state, story } = smallMap();
    const command = propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "story", text: "Another story" } }));
    const before = calls.nextId;
    const result = refused(state, command, ctx);
    expect(result.reason).toBe("STORY_ALREADY_EXISTS");
    expect(result.detail).toContain(story);
    expect(calls.nextId).toBe(before);
    expect("events" in result).toBe(false);
    // after the story is removed a new one is allowed
    const removed = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: story })), ctx).state;
    expect(run(removed, command, ctx).events.length).toBe(2);
  });

  it("23. an example with a non-live or non-rule link is refused: CARD_NOT_LIVE for a removed rule, LINK_KIND_MISMATCH for a question id", () => {
    const { ctx, state, rule } = smallMap();
    const q = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q?", about_card_id: null } })), ctx);
    const questionId = createdCardId(q.events);
    const removed = run(q.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    expect(refused(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E", rule_id: rule } })), ctx).reason).toBe("CARD_NOT_LIVE");
    expect(refused(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E", rule_id: questionId } })), ctx).reason).toBe("LINK_KIND_MISMATCH");
    expect(refused(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E", rule_id: "card_nope" } })), ctx).reason).toBe("CARD_NOT_FOUND");
    expect(refused(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q2", about_card_id: rule } })), ctx).reason).toBe("CARD_NOT_LIVE");
    // an unattached example is allowed
    expect(run(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E", rule_id: null } })), ctx).events.length).toBe(2);
  });

  it("24. card.update bumps version, resets confirmed -> applied, clears confirmation, keeps history, sets restored_by null", () => {
    const { ctx, state, rule } = smallMap();
    const confirmed = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule], proposal_ids: [] })), ctx).state;
    expect(confirmed.cards[rule]!.status).toBe("confirmed");
    const pid = ctx.nextId("prop");
    const updated = run(confirmed, propose(humanProposal(pid, { kind: "card.update", card_id: rule, patch: { text: "New text." } }, "Ana")), ctx);
    const card = updated.state.cards[rule]!;
    expect(card.version).toBe(2);
    expect(card.status).toBe("applied");
    expect(card.confirmation).toBeNull();
    expect(card.text).toBe("New text.");
    expect(card.history.length).toBe(1);
    expect(card.history[0]!.record.text).toBe(RULE_TEXT);
    expect(card.history[0]!.record.status).toBe("confirmed");
    expect(card.changed.proposal_id).toBe(pid);
    expect(card.changed.event_id).toBe(updated.events[1]!.id);
    expect(card.created.proposal_id).not.toBe(pid);
    expect(card.restored_by).toBeNull();
    expect(updated.state.proposals[pid]!.affected_card_ids).toEqual([rule]);
    // a question's answer and acceptance: answer is content; a content change clears accepted_outstanding
    const q = run(updated.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q?", about_card_id: rule } })), ctx);
    const questionId = createdCardId(q.events);
    const accepted = run(q.state, { kind: "question.accept", question_id: questionId, by: "Sam", reason: "later" }, ctx).state;
    expect(question(accepted.cards[questionId]).accepted_outstanding?.by).toBe("Sam");
    const answered = run(accepted, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: questionId, patch: { answer: "Yes." } })), ctx).state;
    expect(question(answered.cards[questionId]).answer).toBe("Yes.");
    expect(question(answered.cards[questionId]).accepted_outstanding).toBeNull();
    expect(question(answered.cards[questionId]).version).toBe(2);
  });

  it("25. card.update with identical content -> NO_CHANGE; a disallowed patch key -> PATCH_FIELD_NOT_ALLOWED; an empty patch -> PATCH_EMPTY", () => {
    const { ctx, state, rule } = smallMap();
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: RULE_TEXT } })), ctx).reason).toBe("NO_CHANGE");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: `  ${RULE_TEXT}  ` } })), ctx).reason).toBe("NO_CHANGE");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { rule_id: null } })), ctx).reason).toBe("PATCH_FIELD_NOT_ALLOWED");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { answer: "x" } })), ctx).reason).toBe("PATCH_FIELD_NOT_ALLOWED");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: {} })), ctx).reason).toBe("PATCH_EMPTY");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "  " } })), ctx).reason).toBe("EMPTY_TEXT");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: "card_404", patch: { text: "x" } })), ctx).reason).toBe("CARD_NOT_FOUND");
  });

  it("26. a rule update flags linked live examples needs_review and leaves unlinked ones alone; confirming the rule does not clear them; confirming the example does", () => {
    const { ctx, state, rule } = smallMap();
    const r2 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Second rule." } })), ctx);
    const rule2 = createdCardId(r2.events);
    const e1 = run(r2.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const e2 = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E2", rule_id: rule2 } })), ctx);
    const e3 = run(e2.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E3", rule_id: null } })), ctx);
    const [ex1, ex2, ex3] = [createdCardId(e1.events), createdCardId(e2.events), createdCardId(e3.events)];
    const updated = run(e3.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "Rule changed." } })), ctx);
    const flag = example(updated.state.cards[ex1]).needs_review;
    expect(flag).toEqual({ reason: "rule_changed", rule_id: rule, event_id: updated.events[1]!.id });
    expect(example(updated.state.cards[ex1]).version).toBe(1); // review state only
    expect(example(updated.state.cards[ex2]).needs_review).toBeNull();
    expect(example(updated.state.cards[ex3]).needs_review).toBeNull();
    const applied = updated.events[1] as Extract<ExmapEvent, { type: "proposal.applied" }>;
    expect(applied.effects.map((e) => e.card_id)).toEqual([rule, ex1]);
    const ruleConfirmed = run(updated.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule], proposal_ids: [] })), ctx).state;
    expect(example(ruleConfirmed.cards[ex1]).needs_review).toEqual(flag);
    const exampleConfirmed = run(ruleConfirmed, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [ex1], proposal_ids: [] })), ctx).state;
    expect(example(exampleConfirmed.cards[ex1]).needs_review).toBeNull();
    expect(exampleConfirmed.cards[ex1]!.status).toBe("confirmed");
    // a definitions-only change flags too; a link-only change on an example does not touch the rule's other examples
    const defs = run(exampleConfirmed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { definitions: [{ term: "GP", definition: "general practitioner" }] } })), ctx).state;
    expect(example(defs.cards[ex1]).needs_review?.reason).toBe("rule_changed");
    expect(defs.cards[ex1]!.status).toBe("confirmed"); // the flag does not change the example's status
  });

  it("27. card.remove -> rejected/removed, keeps history and provenance; removing a rule flags its examples rule_removed and leaves the dangling rule_id", () => {
    const { ctx, state, rule } = smallMap();
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const updated = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: rule, patch: { text: "v2" } })), ctx).state;
    const pid = ctx.nextId("prop");
    const removed = run(updated, propose(humanProposal(pid, { kind: "card.remove", card_id: rule }, "Ana")), ctx);
    const card = removed.state.cards[rule]!;
    expect(card.status).toBe("rejected");
    expect(card.rejection).toEqual({ kind: "removed", proposal_id: pid, event_id: removed.events[1]!.id });
    expect(card.confirmation).toBeNull();
    expect(card.version).toBe(2);
    expect(card.history.length).toBe(1);
    expect(card.changed.proposal_id).not.toBe(pid); // provenance of the content is untouched
    expect(card.created.proposal_id).toBe(updated.cards[rule]!.created.proposal_id);
    const ex = example(removed.state.cards[ex1]);
    expect(ex.rule_id).toBe(rule);
    expect(ex.needs_review).toEqual({ reason: "rule_removed", rule_id: rule, event_id: removed.events[1]!.id });
    expect(removed.state.proposals[pid]!.affected_card_ids).toEqual([rule]);
    expect(refused(removed.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).reason).toBe("CARD_NOT_LIVE");
    // the removed card's own needs_review (an example) is cleared when it leaves the live set
    const removedExample = run(removed.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: ex1 })), ctx).state;
    expect(example(removedExample.cards[ex1]).needs_review).toBeNull();
  });

  it("28. card.replace by text supersedes the old card, links supersedes/superseded_by, re-links examples (rule_replaced) and questions", () => {
    const { ctx, state, rule } = smallMap();
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const q1 = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "question", text: "Q?", about_card_id: rule } })), ctx);
    const qid = createdCardId(q1.events);
    const confirmedAll = run(q1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule, ex1, qid], proposal_ids: [] })), ctx).state;
    const pid = ctx.nextId("prop");
    const replaced = run(confirmedAll, propose(humanProposal(pid, { kind: "card.replace", card_id: rule, replacement: { text: "The new rule.", definitions: [{ term: "slot", definition: "a booking" }] } })), ctx);
    const newId = createdCardId(replaced.events);
    const fresh = replaced.state.cards[newId]!;
    const old = replaced.state.cards[rule]!;
    expect(fresh.kind).toBe("rule");
    expect(fresh.status).toBe("applied");
    expect(fresh.version).toBe(1);
    expect(fresh.supersedes).toBe(rule);
    expect(fresh.created).toEqual(fresh.changed);
    expect(fresh.created.proposal_id).toBe(pid);
    expect(fresh.definitions).toEqual([{ term: "slot", definition: "a booking" }]);
    expect(old.status).toBe("superseded");
    expect(old.superseded_by).toBe(newId);
    expect(old.confirmation).toBeNull();
    expect(old.version).toBe(1);
    const ex = example(replaced.state.cards[ex1]);
    expect(ex.rule_id).toBe(newId);
    expect(ex.version).toBe(2);
    expect(ex.status).toBe("applied");
    expect(ex.needs_review).toEqual({ reason: "rule_replaced", rule_id: newId, event_id: replaced.events[1]!.id });
    expect(ex.changed.proposal_id).toBe(pid);
    const q = question(replaced.state.cards[qid]);
    expect(q.about_card_id).toBe(newId);
    expect(q.version).toBe(2);
    expect(replaced.state.proposals[pid]!.affected_card_ids).toEqual([rule, newId]);
    expect(replaced.state.revisions.length).toBe(confirmedAll.revisions.length + 1);
    expect(refused(confirmedAll, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule, replacement: { text: RULE_TEXT } })), ctx).reason).toBe("NO_CHANGE");
    // a replaced question keeps its link and drops its answer
    const answered = run(replaced.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.update", card_id: qid, patch: { answer: "Because." } })), ctx).state;
    const qReplaced = run(answered, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: qid, replacement: { text: "Q, reworded?" } })), ctx);
    const q2 = question(qReplaced.state.cards[createdCardId(qReplaced.events)]);
    expect(q2.about_card_id).toBe(newId);
    expect(q2.answer).toBeNull();
  });

  it("29. card.replace by replacement_card_id keeps the replacement's id, provenance, confirmation and version; refusals KIND_MISMATCH / REPLACEMENT_INVALID / CARD_NOT_LIVE", () => {
    const { ctx, state, rule, story } = smallMap();
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const r2 = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Rule two." } })), ctx);
    const rule2 = createdCardId(r2.events);
    const confirmed = run(r2.state, propose(humanProposal(ctx.nextId("prop"), { kind: "confirm", card_ids: [rule2], proposal_ids: [] })), ctx).state;
    const pid = ctx.nextId("prop");
    const replaced = run(confirmed, propose(humanProposal(pid, { kind: "card.replace", card_id: rule, replacement_card_id: rule2 })), ctx);
    const rep = replaced.state.cards[rule2]!;
    expect(rep.supersedes).toBe(rule);
    expect(rep.status).toBe("confirmed");
    expect(rep.confirmation).toEqual(confirmed.cards[rule2]!.confirmation);
    expect(rep.version).toBe(1);
    expect(rep.changed).toEqual(confirmed.cards[rule2]!.changed);
    expect(replaced.state.cards[rule]!.superseded_by).toBe(rule2);
    expect(replaced.state.cards[rule]!.status).toBe("superseded");
    expect(example(replaced.state.cards[ex1]).rule_id).toBe(rule2);
    expect(example(replaced.state.cards[ex1]).needs_review?.reason).toBe("rule_replaced");
    expect(replaced.state.proposals[pid]!.affected_card_ids).toEqual([rule, rule2]);
    expect(replaced.state.revisions.length).toBe(confirmed.revisions.length + 1);
    // refusals
    expect(refused(confirmed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule, replacement_card_id: story })), ctx).reason).toBe("KIND_MISMATCH");
    expect(refused(confirmed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule, replacement_card_id: rule })), ctx).reason).toBe("REPLACEMENT_INVALID");
    const r3 = run(replaced.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Rule three." } })), ctx);
    const rule3 = createdCardId(r3.events);
    expect(refused(r3.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule3, replacement_card_id: rule2 })), ctx).reason).toBe("REPLACEMENT_INVALID");
    const removed = run(r3.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule3 })), ctx).state;
    expect(refused(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule2, replacement_card_id: rule3 })), ctx).reason).toBe("CARD_NOT_LIVE");
    expect(refused(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.replace", card_id: rule2, replacement_card_id: "card_404" })), ctx).reason).toBe("CARD_NOT_FOUND");
  });

  it("30. definition.refine upserts by term and is a content change (flags examples of a rule); identical refine -> NO_CHANGE; empty term -> INVALID_DEFINITION", () => {
    const { ctx, state, rule, story } = smallMap();
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const refined = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: " appointment ", definition: "a booked slot" })), ctx);
    expect(refined.state.cards[rule]!.definitions).toEqual([{ term: "appointment", definition: "a booked slot" }]);
    expect(refined.state.cards[rule]!.version).toBe(2);
    expect(example(refined.state.cards[ex1]).needs_review?.reason).toBe("rule_changed");
    const again = run(refined.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: "appointment", definition: "a booked slot, not a walk-in" })), ctx);
    expect(again.state.cards[rule]!.definitions).toEqual([{ term: "appointment", definition: "a booked slot, not a walk-in" }]);
    const second = run(again.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: "GP", definition: "general practitioner" })), ctx);
    expect(second.state.cards[rule]!.definitions.map((d) => d.term)).toEqual(["GP", "appointment"]); // sorted by term (code-unit order)
    expect(refused(second.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: "GP", definition: "general practitioner" })), ctx).reason).toBe("NO_CHANGE");
    expect(refused(second.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: "  ", definition: "x" })), ctx).reason).toBe("INVALID_DEFINITION");
    expect(refused(second.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: rule, term: "x", definition: "" })), ctx).reason).toBe("INVALID_DEFINITION");
    // any kind: the story
    expect(run(second.state, propose(humanProposal(ctx.nextId("prop"), { kind: "definition.refine", card_id: story, term: "online", definition: "via the website or app" })), ctx).state.cards[story]!.definitions.length).toBe(1);
    // create with a duplicate term is refused
    expect(refused(second.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "R", definitions: [{ term: "a", definition: "1" }, { term: "a", definition: "2" }] } })), ctx).reason).toBe("INVALID_DEFINITION");
    expect(STORY_TEXT).toBe(second.state.cards[story]!.text);
  });

  it("scenario: the story and the rule carry the brief's texts after every amendment", () => {
    const s = scenario();
    expect(s.state.cards[s.ids.story!]!.definitions).toEqual([{ term: "appointment", definition: "a booked slot, not a walk-in" }]);
    expect(s.state.cards[s.ids.rule!]!.history.map((h) => h.version)).toEqual([1, 2]);
  });
});
