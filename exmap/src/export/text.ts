// exmap/src/export/text.ts — slugify, storyTitle, parseGwt, indent, mdEscape (design §12.1–12.4). Step-zero stubs.
import type { StoryCard } from "../core/types.js";

/** NFKD -> ASCII letters/digits -> lowercase; runs of other chars -> "-"; leading "-" removed. */
export function slugify(text: string): string {
  void text;
  throw new Error("not implemented: slugify");
}

/** First sentence of the story text, trimmed, truncated to 120 chars at a word boundary; null without a story. */
export function storyTitle(story: StoryCard | null): string | null {
  void story;
  throw new Error("not implemented: storyTitle");
}

export interface Gwt {
  given: string;
  when: string | null;
  then: string;
}

/** Given/if … when … then …; null when the text has no such structure (no invented structure). */
export function parseGwt(text: string): Gwt | null {
  void text;
  throw new Error("not implemented: parseGwt");
}

export function indent(text: string, spaces: number): string {
  void text;
  void spaces;
  throw new Error("not implemented: indent");
}

export function mdEscape(text: string): string {
  void text;
  throw new Error("not implemented: mdEscape");
}
