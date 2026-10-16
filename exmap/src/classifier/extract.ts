// exmap/src/classifier/extract.ts — cue matching plus detectKind, kindCue, extractDraft, extractAmendment, extractAnswer,
// extractDefinition, extractReason, replacementDraft (design §6.3). Extractors match on the normalised sentence text and read
// captures back as original spans, so drafts, amendments and definitions keep the speaker's own words.
import type { CardDraft, CardKind, ClassifierAmendment, ClassifierCardPatch, ClassifierInput, Intent } from "../core/types.js";
import {
  A3_EXCLUDED_SUBJECTS, A3_OPENER, A5_OPENER, A5_TERMINAL, CORRECTION_PREFIX, DEFINITION_PATTERNS, INTENT_CUES,
  INTERROGATIVE_OPENERS, KIND_CUES, KIND_NOUNS, LEAD_IN_PATTERNS, type CueEntry,
} from "./cues.js";
import { contentTokens, normalizeText, originalSpan, sentenceRaw, type Sentence } from "./normalize.js";
import { linkAbout, linkRule, maskReferents } from "./referents.js";

export interface CueHit {
  cue: string;
  index: number;
  end: number;
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const phraseCache = new Map<string, RegExp>();
function phraseRe(phrase: string): RegExp {
  let re = phraseCache.get(phrase);
  if (!re) {
    re = new RegExp(`(?<![a-z0-9'])${escapeRe(phrase)}(?![a-z0-9'])`);
    phraseCache.set(phrase, re);
  }
  return re;
}

/** Matches one cue entry (a phrase at word boundaries, or a regex) against a text. */
export function matchEntry(text: string, entry: CueEntry): CueHit | null {
  const re = typeof entry === "string" ? phraseRe(entry) : entry;
  const m = re.exec(text);
  if (!m) return null;
  return { cue: m[0], index: m.index, end: m.index + m[0].length };
}

/** The first matching entry of a list. */
export function matchAny(text: string, entries: readonly CueEntry[]): CueHit | null {
  for (const e of entries) {
    const h = matchEntry(text, e);
    if (h) return h;
  }
  return null;
}

/** The sentence text as cue matching sees it: commas removed, "?" kept. */
export function cueText(text: string): string {
  return text.replace(/,/g, "").replace(/\s+/g, " ").trim();
}

/** The rule-kind cue search ignores a sentence-initial interrogative opener ("should we delete that?" is A5, not a rule). */
function withoutOpener(masked: string): string {
  const first = masked.split(" ")[0] ?? "";
  if (INTERROGATIVE_OPENERS.has(first)) return masked.slice(first.length).trim();
  return masked;
}

/** Lexical card-kind cue on the (masked) sentence; precedence question > example > rule. */
export function kindCue(masked: string): { kind: "rule" | "example" | "question"; cue: string } | null {
  const text = cueText(masked);
  const q = matchAny(text, KIND_CUES.question);
  if (q) return { kind: "question", cue: q.cue };
  const e = matchAny(text, KIND_CUES.example);
  if (e) return { kind: "example", cue: e.cue };
  const r = matchAny(withoutOpener(text), KIND_CUES.rule);
  if (r) return { kind: "rule", cue: r.cue };
  return null;
}

/** A3: subject-modal opener on the comma-less sentence, subject not a pronoun / discourse word. */
export function a3Match(text: string): CueHit | null {
  // the sentence itself, then each clause after a comma ("Actually, patients must confirm by email")
  const clauses = text.split(",").map((c) => c.trim()).filter(Boolean);
  let offset = 0;
  for (let i = 0; i < clauses.length; i++) {
    const clause = cueText(clauses[i] ?? "");
    const m = A3_OPENER.exec(clause);
    if (m) {
      const s1 = m[2] ?? "";
      const s2 = m[3] ?? "";
      if (!(A3_EXCLUDED_SUBJECTS.has(s1) || (s2 && A3_EXCLUDED_SUBJECTS.has(s2)))) return { cue: m[0], index: offset, end: offset + m[0].length };
    }
    offset += (clauses[i]?.length ?? 0) + 1;
  }
  return null;
}

/** A5: interrogative form. */
export function a5Match(text: string): CueHit | null {
  const t = cueText(text);
  if (A5_TERMINAL.test(t)) return { cue: "?", index: t.length - 1, end: t.length };
  const m = A5_OPENER.exec(t);
  if (m) return { cue: m[0], index: 0, end: m[0].length };
  return null;
}

export interface KindDetection {
  kind: "rule" | "example" | "question";
  cue: string | null;
  how: "cue" | "continuation" | "noun" | "default";
}

/**
 * The kind of the card an add creates: every kindCue plus the interrogative form as question cues (question > example >
 * rule); no cue -> A6 (the last add's kind); then the A1 noun heuristic; otherwise rule (and the rationale says so).
 */
export function detectKind(sentences: Sentence[], ctx: { input: ClassifierInput; continuation: boolean }): KindDetection {
  let example: string | null = null;
  let rule: string | null = null;
  for (const s of sentences) {
    const masked = maskReferents(s.text);
    const q = matchAny(cueText(masked), KIND_CUES.question);
    if (q) return { kind: "question", cue: q.cue, how: "cue" };
    if (a5Match(s.text)) return { kind: "question", cue: "?", how: "cue" };
    const kc = kindCue(masked);
    if (kc?.kind === "example" && example === null) example = kc.cue;
    if (kc?.kind === "rule" && rule === null) rule = kc.cue;
  }
  if (example !== null) return { kind: "example", cue: example, how: "cue" };
  if (rule !== null) return { kind: "rule", cue: rule, how: "cue" };
  const lp = ctx.input.last_proposal;
  if (ctx.continuation && lp && lp.intent === "add" && lp.kind !== null && lp.kind !== "story") {
    return { kind: lp.kind, cue: null, how: "continuation" };
  }
  const all = sentences.map((s) => cueText(s.text)).join(" ");
  for (const n of KIND_NOUNS) {
    if (n.re.test(all)) return { kind: n.kind, cue: n.re.exec(all)?.[0] ?? null, how: "noun" };
  }
  return { kind: "rule", cue: null, how: "default" };
}

function capitalize(s: string): string {
  const t = s.trim().replace(/\s+/g, " ");
  if (!t) return t;
  return t[0]!.toUpperCase() + t.slice(1);
}

function ensureStop(s: string): string {
  const t = s.trim();
  if (!t) return t;
  return /[.?!]$/.test(t) ? t : `${t}.`;
}

/** The raw text of a sentence minus its lead-in phrases ("for example,", "one more example:", "yes, but", …). */
export function sentenceDraftText(s: Sentence): string {
  let raw = sentenceRaw(s).trim();
  for (let i = 0; i < 2; i++) {
    for (const re of LEAD_IN_PATTERNS) raw = raw.replace(re, "");
  }
  return raw.trim();
}

/** The draft of a new card: its text from the kept sentences, with links by linkRule / linkAbout. */
export function extractDraft(sentences: Sentence[], kind: CardKind, input: ClassifierInput): CardDraft {
  const parts: string[] = [];
  for (const s of sentences) {
    const t = sentenceDraftText(s);
    if (!t || contentTokens(t).length === 0) continue; // lead-in-only / discourse-only sentence
    parts.push(t);
  }
  const text = ensureStop(capitalize(parts.join(" ")));
  const draft: CardDraft = { kind, text, rule_id: null, about_card_id: null };
  if (kind === "example") draft.rule_id = linkRule(draft, input);
  if (kind === "question") draft.about_card_id = linkAbout(draft, input);
  return draft;
}

const VALUE_RE = /(?<![a-z0-9])(\d+(?:\.\d+)?)(?: (hours?|hrs?|minutes?|mins?|days?|weeks?|months?|years?|percent|%|pounds?|dollars?|times?))?(?![a-z0-9])/g;

export interface ValueHit {
  /** digits + unit, as the normalised text has it ("24 hours", "3 hours", "48") */
  value: string;
  index: number;
  end: number;
}

/** Every `<number> [unit]` phrase of a normalised text. */
export function findValues(text: string): ValueHit[] {
  const out: ValueHit[] = [];
  VALUE_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = VALUE_RE.exec(text)) !== null) {
    out.push({ value: m[0], index: m.index, end: m.index + m[0].length });
  }
  return out;
}

export interface AmendmentExtract {
  to: string;
  scope: string | null;
  from: string | null;
  patch: ClassifierCardPatch;
  amendment: ClassifierAmendment;
}

/** The utterance minus correction cues and yes/no prefixes, first letter upper-cased, trailing full stop ensured. */
export function appendText(sentences: Sentence[]): string {
  const parts: string[] = [];
  for (const s of sentences) {
    let raw = sentenceRaw(s).trim();
    raw = raw.replace(CORRECTION_PREFIX, "");
    raw = raw.replace(/^(yes|no|yeah|yep|nope)\b\s*,?\s*(but\b\s+)?/i, "");
    raw = raw.trim();
    if (raw) parts.push(raw);
  }
  return ensureStop(capitalize(parts.join(" ")));
}

/**
 * The amendment carried by an utterance: `to` = the first `<number> [unit]`, `scope` = the span after "for " following the
 * value, `from` = the single `<number> [unit]` of the card's text when exactly one exists. `card` null (a "$choice"
 * target) always yields the append form. Returns null when the utterance carries no value.
 */
export function extractAmendment(sentences: Sentence[], card: { text: string } | null): AmendmentExtract | null {
  let hit: ValueHit | null = null;
  let hitSentence: Sentence | null = null;
  for (const s of sentences) {
    const vals = findValues(s.text);
    const v = vals[0];
    if (v) { hit = v; hitSentence = s; break; }
  }
  if (!hit || !hitSentence) return null;
  const to = hit.value;
  let scope: string | null = null;
  const after = hitSentence.text.slice(hit.end);
  const sm = /^ for ([^,?]+)/.exec(after);
  if (sm && sm[1]) {
    const c0 = hit.end + " for ".length;
    scope = originalSpan(hitSentence, c0, c0 + sm[1].length).trim() || null;
  }
  let from: string | null = null;
  if (card) {
    const cn = normalizeText(card.text);
    const vals = findValues(cn.text);
    if (vals.length === 1 && vals[0]) from = originalSpan(cn, vals[0].index, vals[0].end) || null;
  }
  const amendment: ClassifierAmendment = { from, to, scope };
  const emptyPatch: ClassifierCardPatch = { text: null, text_append: null, answer: null, rule_id: null, about_card_id: null };
  if (card && scope === null && from !== null && from !== to && card.text.includes(from)) {
    const text = card.text.replace(from, to);
    return { to, scope, from, patch: { ...emptyPatch, text }, amendment };
  }
  return { to, scope, from, patch: { ...emptyPatch, text_append: appendText(sentences) }, amendment };
}

/** The recorded answer after an M4 cue ("the answer is …"), as the speaker said it, trailing full stop removed. */
export function extractAnswer(s: Sentence): string | null {
  const group = INTENT_CUES.amend.find((g) => g.id === "M4");
  if (!group) return null;
  const hit = matchAny(s.text, group.entries);
  if (!hit) return null;
  const rest = s.text.slice(hit.end).trim();
  if (!rest) return null;
  const c0 = hit.end + (s.text.slice(hit.end).length - s.text.slice(hit.end).trimStart().length);
  const span = originalSpan(s, c0, s.text.length).trim().replace(/[.!]+$/, "").trim();
  return span || null;
}

/** The definition carried by a C2 pattern: term and definition as original spans, term trimmed of articles. */
export function extractDefinition(s: Sentence): { term: string; definition: string } | null {
  for (const re of DEFINITION_PATTERNS) {
    const m = re.exec(s.text);
    if (!m || !m.indices?.groups) continue;
    const ti = m.indices.groups["term"];
    const di = m.indices.groups["def"];
    if (!ti || !di) continue;
    let term = originalSpan(s, ti[0], ti[1]).trim().replace(/^(an?|the) /i, "").replace(/[,]+$/, "").trim();
    const definition = originalSpan(s, di[0], di[1]).trim().replace(/[.!]+$/, "").trim();
    term = term.replace(/[.!?,]+$/, "");
    if (!term || !definition) continue;
    return { term, definition };
  }
  return null;
}

/** The reason of a removal: the sentences after the cue sentence, else the span after the first comma following the cue, else "". */
export function extractReason(sentences: Sentence[], cueIdx: number, cueEnd: number): string {
  const after = sentences.slice(cueIdx + 1).map((s) => sentenceRaw(s).trim()).filter(Boolean);
  if (after.length > 0) return after.join(" ");
  const s = sentences[cueIdx];
  if (!s) return "";
  const comma = s.text.indexOf(",", Math.max(0, cueEnd - 1));
  if (comma < 0) return "";
  const c0 = comma + 1;
  return originalSpan(s, c0, s.text.length).trim().replace(/^,\s*/, "").trim();
}

const P_PHRASES = ["instead of", "instead", "rather than", "in place of", "use this example", "use this rule", "use this one", "use this", "use that", "use the following", "this one instead", "this version", "this example", "this rule", "this wording", "the following", "replace", "replaces", "swap", "supersede", "supersedes", "better example", "better rule"];

/**
 * New content offered by a replace ("Instead, if a GP cancels at 9am …"): the utterance minus P1/P2 phrases and a leading
 * "instead,", kept only with >= DRAFT_MIN_CONTENT_WORDS content tokens and a kind cue or A3/A4 structure.
 */
export function replacementDraft(sentences: Sentence[], minWords: number): { text: string; kind: "rule" | "example" | "question" } | null {
  const parts: string[] = [];
  for (const s of sentences) {
    let raw = sentenceRaw(s).trim();
    for (const p of P_PHRASES) raw = raw.replace(new RegExp(`(?<![a-z0-9])${escapeRe(p)}(?![a-z0-9])\\s*,?\\s*`, "gi"), " ");
    raw = raw.replace(/^\s*,\s*/, "").trim();
    if (raw && contentTokens(raw).length > 0) parts.push(raw);
  }
  const text = parts.join(" ").replace(/\s+/g, " ").replace(/\s+([.,?!])/g, "$1").trim();
  if (!text) return null;
  if (contentTokens(text).length < minWords) return null;
  const n = normalizeText(text);
  const joined = n.sentences.map((s) => s.text).join(" | ");
  const kc = kindCue(joined);
  const structural = kc ?? (a3Match(joined) ? { kind: "rule" as const, cue: "a3" } : null) ?? (matchAny(cueText(joined), INTENT_CUES.add.find((g) => g.id === "A4")?.entries ?? []) ? { kind: "example" as const, cue: "a4" } : null);
  if (!structural) return null;
  return { text: ensureStop(capitalize(text)), kind: structural.kind };
}

/** A verb phrase for the confirm_intent question "Did you mean to …?". */
export function verbPhrase(intent: Intent, detail: { kind?: CardKind; text?: string; label?: string; term?: string }): string {
  const short = (t: string): string => (t.length > 40 ? `${t.slice(0, 40).trimEnd()}…` : t);
  switch (intent) {
    case "add": return `add a ${detail.kind ?? "card"}: "${short(detail.text ?? "")}"`;
    case "amend": return `change ${detail.label ?? "that card"}`;
    case "remove": return `remove ${detail.label ?? "that card"}`;
    case "replace": return `replace ${detail.label ?? "that card"}`;
    case "clarify": return `define "${detail.term ?? ""}"`;
    case "reject": return "reject the last interpretation";
    case "confirm": return "confirm the last interpretation";
    case "undo": return "undo the last change";
  }
}
