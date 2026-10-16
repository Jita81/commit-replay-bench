// exmap/src/export/index.ts — exportFile, buildExportContext, the five mappers (design §12). All pure; same input ->
// byte-identical output. The gate: buildExportContext refuses iff !draft && !isHumanVerified(state); a draft on a
// verified map still watermarks (the UI never offers the toggle there, but the server honours the query).
import { dodReport, isHumanVerified, select } from "../core/index.js";
import type {
  CardId, DodReport, EventId, ExampleCard, ExportFile, ExportInput, ExportOptions, ExportRefusal, ExportResult, ExportSession,
  IsoTimestamp, QuestionCard, Revision, RevisionStamp, RuleCard, Sha256Hex, Signoff, StoryCard,
} from "../core/types.js";
import { backlogItem } from "./backlog-item.js";
import { evidence } from "./evidence.js";
import { feature } from "./feature.js";
import { DRAFT_WATERMARK, slugify, storyTitle } from "./text.js";
import { ticket, ticketMarkdown } from "./ticket.js";

export type * from "./types.js";
export { loadCatalogue, slotsFor, isCatalogueClass } from "./catalogue.js";
export type { Catalogue, Slot } from "./catalogue.js";
export { backlogItem, acceptanceCriteria, exampleLine, factLine, description } from "./backlog-item.js";
export { ticket, ticketMarkdown, ticketTags, POINTS_FOR_SIZE } from "./ticket.js";
export { feature } from "./feature.js";
export { evidence } from "./evidence.js";
export { slugify, storyTitle, titleOf, parseGwt, indent, mdEscape, oneLine, DRAFT_WATERMARK } from "./text.js";
export type { Gwt } from "./text.js";
export { groupQuestions } from "./questions.js";
export type { QuestionGroups } from "./questions.js";

export const EXPORT_FILES: readonly ExportFile[] = ["crb-backlog-item.json", "ticket.json", "ticket.md", "requirement.feature", "evidence.json"];

export const CONTENT_TYPES: Readonly<Record<ExportFile, string>> = {
  "crb-backlog-item.json": "application/json",
  "ticket.json": "application/json",
  "ticket.md": "text/markdown; charset=utf-8",
  "requirement.feature": "text/plain; charset=utf-8",
  "evidence.json": "application/json",
};

export const REFUSAL_DETAIL = "export needs a human-verified requirement; add ?draft=true for a watermarked draft";

/** The item-id slug cap (design §12.1): 48 + "-draft" + "-" + 8 = 63 ≤ crb's 64. */
const SLUG_MAX = 48;
const HASH_SHORT = 8;

export interface ExportContext {
  session: ExportSession;
  draft: boolean;
  verified: boolean;
  now: IsoTimestamp;
  revision: RevisionStamp;
  head: { seq: number; hash: Sha256Hex | ""; event_id: EventId | null }; // event_id added for evidence.json's chain_head
  signoff: Signoff | null; // the active one when verified; else the last one (its status tells) or null
  dod: DodReport;
  story: StoryCard | null;
  rules: RuleCard[];
  examples: ExampleCard[];
  questions: QuestionCard[]; // live, in card_order
  examplesByRule: Map<CardId, ExampleCard[]>; // one entry per live rule, in card_order; [] for a rule without examples
  unattachedExamples: ExampleCard[]; // rule_id null or naming a card that is not a live rule
  options: ExportOptions; // select.exportOptions(state) ?? the §12.1 default with seq 0
  optionsHistory: ExportOptions[];
  itemId: string;
  title: string;
}

export function defaultExportOptions(now: IsoTimestamp): ExportOptions {
  return { capability_class: "unclassified", kind: "code", size_estimate: "unsized", facts: [], by: "", seq: 0, at: now };
}

/** `slugify(baseTitle)` cut to 48 chars without a trailing "-" (or "exmap"), "-draft" on drafts, then "-<hash8>" of the revision. */
export function itemIdFor(baseTitle: string, draft: boolean, revisionHash: Sha256Hex): string {
  const slug = slugify(baseTitle).slice(0, SLUG_MAX).replace(/-+$/, "") || "exmap";
  return `${slug}${draft ? "-draft" : ""}-${revisionHash.slice(0, HASH_SHORT)}`;
}

function gateStatus(current: Revision, last: Signoff | null): ExportRefusal["signoff"] {
  if (last === null) return { status: "none" };
  if (last.status === "invalidated") {
    const signoff: ExportRefusal["signoff"] = { status: "invalidated", id: last.id, revision: last.revision };
    if (last.invalidated) signoff.invalidated_by_event_id = last.invalidated.by_event_id;
    return signoff;
  }
  if (last.revision.hash !== current.hash) return { status: "active_but_stale", id: last.id, revision: last.revision };
  return { status: "active_but_dod_failed", id: last.id, revision: last.revision };
}

/** Refuses iff !draft && !isHumanVerified(state). */
export function buildExportContext(input: ExportInput): { ok: true; ctx: ExportContext } | ExportRefusal {
  const { session, state, draft, now } = input;
  const verified = isHumanVerified(state);
  const dod = dodReport(state);
  const current = select.currentRevision(state);
  const last = select.lastSignoff(state);
  if (!draft && !verified) {
    return { ok: false, reason: "NOT_HUMAN_VERIFIED", detail: REFUSAL_DETAIL, checks: dod, signoff: gateStatus(current, last) };
  }

  const story = select.story(state);
  const rules = select.cardsByKind(state, "rule");
  const examples = select.cardsByKind(state, "example");
  const questions = select.cardsByKind(state, "question");
  const examplesByRule = new Map<CardId, ExampleCard[]>();
  for (const rule of rules) examplesByRule.set(rule.id, []);
  const unattachedExamples: ExampleCard[] = [];
  for (const example of examples) {
    const bucket = example.rule_id === null ? undefined : examplesByRule.get(example.rule_id);
    if (bucket) bucket.push(example);
    else unattachedExamples.push(example);
  }

  const baseTitle = storyTitle(story) ?? (session.title.trim() || "Untitled requirement");
  const title = draft ? `[${DRAFT_WATERMARK}] ${baseTitle}` : baseTitle;

  return {
    ok: true,
    ctx: {
      session,
      draft,
      verified,
      now,
      revision: { seq: current.seq, hash: current.hash },
      head: { seq: state.head.seq, hash: state.head.hash, event_id: state.head.event_id },
      signoff: verified ? select.activeSignoff(state) : last,
      dod,
      story,
      rules,
      examples,
      questions,
      examplesByRule,
      unattachedExamples,
      options: select.exportOptions(state) ?? defaultExportOptions(now),
      optionsHistory: [...state.export_options],
      itemId: itemIdFor(baseTitle, draft, current.hash),
      title,
    },
  };
}

const json = (value: unknown): string => JSON.stringify(value, null, 2) + "\n";

export function exportFile(input: ExportInput, file: ExportFile): ExportResult | ExportRefusal {
  const built = buildExportContext(input);
  if (!built.ok) return built;
  const ctx = built.ctx;
  const filename = `${ctx.draft ? "DRAFT-" : ""}${file}`;
  const content_type = CONTENT_TYPES[file];
  switch (file) {
    case "crb-backlog-item.json":
      return { ok: true, filename, content_type, body: json(backlogItem(ctx)) };
    case "ticket.json":
      return { ok: true, filename, content_type, body: json(ticket(ctx)) };
    case "ticket.md":
      return { ok: true, filename, content_type, body: ticketMarkdown(ctx) };
    case "requirement.feature":
      return { ok: true, filename, content_type, body: feature(ctx) };
    case "evidence.json":
      return { ok: true, filename, content_type, body: json(evidence(ctx)) };
    default: {
      const unknown: never = file;
      throw new Error(`unknown export file: ${String(unknown)}`);
    }
  }
}
