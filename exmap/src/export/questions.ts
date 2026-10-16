// exmap/src/export/questions.ts — how the export files group live questions (design §12.3 / §12.4; brief §1.11: an accepted
// question is still unanswered, and an export never says "answered" about it). Internal to the export module; the grouping
// mirrors core's DoD check 4 so the files and the gate cannot disagree.
import type { CardId, Definition, ExampleCard, QuestionCard, RuleCard, StoryCard } from "../core/types.js";
import { oneLine } from "./text.js";

export interface QuestionGroups {
  /** accepted as outstanding by a person; still unanswered (or holding an answer nobody confirmed) */
  accepted: QuestionCard[];
  /** a recorded answer (confirmed, or recorded and not yet confirmed — marked as such) */
  answered: QuestionCard[];
  /** neither answered nor accepted: only a draft can carry these */
  unresolved: QuestionCard[];
}

function isAnsweredAndConfirmed(q: QuestionCard): boolean {
  return q.answer !== null && q.status === "confirmed";
}

/** The same partition DoD check 4 uses: answered+confirmed, else accepted outstanding, else answered (unconfirmed), else unresolved. */
export function groupQuestions(questions: readonly QuestionCard[]): QuestionGroups {
  const groups: QuestionGroups = { accepted: [], answered: [], unresolved: [] };
  for (const q of questions) {
    if (isAnsweredAndConfirmed(q)) groups.answered.push(q);
    else if (q.accepted_outstanding !== null) groups.accepted.push(q);
    else if (q.answer !== null) groups.answered.push(q);
    else groups.unresolved.push(q);
  }
  return groups;
}

/** "accepted as outstanding by <by>: <reason> (no answer recorded)" — never the word "answered". */
export function acceptedNote(q: QuestionCard): string {
  const accepted = q.accepted_outstanding;
  if (!accepted) return "";
  const answer = q.answer === null ? "no answer recorded" : `an unconfirmed answer is recorded: ${oneLine(q.answer)}`;
  return `accepted as outstanding by ${accepted.by}: ${oneLine(accepted.reason)} (${answer})`;
}

/** "<answer>" plus "(answer recorded, not confirmed)" when nobody confirmed it. */
export function answeredNote(q: QuestionCard): string {
  const answer = oneLine(q.answer ?? "");
  return q.status === "confirmed" ? answer : `${answer} (answer recorded, not confirmed)`;
}

/** Live questions about `cardId`, in card_order. */
export function questionsAbout(questions: readonly QuestionCard[], cardId: CardId): QuestionCard[] {
  return questions.filter((q) => q.about_card_id === cardId);
}

/** Questions that belong to the feature as a whole: about nothing, about the story, or about a card that is not a live rule or example. */
export function featureLevelQuestions(
  questions: readonly QuestionCard[],
  story: StoryCard | null,
  rules: readonly RuleCard[],
  examples: readonly ExampleCard[],
): QuestionCard[] {
  const attached = new Set<CardId>([...rules.map((r) => r.id), ...examples.map((e) => e.id)]);
  return questions.filter((q) => q.about_card_id === null || (story !== null && q.about_card_id === story.id) || !attached.has(q.about_card_id));
}

/** Every definition on the given cards, deduplicated by term (first in card order wins), sorted by term. */
export function collectDefinitions(cards: readonly { definitions: Definition[] }[]): Definition[] {
  const byTerm = new Map<string, Definition>();
  for (const card of cards) {
    for (const d of card.definitions) if (!byTerm.has(d.term)) byTerm.set(d.term, { term: d.term, definition: d.definition });
  }
  return [...byTerm.values()].sort((a, b) => (a.term < b.term ? -1 : a.term > b.term ? 1 : 0));
}
