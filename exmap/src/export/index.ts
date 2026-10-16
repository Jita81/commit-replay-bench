// exmap/src/export/index.ts — exportFile, buildExportContext, the five mappers (design §12). All pure; same input ->
// byte-identical output. Step-zero: ExportContext and DRAFT_WATERMARK are real; the functions are stubs.
import type {
  CardId, DodReport, ExampleCard, ExportFile, ExportInput, ExportOptions, ExportRefusal, ExportResult, ExportSession,
  IsoTimestamp, QuestionCard, RevisionStamp, RuleCard, Sha256Hex, Signoff, StoryCard,
} from "../core/types.js";

export type * from "./types.js";
export { loadCatalogue, slotsFor, isCatalogueClass } from "./catalogue.js";
export type { Catalogue, Slot } from "./catalogue.js";
export { backlogItem } from "./backlog-item.js";
export { ticket, ticketMarkdown } from "./ticket.js";
export { feature } from "./feature.js";
export { evidence } from "./evidence.js";
export { slugify, storyTitle, parseGwt, indent, mdEscape } from "./text.js";

export const DRAFT_WATERMARK = "DRAFT / NOT VERIFIED";

export interface ExportContext {
  session: ExportSession;
  draft: boolean;
  verified: boolean;
  now: IsoTimestamp;
  revision: RevisionStamp;
  head: { seq: number; hash: Sha256Hex | "" };
  signoff: Signoff | null; // the active one when verified; else the last one (its status tells) or null
  dod: DodReport;
  story: StoryCard | null;
  rules: RuleCard[];
  examples: ExampleCard[];
  questions: QuestionCard[]; // live, in card_order
  examplesByRule: Map<CardId, ExampleCard[]>;
  unattachedExamples: ExampleCard[];
  options: ExportOptions; // select.exportOptions(state) ?? the §12.1 default with seq 0
  optionsHistory: ExportOptions[];
  itemId: string;
  title: string;
}

/** Refuses iff !draft && !isHumanVerified(state). */
export function buildExportContext(input: ExportInput): { ok: true; ctx: ExportContext } | ExportRefusal {
  void input;
  throw new Error("not implemented: buildExportContext");
}

export function exportFile(input: ExportInput, file: ExportFile): ExportResult | ExportRefusal {
  void input;
  void file;
  throw new Error("not implemented: exportFile");
}
