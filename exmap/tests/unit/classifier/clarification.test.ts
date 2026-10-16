// exmap/tests/unit/classifier/clarification.test.ts — TEST-PLAN §2 clarification rows 1–20 (design §6.6).
import { describe, expect, it } from "vitest";
import { classifyRules } from "../../../src/classifier/rules-v1.js";
import type { ClassifierInput, ClassifierOperation, PendingClarification } from "../../../src/core/types.js";
import { card, input, label, pending, story, utt } from "./helpers.js";

const E1 = card("card_e1", "example", "If a GP appointment is at 10am and the patient cancels at 9am, it is refused.", { seq: 3, last_utterance_id: "utt_3", last_speaker: "Sam", proposal_id: "prop_b" });
const E2 = card("card_e2", "example", "For a nurse appointment at 10am, cancelling at 8am is allowed.", { seq: 4, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_c" });
const E3 = card("card_e3", "example", "A receptionist cancels on the patient's behalf at 9am.", { seq: 5, last_utterance_id: "utt_5", last_speaker: "Sam", proposal_id: "prop_d" });
const R1 = card("card_r1", "rule", "A patient should be able to cancel online, but not within two hours of their appointment.", { seq: 2, last_utterance_id: "utt_2", last_speaker: "Priya", proposal_id: "prop_a" });

const REMOVE_CHOICE: ClassifierOperation = { kind: "card.remove", card_id: "$choice", reason: "It's not what I meant." };

function chooseRemove(cands = [E2, E1]): PendingClarification {
  return pending({ proposal_id: "prop_05", intent: "remove", kind: "choose_target", question: "Which example do you mean?", candidates: cands.map((c) => ({ card_id: c.id, label: label(c) })), pending_operations: [REMOVE_CHOICE], asked_by_utterance_id: "utt_05" });
}

function confirmRemove(): PendingClarification {
  return pending({ proposal_id: "prop_05", intent: "remove", kind: "confirm_intent", question: "Did you mean to remove …?", candidates: [], pending_operations: [{ kind: "card.remove", card_id: "card_e1", reason: "" }], asked_by_utterance_id: "utt_05" });
}

function ask(text: string, pc: PendingClarification, over: Partial<ClassifierInput> = {}): ReturnType<typeof classifyRules> {
  return classifyRules(input({ utterance: utt("utt_06", text, { speaker: "Priya" }), cards: [story(), E1, E2], pending_clarification: pc, ...over }));
}

describe("clarification protocol", () => {
  it("1. an ordinal answer resolves the choose_target with the asking classifier's stamp", () => {
    const p = ask("The second one.", chooseRemove());
    expect(p.intent).toBe("remove");
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "It's not what I meant." }]);
    expect(p.confidence).toBe(1);
    expect(p.resolves).toEqual({ proposal_id: "prop_05", chosen_card_ids: ["card_e1"], dismissed: false });
    expect(p.source_utterance_ids).toEqual(["utt_06", "utt_05"]);
    expect(p.classifier).toEqual(chooseRemove().classifier);
    expect(p.needs_clarification).toBe(false);
    expect(p.rationale).toBe(`You chose ${label(E1)}.`);
  });

  it("2. 'Number 2.' and a bare '2' are the same answer", () => {
    for (const t of ["Number 2.", "2"]) {
      const p = ask(t, chooseRemove());
      expect(p.resolves?.chosen_card_ids).toEqual(["card_e1"]);
      expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "It's not what I meant." }]);
    }
  });

  it("3. a label answer picks the candidate whose text matches", () => {
    const p = ask("The GP one.", chooseRemove());
    expect(p.resolves?.chosen_card_ids).toEqual(["card_e1"]);
    expect(p.intent).toBe("remove");
  });

  it("4. filler words are ignored in a label answer", () => {
    const p = ask("The GP one, please.", chooseRemove());
    expect(p.resolves?.chosen_card_ids).toEqual(["card_e1"]);
  });

  it("5. a label that ties between candidates is not an answer", () => {
    const p = ask("The appointment one.", chooseRemove());
    expect(p.intent).toBe("none");
    expect(p.resolves).toBeNull();
  });

  it("6. 'The latest one.' is the first candidate", () => {
    const p = ask("The latest one.", chooseRemove());
    expect(p.resolves?.chosen_card_ids).toEqual(["card_e2"]);
  });

  it("7. 'Neither.' dismisses the question", () => {
    const p = ask("Neither.", chooseRemove());
    expect(p.intent).toBe("none");
    expect(p.heard_intent).toBe("remove");
    expect(p.resolves).toEqual({ proposal_id: "prop_05", chosen_card_ids: [], dismissed: true });
    expect(p.operations).toEqual([]);
    expect(p.source_utterance_ids).toEqual(["utt_06", "utt_05"]);
  });

  it("8. 'Neither, I meant the rule.' dismisses; a remainder without a verb is none", () => {
    const p = ask("Neither, I meant the rule.", chooseRemove(), { cards: [story(), E1, E2, R1] });
    expect(p.intent).toBe("none");
    expect(p.resolves?.dismissed).toBe(true);
    expect(p.operations).toEqual([]);
  });

  it("9. 'No, delete the rule instead.' dismisses and classifies the remainder without a reject prefix", () => {
    const p = ask("No, delete the rule instead.", chooseRemove(), { cards: [story(), E1, E2, R1] });
    expect(p.intent).toBe("remove");
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_r1", reason: "" }]);
    expect(p.resolves).toEqual({ proposal_id: "prop_05", chosen_card_ids: [], dismissed: true });
    expect(p.source_utterance_ids).toEqual(["utt_06", "utt_05"]);
  });

  it("10. a bare 'No.' to a choose_target dismisses it", () => {
    const p = ask("No.", chooseRemove());
    expect(p.intent).toBe("none");
    expect(p.resolves?.dismissed).toBe(true);
    expect(p.operations).toEqual([]);
  });

  it("11. 'No, that's not what I said.' dismisses with no remainder", () => {
    const p = ask("No, that's not what I said.", chooseRemove());
    expect(p.intent).toBe("none");
    expect(p.resolves?.dismissed).toBe(true);
    expect(p.operations).toEqual([]);
  });

  it("12. an unrelated statement leaves the clarification open and is classified normally", () => {
    const p = ask("A patient must give a reason.", chooseRemove());
    expect(p.intent).toBe("add");
    expect(p.operations[0]).toMatchObject({ kind: "card.create", card: { kind: "rule" } });
    expect(p.resolves).toBeNull();
    expect(p.source_utterance_ids).toEqual(["utt_06"]);
  });

  it("13. a bare 'Yes.' to a choose_target asks again (none, heard remove, not clarifying)", () => {
    const p = ask("Yes.", chooseRemove());
    expect(p.intent).toBe("none");
    expect(p.heard_intent).toBe("remove");
    expect(p.needs_clarification).toBe(false);
    expect(p.resolves).toBeNull();
    expect(p.rationale).toBe("Please say which one: first or second, or name it.");
  });

  it("14. 'Yes.' to a confirm_intent applies the pending operation", () => {
    const p = ask("Yes.", confirmRemove());
    expect(p.intent).toBe("remove");
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "" }]);
    expect(p.resolves).toEqual({ proposal_id: "prop_05", chosen_card_ids: [], dismissed: false });
    expect(p.confidence).toBe(1);
  });

  it("15. 'No.' to a confirm_intent dismisses it", () => {
    const p = ask("No.", confirmRemove());
    expect(p.intent).toBe("none");
    expect(p.resolves?.dismissed).toBe(true);
    expect(p.operations).toEqual([]);
  });

  it("16. 'No, make it 48 hours.' dismisses the confirm_intent and amends the rule", () => {
    const p = ask("No, make it 48 hours.", confirmRemove(), { cards: [story(), E1, R1] });
    expect(p.intent).toBe("amend");
    expect(p.operations).toEqual([{ kind: "card.update", card_id: "card_r1", patch: { text: "A patient should be able to cancel online, but not within 48 hours of their appointment.", text_append: null, answer: null, rule_id: null, about_card_id: null }, amendment: { from: "two hours", to: "48 hours", scope: null } }]);
    expect(p.resolves?.dismissed).toBe(true);
  });

  it("17. 'Both.' with two candidates removes both", () => {
    const p = ask("Both.", chooseRemove());
    expect(p.intent).toBe("remove");
    expect(p.operations).toEqual([
      { kind: "card.remove", card_id: "card_e2", reason: "It's not what I meant." },
      { kind: "card.remove", card_id: "card_e1", reason: "It's not what I meant." },
    ]);
    expect(p.resolves?.chosen_card_ids).toEqual(["card_e2", "card_e1"]);
    expect(p.target_card_ids).toEqual(["card_e2", "card_e1"]);
  });

  it("18. 'Both.' with three candidates is not an answer", () => {
    const p = ask("Both.", chooseRemove([E3, E2, E1]), { cards: [story(), E1, E2, E3] });
    expect(p.intent).toBe("none");
    expect(p.resolves).toBeNull();
  });

  it("19. choosing a card for an interpretation.reject resolves to that card's proposal", () => {
    const pc = pending({ proposal_id: "prop_17", intent: "reject", kind: "choose_target", question: "Which interpretation is wrong?", candidates: [E1, E2].map((c) => ({ card_id: c.id, label: label(c) })), pending_operations: [{ kind: "interpretation.reject", proposal_id: "$choice" }], asked_by_utterance_id: "utt_17" });
    const p = ask("The first one.", pc);
    expect(p.intent).toBe("reject");
    expect(p.operations).toEqual([{ kind: "interpretation.reject", proposal_id: "prop_b" }]);
    expect(p.resolves).toEqual({ proposal_id: "prop_17", chosen_card_ids: ["card_e1"], dismissed: false });
  });

  it("20. choosing a card made by a person cannot be rejected as an interpretation", () => {
    const byHand = { ...E2, proposal_id: null };
    const pc = pending({ proposal_id: "prop_17", intent: "reject", kind: "choose_target", question: "Which interpretation is wrong?", candidates: [E1, byHand].map((c) => ({ card_id: c.id, label: label(c) })), pending_operations: [{ kind: "interpretation.reject", proposal_id: "$choice" }], asked_by_utterance_id: "utt_17" });
    const p = ask("The second one.", pc, { cards: [story(), E1, byHand] });
    expect(p.intent).toBe("none");
    expect(p.heard_intent).toBe("reject");
    expect(p.resolves).toEqual({ proposal_id: "prop_17", chosen_card_ids: ["card_e2"], dismissed: false });
    expect(p.rationale).toContain("made by a person");
  });
});
