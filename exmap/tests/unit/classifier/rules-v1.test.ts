// exmap/tests/unit/classifier/rules-v1.test.ts — TEST-PLAN §2 rules-v1 rows 1–58 (one `it` per row).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { classifyRules, createRulesClassifier } from "../../../src/classifier/rules-v1.js";
import { ProposalSchema, assertProposalInvariants } from "../../../src/classifier/schema.js";
import type { ClassifierInput, ClassifierProposal, ClassifierUtterance } from "../../../src/core/types.js";
import { STORY_ID, card, expectOp, input, label, ref, story, utt } from "./helpers.js";

const RULE_TEXT = "A patient should be able to cancel online, but not within two hours of their appointment.";
const R1 = card("card_r1", "rule", RULE_TEXT, { seq: 3, last_utterance_id: "utt_3", last_speaker: "Sam", proposal_id: "prop_a" });
const R2 = card("card_r2", "rule", "Patients must confirm by email.", { seq: 4, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_b" });
const E1 = card("card_e1", "example", "If a GP appointment is at 10am and the patient cancels at 9am, it is refused.", { seq: 3, last_utterance_id: "utt_3", last_speaker: "Sam", proposal_id: "prop_b", links: { rule_id: "card_r1" } });
const E2 = card("card_e2", "example", "For a nurse appointment at 10am, cancelling at 8am is allowed.", { seq: 4, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_c", links: { rule_id: "card_r1" } });
const Q1 = card("card_q1", "question", "Do walk-ins count as appointments?", { seq: 4, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_q" });

const WINDOW: ClassifierUtterance[] = [utt("utt_1", "Right, let's start."), utt("utt_2", "The story is cancellation.", { speaker: "Priya" }), utt("utt_3", "A patient should be able to cancel online.", { speaker: "Sam" }), utt("utt_4", "Patients must confirm by email.", { speaker: "Priya" })];
/** A window that leaves utt_3 / utt_4 out (the last four are utt_5…utt_8). */
const LATER: ClassifierUtterance[] = [...WINDOW, utt("utt_5", "Okay."), utt("utt_6", "Right."), utt("utt_7", "Hmm."), utt("utt_8", "Yes.")];

const all: ClassifierProposal[] = [];
function run(over: NonNullable<Parameters<typeof input>[0]>, speaker = "Sam"): ClassifierProposal {
  const u = typeof over.utterance === "string" ? utt("utt_new", over.utterance, { speaker }) : over.utterance;
  const inp: ClassifierInput = input({ ...over, utterance: u });
  const p = classifyRules(inp);
  all.push(p);
  return p;
}

function expectNone(p: ClassifierProposal, heard: ClassifierProposal["heard_intent"]): void {
  expect(p.intent).toBe("none");
  expect(p.heard_intent).toBe(heard);
  expect(p.operations).toEqual([]);
  expect(p.needs_clarification).toBe(false);
}

describe("rules.v1", () => {
  it("1. chatter is none with confidence 0", () => {
    const p = run({ utterance: "Right, let's start with how cancellation works today." });
    expectNone(p, null);
    expect(p.confidence).toBe(0);
    expect(p.rationale).toBe("No map-changing cue found.");
    expect(p.classifier).toEqual({ provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null });
  });

  it("2. a modal rule statement is add rule 1.0, text verbatim", () => {
    const p = run({ utterance: RULE_TEXT });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "rule", text: RULE_TEXT, rule_id: null, about_card_id: null } });
  });

  it("3. a subject-modal opener without an article is add rule 1.0", () => {
    const p = run({ utterance: "Patients must confirm by email." });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "rule", text: "Patients must confirm by email." } });
  });

  it("4. 'We also need an error case.' is add example 0.5 (A1 + noun case)", () => {
    const p = run({ utterance: "We also need an error case." });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(0.5);
    expectOp(p, { kind: "card.create", card: { kind: "example" } });
  });

  it("5. 'We need a rule for weekends.' is add rule 0.5 (noun rule)", () => {
    const p = run({ utterance: "We need a rule for weekends." });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(0.5);
    expectOp(p, { kind: "card.create", card: { kind: "rule" } });
  });

  it("6. 'For example, if … then …' is add example 1.0 without the lead-in", () => {
    const p = run({ utterance: "For example, if a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused." });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "example", text: "If a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused." } });
  });

  it("7. Given / when / then is add example 1.0 verbatim", () => {
    const text = "Given a nurse appointment at 10am, when the patient cancels at 8am, then it is allowed.";
    const p = run({ utterance: text });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "example", text } });
  });

  it("8. 'Say a patient has …' is add example 1.0", () => {
    const p = run({ utterance: "Say a patient has two appointments on the same day." });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "example" } });
  });

  it("9. 'What about …?' after an add rule in the window is add question 1.0 about that rule", () => {
    const p = run({ utterance: "What about appointments already in progress?", cards: [story(), R1], recent: WINDOW, last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "question", about_card_id: "card_r1" } });
  });

  it("10. 'Do we know if …?' is add question 1.0", () => {
    const p = run({ utterance: "Do we know if nurses can cancel?" });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "question" } });
  });

  it("11. a bare question mark is add question 0.5 (A5 only)", () => {
    const p = run({ utterance: "Is the limit the same for nurses?" });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(0.5);
    expectOp(p, { kind: "card.create", card: { kind: "question", text: "Is the limit the same for nurses?" } });
  });

  it("12. 'I'm not sure, let's leave that open.' is none", () => {
    expectNone(run({ utterance: "I'm not sure, let's leave that open." }), null);
  });

  it("13. 'Change that limit to 24 hours.' replaces the single value of the only rule", () => {
    const p = run({ utterance: "Change that limit to 24 hours.", cards: [story(), R1] });
    expect(p.intent).toBe("amend");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{
      kind: "card.update", card_id: "card_r1",
      patch: { text: "A patient should be able to cancel online, but not within 24 hours of their appointment.", text_append: null, answer: null, rule_id: null, about_card_id: null },
      amendment: { from: "two hours", to: "24 hours", scope: null },
    }]);
  });

  it("14. a scoped amendment is appended verbatim", () => {
    const p = run({ utterance: "Actually, make that 24 hours for nurse appointments. Keep two hours for GPs.", cards: [story(), R1], recent: WINDOW, last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("amend");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{
      kind: "card.update", card_id: "card_r1",
      patch: { text: null, text_append: "Make that 24 hours for nurse appointments. Keep two hours for GPs.", answer: null, rule_id: null, about_card_id: null },
      amendment: { from: "two hours", to: "24 hours", scope: "nurse appointments" },
    }]);
  });

  it("15. two recent rules by different speakers -> choose_target, most recent first, append-form pending op", () => {
    const p = run({ utterance: "Change that limit to 24 hours.", cards: [story(), R1, R2], recent: WINDOW }, "Sam");
    expect(p.intent).toBe("amend");
    expect(p.needs_clarification).toBe(true);
    expect(p.operations).toEqual([]);
    expect(p.clarification?.kind).toBe("choose_target");
    expect(p.clarification?.candidates.map((c) => c.card_id)).toEqual(["card_r2", "card_r1"]);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "card.update", card_id: "$choice", patch: { text: null, text_append: "Change that limit to 24 hours.", answer: null, rule_id: null, about_card_id: null }, amendment: { from: null, to: "24 hours", scope: null } }]);
    expect(p.target_card_ids).toEqual(["card_r2", "card_r1"]);
  });

  it("16. two rules, neither recent -> choose_target with both", () => {
    const p = run({ utterance: "Change that limit to 24 hours.", cards: [story(), R1, R2], recent: LATER });
    expect(p.clarification?.kind).toBe("choose_target");
    expect(p.clarification?.candidates.map((c) => c.card_id)).toEqual(["card_r2", "card_r1"]);
  });

  it("17. a value amendment with no rule on the map is none / heard amend", () => {
    const p = run({ utterance: "Change it to 48 hours.", cards: [story(), E1] });
    expectNone(p, "amend");
    expect(p.rationale).toBe("There is no rule to change.");
  });

  it("18. 'Delete that example.' with two recent examples, the latest by someone else -> choose_target [E2, E1]", () => {
    const p = run({ utterance: "Delete that example.", cards: [story(), E1, E2], recent: WINDOW }, "Sam");
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(0.5);
    expect(p.clarification?.kind).toBe("choose_target");
    expect(p.clarification?.candidates.map((c) => c.card_id)).toEqual(["card_e2", "card_e1"]);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "card.remove", card_id: "$choice", reason: "" }]);
  });

  it("19. the same by the speaker who gave the latest example resolves to it", () => {
    const p = run({ utterance: "Delete that example.", cards: [story(), E1, E2], recent: WINDOW }, "Priya");
    expect(p.intent).toBe("remove");
    expect(p.needs_clarification).toBe(false);
    expectOp(p, { kind: "card.remove", card_id: "card_e2" });
    expect(p.rationale).toContain("the example you just gave");
  });

  it("20. the second sentence becomes the removal reason", () => {
    const p = run({ utterance: "Delete that example. It's not what I meant.", cards: [story(), E1], recent: WINDOW });
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "It's not what I meant." }]);
  });

  it("21. 'We don't need that rule.' is remove 0.5 (D2)", () => {
    const p = run({ utterance: "We don't need that rule.", cards: [story(), R1] });
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(0.5);
    expectOp(p, { kind: "card.remove", card_id: "card_r1" });
  });

  it("22. a named topic resolves the example", () => {
    const p = run({ utterance: "Delete the example about nurses.", cards: [story(), E1, E2] });
    expect(p.intent).toBe("remove");
    expect(p.needs_clarification).toBe(false);
    expectOp(p, { kind: "card.remove", card_id: "card_e2" });
  });

  it("23. a named topic that matches nothing asks over the examples", () => {
    const p = run({ utterance: "Delete the example about dentists.", cards: [story(), E1, E2] });
    expect(p.clarification?.kind).toBe("choose_target");
    expect(p.rationale).toContain("no example about 'dentists'");
    expect(p.clarification?.candidates.map((c) => c.card_id)).toEqual(["card_e2", "card_e1"]);
  });

  it("24. a named miss with a single example is a confirm_intent naming it", () => {
    const p = run({ utterance: "Delete the example about dentists.", cards: [story(), E1] });
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.question).toBe(`Did you mean to remove ${label(E1)}? (no example about 'dentists')`);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "" }]);
  });

  it("25. a bare 'that' after the speaker's own add resolves to it, reason after the comma", () => {
    const gp2 = card("card_gp2", "example", "A GP appointment at 10am cancelled at 7am is allowed.", { seq: 24, last_utterance_id: "utt_24", last_speaker: "Sam", proposal_id: "prop_24" });
    const gp3 = card("card_gp3", "example", "A GP appointment at 10am cancelled at 9am is refused.", { seq: 25, last_utterance_id: "utt_25", last_speaker: "Priya", proposal_id: "prop_25" });
    const recent = [utt("utt_22", "Is the two-hour window the same for dentists?"), utt("utt_23", "Let's park that for now.", { speaker: "Priya" }), utt("utt_24", gp2.text), utt("utt_25", gp3.text, { speaker: "Priya" })];
    const p = run({ utterance: "Delete that, it duplicates the GP one.", cards: [story(), R1, gp2, gp3], recent, last_proposal: ref("prop_25", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_gp3"], utterance_id: "utt_25" }) }, "Priya");
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_gp3", reason: "it duplicates the GP one" }]);
  });

  it("26. 'Use this example instead.' replaces the older example with the one just added", () => {
    const e3 = card("card_e3", "example", "For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused.", { seq: 5, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_e3" });
    const p = run({ utterance: "Use this example instead.", cards: [story(), E1, e3], recent: WINDOW, last_proposal: ref("prop_e3", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e3"], utterance_id: "utt_4" }) });
    expect(p.intent).toBe("replace");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "card.replace", card_id: "card_e1", replacement: null, replacement_card_id: "card_e3" }]);
  });

  it("27. '… instead of the old nurse one' targets the nurse example by topic", () => {
    const e3 = card("card_e3", "example", "For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused.", { seq: 5, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_e3" });
    const p = run({ utterance: "Use this example instead of the old nurse one.", cards: [story(), E1, E2, e3], recent: WINDOW, last_proposal: ref("prop_e3", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e3"], utterance_id: "utt_4" }) });
    expect(p.intent).toBe("replace");
    expect(p.operations).toEqual([{ kind: "card.replace", card_id: "card_e2", replacement: null, replacement_card_id: "card_e3" }]);
  });

  it("28. 'Instead, <new example>' replaces by text", () => {
    const p = run({ utterance: "Instead, if a GP cancels at 9am for a 10am slot it is refused.", cards: [story(), E1], recent: WINDOW });
    expect(p.intent).toBe("replace");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "card.replace", card_id: "card_e1", replacement: { text: "If a GP cancels at 9am for a 10am slot it is refused." }, replacement_card_id: null }]);
  });

  it("29. 'Use this instead.' with nothing to use is none / heard replace", () => {
    const p = run({ utterance: "Use this instead.", cards: [story(), E1] });
    expectNone(p, "replace");
    expect(p.rationale).toContain("no new content");
  });

  it("30. 'By appointment I mean …' defines the term on the story", () => {
    const p = run({ utterance: "By appointment I mean a booked slot, not a walk-in." });
    expect(p.intent).toBe("clarify");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "definition.refine", card_id: STORY_ID, term: "appointment", definition: "a booked slot, not a walk-in" }]);
  });

  it("31. 'When we say X we mean Y' keeps the hyphen in the term", () => {
    const p = run({ utterance: "When we say cut-off we mean the two-hour window." });
    expect(p.intent).toBe("clarify");
    expect(p.operations).toEqual([{ kind: "definition.refine", card_id: STORY_ID, term: "cut-off", definition: "the two-hour window" }]);
  });

  it("32. a clarification cue without a definition is none / heard clarify", () => {
    const p = run({ utterance: "To clarify, nurses are clinicians too." });
    expectNone(p, "clarify");
    expect(p.confidence).toBe(0.25);
    expect(p.rationale).toContain("say 'By X I mean Y'");
  });

  it("33. 'No, that's not what I said.' rejects the last rejectable in the window", () => {
    const p = run({ utterance: "No, that's not what I said.", cards: [story(), R1], recent: WINDOW, last_rejectable: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("reject");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "interpretation.reject", proposal_id: "prop_a" }]);
  });

  it("34. with nothing rejectable it is none / heard reject", () => {
    const p = run({ utterance: "No, that's not what I said.", cards: [story(), R1] });
    expectNone(p, "reject");
  });

  it("35. a stale last rejectable asks which interpretation is wrong", () => {
    const e1 = { ...E1, proposal_id: "prop_b", seq: 4 };
    const e2 = { ...E2, proposal_id: "prop_c", seq: 5 };
    const p = run({ utterance: "No, that's not what I said.", cards: [story(), R1, e1, e2], recent: LATER, last_rejectable: ref("prop_c", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e2"], utterance_id: "utt_4" }) });
    expect(p.intent).toBe("reject");
    expect(p.clarification?.kind).toBe("choose_target");
    expect(p.clarification?.question).toBe("Which interpretation is wrong?");
    expect(p.clarification?.candidates.map((c) => c.card_id)).toEqual(["card_e2", "card_e1", "card_r1"]);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "interpretation.reject", proposal_id: "$choice" }]);
  });

  it("36. a stale last rejectable with one interpreted card is a confirm_intent", () => {
    const p = run({ utterance: "No, that's not what I said.", cards: [story(), R1], recent: LATER, last_rejectable: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.question).toBe(`Did you mean to reject the interpretation that produced ${label(R1)}?`);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "interpretation.reject", proposal_id: "prop_a" }]);
  });

  it("37. 'No, delete the nurse example.' is a reject prefix plus a remove", () => {
    const p = run({ utterance: "No, delete the nurse example.", cards: [story(), E1, E2], recent: WINDOW, last_rejectable: ref("prop_c", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e2"], utterance_id: "utt_4" }) });
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "interpretation.reject", proposal_id: "prop_c" }, { kind: "card.remove", card_id: "card_e2", reason: "" }]);
  });

  it("38. 'Yes, that's exactly right.' confirms the last proposal's live cards", () => {
    const p = run({ utterance: "Yes, that's exactly right.", cards: [story(), R1], last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("confirm");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "confirm", card_ids: ["card_r1"] }]);
  });

  it("39. a bare 'Yes.' is confirm 0.5", () => {
    const p = run({ utterance: "Yes.", cards: [story(), R1], last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("confirm");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "confirm", card_ids: ["card_r1"] }]);
  });

  it("40. a 'Yes.' after a removal / undo / rejection reviews the act", () => {
    for (const [op, word] of [["card.remove", "removal"], ["undo", "undo"], ["interpretation.reject", "rejection"]] as const) {
      const p = run({ utterance: "Yes.", cards: [story(), R1], last_proposal: ref("prop_x", { intent: op === "card.remove" ? "remove" : op === "undo" ? "undo" : "reject", op, kind: "example", card_ids: ["card_gone"], utterance_id: "utt_3" }) });
      expect(p.intent).toBe("confirm");
      expect(p.confidence).toBe(0.5);
      expect(p.operations).toEqual([{ kind: "confirm", card_ids: [] }]);
      expect(p.rationale).toBe(`Confirmed the ${word}.`);
    }
  });

  it("41. a confirmed or confirm-kind last proposal cannot be confirmed", () => {
    const a = run({ utterance: "Yes.", cards: [story(), R1], last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3", status: "confirmed" }) });
    expectNone(a, "confirm");
    expect(a.rationale).toContain("already confirmed");
    const b = run({ utterance: "Yes.", cards: [story(), R1], last_proposal: ref("prop_f", { intent: "confirm", op: "confirm", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_4" }) });
    expectNone(b, "confirm");
    expect(b.rationale).toBe("A confirmation cannot be confirmed.");
  });

  it("42. 'Yes, but make it 24 hours.' is a confirm prefix plus the amendment", () => {
    const p = run({ utterance: "Yes, but make it 24 hours.", cards: [story(), R1], recent: WINDOW, last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("amend");
    expect(p.operations[0]).toEqual({ kind: "confirm", card_ids: ["card_r1"] });
    expect(p.operations[1]).toMatchObject({ kind: "card.update", card_id: "card_r1", patch: { text: "A patient should be able to cancel online, but not within 24 hours of their appointment." }, amendment: { from: "two hours", to: "24 hours" } });
  });

  it("43. 'Okay.' with no last proposal is none / heard confirm", () => {
    const p = run({ utterance: "Okay." });
    expectNone(p, "confirm");
    expect(p.rationale).toBe("Nothing to confirm yet.");
  });

  it("44. 'Go back to the previous version.' is undo 1.0, one step", () => {
    const p = run({ utterance: "Go back to the previous version." });
    expect(p.intent).toBe("undo");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "undo", steps: 1 }]);
  });

  it("45. 'Undo that.' is undo 0.5, one step", () => {
    const p = run({ utterance: "Undo that." });
    expect(p.intent).toBe("undo");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "undo", steps: 1 }]);
  });

  it("46. 'Undo the last two changes.' is undo 1.0, two steps", () => {
    const p = run({ utterance: "Undo the last two changes." });
    expect(p.intent).toBe("undo");
    expect(p.confidence).toBe(1);
    expect(p.operations).toEqual([{ kind: "undo", steps: 2 }]);
  });

  it("47. 'Should we delete that example?' is damped below the threshold and asks", () => {
    const p = run({ utterance: "Should we delete that example?", cards: [story(), E1] });
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(0.25);
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.question).toBe(`Did you mean to remove ${label(E1)}?`);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "" }]);
  });

  it("48. 'Yes, but not within two hours.' is a confirm prefix plus an add rule", () => {
    const p = run({ utterance: "Yes, but not within two hours.", cards: [story(), R1], recent: WINDOW, last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(0.5);
    expect(p.operations[0]).toEqual({ kind: "confirm", card_ids: ["card_r1"] });
    expect(p.operations[1]).toEqual({ kind: "card.create", card: { kind: "rule", text: "Not within two hours.", rule_id: null, about_card_id: null } });
  });

  it("49. 'Actually, 24 hours.' corrects the last rule's single value", () => {
    const p = run({ utterance: "Actually, 24 hours.", cards: [story(), R1], recent: WINDOW, last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("amend");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "card.update", card_id: "card_r1", patch: { text: "A patient should be able to cancel online, but not within 24 hours of their appointment.", text_append: null, answer: null, rule_id: null, about_card_id: null }, amendment: { from: "two hours", to: "24 hours", scope: null } }]);
  });

  it("50. 'And …' after an add example continues it as an example", () => {
    const p = run({ utterance: "And a GP appointment at 10am cancelled at 9am is refused.", cards: [story(), R1, E1], recent: WINDOW, last_proposal: ref("prop_b", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(0.5);
    expectOp(p, { kind: "card.create", card: { kind: "example", text: "A GP appointment at 10am cancelled at 9am is refused.", rule_id: "card_r1" } });
  });

  it("51. the same after an add rule continues it as a rule", () => {
    const p = run({ utterance: "And a GP appointment at 10am cancelled at 9am is refused.", cards: [story(), R1], recent: WINDOW, last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_3" }) });
    expect(p.intent).toBe("add");
    expectOp(p, { kind: "card.create", card: { kind: "rule" } });
  });

  it("52. the same with no last proposal is none", () => {
    expectNone(run({ utterance: "And a GP appointment at 10am cancelled at 9am is refused.", cards: [story(), R1] }), null);
  });

  it("53. a value amendment targets the rule even when the last proposal was a question", () => {
    const r1 = { ...R1, last_utterance_id: "utt_3" };
    const q = { ...Q1, last_utterance_id: "utt_8", seq: 8 };
    const p = run({ utterance: "Change that limit to 24 hours.", cards: [story(), r1, q], recent: LATER, last_proposal: ref("prop_q", { intent: "add", op: "card.create", kind: "question", card_ids: ["card_q1"], utterance_id: "utt_8" }) });
    expect(p.intent).toBe("amend");
    expect(p.confidence).toBe(1);
    expect(p.operations).toMatchObject([{ kind: "card.update", card_id: "card_r1" }]);
  });

  it("54. 'The answer is …' records the answer on the open question", () => {
    const p = run({ utterance: "The answer is yes, walk-ins count.", cards: [story(), R1, Q1], recent: WINDOW });
    expect(p.intent).toBe("amend");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "card.update", card_id: "card_q1", patch: { text: null, text_append: null, answer: "yes, walk-ins count", rule_id: null, about_card_id: null }, amendment: null }]);
  });

  it("55. 'We need another example.' is add example 1.0", () => {
    const p = run({ utterance: "We need another example." });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(1);
    expectOp(p, { kind: "card.create", card: { kind: "example" } });
  });

  it("56. 'Delete the rule instead.' is remove 0.5 (a trailing instead does not score replace)", () => {
    const p = run({ utterance: "Delete the rule instead.", cards: [story(), R1] });
    expect(p.intent).toBe("remove");
    expect(p.confidence).toBe(0.5);
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_r1", reason: "" }]);
  });

  it("57. classifying the whole fixture twice is byte-identical", async () => {
    const fixture = JSON.parse(readFileSync(new URL("../../../src/web/public/replay/conversation.v1.json", import.meta.url), "utf8")) as { utterances: Array<{ label: string; text: string; lane: "remote" | "me"; speaker: string }> };
    const classifier = createRulesClassifier();
    const pass = async (): Promise<ClassifierProposal[]> => {
      const out: ClassifierProposal[] = [];
      const recent: ClassifierUtterance[] = [];
      for (const u of fixture.utterances) {
        const cu: ClassifierUtterance = { id: `utt_${u.label}`, text: u.text, lane: u.lane, speaker: u.speaker };
        out.push(await classifier.classify(input({ utterance: cu, recent: recent.slice(-12), cards: [story(), R1, E1] })));
        recent.push(cu);
      }
      return out;
    };
    const a = await pass();
    const b = await pass();
    expect(a).toEqual(b);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    expect(a.length).toBe(31);
  });

  it("58. every proposal above validates and keeps the invariants", () => {
    expect(all.length).toBeGreaterThanOrEqual(56);
    for (const p of all) {
      expect(() => ProposalSchema.parse(p)).not.toThrow();
    }
    // invariants were asserted inside classifyRules for each; re-assert against a fresh minimal input where the ids are known
    const p = classifyRules(input({ utterance: utt("utt_new", "Delete that example."), cards: [story(), E1] }));
    expect(() => assertProposalInvariants(p, input({ utterance: utt("utt_new", "Delete that example."), cards: [story(), E1] }))).not.toThrow();
  });
});
