// tests/unit/core/fixtures.ts — design §5.10: testCtx() (counter ids, a clock stepping 1 s) and scenario() (the brief's
// conversation as bound commands, run through apply() step by step with every id captured).
import { expect } from "vitest";
import { apply } from "../../../src/core/apply.js";
import { sha256 } from "../../../src/server/hash.js";
import type {
  ApplyContext, ApplyResult, ClassifierStamp, Command, ExmapEvent, IdPrefix, Intent, MapState, Operation,
  OperationTemplate, Proposal, Utterance,
} from "../../../src/core/types.js";
import { initialState } from "../../../src/core/reduce.js";

export const SESSION_ID = "sess_scenario";

export interface TestCtx {
  ctx: ApplyContext;
  calls: { nextId: number; now: number; byPrefix: Record<IdPrefix, number> };
}

/** Counter ids `evt_1`, `card_1`, … per prefix and a fixed clock stepping 1 s per call. */
export function testCtx(start = "2026-10-16T12:00:00.000Z"): TestCtx {
  const counters = new Map<string, number>();
  let t = Date.parse(start);
  const calls: TestCtx["calls"] = { nextId: 0, now: 0, byPrefix: { evt: 0, card: 0, prop: 0, clar: 0, sig: 0, utt: 0 } };
  const ctx: ApplyContext = {
    now: () => {
      calls.now++;
      const at = new Date(t).toISOString();
      t += 1000;
      return at;
    },
    nextId: (prefix) => {
      calls.nextId++;
      calls.byPrefix[prefix]++;
      const n = (counters.get(prefix) ?? 0) + 1;
      counters.set(prefix, n);
      return `${prefix}_${n}`;
    },
    sha256,
  };
  return { ctx, calls };
}

/* ───────────── builders ───────────── */

export function utterance(id: string, text: string, opts: Partial<Omit<Utterance, "id" | "text">> = {}): Utterance {
  const t = opts.t_start_ms ?? 0;
  return {
    id, text, lane: opts.lane ?? "remote", speaker: opts.speaker === undefined ? "Priya" : opts.speaker, provider: opts.provider ?? "replay",
    model: opts.model ?? null, t_start_ms: t, t_end_ms: opts.t_end_ms ?? t + 3000, is_local: opts.is_local ?? true, confidence: opts.confidence ?? null,
  };
}

export const stamps = {
  rules(actor: string | null = null): ClassifierStamp {
    return { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null, actor };
  },
  claude(actor: string | null = null): ClassifierStamp {
    return { provider: "claude", model: "claude-test", prompt_version: "exmap.classifier.claude.v1", fallback_from: null, error: null, actor };
  },
  fallback(error = "CLASSIFIER_TIMEOUT", actor: string | null = null): ClassifierStamp {
    return { provider: "rules.v1", model: null, prompt_version: "exmap.classifier.claude.v1", fallback_from: "claude", error, actor };
  },
  human(actor: string): ClassifierStamp {
    return { provider: "human", model: null, prompt_version: null, fallback_from: null, error: null, actor };
  },
};

export const INTENT_OF_KIND: Record<Operation["kind"], Intent> = {
  "card.create": "add", "card.update": "amend", "card.remove": "remove", "card.replace": "replace", "definition.refine": "clarify",
  "interpretation.reject": "reject", confirm: "confirm", undo: "undo",
};

export interface ProposalOpts {
  utts?: string[];
  confidence?: number;
  stamp?: ClassifierStamp;
  rationale?: string;
  intent?: Intent;
  resolves?: string | null;
}

export function aiProposal(id: string, operation: Operation, opts: ProposalOpts = {}): Proposal {
  return {
    id, intent: opts.intent ?? INTENT_OF_KIND[operation.kind], operation, template: null, pending_operation: null, candidates: [],
    confidence: opts.confidence ?? 1, needs_clarification: false, question: null, source_utterance_ids: opts.utts ?? [],
    classifier: opts.stamp ?? stamps.rules(), resolves_clarification_id: opts.resolves ?? null, rationale: opts.rationale ?? "test proposal",
  };
}

export function humanProposal(id: string, operation: Operation, actor = "Sam", rationale = `by ${actor}`): Proposal {
  return aiProposal(id, operation, { stamp: stamps.human(actor), utts: [], confidence: 1, rationale });
}

export interface ClarifyingOpts extends ProposalOpts {
  question?: string;
  template?: OperationTemplate | null;
  pending?: Operation | null;
  candidates?: Array<{ card_id: string; label: string; score?: number | null }>;
}

export function clarifying(id: string, intent: Intent, opts: ClarifyingOpts = {}): Proposal {
  return {
    id, intent, operation: null, template: opts.template ?? null, pending_operation: opts.pending ?? null,
    candidates: (opts.candidates ?? []).map((c) => ({ card_id: c.card_id, label: c.label, score: c.score === undefined ? null : c.score })),
    confidence: opts.confidence ?? 0.5, needs_clarification: true, question: opts.question ?? "Which one do you mean?",
    source_utterance_ids: opts.utts ?? [], classifier: opts.stamp ?? stamps.rules(), resolves_clarification_id: opts.resolves ?? null,
    rationale: opts.rationale ?? "ambiguous target",
  };
}

export function propose(...proposals: Proposal[]): Command {
  return { kind: "proposal.propose", proposals };
}

export function classify(utterance_id: string, intent: Intent | "none", proposal_ids: string[] = [], opts: Partial<Extract<Command, { kind: "classification.record" }>> = {}): Command {
  return {
    kind: "classification.record", utterance_id, intent, heard_intent: opts.heard_intent ?? null, classifier: opts.classifier ?? stamps.rules(),
    confidence: opts.confidence ?? (intent === "none" ? 0 : 1), rationale: opts.rationale ?? "", proposal_ids, refused: opts.refused ?? [], error: opts.error ?? null,
  };
}

export const CONFIRMATION = "I have reviewed the complete requirement and confirm it represents the agreed intent.";

export function signoff(state: MapState, reviewer = "Sam", text = CONFIRMATION): Command {
  return { kind: "signoff.record", reviewer: { name: reviewer }, confirmation_text: text, cited_revision_hash: state.revisions[state.revisions.length - 1]!.hash };
}

/* ───────────── running ───────────── */

export type Ok = Extract<ApplyResult, { ok: true }>;
export type Refused = Extract<ApplyResult, { ok: false }>;

export function run(state: MapState, command: Command, ctx: ApplyContext): Ok {
  const result = apply(state, command, ctx);
  if (!result.ok) throw new Error(`apply refused ${result.reason}: ${result.detail}`);
  return result;
}

export function refused(state: MapState, command: Command, ctx: ApplyContext): Refused {
  const result = apply(state, command, ctx);
  expect(result.ok, "expected a refusal").toBe(false);
  return result as Refused;
}

export function createdCardId(events: readonly ExmapEvent[]): string {
  for (const e of events) {
    if (e.type === "proposal.made") {
      const created = e.effects.find((x) => x.before === null);
      if (created) return created.card_id;
    }
    if (e.type === "proposal.applied") {
      const created = e.effects.find((x) => x.before === null);
      if (created) return created.card_id;
    }
  }
  throw new Error("no card was created by these events");
}

export function revisionHash(state: MapState): string {
  return state.revisions[state.revisions.length - 1]!.hash;
}

/* ───────────── the scenario ───────────── */

export interface ScenarioStep {
  label: string;
  command: Command;
  before: MapState;
  state: MapState;
  events: ExmapEvent[];
}

export interface ScenarioIds {
  [key: string]: string;
}

export interface Scenario {
  session_id: string;
  ctx: ApplyContext;
  calls: TestCtx["calls"];
  steps: ScenarioStep[];
  events: ExmapEvent[];
  state: MapState;
  ids: ScenarioIds;
  step(label: string): ScenarioStep;
  stateAfter(label: string): MapState;
  stateBefore(label: string): MapState;
  eventsUpTo(label: string): ExmapEvent[];
}

const UTTERANCES: Array<[string, string, string, "remote" | "me"]> = [
  ["u1", "A patient should be able to cancel online, but not within two hours of their appointment.", "Priya", "remote"],
  ["u2", "If a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused.", "Sam", "me"],
  ["u3", "What about appointments already in progress?", "Sam", "me"],
  ["u4", "Actually, make that 24 hours for nurse appointments.", "Sam", "me"],
  ["u5", "And a nurse appointment at 10am cancelled at 8am is allowed.", "Priya", "remote"],
  ["u6", "Delete that example. It's not what I meant.", "Sam", "me"],
  ["u7", "Change that limit.", "Priya", "remote"],
  ["u8", "the rule", "Sam", "me"],
  ["u9", "By appointment I mean a booked slot, not a walk-in.", "Sam", "me"],
  ["u10", "Delete the nurse example.", "Priya", "remote"],
  ["u11", "No, that's not what I said. Delete the in-progress question.", "Sam", "me"],
  ["u12", "Yes.", "Priya", "remote"],
  ["u13", "Use this example instead: a GP appointment at 10am cancelled at 7am is allowed.", "Sam", "me"],
  ["u14", "No, that's not what I said.", "Priya", "remote"],
  ["u15", "A nurse appointment at 10am cancelled at 9am is refused.", "Priya", "remote"],
  ["u16", "Use this example instead of the old nurse one.", "Sam", "me"],
  ["u17", "Go back to the previous version.", "Priya", "remote"],
  ["u18", "Actually, redo that.", "Sam", "me"],
  ["u19", "Yes, that's exactly right.", "Priya", "remote"],
  ["u20", "Can a patient cancel twice in one day?", "Sam", "me"],
  ["u21", "Actually, make the GP window three hours.", "Priya", "remote"],
];

export const RULE_TEXT = "A patient should be able to cancel online, but not within two hours of their appointment.";
export const RULE_TEXT_V2 = "A patient should be able to cancel online, but not within two hours of their appointment. Make that 24 hours for nurse appointments.";
export const RULE_TEXT_V3 = `${RULE_TEXT_V2} Make the GP window three hours.`;
export const STORY_TEXT = "A patient cancels an appointment online";
export const ACCEPT_REASON = "To be settled with the practice manager";

/** The brief's conversation as bound commands (§5.10), every step applied through apply() with testCtx(). */
export function scenario(): Scenario {
  const { ctx, calls } = testCtx();
  const steps: ScenarioStep[] = [];
  const ids: ScenarioIds = {};
  let state = initialState(SESSION_ID);
  const uttById = new Map(UTTERANCES.map((u) => [u[0], u]));
  let tMs = 0;

  const add = (label: string, command: Command): ExmapEvent[] => {
    const before = state;
    const result = apply(state, command, ctx);
    if (!result.ok) throw new Error(`scenario step ${label} refused ${result.reason}: ${result.detail}`);
    state = result.state;
    steps.push({ label, command, before, state, events: result.events });
    return result.events;
  };
  const utt = (label: string): string => {
    const row = uttById.get(label);
    if (!row) throw new Error(`unknown utterance ${label}`);
    const id = `utt_${label}`;
    ids[label] = id;
    tMs += 4000;
    add(label, { kind: "utterance.record", utterance: utterance(id, row[1], { speaker: row[2], lane: row[3], t_start_ms: tMs, provider: row[3] === "me" && label === "u8" ? "manual" : "replay" }) });
    return id;
  };
  const pid = (key: string): string => {
    const id = ctx.nextId("prop");
    ids[key] = id;
    return id;
  };
  const ai = (label: string, key: string, operation: Operation, uttLabels: string[], opts: ProposalOpts = {}): ExmapEvent[] => {
    const id = pid(key);
    const events = add(label, propose(aiProposal(id, operation, { utts: uttLabels.map((u) => ids[u]!), ...opts })));
    add(`${label}.classified`, classify(ids[uttLabels[0]!]!, INTENT_OF_KIND[operation.kind], [id]));
    return events;
  };

  // story (a click), the rule (u1)
  utt("u1");
  ids.story = createdCardId(add("story", propose(humanProposal(pid("p_story"), { kind: "card.create", card: { kind: "story", text: STORY_TEXT } }))));
  ids.rule = createdCardId(ai("rule", "p_rule", { kind: "card.create", card: { kind: "rule", text: RULE_TEXT } }, ["u1"]));
  // example, question
  utt("u2");
  ids.ex_gp = createdCardId(ai("ex_gp", "p_ex_gp", { kind: "card.create", card: { kind: "example", text: uttById.get("u2")![1], rule_id: ids.rule } }, ["u2"]));
  utt("u3");
  ids.q_inprogress = createdCardId(ai("q_inprogress", "p_q_inprogress", { kind: "card.create", card: { kind: "question", text: uttById.get("u3")![1], about_card_id: ids.rule } }, ["u3"]));
  // the 24h-for-nurses amendment (flags the example)
  utt("u4");
  ai("amend", "p_amend", { kind: "card.update", card_id: ids.rule, patch: { text: RULE_TEXT_V2 } }, ["u4"]);
  utt("u5");
  ids.ex_nurse = createdCardId(ai("ex_nurse", "p_ex_nurse", { kind: "card.create", card: { kind: "example", text: uttById.get("u5")![1], rule_id: ids.rule } }, ["u5"]));
  // a two-candidate removal clarification answered by candidate
  utt("u6");
  {
    const id = pid("p_clar_remove");
    const events = add("clar_remove", propose(clarifying(id, "remove", {
      question: "Which example do you mean: (1) the nurse example (Priya), or (2) the GP example (Sam)?",
      template: { kind: "card.remove" },
      candidates: [{ card_id: ids.ex_nurse, label: "nurse example" }, { card_id: ids.ex_gp, label: "GP example" }],
      utts: [ids.u6!], confidence: 0.5,
    })));
    ids.clar_remove = events.find((e) => e.type === "clarification.asked")!.type === "clarification.asked" ? (events[1] as Extract<ExmapEvent, { type: "clarification.asked" }>).clarification_id : "";
    add("clar_remove.classified", classify(ids.u6!, "remove", [id], { confidence: 0.5 }));
    const answered = add("answer_candidate", { kind: "clarification.answer", clarification_id: ids.clar_remove, answer: { kind: "candidate", card_id: ids.ex_gp }, actor: "Sam" });
    ids.p_resolved_remove = (answered[0] as Extract<ExmapEvent, { type: "clarification.answered" }>).resolved_by_proposal_id!;
  }
  // a clarification answered by text with no resolver, later dismissed
  utt("u7");
  {
    const id = pid("p_clar_amend");
    const events = add("clar_amend", propose(clarifying(id, "amend", {
      question: "Which limit do you mean?",
      template: { kind: "card.update", patch: { text: "" }, amendment: { from: "two hours", to: "24 hours", scope: null, append: "Change that limit." } },
      candidates: [{ card_id: ids.rule, label: "the cancellation rule", score: 0.5 }],
      utts: [ids.u7!], confidence: 0.5,
    })));
    ids.clar_amend = (events[1] as Extract<ExmapEvent, { type: "clarification.asked" }>).clarification_id;
    add("clar_amend.classified", classify(ids.u7!, "amend", [id], { confidence: 0.5 }));
    utt("u8");
    add("answer_text", { kind: "clarification.answer", clarification_id: ids.clar_amend, answer: { kind: "text", text: "the rule", utterance_id: ids.u8! }, actor: "Sam" });
    add("dismiss", { kind: "clarification.answer", clarification_id: ids.clar_amend, answer: { kind: "dismiss", reason: "Already changed to 24 hours for nurses." }, actor: "Sam" });
  }
  // a confirm_intent answered yes
  utt("u9");
  {
    const id = pid("p_clar_refine");
    const events = add("clar_refine", propose(clarifying(id, "clarify", {
      question: "Record a definition of \"appointment\" on the story: a booked slot, not a walk-in?",
      pending: { kind: "definition.refine", card_id: ids.story, term: "appointment", definition: "a booked slot, not a walk-in" },
      utts: [ids.u9!], confidence: 0.5,
    })));
    ids.clar_refine = (events[1] as Extract<ExmapEvent, { type: "clarification.asked" }>).clarification_id;
    add("clar_refine.classified", classify(ids.u9!, "clarify", [id], { confidence: 0.5 }));
    const answered = add("answer_yes", { kind: "clarification.answer", clarification_id: ids.clar_refine, answer: { kind: "yes" }, actor: "Sam" });
    ids.p_resolved_refine = (answered[0] as Extract<ExmapEvent, { type: "clarification.answered" }>).resolved_by_proposal_id!;
  }
  // a voice removal, then a two-proposal batch (reject prefix + remove), then the removal reviewed by voice
  utt("u10");
  ai("remove_nurse", "p_remove_nurse", { kind: "card.remove", card_id: ids.ex_nurse }, ["u10"], { confidence: 0.5 });
  utt("u11");
  {
    const rejectId = pid("p_reject_prefix");
    const removeId = pid("p_remove_q");
    add("batch", propose(
      aiProposal(rejectId, { kind: "interpretation.reject", proposal_id: ids.p_remove_nurse! }, { utts: [ids.u11!] }),
      aiProposal(removeId, { kind: "card.remove", card_id: ids.q_inprogress! }, { utts: [ids.u11!] }),
    ));
    add("batch.classified", classify(ids.u11!, "reject", [rejectId, removeId]));
  }
  utt("u12");
  ai("voice_review", "p_voice_review", { kind: "confirm", card_ids: [], proposal_ids: [ids.p_remove_q!] }, ["u12"], { confidence: 0.5, stamp: stamps.rules("Priya") });
  // a replace by text, rejected by voice
  utt("u13");
  ids.ex_gp2 = createdCardId(ai("replace_text", "p_replace_text", { kind: "card.replace", card_id: ids.ex_nurse, replacement: { text: "A GP appointment at 10am cancelled at 7am is allowed." } }, ["u13"]));
  utt("u14");
  ai("reject_replace", "p_reject_replace", { kind: "interpretation.reject", proposal_id: ids.p_replace_text! }, ["u14"]);
  // a replace by replacement_card_id, undone, then the undo undone
  utt("u15");
  ids.ex_nurse2 = createdCardId(ai("ex_nurse2", "p_ex_nurse2", { kind: "card.create", card: { kind: "example", text: uttById.get("u15")![1], rule_id: ids.rule } }, ["u15"]));
  utt("u16");
  ai("replace_id", "p_replace_id", { kind: "card.replace", card_id: ids.ex_nurse, replacement_card_id: ids.ex_nurse2 }, ["u16"]);
  utt("u17");
  ai("undo1", "p_undo1", { kind: "undo", to_revision_seq: null }, ["u17"]);
  utt("u18");
  ai("undo2", "p_undo2", { kind: "undo", to_revision_seq: null }, ["u18"]);
  // confirmations by click and by voice
  add("confirm_click", propose(humanProposal(pid("p_confirm_click"), { kind: "confirm", card_ids: [ids.story, ids.rule], proposal_ids: [] })));
  utt("u19");
  ai("confirm_voice", "p_confirm_voice", { kind: "confirm", card_ids: [ids.ex_nurse2], proposal_ids: [] }, ["u19"], { stamp: stamps.rules("Priya") });
  // a question, accepted as outstanding
  utt("u20");
  ids.q_twice = createdCardId(ai("q_twice", "p_q_twice", { kind: "card.create", card: { kind: "question", text: uttById.get("u20")![1], about_card_id: ids.rule } }, ["u20"], { confidence: 0.5 }));
  add("accept_question", { kind: "question.accept", question_id: ids.q_twice, by: "Sam", reason: ACCEPT_REASON });
  // the AI acts reviewed by click, export options, sign-off
  add("accept_acts", propose(humanProposal(pid("p_accept_acts"), { kind: "confirm", card_ids: [], proposal_ids: [ids.p_reject_prefix!, ids.p_reject_replace!, ids.p_undo1!, ids.p_undo2!] })));
  add("export_options", { kind: "export.options_set", options: { capability_class: "backend.route.edit", kind: "code", size_estimate: "M", facts: [{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }], by: "Sam" } });
  {
    const events = add("signoff", signoff(state));
    ids.sig1 = (events[0] as Extract<ExmapEvent, { type: "signoff.recorded" }>).signoff.id;
  }
  // a later change (invalidation), review again, re-sign-off
  utt("u21");
  ai("amend2", "p_amend2", { kind: "card.update", card_id: ids.rule, patch: { text: RULE_TEXT_V3 } }, ["u21"]);
  add("review_again", propose(humanProposal(pid("p_review_again"), { kind: "confirm", card_ids: [ids.rule, ids.ex_nurse2], proposal_ids: [] })));
  {
    const events = add("signoff2", signoff(state));
    ids.sig2 = (events[0] as Extract<ExmapEvent, { type: "signoff.recorded" }>).signoff.id;
  }

  const events = steps.flatMap((s) => s.events);
  const step = (label: string): ScenarioStep => {
    const found = steps.find((s) => s.label === label);
    if (!found) throw new Error(`no scenario step ${label}`);
    return found;
  };
  return {
    session_id: SESSION_ID,
    ctx,
    calls,
    steps,
    events,
    state,
    ids,
    step,
    stateAfter: (label) => step(label).state,
    stateBefore: (label) => step(label).before,
    eventsUpTo: (label) => {
      const index = steps.findIndex((s) => s.label === label);
      return steps.slice(0, index + 1).flatMap((s) => s.events);
    },
  };
}

/* ───────────── misc helpers ───────────── */

export function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value as object)) deepFreeze((value as Record<string, unknown>)[key]);
  }
  return value;
}

/** A fresh map with a live story and one live rule (human-made), for tests that start small. */
export function smallMap(): { ctx: ApplyContext; calls: TestCtx["calls"]; state: MapState; story: string; rule: string } {
  const { ctx, calls } = testCtx();
  let state = initialState("sess_small");
  const s = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "story", text: STORY_TEXT } })), ctx);
  state = s.state;
  const r = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: RULE_TEXT } })), ctx);
  state = r.state;
  return { ctx, calls, state, story: createdCardId(s.events), rule: createdCardId(r.events) };
}
