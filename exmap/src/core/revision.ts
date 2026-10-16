// exmap/src/core/revision.ts — design §5.2. The requirement revision is sha256 of the canonical meaning of the map:
// live cards' id, kind, text, definitions, links and a question's answer. Everything else (status, confirmations,
// needs_review, acceptance, versions, provenance, timestamps, non-live cards) is excluded.
import { canonicalJson } from "./canonical.js";
import type { CanonicalCard, CanonicalState, CardId, CardRecord, Sha256Fn, Sha256Hex } from "./types.js";

/** = sha256('{"cards":[],"schema":"exmap.revision.v1"}') */
export const GENESIS_REVISION_HASH = "8e97e07bb7573b0849c4f8894c845ce76472f2c9f0eda7a7db37004bc269f675";

function isLive(record: CardRecord): boolean {
  return record.status === "applied" || record.status === "confirmed";
}

function toCanonicalCard(record: CardRecord): CanonicalCard {
  const definitions = record.definitions.map((d) => ({ term: d.term, definition: d.definition }));
  switch (record.kind) {
    case "story":
      return { id: record.id, kind: "story", text: record.text, definitions };
    case "rule":
      return { id: record.id, kind: "rule", text: record.text, definitions };
    case "example":
      return { id: record.id, kind: "example", text: record.text, definitions, rule_id: record.rule_id };
    case "question":
      return { id: record.id, kind: "question", text: record.text, definitions, about_card_id: record.about_card_id, answer: record.answer };
  }
}

/** Live cards (status applied | confirmed), sorted by id, as CanonicalCard. Accepts the state's card map or a card list. */
export function canonicalState(cards: Readonly<Record<CardId, CardRecord>> | readonly CardRecord[]): CanonicalState {
  const list: readonly CardRecord[] = Array.isArray(cards) ? (cards as readonly CardRecord[]) : Object.values(cards as Record<CardId, CardRecord>);
  const live = list
    .filter(isLive)
    .map(toCanonicalCard)
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { schema: "exmap.revision.v1", cards: live };
}

export function computeRevision(cards: Readonly<Record<CardId, CardRecord>> | readonly CardRecord[], sha256: Sha256Fn): Sha256Hex {
  return sha256(canonicalJson(canonicalState(cards)));
}
