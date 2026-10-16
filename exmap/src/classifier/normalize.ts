// exmap/src/classifier/normalize.ts — normalizeText, splitSentences, stripDiscourse, contentTokens, tokenMatch, originalSpan
// (design §6.3). Normalisation works token by token so every normalised token keeps the character span of the original
// word(s); extractors match on the normalised text and read captures back with originalSpan(), so a capture such as
// "two hours" or "a booked slot, not a walk-in" keeps the speaker's casing, hyphens and number words.
import { CONTINUATION_WORDS, DISCOURSE_DROP, DISCOURSE_MARKERS, NEVER_STRIP, STOP_WORDS } from "./cues.js";

export type TokKind = "word" | "comma" | "q" | "break";

/** One normalised token: its text, its kind and the span [r0, r1) of the raw utterance it came from. */
export interface Tok {
  t: string;
  r0: number;
  r1: number;
  kind: TokKind;
  /** Absolute position of the rendered token in Normalized.text ([n0, n1); -1 for an unrendered break). */
  n0: number;
  n1: number;
}

export interface Normalized {
  raw: string;
  toks: Tok[];
  /** The normalised text: sentences joined with " | ", words separated by single spaces, "," and "?" attached. */
  text: string;
  sentences: Sentence[];
}

/** A sentence of the normalised text: a rendered token range plus the break token that closed it. */
export interface Sentence {
  norm: Normalized;
  i0: number;
  i1: number;
  term: Tok | null;
  /** The sentence's normalised text (a substring of norm.text starting at `offset`). */
  text: string;
  offset: number;
  /** The first word of the sentence before stripDiscourse() ran (A6 remembers "and", "also", …). */
  lead: string | null;
  /** The raw span of the sentence (including its terminator). */
  rawStart: number;
  rawEnd: number;
}

const CONTRACTIONS: Record<string, string> = {
  "don't": "do not", "doesn't": "does not", "didn't": "did not", "can't": "can not", "cannot": "can not", "won't": "will not",
  "wouldn't": "would not", "shouldn't": "should not", "couldn't": "could not", "isn't": "is not", "aren't": "are not",
  "wasn't": "was not", "weren't": "were not", "hasn't": "has not", "haven't": "have not", "hadn't": "had not",
  "mustn't": "must not", "needn't": "need not", "ain't": "is not", "that's": "that is", "it's": "it is", "what's": "what is",
  "there's": "there is", "here's": "here is", "who's": "who is", "let's": "let us", "i'm": "i am", "we're": "we are",
  "they're": "they are", "you're": "you are", "i've": "i have", "we've": "we have", "they've": "they have",
  "you've": "you have", "i'd": "i would", "we'd": "we would", "you'd": "you would", "they'd": "they would",
  "i'll": "i will", "we'll": "we will", "you'll": "you will", "they'll": "they will", "it'll": "it will",
  "that'll": "that will", "he's": "he is", "she's": "she is", "where's": "where is", "how's": "how is",
};

const UNITS_WORDS: Record<string, number> = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11,
  twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19,
};
const TENS_WORDS: Record<string, number> = {
  twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90,
};
const UNIT_NOUNS = new Set([
  "hour", "hours", "hr", "hrs", "minute", "minutes", "min", "mins", "day", "days", "week", "weeks", "month", "months",
  "year", "years", "percent", "pound", "pounds", "dollar", "dollars", "time", "times", "second", "seconds",
]);

interface RawTok { t: string; r0: number; r1: number; kind: TokKind }

function cleanWord(s: string): string {
  return s.replace(/[^a-z0-9'%]/g, "").replace(/^'+/, "");
}

/** Splits one whitespace-delimited chunk of the raw text into tokens. */
function chunkTokens(raw: string, s: number, e: number, out: RawTok[]): void {
  const chunkRaw = raw.slice(s, e);
  const chunk = chunkRaw.toLowerCase().replace(/[’‘]/g, "'").replace(/[“”]/g, '"');
  // abbreviations whose dots are not sentence breaks
  const abbr = /^[^a-z0-9]*(e\.g|i\.e)\.?([^a-z0-9]*)$/.exec(chunk);
  if (abbr) {
    const letters = abbr[1] ?? "e.g";
    out.push({ t: letters[0] ?? "e", r0: s, r1: e, kind: "word" });
    out.push({ t: letters[2] ?? "g", r0: s, r1: e, kind: "word" });
    pushTrailing(abbr[2] ?? "", s, e, out);
    return;
  }
  // leading punctuation (quotes, brackets, dashes) is dropped
  let b0 = 0;
  while (b0 < chunk.length && !/[a-z0-9%£$€]/.test(chunk[b0] ?? "")) b0++;
  // trailing punctuation cluster
  let b1 = chunk.length;
  while (b1 > b0 && !/[a-z0-9%]/.test(chunk[b1 - 1] ?? "")) b1--;
  if (b0 >= b1) {
    // a chunk made only of punctuation: "..." / "—" / "?"
    pushTrailing(chunk, s, e, out);
    return;
  }
  const body = chunk.slice(b0, b1);
  // split the body into pieces on hyphens, dashes, slashes and dots that are not between digits
  let p0 = 0;
  const pieces: Array<[number, number]> = [];
  for (let i = 0; i <= body.length; i++) {
    const ch = body[i];
    const isDigitDot = ch === "." && i > 0 && i + 1 < body.length && /\d/.test(body[i - 1] ?? "") && /\d/.test(body[i + 1] ?? "");
    const isDigitComma = ch === "," && i > 0 && i + 1 < body.length && /\d/.test(body[i - 1] ?? "") && /\d/.test(body[i + 1] ?? "");
    const sep = i === body.length || ((ch === "-" || ch === "–" || ch === "—" || ch === "/" || ch === ".") && !isDigitDot);
    if (sep) {
      if (i > p0) pieces.push([p0, i]);
      p0 = i + 1;
    } else if (isDigitComma) {
      // "1,000" -> "1000": handled by cleanWord dropping the comma
    }
  }
  for (const [a, b] of pieces) {
    const pieceRaw = body.slice(a, b);
    const r0 = s + b0 + a;
    const r1 = s + b0 + b;
    const cleaned = cleanWord(pieceRaw).replace(/'+$/, "");
    if (!cleaned) continue;
    const expanded = CONTRACTIONS[cleaned];
    if (expanded !== undefined) {
      for (const w of expanded.split(" ")) out.push({ t: w, r0, r1, kind: "word" });
      continue;
    }
    const generic = /^([a-z]+)'(ll|re|ve|d|m)$/.exec(cleaned);
    if (generic) {
      const map: Record<string, string> = { ll: "will", re: "are", ve: "have", d: "would", m: "am" };
      out.push({ t: generic[1] ?? "", r0, r1, kind: "word" });
      out.push({ t: map[generic[2] ?? ""] ?? "", r0, r1, kind: "word" });
      continue;
    }
    out.push({ t: cleaned, r0, r1, kind: "word" });
  }
  pushTrailing(chunk.slice(b1), s + b1, e, out);
}

function pushTrailing(cluster: string, r0: number, r1: number, out: RawTok[]): void {
  if (!cluster) return;
  if (cluster.includes("?")) out.push({ t: "?", r0, r1, kind: "q" });
  else if (/[.!;:]/.test(cluster)) out.push({ t: "|", r0, r1, kind: "break" });
  else if (cluster.includes(",")) out.push({ t: ",", r0, r1, kind: "comma" });
}

/** Number words -> digits over consecutive word tokens; "one" only inside a compound or before a unit noun. */
function foldNumbers(toks: RawTok[]): RawTok[] {
  const out: RawTok[] = [];
  let i = 0;
  const word = (k: number): string | null => (toks[k]?.kind === "word" ? (toks[k]?.t ?? null) : null);
  while (i < toks.length) {
    const t = toks[i];
    if (!t || t.kind !== "word") { if (t) out.push(t); i++; continue; }
    // "a couple of" -> 2
    if (t.t === "a" && word(i + 1) === "couple" && word(i + 2) === "of") {
      out.push({ t: "2", r0: t.r0, r1: toks[i + 2]?.r1 ?? t.r1, kind: "word" });
      i += 3;
      continue;
    }
    // "half an hour" -> 30 minutes
    if (t.t === "half" && word(i + 1) === "an" && word(i + 2) === "hour") {
      const r1 = toks[i + 2]?.r1 ?? t.r1;
      out.push({ t: "30", r0: t.r0, r1, kind: "word" });
      out.push({ t: "minutes", r0: t.r0, r1, kind: "word" });
      i += 3;
      continue;
    }
    // "an hour" -> 1 hour
    if (t.t === "an" && word(i + 1) === "hour") {
      const r1 = toks[i + 1]?.r1 ?? t.r1;
      out.push({ t: "1", r0: t.r0, r1, kind: "word" });
      out.push({ t: "hour", r0: t.r0, r1, kind: "word" });
      i += 2;
      continue;
    }
    const seq = numberSequence(toks, i);
    if (seq) {
      out.push({ t: String(seq.value), r0: t.r0, r1: toks[seq.end - 1]?.r1 ?? t.r1, kind: "word" });
      i = seq.end;
      continue;
    }
    out.push(t);
    i++;
  }
  return out;
}

/** Parses a run of number words starting at i; returns null when it is not a number (or a lone "one" not before a unit). */
function numberSequence(toks: RawTok[], i: number): { value: number; end: number } | null {
  let k = i;
  let value = 0;
  let count = 0;
  let sawHundred = false;
  let last: "none" | "unit" | "tens" | "hundred" = "none";
  for (;;) {
    const tk = toks[k];
    if (!tk || tk.kind !== "word") break;
    const w = tk.t;
    if (w in UNITS_WORDS) {
      const u = UNITS_WORDS[w] ?? 0;
      if (last === "unit") break; // "two three" is not one number
      if (last === "tens" && u >= 10) break; // "twenty twelve"
      value += u;
      last = "unit";
      count++;
      k++;
      continue;
    }
    if (w in TENS_WORDS) {
      if (last === "unit" || last === "tens") break;
      value += TENS_WORDS[w] ?? 0;
      last = "tens";
      count++;
      k++;
      continue;
    }
    if (w === "hundred" && last === "unit" && !sawHundred) {
      value *= 100;
      sawHundred = true;
      last = "hundred";
      count++;
      k++;
      const andTok = toks[k];
      const afterAnd = toks[k + 1];
      if (andTok?.kind === "word" && andTok.t === "and" && afterAnd?.kind === "word" && (afterAnd.t in UNITS_WORDS || afterAnd.t in TENS_WORDS)) k++;
      continue;
    }
    break;
  }
  if (count === 0) return null;
  const first = toks[i]?.t ?? "";
  if (count === 1 && first === "one") {
    const next = toks[k];
    if (!next || next.kind !== "word" || !UNIT_NOUNS.has(next.t)) return null;
  }
  return { value, end: k };
}

/** The pure normalisation of design §6.3 (1)–(4). Same input -> identical output. */
export function normalizeText(raw: string): Normalized {
  const rawToks: RawTok[] = [];
  const re = /\S+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) chunkTokens(raw, m.index, m.index + m[0].length, rawToks);
  const folded = foldNumbers(rawToks);
  const toks: Tok[] = folded.map((t) => ({ ...t, n0: -1, n1: -1 }));
  const norm: Normalized = { raw, toks, text: "", sentences: [] };
  // sentence ranges: a break or a q token closes a sentence
  const sentences: Sentence[] = [];
  let i0 = 0;
  for (let i = 0; i <= toks.length; i++) {
    const tk = toks[i];
    const closes = tk === undefined || tk.kind === "break" || tk.kind === "q";
    if (!closes) continue;
    const i1 = tk?.kind === "q" ? i + 1 : i;
    const hasWord = toks.slice(i0, i1).some((x) => x.kind === "word");
    if (hasWord) {
      const term = tk?.kind === "break" ? tk : null;
      const s: Sentence = { norm, i0, i1, term, text: "", offset: 0, lead: null, rawStart: 0, rawEnd: 0 };
      sentences.push(s);
    }
    i0 = tk?.kind === "q" ? i + 1 : i + 1;
  }
  // render
  let text = "";
  for (const s of sentences) {
    if (text) text += " | ";
    s.offset = text.length;
    text += renderSentence(s, text.length);
    s.text = text.slice(s.offset);
    const first = firstWord(s);
    s.lead = first ? first.t : null;
    const start = toks[s.i0];
    const last = s.term ?? toks[s.i1 - 1];
    s.rawStart = start?.r0 ?? 0;
    s.rawEnd = last?.r1 ?? raw.length;
  }
  norm.text = text;
  norm.sentences = sentences;
  return norm;
}

/** Renders tokens i0..i1 of a sentence into text, setting each token's absolute n0/n1 (base = where the text starts). */
function renderSentence(s: Sentence, base: number): string {
  let out = "";
  for (let k = s.i0; k < s.i1; k++) {
    const tk = s.norm.toks[k];
    if (!tk) continue;
    if (tk.kind === "break") continue;
    if (tk.kind === "word") {
      if (out) out += " ";
      tk.n0 = base + out.length;
      out += tk.t;
      tk.n1 = base + out.length;
    } else {
      // comma / q attach to the preceding word
      if (!out) continue;
      tk.n0 = base + out.length;
      out += tk.t;
      tk.n1 = base + out.length;
    }
  }
  return out;
}

function firstWord(s: Sentence): Tok | null {
  for (let k = s.i0; k < s.i1; k++) {
    const tk = s.norm.toks[k];
    if (tk && tk.kind === "word") return tk;
  }
  return null;
}

/** The sentences of a normalised utterance (split on "|" and "?", "?" kept attached). */
export function splitSentences(n: Normalized): Sentence[] {
  return n.sentences;
}

/** The raw text of a sentence (including its terminator), after any stripping. */
export function sentenceRaw(s: Sentence): string {
  return s.norm.raw.slice(s.rawStart, s.rawEnd);
}

/** The word tokens of a sentence in order. */
export function sentenceWords(s: Sentence): Tok[] {
  const out: Tok[] = [];
  for (let k = s.i0; k < s.i1; k++) {
    const tk = s.norm.toks[k];
    if (tk && tk.kind === "word") out.push(tk);
  }
  return out;
}

/** A sub-sentence starting at token index `from` (used by stripDiscourse and the clarification dismissal remainder). */
export function subSentence(s: Sentence, from: number): Sentence | null {
  let k = from;
  // skip leading commas
  while (k < s.i1 && s.norm.toks[k]?.kind !== "word") k++;
  if (k >= s.i1) return null;
  const first = s.norm.toks[k];
  if (!first || first.n0 < 0) return null;
  const offset = first.n0;
  const text = s.norm.text.slice(offset, s.offset + s.text.length);
  return { ...s, i0: k, offset, text, rawStart: first.r0 };
}

/**
 * Removes (at most three times) a leading discourse marker followed by a comma or by >= 3 words; drops a sentence that is
 * only a marker ("Got it."); keeps a bare "Okay." / "Right." (a confirm cue). Returns null for a dropped sentence.
 */
export function stripDiscourse(s: Sentence): Sentence | null {
  let cur: Sentence = s;
  const lead = firstWord(s)?.t ?? null;
  for (let round = 0; round < 3; round++) {
    const words = wordIndices(cur);
    if (words.length === 0) return null;
    const phrase = (n: number): string => words.slice(0, n).map((k) => cur.norm.toks[k]?.t ?? "").join(" ");
    // a sentence consisting only of a droppable marker
    for (const n of [2, 1]) {
      if (words.length === n && DISCOURSE_DROP.has(phrase(n))) return null;
    }
    let matched = 0;
    for (const n of [2, 1]) {
      if (words.length < n) continue;
      const p = phrase(n);
      if (NEVER_STRIP.has(p) || !DISCOURSE_MARKERS.has(p)) continue;
      const lastIdx = words[n - 1] ?? cur.i0;
      const after = cur.norm.toks[lastIdx + 1];
      const followedByComma = after?.kind === "comma";
      const restWords = words.length - n;
      if (followedByComma || restWords >= 3) { matched = n; break; }
    }
    if (matched === 0) break;
    const lastIdx = words[matched - 1] ?? cur.i0;
    const next = subSentence(cur, lastIdx + 1);
    if (!next) return null;
    cur = next;
  }
  return { ...cur, lead };
}

function wordIndices(s: Sentence): number[] {
  const out: number[] = [];
  for (let k = s.i0; k < s.i1; k++) if (s.norm.toks[k]?.kind === "word") out.push(k);
  return out;
}

/** True when the sentence's first word (before stripping) is a continuation word (A6). */
export function isContinuation(s: Sentence): boolean {
  return s.lead !== null && CONTINUATION_WORDS.has(s.lead);
}

/** The original (raw) text covering a normalised character range of a Normalized text or of a Sentence (local offsets). */
export function originalSpan(target: Normalized | Sentence, c0: number, c1: number): string {
  const norm: Normalized = "norm" in target ? target.norm : target;
  const a = "norm" in target ? target.offset + c0 : c0;
  const b = "norm" in target ? target.offset + c1 : c1;
  let r0 = Number.POSITIVE_INFINITY;
  let r1 = -1;
  for (const tk of norm.toks) {
    if (tk.n0 < 0) continue;
    if (tk.kind !== "word") continue;
    if (tk.n1 <= a || tk.n0 >= b) continue;
    if (tk.r0 < r0) r0 = tk.r0;
    if (tk.r1 > r1) r1 = tk.r1;
  }
  if (r1 < 0) return "";
  return norm.raw.slice(r0, r1);
}

const UNIT_PLURAL_ES = /(ss|sh|ch|x|z)es$/;

/** Light suffix stemming: ies->y; ations/ation/ings/ing/ed when >= 4 chars remain; plural s/es when >= 2 remain. */
export function stem(word: string): string {
  let w = word;
  if (/^\d/.test(w)) return w;
  if (w.endsWith("ies") && w.length - 3 >= 2) return w.slice(0, -3) + "y";
  for (const suf of ["ations", "ation", "ings", "ing", "ed"]) {
    if (w.endsWith(suf) && w.length - suf.length >= 4) return w.slice(0, -suf.length);
  }
  if (UNIT_PLURAL_ES.test(w) && w.length - 2 >= 2) return w.slice(0, -2);
  if (w.endsWith("s") && !w.endsWith("ss") && w.length - 1 >= 2) w = w.slice(0, -1);
  return w;
}

/** Content tokens: words minus stop words, possessives and punctuation, stemmed. Accepts raw or normalised text. */
export function contentTokens(text: string): string[] {
  const out: string[] = [];
  for (const piece of text.toLowerCase().replace(/[-–—/]/g, " ").split(/\s+/)) {
    if (!piece || piece === "<ref>") continue;
    let w = piece.replace(/'s$/, "").replace(/[^a-z0-9]/g, "");
    if (!w) continue;
    if (STOP_WORDS.has(w)) continue;
    w = stem(w);
    if (!w) continue;
    out.push(w);
  }
  return out;
}

/** Equal stems, or one a prefix of the other with the shorter >= 5 chars (cancel ~ cancellation; gps -> gp). */
export function tokenMatch(a: string, b: string): boolean {
  const x = stem(a.toLowerCase());
  const y = stem(b.toLowerCase());
  if (x === y) return true;
  const shorter = x.length <= y.length ? x : y;
  const longer = x.length <= y.length ? y : x;
  return shorter.length >= 5 && longer.startsWith(shorter);
}

/** How many of `tokens` match at least one of `against` (distinct `tokens` entries). */
export function matchCount(tokens: readonly string[], against: readonly string[]): number {
  let n = 0;
  for (const t of new Set(tokens)) if (against.some((c) => tokenMatch(t, c))) n++;
  return n;
}
