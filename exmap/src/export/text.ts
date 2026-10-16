// exmap/src/export/text.ts — slugify, storyTitle, parseGwt, indent, mdEscape (design §12.1–12.4). Pure string helpers;
// nothing here reads state. DRAFT_WATERMARK lives here (not in index.ts) so the mappers can import it without a cycle.
import type { StoryCard } from "../core/types.js";

export const DRAFT_WATERMARK = "DRAFT / NOT VERIFIED";

/**
 * NFKD -> ASCII letters/digits -> lowercase; runs of other chars -> "-"; leading "-" removed. Combining marks left by the
 * NFKD decomposition are dropped first so "café" slugs to "cafe" rather than "cafe-". A trailing "-" is kept (the item-id
 * rule of §12.1 strips it after the 48-char cut).
 */
export function slugify(text: string): string {
  const ascii = text.normalize("NFKD").replace(/\p{M}+/gu, "");
  return ascii.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "");
}

/**
 * The first sentence of `text` (split at ". ", ".\n" or "\n"), trimmed, without its full stop, truncated to `max` chars at
 * a word boundary (no ellipsis is added, as §12.1 says; the full text is always elsewhere in the same export). "" when the
 * sentence is empty after trimming.
 */
export function titleOf(text: string, max: number): string {
  const normalised = text.replace(/\r\n/g, "\n");
  let end = normalised.length;
  for (const separator of [". ", ".\n", "\n"]) {
    const at = normalised.indexOf(separator);
    if (at !== -1 && at < end) end = at;
  }
  let first = normalised.slice(0, end).trim().replace(/\.$/, "").trim();
  if (first.length > max) {
    const cut = first.lastIndexOf(" ", max);
    first = (cut > 0 ? first.slice(0, cut) : first.slice(0, max)).trim();
  }
  return first.replace(/[,;:]+$/, "").trim();
}

/** First sentence of the story text, trimmed, truncated to 120 chars at a word boundary; null without a story (or an empty title). */
export function storyTitle(story: StoryCard | null): string | null {
  if (!story) return null;
  return titleOf(story.text, 120) || null;
}

/** Card text collapsed to one line (for list items, step lines and comments). */
export function oneLine(text: string): string {
  return text.replace(/\s*\n\s*/g, " ").replace(/[ \t]+/g, " ").trim();
}

export interface Gwt {
  given: string;
  when: string | null;
  then: string;
}

function keywordAt(text: string, word: string): { start: number; end: number } | null {
  const match = new RegExp(`\\b${word}\\b`, "i").exec(text);
  return match ? { start: match.index, end: match.index + match[0].length } : null;
}

/** Strips a leading "," / ";" / ":" / "and" left after a keyword, and trailing separators (or a dangling "and") before the next one. */
function clause(raw: string): string {
  return raw
    .replace(/^[\s,;:]+/, "")
    .replace(/^and\b[\s,;:]*/i, "")
    .replace(/^[\s,;:]+/, "")
    .replace(/[\s,;:]+$/, "")
    .replace(/[\s,;:]*\band$/i, "")
    .replace(/[\s,;:]+$/, "")
    .trim();
}

/**
 * Given/if … when … then …; null when the text has no such structure (no invented structure). The whitespace-collapsed
 * text must open with "given", "if" or "when"; it is split at the first standalone "when" (only after a given/if opener,
 * and only when it precedes "then") and at the first standalone "then" (required). The opener and a leading ","/"and" after
 * each keyword are stripped; a trailing full stop is removed from `then`. A "when" opener fills `given` (the Gwt shape has
 * no optional given; a "When X, then Y" example is a conditional, which Gherkin states as Given X / Then Y).
 */
export function parseGwt(text: string): Gwt | null {
  const collapsed = text.replace(/\s+/g, " ").trim();
  const opener = /^(given|if|when)(?=[\s,;:]|$)/i.exec(collapsed);
  if (!opener) return null;
  const kind = opener[1]!.toLowerCase();
  const rest = collapsed.slice(opener[0].length);
  const thenAt = keywordAt(rest, "then");
  if (!thenAt) return null;
  let whenAt = kind === "when" ? null : keywordAt(rest, "when");
  if (whenAt && whenAt.start > thenAt.start) whenAt = null;
  const given = clause(rest.slice(0, whenAt ? whenAt.start : thenAt.start));
  const when = whenAt ? clause(rest.slice(whenAt.end, thenAt.start)) : null;
  const then = clause(rest.slice(thenAt.end)).replace(/\.$/, "").trim();
  if (!given || !then) return null;
  if (whenAt && !when) return null;
  return { given, when, then };
}

/** A line Gherkin would read as structure (a keyword line, a step, a tag, a table row, a doc string fence). */
const GHERKIN_LINE = /^\s*(?:(?:Feature|Rule|Background|Scenario Outline|Scenario Template|Scenario|Example|Examples|Scenarios)\s*:|(?:Given|When|Then|And|But|\*)(?:\s|$)|[@|]|"""|```)/;

/**
 * Free text for a Gherkin description: every line that Gherkin would parse as structure is written as a comment
 * (`# <line>`), so card text can never add a scenario, a step or a tag to the file (design §12.4: no invented steps).
 */
export function gherkinDescription(text: string): string {
  return text
    .split("\n")
    .map((line) => (GHERKIN_LINE.test(line) ? `# ${line.trim()}` : line))
    .join("\n");
}

/** Prefixes every non-empty line with `spaces` spaces; empty lines stay empty (no trailing whitespace). */
export function indent(text: string, spaces: number): string {
  const pad = " ".repeat(spaces);
  return text
    .split("\n")
    .map((line) => (line.length > 0 ? pad + line : line))
    .join("\n");
}

/**
 * Neutralises a leading "#" / ">" / "-" (per line), backticks, "<" (raw HTML and autolinks) and "](" (an inline link
 * target such as javascript:) in card text; everything else is left as typed and renders as typed.
 */
export function mdEscape(text: string): string {
  return text
    .split("\n")
    .map((line) => line.replace(/^(\s*)([#>-])/, "$1\\$2"))
    .join("\n")
    .replace(/`/g, "\\`")
    .replace(/</g, "\\<")
    .replace(/\]\(/g, "]\\(");
}
