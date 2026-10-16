// exmap/src/web/format.ts — small presentation helpers shared by the components (design §10.3–§10.6). Pure; no React.
import type { Card, CardKind, Lane, MapState, Operation, OperationTemplate, Utterance } from "../core/types.js";

export const hash8 = (hash: string): string => hash.slice(0, 8);

/** `mm:ss` from session-relative milliseconds. */
export function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** The first `max` characters of a text, with an ellipsis when cut. */
export function excerpt(text: string, max = 60): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, max).trimEnd()}…`;
}

/** A readable local time for an ISO timestamp; the ISO string itself when it does not parse. */
export function timeOf(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export const LANE_LABEL: Record<Lane, string> = { remote: "Call", me: "Me", manual: "Typed" };
export const KIND_LABEL: Record<CardKind, string> = { story: "Story", rule: "Rules", example: "Examples", question: "Questions" };
export const KIND_SINGULAR: Record<CardKind, string> = { story: "story", rule: "rule", example: "example", question: "question" };

/** No code path substitutes a lane name for a missing speaker label. */
export function speakerLabel(speaker: string | null): string {
  return speaker ?? "— (no speaker label)";
}

export function providerChip(u: Pick<Utterance, "provider" | "model">): string {
  switch (u.provider) {
    case "local-whisper":
      return `Whisper · ${u.model ? u.model.replace(/^.*whisper-/, "") : "local"}`;
    case "web-speech":
      return "Web Speech (not local)";
    case "manual":
      return "Typed";
    case "replay":
      return "Replay";
  }
}

export function cardText(state: MapState, id: string | null, max = 40): string {
  if (id === null) return "(none)";
  const card = state.cards[id];
  return card ? excerpt(card.text, max) : id;
}

export function kindOf(state: MapState, id: string): CardKind | null {
  return state.cards[id]?.kind ?? null;
}

/** One line describing an operation ("Will: …" in the tray, the diff header in a proposal item). */
export function describeOperation(state: MapState, op: Operation): string {
  switch (op.kind) {
    case "card.create":
      return `add ${op.card.kind}: ${excerpt(op.card.text, 80)}`;
    case "card.update": {
      const parts: string[] = [];
      if (op.patch.text !== undefined) parts.push(`text → ${excerpt(op.patch.text, 80)}`);
      if (op.patch.answer !== undefined) parts.push(op.patch.answer === null ? "re-open the question" : `answer → ${excerpt(op.patch.answer, 80)}`);
      if (op.patch.rule_id !== undefined) parts.push(`rule → ${cardText(state, op.patch.rule_id)}`);
      if (op.patch.about_card_id !== undefined) parts.push(`about → ${cardText(state, op.patch.about_card_id)}`);
      if (op.patch.definitions !== undefined) parts.push(`definitions → ${op.patch.definitions.map((d) => `${d.term}: ${d.definition}`).join("; ")}`);
      return `amend ${kindOf(state, op.card_id) ?? "card"} ${cardText(state, op.card_id)}: ${parts.join(", ")}`;
    }
    case "card.remove":
      return `remove ${kindOf(state, op.card_id) ?? "card"}: ${cardText(state, op.card_id, 80)}`;
    case "card.replace":
      return "replacement" in op
        ? `replace ${kindOf(state, op.card_id) ?? "card"} ${cardText(state, op.card_id)} ⇢ ${excerpt(op.replacement.text, 80)}`
        : `replace ${kindOf(state, op.card_id) ?? "card"} ${cardText(state, op.card_id)} ⇢ ${cardText(state, op.replacement_card_id, 80)}`;
    case "definition.refine":
      return `refine ${cardText(state, op.card_id)}: ${op.term}: ${op.definition}`;
    case "interpretation.reject":
      return `reject proposal ${op.proposal_id}`;
    case "confirm":
      return `confirm ${[...op.card_ids.map((id) => cardText(state, id)), ...op.proposal_ids.map((id) => `proposal ${id}`)].join(", ")}`;
    case "undo":
      return op.to_revision_seq === null ? "undo one step" : `undo to revision ${op.to_revision_seq}`;
  }
}

/** "Will: remove the chosen example" and friends for a clarification with a template. */
export function describeTemplate(state: MapState, template: OperationTemplate, candidateIds: readonly string[]): string {
  const kinds = new Set(candidateIds.map((id) => kindOf(state, id)).filter((k): k is CardKind => k !== null));
  const noun = kinds.size === 1 ? `the chosen ${KIND_SINGULAR[[...kinds][0]!]}` : "the chosen card";
  switch (template.kind) {
    case "card.create":
      return `add ${template.card.kind}: ${excerpt(template.card.text, 80)} (linked to ${noun})`;
    case "card.update":
      return template.amendment
        ? `amend ${noun}: ${template.amendment.from === null ? "" : `${template.amendment.from} → `}${template.amendment.to || template.amendment.append}`
        : `amend ${noun}: ${excerpt(template.patch.text ?? template.patch.answer ?? "", 80)}`;
    case "card.remove":
      return `remove ${noun}`;
    case "card.replace":
      return "replacement" in template ? `replace ${noun} ⇢ ${excerpt(template.replacement.text, 80)}` : `replace ${noun} with ${cardText(state, template.replacement_card_id, 60)}`;
    case "definition.refine":
      return `refine ${noun}: ${template.term}: ${template.definition}`;
    case "confirm":
      return `confirm ${noun}`;
    case "interpretation.reject":
      return `reject the interpretation that produced ${noun}`;
  }
}

export function cardLink(card: Card): string | null {
  if (card.kind === "example") return card.rule_id;
  if (card.kind === "question") return card.about_card_id;
  return null;
}
