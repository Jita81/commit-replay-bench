// exmap/src/core/shape.ts — step (0) of apply() (design §5.4): the command's shape. Types, enums and unknown keys
// (BAD_SHAPE naming the path), text normalisation (trim, CRLF -> LF), the 2-dp confidence rule, definitions. Core copies
// declared fields only: every value the engine stores is rebuilt here from validated fields, never spread from input.
// State-dependent checks (ids, liveness, kinds) live in apply.ts.
import { REFUSAL } from "./refusals.js";
import type {
  Amendment, CardPatch, ClarificationAnswer, ClassifierStamp, Command, Definition, DodReport, ExportFact, ExportOptionsInput,
  Intent, NewCard, Operation, OperationTemplate, Proposal, RefusalCode, Utterance,
} from "./types.js";

export class Refusal {
  constructor(
    readonly reason: RefusalCode,
    readonly detail: string,
    readonly checks?: DodReport,
  ) {}
}

export function refuse(reason: RefusalCode, detail: string, checks?: DodReport): never {
  throw new Refusal(reason, detail, checks);
}

export const INTENTS: readonly Intent[] = ["add", "amend", "remove", "replace", "clarify", "reject", "confirm", "undo"];
export const CARD_KINDS = ["story", "rule", "example", "question"] as const;
export const LANES = ["remote", "me", "manual"] as const;
export const TRANSCRIPTION_PROVIDERS = ["local-whisper", "web-speech", "manual", "replay"] as const;
export const CLASSIFIER_PROVIDERS = ["rules.v1", "claude", "human"] as const;
export const OPERATION_KINDS = [
  "card.create", "card.update", "card.remove", "card.replace", "definition.refine", "interpretation.reject", "confirm", "undo",
] as const;
export const TEMPLATE_KINDS = ["card.create", "card.update", "card.remove", "card.replace", "definition.refine", "confirm", "interpretation.reject"] as const;
export const BACKLOG_KINDS = ["code", "infra", "operator"] as const;
export const SIZE_ESTIMATES = ["XS", "S", "M", "L", "XL", "unsized"] as const;
export const COMMAND_KINDS = [
  "utterance.record", "proposal.propose", "classification.record", "clarification.answer", "question.accept", "signoff.record", "export.options_set",
] as const;

export const INTENT_OF: Record<Operation["kind"], Intent> = {
  "card.create": "add",
  "card.update": "amend",
  "card.remove": "remove",
  "card.replace": "replace",
  "definition.refine": "clarify",
  "interpretation.reject": "reject",
  confirm: "confirm",
  undo: "undo",
};

export const MAX_FACTS = 40;
export const MAX_CAPABILITY_CLASS_LENGTH = 80;
export const FACT_SLOT = /^[A-Za-z][A-Za-z0-9_]*$/;

type Rec = Record<string, unknown>;

/** trim; CRLF -> LF */
export function normText(text: string): string {
  return text.replace(/\r\n/g, "\n").trim();
}

/** 0..1 with at most two decimal places; never rounded. */
export function isValidConfidence(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 && /^(?:0|1|0\.\d{1,2})$/.test(String(value));
}

function isRec(value: unknown): value is Rec {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function present(record: Rec, key: string): boolean {
  return record[key] !== undefined;
}

export function shapeObject(value: unknown, path: string, keys: readonly string[]): Rec {
  if (!isRec(value)) refuse(REFUSAL.BAD_SHAPE, `${path} must be an object`);
  for (const key of Object.keys(value)) {
    if (!keys.includes(key) && value[key] !== undefined) refuse(REFUSAL.BAD_SHAPE, `${path}.${key} is not a declared field`);
  }
  return value;
}

function required(record: Rec, key: string, path: string): unknown {
  if (!present(record, key)) refuse(REFUSAL.BAD_SHAPE, `${path}.${key} is required`);
  return record[key];
}

export function shapeString(value: unknown, path: string): string {
  if (typeof value !== "string") refuse(REFUSAL.BAD_SHAPE, `${path} must be a string`);
  return value;
}

export function shapeStringOrNull(value: unknown, path: string): string | null {
  if (value === null) return null;
  return shapeString(value, path);
}

export function shapeBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") refuse(REFUSAL.BAD_SHAPE, `${path} must be a boolean`);
  return value;
}

export function shapeNumber(value: unknown, path: string): number {
  if (typeof value !== "number") refuse(REFUSAL.BAD_SHAPE, `${path} must be a number`);
  return value;
}

export function shapeArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) refuse(REFUSAL.BAD_SHAPE, `${path} must be an array`);
  return value;
}

export function shapeStringArray(value: unknown, path: string): string[] {
  return shapeArray(value, path).map((v, i) => shapeString(v, `${path}[${i}]`));
}

export function shapeEnum<T extends string>(value: unknown, path: string, values: readonly T[], code: RefusalCode = REFUSAL.INVALID_ENUM): T {
  if (typeof value !== "string" || !(values as readonly string[]).includes(value)) {
    refuse(code, `${path} must be one of ${values.map((v) => JSON.stringify(v)).join(", ")}; got ${JSON.stringify(value)}`);
  }
  return value as T;
}

export function shapeConfidence(value: unknown, path: string): number {
  const n = shapeNumber(value, path);
  if (!isValidConfidence(n)) refuse(REFUSAL.INVALID_CONFIDENCE, `${path} must be between 0 and 1 with at most two decimal places; got ${n}`);
  return n;
}

export function shapeDefinitions(value: unknown, path: string): Definition[] {
  const out: Definition[] = [];
  const seen = new Set<string>();
  shapeArray(value, path).forEach((item, i) => {
    const d = shapeObject(item, `${path}[${i}]`, ["term", "definition"]);
    const term = normText(shapeString(required(d, "term", `${path}[${i}]`), `${path}[${i}].term`));
    const definition = normText(shapeString(required(d, "definition", `${path}[${i}]`), `${path}[${i}].definition`));
    if (term === "") refuse(REFUSAL.INVALID_DEFINITION, `${path}[${i}].term is empty`);
    if (definition === "") refuse(REFUSAL.INVALID_DEFINITION, `${path}[${i}].definition is empty`);
    if (seen.has(term)) refuse(REFUSAL.INVALID_DEFINITION, `${path} defines the term ${JSON.stringify(term)} twice`);
    seen.add(term);
    out.push({ term, definition });
  });
  return sortDefinitions(out);
}

export function sortDefinitions(definitions: readonly Definition[]): Definition[] {
  return [...definitions].sort((a, b) => (a.term < b.term ? -1 : a.term > b.term ? 1 : 0));
}

export function shapeNewCard(value: unknown, path: string): NewCard {
  if (!isRec(value)) refuse(REFUSAL.BAD_SHAPE, `${path} must be an object`);
  const kind = shapeEnum(value.kind, `${path}.kind`, CARD_KINDS);
  const keys = ["kind", "text", "definitions", ...(kind === "example" ? ["rule_id"] : kind === "question" ? ["about_card_id"] : [])];
  shapeObject(value, path, keys);
  const text = normText(shapeString(required(value, "text", path), `${path}.text`));
  if (text === "") refuse(REFUSAL.EMPTY_TEXT, `${path}.text is empty`);
  const definitions = present(value, "definitions") ? shapeDefinitions(value.definitions, `${path}.definitions`) : undefined;
  const withDefs = <T extends object>(card: T): T & { definitions?: Definition[] } => (definitions ? { ...card, definitions } : card);
  switch (kind) {
    case "story":
      return withDefs({ kind: "story" as const, text });
    case "rule":
      return withDefs({ kind: "rule" as const, text });
    case "example":
      return withDefs({ kind: "example" as const, text, rule_id: present(value, "rule_id") ? shapeStringOrNull(value.rule_id, `${path}.rule_id`) : null });
    case "question":
      return withDefs({
        kind: "question" as const, text, about_card_id: present(value, "about_card_id") ? shapeStringOrNull(value.about_card_id, `${path}.about_card_id`) : null,
      });
  }
}

/** `allowEmpty`: a template patch with an amendment may be empty or carry text "" (resolveTemplate recomputes it). */
export function shapePatch(value: unknown, path: string, allowEmpty = false): CardPatch {
  const p = shapeObject(value, path, ["text", "definitions", "rule_id", "about_card_id", "answer"]);
  const patch: CardPatch = {};
  let keys = 0;
  if (present(p, "text")) {
    const text = normText(shapeString(p.text, `${path}.text`));
    if (text === "" && !allowEmpty) refuse(REFUSAL.EMPTY_TEXT, `${path}.text is empty`);
    patch.text = text;
    keys++;
  }
  if (present(p, "definitions")) {
    patch.definitions = shapeDefinitions(p.definitions, `${path}.definitions`);
    keys++;
  }
  if (present(p, "rule_id")) {
    patch.rule_id = shapeStringOrNull(p.rule_id, `${path}.rule_id`);
    keys++;
  }
  if (present(p, "about_card_id")) {
    patch.about_card_id = shapeStringOrNull(p.about_card_id, `${path}.about_card_id`);
    keys++;
  }
  if (present(p, "answer")) {
    const answer = shapeStringOrNull(p.answer, `${path}.answer`);
    patch.answer = answer === null ? null : normText(answer);
    if (patch.answer === "") refuse(REFUSAL.EMPTY_TEXT, `${path}.answer is empty (use null to re-open the question)`);
    keys++;
  }
  if (keys === 0 && !allowEmpty) refuse(REFUSAL.PATCH_EMPTY, `${path} changes nothing`);
  return patch;
}

function shapeReplacement(value: unknown, path: string): { text: string; definitions?: Definition[] } {
  const r = shapeObject(value, path, ["text", "definitions"]);
  const text = normText(shapeString(required(r, "text", path), `${path}.text`));
  if (text === "") refuse(REFUSAL.EMPTY_TEXT, `${path}.text is empty`);
  return present(r, "definitions") ? { text, definitions: shapeDefinitions(r.definitions, `${path}.definitions`) } : { text };
}

function shapeTerm(value: unknown, path: string): string {
  const term = normText(shapeString(value, path));
  if (term === "") refuse(REFUSAL.INVALID_DEFINITION, `${path} is empty`);
  return term;
}

export function shapeOperation(value: unknown, path: string): Operation {
  if (!isRec(value)) refuse(REFUSAL.BAD_SHAPE, `${path} must be an object`);
  const kind = shapeEnum(value.kind, `${path}.kind`, OPERATION_KINDS, REFUSAL.BAD_SHAPE);
  switch (kind) {
    case "card.create":
      shapeObject(value, path, ["kind", "card"]);
      return { kind, card: shapeNewCard(required(value, "card", path), `${path}.card`) };
    case "card.update":
      shapeObject(value, path, ["kind", "card_id", "patch"]);
      return { kind, card_id: shapeString(required(value, "card_id", path), `${path}.card_id`), patch: shapePatch(required(value, "patch", path), `${path}.patch`) };
    case "card.remove":
      shapeObject(value, path, ["kind", "card_id"]);
      return { kind, card_id: shapeString(required(value, "card_id", path), `${path}.card_id`) };
    case "card.replace": {
      shapeObject(value, path, ["kind", "card_id", "replacement", "replacement_card_id"]);
      const card_id = shapeString(required(value, "card_id", path), `${path}.card_id`);
      const byText = present(value, "replacement") && value.replacement !== null;
      const byId = present(value, "replacement_card_id") && value.replacement_card_id !== null;
      if (byText === byId) refuse(REFUSAL.BAD_SHAPE, `${path} must carry exactly one of replacement / replacement_card_id`);
      if (byText) return { kind, card_id, replacement: shapeReplacement(value.replacement, `${path}.replacement`) };
      return { kind, card_id, replacement_card_id: shapeString(value.replacement_card_id, `${path}.replacement_card_id`) };
    }
    case "definition.refine":
      shapeObject(value, path, ["kind", "card_id", "term", "definition"]);
      return {
        kind,
        card_id: shapeString(required(value, "card_id", path), `${path}.card_id`),
        term: shapeTerm(required(value, "term", path), `${path}.term`),
        definition: shapeTerm(required(value, "definition", path), `${path}.definition`),
      };
    case "interpretation.reject":
      shapeObject(value, path, ["kind", "proposal_id"]);
      return { kind, proposal_id: shapeString(required(value, "proposal_id", path), `${path}.proposal_id`) };
    case "confirm":
      shapeObject(value, path, ["kind", "card_ids", "proposal_ids"]);
      return {
        kind,
        card_ids: shapeStringArray(required(value, "card_ids", path), `${path}.card_ids`),
        proposal_ids: shapeStringArray(required(value, "proposal_ids", path), `${path}.proposal_ids`),
      };
    case "undo": {
      shapeObject(value, path, ["kind", "to_revision_seq"]);
      const seq = required(value, "to_revision_seq", path);
      if (seq !== null && !Number.isInteger(seq)) refuse(REFUSAL.BAD_SHAPE, `${path}.to_revision_seq must be an integer or null`);
      return { kind, to_revision_seq: seq as number | null };
    }
  }
}

function shapeAmendment(value: unknown, path: string): Amendment {
  const a = shapeObject(value, path, ["from", "to", "scope", "append"]);
  return {
    from: shapeStringOrNull(required(a, "from", path), `${path}.from`),
    to: shapeString(required(a, "to", path), `${path}.to`),
    scope: shapeStringOrNull(required(a, "scope", path), `${path}.scope`),
    append: shapeString(required(a, "append", path), `${path}.append`),
  };
}

export function shapeTemplate(value: unknown, path: string): OperationTemplate {
  if (!isRec(value)) refuse(REFUSAL.BAD_SHAPE, `${path} must be an object`);
  const kind = shapeEnum(value.kind, `${path}.kind`, TEMPLATE_KINDS, REFUSAL.BAD_SHAPE);
  switch (kind) {
    case "card.create": {
      shapeObject(value, path, ["kind", "card"]);
      const card = shapeNewCard(required(value, "card", path), `${path}.card`);
      if (card.kind !== "example" && card.kind !== "question") {
        refuse(REFUSAL.CLARIFICATION_SHAPE, `${path}.card.kind must be example or question (a ${card.kind} has no link for the answer to fill)`);
      }
      return { kind, card };
    }
    case "card.update": {
      shapeObject(value, path, ["kind", "patch", "amendment"]);
      const amendmentValue = required(value, "amendment", path);
      const amendment = amendmentValue === null ? null : shapeAmendment(amendmentValue, `${path}.amendment`);
      return { kind, patch: shapePatch(required(value, "patch", path), `${path}.patch`, amendment !== null), amendment };
    }
    case "card.remove":
      shapeObject(value, path, ["kind"]);
      return { kind };
    case "card.replace": {
      shapeObject(value, path, ["kind", "replacement", "replacement_card_id"]);
      const byText = present(value, "replacement") && value.replacement !== null;
      const byId = present(value, "replacement_card_id") && value.replacement_card_id !== null;
      if (byText === byId) refuse(REFUSAL.BAD_SHAPE, `${path} must carry exactly one of replacement / replacement_card_id`);
      if (byText) return { kind, replacement: shapeReplacement(value.replacement, `${path}.replacement`) };
      return { kind, replacement_card_id: shapeString(value.replacement_card_id, `${path}.replacement_card_id`) };
    }
    case "definition.refine":
      shapeObject(value, path, ["kind", "term", "definition"]);
      return { kind, term: shapeTerm(required(value, "term", path), `${path}.term`), definition: shapeTerm(required(value, "definition", path), `${path}.definition`) };
    case "confirm":
      shapeObject(value, path, ["kind"]);
      return { kind };
    case "interpretation.reject":
      shapeObject(value, path, ["kind"]);
      return { kind };
  }
}

export function shapeStamp(value: unknown, path: string, providers: readonly ClassifierStamp["provider"][] = CLASSIFIER_PROVIDERS): ClassifierStamp {
  const s = shapeObject(value, path, ["provider", "model", "prompt_version", "fallback_from", "error", "actor"]);
  const provider = shapeEnum(required(s, "provider", path), `${path}.provider`, providers);
  const fallback = required(s, "fallback_from", path);
  if (fallback !== null && fallback !== "claude") refuse(REFUSAL.INVALID_ENUM, `${path}.fallback_from must be "claude" or null`);
  const actorValue = shapeStringOrNull(required(s, "actor", path), `${path}.actor`);
  const actor = actorValue === null ? null : actorValue.trim();
  if (actor === "") refuse(REFUSAL.ACTOR_REQUIRED, `${path}.actor is empty (use null for a pure AI interpretation)`);
  if (provider === "human" && actor === null) refuse(REFUSAL.ACTOR_REQUIRED, `${path}.actor must name the person behind a human proposal`);
  return {
    provider,
    model: shapeStringOrNull(required(s, "model", path), `${path}.model`),
    prompt_version: shapeStringOrNull(required(s, "prompt_version", path), `${path}.prompt_version`),
    fallback_from: fallback as "claude" | null,
    error: shapeStringOrNull(required(s, "error", path), `${path}.error`),
    actor,
  };
}

const PROPOSAL_KEYS = [
  "id", "intent", "operation", "template", "pending_operation", "candidates", "confidence", "needs_clarification", "question",
  "source_utterance_ids", "classifier", "resolves_clarification_id", "rationale",
];

export function shapeProposal(value: unknown, path: string): Proposal {
  const p = shapeObject(value, path, PROPOSAL_KEYS);
  const id = shapeString(required(p, "id", path), `${path}.id`);
  if (id === "") refuse(REFUSAL.BAD_SHAPE, `${path}.id is empty`);
  const operationValue = required(p, "operation", path);
  const templateValue = required(p, "template", path);
  const pendingValue = required(p, "pending_operation", path);
  const questionValue = shapeStringOrNull(required(p, "question", path), `${path}.question`);
  const candidates = shapeArray(required(p, "candidates", path), `${path}.candidates`).map((c, i) => {
    const o = shapeObject(c, `${path}.candidates[${i}]`, ["card_id", "label", "score"]);
    const score = required(o, "score", `${path}.candidates[${i}]`);
    return {
      card_id: shapeString(required(o, "card_id", `${path}.candidates[${i}]`), `${path}.candidates[${i}].card_id`),
      label: shapeString(required(o, "label", `${path}.candidates[${i}]`), `${path}.candidates[${i}].label`),
      score: score === null ? null : shapeConfidence(score, `${path}.candidates[${i}].score`),
    };
  });
  return {
    id,
    intent: shapeEnum(required(p, "intent", path), `${path}.intent`, INTENTS),
    operation: operationValue === null ? null : shapeOperation(operationValue, `${path}.operation`),
    template: templateValue === null ? null : shapeTemplate(templateValue, `${path}.template`),
    pending_operation: pendingValue === null ? null : shapeOperation(pendingValue, `${path}.pending_operation`),
    candidates,
    confidence: shapeConfidence(required(p, "confidence", path), `${path}.confidence`),
    needs_clarification: shapeBoolean(required(p, "needs_clarification", path), `${path}.needs_clarification`),
    question: questionValue === null ? null : normText(questionValue),
    source_utterance_ids: shapeStringArray(required(p, "source_utterance_ids", path), `${path}.source_utterance_ids`),
    classifier: shapeStamp(required(p, "classifier", path), `${path}.classifier`),
    resolves_clarification_id: shapeStringOrNull(required(p, "resolves_clarification_id", path), `${path}.resolves_clarification_id`),
    rationale: shapeString(required(p, "rationale", path), `${path}.rationale`),
  };
}

export function shapeUtterance(value: unknown, path: string): Utterance {
  const u = shapeObject(value, path, ["id", "text", "lane", "speaker", "provider", "model", "t_start_ms", "t_end_ms", "is_local", "confidence"]);
  const id = shapeString(required(u, "id", path), `${path}.id`);
  if (id === "") refuse(REFUSAL.DUPLICATE_ID, `${path}.id is empty`);
  const text = normText(shapeString(required(u, "text", path), `${path}.text`));
  if (text === "") refuse(REFUSAL.EMPTY_TEXT, `${path}.text is empty`);
  const lane = shapeEnum(required(u, "lane", path), `${path}.lane`, LANES);
  const speaker = shapeStringOrNull(required(u, "speaker", path), `${path}.speaker`);
  const provider = shapeEnum(required(u, "provider", path), `${path}.provider`, TRANSCRIPTION_PROVIDERS);
  const model = shapeStringOrNull(required(u, "model", path), `${path}.model`);
  const t_start_ms = shapeNumber(required(u, "t_start_ms", path), `${path}.t_start_ms`);
  const t_end_ms = shapeNumber(required(u, "t_end_ms", path), `${path}.t_end_ms`);
  if (!Number.isInteger(t_start_ms) || !Number.isInteger(t_end_ms)) refuse(REFUSAL.INVALID_TIMING, `${path}.t_start_ms / t_end_ms must be integer milliseconds`);
  if (t_start_ms < 0 || t_end_ms < 0) refuse(REFUSAL.INVALID_TIMING, `${path}.t_start_ms / t_end_ms must not be negative`);
  if (t_end_ms < t_start_ms) refuse(REFUSAL.INVALID_TIMING, `${path}.t_end_ms (${t_end_ms}) is before t_start_ms (${t_start_ms})`);
  const is_local = shapeBoolean(required(u, "is_local", path), `${path}.is_local`);
  const confidenceValue = required(u, "confidence", path);
  const confidence = confidenceValue === null ? null : shapeConfidence(confidenceValue, `${path}.confidence`);
  return { id, text, lane, speaker, provider, model, t_start_ms, t_end_ms, is_local, confidence };
}

function shapeAnswer(value: unknown, path: string): ClarificationAnswer {
  if (!isRec(value)) refuse(REFUSAL.BAD_SHAPE, `${path} must be an object`);
  const kind = shapeEnum(value.kind, `${path}.kind`, ["candidate", "yes", "text", "dismiss"] as const, REFUSAL.BAD_SHAPE);
  switch (kind) {
    case "candidate":
      shapeObject(value, path, ["kind", "card_id"]);
      return { kind, card_id: shapeString(required(value, "card_id", path), `${path}.card_id`) };
    case "yes":
      shapeObject(value, path, ["kind"]);
      return { kind };
    case "text":
      shapeObject(value, path, ["kind", "text", "utterance_id"]);
      return {
        kind,
        text: normText(shapeString(required(value, "text", path), `${path}.text`)),
        utterance_id: shapeStringOrNull(required(value, "utterance_id", path), `${path}.utterance_id`),
      };
    case "dismiss":
      shapeObject(value, path, ["kind", "reason"]);
      return { kind, reason: normText(shapeString(required(value, "reason", path), `${path}.reason`)) };
  }
}

function shapeExportOptions(value: unknown, path: string): ExportOptionsInput {
  const o = shapeObject(value, path, ["capability_class", "kind", "size_estimate", "facts", "by"]);
  const capability_class = normText(shapeString(required(o, "capability_class", path), `${path}.capability_class`));
  if (capability_class === "") refuse(REFUSAL.EMPTY_TEXT, `${path}.capability_class is empty`);
  if (capability_class.length > MAX_CAPABILITY_CLASS_LENGTH) refuse(REFUSAL.EMPTY_TEXT, `${path}.capability_class is longer than ${MAX_CAPABILITY_CLASS_LENGTH} characters`);
  const kind = shapeEnum(required(o, "kind", path), `${path}.kind`, BACKLOG_KINDS);
  const size_estimate = shapeEnum(required(o, "size_estimate", path), `${path}.size_estimate`, SIZE_ESTIMATES);
  const factsValue = shapeArray(required(o, "facts", path), `${path}.facts`);
  if (factsValue.length > MAX_FACTS) refuse(REFUSAL.BAD_SHAPE, `${path}.facts has ${factsValue.length} entries; at most ${MAX_FACTS} are allowed`);
  const facts: ExportFact[] = factsValue.map((f, i) => {
    const fact = shapeObject(f, `${path}.facts[${i}]`, ["slot", "text"]);
    const slot = shapeString(required(fact, "slot", `${path}.facts[${i}]`), `${path}.facts[${i}].slot`);
    if (!FACT_SLOT.test(slot)) refuse(REFUSAL.BAD_SHAPE, `${path}.facts[${i}].slot ${JSON.stringify(slot)} must match ${FACT_SLOT}`);
    const text = normText(shapeString(required(fact, "text", `${path}.facts[${i}]`), `${path}.facts[${i}].text`));
    if (text === "") refuse(REFUSAL.EMPTY_TEXT, `${path}.facts[${i}].text is empty`);
    return { slot, text };
  });
  const by = normText(shapeString(required(o, "by", path), `${path}.by`));
  if (by === "") refuse(REFUSAL.ACTOR_REQUIRED, `${path}.by is empty`);
  return { capability_class, kind, size_estimate, facts, by };
}

/** The shape pass: a Command rebuilt from validated fields only. */
export function shapeCommand(value: unknown): Command {
  if (!isRec(value)) refuse(REFUSAL.BAD_SHAPE, "command must be an object");
  const kind = shapeEnum(value.kind, "command.kind", COMMAND_KINDS, REFUSAL.BAD_SHAPE);
  const path = "command";
  switch (kind) {
    case "utterance.record":
      shapeObject(value, path, ["kind", "utterance"]);
      return { kind, utterance: shapeUtterance(required(value, "utterance", path), `${path}.utterance`) };
    case "proposal.propose": {
      shapeObject(value, path, ["kind", "proposals"]);
      const proposals = shapeArray(required(value, "proposals", path), `${path}.proposals`).map((p, i) => shapeProposal(p, `${path}.proposals[${i}]`));
      return { kind, proposals };
    }
    case "classification.record": {
      shapeObject(value, path, ["kind", "utterance_id", "intent", "heard_intent", "classifier", "confidence", "rationale", "proposal_ids", "refused", "error"]);
      const intent = shapeEnum(required(value, "intent", path), `${path}.intent`, [...INTENTS, "none"] as const);
      const heardValue = required(value, "heard_intent", path);
      const heard_intent = heardValue === null ? null : shapeEnum(heardValue, `${path}.heard_intent`, INTENTS);
      if (heard_intent !== null && intent !== "none") refuse(REFUSAL.BAD_SHAPE, `${path}.heard_intent is set only when intent is "none"`);
      const refused = shapeArray(required(value, "refused", path), `${path}.refused`).map((r, i) => {
        const o = shapeObject(r, `${path}.refused[${i}]`, ["operation", "reason", "detail"]);
        return {
          operation: shapeEnum(required(o, "operation", `${path}.refused[${i}]`), `${path}.refused[${i}].operation`, [...OPERATION_KINDS, "unknown"] as const, REFUSAL.BAD_SHAPE),
          reason: shapeString(required(o, "reason", `${path}.refused[${i}]`), `${path}.refused[${i}].reason`),
          detail: shapeString(required(o, "detail", `${path}.refused[${i}]`), `${path}.refused[${i}].detail`),
        };
      });
      const errorValue = required(value, "error", path);
      let error: { code: string; message: string } | null = null;
      if (errorValue !== null) {
        const e = shapeObject(errorValue, `${path}.error`, ["code", "message"]);
        error = { code: shapeString(required(e, "code", `${path}.error`), `${path}.error.code`), message: shapeString(required(e, "message", `${path}.error`), `${path}.error.message`) };
      }
      return {
        kind,
        utterance_id: shapeString(required(value, "utterance_id", path), `${path}.utterance_id`),
        intent,
        heard_intent,
        classifier: shapeStamp(required(value, "classifier", path), `${path}.classifier`, ["rules.v1", "claude"]),
        confidence: shapeConfidence(required(value, "confidence", path), `${path}.confidence`),
        rationale: shapeString(required(value, "rationale", path), `${path}.rationale`),
        proposal_ids: shapeStringArray(required(value, "proposal_ids", path), `${path}.proposal_ids`),
        refused,
        error,
      };
    }
    case "clarification.answer":
      shapeObject(value, path, ["kind", "clarification_id", "answer", "actor"]);
      return {
        kind,
        clarification_id: shapeString(required(value, "clarification_id", path), `${path}.clarification_id`),
        answer: shapeAnswer(required(value, "answer", path), `${path}.answer`),
        actor: normText(shapeString(required(value, "actor", path), `${path}.actor`)),
      };
    case "question.accept":
      shapeObject(value, path, ["kind", "question_id", "by", "reason"]);
      return {
        kind,
        question_id: shapeString(required(value, "question_id", path), `${path}.question_id`),
        by: normText(shapeString(required(value, "by", path), `${path}.by`)),
        reason: normText(shapeString(required(value, "reason", path), `${path}.reason`)),
      };
    case "signoff.record": {
      shapeObject(value, path, ["kind", "reviewer", "confirmation_text", "cited_revision_hash"]);
      const reviewer = shapeObject(required(value, "reviewer", path), `${path}.reviewer`, ["name"]);
      return {
        kind,
        reviewer: { name: normText(shapeString(required(reviewer, "name", `${path}.reviewer`), `${path}.reviewer.name`)) },
        confirmation_text: shapeString(required(value, "confirmation_text", path), `${path}.confirmation_text`),
        cited_revision_hash: shapeString(required(value, "cited_revision_hash", path), `${path}.cited_revision_hash`),
      };
    }
    case "export.options_set":
      shapeObject(value, path, ["kind", "options"]);
      return { kind, options: shapeExportOptions(required(value, "options", path), `${path}.options`) };
  }
}
