// TEST-PLAN §1 cases 43–50: clarification requests and every way of answering them.
import { describe, expect, it } from "vitest";
import { dodReport } from "../../../src/core/dod.js";
import * as select from "../../../src/core/select.js";
import type { ExmapEvent, OperationTemplate } from "../../../src/core/types.js";
import { aiProposal, clarifying, createdCardId, humanProposal, propose, refused, run, scenario, smallMap, stamps, utterance } from "./fixtures.js";

type Answered = Extract<ExmapEvent, { type: "clarification.answered" }>;
type Asked = Extract<ExmapEvent, { type: "clarification.asked" }>;

/** A small map with a rule, two examples and the utterance the clarifications cite. */
function withExamples() {
  const base = smallMap();
  const { ctx } = base;
  const e1 = run(base.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "If a GP appointment is at 10am and the patient cancels at 9am, then it is refused.", rule_id: base.rule } })), ctx);
  const e2 = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "A nurse appointment at 10am cancelled at 8am is allowed.", rule_id: base.rule } })), ctx);
  const state = run(e2.state, { kind: "utterance.record", utterance: utterance("utt_c", "Delete that example.", { speaker: "Sam", lane: "me" }) }, ctx).state;
  return { ...base, state, ex1: createdCardId(e1.events), ex2: createdCardId(e2.events) };
}

function askRemove(m: ReturnType<typeof withExamples>, stamp = stamps.rules()) {
  const pid = m.ctx.nextId("prop");
  const asked = run(m.state, propose(clarifying(pid, "remove", {
    question: "Which example do you mean?", template: { kind: "card.remove" },
    candidates: [{ card_id: m.ex2, label: "nurse" }, { card_id: m.ex1, label: "GP" }], utts: ["utt_c"], stamp,
  })), m.ctx);
  const clarId = (asked.events[1] as Asked).clarification_id;
  return { pid, asked, clarId };
}

describe("clarification", () => {
  it("43. needs_clarification yields proposal.made + clarification.asked, no card, no revision; shape refusals", () => {
    const m = withExamples();
    const { pid, asked, clarId } = askRemove(m);
    expect(asked.events.map((e) => e.type)).toEqual(["proposal.made", "clarification.asked"]);
    expect(asked.state.revisions.length).toBe(m.state.revisions.length);
    expect(Object.keys(asked.state.cards).length).toBe(Object.keys(m.state.cards).length);
    expect(asked.state.proposals[pid]!.status).toBe("clarifying");
    expect(asked.state.proposals[pid]!.outcome_event_id).toBe(asked.events[1]!.id);
    const clarification = asked.state.clarifications[clarId]!;
    expect(clarification.status).toBe("open");
    expect(clarification.candidates.map((c) => c.card_id)).toEqual([m.ex2, m.ex1]);
    expect(clarification.template).toEqual({ kind: "card.remove" });
    expect(clarification.pending_operation).toBeNull();
    expect(select.openClarifications(asked.state).map((c) => c.id)).toEqual([clarId]);
    expect(dodReport(asked.state).checks[2]!.details).toContain(`clarification ${clarId} is open: "Which example do you mean?"`);
    const { ctx, rule } = m;
    const both = clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, pending: { kind: "card.remove", card_id: m.ex1 }, utts: ["utt_c"] });
    expect(refused(m.state, propose(both), ctx).reason).toBe("CLARIFICATION_SHAPE");
    const candidatesWithPending = clarifying(ctx.nextId("prop"), "remove", { pending: { kind: "card.remove", card_id: m.ex1 }, candidates: [{ card_id: m.ex2, label: "n" }], utts: ["utt_c"] });
    expect(refused(m.state, propose(candidatesWithPending), ctx).reason).toBe("CLARIFICATION_SHAPE");
    const ruleTemplate = { kind: "card.create", card: { kind: "rule", text: "R" } } as unknown as OperationTemplate;
    expect(refused(m.state, propose(clarifying(ctx.nextId("prop"), "add", { template: ruleTemplate, utts: ["utt_c"] })), ctx).reason).toBe("CLARIFICATION_SHAPE");
    const removed = run(m.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: m.ex1 })), ctx).state;
    expect(refused(removed, propose(clarifying(ctx.nextId("prop"), "remove", { pending: { kind: "card.remove", card_id: m.ex1 }, utts: ["utt_c"] })), ctx).reason).toBe("CARD_NOT_LIVE");
    expect(refused(m.state, propose(clarifying(ctx.nextId("prop"), "remove", { question: "  ", template: { kind: "card.remove" }, utts: ["utt_c"] })), ctx).reason).toBe("CLARIFICATION_QUESTION_REQUIRED");
    expect(refused(m.state, propose(clarifying(ctx.nextId("prop"), "add", { template: { kind: "card.remove" }, utts: ["utt_c"] })), ctx).reason).toBe("INTENT_OPERATION_MISMATCH");
    expect(refused(m.state, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, candidates: [{ card_id: "card_404", label: "x" }], utts: ["utt_c"] })), ctx).reason).toBe("CARD_NOT_FOUND");
    expect(refused(m.state, propose({ ...clarifying(ctx.nextId("prop"), "remove", { utts: ["utt_c"] }), needs_clarification: false }), ctx).reason).toBe("CLARIFICATION_SHAPE");
    expect(refused(m.state, propose({ ...aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule }, { utts: ["utt_c"] }), question: "?" }), ctx).reason).toBe("CLARIFICATION_SHAPE");
    // a pure question (no template, no pending operation) is allowed
    expect(run(m.state, propose(clarifying(ctx.nextId("prop"), "remove", { question: "What do you mean?", utts: ["utt_c"] })), ctx).events.length).toBe(2);
  });

  it("44. answering with a candidate applies the resolved operation in the same batch; the asking stamp is kept with the answerer as actor; nextId('prop') once, after validation", () => {
    const m = withExamples();
    const { pid, asked, clarId } = askRemove(m, stamps.fallback("CLASSIFIER_TIMEOUT"));
    const before = m.calls.byPrefix.prop;
    const answered = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Ana" }, m.ctx);
    expect(answered.events.map((e) => e.type)).toEqual(["clarification.answered", "proposal.made", "proposal.applied"]);
    expect(m.calls.byPrefix.prop - before).toBe(1);
    const resolvedId = (answered.events[0] as Answered).resolved_by_proposal_id!;
    const resolved = answered.state.proposals[resolvedId]!;
    expect(resolved.proposal.classifier).toEqual({ ...stamps.fallback("CLASSIFIER_TIMEOUT"), actor: "Ana" });
    expect(resolved.proposal.confidence).toBe(1);
    expect(resolved.proposal.intent).toBe("remove");
    expect(resolved.proposal.operation).toEqual({ kind: "card.remove", card_id: m.ex1 });
    expect(resolved.proposal.resolves_clarification_id).toBe(clarId);
    expect(resolved.proposal.source_utterance_ids).toEqual(["utt_c"]);
    expect(resolved.proposal.rationale).toBe("clarification answered by Ana");
    expect(resolved.status).toBe("applied");
    const clarification = answered.state.clarifications[clarId]!;
    expect(clarification.status).toBe("answered");
    expect(clarification.resolved_by_proposal_id).toBe(resolvedId);
    expect(clarification.answer).toEqual({ kind: "candidate", card_id: m.ex1 });
    expect(clarification.answered_event_id).toBe(answered.events[0]!.id);
    expect(answered.state.proposals[pid]!.status).toBe("answered");
    expect(answered.state.cards[m.ex1]!.status).toBe("rejected");
    expect(answered.state.cards[m.ex1]!.rejection?.proposal_id).toBe(resolvedId);
    expect(select.unreviewedActs(answered.state)).toEqual([]); // the answerer is the actor
    expect(answered.events.every((e) => e.batch_id === answered.events[0]!.id)).toBe(true);
    // a refused candidate calls nextId zero times and appends nothing
    const { clarId: clar2 } = askRemove(m);
    const removed = run(asked.state, propose(humanProposal(m.ctx.nextId("prop"), { kind: "card.remove", card_id: m.ex2 })), m.ctx).state;
    const calls = m.calls.nextId;
    expect(refused(removed, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.ex2 }, actor: "Ana" }, m.ctx).reason).toBe("CARD_NOT_LIVE");
    expect(m.calls.nextId).toBe(calls);
    expect(clar2).not.toBe(clarId);
    // the person is in control: a live card outside the candidate list is accepted
    expect(run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.rule }, actor: "Ana" }, m.ctx).state.cards[m.rule]!.status).toBe("rejected");
  });

  it("45. answering yes applies the pending operation; yes without pending_operation -> CLARIFICATION_NO_OPERATION; yes after the target was removed -> CARD_NOT_LIVE", () => {
    const m = withExamples();
    const { ctx } = m;
    const pid = ctx.nextId("prop");
    const asked = run(m.state, propose(clarifying(pid, "remove", { question: "Remove the nurse example?", pending: { kind: "card.remove", card_id: m.ex2 }, utts: ["utt_c"] })), ctx);
    const clarId = (asked.events[1] as Asked).clarification_id;
    const yes = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "yes" }, actor: "Sam" }, ctx);
    expect(yes.events.map((e) => e.type)).toEqual(["clarification.answered", "proposal.made", "proposal.applied"]);
    expect(yes.state.cards[m.ex2]!.status).toBe("rejected");
    expect(yes.state.cards[m.ex2]!.rejection?.kind).toBe("removed");
    const resolved = yes.state.proposals[(yes.events[0] as Answered).resolved_by_proposal_id!]!;
    expect(resolved.proposal.classifier.actor).toBe("Sam");
    expect(resolved.proposal.classifier.provider).toBe("rules.v1");
    expect(select.unreviewedActs(yes.state)).toEqual([]);
    expect(yes.state.clarifications[clarId]!.answer).toEqual({ kind: "yes" });
    const { clarId: templateClar } = askRemove(m);
    const templateState = run(m.state, propose(clarifying(ctx.nextId("prop"), "remove", { template: { kind: "card.remove" }, utts: ["utt_c"] })), ctx);
    const tId = (templateState.events[1] as Asked).clarification_id;
    expect(refused(templateState.state, { kind: "clarification.answer", clarification_id: tId, answer: { kind: "yes" }, actor: "Sam" }, ctx).reason).toBe("CLARIFICATION_NO_OPERATION");
    expect(templateClar).not.toBe(tId);
    const removed = run(asked.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: m.ex2 })), ctx).state;
    const calls = m.calls.nextId;
    const stale = refused(removed, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "yes" }, actor: "Sam" }, ctx);
    expect(stale.reason).toBe("CARD_NOT_LIVE");
    expect(m.calls.nextId).toBe(calls);
    expect(removed.clarifications[clarId]!.status).toBe("open"); // nothing appended; Dismiss remains available
  });

  it("46. an amendment template resolves per card: substitution when the card contains `from`, otherwise the append path; from null -> append", () => {
    const m = withExamples();
    const { ctx, rule } = m;
    const ask = (amendment: { from: string | null; to: string; scope: string | null; append: string }) => {
      const asked = run(m.state, propose(clarifying(ctx.nextId("prop"), "amend", {
        question: "Which card?", template: { kind: "card.update", patch: { text: "" }, amendment }, candidates: [{ card_id: rule, label: "rule" }, { card_id: m.ex1, label: "GP" }], utts: ["utt_c"],
      })), ctx);
      return { state: asked.state, clarId: (asked.events[1] as Asked).clarification_id };
    };
    const a = ask({ from: "two hours", to: "24 hours", scope: null, append: "Make that 24 hours." });
    const substituted = run(a.state, { kind: "clarification.answer", clarification_id: a.clarId, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx).state;
    expect(substituted.cards[rule]!.text).toBe("A patient should be able to cancel online, but not within 24 hours of their appointment.");
    const appended = run(a.state, { kind: "clarification.answer", clarification_id: a.clarId, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Sam" }, ctx).state;
    expect(appended.cards[m.ex1]!.text).toBe(`${m.state.cards[m.ex1]!.text} Amendment: Make that 24 hours.`);
    const b = ask({ from: null, to: "", scope: null, append: "Make that 24 hours." });
    const fromNull = run(b.state, { kind: "clarification.answer", clarification_id: b.clarId, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx).state;
    expect(fromNull.cards[rule]!.text).toBe(`${m.state.cards[rule]!.text} Amendment: Make that 24 hours.`);
    // a scope forces the append path; the match is case-insensitive, first occurrence
    const c = ask({ from: "TWO HOURS", to: "three hours", scope: "nurses only", append: "Make that three hours for nurses only." });
    const scoped = run(c.state, { kind: "clarification.answer", clarification_id: c.clarId, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx).state;
    expect(scoped.cards[rule]!.text).toBe(`${m.state.cards[rule]!.text} Amendment: Make that three hours for nurses only.`);
    const d = ask({ from: "TWO HOURS", to: "three hours", scope: null, append: "x" });
    expect(run(d.state, { kind: "clarification.answer", clarification_id: d.clarId, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx).state.cards[rule]!.text).toContain("within three hours");
    // a substitution that changes nothing is NO_CHANGE and refuses the whole answer
    const e = ask({ from: "two hours", to: "two hours", scope: null, append: "" });
    expect(refused(e.state, { kind: "clarification.answer", clarification_id: e.clarId, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx).reason).toBe("NO_CHANGE");
  });

  it("47. answering with text keeps the clarification open; a later proposal citing it resolves it; a second citing proposal -> CLARIFICATION_NOT_AWAITING_PROPOSAL", () => {
    const m = withExamples();
    const { ctx } = m;
    const { asked, clarId, pid } = askRemove(m);
    const withUtt = run(asked.state, { kind: "utterance.record", utterance: utterance("utt_t", "The GP one.", { speaker: "Sam", lane: "me" }) }, ctx).state;
    const text = run(withUtt, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "text", text: "The GP one.", utterance_id: "utt_t" }, actor: "Sam" }, ctx);
    expect(text.events.map((e) => e.type)).toEqual(["clarification.answered"]);
    expect((text.events[0] as Answered).resolved_by_proposal_id).toBeNull();
    const open = text.state.clarifications[clarId]!;
    expect(open.status).toBe("open");
    expect(open.text_answers).toEqual([{ text: "The GP one.", utterance_id: "utt_t", actor: "Sam", event_id: text.events[0]!.id }]);
    expect(text.state.proposals[pid]!.status).toBe("clarifying");
    const resolverId = ctx.nextId("prop");
    const resolved = run(text.state, propose(aiProposal(resolverId, { kind: "card.remove", card_id: m.ex1 }, { utts: ["utt_t", "utt_c"], resolves: clarId })), ctx);
    expect(resolved.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied"]);
    const clarification = resolved.state.clarifications[clarId]!;
    expect(clarification.status).toBe("answered");
    expect(clarification.resolved_by_proposal_id).toBe(resolverId);
    expect(clarification.answered_event_id).toBe(resolved.events[0]!.id);
    expect(clarification.answer).toEqual({ kind: "text", text: "The GP one.", utterance_id: "utt_t" });
    expect(resolved.state.proposals[pid]!.status).toBe("answered");
    const again = refused(resolved.state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: m.ex2 }, { utts: ["utt_t"], resolves: clarId })), ctx);
    expect(again.reason).toBe("CLARIFICATION_NOT_AWAITING_PROPOSAL");
    expect(refused(resolved.state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: m.ex2 }, { utts: ["utt_t"], resolves: "clar_404" })), ctx).reason).toBe("CLARIFICATION_NOT_AWAITING_PROPOSAL");
    expect(refused(text.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "text", text: "x", utterance_id: "utt_404" }, actor: "Sam" }, ctx).reason).toBe("UTTERANCE_UNKNOWN");
    expect(refused(text.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "text", text: "  ", utterance_id: null }, actor: "Sam" }, ctx).reason).toBe("EMPTY_TEXT");
  });

  it("48. a text answer with no resolver can still be answered by candidate, yes or dismiss; two text answers -> text_answers.length === 2, still open; dismiss -> check 3 passes", () => {
    const m = withExamples();
    const { ctx } = m;
    const { asked, clarId } = askRemove(m);
    const one = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "text", text: "Hmm.", utterance_id: null }, actor: "Sam" }, ctx).state;
    const two = run(one, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "text", text: "The nurse one, I think.", utterance_id: null }, actor: "Priya" }, ctx).state;
    expect(two.clarifications[clarId]!.text_answers.length).toBe(2);
    expect(two.clarifications[clarId]!.status).toBe("open");
    expect(dodReport(two).checks[2]!.pass).toBe(false);
    const byCandidate = run(two, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.ex2 }, actor: "Sam" }, ctx).state;
    expect(byCandidate.clarifications[clarId]!.status).toBe("answered");
    expect(byCandidate.cards[m.ex2]!.status).toBe("rejected");
    const dismissed = run(two, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "dismiss", reason: "Nobody could say." }, actor: "Sam" }, ctx).state;
    expect(dismissed.clarifications[clarId]!.status).toBe("dismissed");
    expect(dodReport(dismissed).checks[2]!.pass).toBe(true);
    expect(select.openClarifications(dismissed)).toEqual([]);
    // yes after text, on a confirm_intent clarification
    const pending = run(m.state, propose(clarifying(ctx.nextId("prop"), "remove", { pending: { kind: "card.remove", card_id: m.ex1 }, utts: ["utt_c"] })), ctx);
    const pId = (pending.events[1] as Asked).clarification_id;
    const afterText = run(pending.state, { kind: "clarification.answer", clarification_id: pId, answer: { kind: "text", text: "Yes, that one.", utterance_id: null }, actor: "Sam" }, ctx).state;
    expect(run(afterText, { kind: "clarification.answer", clarification_id: pId, answer: { kind: "yes" }, actor: "Sam" }, ctx).state.cards[m.ex1]!.status).toBe("rejected");
  });

  it("49. dismiss closes it and marks the asking proposal dismissed; answering a dismissed or resolved one -> CLARIFICATION_NOT_ANSWERABLE; CLARIFICATION_NO_TEMPLATE; citing a dismissed one; ACTOR_REQUIRED; REASON_REQUIRED", () => {
    const m = withExamples();
    const { ctx } = m;
    const { asked, clarId, pid } = askRemove(m);
    const dismissed = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "dismiss", reason: "Moved on." }, actor: "Sam" }, ctx);
    expect(dismissed.events.map((e) => e.type)).toEqual(["clarification.answered"]);
    expect(dismissed.state.clarifications[clarId]!.status).toBe("dismissed");
    expect(dismissed.state.clarifications[clarId]!.answer).toEqual({ kind: "dismiss", reason: "Moved on." });
    expect(dismissed.state.proposals[pid]!.status).toBe("dismissed");
    expect(refused(dismissed.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Sam" }, ctx).reason).toBe("CLARIFICATION_NOT_ANSWERABLE");
    const resolved = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Sam" }, ctx).state;
    expect(refused(resolved, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "dismiss", reason: "x" }, actor: "Sam" }, ctx).reason).toBe("CLARIFICATION_NOT_ANSWERABLE");
    const pure = run(m.state, propose(clarifying(ctx.nextId("prop"), "remove", { question: "What?", utts: ["utt_c"] })), ctx);
    const pureId = (pure.events[1] as Asked).clarification_id;
    expect(refused(pure.state, { kind: "clarification.answer", clarification_id: pureId, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Sam" }, ctx).reason).toBe("CLARIFICATION_NO_TEMPLATE");
    expect(refused(dismissed.state, propose(aiProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: m.ex1 }, { utts: ["utt_c"], resolves: clarId })), ctx).reason).toBe("CLARIFICATION_NOT_AWAITING_PROPOSAL");
    expect(refused(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: m.ex1 }, actor: "  " }, ctx).reason).toBe("ACTOR_REQUIRED");
    expect(refused(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "dismiss", reason: " " }, actor: "Sam" }, ctx).reason).toBe("REASON_REQUIRED");
    expect(refused(asked.state, { kind: "clarification.answer", clarification_id: "clar_404", answer: { kind: "yes" }, actor: "Sam" }, ctx).reason).toBe("CLARIFICATION_NOT_FOUND");
  });

  it("50. a reject template resolves to the card's authoring proposal", () => {
    const m = withExamples();
    const { ctx, rule } = m;
    const author = ctx.nextId("prop");
    const updated = run(m.state, propose(aiProposal(author, { kind: "card.update", card_id: rule, patch: { text: "Changed by the AI." } }, { utts: ["utt_c"] })), ctx).state;
    const asked = run(updated, propose(clarifying(ctx.nextId("prop"), "reject", { question: "Which change do you reject?", template: { kind: "interpretation.reject" }, candidates: [{ card_id: rule, label: "the rule" }], utts: ["utt_c"] })), ctx);
    const clarId = (asked.events[1] as Asked).clarification_id;
    const answered = run(asked.state, { kind: "clarification.answer", clarification_id: clarId, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx);
    const resolved = answered.state.proposals[(answered.events[0] as Answered).resolved_by_proposal_id!]!;
    expect(resolved.proposal.operation).toEqual({ kind: "interpretation.reject", proposal_id: author });
    expect(answered.events[2]!.type).toBe("proposal.rejected");
    expect(answered.state.cards[rule]!.text).toBe(m.state.cards[rule]!.text);
    expect(answered.state.proposals[author]!.status).toBe("rejected");
    // the other templates resolve too: create (link filled), confirm (card_ids: [it]), replace by id, refine
    const create = run(m.state, propose(clarifying(ctx.nextId("prop"), "add", { template: { kind: "card.create", card: { kind: "example", text: "New example.", rule_id: null } }, candidates: [{ card_id: rule, label: "r" }], utts: ["utt_c"] })), ctx);
    const created = run(create.state, { kind: "clarification.answer", clarification_id: (create.events[1] as Asked).clarification_id, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx);
    const newId = createdCardId(created.events);
    expect(created.state.cards[newId]!.kind === "example" && (created.state.cards[newId] as { rule_id: string }).rule_id).toBe(rule);
    expect(refused(create.state, { kind: "clarification.answer", clarification_id: (create.events[1] as Asked).clarification_id, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Sam" }, ctx).reason).toBe("LINK_KIND_MISMATCH");
    const confirm = run(m.state, propose(clarifying(ctx.nextId("prop"), "confirm", { template: { kind: "confirm" }, candidates: [{ card_id: rule, label: "r" }], utts: ["utt_c"] })), ctx);
    const confirmed = run(confirm.state, { kind: "clarification.answer", clarification_id: (confirm.events[1] as Asked).clarification_id, answer: { kind: "candidate", card_id: m.ex2 }, actor: "Sam" }, ctx).state;
    expect(confirmed.cards[m.ex2]!.status).toBe("confirmed");
    const replace = run(m.state, propose(clarifying(ctx.nextId("prop"), "replace", { template: { kind: "card.replace", replacement_card_id: m.ex2 }, candidates: [{ card_id: m.ex1, label: "GP" }], utts: ["utt_c"] })), ctx);
    const replaced = run(replace.state, { kind: "clarification.answer", clarification_id: (replace.events[1] as Asked).clarification_id, answer: { kind: "candidate", card_id: m.ex1 }, actor: "Sam" }, ctx).state;
    expect(replaced.cards[m.ex1]!.superseded_by).toBe(m.ex2);
    const refine = run(m.state, propose(clarifying(ctx.nextId("prop"), "clarify", { template: { kind: "definition.refine", term: "appointment", definition: "a booked slot" }, candidates: [{ card_id: rule, label: "r" }], utts: ["utt_c"] })), ctx);
    const refined = run(refine.state, { kind: "clarification.answer", clarification_id: (refine.events[1] as Asked).clarification_id, answer: { kind: "candidate", card_id: rule }, actor: "Sam" }, ctx).state;
    expect(refined.cards[rule]!.definitions).toEqual([{ term: "appointment", definition: "a booked slot" }]);
    // the scenario's own round-trip
    const s = scenario();
    expect(s.state.clarifications[s.ids.clar_remove!]!.status).toBe("answered");
    expect(s.state.clarifications[s.ids.clar_amend!]!.status).toBe("dismissed");
    expect(s.state.clarifications[s.ids.clar_amend!]!.text_answers.length).toBe(1);
    expect(s.state.clarifications[s.ids.clar_refine!]!.status).toBe("answered");
  });
});
