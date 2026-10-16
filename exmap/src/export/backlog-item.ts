// exmap/src/export/backlog-item.ts — crb-backlog-item.json: crb's BacklogItem (design §12.2, brief §3). Pure over the
// ExportContext; same context -> byte-identical item.
import type { BacklogItem, Card, Definition, ExampleCard, ExportFact } from "../core/types.js";
import type { ExportContext } from "./index.js";
import { collectDefinitions } from "./questions.js";
import { oneLine, parseGwt } from "./text.js";

/** `slot: text` — the line crb reads as a structural fact when `slot` is in the item's class catalogue. */
export function factLine(fact: ExportFact): string {
  return `${fact.slot}: ${fact.text}`;
}

/** `Given <g>, when <w>, then <t>` when the example parses (`when` omitted if null), else `Example: <text>` verbatim (one line). */
export function exampleLine(example: ExampleCard): string {
  const gwt = parseGwt(example.text);
  if (!gwt) return `Example: ${oneLine(example.text)}`;
  return gwt.when === null ? `Given ${gwt.given}, then ${gwt.then}` : `Given ${gwt.given}, when ${gwt.when}, then ${gwt.then}`;
}

/** Live examples in card_order, then the export facts. Shared by the backlog item and the ticket. */
export function acceptanceCriteria(ctx: ExportContext): string[] {
  return [...ctx.examples.map(exampleLine), ...ctx.options.facts.map(factLine)];
}

/** Every live card in card_order (story, rules, examples, questions). */
export function liveCards(ctx: ExportContext): Card[] {
  const cards: Card[] = [];
  if (ctx.story) cards.push(ctx.story);
  cards.push(...ctx.rules, ...ctx.examples, ...ctx.questions);
  return cards;
}

/** Definitions of every live card, deduplicated by term and sorted. */
export function definitionsOf(ctx: ExportContext): Definition[] {
  return collectDefinitions(liveCards(ctx));
}

/** Story text; then "Rules:" with one line per live rule when any; then "Definitions:" when any live card defines a term. */
export function description(ctx: ExportContext): string {
  const parts: string[] = [ctx.story ? ctx.story.text : "No story card is recorded in this session."];
  if (ctx.rules.length > 0) parts.push(`Rules:\n${ctx.rules.map((r) => `- ${oneLine(r.text)}`).join("\n")}`);
  const definitions = definitionsOf(ctx);
  if (definitions.length > 0) parts.push(`Definitions:\n${definitions.map((d) => `- ${d.term}: ${d.definition}`).join("\n")}`);
  return parts.join("\n\n");
}

export function backlogItem(ctx: ExportContext): BacklogItem {
  const labels: Record<string, string> = {
    exmap_session: ctx.session.id,
    exmap_revision: ctx.revision.hash,
    exmap_signoff: ctx.verified && ctx.signoff ? ctx.signoff.id : "",
    exmap_export_options_seq: String(ctx.options.seq),
  };
  if (ctx.draft) labels.exmap_draft = "true";
  if (ctx.verified && ctx.signoff) {
    labels.exmap_reviewer = ctx.signoff.reviewer.name;
    labels.exmap_signed_at = ctx.signoff.at;
  }
  return {
    id: ctx.itemId,
    title: ctx.title,
    kind: ctx.options.kind,
    description: description(ctx),
    acceptance_criteria: acceptanceCriteria(ctx),
    capability_class: ctx.options.capability_class,
    size_estimate: ctx.options.size_estimate,
    structural_facts: ctx.options.facts.map(factLine),
    depends_on: [],
    level: "L1",
    supersedes: "", // chaining exports by revision is a documented next step (design §16)
    registered: ctx.now,
    labels,
  };
}
