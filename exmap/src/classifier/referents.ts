// exmap/src/classifier/referents.ts — parseReferent, maskReferents, resolveReferent, linkRule, linkAbout, askTarget
// (design §6.3). A referent is what the speaker points at ("that example", "the GP one", "that limit", "it"); resolution
// maps it to one index card, a list of candidates to ask about, or nothing — never a guess.
import type { CardDraft, CardIndexEntry, CardKind, ClassifierClarification, ClassifierInput, ClassifierOperation, Intent, LastProposalRef } from "../core/types.js";
import { MAX_CANDIDATES, RECENCY_WINDOW, TOPIC_MIN_SCORE } from "./constants.js";
import { INTERROGATIVE_OPENERS, REFERENT_PATTERNS, STOP_WORDS } from "./cues.js";
import { contentTokens, matchCount, normalizeText } from "./normalize.js";
import { CHOICE } from "./schema.js";

export interface Referent {
  kind: CardKind | null;
  topic: { text: string; named: boolean } | null;
  ordinal: 1 | 2 | 3 | 4 | "last" | "previous" | null;
  bare: boolean;
  span: [number, number];
}

interface Word { w: string; start: number; end: number; commaAfter: boolean; qAfter: boolean }

function words(text: string): Word[] {
  const out: Word[] = [];
  const re = /\S+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    let w = m[0];
    let end = m.index + w.length;
    let commaAfter = false;
    let qAfter = false;
    while (w.endsWith(",") || w.endsWith("?")) {
      if (w.endsWith(",")) commaAfter = true; else qAfter = true;
      w = w.slice(0, -1);
      end--;
    }
    if (!w) continue;
    out.push({ w, start: m.index, end, commaAfter, qAfter });
  }
  return out;
}

const { determiners: DET, kindWords: KIND, noKindWords: NOKIND, ordinals: ORD, targetVerbs: VERBS, unitNouns: UNITS, notReferentPhrases } = REFERENT_PATTERNS;

function excludedSpans(text: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (const p of notReferentPhrases) {
    let from = 0;
    for (;;) {
      const idx = text.indexOf(p, from);
      if (idx < 0) break;
      out.push([idx, idx + p.length]);
      from = idx + 1;
    }
  }
  return out;
}

function isDigits(w: string): boolean {
  return /^\d+(\.\d+)?$/.test(w);
}

function tryAt(ws: Word[], i: number, excluded: Array<[number, number]>): { ref: Referent; endIdx: number } | null {
  const cur = ws[i];
  if (!cur) return null;
  const w = cur.w;
  const inExcluded = excluded.some(([a, b]) => cur.start >= a && cur.end <= b);
  const prev = ws[i - 1];
  const join = (k: number): boolean => k > i && !ws.slice(i, k).some((x) => x.commaAfter || x.qAfter);
  const make = (ref: Omit<Referent, "span">, endIdx: number): { ref: Referent; endIdx: number } => ({
    ref: { ...ref, span: [cur.start, ws[endIdx]?.end ?? cur.end] },
    endIdx,
  });

  // (1) the story
  if (w === "the" && ws[i + 1]?.w === "story" && join(i + 1)) return make({ kind: "story", topic: null, ordinal: null, bare: false }, i + 1);

  if (DET.has(w)) {
    if (inExcluded) return null;
    // "use this example" / "take this one" is P2 (new content), not a referent
    if (w === "this" && prev && (prev.w === "use" || prev.w === "take")) return null;
    // (2) <det> <ordinal>? <kind-word> (about <topic>)?
    let j = i + 1;
    let ordinal: Referent["ordinal"] = null;
    const ordWord = ws[j]?.w ?? "";
    if (ws[j] && ordWord in ORD && join(j)) { ordinal = ORD[ordWord] ?? null; j++; }
    const nounWord = ws[j]?.w ?? "";
    if (ws[j] && (nounWord in KIND || NOKIND.has(nounWord)) && join(j)) {
      const kind = KIND[nounWord] ?? null;
      let k = j;
      let topic: Referent["topic"] = null;
      if (ws[k + 1]?.w === "about" && join(k + 1)) {
        const collected: string[] = [];
        let t = k + 2;
        while (ws[t] && collected.length < 6) {
          collected.push(ws[t]!.w);
          if (ws[t]!.commaAfter || ws[t]!.qAfter) break;
          t++;
        }
        if (collected.length > 0) { topic = { text: collected.join(" "), named: true }; k = Math.min(t, ws.length - 1); }
      }
      const bare = kind === null && topic === null && ordinal === null;
      return make({ kind, topic, ordinal, bare }, k);
    }
    // (3) the <adj>+ (example|rule|question|one)
    if (w === "the") {
      const adjectives: string[] = [];
      let a = i + 1;
      while (ws[a] && adjectives.length < 3) {
        const aw = ws[a]!.w;
        if (aw in KIND || NOKIND.has(aw) || (STOP_WORDS.has(aw) && !isDigits(aw)) || !join(a)) break;
        adjectives.push(aw);
        a++;
      }
      const tail = ws[a]?.w ?? "";
      if (adjectives.length > 0 && ws[a] && (tail in KIND || tail === "one" || tail === "ones") && join(a)) {
        return make({ kind: KIND[tail] ?? null, topic: { text: adjectives.join(" "), named: true }, ordinal: null, bare: false }, a);
      }
    }
    // (5) <det> <adj>* <noun> after a target verb / an interrogative opener / at the sentence start -> paraphrase topic
    const allowed = i === 0 || (prev !== undefined && VERBS.has(prev.w)) || (i === 1 && prev !== undefined && prev.w !== "when" && INTERROGATIVE_OPENERS.has(prev.w));
    if (allowed) {
      const collected: string[] = [];
      let c = i + 1;
      while (ws[c] && collected.length < 3) {
        const cw = ws[c]!.w;
        if (cw in KIND || NOKIND.has(cw) || STOP_WORDS.has(cw) || !join(c)) break;
        collected.push(cw);
        c++;
      }
      const isValue = collected.length > 0 && isDigits(collected[0]!) && (collected.length === 1 || (collected.length === 2 && UNITS.has(collected[1]!)));
      if (collected.length > 0 && !isValue) {
        while (collected.length > 0 && isDigits(collected[collected.length - 1]!)) collected.pop();
        if (collected.length > 0 && !(collected.length === 1 && isDigits(collected[0]!))) {
          return make({ kind: null, topic: { text: collected.join(" "), named: false }, ordinal: null, bare: false }, i + collected.length);
        }
      }
    }
    // (6) bare demonstrative: that one | this one | that | this | those | these, followed by nothing / a stop word / a number / a verb
    if (w === "that" || w === "this" || w === "those" || w === "these") {
      let k = i;
      if (ws[i + 1]?.w === "one" && join(i + 1)) k = i + 1;
      const next = ws[k + 1];
      const boundary = ws[k]!.commaAfter || ws[k]!.qAfter;
      const ok = next === undefined || boundary || STOP_WORDS.has(next.w) || isDigits(next.w) || /(ed|s)$/.test(next.w);
      if (ok) return make({ kind: null, topic: null, ordinal: null, bare: true }, k);
    }
    return null;
  }
  // "it" only after a change/remove/undo verb or before "to" / "back" / "out"
  if (w === "it") {
    if (inExcluded) return null;
    const next = ws[i + 1]?.w ?? "";
    if ((prev && VERBS.has(prev.w)) || next === "to" || next === "back" || next === "out") {
      return make({ kind: null, topic: null, ordinal: null, bare: true }, i);
    }
    return null;
  }
  // (7) ordinal only: number N / option N
  if ((w === "number" || w === "option") && ws[i + 1] && /^[1-4]$/.test(ws[i + 1]!.w) && join(i + 1)) {
    const n = Number(ws[i + 1]!.w) as 1 | 2 | 3 | 4;
    return make({ kind: null, topic: null, ordinal: n, bare: false }, i + 1);
  }
  return null;
}

/** Every referent of a normalised sentence, in order of position. */
export function parseReferents(text: string): Referent[] {
  const t = text.toLowerCase();
  const ws = words(t);
  const excluded = excludedSpans(t);
  const out: Referent[] = [];
  let i = 0;
  while (i < ws.length) {
    const r = tryAt(ws, i, excluded);
    if (r) { out.push(r.ref); i = r.endIdx + 1; continue; }
    i++;
  }
  return out;
}

/** The first referent by position, or null. */
export function parseReferent(text: string): Referent | null {
  return parseReferents(text)[0] ?? null;
}

/** The sentence with every referent span replaced by "<ref>". */
export function maskReferents(text: string): string {
  const refs = parseReferents(text);
  let out = text;
  for (const r of [...refs].reverse()) out = `${out.slice(0, r.span[0])}<ref>${out.slice(r.span[1])}`;
  return out;
}

/* ───────────── recency ───────────── */

export function recentIds(input: ClassifierInput): Set<string> {
  return new Set(input.recent.slice(-RECENCY_WINDOW).map((u) => u.id));
}

export function isRecent(card: CardIndexEntry, input: ClassifierInput): boolean {
  return card.last_utterance_id !== null && recentIds(input).has(card.last_utterance_id);
}

export function inWindow(ref: LastProposalRef | null, input: ClassifierInput): ref is LastProposalRef {
  return ref !== null && recentIds(input).has(ref.utterance_id);
}

/** Why the last interpretation cannot be the one a bare "no" rejects (it is not the last rejectable). */
export function lastNotRejectable(lp: LastProposalRef): string {
  if (lp.status === "confirmed") return "has been confirmed";
  if (lp.op === "confirm") return "was a confirmation";
  return "has changed since";
}

export function bySeqDesc(cards: CardIndexEntry[]): CardIndexEntry[] {
  return [...cards].sort((a, b) => b.seq - a.seq);
}

/* ───────────── resolution ───────────── */

export type Resolution =
  | { kind: "resolved"; card: CardIndexEntry; how: string }
  | { kind: "ambiguous"; candidates: CardIndexEntry[]; why: string }
  | { kind: "none"; why: string };

const tokenCache = new WeakMap<CardIndexEntry, string[]>();
export function cardTokens(card: CardIndexEntry): string[] {
  let t = tokenCache.get(card);
  if (!t) {
    t = contentTokens(normalizeText(card.text).text);
    tokenCache.set(card, t);
  }
  return t;
}

function topicScore(topic: string, card: CardIndexEntry): number {
  const tt = [...new Set(contentTokens(normalizeText(topic).text))];
  if (tt.length === 0) return 0;
  return matchCount(tt, cardTokens(card)) / tt.length;
}

function kindLabel(kind: CardKind | null | undefined): string {
  return kind ?? "card";
}

/** Resolves a referent against the index (design §6.3, steps 0–8); first hit wins. */
export function resolveReferent(ref: Referent | null, input: ClassifierInput, want: { kind?: CardKind | undefined; exclude?: readonly string[] | undefined }): Resolution {
  const kind: CardKind | undefined = ref?.kind ?? want.kind;
  const exclude = new Set(want.exclude ?? []);
  let pool = input.cards.filter((c) => !exclude.has(c.id));
  if (kind !== "story") pool = pool.filter((c) => c.kind !== "story");
  if (kind) pool = pool.filter((c) => c.kind === kind);
  const k = kindLabel(kind);
  if (pool.length === 0) return { kind: "none", why: `There is no ${k} on the map.` };
  // (3) last-interpretation shortcut
  if (ref === null || ref.bare) {
    const lp = input.last_proposal;
    if (inWindow(lp, input)) {
      const hit = pool.filter((c) => lp.card_ids.includes(c.id));
      if (hit.length === 1 && hit[0]) return { kind: "resolved", card: hit[0], how: "the last interpretation" };
    }
  }
  // (4) named topic
  if (ref?.topic?.named) {
    const scored = pool.map((c) => ({ c, s: topicScore(ref.topic!.text, c) })).filter((x) => x.s >= TOPIC_MIN_SCORE).sort((a, b) => b.s - a.s || b.c.seq - a.c.seq);
    if (scored.length === 1 && scored[0]) return { kind: "resolved", card: scored[0].c, how: `named '${ref.topic.text}'` };
    if (scored.length > 1) {
      const best = scored[0]!;
      const tied = scored.filter((x) => x.s === best.s);
      if (tied.length === 1) return { kind: "resolved", card: best.c, how: `named '${ref.topic.text}'` };
      return { kind: "ambiguous", candidates: tied.map((x) => x.c).slice(0, MAX_CANDIDATES), why: `several ${k}s match '${ref.topic.text}'` };
    }
    return { kind: "ambiguous", candidates: bySeqDesc(pool).slice(0, MAX_CANDIDATES), why: `no ${k} about '${ref.topic.text}'` };
  }
  // (5) paraphrase topic
  if (ref?.topic && !ref.topic.named) {
    const scored = pool.map((c) => ({ c, s: topicScore(ref.topic!.text, c) })).filter((x) => x.s >= TOPIC_MIN_SCORE).sort((a, b) => b.s - a.s || b.c.seq - a.c.seq);
    if (scored.length === 1 && scored[0]) return { kind: "resolved", card: scored[0].c, how: `matched '${ref.topic.text}'` };
    if (scored.length > 1) {
      const best = scored[0]!;
      const tied = scored.filter((x) => x.s === best.s);
      if (tied.length === 1) return { kind: "resolved", card: best.c, how: `matched '${ref.topic.text}'` };
      return { kind: "ambiguous", candidates: tied.map((x) => x.c).slice(0, MAX_CANDIDATES), why: `several ${k}s match '${ref.topic.text}'` };
    }
  }
  // (6) ordinal
  if (ref?.ordinal !== null && ref?.ordinal !== undefined) {
    const sorted = bySeqDesc(pool);
    if (ref.ordinal === "last" && sorted[0]) return { kind: "resolved", card: sorted[0], how: "the most recent" };
    if (ref.ordinal === "previous" && sorted[1]) return { kind: "resolved", card: sorted[1], how: "the one before" };
    if (typeof ref.ordinal === "number") return { kind: "ambiguous", candidates: sorted.slice(0, MAX_CANDIDATES), why: "which number" };
  }
  // (7) the only one
  if (pool.length === 1 && pool[0]) return { kind: "resolved", card: pool[0], how: `the only ${k}` };
  // (8) recency
  const touched = bySeqDesc(pool.filter((c) => isRecent(c, input)));
  if (touched.length === 1 && touched[0]) return { kind: "resolved", card: touched[0], how: `the ${touched[0].kind} mentioned most recently` };
  if (touched.length >= 2) {
    const top = touched[0]!;
    if (top.last_speaker !== null && top.last_speaker === input.utterance.speaker) {
      return { kind: "resolved", card: top, how: `the ${top.kind} you just gave` };
    }
    return { kind: "ambiguous", candidates: touched.slice(0, MAX_CANDIDATES), why: `two ${k}s were mentioned recently` };
  }
  return { kind: "ambiguous", candidates: bySeqDesc(pool).slice(0, MAX_CANDIDATES), why: `nothing recent of that kind` };
}

/* ───────────── links ───────────── */

function draftTokens(draft: { text: string }): string[] {
  return contentTokens(normalizeText(draft.text).text);
}

/** example -> rule: best token overlap (>= 2, strictly best); else the rule touched most recently in the window; else the only rule; else null. */
export function linkRule(draft: CardDraft, input: ClassifierInput): string | null {
  const rules = input.cards.filter((c) => c.kind === "rule");
  if (rules.length === 0) return null;
  const dt = draftTokens(draft);
  const scored = rules.map((c) => ({ c, n: matchCount(dt, cardTokens(c)) })).sort((a, b) => b.n - a.n || b.c.seq - a.c.seq);
  const best = scored[0]!;
  if (best.n >= 2 && !scored.some((x) => x !== best && x.n === best.n)) return best.c.id;
  const touched = bySeqDesc(rules.filter((c) => isRecent(c, input)));
  if (touched[0]) return touched[0].id;
  if (rules.length === 1 && rules[0]) return rules[0].id;
  return null;
}

/** question -> card: best overlap over rules and examples (ties rule-first, then recency); else the last proposal's single card in the window; else null. */
export function linkAbout(draft: CardDraft, input: ClassifierInput): string | null {
  const cards = input.cards.filter((c) => c.kind === "rule" || c.kind === "example");
  const dt = draftTokens(draft);
  const rank = (c: CardIndexEntry): number => (c.kind === "rule" ? 1 : 0);
  const scored = cards.map((c) => ({ c, n: matchCount(dt, cardTokens(c)) })).sort((a, b) => b.n - a.n || rank(b.c) - rank(a.c) || b.c.seq - a.c.seq);
  const best = scored[0];
  if (best && best.n >= 2) return best.c.id;
  const lp = input.last_proposal;
  if (inWindow(lp, input)) {
    const live = lp.card_ids.filter((id) => input.cards.some((c) => c.id === id));
    if (live.length === 1 && live[0]) return live[0];
  }
  return null;
}

/* ───────────── labels and asking ───────────── */

/** "<title> (<kind>, <speaker>)" — the speaker is the label a person assigned, or the lane / "typed" when none was. */
export function candidateLabel(card: CardIndexEntry, input: ClassifierInput): string {
  return `${titleOf(card)} (${card.kind}, ${speakerOf(card, input)})`;
}

export function titleOf(card: CardIndexEntry): string {
  const text = card.text.replace(/\s+/g, " ").trim();
  if (text.length <= 60) return text;
  const head = card.title.length > 0 ? card.title : text.slice(0, 60);
  const cut = head.lastIndexOf(" ");
  return `${(cut > 20 ? head.slice(0, cut) : head).trimEnd()}…`;
}

export function speakerOf(card: CardIndexEntry, input: ClassifierInput): string {
  if (card.last_speaker !== null) return card.last_speaker;
  if (card.last_utterance_id === null) return "by hand";
  const u = input.recent.find((r) => r.id === card.last_utterance_id) ?? (input.utterance.id === card.last_utterance_id ? input.utterance : null);
  if (u) return u.lane === "manual" ? "typed" : `${u.lane}, no speaker label`;
  return "no speaker label";
}

export type AskResult =
  | { kind: "clarification"; clarification: ClassifierClarification; candidates: CardIndexEntry[] }
  | { kind: "none"; why: string };

/** Replaces the target field of an operation with "$choice" or a concrete card (interpretation.reject takes the card's proposal). */
export function withTarget(op: ClassifierOperation, target: string, card?: CardIndexEntry): ClassifierOperation {
  switch (op.kind) {
    case "card.update": return { ...op, card_id: target };
    case "card.remove": return { ...op, card_id: target };
    case "card.replace": return { ...op, card_id: target };
    case "definition.refine": return { ...op, card_id: target };
    case "interpretation.reject": return { ...op, proposal_id: card ? card.proposal_id ?? target : target };
    case "confirm": return { ...op, card_ids: [target] };
    case "card.create": return op.card.kind === "example" ? { ...op, card: { ...op.card, rule_id: target } } : { ...op, card: { ...op.card, about_card_id: target } };
    case "undo": return op;
  }
}

/**
 * Turns an ambiguous / none resolution into a clarification: >= 2 candidates -> choose_target with "$choice" in the
 * operation; exactly 1 -> confirm_intent bound to it ("Did you mean to <verb> <label>? (<why>)"); none -> a none result.
 */
export function askTarget(res: Resolution, op: ClassifierOperation, _intent: Intent, verb: string, input: ClassifierInput, opts: { question?: string; kind?: CardKind | null } = {}): AskResult {
  if (res.kind === "none") return { kind: "none", why: res.why };
  if (res.kind === "resolved") {
    const label = candidateLabel(res.card, input);
    return {
      kind: "clarification",
      clarification: { kind: "confirm_intent", question: `Did you mean to ${verb} ${label}?`, candidates: [], pending_operations: [withTarget(op, res.card.id, res.card)] },
      candidates: [res.card],
    };
  }
  const cands = res.candidates.slice(0, MAX_CANDIDATES);
  if (cands.length >= 2) {
    const kinds = new Set(cands.map((c) => c.kind));
    const what = opts.kind !== undefined ? kindLabel(opts.kind) : kinds.size === 1 ? kindLabel(cands[0]!.kind) : "card";
    const parts = cands.map((c, i) => `(${i + 1}) ${candidateLabel(c, input)}`);
    const list = parts.length === 2 ? `${parts[0]}, or ${parts[1]}` : `${parts.slice(0, -1).join(", ")}, or ${parts[parts.length - 1]}`;
    const question = opts.question ?? `Which ${what} do you mean: ${list}?`;
    return {
      kind: "clarification",
      clarification: { kind: "choose_target", question, candidates: cands.map((c) => ({ card_id: c.id, label: candidateLabel(c, input) })), pending_operations: [withTarget(op, CHOICE)] },
      candidates: cands,
    };
  }
  const only = cands[0];
  if (!only) return { kind: "none", why: res.why };
  const label = candidateLabel(only, input);
  const question = `Did you mean to ${verb} ${label}? (${res.why})`;
  return {
    kind: "clarification",
    clarification: { kind: "confirm_intent", question, candidates: [], pending_operations: [withTarget(op, only.id, only)] },
    candidates: [only],
  };
}
