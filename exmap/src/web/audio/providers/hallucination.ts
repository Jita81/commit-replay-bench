// exmap/src/web/audio/providers/hallucination.ts — the hallucination gate (design §7.5): a pure function of
// (text, durationMs, peakRmsDb) that only drops or keeps. Nothing is ever rewritten. Single words (okay, yes, you,
// bye) are never in the table — "Okay." and "Yes." are Confirm cues.
export const KNOWN_HALLUCINATIONS: ReadonlySet<string> = new Set([
  "thank you",
  "thanks for watching",
  "thank you for watching",
  "thank you so much",
  "subtitles by the amara org community",
  "the end",
  "blank audio",
]);

export const HALLUCINATION_QUIET_DB = -35;
export const HALLUCINATION_SHORT_MS = 1000;

/** Lower-cased, punctuation stripped, whitespace collapsed. */
export function normalizeTranscript(text: string): string {
  return text
    .toLowerCase()
    .replace(/[\p{P}\p{S}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Empty after stripping punctuation, whitespace and bracketed/parenthesised tokens, or made only of such tokens. */
function isNonLexical(text: string): boolean {
  const stripped = text
    .replace(/\[[^\]]*\]/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/[\p{P}\p{S}\s]+/gu, "");
  return stripped.length === 0;
}

function isRepeatedToken(norm: string): boolean {
  const tokens = norm.split(" ").filter((t) => t.length > 0);
  if (tokens.length < 5) return false;
  const first = tokens[0];
  return tokens.every((t) => t === first);
}

export function isLikelyHallucination(text: string, ctx: { durationMs: number; peakRmsDb: number }): boolean {
  if (isNonLexical(text)) return true;
  const norm = normalizeTranscript(text);
  if (norm.length === 0) return true;
  if (isRepeatedToken(norm)) return true;
  if (KNOWN_HALLUCINATIONS.has(norm) && ctx.peakRmsDb < HALLUCINATION_QUIET_DB && ctx.durationMs < HALLUCINATION_SHORT_MS) return true;
  return false;
}
