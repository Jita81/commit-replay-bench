// exmap/src/classifier/clarification.ts — parseAnswer, applyChoice, resolveClarificationAnswer (design §6.6).
// The classifier answers the most recent open clarification the bridge could represent; a voice answer is parsed in the
// forms of §6.6 and resolved with the asking classifier's stamp. Nothing here guesses: an unparseable answer is null and
// the utterance is classified normally with the clarification left open.
import type { CardIndexEntry, ClassifierInput, ClassifierOperation, ClassifierProposal, Intent, PendingClarification } from "../core/types.js";
import { ANSWER_MAX_TOKENS, ANSWER_MIN_RATIO, RATIONALE_MAX } from "./constants.js";
import { ANSWER_FILLER } from "./cues.js";
import { cueText } from "./extract.js";
import { contentTokens, matchCount, normalizeText, sentenceWords, subSentence, type Sentence } from "./normalize.js";
import { cardTokens } from "./referents.js";
import { CHOICE, targetCardIds } from "./schema.js";

export type Answer =
  | { kind: "choose"; card_ids: string[]; how: string }
  | { kind: "yes" }
  | { kind: "no" }
  | { kind: "dismiss"; remainder: Sentence[] | null }
  | { kind: "reask" }
  | null;

export interface AnswerContext {
  /** The §6.3 group counts of a sentence (injected by rules-v1 to avoid a module cycle). */
  scoreOf: (s: Sentence) => Record<Intent, number>;
  cards: readonly CardIndexEntry[];
}

const BARE_CONFIRM = /^(yes|yeah|yep|yup|correct|right|exactly|agreed|ok|okay|sure|fine|perfect|great|good|absolutely|definitely|do it|go ahead|please do|that is right|that is correct|that is it|yes please|yes do)( please)?( do it)?$/;
const BARE_NEGATION = /^(no|nope|nah|no thanks|no thank you|do not|not that|not that one)( please)?$/;
const DISMISS_LEAD = /^(neither|none of them|none of those|not those|scrap that question|never mind)(?=,|$)/;

function plain(s: Sentence): string {
  return cueText(s.text).replace(/\?$/, "").replace(/\s+(please|thanks|thank you)$/, "").trim();
}

function wordCount(t: string): number {
  return t ? t.split(" ").length : 0;
}

function isBareConfirm(s: Sentence, rest: Sentence[]): boolean {
  const t = plain(s);
  return rest.length === 0 && wordCount(t) <= 3 && BARE_CONFIRM.test(t);
}

function isBareNegation(s: Sentence, rest: Sentence[]): boolean {
  const t = plain(s);
  return rest.length === 0 && wordCount(t) <= 3 && BARE_NEGATION.test(t);
}

/** The sub-sentence after the first `skip` words plus an optional comma and an optional "i meant" / "i mean" / "actually". */
function remainderAfter(s: Sentence, skipWords: number): Sentence | null {
  const ws = sentenceWords(s);
  let k = skipWords;
  const next2 = ws.slice(k, k + 2).map((w) => w.t).join(" ");
  if (next2 === "i meant" || next2 === "i mean") k += 2;
  else if (ws[k]?.t === "actually") k += 1;
  const tok = ws[k];
  if (!tok) return null;
  const idx = s.norm.toks.indexOf(tok);
  return subSentence(s, idx);
}

function ordinalAnswer(text: string, n: number): number[] | null {
  const t = text;
  const words: Record<string, number> = { first: 1, second: 2, third: 3, fourth: 4 };
  let m = /^(?:the )?(first|second|third|fourth)(?: one)?$/.exec(t);
  if (m) { const i = (words[m[1] ?? ""] ?? 0) - 1; return i < n ? [i] : null; }
  m = /^(?:number|option|no|the) ?([1-4])(?: one)?$/.exec(t) ?? /^([1-4])$/.exec(t);
  if (m) { const i = Number(m[1]) - 1; return i < n ? [i] : null; }
  if (/^(?:the )?(latest|last|most recent|newest|newer|new)(?: one)?$/.test(t)) return n > 0 ? [0] : null;
  if (/^(?:the )?(earlier|older|previous|old)(?: one)?$/.test(t)) return n === 2 ? [1] : null;
  if (/^both(?: of them| of those)?$/.test(t)) return n === 2 ? [0, 1] : null;
  if (/^all(?: of them| of those| of these| three| four)?$/.test(t)) return n >= 2 ? Array.from({ length: n }, (_, i) => i) : null;
  return null;
}

function labelAnswer(s: Sentence, pending: PendingClarification, s1Scores: Record<Intent, number>, cards: readonly CardIndexEntry[]): string[] | null {
  if (Object.values(s1Scores).some((v) => v > 0)) return null;
  let t = ` ${plain(s)} `;
  for (const f of [...ANSWER_FILLER].sort((a, b) => b.length - a.length)) {
    t = t.replace(new RegExp(` ${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?= )`, "g"), " ");
  }
  const tokens = [...new Set(contentTokens(normalizeText(t.trim()).text))];
  if (tokens.length < 1 || tokens.length > ANSWER_MAX_TOKENS) return null;
  const scored = pending.candidates.map((c) => {
    const card = cards.find((x) => x.id === c.card_id);
    const against = card ? cardTokens(card) : contentTokens(normalizeText(c.label).text);
    return { id: c.card_id, ratio: matchCount(tokens, against) / tokens.length };
  });
  const best = Math.max(...scored.map((x) => x.ratio));
  if (best < ANSWER_MIN_RATIO) return null;
  const winners = scored.filter((x) => x.ratio === best);
  if (winners.length !== 1) return null;
  return [winners[0]!.id];
}

/** Parses a voice answer to the pending clarification (design §6.6, forms 1–6). */
export function parseAnswer(s1: Sentence, pending: PendingClarification, rest: Sentence[], s1Scores: Record<Intent, number>, ctx: AnswerContext): Answer {
  const n = pending.candidates.length;
  const choose = pending.kind === "choose_target";
  // (1) confirm_intent: a bare yes / no
  if (!choose) {
    if (isBareConfirm(s1, rest)) return { kind: "yes" };
    if (isBareNegation(s1, rest)) return { kind: "no" };
  }
  // (2) dismissal
  const t = plain(s1);
  const lead = DISMISS_LEAD.exec(cueText(s1.text).replace(/\?$/, ""));
  if (lead) {
    const skip = wordCount(lead[1] ?? "");
    const rem = remainderAfter(s1, skip);
    const remainder = [...(rem ? [rem] : []), ...rest];
    return { kind: "dismiss", remainder: remainder.length > 0 ? remainder : null };
  }
  const noLead = /^(no|nope|neither)\b/.exec(t);
  if (noLead && wordCount(t) > 1) {
    const rem = remainderAfter(s1, 1);
    if (rem) {
      const sc = ctx.scoreOf(rem);
      const other = (Object.keys(sc) as Intent[]).some((k) => k !== "confirm" && k !== "reject" && sc[k] >= 1);
      if (other) return { kind: "dismiss", remainder: [rem, ...rest] };
      if (sc.reject >= 1) return { kind: "dismiss", remainder: null };
      if (choose) {
        const ord = ordinalAnswer(plain(rem), n);
        if (ord) return { kind: "choose", card_ids: ord.map((i) => pending.candidates[i]!.card_id), how: "by number" };
        const lab = labelAnswer(rem, pending, ctx.scoreOf(rem), ctx.cards);
        if (lab) return { kind: "choose", card_ids: lab, how: "by name" };
      }
      return { kind: "dismiss", remainder: null };
    }
  }
  if (choose && isBareNegation(s1, rest)) return { kind: "dismiss", remainder: null };
  if (choose) {
    // (3) ordinal
    const ord = ordinalAnswer(t, n);
    if (ord) return { kind: "choose", card_ids: ord.map((i) => pending.candidates[i]!.card_id), how: "by number" };
    // (4) label
    const lab = labelAnswer(s1, pending, s1Scores, ctx.cards);
    if (lab) return { kind: "choose", card_ids: lab, how: "by name" };
    // (5) a bare yes to a choose_target question cannot be mapped
    if (isBareConfirm(s1, rest)) return { kind: "reask" };
  }
  return null;
}

/** Replaces "$choice" with the chosen card(s); interpretation.reject resolves to the chosen card's proposal. */
export function applyChoice(ops: ClassifierOperation[], chosen: string[], input: ClassifierInput): { ops: ClassifierOperation[] } | { none: string } {
  const first = chosen[0];
  if (!first) return { none: "No card was chosen." };
  const out: ClassifierOperation[] = [];
  for (const op of ops) {
    if (op.kind === "card.remove" && op.card_id === CHOICE) {
      for (const id of chosen) out.push({ ...op, card_id: id });
      continue;
    }
    if (op.kind === "interpretation.reject" && op.proposal_id === CHOICE) {
      const card = input.cards.find((c) => c.id === first);
      if (!card || card.proposal_id === null) return { none: "That card was made by a person, not by an interpretation; use Remove." };
      out.push({ ...op, proposal_id: card.proposal_id });
      continue;
    }
    switch (op.kind) {
      case "card.update": out.push(op.card_id === CHOICE ? { ...op, card_id: first } : op); break;
      case "card.replace": out.push(op.card_id === CHOICE ? { ...op, card_id: first } : op); break;
      case "definition.refine": out.push(op.card_id === CHOICE ? { ...op, card_id: first } : op); break;
      case "confirm": out.push(op.card_ids.includes(CHOICE) ? { ...op, card_ids: op.card_ids.map((id) => (id === CHOICE ? first : id)) } : op); break;
      case "card.create": {
        const card = { ...op.card };
        if (card.rule_id === CHOICE) card.rule_id = first;
        if (card.about_card_id === CHOICE) card.about_card_id = first;
        out.push({ ...op, card });
        break;
      }
      default: out.push(op);
    }
  }
  return { ops: out };
}

function trimRationale(r: string): string {
  const t = r.trim();
  return t.length > RATIONALE_MAX ? `${t.slice(0, RATIONALE_MAX - 1).trimEnd()}…` : t;
}

/**
 * The proposal that resolves (or dismisses) the pending clarification for a parsed answer of kind choose / yes / no /
 * dismiss(null) / reask. A dismissal with a remainder is classified by rules-v1 itself (the remainder is a normal utterance).
 */
export function resolveClarificationAnswer(pending: PendingClarification, answer: Exclude<Answer, null>, input: ClassifierInput): ClassifierProposal {
  const base = {
    classifier: pending.classifier,
    source_utterance_ids: [input.utterance.id, pending.asked_by_utterance_id],
    needs_clarification: false,
    clarification: null,
  };
  const finish = (p: Omit<ClassifierProposal, "target_card_ids">): ClassifierProposal => ({ ...p, target_card_ids: targetCardIds(p), rationale: trimRationale(p.rationale) });
  const dismissed = (rationale: string): ClassifierProposal => finish({
    ...base,
    intent: "none",
    heard_intent: pending.intent,
    operations: [],
    confidence: 1,
    resolves: { proposal_id: pending.proposal_id, chosen_card_ids: [], dismissed: true },
    rationale,
  });
  switch (answer.kind) {
    case "choose": {
      const applied = applyChoice(pending.pending_operations, answer.card_ids, input);
      if ("none" in applied) {
        return finish({
          ...base,
          intent: "none",
          heard_intent: pending.intent,
          operations: [],
          confidence: 1,
          resolves: { proposal_id: pending.proposal_id, chosen_card_ids: answer.card_ids, dismissed: false },
          rationale: applied.none,
        });
      }
      const labels = answer.card_ids.map((id) => pending.candidates.find((c) => c.card_id === id)?.label ?? id);
      const several = answer.card_ids.length > 1 && !applied.ops.every((op) => op.kind === "card.remove");
      return finish({
        ...base,
        intent: pending.intent,
        heard_intent: null,
        operations: applied.ops,
        confidence: 1,
        resolves: { proposal_id: pending.proposal_id, chosen_card_ids: answer.card_ids, dismissed: false },
        rationale: several ? `You chose ${labels.join(" and ")}; only the first can be used here.` : `You chose ${labels.join(" and ")}.`,
      });
    }
    case "yes":
      return finish({
        ...base,
        intent: pending.intent,
        heard_intent: null,
        operations: pending.pending_operations,
        confidence: 1,
        resolves: { proposal_id: pending.proposal_id, chosen_card_ids: [], dismissed: false },
        rationale: "You said yes.",
      });
    case "no":
    case "dismiss":
      return dismissed("Dismissed the question.");
    case "reask":
      return finish({
        ...base,
        intent: "none",
        heard_intent: pending.intent,
        operations: [],
        confidence: 1,
        resolves: null,
        source_utterance_ids: [input.utterance.id],
        rationale: "Please say which one: first or second, or name it.",
      });
  }
}
