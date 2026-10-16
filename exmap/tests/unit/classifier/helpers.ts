// exmap/tests/unit/classifier/helpers.ts — builders for classifier inputs (TEST-PLAN §2): card(), utt(), input() with
// defaults (recent [], cards [story], refs null), ref(), expectOp(), mintIds() (counter ids + a clock stepping 1 s).
import { expect } from "vitest";
import type {
  ApplyContext, CardIndexEntry, CardKind, CardStatus, ClassifierInput, ClassifierOperation, ClassifierProposal, ClassifierUtterance,
  IdPrefix, Intent, Lane, LastProposalRef, OperationKind, PendingClarification,
} from "../../../src/core/types.js";

export const STORY_ID = "card_story";

export function card(
  id: string,
  kind: CardKind,
  text: string,
  opts: {
    seq?: number; last_utterance_id?: string | null; last_speaker?: string | null;
    links?: { rule_id?: string | null; about_card_id?: string | null }; answer?: string | null; proposal_id?: string | null; status?: CardStatus;
  } = {},
): CardIndexEntry {
  return {
    id,
    kind,
    title: text.slice(0, 60),
    text,
    status: opts.status ?? "applied",
    links: { rule_id: opts.links?.rule_id ?? null, about_card_id: opts.links?.about_card_id ?? null },
    answer: opts.answer ?? null,
    seq: opts.seq ?? 1,
    last_utterance_id: opts.last_utterance_id === undefined ? null : opts.last_utterance_id,
    last_speaker: opts.last_speaker === undefined ? null : opts.last_speaker,
    proposal_id: opts.proposal_id === undefined ? null : opts.proposal_id,
  };
}

export function story(text = "A patient cancels an appointment online"): CardIndexEntry {
  return card(STORY_ID, "story", text, { seq: 1, proposal_id: null });
}

export function utt(id: string, text: string, opts: { speaker?: string | null; lane?: Lane } = {}): ClassifierUtterance {
  return { id, text, lane: opts.lane ?? "me", speaker: opts.speaker === undefined ? "Sam" : opts.speaker };
}

export function ref(id: string, over: Partial<LastProposalRef> & { intent: Intent; op: OperationKind; card_ids: string[]; utterance_id: string }): LastProposalRef {
  return {
    id,
    intent: over.intent,
    op: over.op,
    kind: over.kind === undefined ? null : over.kind,
    status: over.status ?? "applied",
    card_ids: over.card_ids,
    utterance_id: over.utterance_id,
    rejectable: over.rejectable ?? true,
  };
}

export function input(over: Partial<Omit<ClassifierInput, "utterance">> & { utterance?: ClassifierUtterance | string } = {}): ClassifierInput {
  const u = over.utterance === undefined ? utt("utt_new", "") : typeof over.utterance === "string" ? utt("utt_new", over.utterance) : over.utterance;
  return {
    utterance: u,
    recent: over.recent ?? [],
    cards: over.cards ?? [story()],
    last_proposal: over.last_proposal ?? null,
    last_rejectable: over.last_rejectable ?? null,
    pending_clarification: over.pending_clarification ?? null,
  };
}

export function pending(over: Partial<PendingClarification> & { pending_operations: ClassifierOperation[]; intent: Intent }): PendingClarification {
  return {
    proposal_id: over.proposal_id ?? "prop_ask",
    kind: over.kind ?? (over.candidates && over.candidates.length >= 2 ? "choose_target" : "confirm_intent"),
    question: over.question ?? "Which one?",
    candidates: over.candidates ?? [],
    pending_operations: over.pending_operations,
    intent: over.intent,
    asked_by_utterance_id: over.asked_by_utterance_id ?? "utt_ask",
    source_utterance_ids: over.source_utterance_ids ?? ["utt_ask"],
    classifier: over.classifier ?? { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null },
  };
}

function deepPartial(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(deepPartial);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) out[k] = deepPartial(x);
    return expect.objectContaining(out);
  }
  return v;
}

/** Asserts the proposal carries an operation matching `op` (deep partial match). */
export function expectOp(p: ClassifierProposal, op: Record<string, unknown>, at?: number): void {
  if (at !== undefined) {
    expect(p.operations[at]).toMatchObject(op);
    return;
  }
  expect(p.operations).toEqual(expect.arrayContaining([deepPartial(op)]));
}

/** The candidate label the classifier prints for a card: "<title> (<kind>, <speaker>)". */
export function label(c: CardIndexEntry, speaker = c.last_speaker ?? "by hand"): string {
  return `${title(c)} (${c.kind}, ${speaker})`;
}

export function title(c: CardIndexEntry): string {
  if (c.text.length <= 60) return c.text;
  const head = c.text.slice(0, 60);
  return `${head.slice(0, head.lastIndexOf(" ")).trimEnd()}…`;
}

/** Counter ids (evt_1, card_1, …) and a clock stepping 1 s from a fixed instant; the shape core's testCtx() has. */
export function mintIds(): ApplyContext & { calls: number } {
  const counters: Partial<Record<IdPrefix, number>> = {};
  let t = Date.UTC(2026, 9, 16, 12, 0, 0);
  const ctx = {
    calls: 0,
    now: (): string => {
      const at = new Date(t).toISOString();
      t += 1000;
      return at;
    },
    nextId: (prefix: IdPrefix): string => {
      ctx.calls++;
      const n = (counters[prefix] ?? 0) + 1;
      counters[prefix] = n;
      return `${prefix}_${n}`;
    },
    sha256: (utf8: string): string => sha256Hex(utf8),
  };
  return ctx;
}

import { createHash } from "node:crypto";
function sha256Hex(utf8: string): string {
  return createHash("sha256").update(utf8, "utf8").digest("hex");
}
