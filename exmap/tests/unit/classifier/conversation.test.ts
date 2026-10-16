// exmap/tests/unit/classifier/conversation.test.ts — the §14 fixture end to end under rules.v1: createRulesClassifier(),
// buildClassifierInput + toCoreCommands (src/server/classifier-bridge.ts) and core apply() with testCtx(); a MapState is
// threaded through, the `ui` steps run as core commands, every `expect` block is checked with its $symbols bound to the ids
// core assigned, and the sign-off / invalidation / re-sign-off gates are asserted (TEST-PLAN §2 conversation.test.ts).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { createRulesClassifier } from "../../../src/classifier/rules-v1.js";
import { ProposalSchema, assertProposalInvariants } from "../../../src/classifier/schema.js";
import { apply } from "../../../src/core/apply.js";
import { SIGNOFF_CONFIRMATION_TEXT, isHumanVerified } from "../../../src/core/dod.js";
import { initialState } from "../../../src/core/reduce.js";
import * as select from "../../../src/core/select.js";
import type {
  Card, CardKind, Command, ExmapEvent, Intent, MapState, Operation, Proposal, Utterance,
} from "../../../src/core/types.js";
import { buildClassifierInput, intentOf, toCoreCommands } from "../../../src/server/classifier-bridge.js";
import { testCtx } from "../core/fixtures.js";

interface FixtureOp { kind: string; bind?: string; [k: string]: unknown }
interface FixtureExpect {
  intent: Intent | "none";
  heard_intent?: Intent | null;
  confidence: number;
  ops: FixtureOp[];
  clarification: { kind: "choose_target" | "confirm_intent"; candidates: string[]; pending: FixtureOp[] } | null;
  resolves?: { proposal_id: string; chosen: string[]; dismissed: boolean };
}
interface FixtureUtterance { label: string; atMs: number; lane: "remote" | "me"; speaker: string; text: string; expect: FixtureExpect }
interface UiStep {
  after: string; action: "accept_questions" | "accept_acts" | "review" | "signoff" | "export_options" | "export";
  questions?: string[]; proposals?: string[]; checks?: string[]; by?: string; reason?: string; actor?: string; reviewer?: string;
  capability_class?: string; facts?: Array<{ slot: string; text: string }>;
}
interface Fixture { version: number; title: string; story: string; speakers: Record<string, string>; utterances: FixtureUtterance[]; ui: UiStep[] }

const fixture = JSON.parse(readFileSync(new URL("../../../src/web/public/replay/conversation.v1.json", import.meta.url), "utf8")) as Fixture;
const SESSION = "sess_fixture";

describe("the fixture conversation under rules.v1", () => {
  it("replays every utterance and ui step through classifier, bridge and core with the expected proposals", async () => {
    const { ctx } = testCtx();
    const classifier = createRulesClassifier();
    let state: MapState = initialState(SESSION);
    const seqOf = new Map<string, number>();
    const bound = new Map<string, string>();
    const bind = (sym: string, id: string): void => {
      const prev = bound.get(sym);
      if (prev !== undefined && prev !== id) throw new Error(`symbol ${sym} bound twice: ${prev} / ${id}`);
      bound.set(sym, id);
    };
    const resolveSym = (v: unknown): unknown => {
      if (typeof v === "string" && v.startsWith("$") && v !== "$choice") {
        const id = bound.get(v);
        if (id === undefined) throw new Error(`unbound symbol ${v}`);
        return id;
      }
      if (Array.isArray(v)) return v.map(resolveSym);
      if (v && typeof v === "object") return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, resolveSym(x)]));
      return v;
    };
    const run = (command: Command, where: string): ExmapEvent[] => {
      const r = apply(state, command, ctx);
      if (!r.ok) throw new Error(`${where}: ${r.reason}: ${r.detail}`);
      state = r.state;
      for (const e of r.events) seqOf.set(e.id, e.seq);
      return r.events;
    };
    const human = (operation: Operation, actor: string, rationale: string): Proposal => ({
      id: ctx.nextId("prop"), intent: intentOf(operation.kind), operation, template: null, pending_operation: null, candidates: [], confidence: 1,
      needs_clarification: false, question: null, source_utterance_ids: [],
      classifier: { provider: "human", model: null, prompt_version: null, fallback_from: null, error: null, actor },
      resolves_clarification_id: null, rationale,
    });
    const live = (kind?: CardKind): Card[] => select.liveCards(state).filter((c) => !kind || c.kind === kind);

    // the story, as session creation makes it
    const storyEvents = run({ kind: "proposal.propose", proposals: [human({ kind: "card.create", card: { kind: "story", text: fixture.story } }, "Sam", "story at session creation")] }, "story");
    const storyId = storyEvents.find((e) => e.type === "proposal.made")?.type === "proposal.made" ? (storyEvents.find((e) => e.type === "proposal.made") as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]?.card_id : undefined;
    if (!storyId) throw new Error("no story");
    bind("$story", storyId);

    const uiAfter = new Map<string, UiStep[]>();
    for (const step of fixture.ui) uiAfter.set(step.after, [...(uiAfter.get(step.after) ?? []), step]);

    const runUi = (step: UiStep, label: string): ExmapEvent[] => {
      const actor = step.actor ?? step.by ?? step.reviewer ?? "Sam";
      switch (step.action) {
        case "accept_questions": {
          const out: ExmapEvent[] = [];
          for (const q of step.questions ?? []) out.push(...run({ kind: "question.accept", question_id: resolveSym(q) as string, by: step.by ?? actor, reason: step.reason ?? "accepted" }, `${label} accept ${q}`));
          return out;
        }
        case "accept_acts": {
          const out: ExmapEvent[] = [];
          for (const p of step.proposals ?? []) {
            out.push(...run({ kind: "proposal.propose", proposals: [human({ kind: "confirm", card_ids: [], proposal_ids: [resolveSym(p) as string] }, actor, `accepted by ${actor}`)] }, `${label} accept act ${p}`));
          }
          return out;
        }
        case "review": {
          const out: ExmapEvent[] = [];
          for (const check of step.checks ?? []) {
            let ids: string[] = [];
            if (check === "story_rules_confirmed") ids = live().filter((c) => (c.kind === "story" || c.kind === "rule") && c.status !== "confirmed").map((c) => c.id);
            else if (check === "examples_reviewed") ids = live("example").filter((c) => c.status !== "confirmed" || (c.kind === "example" && c.needs_review !== null)).map((c) => c.id);
            else if (check === "questions_resolved") ids = live("question").filter((c) => c.kind === "question" && c.answer !== null && c.status !== "confirmed").map((c) => c.id);
            if (ids.length === 0) continue;
            out.push(...run({ kind: "proposal.propose", proposals: [human({ kind: "confirm", card_ids: ids, proposal_ids: [] }, actor, `review check ${check} by ${actor}`)] }, `${label} review ${check}`));
          }
          return out;
        }
        case "signoff":
          return run({ kind: "signoff.record", reviewer: { name: step.reviewer ?? actor }, confirmation_text: SIGNOFF_CONFIRMATION_TEXT, cited_revision_hash: select.currentRevision(state).hash }, `${label} signoff`);
        case "export_options":
          return run({ kind: "export.options_set", options: { capability_class: step.capability_class ?? "unclassified", kind: "code", size_estimate: "unsized", facts: step.facts ?? [], by: actor } }, `${label} export options`);
        case "export":
          return []; // the export mappers are the export module's; nothing to apply here
      }
    };

    let signoffsSeen = 0;
    for (const u of fixture.utterances) {
      const utterance: Utterance = {
        id: `utt_${u.label}`, text: u.text, lane: u.lane, speaker: u.speaker, provider: "replay", model: null,
        t_start_ms: u.atMs, t_end_ms: u.atMs + 2500, is_local: true, confidence: null,
      };
      run({ kind: "utterance.record", utterance }, `${u.label} record`);
      const input = buildClassifierInput({ state, seqOfEvent: (id) => seqOf.get(id) ?? 0 }, utterance);
      const p = await classifier.classify(input);
      expect(() => ProposalSchema.parse(p), `${u.label} schema`).not.toThrow();
      expect(() => assertProposalInvariants(p, input), `${u.label} invariants`).not.toThrow();

      // the expected proposal
      const ex = u.expect;
      expect(p.intent, `${u.label} intent`).toBe(ex.intent);
      if (ex.intent === "none") expect(p.heard_intent, `${u.label} heard_intent`).toBe(ex.heard_intent ?? null);
      expect(Math.abs(p.confidence - ex.confidence), `${u.label} confidence ${p.confidence} vs ${ex.confidence}`).toBeLessThanOrEqual(0.005);
      expect(p.operations.length, `${u.label} op count`).toBe(ex.ops.length);
      ex.ops.forEach((op, i) => {
        const { bind: _b, ...rest } = op;
        expect(p.operations[i], `${u.label} op ${i}`).toMatchObject(resolveSym(rest) as object);
      });
      if (ex.clarification) {
        expect(p.needs_clarification, `${u.label} needs_clarification`).toBe(true);
        expect(p.clarification?.kind, `${u.label} clarification kind`).toBe(ex.clarification.kind);
        expect(p.clarification?.candidates.map((c) => c.card_id), `${u.label} candidates`).toEqual(ex.clarification.candidates.map(resolveSym));
        expect(p.clarification?.pending_operations, `${u.label} pending`).toMatchObject(resolveSym(ex.clarification.pending) as object[]);
      } else {
        expect(p.needs_clarification, `${u.label} needs_clarification`).toBe(false);
      }
      if (ex.resolves) {
        expect(p.resolves, `${u.label} resolves`).toEqual({ proposal_id: resolveSym(ex.resolves.proposal_id), chosen_card_ids: ex.resolves.chosen.map(resolveSym), dismissed: ex.resolves.dismissed });
      } else {
        expect(p.resolves, `${u.label} resolves`).toBeNull();
      }

      // the bridge, then core — every command must apply (refused[] stays empty)
      const commands = toCoreCommands(p, state, utterance, { nextId: ctx.nextId, actorForVoice: (x) => x.speaker ?? "(no speaker label)" });
      const proposalIds: string[] = [];
      const batch: ExmapEvent[] = [];
      for (const c of commands) {
        if (c.kind === "proposal.propose") proposalIds.push(...c.proposals.map((x) => x.id));
        batch.push(...run(c, `${u.label} ${c.kind}`));
      }
      if (ex.intent !== "none") expect(proposalIds.length, `${u.label} proposals`).toBeGreaterThan(0);
      const mainProposal = proposalIds[proposalIds.length - 1];
      if (mainProposal) bind(`$p${u.label.slice(1)}`, mainProposal);
      // bind the created cards
      const created = batch.filter((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made").flatMap((e) => e.effects.filter((f) => f.before === null).map((f) => f.card_id));
      const binds = ex.ops.filter((op) => op.bind).map((op) => op.bind as string);
      expect(created.length, `${u.label} created cards`).toBe(binds.length);
      binds.forEach((sym, i) => bind(sym, created[i]!));

      run({
        kind: "classification.record", utterance_id: utterance.id, intent: p.intent, heard_intent: p.heard_intent,
        classifier: { ...p.classifier, actor: null }, confidence: p.confidence, rationale: p.rationale, proposal_ids: proposalIds, refused: [], error: null,
      }, `${u.label} classification`);

      // per-row gates
      if (u.label === "u15") {
        const p14 = state.proposals[bound.get("$p14")!];
        expect(p14?.status, "u15: $p14 confirmed by voice").toBe("confirmed");
        const p15 = state.proposals[bound.get("$p15")!];
        expect(p15?.proposal.classifier.provider, "u15: confirmed by rules.v1").toBe("rules.v1");
      }
      if (u.label === "u31") {
        expect(batch.some((e) => e.type === "signoff.invalidated"), "u31 invalidates the sign-off").toBe(true);
        expect(isHumanVerified(state), "u31: not verified").toBe(false);
      }

      for (const step of uiAfter.get(u.label) ?? []) {
        runUi(step, u.label);
        if (step.action === "signoff") {
          signoffsSeen++;
          expect(isHumanVerified(state), `${u.label}: verified after sign-off ${signoffsSeen}`).toBe(true);
        }
      }
    }
    expect(signoffsSeen).toBe(2);

    // the final live index is exactly the §14 set
    const expectedLive = ["$story", "$rule_cancel", "$rule_override2", "$ex_nurse", "$ex_nurse2", "$ex_gp2", "$ex_gp3", "$q_inprogress", "$q_behalf", "$q_dentist", "$q_twice"].map((s) => bound.get(s)!);
    expect(new Set(select.liveCards(state).map((c) => c.id))).toEqual(new Set(expectedLive));
    expect(state.cards[bound.get("$ex_gp")!]?.status).toBe("rejected");
    expect(state.cards[bound.get("$ex_error")!]?.status).toBe("rejected");
    expect(state.cards[bound.get("$rule_override")!]?.status).toBe("rejected");
    expect(state.cards[bound.get("$ex_gp3")!]?.restored_by?.proposal_id).toBe(bound.get("$p27"));

    // counts after u31 (plus the ui steps): every number comes from the ledger
    const counts = select.counts(state);
    expect(counts.utterances).toBe(31);
    expect(counts.classified).toBe(31);
    expect(counts.fallbacks).toBe(0);
    expect(counts.classifier_errors).toBe(0);
    expect(counts.by_kind.story).toBe(1);
    expect(counts.by_kind.rule).toBe(2);
    expect(counts.by_kind.example).toBe(4);
    expect(counts.by_kind.question).toBe(4);
    expect(counts.cards_live).toBe(11);
    expect(counts.accepted_questions).toBe(4);
    expect(counts.open_clarifications).toBe(0);
    expect(counts.events).toBe(state.head.seq);
  });
});
