// exmap/src/classifier/rules-v1.ts — the deterministic, offline classifier (design §6.3): cue tables + heuristics, a
// confidence derived from the cue groups matched, referent resolution that asks rather than guesses, and the clarification
// protocol of §6.6. classifyRules() is pure and synchronous: no I/O, randomness or clock; same input -> identical proposal.
import type {
  CardIndexEntry, CardKind, Classifier, ClassifierClarification, ClassifierInput, ClassifierIntent, ClassifierOperation,
  ClassifierProposal, ClassifierResolves, HeardIntent, Intent,
} from "../core/types.js";
import { parseAnswer, resolveClarificationAnswer } from "./clarification.js";
import { DRAFT_MIN_CONTENT_WORDS, MIN_CONFIDENCE, RATIONALE_MAX } from "./constants.js";
import { DEFINITION_PATTERNS, INTENT_CUES, INTENT_PRECEDENCE } from "./cues.js";
import {
  a3Match, a5Match, appendText, cueText, detectKind, extractAmendment, extractAnswer, extractDefinition, extractDraft,
  extractReason, kindCue, matchAny, matchEntry, replacementDraft, verbPhrase,
} from "./extract.js";
import { isContinuation, normalizeText, splitSentences, stripDiscourse, type Sentence } from "./normalize.js";
import {
  askTarget, bySeqDesc, candidateLabel, inWindow, isRecent, maskReferents, parseReferent, parseReferents, resolveReferent,
  titleOf, type AskResult, type Resolution,
} from "./referents.js";
import { CHOICE, ClassifierInputSchema, assertProposalInvariants, targetCardIds } from "./schema.js";
import { ClassifierError } from "./types.js";

const INTENTS: Intent[] = ["add", "amend", "remove", "replace", "clarify", "reject", "confirm", "undo"];

export function createRulesClassifier(): Classifier {
  return {
    provider: "rules.v1",
    classify: async (input) => classifyRules(input),
  };
}

/* ───────────── scoring ───────────── */

export interface GroupScores {
  scores: Record<Intent, number>;
  cues: Record<Intent, string[]>;
  /** The sentence index and end offset of the first matched cue of each intent (for extractReason). */
  firstHit: Partial<Record<Intent, { sentence: number; end: number }>>;
  a5: boolean;
}

function emptyScores(): Record<Intent, number> {
  return { add: 0, amend: 0, remove: 0, replace: 0, clarify: 0, reject: 0, confirm: 0, undo: 0 };
}

/** Raw cue-group counts over the sentences (reject: first sentence only). */
export function groupScores(sentences: Sentence[], input: ClassifierInput): GroupScores {
  const scores = emptyScores();
  const cues: Record<Intent, string[]> = { add: [], amend: [], remove: [], replace: [], clarify: [], reject: [], confirm: [], undo: [] };
  const firstHit: GroupScores["firstHit"] = {};
  const matched = new Set<string>();
  let a5 = false;
  const hit = (intent: Intent, group: string, cue: string, sentence: number, end: number): void => {
    const key = `${intent}:${group}`;
    if (matched.has(key)) return;
    matched.add(key);
    scores[intent]++;
    cues[intent].push(cue);
    if (!firstHit[intent]) firstHit[intent] = { sentence, end };
  };
  const continuation = sentences[0] ? isContinuation(sentences[0]) : false;
  sentences.forEach((s, si) => {
    const text = cueText(s.text);
    const masked = cueText(maskReferents(s.text));
    for (const intent of INTENTS) {
      if (intent === "reject" && si > 0) continue;
      for (const g of INTENT_CUES[intent]) {
        if (g.special === "kind") {
          const kc = kindCue(masked);
          if (kc) hit(intent, g.id, kc.cue, si, 0);
          continue;
        }
        if (g.special === "continuation") {
          const lp = input.last_proposal;
          if (si === 0 && continuation && inWindow(lp, input) && lp.intent === "add" && lp.kind !== null) hit(intent, g.id, s.lead ?? "and", si, 0);
          continue;
        }
        if (g.id === "A3") {
          const m = a3Match(s.text);
          if (m) hit(intent, g.id, m.cue, si, m.end);
          continue;
        }
        if (g.id === "A5") {
          const m = a5Match(s.text);
          if (m) { a5 = true; hit(intent, g.id, m.cue, si, m.end); }
          continue;
        }
        if (g.id === "C2") {
          if (DEFINITION_PATTERNS.some((re) => re.test(s.text))) hit(intent, g.id, "by X I mean Y", si, 0);
          continue;
        }
        if (g.id === "P1") {
          const p2 = matchAny(text, INTENT_CUES.replace.find((x) => x.id === "P2")?.entries ?? []) !== null;
          for (const e of g.entries) {
            const m = matchEntry(text, e);
            if (!m) continue;
            if (e === "instead" && m.end === text.length && !p2) continue; // a bare sentence-final "instead" needs P2
            hit(intent, g.id, m.cue, si, m.end);
            break;
          }
          continue;
        }
        // a correction cue inside a rejection phrase ("not what i meant") is the rejection, not an amendment
        const haystack = g.id === "M3" ? text.replace(/\b(not what (i|we) (meant|said)|(i|we) did not mean)\b/g, " ") : text;
        const m = matchAny(haystack, g.entries);
        if (m) hit(intent, g.id, m.cue, si, m.end);
      }
    }
  });
  return { scores, cues, firstHit, a5 };
}

export interface Scoring extends GroupScores {
  prefix: "reject" | "confirm" | null;
  best: Intent | "none";
  runner: Intent | null;
  confidence: number;
  damped: boolean;
}

function round2(x: number): number {
  return Math.round(x * 100) / 100;
}

/** Group counts plus the interactions (a)–(f) of design §6.3 and the confidence. */
export function scoreSentences(sentences: Sentence[], input: ClassifierInput): Scoring {
  const g = groupScores(sentences, input);
  const scores = { ...g.scores };
  const s1 = sentences[0];
  const r1 = s1 ? matchAny(cueText(s1.text), INTENT_CUES.reject.find((x) => x.id === "R1")?.entries ?? []) !== null : false;
  const f1 = s1 ? matchAny(cueText(s1.text), INTENT_CUES.confirm.find((x) => x.id === "F1")?.entries ?? []) !== null : false;
  const othersScored = (except: Intent): boolean => INTENTS.some((i) => i !== except && scores[i] > 0);
  let prefix: Scoring["prefix"] = null;
  // (a) prefix reject
  if (r1 && othersScored("reject")) { scores.reject = 0; prefix = "reject"; }
  // (b) prefix confirm
  if (f1 && prefix === null && othersScored("confirm")) { scores.confirm = 0; prefix = "confirm"; }
  // (c) replace absorbs content
  if (scores.replace > 0) {
    const kept = countAddGroups(sentences, input, new Set(["A1", "A5", "A6"]));
    scores.add = kept;
  }
  // (d) interrogative
  let damped = false;
  if (g.a5 && othersScored("add")) {
    const kept = countAddGroups(sentences, input, scores.replace > 0 ? new Set(["A1", "A6"]) : new Set(["A1", "A2", "A3", "A4", "A6"]));
    scores.add = kept;
    damped = true;
  }
  // (e) all zero
  const ranked = [...INTENTS].sort((a, b) => scores[b] - scores[a] || INTENT_PRECEDENCE.indexOf(a) - INTENT_PRECEDENCE.indexOf(b));
  const best = ranked[0]!;
  const runner = ranked[1]!;
  if (scores[best] === 0) return { ...g, scores, prefix, best: "none", runner: null, confidence: 0, damped: false };
  const strength = Math.min(scores[best] / 2, 1);
  const margin = (scores[best] - scores[runner] + 1) / (scores[best] + 1);
  let confidence = round2(strength * margin);
  // (f)
  if (damped && best !== "add") confidence = round2(confidence * 0.5);
  else damped = false;
  return { ...g, scores, prefix, best, runner, confidence, damped };
}

/** The number of add groups among `keep` that matched (used when (c) or (d) discount the others). */
function countAddGroups(sentences: Sentence[], input: ClassifierInput, keep: Set<string>): number {
  let n = 0;
  const continuation = sentences[0] ? isContinuation(sentences[0]) : false;
  const groups = INTENT_CUES.add;
  const found = new Set<string>();
  sentences.forEach((s, si) => {
    const text = cueText(s.text);
    const masked = cueText(maskReferents(s.text));
    for (const g of groups) {
      if (!keep.has(g.id) || found.has(g.id)) continue;
      let ok = false;
      if (g.special === "kind") ok = kindCue(masked) !== null;
      else if (g.special === "continuation") { const lp = input.last_proposal; ok = si === 0 && continuation && inWindow(lp, input) && lp.intent === "add" && lp.kind !== null; }
      else if (g.id === "A3") ok = a3Match(s.text) !== null;
      else if (g.id === "A5") ok = a5Match(s.text) !== null;
      else ok = matchAny(text, g.entries) !== null;
      if (ok) found.add(g.id);
    }
  });
  n = found.size;
  return n;
}

/* ───────────── drafts ───────────── */

interface Draft {
  intent: ClassifierIntent;
  operations: ClassifierOperation[];
  confidence: number;
  clarification: ClassifierClarification | null;
  heard_intent: HeardIntent;
  rationale: string;
}

function none(heard: HeardIntent, confidence: number, rationale: string): Draft {
  return { intent: "none", operations: [], confidence, clarification: null, heard_intent: heard, rationale };
}

function chatter(): Draft {
  return none(null, 0, "No map-changing cue found.");
}

function quote(cues: string[]): string {
  return cues.map((c) => `'${c}'`).join(", ");
}

function fromAsk(ask: AskResult, intent: Intent, confidence: number, heard: Intent, rationale: string, noneRationale: string): Draft {
  if (ask.kind === "none") return none(heard, confidence, noneRationale);
  return { intent, operations: [], confidence, clarification: ask.clarification, heard_intent: null, rationale };
}

function kindWord(kind: CardKind | null | undefined): string {
  return kind ?? "card";
}

/* ───────────── per-intent handling ───────────── */

function handleAdd(sentences: Sentence[], sc: Scoring, input: ClassifierInput): Draft {
  const continuation = sentences[0] ? isContinuation(sentences[0]) : false;
  const kd = detectKind(sentences, { input, continuation });
  const draft = extractDraft(sentences, kd.kind, input);
  if (!draft.text) return chatter();
  let rationale = kd.how === "continuation" ? `Heard a ${kd.kind} (continues the last one).` : `Heard a ${kd.kind} (${quote(sc.cues.add)}).`;
  if (kd.how === "default") rationale += " Kind defaulted to rule.";
  return { intent: "add", operations: [{ kind: "card.create", card: draft }], confidence: sc.confidence, clarification: null, heard_intent: null, rationale };
}

function handleAmend(sentences: Sentence[], sc: Scoring, input: ClassifierInput): Draft {
  const s1 = sentences[0]!;
  const emptyPatch = { text: null, text_append: null, answer: null, rule_id: null, about_card_id: null };
  // M4: an answer to a question
  const m4 = INTENT_CUES.amend.find((g) => g.id === "M4")?.entries ?? [];
  const answerSentence = sentences.find((s) => matchAny(s.text, m4));
  if (answerSentence) {
    const answer = extractAnswer(answerSentence);
    if (!answer) return none("amend", sc.confidence, "Heard an answer but could not read it; say 'the answer is …'.");
    const questions = input.cards.filter((c) => c.kind === "question" && c.answer === null);
    const recentQ = bySeqDesc(questions.filter((c) => isRecent(c, input)));
    const target = recentQ[0] ?? (questions.length === 1 ? questions[0] : undefined);
    const op = (id: string): ClassifierOperation => ({ kind: "card.update", card_id: id, patch: { ...emptyPatch, answer }, amendment: null });
    if (target) return { intent: "amend", operations: [op(target.id)], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: `Answered "${titleOf(target)}".` };
    if (questions.length >= 2) {
      const res: Resolution = { kind: "ambiguous", candidates: bySeqDesc(questions), why: "no question was asked recently" };
      return fromAsk(askTarget(res, op(CHOICE), "amend", "answer", input, { kind: "question" }), "amend", sc.confidence, "amend", "Which question? Several are open.", "There is no open question to answer.");
    }
    return none("amend", sc.confidence, "There is no open question to answer.");
  }
  const probe = extractAmendment(sentences, null);
  const ref = parseReferent(s1.text);
  const res = resolveReferent(ref, input, { kind: probe ? "rule" : undefined });
  if (res.kind === "resolved") {
    const am = extractAmendment(sentences, res.card);
    const op: ClassifierOperation = {
      kind: "card.update",
      card_id: res.card.id,
      patch: am ? am.patch : { ...emptyPatch, text_append: appendText(sentences) },
      amendment: am ? am.amendment : null,
    };
    const rationale = am && am.patch.text !== null
      ? `Change to ${titleOf(res.card)}: replaced '${am.from}' with '${am.to}'.`
      : `Change to ${titleOf(res.card)}: appended the amendment verbatim; review the wording.`;
    return { intent: "amend", operations: [op], confidence: sc.confidence, clarification: null, heard_intent: null, rationale };
  }
  if (res.kind === "ambiguous") {
    const op: ClassifierOperation = {
      kind: "card.update",
      card_id: CHOICE,
      patch: { ...emptyPatch, text_append: appendText(sentences) },
      amendment: probe ? { from: null, to: probe.to, scope: probe.scope } : null,
    };
    const kind = ref?.kind ?? (probe ? "rule" : null);
    return fromAsk(askTarget(res, op, "amend", "change", input, { kind }), "amend", sc.confidence, "amend", `Which ${kindWord(kind)}? ${capitalizeFirst(res.why)}.`, `There is no ${kindWord(kind)} to change.`);
  }
  return none("amend", sc.confidence, `There is no ${kindWord(ref?.kind ?? (probe ? "rule" : null))} to change.`);
}

function capitalizeFirst(s: string): string {
  if (s.startsWith("no ")) return `There is ${s}`;
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

function handleRemove(sentences: Sentence[], sc: Scoring, input: ClassifierInput): Draft {
  const s1 = sentences[0]!;
  const ref = parseReferent(s1.text);
  const res = resolveReferent(ref, input, {});
  const first = sc.firstHit.remove ?? { sentence: 0, end: 0 };
  const reason = extractReason(sentences, first.sentence, first.end);
  if (res.kind === "resolved") {
    const op: ClassifierOperation = { kind: "card.remove", card_id: res.card.id, reason };
    return { intent: "remove", operations: [op], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: `Remove ${titleOf(res.card)} — ${res.how}.` };
  }
  const kind = ref?.kind ?? null;
  if (res.kind === "ambiguous") {
    const op: ClassifierOperation = { kind: "card.remove", card_id: CHOICE, reason };
    return fromAsk(askTarget(res, op, "remove", "remove", input, { kind }), "remove", sc.confidence, "remove", `Which ${kindWord(kind)}? ${capitalizeFirst(res.why)}.`, `There is no ${kindWord(kind)} to remove.`);
  }
  return none("remove", sc.confidence, `There is no ${kindWord(kind)} to remove.`);
}

function handleReplace(sentences: Sentence[], sc: Scoring, input: ClassifierInput): Draft {
  const s1 = sentences[0]!;
  const replacement = replacementDraft(sentences, DRAFT_MIN_CONTENT_WORDS);
  let replacementCard: CardIndexEntry | null = null;
  if (!replacement) {
    const lp = input.last_proposal;
    if (inWindow(lp, input) && lp.intent === "add") {
      const id = lp.card_ids[0];
      replacementCard = input.cards.find((c) => c.id === id) ?? null;
    }
  }
  if (!replacement && !replacementCard) return none("replace", sc.confidence, "Heard 'instead' but no new content; say the new example first.");
  const ref = parseReferent(s1.text);
  const kind: CardKind = replacement ? replacement.kind : replacementCard!.kind;
  const res = resolveReferent(ref, input, { kind, exclude: replacementCard ? [replacementCard.id] : [] });
  const make = (target: string): ClassifierOperation => ({
    kind: "card.replace",
    card_id: target,
    replacement: replacement ? { text: replacement.text } : null,
    replacement_card_id: replacementCard ? replacementCard.id : null,
  });
  if (res.kind === "resolved") {
    const withWhat = replacement ? "the new text" : `the ${replacementCard!.kind} you just gave`;
    return { intent: "replace", operations: [make(res.card.id)], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: `Replace ${titleOf(res.card)} with ${withWhat}.` };
  }
  const k = ref?.kind ?? kind;
  if (res.kind === "ambiguous") {
    return fromAsk(askTarget(res, make(CHOICE), "replace", "replace", input, { kind: k }), "replace", sc.confidence, "replace", `Which ${kindWord(k)}? ${capitalizeFirst(res.why)}.`, `There is no ${kindWord(k)} to replace.`);
  }
  return none("replace", sc.confidence, `There is no ${kindWord(k)} to replace.`);
}

function handleClarify(sentences: Sentence[], sc: Scoring, input: ClassifierInput): Draft {
  let def: { term: string; definition: string } | null = null;
  let defSentence: Sentence | null = null;
  for (const s of sentences) {
    def = extractDefinition(s);
    if (def) { defSentence = s; break; }
  }
  if (!def || !defSentence) return none("clarify", sc.confidence, "Heard a clarification but no definition; say 'By X I mean Y'.");
  // an explicit referent with a kind ("for the GP example, by X I mean Y") names the card; otherwise the story
  const explicit = parseReferents(defSentence.text).find((r) => r.kind !== null || (r.topic !== null && r.topic.named));
  let cardId: string | null = null;
  if (explicit) {
    const res = resolveReferent(explicit, input, {});
    if (res.kind === "resolved") cardId = res.card.id;
    else if (res.kind === "ambiguous") {
      const op: ClassifierOperation = { kind: "definition.refine", card_id: CHOICE, term: def.term, definition: def.definition };
      return fromAsk(askTarget(res, op, "clarify", "define", input, { kind: explicit.kind }), "clarify", sc.confidence, "clarify", `Which ${kindWord(explicit.kind)} does the definition belong to?`, "There is no card to attach the definition to.");
    }
  }
  if (cardId === null) {
    const story = input.cards.find((c) => c.kind === "story");
    if (!story) return none("clarify", sc.confidence, "There is no story to attach the definition to.");
    cardId = story.id;
  }
  const op: ClassifierOperation = { kind: "definition.refine", card_id: cardId, term: def.term, definition: def.definition };
  return { intent: "clarify", operations: [op], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: `Defined '${def.term}'.` };
}

function handleReject(sc: Scoring, input: ClassifierInput): Draft {
  const lr = input.last_rejectable;
  if (lr === null) return none("reject", sc.confidence, "Heard a rejection, but nothing on the map can be rejected right now; use Remove or Edit on the card.");
  if (inWindow(lr, input)) {
    const op: ClassifierOperation = { kind: "interpretation.reject", proposal_id: lr.id };
    return { intent: "reject", operations: [op], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: `Rejecting the last interpretation (${quote(sc.cues.reject)}).` };
  }
  const pool = bySeqDesc(input.cards.filter((c) => c.kind !== "story" && c.proposal_id !== null));
  const res: Resolution = pool.length === 0 ? { kind: "none", why: "no interpretation on the map" } : { kind: "ambiguous", candidates: pool, why: "" };
  const op: ClassifierOperation = { kind: "interpretation.reject", proposal_id: CHOICE };
  const ask = askTarget(res, op, "reject", "reject the interpretation that produced", input, { question: "Which interpretation is wrong?", kind: null });
  if (ask.kind === "clarification" && ask.clarification.kind === "confirm_intent") {
    ask.clarification.question = ask.clarification.question.replace(/ \(\)$/, "");
  }
  return fromAsk(ask, "reject", sc.confidence, "reject", "Which interpretation is wrong? The last one is not recent.", "Heard a rejection, but nothing on the map can be rejected right now; use Remove or Edit on the card.");
}

function handleConfirm(sc: Scoring, input: ClassifierInput): Draft {
  const lp = input.last_proposal;
  if (lp === null) return none("confirm", sc.confidence, "Nothing to confirm yet.");
  if (lp.status === "confirmed") return none("confirm", sc.confidence, "That interpretation is already confirmed.");
  if (lp.op === "confirm") return none("confirm", sc.confidence, "A confirmation cannot be confirmed.");
  if (lp.op === "card.remove" || lp.op === "undo" || lp.op === "interpretation.reject") {
    const what = lp.op === "card.remove" ? "removal" : lp.op === "undo" ? "undo" : "rejection";
    return { intent: "confirm", operations: [{ kind: "confirm", card_ids: [] }], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: `Confirmed the ${what}.` };
  }
  const live = lp.card_ids.filter((id) => input.cards.some((c) => c.id === id));
  if (live.length === 0) return none("confirm", sc.confidence, "Nothing live to confirm.");
  return { intent: "confirm", operations: [{ kind: "confirm", card_ids: live }], confidence: sc.confidence, clarification: null, heard_intent: null, rationale: "Confirmed the last interpretation." };
}

function handleUndo(sentences: Sentence[], sc: Scoring): Draft {
  const all = sentences.map((s) => cueText(s.text)).join(" | ");
  let steps = 1;
  const m = /(\d+) (steps?|changes?|versions?|times)\b/.exec(all);
  if (m) steps = Math.max(1, Number(m[1]));
  else if (/\btwice\b/.test(all)) steps = 2;
  const rationale = steps === 1 ? `Undo one step (${quote(sc.cues.undo)}).` : `Undo ${steps} steps (${quote(sc.cues.undo)}).`;
  return { intent: "undo", operations: [{ kind: "undo", steps }], confidence: sc.confidence, clarification: null, heard_intent: null, rationale };
}

/* ───────────── prefix, threshold, finalisation ───────────── */

function addPrefix(draft: Draft, sc: Scoring, input: ClassifierInput): Draft {
  if (sc.prefix === null || draft.intent === "none" || draft.clarification !== null) {
    if (sc.prefix !== null && draft.intent !== "none" && draft.clarification !== null) {
      return { ...draft, rationale: `${draft.rationale} (The leading '${sc.prefix === "reject" ? "no" : "yes"}' was not applied.)` };
    }
    return draft;
  }
  if (sc.prefix === "reject") {
    const lr = input.last_rejectable;
    if (inWindow(lr, input)) return { ...draft, operations: [{ kind: "interpretation.reject", proposal_id: lr.id }, ...draft.operations] };
    return { ...draft, rationale: `${draft.rationale} (The leading 'no' could not be tied to a recent interpretation.)` };
  }
  const lp = input.last_proposal;
  if (inWindow(lp, input) && lp.status === "applied" && (lp.op === "card.create" || lp.op === "card.update" || lp.op === "card.replace" || lp.op === "definition.refine")) {
    const live = lp.card_ids.filter((id) => input.cards.some((c) => c.id === id));
    if (live.length > 0) return { ...draft, operations: [{ kind: "confirm", card_ids: live }, ...draft.operations] };
  }
  return { ...draft, rationale: `${draft.rationale} (The leading 'yes' could not be tied to a recent interpretation.)` };
}

function labelOfOp(op: ClassifierOperation, input: ClassifierInput): string {
  const id = "card_id" in op ? op.card_id : op.kind === "confirm" ? op.card_ids[0] ?? "" : "";
  const card = input.cards.find((c) => c.id === id);
  return card ? candidateLabel(card, input) : "that card";
}

/** Below MIN_CONFIDENCE an actionable proposal becomes a confirm_intent question (the prefix op is dropped). */
export function thresholdWrap(draft: Draft, sc: Scoring | null, input: ClassifierInput): Draft {
  if (draft.intent === "none" || draft.clarification !== null || draft.confidence >= MIN_CONFIDENCE) return draft;
  const ops = draft.operations;
  const main = ops[ops.length - 1];
  if (!main) return draft;
  const dropped = ops.length > 1;
  let detail: Parameters<typeof verbPhrase>[1] = {};
  switch (main.kind) {
    case "card.create": detail = { kind: main.card.kind, text: main.card.text }; break;
    case "definition.refine": detail = { term: main.term }; break;
    case "card.update": case "card.remove": case "card.replace": detail = { label: labelOfOp(main, input) }; break;
    default: detail = {};
  }
  const question = `Did you mean to ${verbPhrase(draft.intent, detail)}?`;
  let rationale: string;
  if (sc && sc.runner && sc.scores[sc.runner] > 0) {
    rationale = `Could be ${sc.best} or ${sc.runner}: matched ${quote(sc.cues[sc.best as Intent].slice(0, 1))} and ${quote(sc.cues[sc.runner].slice(0, 1))}.`;
  } else if (sc && sc.best !== "none") {
    rationale = `Only a weak cue for ${sc.best} (${quote(sc.cues[sc.best].slice(0, 2))}); asking.`;
  } else {
    rationale = "Not confident enough; asking.";
  }
  if (dropped) rationale += " (The leading yes/no was dropped.)";
  return {
    ...draft,
    operations: [],
    clarification: { kind: "confirm_intent", question, candidates: [], pending_operations: [main] },
    rationale,
  };
}

function trimRationale(r: string): string {
  const t = r.replace(/\s+/g, " ").trim();
  if (!t) return "Classified by rules.v1.";
  return t.length > RATIONALE_MAX ? `${t.slice(0, RATIONALE_MAX - 1).trimEnd()}…` : t;
}

function finalize(draft: Draft, input: ClassifierInput, resolves: ClassifierResolves | null): ClassifierProposal {
  const needs = draft.clarification !== null;
  const partial = { operations: draft.operations, clarification: draft.clarification };
  const source = [input.utterance.id];
  if (resolves && input.pending_clarification) source.push(input.pending_clarification.asked_by_utterance_id);
  const p: ClassifierProposal = {
    intent: draft.intent,
    operations: draft.operations,
    target_card_ids: targetCardIds(partial),
    confidence: round2(draft.confidence),
    needs_clarification: needs,
    clarification: draft.clarification,
    resolves,
    rationale: trimRationale(draft.rationale),
    heard_intent: draft.intent === "none" ? draft.heard_intent : null,
    classifier: { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null },
    source_utterance_ids: source,
  };
  assertProposalInvariants(p, input);
  return p;
}

/** Steps 3–5 of the pipeline over already-normalised sentences. */
function classifySentences(sentences: Sentence[], input: ClassifierInput, resolves: ClassifierResolves | null): ClassifierProposal {
  if (sentences.length === 0) return finalize(chatter(), input, resolves);
  const sc = scoreSentences(sentences, input);
  let draft: Draft;
  switch (sc.best) {
    case "none": draft = chatter(); break;
    case "add": draft = handleAdd(sentences, sc, input); break;
    case "amend": draft = handleAmend(sentences, sc, input); break;
    case "remove": draft = handleRemove(sentences, sc, input); break;
    case "replace": draft = handleReplace(sentences, sc, input); break;
    case "clarify": draft = handleClarify(sentences, sc, input); break;
    case "reject": draft = handleReject(sc, input); break;
    case "confirm": draft = handleConfirm(sc, input); break;
    case "undo": draft = handleUndo(sentences, sc); break;
  }
  draft = addPrefix(draft, sc, input);
  draft = thresholdWrap(draft, sc, input);
  return finalize(draft, input, resolves);
}

/** The pure classifier: same input -> byte-identical proposal. Throws ClassifierError on a malformed input. */
export function classifyRules(input: ClassifierInput): ClassifierProposal {
  const parsed = ClassifierInputSchema.safeParse(input);
  if (!parsed.success) {
    throw new ClassifierError("E_CLASSIFIER_INPUT_INVALID", parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
  }
  const n = normalizeText(input.utterance.text);
  const sentences = splitSentences(n).map(stripDiscourse).filter((s): s is Sentence => s !== null);
  if (sentences.length === 0) return finalize(chatter(), input, null);
  const pending = input.pending_clarification;
  if (pending) {
    const s1 = sentences[0]!;
    const rest = sentences.slice(1);
    const scoreOf = (s: Sentence): Record<Intent, number> => groupScores([s], input).scores;
    const answer = parseAnswer(s1, pending, rest, scoreOf(s1), { scoreOf, cards: input.cards });
    if (answer) {
      if (answer.kind === "dismiss" && answer.remainder) {
        return classifySentences(answer.remainder, input, { proposal_id: pending.proposal_id, chosen_card_ids: [], dismissed: true });
      }
      const p = resolveClarificationAnswer(pending, answer, input);
      assertProposalInvariants(p, input);
      return p;
    }
  }
  return classifySentences(sentences, input, null);
}

