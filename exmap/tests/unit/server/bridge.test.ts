// TEST-PLAN §4.5 — the classifier bridge (design §8.7): buildClassifierInput() and toCoreCommands()/bridgeProposal(),
// pure, over states built with the real core apply().
import { describe, expect, it } from "vitest";
import { apply } from "../../../src/core/apply.js";
import { initialState } from "../../../src/core/reduce.js";
import * as select from "../../../src/core/select.js";
import type {
  ClassifierOperation, ClassifierProposal, ClassifierProvenance, Command, ExmapEvent, MapState, Operation, Proposal, Utterance,
} from "../../../src/core/types.js";
import {
  REDO_QUESTION, bridgeProposal, buildClassifierInput, intentOf, toCoreCommands, voiceActor,
} from "../../../src/server/classifier-bridge.js";
import { aiProposal, clarifying, humanProposal, stamps, testCtx, utterance } from "../core/fixtures.js";

const RULES: ClassifierProvenance = { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null };
const INTENT_OF_OP: Record<ClassifierOperation["kind"], ClassifierProposal["intent"]> = {
  "card.create": "add", "card.update": "amend", "card.remove": "remove", "card.replace": "replace", "definition.refine": "clarify",
  "interpretation.reject": "reject", confirm: "confirm", undo: "undo",
};

/** A small map threaded through core: story (human), then AI rule R, examples E1/E2 under R, question Q about R. */
class World {
  readonly ctx = testCtx().ctx;
  state: MapState = initialState("sess_bridge");
  readonly seq = new Map<string, number>();
  n = 0;
  story = "";
  R = "";
  E1 = "";
  E2 = "";
  Q = "";
  pR = "";
  pQ = "";

  run(command: Command): ExmapEvent[] {
    const r = apply(this.state, command, this.ctx);
    if (!r.ok) throw new Error(`${command.kind}: ${r.reason}: ${r.detail}`);
    this.state = r.state;
    for (const e of r.events) this.seq.set(e.id, e.seq);
    return r.events;
  }
  say(text: string, opts: Partial<Omit<Utterance, "id" | "text">> = {}): Utterance {
    const u = utterance(`utt_${++this.n}`, text, { t_start_ms: this.n * 1000, ...opts });
    this.run({ kind: "utterance.record", utterance: u });
    return u;
  }
  /** An AI proposal from an utterance, applied, plus its classification; returns [proposal id, created card id | null]. */
  ai(text: string, operation: Operation, speaker: string | null = "Priya"): [string, string | null] {
    const u = this.say(text, { speaker });
    const pid = this.ctx.nextId("prop");
    const events = this.run({ kind: "proposal.propose", proposals: [aiProposal(pid, operation, { utts: [u.id], confidence: 0.8 })] });
    this.run({ kind: "classification.record", utterance_id: u.id, intent: intentOf(operation.kind), heard_intent: null, classifier: stamps.rules(), confidence: 0.8, rationale: "", proposal_ids: [pid], refused: [], error: null });
    const made = events.find((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made");
    return [pid, made?.effects.find((f) => f.before === null)?.card_id ?? null];
  }
  input(u: Utterance) {
    return buildClassifierInput({ state: this.state, seqOfEvent: (id) => this.seq.get(id) ?? 0 }, u);
  }
  bridge(p: ClassifierProposal, u: Utterance) {
    return bridgeProposal(p, this.state, u, { nextId: this.ctx.nextId, actorForVoice: voiceActor });
  }
  /** Bridges and applies the commands, as the server's job does. */
  apply(p: ClassifierProposal, u: Utterance): ExmapEvent[] {
    const out: ExmapEvent[] = [];
    for (const c of toCoreCommands(p, this.state, u, { nextId: this.ctx.nextId, actorForVoice: voiceActor })) out.push(...this.run(c));
    return out;
  }
}

function world(): World {
  const w = new World();
  const s = w.run({ kind: "proposal.propose", proposals: [humanProposal(w.ctx.nextId("prop"), { kind: "card.create", card: { kind: "story", text: "A patient can cancel an appointment online." } }, "Sam")] });
  w.story = (s[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;
  [w.pR, w.R] = w.ai("A patient cannot cancel within two hours.", { kind: "card.create", card: { kind: "rule", text: "A patient cannot cancel within two hours of the appointment." } }) as [string, string];
  w.E1 = w.ai("GP at ten, cancel at nine: refused.", { kind: "card.create", card: { kind: "example", text: "A GP appointment at 10am cancelled at 9am is refused.", rule_id: w.R } })[1]!;
  w.E2 = w.ai("Nurse at ten, cancel at seven: allowed.", { kind: "card.create", card: { kind: "example", text: "A nurse appointment at 10am cancelled at 7am is allowed.", rule_id: w.R } }, "Sam")[1]!;
  [w.pQ, w.Q] = w.ai("What about the clinic cancelling?", { kind: "card.create", card: { kind: "question", text: "What if the clinic cancels?", about_card_id: w.R } }) as [string, string];
  return w;
}

function cp(u: Utterance, over: Partial<ClassifierProposal> & Pick<ClassifierProposal, "intent">): ClassifierProposal {
  return {
    operations: [], target_card_ids: [], confidence: 0.8, needs_clarification: false, clarification: null, resolves: null,
    rationale: "test rationale", heard_intent: null, classifier: RULES, source_utterance_ids: [u.id], ...over,
  };
}

const proposalsOf = (commands: Command[]): Proposal[] => commands.flatMap((c) => (c.kind === "proposal.propose" ? c.proposals : []));

const upd = (card_id: string, patch: Partial<Extract<ClassifierOperation, { kind: "card.update" }>["patch"]>, amendment: Extract<ClassifierOperation, { kind: "card.update" }>["amendment"] = null): ClassifierOperation => ({
  kind: "card.update", card_id, patch: { text: null, text_append: null, answer: null, rule_id: null, about_card_id: null, ...patch }, amendment,
});

describe("toCoreCommands", () => {
  it("maps every classifier op to the expected core op, with intent === intentOf(kind) and the classifier's stamp", () => {
    const w = world();
    const u = w.say("utterance under test");
    const target = select.undoTarget(w.state, 1);
    const table: Array<[ClassifierOperation, Operation]> = [
      [{ kind: "card.create", card: { kind: "rule", text: "Rule two.", rule_id: null, about_card_id: null } }, { kind: "card.create", card: { kind: "rule", text: "Rule two." } }],
      [{ kind: "card.create", card: { kind: "example", text: "Example three.", rule_id: w.R, about_card_id: null } }, { kind: "card.create", card: { kind: "example", text: "Example three.", rule_id: w.R } }],
      [{ kind: "card.create", card: { kind: "question", text: "Question two?", rule_id: null, about_card_id: w.R } }, { kind: "card.create", card: { kind: "question", text: "Question two?", about_card_id: w.R } }],
      [upd(w.R, { text: "A patient cannot cancel within 24 hours." }), { kind: "card.update", card_id: w.R, patch: { text: "A patient cannot cancel within 24 hours." } }],
      [{ kind: "card.remove", card_id: w.E1, reason: "" }, { kind: "card.remove", card_id: w.E1 }],
      [{ kind: "card.replace", card_id: w.E1, replacement: { text: "A GP appointment at 11am cancelled at 10am is refused." }, replacement_card_id: null }, { kind: "card.replace", card_id: w.E1, replacement: { text: "A GP appointment at 11am cancelled at 10am is refused." } }],
      [{ kind: "definition.refine", card_id: w.R, term: "appointment", definition: "a booked slot" }, { kind: "definition.refine", card_id: w.R, term: "appointment", definition: "a booked slot" }],
      [{ kind: "interpretation.reject", proposal_id: w.pQ }, { kind: "interpretation.reject", proposal_id: w.pQ }],
      [{ kind: "confirm", card_ids: [w.E1] }, { kind: "confirm", card_ids: [w.E1], proposal_ids: [] }],
      [{ kind: "undo", steps: 1 }, { kind: "undo", to_revision_seq: target }],
    ];
    for (const [cop, expected] of table) {
      const p = cp(u, { intent: INTENT_OF_OP[cop.kind], operations: [cop] });
      const { commands, refused } = w.bridge(p, u);
      expect(refused, cop.kind).toEqual([]);
      expect(commands, cop.kind).toHaveLength(1);
      const [prop] = proposalsOf(commands);
      expect(prop!.operation, cop.kind).toEqual(expected);
      expect(prop!.intent, cop.kind).toBe(intentOf(expected.kind));
      expect(prop!.confidence).toBe(0.8);
      expect(prop!.source_utterance_ids).toEqual([u.id]);
      expect(prop!.needs_clarification).toBe(false);
      // a voice confirmation carries the speaker label; every other AI interpretation carries actor null
      expect(prop!.classifier, cop.kind).toEqual({ ...RULES, actor: cop.kind === "confirm" ? "Priya" : null });
    }
  });

  it("a story create with a live story becomes card.update under amend", () => {
    const w = world();
    const u = w.say("The story is: a patient cancels online or by phone.");
    const p = cp(u, { intent: "add", operations: [{ kind: "card.create", card: { kind: "story", text: "A patient cancels online or by phone.", rule_id: null, about_card_id: null } }] });
    const [prop] = proposalsOf(toCoreCommands(p, w.state, u, { nextId: w.ctx.nextId, actorForVoice: voiceActor }));
    expect(prop!.operation).toEqual({ kind: "card.update", card_id: w.story, patch: { text: "A patient cancels online or by phone." } });
    expect(prop!.intent).toBe("amend");
    expect(prop!.rationale).toBe("test rationale (the map already has a story; updating it)");
    w.apply(p, u);
    expect(select.story(w.state)?.text).toBe("A patient cancels online or by phone.");
  });

  it("a confirm prefix under remove and a reject prefix under amend are their own proposals in one proposal.propose", () => {
    const w = world();
    const u = w.say("Yes that one is right, but delete the nurse example.");
    const p = cp(u, { intent: "remove", operations: [{ kind: "confirm", card_ids: [w.E1] }, { kind: "card.remove", card_id: w.E2, reason: "wrong times" }] });
    const commands = toCoreCommands(p, w.state, u, { nextId: w.ctx.nextId, actorForVoice: voiceActor });
    expect(commands.map((c) => c.kind)).toEqual(["proposal.propose"]);
    const props = proposalsOf(commands);
    expect(props.map((x) => x.intent)).toEqual(["confirm", "remove"]);
    expect(props[1]!.rationale).toBe("test rationale — wrong times");
    const events = w.apply(p, u);
    expect(new Set(events.map((e) => e.batch_id)).size).toBe(1);

    const w2 = world();
    const u2 = w2.say("No, that question is wrong; change the rule to 24 hours.");
    const p2 = cp(u2, { intent: "amend", operations: [{ kind: "interpretation.reject", proposal_id: w2.pQ }, upd(w2.R, { text: "A patient cannot cancel within 24 hours." })] });
    const props2 = proposalsOf(toCoreCommands(p2, w2.state, u2, { nextId: w2.ctx.nextId, actorForVoice: voiceActor }));
    expect(props2.map((x) => x.intent)).toEqual(["reject", "amend"]);
    expect(props2.map((x) => x.operation?.kind)).toEqual(["interpretation.reject", "card.update"]);
  });

  it("replacement_card_id → one card.replace; text_append → patch.text = current + \" \" + append", () => {
    const w = world();
    const u = w.say("Use the nurse example instead of the GP one.");
    const rep = proposalsOf(toCoreCommands(cp(u, { intent: "replace", operations: [{ kind: "card.replace", card_id: w.E1, replacement: null, replacement_card_id: w.E2 }] }), w.state, u, { nextId: w.ctx.nextId, actorForVoice: voiceActor }));
    expect(rep).toHaveLength(1);
    expect(rep[0]!.operation).toEqual({ kind: "card.replace", card_id: w.E1, replacement_card_id: w.E2 });

    const append = proposalsOf(toCoreCommands(cp(u, { intent: "amend", operations: [upd(w.R, { text_append: "  Keep two hours for GPs.  " })] }), w.state, u, { nextId: w.ctx.nextId, actorForVoice: voiceActor }));
    expect(append[0]!.operation).toEqual({ kind: "card.update", card_id: w.R, patch: { text: "A patient cannot cancel within two hours of the appointment. Keep two hours for GPs." } });
  });

  it("confirm { card_ids: [] } reviews a removal last_proposal; after a create it is refused NOTHING_TO_CONFIRM", () => {
    const w = world();
    const u0 = w.say("Yes.");
    const skipped = w.bridge(cp(u0, { intent: "confirm", operations: [{ kind: "confirm", card_ids: [] }] }), u0);
    expect(skipped.commands).toEqual([]);
    expect(skipped.refused).toEqual([{ operation: "unknown", reason: "NOTHING_TO_CONFIRM", detail: expect.any(String) }]);

    const [removal] = w.ai("Delete the nurse example.", { kind: "card.remove", card_id: w.E2 });
    const u = w.say("Yes, that's right.");
    const { commands, refused } = w.bridge(cp(u, { intent: "confirm", operations: [{ kind: "confirm", card_ids: [] }] }), u);
    expect(refused).toEqual([]);
    expect(proposalsOf(commands)[0]!.operation).toEqual({ kind: "confirm", card_ids: [], proposal_ids: [removal] });
    w.apply(cp(u, { intent: "confirm", operations: [{ kind: "confirm", card_ids: [] }] }), u);
    expect(w.state.proposals[removal]!.status).toBe("confirmed");
    expect(select.unreviewedActs(w.state)).toEqual([]);
  });

  it("undo { steps: 2 } → select.undoTarget(state, 2); an undo right after an undo asks \"redo it?\" unless the words say redo", () => {
    const w = world();
    const u = w.say("Go back two steps.");
    const two = proposalsOf(w.bridge(cp(u, { intent: "undo", operations: [{ kind: "undo", steps: 2 }] }), u).commands);
    expect(two[0]!.operation).toEqual({ kind: "undo", to_revision_seq: select.undoTarget(w.state, 2) });

    w.apply(cp(u, { intent: "undo", operations: [{ kind: "undo", steps: 1 }] }), u);
    expect(select.currentRevision(w.state).cause).toBe("undo.applied");
    const again = w.say("Go back to the previous version.");
    const ask = proposalsOf(w.bridge(cp(again, { intent: "undo", operations: [{ kind: "undo", steps: 1 }] }), again).commands);
    expect(ask[0]).toMatchObject({
      intent: "undo", operation: null, needs_clarification: true, question: REDO_QUESTION, template: null, candidates: [],
      pending_operation: { kind: "undo", to_revision_seq: select.undoTarget(w.state, 1) },
    });
    const redo = w.say("Redo that.");
    const plain = proposalsOf(w.bridge(cp(redo, { intent: "undo", operations: [{ kind: "undo", steps: 1 }] }), redo).commands);
    expect(plain[0]!.operation).toEqual({ kind: "undo", to_revision_seq: select.undoTarget(w.state, 1) });
    // the "redo it?" clarification applies through core and a voice yes resolves it with the exact pending operation
    w.apply(cp(again, { intent: "undo", operations: [{ kind: "undo", steps: 1 }] }), again);
    const clar = select.openClarifications(w.state)[0]!;
    const yes = w.say("Yes.");
    const resolved = cp(yes, {
      intent: "undo", confidence: 1, operations: [{ kind: "undo", steps: 1 }], source_utterance_ids: [yes.id, again.id],
      resolves: { proposal_id: clar.proposal_id, chosen_card_ids: [], dismissed: false },
    });
    const props = proposalsOf(w.bridge(resolved, yes).commands);
    expect(props[0]!.operation).toEqual(clar.pending_operation);
    expect(props[0]!.needs_clarification).toBe(false);
  });

  it("choose_target → a template without its target, candidates unranked; a card.update template carries the amendment", () => {
    const w = world();
    const u = w.say("Delete that example.");
    const remove = cp(u, {
      intent: "remove", confidence: 0.5, needs_clarification: true, target_card_ids: [w.E1, w.E2],
      clarification: { kind: "choose_target", question: "Which example?", candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }], pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "Not what I meant." }] },
    });
    const [ask] = proposalsOf(w.bridge(remove, u).commands);
    expect(ask).toMatchObject({
      intent: "remove", operation: null, needs_clarification: true, question: "Which example?", pending_operation: null,
      template: { kind: "card.remove" },
      candidates: [{ card_id: w.E1, label: "GP", score: null }, { card_id: w.E2, label: "nurse", score: null }],
    });
    expect(ask!.rationale).toBe("test rationale — Not what I meant.");

    const u2 = w.say("change that limit to 24 hours");
    const amend = cp(u2, {
      intent: "amend", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which card?", candidates: [{ card_id: w.R, label: "rule" }, { card_id: w.E1, label: "GP" }], pending_operations: [upd("$choice", { text_append: "Amendment: change that limit to 24 hours" }, { from: "two hours", to: "24 hours", scope: null })] },
    });
    const [ask2] = proposalsOf(w.bridge(amend, u2).commands);
    expect(ask2!.template).toEqual({
      kind: "card.update",
      patch: { text: "Amendment: change that limit to 24 hours" },
      amendment: { from: "two hours", to: "24 hours", scope: null, append: "Change that limit to 24 hours." },
    });
    // through core: a click on the rule recomputes the text for that card
    w.apply(amend, u2);
    const clar = select.openClarifications(w.state)[0]!;
    w.run({ kind: "clarification.answer", clarification_id: clar.id, answer: { kind: "candidate", card_id: w.R }, actor: "Ana" });
    expect(w.state.cards[w.R]!.text).toBe("A patient cannot cancel within 24 hours of the appointment.");
  });

  it("a voice choice of an amendment template gives the same text a click would", () => {
    const w = world();
    const u = w.say("change that to a day");
    w.apply(cp(u, {
      intent: "amend", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which card?", candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }], pending_operations: [upd("$choice", { text_append: "change that to a day" }, { from: null, to: "", scope: null })] },
    }), u);
    const clar = select.openClarifications(w.state)[0]!;
    const input = w.input(w.say("The GP one."));
    expect(input.pending_clarification?.pending_operations[0]).toMatchObject({ kind: "card.update", card_id: "$choice", patch: { text_append: "Change that to a day." } });
    const answer = w.state.utterances[w.state.utterances.length - 1]!;
    const voice = cp(answer, {
      intent: "amend", confidence: 1, operations: [upd(w.E1, { text_append: "Change that to a day." }, { from: null, to: "", scope: null })],
      source_utterance_ids: [answer.id, u.id], resolves: { proposal_id: clar.proposal_id, chosen_card_ids: [w.E1], dismissed: false },
    });
    const [prop] = proposalsOf(w.bridge(voice, answer).commands);
    expect(prop!.operation).toEqual({ kind: "card.update", card_id: w.E1, patch: { text: "A GP appointment at 10am cancelled at 9am is refused. Amendment: Change that to a day." } });
  });

  it("confirm_intent → pending_operation, template null, candidates []", () => {
    const w = world();
    const u = w.say("Maybe remove the question?");
    const p = cp(u, {
      intent: "remove", confidence: 0.45, needs_clarification: true,
      clarification: { kind: "confirm_intent", question: "Remove the clinic question?", candidates: [], pending_operations: [{ kind: "card.remove", card_id: w.Q, reason: "" }] },
    });
    const [ask] = proposalsOf(w.bridge(p, u).commands);
    expect(ask).toMatchObject({ intent: "remove", operation: null, needs_clarification: true, template: null, candidates: [], pending_operation: { kind: "card.remove", card_id: w.Q }, question: "Remove the clinic question?" });
  });

  it("resolves (not dismissed) → a text answer, then resolves_clarification_id on exactly the first proposal; the speaker is the actor", () => {
    const w = world();
    const ask = w.say("Delete those examples.");
    w.apply(cp(ask, {
      intent: "remove", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which example?", candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }], pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "" }] },
    }), ask);
    const clar = select.openClarifications(w.state)[0]!;
    const both = w.say("Both of them.", { speaker: null, lane: "remote" });
    const p = cp(both, {
      intent: "remove", confidence: 1, operations: [{ kind: "card.remove", card_id: w.E1, reason: "" }, { kind: "card.remove", card_id: w.E2, reason: "" }],
      source_utterance_ids: [both.id, ask.id], resolves: { proposal_id: clar.proposal_id, chosen_card_ids: [w.E1, w.E2], dismissed: false },
    });
    const { commands } = w.bridge(p, both);
    expect(commands.map((c) => c.kind)).toEqual(["clarification.answer", "proposal.propose"]);
    expect(commands[0]).toEqual({ kind: "clarification.answer", clarification_id: clar.id, answer: { kind: "text", text: "Both of them.", utterance_id: both.id }, actor: "(Call, no speaker label)" });
    const props = proposalsOf(commands);
    expect(props.map((x) => x.resolves_clarification_id)).toEqual([clar.id, null]);
    expect(props.map((x) => x.classifier.actor)).toEqual(["(Call, no speaker label)", "(Call, no speaker label)"]);
    w.apply(p, both);
    expect(w.state.clarifications[clar.id]!.status).toBe("answered");
    expect(select.unreviewedActs(w.state)).toEqual([]); // the person chose both removals
    expect(voiceActor({ speaker: "Priya", lane: "me" })).toBe("Priya");
    expect(voiceActor({ speaker: null, lane: "manual" })).toBe("(Typed, no speaker label)");
  });

  it("resolves (dismissed) with a remainder → dismiss first, then the remainder with resolves_clarification_id null", () => {
    const w = world();
    const ask = w.say("Delete that example.");
    w.apply(cp(ask, {
      intent: "remove", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which example?", candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }], pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "" }] },
    }), ask);
    const clar = select.openClarifications(w.state)[0]!;
    const no = w.say("Neither, I meant we need an error case.");
    const p = cp(no, {
      intent: "add", operations: [{ kind: "card.create", card: { kind: "example", text: "Cancelling a past appointment shows an error.", rule_id: w.R, about_card_id: null } }],
      source_utterance_ids: [no.id, ask.id], resolves: { proposal_id: clar.proposal_id, chosen_card_ids: [], dismissed: true },
    });
    const { commands } = w.bridge(p, no);
    expect(commands[0]).toEqual({ kind: "clarification.answer", clarification_id: clar.id, answer: { kind: "dismiss", reason: no.text }, actor: "Priya" });
    const props = proposalsOf(commands);
    expect(props).toHaveLength(1);
    expect(props[0]!.resolves_clarification_id).toBeNull();
    expect(props[0]!.classifier.actor).toBeNull();
    w.apply(p, no);
    expect(w.state.clarifications[clar.id]!.status).toBe("dismissed");

    // a dismissal with intent none still dismisses
    const w2 = world();
    const ask2 = w2.say("Delete that example.");
    w2.apply(cp(ask2, {
      intent: "remove", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which example?", candidates: [{ card_id: w2.E1, label: "GP" }, { card_id: w2.E2, label: "nurse" }], pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "" }] },
    }), ask2);
    const c2 = select.openClarifications(w2.state)[0]!;
    const neither = w2.say("Neither.");
    const cmds = toCoreCommands(cp(neither, { intent: "none", heard_intent: "remove", confidence: 1, source_utterance_ids: [neither.id, ask2.id], resolves: { proposal_id: c2.proposal_id, chosen_card_ids: [], dismissed: true } }), w2.state, neither, { nextId: w2.ctx.nextId, actorForVoice: voiceActor });
    expect(cmds.map((c) => c.kind)).toEqual(["clarification.answer"]);
  });

  it("a resolves whose utterance is already in text_answers records no second text answer; prompt_version is carried", () => {
    const w = world();
    const ask = w.say("Delete that example.");
    w.apply(cp(ask, {
      intent: "remove", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which example?", candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }], pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "" }] },
    }), ask);
    const clar = select.openClarifications(w.state)[0]!;
    const typed = w.say("The GP one", { lane: "manual", speaker: "Ana", provider: "manual" });
    w.run({ kind: "clarification.answer", clarification_id: clar.id, answer: { kind: "text", text: typed.text, utterance_id: typed.id }, actor: "Ana" });
    const claude: ClassifierProvenance = { provider: "claude", model: "test-model-id", prompt_version: "exmap.classifier.claude.v1", fallback_from: null, error: null };
    const p = cp(typed, {
      intent: "remove", confidence: 1, operations: [{ kind: "card.remove", card_id: w.E1, reason: "" }], classifier: claude,
      source_utterance_ids: [typed.id, ask.id], resolves: { proposal_id: clar.proposal_id, chosen_card_ids: [w.E1], dismissed: false },
    });
    const commands = toCoreCommands(p, w.state, typed, { nextId: w.ctx.nextId, actorForVoice: voiceActor });
    expect(commands.map((c) => c.kind)).toEqual(["proposal.propose"]);
    const [prop] = proposalsOf(commands);
    expect(prop!.classifier).toEqual({ ...claude, actor: "Ana" });
    expect(prop!.resolves_clarification_id).toBe(clar.id);
  });
});

describe("buildClassifierInput", () => {
  it("passes lane manual and speaker null through; builds answer / proposal_id / last_speaker; recent is the 12 before", () => {
    const w = world();
    const human = w.run({ kind: "proposal.propose", proposals: [humanProposal(w.ctx.nextId("prop"), { kind: "card.update", card_id: w.Q, patch: { answer: "The clinic rebooks the patient." } }, "Ana")] });
    void human;
    for (let i = 0; i < 12; i++) w.say(`filler ${i}`);
    const u = w.say("typed note", { lane: "manual", speaker: null, provider: "manual" });
    const input = w.input(u);
    expect(input.utterance).toEqual({ id: u.id, text: "typed note", lane: "manual", speaker: null });
    expect(input.recent).toHaveLength(12);
    expect(input.recent[11]!.text).toBe("filler 11");
    expect(input.recent.some((r) => r.id === u.id)).toBe(false);
    const byId = new Map(input.cards.map((c) => [c.id, c]));
    expect(input.cards.map((c) => c.id)).toEqual([w.story, w.R, w.E1, w.E2, w.Q]);
    expect(byId.get(w.story)).toMatchObject({ kind: "story", proposal_id: null, last_utterance_id: null, last_speaker: null });
    expect(byId.get(w.R)).toMatchObject({ kind: "rule", proposal_id: w.pR, last_speaker: "Priya", links: { rule_id: null, about_card_id: null } });
    expect(byId.get(w.E1)!.links.rule_id).toBe(w.R);
    expect(byId.get(w.E2)!.last_speaker).toBe("Sam");
    expect(byId.get(w.Q)).toMatchObject({ answer: "The clinic rebooks the patient.", proposal_id: null, links: { about_card_id: w.R } });
    expect(byId.get(w.R)!.seq).toBe(w.seq.get(w.state.cards[w.R]!.changed.event_id));
    expect(byId.get(w.R)!.title).toBe(w.state.cards[w.R]!.text.slice(0, 60));
  });

  it("last_proposal includes a confirmed one and skips human proposals; last_rejectable uses select.isRejectable", () => {
    const w = world();
    // a voice confirmation of E1 (an AI confirm proposal) then a human confirmation of the question
    const yes = w.say("Yes, the GP example is right.");
    w.apply(cp(yes, { intent: "confirm", operations: [{ kind: "confirm", card_ids: [w.E1] }] }), yes);
    w.run({ kind: "proposal.propose", proposals: [humanProposal(w.ctx.nextId("prop"), { kind: "confirm", card_ids: [w.Q], proposal_ids: [] }, "Ana")] });
    const input = w.input(w.say("next"));
    // the most recent non-human applied|confirmed proposal is the voice confirm (applied)
    const last = select.lastAppliedProposal(w.state, { aiOnly: true, statuses: ["applied", "confirmed"] })!;
    expect(input.last_proposal).toMatchObject({ id: last.proposal.id, op: "confirm", intent: "confirm", status: "applied", rejectable: false });
    expect(input.last_proposal!.utterance_id).toBe(yes.id);
    // last_rejectable: the newest rejectable proposal that cites an utterance — the question's create is confirmed now
    // (not rejectable) and so is E1's, so it is E2's create
    const expected = [...w.state.proposal_order].reverse().find((id) => w.state.proposals[id]!.proposal.source_utterance_ids.length > 0 && select.isRejectable(w.state, id));
    expect(input.last_rejectable?.id).toBe(expected);
    expect(select.isRejectable(w.state, w.pQ)).toBe(false);
    expect(input.last_rejectable).toMatchObject({ op: "card.create", kind: "example", card_ids: [w.E2], rejectable: true });

    // a confirmed proposal counts for last_proposal
    const w2 = world();
    const q = w2.say("The clinic question is right.");
    w2.apply(cp(q, { intent: "confirm", operations: [{ kind: "confirm", card_ids: [w2.Q] }] }), q);
    expect(w2.state.proposals[w2.pQ]!.status).toBe("confirmed");
    const ref = buildClassifierInput({ state: w2.state, seqOfEvent: () => 0 }, w2.say("ok"));
    expect(ref.last_proposal?.op).toBe("confirm");
    const lastNonConfirm = select.lastAppliedProposal(w2.state, { aiOnly: true, statuses: ["confirmed"] });
    expect(lastNonConfirm?.proposal.id).toBe(w2.pQ);
  });

  it("pending_clarification is the most recent representable open one: confirm_intent maps back from pending_operation; a pure question is skipped", () => {
    const w = world();
    const a = w.say("Remove the question maybe.");
    const confirmIntent = clarifying(w.ctx.nextId("prop"), "remove", { utts: [a.id], pending: { kind: "card.remove", card_id: w.Q }, question: "Remove the clinic question?" });
    w.run({ kind: "proposal.propose", proposals: [confirmIntent] });
    let input = w.input(w.say("hmm"));
    expect(input.pending_clarification).toMatchObject({
      proposal_id: confirmIntent.id, kind: "confirm_intent", candidates: [], intent: "remove", asked_by_utterance_id: a.id,
      pending_operations: [{ kind: "card.remove", card_id: w.Q, reason: "" }], classifier: RULES, question: "Remove the clinic question?",
    });

    const b = w.say("Which one?");
    const chooser = clarifying(w.ctx.nextId("prop"), "remove", {
      utts: [b.id], template: { kind: "card.remove" }, candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }],
    });
    w.run({ kind: "proposal.propose", proposals: [chooser] });
    input = w.input(w.say("hmm"));
    expect(input.pending_clarification).toMatchObject({
      proposal_id: chooser.id, kind: "choose_target", candidates: [{ card_id: w.E1, label: "GP" }, { card_id: w.E2, label: "nurse" }],
      pending_operations: [{ kind: "card.remove", card_id: "$choice" }],
    });

    const c = w.say("Something to ask?");
    const pure = clarifying(w.ctx.nextId("prop"), "add", { utts: [c.id], question: "Should the story mention phone bookings?" });
    w.run({ kind: "proposal.propose", proposals: [pure] });
    input = w.input(w.say("hmm"));
    expect(input.pending_clarification?.proposal_id).toBe(chooser.id); // the pure question is click-only
    const only = world();
    const d = only.say("Ask something.");
    only.run({ kind: "proposal.propose", proposals: [clarifying(only.ctx.nextId("prop"), "add", { utts: [d.id], question: "Anything else?" })] });
    expect(only.input(only.say("hmm")).pending_clarification).toBeNull();
  });
});

describe("voice reject after the newest interpretation was confirmed (review finding, real rules.v1 through the app)", () => {
  it("asks about the older rule instead of rejecting it, and leaves both cards as they were", async () => {
    const { classifyRules } = await import("../../../src/classifier/rules-v1.js");
    const h = await import("./helpers.js");
    const t = await h.makeApp({ classifier: h.fakeClassifier([], (input) => classifyRules(input)) });
    const s = await h.createSession(t.app, { story: "As a patient I want to cancel my appointment online" });
    await h.postUtterance(t.app, s.id, h.uttId(), "A patient should be able to cancel online, but not within two hours of their appointment.", { speaker: "Sam" });
    await h.postUtterance(t.app, s.id, h.uttId(), "For example, if a patient cancels three hours before, then the cancellation succeeds.", { speaker: "Priya" });
    const cards = () => Object.values(t.app.exmap.store.open(s.id).state.cards);
    const rule = cards().find((c) => c.kind === "rule")!;
    const example = cards().find((c) => c.kind === "example")!;
    expect([rule.status, example.status]).toEqual(["applied", "applied"]);
    expect((await h.call(t.app, "POST", `/api/sessions/${s.id}/cards/${example.id}/confirm`, { actor: "Sam" })).statusCode).toBe(200);
    const res = await h.postUtterance(t.app, s.id, h.uttId(), "No, that's not what I said.", { speaker: "Priya" });
    const c = h.json<{ classification: { intent: string; needs_clarification?: boolean } }>(res).classification;
    expect(c.intent).toBe("reject");
    const state = t.app.exmap.store.open(s.id).state;
    expect(state.cards[rule.id]!.status).toBe("applied");
    expect(state.cards[example.id]!.status).toBe("confirmed");
    const open = select.openClarifications(state);
    expect(open).toHaveLength(1);
    expect(open[0]!.question).toContain("The last interpretation has been confirmed");
  });
});
