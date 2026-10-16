// exmap/src/core/effects.ts — the card-effect helpers apply() and reduce() share: applyEffects (§5.3), invertEffects
// (§5.4 interpretation.reject), diffToSnapshot (§5.9 undo), the latest check behind REJECT_NOT_LATEST, and the record
// comparisons that define "content", "live" and "substantive". No hashing, no I/O.
import type {
  Card, CardEffect, CardId, CardRecord, CardStatus, Definition, EventId, MapState, Operation, Proposal, ProposalId,
  ProposalRecord, Provenance, RefusalCode,
} from "./types.js";

/** Everything except `history`. */
export function stripHistory(card: Card): CardRecord {
  const { history: _history, ...record } = card;
  return record as CardRecord;
}

export function snapshotOf(cards: Readonly<Record<CardId, Card>>): Record<CardId, CardRecord> {
  const out: Record<CardId, CardRecord> = {};
  for (const id of Object.keys(cards)) out[id] = stripHistory(cards[id]!);
  return out;
}

export function isLive(record: { status: CardStatus }): boolean {
  return record.status === "applied" || record.status === "confirmed";
}

export function definitionsEqual(a: readonly Definition[], b: readonly Definition[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i]!.term !== b[i]!.term || a[i]!.definition !== b[i]!.definition) return false;
  }
  return true;
}

/** Content = text, definitions, rule_id, about_card_id, answer (§5.2). */
export function contentEquals(a: CardRecord, b: CardRecord): boolean {
  if (a.kind !== b.kind || a.text !== b.text || !definitionsEqual(a.definitions, b.definitions)) return false;
  if (a.kind === "example" && b.kind === "example") return a.rule_id === b.rule_id;
  if (a.kind === "question" && b.kind === "question") return a.about_card_id === b.about_card_id && a.answer === b.answer;
  return true;
}

/** Structural equality over plain JSON values (undefined properties count as absent). */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((v, i) => deepEqual(v, b[i]));
  }
  const ra = a as Record<string, unknown>;
  const rb = b as Record<string, unknown>;
  const ka = Object.keys(ra).filter((k) => ra[k] !== undefined);
  const kb = Object.keys(rb).filter((k) => rb[k] !== undefined);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(rb, k) && deepEqual(ra[k], rb[k]));
}

/** Whole-record equality ignoring the named keys (undo compares sans version / restored_by). */
export function recordEqualsIgnoring(a: CardRecord, b: CardRecord, ignore: readonly string[]): boolean {
  const strip = (r: CardRecord): Record<string, unknown> => {
    const out: Record<string, unknown> = { ...(r as unknown as Record<string, unknown>) };
    for (const k of ignore) delete out[k];
    return out;
  };
  return deepEqual(strip(a), strip(b));
}

/** An effect is substantive when before/after differ in content, live-ness or `supersedes` (or it created the card). */
export function isSubstantiveEffect(effect: CardEffect): boolean {
  if (effect.before === null) return true;
  return (
    !contentEquals(effect.before, effect.after) ||
    isLive(effect.before) !== isLive(effect.after) ||
    effect.before.supersedes !== effect.after.supersedes
  );
}

/**
 * §5.3: for each effect, `history` gains the existing record when `after.version` differs; `cards[card_id] = {...after,
 * history}`; new ids are appended to `card_order`. Total: an effect for an unknown card creates it. Pure.
 */
export function applyEffects(
  cards: Readonly<Record<CardId, Card>>,
  cardOrder: readonly CardId[],
  effects: readonly CardEffect[],
  eventId: EventId,
): { cards: Record<CardId, Card>; card_order: CardId[] } {
  if (effects.length === 0) return { cards: cards as Record<CardId, Card>, card_order: cardOrder as CardId[] };
  const next: Record<CardId, Card> = { ...cards };
  const order = [...cardOrder];
  for (const effect of effects) {
    const existing = next[effect.card_id];
    let history = existing ? existing.history : [];
    if (existing && effect.after.version !== existing.version) {
      history = [...history, { version: existing.version, record: stripHistory(existing), replaced_by_event_id: eventId }];
    }
    next[effect.card_id] = { ...effect.after, history } as Card;
    if (!existing && !order.includes(effect.card_id)) order.push(effect.card_id);
  }
  return { cards: next, card_order: order };
}

export interface RestoringAct {
  proposal: Proposal;
  event_id: EventId;
}

export function provenanceOf(proposal: Proposal, eventId: EventId): Provenance {
  return { proposal_id: proposal.id, event_id: eventId, utterance_ids: [...proposal.source_utterance_ids], classifier: proposal.classifier.provider };
}

function withoutReviewFlags(record: CardRecord): CardRecord {
  return record.kind === "example" ? { ...record, needs_review: null } : record;
}

/**
 * §5.4 interpretation.reject: the proposal created the card (before null or proposed) -> rejected / interpretation_rejected;
 * a substantive effect -> `before` restored verbatim at version+1 when content differs, with `restored_by` = the
 * rejecting act; a review-state-only effect restores `needs_review = before.needs_review` only.
 */
export function invertEffects(effects: readonly CardEffect[], cards: Readonly<Record<CardId, Card>>, act: RestoringAct): CardEffect[] {
  const out: CardEffect[] = [];
  for (const effect of effects) {
    const card = cards[effect.card_id];
    if (!card) continue;
    const current = stripHistory(card);
    if (effect.before === null || effect.before.status === "proposed") {
      out.push({
        card_id: current.id,
        before: current,
        after: withoutReviewFlags({
          ...current,
          status: "rejected",
          superseded_by: null,
          rejection: { kind: "interpretation_rejected", proposal_id: act.proposal.id, event_id: act.event_id },
          confirmation: null,
        }),
      });
    } else if (isSubstantiveEffect(effect)) {
      out.push({
        card_id: current.id,
        before: current,
        after: {
          ...effect.before,
          version: contentEquals(effect.before, current) ? current.version : current.version + 1,
          restored_by: provenanceOf(act.proposal, act.event_id),
        } as CardRecord,
      });
    } else if (current.kind === "example" && effect.before.kind === "example" && effect.after.kind === "example") {
      // review-state only: restore the earlier flag, but only while the flag this proposal set is still the current one
      // (a confirmation or a later rule change since then is a person's or a later act's decision, not this proposal's)
      if (!deepEqual(current.needs_review, effect.after.needs_review)) continue;
      const after: CardRecord = { ...current, needs_review: effect.before.needs_review };
      if (!deepEqual(after, current)) out.push({ card_id: current.id, before: current, after });
    }
  }
  return out;
}

/**
 * The latest record of the target's version (the card now when its version has not moved, else the history entry that
 * version left behind), when it is live with the target's content: it carries the review decisions (confirmations,
 * acceptance, reviews of a flag) made on that very content after the target revision, which snapshots never see because
 * review-only events create no revision.
 */
function reviewSource(card: Card, current: CardRecord, target: CardRecord): CardRecord | null {
  if (!isLive(target)) return null;
  const source = current.version === target.version ? current : card.history.find((h) => h.version === target.version)?.record ?? null;
  return source !== null && isLive(source) && contentEquals(source, target) ? source : null;
}

/** The target record with the review state of `source`; a flag raised since the target (by a change being undone) is dropped. */
function withLaterReview(target: CardRecord, source: CardRecord | null): CardRecord {
  if (source === null) return target;
  const reviewed = { ...target, status: source.status, confirmation: source.confirmation } as CardRecord;
  if (reviewed.kind === "question" && source.kind === "question") return { ...reviewed, accepted_outstanding: source.accepted_outstanding };
  if (reviewed.kind === "example" && source.kind === "example") return { ...reviewed, needs_review: source.needs_review === null ? null : reviewed.needs_review };
  return reviewed;
}

/**
 * §5.9 undo: a card present in the snapshot whose record (sans history / version / restored_by) differs -> the snapshot
 * record verbatim at version+1 when content differs, `restored_by` = the undo, except that review decisions made on the
 * target's content since the target revision are kept (reviewSource); a card absent from the snapshot (created after the
 * target) -> rejected / undone. Already-rejected cards absent from the snapshot are left as they are.
 */
export function diffToSnapshot(
  cards: Readonly<Record<CardId, Card>>,
  cardOrder: readonly CardId[],
  snapshot: Readonly<Record<CardId, CardRecord>>,
  act: RestoringAct,
): CardEffect[] {
  const out: CardEffect[] = [];
  for (const id of cardOrder) {
    const card = cards[id];
    if (!card) continue;
    const current = stripHistory(card);
    const target = snapshot[id];
    if (target) {
      if (recordEqualsIgnoring(current, target, ["version", "restored_by"])) continue;
      const restored = withLaterReview(target, reviewSource(card, current, target));
      if (recordEqualsIgnoring(current, restored, ["version", "restored_by"])) continue;
      out.push({
        card_id: id,
        before: current,
        after: {
          ...restored,
          version: contentEquals(current, target) ? current.version : current.version + 1,
          restored_by: provenanceOf(act.proposal, act.event_id),
        } as CardRecord,
      });
    } else if (current.status !== "rejected") {
      out.push({
        card_id: id,
        before: current,
        after: withoutReviewFlags({
          ...current,
          status: "rejected",
          superseded_by: null,
          rejection: { kind: "undone", proposal_id: act.proposal.id, event_id: act.event_id },
          confirmation: null,
        }),
      });
    }
  }
  return out;
}

export type Rejectability =
  | { ok: true; record: ProposalRecord }
  | { ok: false; reason: Extract<RefusalCode, "PROPOSAL_NOT_FOUND" | "PROPOSAL_NOT_REJECTABLE" | "PROPOSAL_KIND_NOT_REJECTABLE" | "REJECT_NOT_LATEST">; detail: string };

/** Exactly the interpretation.reject preconditions of §5.4; select.isRejectable and apply() both use it. */
export function rejectability(state: MapState, proposalId: ProposalId): Rejectability {
  const record = state.proposals[proposalId];
  if (!record) return { ok: false, reason: "PROPOSAL_NOT_FOUND", detail: `proposal ${proposalId} does not exist` };
  if (record.status !== "applied") {
    return { ok: false, reason: "PROPOSAL_NOT_REJECTABLE", detail: `proposal ${proposalId} is ${record.status}, not applied` };
  }
  const operation = record.proposal.operation;
  if (operation === null) return { ok: false, reason: "PROPOSAL_NOT_REJECTABLE", detail: `proposal ${proposalId} carries no operation` };
  if (operation.kind === "confirm") {
    return { ok: false, reason: "PROPOSAL_KIND_NOT_REJECTABLE", detail: `proposal ${proposalId} is a confirmation; confirmations are not rejectable` };
  }
  for (const effect of record.effects) {
    if (!isSubstantiveEffect(effect)) continue;
    const card = state.cards[effect.card_id];
    if (!card || card.version !== effect.after.version || card.status !== effect.after.status) {
      const now = card ? `version ${card.version}, ${card.status}` : "missing";
      return {
        ok: false,
        reason: "REJECT_NOT_LATEST",
        detail: `card ${effect.card_id} has changed since proposal ${proposalId} (now ${now}; the proposal left it at version ${effect.after.version}, ${effect.after.status})`,
      };
    }
  }
  return { ok: true, record };
}

export function distinct<T>(items: readonly T[]): T[] {
  return [...new Set(items)];
}

/** The primary targets of an applied operation (§4 ProposalRecord.affected_card_ids), derived from operation + effects. */
export function primaryTargets(operation: Operation, effects: readonly CardEffect[]): CardId[] {
  switch (operation.kind) {
    case "card.create":
      return distinct(effects.map((e) => e.card_id));
    case "card.update":
    case "card.remove":
    case "definition.refine":
      return [operation.card_id];
    case "card.replace": {
      const replacement = "replacement_card_id" in operation ? operation.replacement_card_id : effects.find((e) => e.before === null)?.card_id;
      return replacement ? [operation.card_id, replacement] : [operation.card_id];
    }
    case "confirm":
      return [...operation.card_ids];
    case "interpretation.reject":
    case "undo":
      return distinct(effects.map((e) => e.card_id));
  }
}
