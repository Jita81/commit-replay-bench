// exmap/src/core/apply.ts — design §5.4. Everything enters here: (0) shape-check (shape.ts), (1) pass 1 validates the
// whole batch against the state with placeholder ids, each proposal against the state reduced so far, (2) pass 2 mints
// real ids and chains the events, (3) signoff.invalidated after the first revision-creating event when a sign-off is
// active, (4) the reduced state is returned. A refusal emits nothing and calls nextId zero times.
import { chainEvent } from "./chain.js";
import { dodReport, SIGNOFF_CONFIRMATION_TEXT } from "./dod.js";
import {
  applyEffects, contentEquals, definitionsEqual, diffToSnapshot, distinct, invertEffects, isLive, provenanceOf, rejectability,
  stripHistory,
} from "./effects.js";
import { reduce } from "./reduce.js";
import { REFUSAL } from "./refusals.js";
import { computeRevision } from "./revision.js";
import * as select from "./select.js";
import { INTENT_OF, Refusal, refuse, shapeCommand, sortDefinitions } from "./shape.js";
import type {
  ApplyContext, ApplyResult, Card, CardEffect, CardId, CardKind, CardRecord, Clarification, Command, Definition, EventId,
  EventPayload, ExmapEvent, ExportOptionsInput, IdPrefix, IsoTimestamp, MapState, NeedsReview, NewCard, Operation, OperationTemplate, Proposal,
  Provenance, RevisionStamp, Sha256Fn, Signoff,
} from "./types.js";

type IdSource = (prefix: IdPrefix) => string;
type Payload = EventPayload | ((at: IsoTimestamp) => EventPayload);

const PLACEHOLDER_AT: IsoTimestamp = "1970-01-01T00:00:00.000Z";
const ACT_KINDS: readonly Operation["kind"][] = ["card.remove", "undo", "interpretation.reject"];

/* ───────────── the batch ───────────── */

class Batch {
  readonly events: ExmapEvent[] = [];
  cur: MapState;
  private readonly signoffBefore: Signoff | null;
  private invalidated = false;

  constructor(
    readonly base: MapState,
    readonly ids: IdSource,
    private readonly now: () => IsoTimestamp,
    readonly sha256: Sha256Fn,
  ) {
    this.cur = base;
    this.signoffBefore = select.activeSignoff(base);
  }

  emit(id: EventId, payload: Payload): ExmapEvent {
    const at = this.now();
    const resolved = typeof payload === "function" ? payload(at) : payload;
    const batch_id = this.events[0]?.id ?? id;
    const body = { ...resolved, id, at, session_id: this.base.session_id, batch_id };
    const event = chainEvent({ seq: this.cur.head.seq, hash: this.cur.head.hash }, body, this.sha256);
    this.events.push(event);
    this.cur = reduce(this.cur, event);
    if ("revision" in event) this.invalidateSignoff(event, event.revision);
    return event;
  }

  /** Appends signoff.invalidated once per batch when a sign-off was active before it (§5.8). */
  invalidateSignoff(by: ExmapEvent, toRevision: RevisionStamp): void {
    if (this.signoffBefore === null || this.invalidated) return;
    this.invalidated = true;
    const signoff = this.signoffBefore;
    this.emit(this.ids("evt"), {
      type: "signoff.invalidated", signoff_id: signoff.id, by_event_id: by.id, from_revision: signoff.revision, to_revision: toRevision,
    });
  }

  nextRevision(): number {
    return select.currentRevision(this.cur).seq + 1;
  }
}

/* ───────────── helpers over the current state ───────────── */

function statusDetail(card: Card): string {
  switch (card.status) {
    case "superseded":
      return `superseded (by ${card.superseded_by})`;
    case "rejected":
      return select.statusLabel(card);
    default:
      return card.status;
  }
}

function requireCard(cur: MapState, id: CardId): Card {
  const card = cur.cards[id];
  if (!card) refuse(REFUSAL.CARD_NOT_FOUND, `card ${id} does not exist`);
  return card;
}

function requireLive(cur: MapState, id: CardId): Card {
  const card = requireCard(cur, id);
  if (!isLive(card)) refuse(REFUSAL.CARD_NOT_LIVE, `card ${id} is ${statusDetail(card)}`);
  return card;
}

function requireLink(cur: MapState, id: CardId, kind: CardKind | null, field: string): Card {
  const card = requireLive(cur, id);
  if (kind !== null && card.kind !== kind) refuse(REFUSAL.LINK_KIND_MISMATCH, `${field} ${id} is a ${card.kind}, not a ${kind}`);
  return card;
}

function utteranceIds(cur: MapState): Set<string> {
  return new Set(cur.utterances.map((u) => u.id));
}

function newRecord(id: CardId, card: NewCard, status: "proposed" | "applied", prov: Provenance): CardRecord {
  const common = {
    id, text: card.text, definitions: card.definitions ?? [], status, version: 1, supersedes: null, superseded_by: null,
    rejection: null, confirmation: null, created: prov, changed: prov, restored_by: null,
  };
  switch (card.kind) {
    case "story":
      return { ...common, kind: "story" };
    case "rule":
      return { ...common, kind: "rule" };
    case "example":
      return { ...common, kind: "example", rule_id: card.rule_id, needs_review: null };
    case "question":
      return { ...common, kind: "question", about_card_id: card.about_card_id, answer: null, accepted_outstanding: null };
  }
}

interface ContentChange {
  text?: string;
  definitions?: Definition[];
  rule_id?: CardId | null;
  about_card_id?: CardId | null;
  answer?: string | null;
}

function withContent(record: CardRecord, change: ContentChange): CardRecord {
  const base = { ...record, text: change.text ?? record.text, definitions: change.definitions ?? record.definitions };
  switch (base.kind) {
    case "example":
      return { ...base, rule_id: change.rule_id === undefined ? base.rule_id : change.rule_id };
    case "question":
      return {
        ...base,
        about_card_id: change.about_card_id === undefined ? base.about_card_id : change.about_card_id,
        answer: change.answer === undefined ? base.answer : change.answer,
      };
    default:
      return base;
  }
}

/** A content change: version+1, status applied, confirmation cleared, `changed` = the proposal, restored_by null, acceptance cleared. */
function contentChanged(record: CardRecord, change: ContentChange, prov: Provenance): CardRecord {
  const next = { ...withContent(record, change), version: record.version + 1, status: "applied" as const, confirmation: null, changed: prov, restored_by: null };
  return next.kind === "question" ? { ...next, accepted_outstanding: null } : next;
}

function flagExamples(cur: MapState, ruleId: CardId, flag: NeedsReview, exclude: readonly CardId[] = []): CardEffect[] {
  return select
    .examplesOf(cur, ruleId)
    .filter((e) => !exclude.includes(e.id))
    .map((e) => {
      const before = stripHistory(e);
      return { card_id: e.id, before, after: { ...before, needs_review: flag } as CardRecord };
    });
}

function leaveLive(record: CardRecord, status: "rejected" | "superseded", change: Partial<CardRecord>): CardRecord {
  const next = { ...record, ...change, status, confirmation: null } as CardRecord;
  return next.kind === "example" ? { ...next, needs_review: null } : next;
}

function revisionStamp(b: Batch, effects: readonly CardEffect[], eventId: EventId): RevisionStamp {
  const next = applyEffects(b.cur.cards, b.cur.card_order, effects, eventId);
  return { seq: b.nextRevision(), hash: computeRevision(next.cards, b.sha256) };
}

/* ───────────── operation plans ───────────── */

interface Plan {
  operation: Operation;
  /** Mints the ids and emits `proposal.made` then the outcome. */
  run: (b: Batch, proposal: Proposal) => void;
}

function emitMade(b: Batch, proposal: Proposal, operation: Operation, effects: CardEffect[] = []): EventId {
  const madeId = b.ids("evt");
  b.emit(madeId, { type: "proposal.made", proposal: { ...proposal, operation }, effects });
  return madeId;
}

function emitApplied(b: Batch, proposal: Proposal, operation: Operation, outcomeId: EventId, effects: CardEffect[]): void {
  const revision = revisionStamp(b, effects, outcomeId);
  b.emit(outcomeId, { type: "proposal.applied", proposal_id: proposal.id, operation, effects, revision });
}

function planCreate(cur: MapState, op: Extract<Operation, { kind: "card.create" }>): Plan {
  const card = op.card;
  if (card.kind === "story") {
    const existing = select.story(cur);
    if (existing) refuse(REFUSAL.STORY_ALREADY_EXISTS, `a live story already exists (${existing.id}); amend or replace it instead`);
  }
  if (card.kind === "example" && card.rule_id !== null) requireLink(cur, card.rule_id, "rule", "rule_id");
  if (card.kind === "question" && card.about_card_id !== null) requireLink(cur, card.about_card_id, null, "about_card_id");
  return {
    operation: op,
    run(b, proposal) {
      const madeId = b.ids("evt");
      const cardId = b.ids("card");
      const proposed = newRecord(cardId, card, "proposed", provenanceOf(proposal, madeId));
      b.emit(madeId, { type: "proposal.made", proposal: { ...proposal, operation: op }, effects: [{ card_id: cardId, before: null, after: proposed }] });
      const outcomeId = b.ids("evt");
      emitApplied(b, proposal, op, outcomeId, [{ card_id: cardId, before: proposed, after: { ...proposed, status: "applied" } }]);
    },
  };
}

function planUpdate(cur: MapState, op: Extract<Operation, { kind: "card.update" }>): Plan {
  const card = requireLive(cur, op.card_id);
  const patch = op.patch;
  if (Object.keys(patch).length === 0) refuse(REFUSAL.PATCH_EMPTY, `the patch for card ${card.id} changes nothing`);
  if (patch.rule_id !== undefined && card.kind !== "example") refuse(REFUSAL.PATCH_FIELD_NOT_ALLOWED, `rule_id is not a field of a ${card.kind} (card ${card.id})`);
  if (patch.about_card_id !== undefined && card.kind !== "question") refuse(REFUSAL.PATCH_FIELD_NOT_ALLOWED, `about_card_id is not a field of a ${card.kind} (card ${card.id})`);
  if (patch.answer !== undefined && card.kind !== "question") refuse(REFUSAL.PATCH_FIELD_NOT_ALLOWED, `answer is not a field of a ${card.kind} (card ${card.id})`);
  if (patch.rule_id !== undefined && patch.rule_id !== null) requireLink(cur, patch.rule_id, "rule", "rule_id");
  if (patch.about_card_id !== undefined && patch.about_card_id !== null) requireLink(cur, patch.about_card_id, null, "about_card_id");
  const before = stripHistory(card);
  const after = withContent(before, patch);
  if (contentEquals(before, after)) refuse(REFUSAL.NO_CHANGE, `the patch leaves card ${card.id} unchanged`);
  const ruleContentChanged = card.kind === "rule" && (before.text !== after.text || !definitionsEqual(before.definitions, after.definitions));
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const effects: CardEffect[] = [{ card_id: card.id, before, after: contentChanged(before, patch, provenanceOf(proposal, outcomeId)) }];
      if (ruleContentChanged) effects.push(...flagExamples(b.cur, card.id, { reason: "rule_changed", rule_id: card.id, event_id: outcomeId }));
      emitApplied(b, proposal, op, outcomeId, effects);
    },
  };
}

function planRemove(cur: MapState, op: Extract<Operation, { kind: "card.remove" }>): Plan {
  const card = requireLive(cur, op.card_id);
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const before = stripHistory(card);
      const effects: CardEffect[] = [
        { card_id: card.id, before, after: leaveLive(before, "rejected", { rejection: { kind: "removed", proposal_id: proposal.id, event_id: outcomeId } }) },
      ];
      if (card.kind === "rule") effects.push(...flagExamples(b.cur, card.id, { reason: "rule_removed", rule_id: card.id, event_id: outcomeId }));
      emitApplied(b, proposal, op, outcomeId, effects);
    },
  };
}

function relinkEffects(cur: MapState, old: Card, replacementId: CardId, prov: Provenance, eventId: EventId): CardEffect[] {
  const effects: CardEffect[] = [];
  if (old.kind === "rule") {
    for (const example of select.examplesOf(cur, old.id)) {
      if (example.id === replacementId) continue;
      const before = stripHistory(example);
      const changed = contentChanged(before, { rule_id: replacementId }, prov);
      effects.push({ card_id: example.id, before, after: { ...changed, needs_review: { reason: "rule_replaced", rule_id: replacementId, event_id: eventId } } as CardRecord });
    }
  }
  for (const question of select.questionsAbout(cur, old.id)) {
    if (question.id === replacementId) continue;
    const before = stripHistory(question);
    effects.push({ card_id: question.id, before, after: contentChanged(before, { about_card_id: replacementId }, prov) });
  }
  return effects;
}

function planReplace(cur: MapState, op: Extract<Operation, { kind: "card.replace" }>): Plan {
  const old = requireLive(cur, op.card_id);
  if ("replacement_card_id" in op) {
    const replacement = requireCard(cur, op.replacement_card_id);
    if (replacement.id === old.id) refuse(REFUSAL.REPLACEMENT_INVALID, `card ${old.id} cannot replace itself`);
    if (!isLive(replacement)) refuse(REFUSAL.CARD_NOT_LIVE, `replacement card ${replacement.id} is ${statusDetail(replacement)}`);
    if (replacement.kind !== old.kind) refuse(REFUSAL.KIND_MISMATCH, `replacement card ${replacement.id} is a ${replacement.kind}; card ${old.id} is a ${old.kind}`);
    if (replacement.supersedes !== null) refuse(REFUSAL.REPLACEMENT_INVALID, `replacement card ${replacement.id} already supersedes ${replacement.supersedes}`);
    return {
      operation: op,
      run(b, proposal) {
        emitMade(b, proposal, op);
        const outcomeId = b.ids("evt");
        const prov = provenanceOf(proposal, outcomeId);
        const repBefore = stripHistory(replacement);
        const oldBefore = stripHistory(old);
        const effects: CardEffect[] = [
          { card_id: replacement.id, before: repBefore, after: { ...repBefore, supersedes: old.id } as CardRecord },
          { card_id: old.id, before: oldBefore, after: leaveLive(oldBefore, "superseded", { superseded_by: replacement.id }) },
          ...relinkEffects(b.cur, old, replacement.id, prov, outcomeId),
        ];
        emitApplied(b, proposal, op, outcomeId, effects);
      },
    };
  }
  const text = op.replacement.text;
  const definitions = op.replacement.definitions ?? [];
  if (old.text === text && definitionsEqual(old.definitions, definitions)) refuse(REFUSAL.NO_CHANGE, `the replacement has the same content as card ${old.id}`);
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const newId = b.ids("card");
      const prov = provenanceOf(proposal, outcomeId);
      const oldBefore = stripHistory(old);
      const draft: NewCard =
        old.kind === "example"
          ? { kind: "example", text, definitions, rule_id: old.rule_id }
          : old.kind === "question"
            ? { kind: "question", text, definitions, about_card_id: old.about_card_id }
            : { kind: old.kind, text, definitions };
      const created = { ...newRecord(newId, draft, "applied", prov), supersedes: old.id } as CardRecord;
      const effects: CardEffect[] = [
        { card_id: newId, before: null, after: created },
        { card_id: old.id, before: oldBefore, after: leaveLive(oldBefore, "superseded", { superseded_by: newId }) },
        ...relinkEffects(b.cur, old, newId, prov, outcomeId),
      ];
      emitApplied(b, proposal, op, outcomeId, effects);
    },
  };
}

function planRefine(cur: MapState, op: Extract<Operation, { kind: "definition.refine" }>): Plan {
  const card = requireLive(cur, op.card_id);
  const definitions = sortDefinitions([...card.definitions.filter((d) => d.term !== op.term), { term: op.term, definition: op.definition }]);
  if (definitionsEqual(card.definitions, definitions)) refuse(REFUSAL.NO_CHANGE, `card ${card.id} already defines ${JSON.stringify(op.term)} that way`);
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const before = stripHistory(card);
      const effects: CardEffect[] = [{ card_id: card.id, before, after: contentChanged(before, { definitions }, provenanceOf(proposal, outcomeId)) }];
      if (card.kind === "rule") effects.push(...flagExamples(b.cur, card.id, { reason: "rule_changed", rule_id: card.id, event_id: outcomeId }));
      emitApplied(b, proposal, op, outcomeId, effects);
    },
  };
}

function planReject(cur: MapState, op: Extract<Operation, { kind: "interpretation.reject" }>): Plan {
  const result = rejectability(cur, op.proposal_id);
  if (!result.ok) refuse(result.reason, result.detail);
  const target = result.record;
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const effects = invertEffects(target.effects, b.cur.cards, { proposal, event_id: outcomeId });
      const revision = revisionStamp(b, effects, outcomeId);
      b.emit(outcomeId, { type: "proposal.rejected", proposal_id: proposal.id, rejected_proposal_id: target.proposal.id, effects, revision });
    },
  };
}

function planConfirm(cur: MapState, op: Extract<Operation, { kind: "confirm" }>): Plan {
  if (new Set(op.card_ids).size !== op.card_ids.length) refuse(REFUSAL.BAD_SHAPE, "confirm.card_ids lists a card twice");
  if (new Set(op.proposal_ids).size !== op.proposal_ids.length) refuse(REFUSAL.BAD_SHAPE, "confirm.proposal_ids lists a proposal twice");
  if (op.card_ids.length === 0 && op.proposal_ids.length === 0) refuse(REFUSAL.EMPTY_TARGET, "confirm names no cards and no proposals");
  const cards = op.card_ids.map((id) => requireLive(cur, id));
  for (const id of op.proposal_ids) {
    const record = cur.proposals[id];
    if (!record) refuse(REFUSAL.PROPOSAL_NOT_FOUND, `proposal ${id} does not exist`);
    if (record.status !== "applied" && record.status !== "confirmed") refuse(REFUSAL.PROPOSAL_NOT_CONFIRMABLE, `proposal ${id} is ${record.status}; only applied acts can be reviewed`);
    const kind = record.proposal.operation?.kind ?? null;
    if (kind === null || !ACT_KINDS.includes(kind)) {
      refuse(REFUSAL.PROPOSAL_NOT_CONFIRMABLE, `proposal ${id} is a ${kind ?? "clarification"}; confirm its cards instead`);
    }
  }
  const changing = cards.filter((c) => c.status !== "confirmed" || (c.kind === "example" && c.needs_review !== null));
  const byActs = op.proposal_ids.filter((id) => cur.proposals[id]?.status === "applied");
  if (changing.length === 0 && byActs.length === 0) {
    refuse(REFUSAL.NOTHING_TO_CONFIRM, `every named card is already confirmed and every named act already reviewed`);
  }
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const effects: CardEffect[] = changing.map((card) => {
        const before = stripHistory(card);
        const confirmed = {
          ...before,
          status: "confirmed" as const,
          confirmation: {
            proposal_id: proposal.id, event_id: outcomeId, version: card.version,
            by: { provider: proposal.classifier.provider, actor: proposal.classifier.actor, confidence: proposal.confidence },
          },
        };
        return { card_id: card.id, before, after: (confirmed.kind === "example" ? { ...confirmed, needs_review: null } : confirmed) as CardRecord };
      });
      const next = applyEffects(b.cur.cards, b.cur.card_order, effects, outcomeId).cards;
      const candidates = new Set<string>();
      for (const card of changing) {
        candidates.add(card.changed.proposal_id);
        if (card.kind === "example" && card.needs_review !== null) {
          const flaggedBy = Object.values(b.cur.proposals).find((p) => p.outcome_event_id === card.needs_review!.event_id);
          if (flaggedBy) candidates.add(flaggedBy.proposal.id);
        }
      }
      const byCards = [...candidates].filter((id) => {
        const record = b.cur.proposals[id];
        if (!record || record.status !== "applied") return false;
        return distinct(record.effects.map((e) => e.card_id)).every((cardId) => {
          const card = next[cardId];
          if (!card || !isLive(card)) return true;
          return card.status === "confirmed" && (card.kind !== "example" || card.needs_review === null);
        });
      });
      b.emit(outcomeId, {
        type: "proposal.confirmed", proposal_id: proposal.id, card_ids: op.card_ids, proposal_ids: op.proposal_ids,
        confirms_proposal_ids: distinct([...byCards, ...byActs]), effects,
      });
    },
  };
}

function planUndo(cur: MapState, op: Extract<Operation, { kind: "undo" }>): Plan {
  const current = select.currentRevision(cur);
  let target: number;
  if (op.to_revision_seq === null) {
    const step = select.undoTarget(cur, 1);
    if (step === null) refuse(REFUSAL.UNDO_NO_EARLIER_REVISION, "there is no earlier revision to go back to");
    target = step;
  } else {
    target = op.to_revision_seq;
    if (target === current.seq) refuse(REFUSAL.UNDO_TARGET_IS_CURRENT, `revision ${target} is the current revision`);
    if (target < 0 || target > current.seq) refuse(REFUSAL.UNDO_TARGET_OUT_OF_RANGE, `revision ${target} does not exist (revisions run 0..${current.seq})`);
  }
  const revision = cur.revisions[target];
  if (!revision) refuse(REFUSAL.UNDO_TARGET_OUT_OF_RANGE, `revision ${target} does not exist`);
  if (revision.hash === current.hash) refuse(REFUSAL.NO_CHANGE, `revision ${target} has the same content as the current revision ${current.seq}`);
  return {
    operation: op,
    run(b, proposal) {
      emitMade(b, proposal, op);
      const outcomeId = b.ids("evt");
      const effects = diffToSnapshot(b.cur.cards, b.cur.card_order, revision.snapshot, { proposal, event_id: outcomeId });
      const stamp = revisionStamp(b, effects, outcomeId);
      if (stamp.hash !== revision.hash) {
        throw new Error(`undo invariant violated: restoring revision ${target} produced ${stamp.hash}, expected ${revision.hash}`);
      }
      b.emit(outcomeId, {
        type: "undo.applied", proposal_id: proposal.id, from_revision: { seq: current.seq, hash: current.hash },
        to_revision: { seq: revision.seq, hash: revision.hash }, effects, revision: { seq: stamp.seq, hash: revision.hash },
      });
    },
  };
}

function planOperation(cur: MapState, op: Operation): Plan {
  switch (op.kind) {
    case "card.create":
      return planCreate(cur, op);
    case "card.update":
      return planUpdate(cur, op);
    case "card.remove":
      return planRemove(cur, op);
    case "card.replace":
      return planReplace(cur, op);
    case "definition.refine":
      return planRefine(cur, op);
    case "interpretation.reject":
      return planReject(cur, op);
    case "confirm":
      return planConfirm(cur, op);
    case "undo":
      return planUndo(cur, op);
  }
}

/* ───────────── clarification requests ───────────── */

function validateTemplate(cur: MapState, template: OperationTemplate): void {
  if (template.kind === "card.replace" && "replacement_card_id" in template) {
    const replacement = requireLive(cur, template.replacement_card_id);
    if (replacement.supersedes !== null) refuse(REFUSAL.REPLACEMENT_INVALID, `replacement card ${replacement.id} already supersedes ${replacement.supersedes}`);
  }
}

function planClarification(cur: MapState, proposal: Proposal): Plan {
  if (proposal.question === null || proposal.question === "") refuse(REFUSAL.CLARIFICATION_QUESTION_REQUIRED, `proposal ${proposal.id} asks for clarification without a question`);
  if (proposal.template !== null && proposal.pending_operation !== null) {
    refuse(REFUSAL.CLARIFICATION_SHAPE, `proposal ${proposal.id} carries both a template and a pending operation`);
  }
  if (proposal.candidates.length > 0 && proposal.template === null) {
    refuse(REFUSAL.CLARIFICATION_SHAPE, `proposal ${proposal.id} lists candidates without a template to fill`);
  }
  for (const candidate of proposal.candidates) requireLive(cur, candidate.card_id);
  const kind = proposal.template?.kind ?? proposal.pending_operation?.kind ?? null;
  if (kind !== null && INTENT_OF[kind] !== proposal.intent) {
    refuse(REFUSAL.INTENT_OPERATION_MISMATCH, `proposal ${proposal.id}: intent ${proposal.intent} does not match ${kind} (expected ${INTENT_OF[kind]})`);
  }
  if (proposal.template !== null) validateTemplate(cur, proposal.template);
  if (proposal.pending_operation !== null) planOperation(cur, proposal.pending_operation); // validated now, emitted never
  return {
    operation: proposal.pending_operation ?? ({ kind: "confirm", card_ids: [], proposal_ids: [] } as Operation), // unused: made carries operation null
    run(b, p) {
      const madeId = b.ids("evt");
      b.emit(madeId, { type: "proposal.made", proposal: p, effects: [] });
      const askedId = b.ids("evt");
      const clarificationId = b.ids("clar");
      b.emit(askedId, {
        type: "clarification.asked", clarification_id: clarificationId, proposal_id: p.id, question: p.question!, candidates: p.candidates,
        template: p.template, pending_operation: p.pending_operation,
      });
    },
  };
}

/* ───────────── proposals ───────────── */

function validateProposal(cur: MapState, proposal: Proposal, batchIds: ReadonlySet<string>): Plan {
  if (cur.proposals[proposal.id] || batchIds.has(proposal.id)) refuse(REFUSAL.DUPLICATE_ID, `proposal ${proposal.id} already exists`);
  const recorded = utteranceIds(cur);
  for (const id of proposal.source_utterance_ids) {
    if (!recorded.has(id)) refuse(REFUSAL.UTTERANCE_UNKNOWN, `utterance ${id} is not recorded`);
  }
  if (proposal.needs_clarification !== (proposal.operation === null)) {
    refuse(REFUSAL.CLARIFICATION_SHAPE, `proposal ${proposal.id}: needs_clarification must be true exactly when operation is null`);
  }
  if (proposal.resolves_clarification_id !== null) {
    const clarification = cur.clarifications[proposal.resolves_clarification_id];
    if (!clarification) refuse(REFUSAL.CLARIFICATION_NOT_AWAITING_PROPOSAL, `clarification ${proposal.resolves_clarification_id} does not exist`);
    if (clarification.status !== "open") refuse(REFUSAL.CLARIFICATION_NOT_AWAITING_PROPOSAL, `clarification ${clarification.id} is ${clarification.status}`);
  }
  if (proposal.operation === null) return planClarification(cur, proposal);
  if (proposal.template !== null || proposal.pending_operation !== null || proposal.candidates.length > 0 || proposal.question !== null) {
    refuse(REFUSAL.CLARIFICATION_SHAPE, `proposal ${proposal.id} carries clarification fields but is not asking for clarification`);
  }
  const expected = INTENT_OF[proposal.operation.kind];
  if (expected !== proposal.intent) {
    refuse(REFUSAL.INTENT_OPERATION_MISMATCH, `proposal ${proposal.id}: intent ${proposal.intent} does not match ${proposal.operation.kind} (expected ${expected})`);
  }
  return planOperation(cur, proposal.operation);
}

function propose(b: Batch, proposals: readonly Proposal[]): void {
  if (proposals.length === 0) refuse(REFUSAL.EMPTY_TARGET, "proposal.propose carries no proposals");
  const batchIds = new Set<string>();
  proposals.forEach((proposal, i) => {
    let plan: Plan;
    try {
      plan = validateProposal(b.cur, proposal, batchIds);
    } catch (e) {
      if (e instanceof Refusal && proposals.length > 1) throw new Refusal(e.reason, `proposal ${i + 1} of ${proposals.length}: ${e.detail}`, e.checks);
      throw e;
    }
    batchIds.add(proposal.id);
    plan.run(b, proposal);
  });
}

/* ───────────── clarification answers ───────────── */

function resolveTemplate(template: OperationTemplate, card: Card): Operation {
  switch (template.kind) {
    case "card.create":
      return {
        kind: "card.create",
        card: template.card.kind === "example" ? { ...template.card, rule_id: card.id } : { ...template.card, about_card_id: card.id },
      };
    case "card.update": {
      const a = template.amendment;
      if (a === null) return { kind: "card.update", card_id: card.id, patch: template.patch };
      let text: string | null = null;
      if (a.scope === null && a.from !== null && a.from !== "") {
        const at = card.text.toLowerCase().indexOf(a.from.toLowerCase());
        if (at >= 0) text = card.text.slice(0, at) + a.to + card.text.slice(at + a.from.length);
      }
      if (text === null) text = `${card.text} Amendment: ${a.append}`;
      return { kind: "card.update", card_id: card.id, patch: { ...template.patch, text } };
    }
    case "card.remove":
      return { kind: "card.remove", card_id: card.id };
    case "card.replace":
      return "replacement_card_id" in template
        ? { kind: "card.replace", card_id: card.id, replacement_card_id: template.replacement_card_id }
        : { kind: "card.replace", card_id: card.id, replacement: template.replacement };
    case "definition.refine":
      return { kind: "definition.refine", card_id: card.id, term: template.term, definition: template.definition };
    case "confirm":
      return { kind: "confirm", card_ids: [card.id], proposal_ids: [] };
    case "interpretation.reject":
      return { kind: "interpretation.reject", proposal_id: card.changed.proposal_id };
  }
}

function resolvedProposal(asking: Proposal, clarification: Clarification, operation: Operation, actor: string): Proposal {
  return {
    id: "$resolved",
    intent: asking.intent,
    operation,
    template: null,
    pending_operation: null,
    candidates: [],
    confidence: 1,
    needs_clarification: false,
    question: null,
    source_utterance_ids: [...asking.source_utterance_ids],
    classifier: { ...asking.classifier, actor },
    resolves_clarification_id: clarification.id,
    rationale: `clarification answered by ${actor}`,
  };
}

function answerClarification(b: Batch, command: Extract<Command, { kind: "clarification.answer" }>): void {
  const cur = b.cur;
  const clarification = cur.clarifications[command.clarification_id];
  if (!clarification) refuse(REFUSAL.CLARIFICATION_NOT_FOUND, `clarification ${command.clarification_id} does not exist`);
  if (clarification.status !== "open") refuse(REFUSAL.CLARIFICATION_NOT_ANSWERABLE, `clarification ${clarification.id} is ${clarification.status}`);
  if (command.actor === "") refuse(REFUSAL.ACTOR_REQUIRED, "a clarification answer must name who answered");
  const asking = cur.proposals[clarification.proposal_id];
  if (!asking) refuse(REFUSAL.CLARIFICATION_NOT_ANSWERABLE, `clarification ${clarification.id} names an unknown proposal ${clarification.proposal_id}`);
  const answer = command.answer;
  let operation: Operation;
  switch (answer.kind) {
    case "text": {
      if (answer.text === "") refuse(REFUSAL.EMPTY_TEXT, "the text answer is empty");
      if (answer.utterance_id !== null && !utteranceIds(cur).has(answer.utterance_id)) refuse(REFUSAL.UTTERANCE_UNKNOWN, `utterance ${answer.utterance_id} is not recorded`);
      b.emit(b.ids("evt"), { type: "clarification.answered", clarification_id: clarification.id, answer, actor: command.actor, resolved_by_proposal_id: null });
      return;
    }
    case "dismiss": {
      if (answer.reason === "") refuse(REFUSAL.REASON_REQUIRED, "dismissing a clarification needs a reason");
      b.emit(b.ids("evt"), { type: "clarification.answered", clarification_id: clarification.id, answer, actor: command.actor, resolved_by_proposal_id: null });
      return;
    }
    case "candidate": {
      if (clarification.template === null) refuse(REFUSAL.CLARIFICATION_NO_TEMPLATE, `clarification ${clarification.id} has no template for a candidate to fill`);
      const needsKind = clarification.template.kind === "card.create" && clarification.template.card.kind === "example" ? "rule" : null;
      const card = requireLink(cur, answer.card_id, needsKind, "the chosen card");
      operation = resolveTemplate(clarification.template, card);
      break;
    }
    case "yes": {
      if (clarification.pending_operation === null) refuse(REFUSAL.CLARIFICATION_NO_OPERATION, `clarification ${clarification.id} has no pending operation to apply`);
      operation = clarification.pending_operation;
      break;
    }
  }
  const draft = resolvedProposal(asking.proposal, clarification, operation, command.actor);
  const plan = validateProposal(cur, draft, new Set());
  const answeredId = b.ids("evt");
  const proposalId = b.ids("prop");
  const proposal: Proposal = { ...draft, id: proposalId, operation: plan.operation };
  b.emit(answeredId, { type: "clarification.answered", clarification_id: clarification.id, answer, actor: command.actor, resolved_by_proposal_id: proposalId });
  plan.run(b, proposal);
}

/* ───────────── the other commands ───────────── */

function recordUtterance(b: Batch, command: Extract<Command, { kind: "utterance.record" }>): void {
  if (utteranceIds(b.cur).has(command.utterance.id)) refuse(REFUSAL.DUPLICATE_ID, `utterance ${command.utterance.id} is already recorded`);
  b.emit(b.ids("evt"), { type: "utterance.recorded", utterance: command.utterance });
}

function recordClassification(b: Batch, command: Extract<Command, { kind: "classification.record" }>): void {
  const cur = b.cur;
  if (!utteranceIds(cur).has(command.utterance_id)) refuse(REFUSAL.UTTERANCE_UNKNOWN, `utterance ${command.utterance_id} is not recorded`);
  for (const id of command.proposal_ids) {
    const record = cur.proposals[id];
    if (!record) refuse(REFUSAL.PROPOSAL_NOT_FOUND, `proposal ${id} does not exist`);
    if (!record.proposal.source_utterance_ids.includes(command.utterance_id)) {
      refuse(REFUSAL.CLASSIFICATION_PROPOSAL_MISMATCH, `proposal ${id} does not cite utterance ${command.utterance_id}`);
    }
  }
  if (command.error !== null && command.proposal_ids.length > 0) {
    refuse(REFUSAL.CLASSIFICATION_PROPOSAL_MISMATCH, "a classification that failed cannot also name proposals");
  }
  const { kind: _kind, ...fields } = command;
  b.emit(b.ids("evt"), { type: "utterance.classified", ...fields });
}

function acceptQuestion(b: Batch, command: Extract<Command, { kind: "question.accept" }>): void {
  const card = requireLive(b.cur, command.question_id);
  if (card.kind !== "question") refuse(REFUSAL.KIND_MISMATCH, `card ${card.id} is a ${card.kind}, not a question`);
  if (card.answer !== null) refuse(REFUSAL.QUESTION_ALREADY_RESOLVED, `question ${card.id} is answered`);
  if (card.accepted_outstanding !== null) refuse(REFUSAL.QUESTION_ALREADY_RESOLVED, `question ${card.id} is already accepted as outstanding by ${card.accepted_outstanding.by}`);
  if (command.by === "") refuse(REFUSAL.ACTOR_REQUIRED, "accepting a question as outstanding must name who accepts it");
  if (command.reason === "") refuse(REFUSAL.REASON_REQUIRED, "accepting a question as outstanding needs a reason");
  const eventId = b.ids("evt");
  const before = stripHistory(card);
  const after: CardRecord = { ...before, accepted_outstanding: { by: command.by, reason: command.reason, event_id: eventId } } as CardRecord;
  b.emit(eventId, { type: "question.accepted_outstanding", question_id: card.id, by: command.by, reason: command.reason, effects: [{ card_id: card.id, before, after }] });
}

function recordSignoff(b: Batch, command: Extract<Command, { kind: "signoff.record" }>): void {
  const cur = b.cur;
  if (command.reviewer.name === "") refuse(REFUSAL.SIGNOFF_REVIEWER_REQUIRED, "a sign-off must name the reviewer");
  if (command.confirmation_text.trim() !== SIGNOFF_CONFIRMATION_TEXT) {
    refuse(REFUSAL.SIGNOFF_CONFIRMATION_TEXT_MISMATCH, `the confirmation text must be exactly: ${SIGNOFF_CONFIRMATION_TEXT}`);
  }
  const current = select.currentRevision(cur);
  if (command.cited_revision_hash !== current.hash) {
    refuse(REFUSAL.SIGNOFF_STALE_REVISION, `the cited revision ${command.cited_revision_hash} is not the current revision ${current.seq} (${current.hash})`);
  }
  const active = select.activeSignoff(cur);
  if (active) refuse(REFUSAL.SIGNOFF_ALREADY_ACTIVE, `sign-off ${active.id} by ${active.reviewer.name} is already active on revision ${active.revision.seq}`);
  const checks = dodReport(cur);
  if (!checks.pass) {
    const failing = checks.checks.filter((c) => !c.pass).map((c) => c.id);
    refuse(REFUSAL.SIGNOFF_DOD_FAILED, `the Definition of Done is not met: ${failing.join(", ")}`, checks);
  }
  const eventId = b.ids("evt");
  const signoffId = b.ids("sig");
  b.emit(eventId, {
    type: "signoff.recorded",
    signoff: {
      id: signoffId, reviewer: { name: command.reviewer.name }, confirmation_text: SIGNOFF_CONFIRMATION_TEXT,
      revision: { seq: current.seq, hash: current.hash }, evidence: { head_seq: cur.head.seq, head_hash: cur.head.hash }, checks,
    },
  });
}

function setExportOptions(b: Batch, command: Extract<Command, { kind: "export.options_set" }>): void {
  const previous = select.exportOptions(b.cur);
  const seq = (previous?.seq ?? 0) + 1;
  const event = b.emit(b.ids("evt"), (at) => ({ type: "export.options_set", options: { ...command.options, seq, at } }));
  // The facts become acceptance-criteria lines of the verified export (brief §1.10), so a changed value that the
  // signing reviewer did not supply is a substantive change for the sign-off (brief §0), though not for the revision.
  const active = select.activeSignoff(b.base);
  if (active !== null && command.options.by !== active.reviewer.name && !sameExportOptions(previous, command.options)) {
    const { seq: revSeq, hash } = select.currentRevision(b.cur);
    b.invalidateSignoff(event, { seq: revSeq, hash });
  }
}

function sameExportOptions(previous: ExportOptionsInput | null, next: ExportOptionsInput): boolean {
  if (previous === null) return next.facts.length === 0 && next.capability_class === "unclassified" && next.kind === "code" && next.size_estimate === "unsized";
  return previous.capability_class === next.capability_class && previous.kind === next.kind && previous.size_estimate === next.size_estimate
    && previous.facts.length === next.facts.length && previous.facts.every((f, i) => f.slot === next.facts[i]!.slot && f.text === next.facts[i]!.text);
}

function execute(b: Batch, command: Command): void {
  switch (command.kind) {
    case "utterance.record":
      return recordUtterance(b, command);
    case "proposal.propose":
      return propose(b, command.proposals);
    case "classification.record":
      return recordClassification(b, command);
    case "clarification.answer":
      return answerClarification(b, command);
    case "question.accept":
      return acceptQuestion(b, command);
    case "signoff.record":
      return recordSignoff(b, command);
    case "export.options_set":
      return setExportOptions(b, command);
  }
}

/* ───────────── invariants (§5.2) ───────────── */

function assertInvariants(state: MapState): void {
  let liveStories = 0;
  for (const id of state.card_order) {
    const card = state.cards[id];
    if (!card) throw new Error(`invariant: card_order names unknown card ${id}`);
    if ((card.rejection !== null) !== (card.status === "rejected")) throw new Error(`invariant: card ${id} rejection/status disagree`);
    if ((card.confirmation !== null) !== (card.status === "confirmed")) throw new Error(`invariant: card ${id} confirmation/status disagree`);
    if ((card.superseded_by !== null) !== (card.status === "superseded")) throw new Error(`invariant: card ${id} superseded_by/status disagree`);
    if (card.status === "proposed") throw new Error(`invariant: card ${id} is still proposed after apply`);
    if (card.kind !== "example" && "needs_review" in card) throw new Error(`invariant: ${card.kind} ${id} carries needs_review`);
    if (card.kind === "story" && isLive(card)) liveStories++;
  }
  if (liveStories > 1) throw new Error("invariant: more than one live story");
}

/* ───────────── entry point ───────────── */

function placeholderIds(): IdSource {
  let n = 0;
  return (prefix) => `$${prefix}_${++n}`;
}

function runBatch(state: MapState, command: Command, ids: IdSource, now: () => IsoTimestamp, sha256: Sha256Fn): ApplyResult {
  const batch = new Batch(state, ids, now, sha256);
  try {
    execute(batch, command);
  } catch (e) {
    if (e instanceof Refusal) return e.checks ? { ok: false, reason: e.reason, detail: e.detail, checks: e.checks } : { ok: false, reason: e.reason, detail: e.detail };
    throw e;
  }
  return { ok: true, events: batch.events, state: batch.cur };
}

export function apply(state: MapState, command: Command, ctx: ApplyContext): ApplyResult {
  let shaped: Command;
  try {
    shaped = shapeCommand(command);
  } catch (e) {
    if (e instanceof Refusal) return { ok: false, reason: e.reason, detail: e.detail };
    throw e;
  }
  const dry = runBatch(state, shaped, placeholderIds(), () => PLACEHOLDER_AT, ctx.sha256);
  if (!dry.ok) return dry;
  const real = runBatch(state, shaped, ctx.nextId, ctx.now, ctx.sha256);
  if (!real.ok) return real;
  assertInvariants(real.state);
  return real;
}
