// exmap/src/server/classifier-bridge.ts — the seam between ClassifierProposal and core's Proposal (design §8.7).
// Pure functions; the only file that imports both core's and the classifier's runtime modules.
//
// buildClassifierInput(): what the classifier sees of the map (card index, recent utterances, the last proposal, the last
// rejectable one, the most recent open clarification it can represent).
// bridgeProposal() / toCoreCommands(): at most one clarification.answer, then at most one proposal.propose holding every
// proposal of the result; classifier ops the bridge cannot turn into a core operation are returned as `refused` entries
// (operation "unknown") instead of being dropped silently.
import { RECENT_UTTERANCES } from "../classifier/constants.js";
import { CHOICE } from "../classifier/schema.js";
import { select } from "../core/index.js";
import type {
  ApplyContext, Amendment, Candidate, Card, CardIndexEntry, CardPatch, Clarification, ClassifierInput, ClassifierOperation,
  ClassifierProposal, ClassifierProvenance, ClassifierStamp, ClassifierUtterance, Command, EventId, Intent, Lane, LastProposalRef,
  MapState, NewCard, Operation, OperationKind, OperationTemplate, PendingClarification, Proposal, ProposalRecord, RefusedOperation,
  Utterance, UtteranceId,
} from "../core/types.js";

/* ───────────── intents and actors ───────────── */

const INTENT_OF: { readonly [K in OperationKind]: Intent } = {
  "card.create": "add",
  "card.update": "amend",
  "card.remove": "remove",
  "card.replace": "replace",
  "definition.refine": "clarify",
  "interpretation.reject": "reject",
  confirm: "confirm",
  undo: "undo",
};

/** The one intent each core operation kind belongs to; every core proposal's intent comes from here. */
export function intentOf(kind: OperationKind): Intent {
  return INTENT_OF[kind];
}

/** The UI's lane names (design §7): remote = the call, me = the microphone, manual = typed. */
export const LANE_LABEL: { readonly [K in Lane]: string } = { remote: "Call", me: "Me", manual: "Typed" };

/** The person behind a voice answer: the label a person assigned to the lane, or an explicit statement that none was. */
export function voiceActor(u: Pick<Utterance, "speaker" | "lane">): string {
  return u.speaker ?? `(${LANE_LABEL[u.lane]}, no speaker label)`;
}

/** The question asked when a bare voice "undo" follows an undo (design §5.9, §8.7). */
export const REDO_QUESTION = "The last change was itself an undo — redo it?";

const ACT_KINDS: readonly OperationKind[] = ["card.remove", "undo", "interpretation.reject"];
const INDEX_STATUSES = new Set(["proposed", "applied", "confirmed"]);

const round2 = (n: number): number => Math.min(1, Math.max(0, Math.round(n * 100) / 100));

function isLive(card: Card | undefined): card is Card {
  return card !== undefined && (card.status === "applied" || card.status === "confirmed");
}

/* ───────────── buildClassifierInput ───────────── */

function toClassifierUtterance(u: Utterance): ClassifierUtterance {
  return { id: u.id, text: u.text, lane: u.lane, speaker: u.speaker };
}

function provenanceOf(stamp: ClassifierStamp): ClassifierProvenance | null {
  if (stamp.provider === "human") return null;
  return { provider: stamp.provider, model: stamp.model, prompt_version: stamp.prompt_version, fallback_from: stamp.fallback_from, error: stamp.error };
}

function indexEntry(card: Card, seqOfEvent: (id: EventId) => number, speakerOf: ReadonlyMap<UtteranceId, string | null>): CardIndexEntry {
  const last = card.changed.utterance_ids[card.changed.utterance_ids.length - 1] ?? null;
  return {
    id: card.id,
    kind: card.kind,
    title: card.text.slice(0, 60),
    text: card.text,
    status: card.status,
    links: {
      rule_id: card.kind === "example" ? card.rule_id : null,
      about_card_id: card.kind === "question" ? card.about_card_id : null,
    },
    answer: card.kind === "question" ? card.answer : null,
    seq: seqOfEvent(card.changed.event_id),
    last_utterance_id: last,
    last_speaker: last === null ? null : (speakerOf.get(last) ?? null),
    proposal_id: card.changed.classifier !== "human" ? card.changed.proposal_id : null,
  };
}

function proposalRef(state: MapState, record: ProposalRecord): LastProposalRef | null {
  const op = record.proposal.operation;
  const utterance_id = record.proposal.source_utterance_ids[0];
  if (op === null || utterance_id === undefined) return null;
  if (record.status !== "applied" && record.status !== "confirmed") return null;
  const first = record.affected_card_ids[0];
  return {
    id: record.proposal.id,
    intent: record.proposal.intent,
    op: op.kind,
    kind: op.kind === "undo" || first === undefined ? null : (state.cards[first]?.kind ?? null),
    status: record.status,
    card_ids: [...record.affected_card_ids],
    utterance_id,
    rejectable: select.isRejectable(state, record.proposal.id),
  };
}

/** The most recent non-human proposal with status applied | confirmed (design §8.7). */
function lastProposalRecord(state: MapState): ProposalRecord | null {
  return select.lastAppliedProposal(state, { aiOnly: true, statuses: ["applied", "confirmed"] });
}

/** The most recent proposal that is rejectable and cites an utterance (a human proposal has none to cite). */
function lastRejectableRecord(state: MapState): ProposalRecord | null {
  for (let i = state.proposal_order.length - 1; i >= 0; i--) {
    const record = state.proposals[state.proposal_order[i]!];
    if (!record || record.proposal.source_utterance_ids.length === 0) continue;
    if (select.isRejectable(state, record.proposal.id)) return record;
  }
  return null;
}

/** Steps n with select.undoTarget(state, n) === seq (1 when seq is null or no n reaches it). */
function stepsTo(state: MapState, seq: number | null): number {
  if (seq === null) return 1;
  for (let n = 1; n <= state.revisions.length; n++) {
    const target = select.undoTarget(state, n);
    if (target === null) break;
    if (target === seq) return n;
  }
  return 1;
}

/** A complete core operation in the classifier's own shape (for a confirm_intent clarification). */
export function toClassifierOp(op: Operation, state: MapState): ClassifierOperation {
  switch (op.kind) {
    case "card.create": {
      const c = op.card;
      return {
        kind: "card.create",
        card: { kind: c.kind, text: c.text, rule_id: c.kind === "example" ? c.rule_id : null, about_card_id: c.kind === "question" ? c.about_card_id : null },
      };
    }
    case "card.update":
      return {
        kind: "card.update",
        card_id: op.card_id,
        patch: {
          text: op.patch.text ?? null,
          text_append: null,
          answer: op.patch.answer ?? null,
          rule_id: op.patch.rule_id ?? null,
          about_card_id: op.patch.about_card_id ?? null,
        },
        amendment: null,
      };
    case "card.remove":
      return { kind: "card.remove", card_id: op.card_id, reason: "" };
    case "card.replace":
      return "replacement_card_id" in op
        ? { kind: "card.replace", card_id: op.card_id, replacement: null, replacement_card_id: op.replacement_card_id }
        : { kind: "card.replace", card_id: op.card_id, replacement: { text: op.replacement.text }, replacement_card_id: null };
    case "definition.refine":
      return { kind: "definition.refine", card_id: op.card_id, term: op.term, definition: op.definition };
    case "interpretation.reject":
      return { kind: "interpretation.reject", proposal_id: op.proposal_id };
    case "confirm":
      return { kind: "confirm", card_ids: [...op.card_ids] };
    case "undo":
      return { kind: "undo", steps: stepsTo(state, op.to_revision_seq) };
  }
}

/** A template in the classifier's shape, "$choice" where the chosen id goes. */
export function templateToClassifierOp(t: OperationTemplate): ClassifierOperation {
  switch (t.kind) {
    case "card.create":
      return {
        kind: "card.create",
        card: { kind: t.card.kind, text: t.card.text, rule_id: t.card.kind === "example" ? CHOICE : null, about_card_id: t.card.kind === "question" ? CHOICE : null },
      };
    case "card.update": {
      const a = t.amendment;
      return {
        kind: "card.update",
        card_id: CHOICE,
        patch: {
          text: a === null ? (t.patch.text ?? null) : null,
          text_append: a === null ? null : a.append,
          answer: t.patch.answer ?? null,
          rule_id: t.patch.rule_id ?? null,
          about_card_id: t.patch.about_card_id ?? null,
        },
        amendment: a === null ? null : { from: a.from, to: a.to, scope: a.scope },
      };
    }
    case "card.remove":
      return { kind: "card.remove", card_id: CHOICE, reason: "" };
    case "card.replace":
      return "replacement_card_id" in t
        ? { kind: "card.replace", card_id: CHOICE, replacement: null, replacement_card_id: t.replacement_card_id }
        : { kind: "card.replace", card_id: CHOICE, replacement: { text: t.replacement.text }, replacement_card_id: null };
    case "definition.refine":
      return { kind: "definition.refine", card_id: CHOICE, term: t.term, definition: t.definition };
    case "confirm":
      return { kind: "confirm", card_ids: [CHOICE] };
    case "interpretation.reject":
      return { kind: "interpretation.reject", proposal_id: CHOICE };
  }
}

/** The most recent open clarification the classifier can represent (design §8.7, §6.6); older ones stay click-only. */
function pendingClarification(state: MapState): PendingClarification | null {
  for (let i = state.clarification_order.length - 1; i >= 0; i--) {
    const c = state.clarifications[state.clarification_order[i]!];
    if (!c || c.status !== "open") continue;
    const asking = state.proposals[c.proposal_id];
    if (!asking) continue;
    const classifier = provenanceOf(asking.proposal.classifier);
    const asked_by = asking.proposal.source_utterance_ids[0];
    if (classifier === null || asked_by === undefined) continue;
    const common = {
      proposal_id: c.proposal_id,
      question: c.question,
      intent: asking.proposal.intent,
      asked_by_utterance_id: asked_by,
      source_utterance_ids: [...asking.proposal.source_utterance_ids],
      classifier,
    };
    if (c.pending_operation !== null) {
      return { ...common, kind: "confirm_intent", candidates: [], pending_operations: [toClassifierOp(c.pending_operation, state)] };
    }
    if (c.template !== null && c.candidates.length >= 2) {
      return {
        ...common,
        kind: "choose_target",
        candidates: c.candidates.map((x) => ({ card_id: x.card_id, label: x.label })),
        pending_operations: [templateToClassifierOp(c.template)],
      };
    }
    // a pure question, or a template with < 2 candidates: click-only
  }
  return null;
}

export function buildClassifierInput(s: { state: MapState; seqOfEvent: (id: EventId) => number }, utterance: Utterance): ClassifierInput {
  const { state } = s;
  const at = state.utterances.findIndex((u) => u.id === utterance.id);
  const before = at >= 0 ? state.utterances.slice(0, at) : state.utterances.filter((u) => u.id !== utterance.id);
  const speakerOf = new Map<UtteranceId, string | null>(state.utterances.map((u) => [u.id, u.speaker]));
  const cards: CardIndexEntry[] = [];
  for (const id of state.card_order) {
    const card = state.cards[id];
    if (card && INDEX_STATUSES.has(card.status)) cards.push(indexEntry(card, s.seqOfEvent, speakerOf));
  }
  const last = lastProposalRecord(state);
  const rejectable = lastRejectableRecord(state);
  return {
    utterance: toClassifierUtterance(utterance),
    recent: before.slice(-RECENT_UTTERANCES).map(toClassifierUtterance),
    cards,
    last_proposal: last ? proposalRef(state, last) : null,
    last_rejectable: rejectable ? proposalRef(state, rejectable) : null,
    pending_clarification: pendingClarification(state),
  };
}

/* ───────────── toCoreCommands ───────────── */

export interface BridgeContext {
  nextId: ApplyContext["nextId"];
  actorForVoice: (u: Utterance) => string;
}

export interface BridgeResult {
  commands: Command[];
  /** Classifier ops the bridge could not turn into a core operation (operation "unknown"); the server ledgers them. */
  refused: RefusedOperation[];
}

type Draft =
  | { kind: "op"; operation: Operation; suffix: string }
  | { kind: "ask"; question: string; template: OperationTemplate | null; pending_operation: Operation | null; candidates: Candidate[]; suffix: string }
  | { kind: "skip"; refused: RefusedOperation };

const skip = (reason: string, detail: string): Draft => ({ kind: "skip", refused: { operation: "unknown", reason, detail } });

/** "Amendment: " stripped, first letter upper-cased, a trailing full stop ensured. */
function sentenceOf(text: string): string {
  let t = text.trim().replace(/^amendment:\s*/i, "").trim();
  if (t === "") return t;
  t = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

/** Exactly core's resolveTemplate rule for an amendment (design §5.4), so a voice choice and a click give the same text. */
function amendedText(cardText: string, a: Amendment): string {
  if (a.scope === null && a.from !== null && a.from !== "") {
    const at = cardText.toLowerCase().indexOf(a.from.toLowerCase());
    if (at >= 0) return cardText.slice(0, at) + a.to + cardText.slice(at + a.from.length);
  }
  return `${cardText} Amendment: ${a.append}`;
}

function newCardOf(draft: { kind: Card["kind"]; text: string; rule_id: string | null; about_card_id: string | null }): NewCard {
  switch (draft.kind) {
    case "story":
      return { kind: "story", text: draft.text };
    case "rule":
      return { kind: "rule", text: draft.text };
    case "example":
      return { kind: "example", text: draft.text, rule_id: draft.rule_id };
    case "question":
      return { kind: "question", text: draft.text, about_card_id: draft.about_card_id };
  }
}

function patchOf(op: Extract<ClassifierOperation, { kind: "card.update" }>, state: MapState): CardPatch {
  const patch: CardPatch = {};
  if (op.patch.text !== null) patch.text = op.patch.text;
  if (op.patch.text_append !== null) {
    const base = state.cards[op.card_id]?.text;
    const append = op.patch.text_append.trim();
    patch.text = base === undefined ? append : `${base} ${append}`;
  }
  if (op.patch.answer !== null) patch.answer = op.patch.answer;
  if (op.patch.rule_id !== null) patch.rule_id = op.patch.rule_id;
  if (op.patch.about_card_id !== null) patch.about_card_id = op.patch.about_card_id;
  return patch;
}

/** The choose_target template for the clarification's pending operation (design §8.7 table, last-but-two row). */
function templateOf(op: ClassifierOperation, utterance: Utterance): { template: OperationTemplate; suffix: string } | null {
  switch (op.kind) {
    case "card.create":
      if (op.card.kind === "example") return { template: { kind: "card.create", card: { kind: "example", text: op.card.text, rule_id: null } }, suffix: "" };
      if (op.card.kind === "question") return { template: { kind: "card.create", card: { kind: "question", text: op.card.text, about_card_id: null } }, suffix: "" };
      return null;
    case "card.update": {
      const p = op.patch;
      const links: CardPatch = {};
      if (p.answer !== null) links.answer = p.answer;
      if (p.rule_id !== null) links.rule_id = p.rule_id;
      if (p.about_card_id !== null) links.about_card_id = p.about_card_id;
      if (p.text === null && p.text_append === null) {
        return Object.keys(links).length > 0 ? { template: { kind: "card.update", patch: links, amendment: null }, suffix: "" } : null;
      }
      const a = op.amendment;
      const append = sentenceOf(p.text_append ?? "") || sentenceOf(utterance.text);
      return {
        template: {
          kind: "card.update",
          patch: { ...links, text: p.text_append ?? p.text ?? "" },
          amendment: { from: a?.from ?? null, to: a?.to ?? "", scope: a?.scope ?? null, append },
        },
        suffix: "",
      };
    }
    case "card.remove":
      return { template: { kind: "card.remove" }, suffix: op.reason.trim() ? ` — ${op.reason.trim()}` : "" };
    case "card.replace":
      if (op.card_id !== CHOICE) return null;
      if (op.replacement_card_id !== null) return { template: { kind: "card.replace", replacement_card_id: op.replacement_card_id }, suffix: "" };
      if (op.replacement !== null) return { template: { kind: "card.replace", replacement: { text: op.replacement.text } }, suffix: "" };
      return null;
    case "definition.refine":
      return { template: { kind: "definition.refine", term: op.term, definition: op.definition }, suffix: "" };
    case "confirm":
      return { template: { kind: "confirm" }, suffix: "" };
    case "interpretation.reject":
      return { template: { kind: "interpretation.reject" }, suffix: "" };
    case "undo":
      return null;
  }
}

interface MapOpts {
  /** The open clarification this result answers (dismissed: false), or null. */
  answering: Clarification | null;
}

/** One classifier operation → one core operation, a clarification request, or a skip (design §8.7 table). */
function draftOf(op: ClassifierOperation, state: MapState, utterance: Utterance, opts: MapOpts): Draft {
  const clar = opts.answering;
  if (clar && clar.pending_operation !== null && clar.pending_operation.kind === op.kind) {
    // a voice "yes" applies exactly the operation a click on Yes would (design §6.6: same map outcome)
    return { kind: "op", operation: clar.pending_operation, suffix: "" };
  }
  switch (op.kind) {
    case "card.create": {
      const live = select.story(state);
      if (op.card.kind === "story" && live) {
        return { kind: "op", operation: { kind: "card.update", card_id: live.id, patch: { text: op.card.text } }, suffix: " (the map already has a story; updating it)" };
      }
      return { kind: "op", operation: { kind: "card.create", card: newCardOf(op.card) }, suffix: "" };
    }
    case "card.update": {
      if (clar && clar.template?.kind === "card.update" && clar.template.amendment !== null && op.card_id !== CHOICE) {
        const card = state.cards[op.card_id];
        if (card) {
          // the chosen card's text exactly as core's resolveTemplate computes it for a click
          return { kind: "op", operation: { kind: "card.update", card_id: op.card_id, patch: { ...clar.template.patch, text: amendedText(card.text, clar.template.amendment) } }, suffix: "" };
        }
      }
      return { kind: "op", operation: { kind: "card.update", card_id: op.card_id, patch: patchOf(op, state) }, suffix: "" };
    }
    case "card.remove":
      return { kind: "op", operation: { kind: "card.remove", card_id: op.card_id }, suffix: op.reason.trim() ? ` — ${op.reason.trim()}` : "" };
    case "card.replace":
      if (op.replacement_card_id !== null) return { kind: "op", operation: { kind: "card.replace", card_id: op.card_id, replacement_card_id: op.replacement_card_id }, suffix: "" };
      if (op.replacement !== null) return { kind: "op", operation: { kind: "card.replace", card_id: op.card_id, replacement: { text: op.replacement.text } }, suffix: "" };
      return skip("BAD_SHAPE", "classifier op card.replace skipped: it names neither a replacement text nor a replacement card");
    case "definition.refine":
      return { kind: "op", operation: { kind: "definition.refine", card_id: op.card_id, term: op.term, definition: op.definition }, suffix: "" };
    case "interpretation.reject":
      return { kind: "op", operation: { kind: "interpretation.reject", proposal_id: op.proposal_id }, suffix: "" };
    case "confirm": {
      const live = op.card_ids.filter((id) => isLive(state.cards[id]));
      if (live.length > 0) return { kind: "op", operation: { kind: "confirm", card_ids: live, proposal_ids: [] }, suffix: "" };
      const last = lastProposalRecord(state);
      const lastOp = last?.proposal.operation ?? null;
      if (last && last.status === "applied" && lastOp !== null && ACT_KINDS.includes(lastOp.kind)) {
        return { kind: "op", operation: { kind: "confirm", card_ids: [], proposal_ids: [last.proposal.id] }, suffix: "" };
      }
      return skip(
        "NOTHING_TO_CONFIRM",
        op.card_ids.length > 0
          ? `classifier op confirm skipped: none of ${op.card_ids.join(", ")} is live`
          : "classifier op confirm skipped: no card named and the last proposal is not an applied removal, undo or rejection",
      );
    }
    case "undo": {
      const target = select.undoTarget(state, op.steps);
      if (target === null) return skip("UNDO_NO_EARLIER_REVISION", `classifier op undo skipped: there are fewer than ${op.steps} step(s) to undo`);
      if (!clar && select.currentRevision(state).cause === "undo.applied" && !/\bredo\b/i.test(utterance.text)) {
        return { kind: "ask", question: REDO_QUESTION, template: null, pending_operation: { kind: "undo", to_revision_seq: target }, candidates: [], suffix: "" };
      }
      return { kind: "op", operation: { kind: "undo", to_revision_seq: target }, suffix: "" };
    }
  }
}

/** The clarification request of a needs_clarification result (design §8.7). */
function askDraft(p: ClassifierProposal, state: MapState, utterance: Utterance): Draft {
  const c = p.clarification;
  const first = c?.pending_operations[0];
  if (!c || !first) return skip("CLARIFICATION_SHAPE", "classifier asked for clarification without a pending operation");
  if (c.kind === "confirm_intent") {
    const d = draftOf(first, state, utterance, { answering: null });
    if (d.kind === "skip") return d;
    if (d.kind === "ask") return { ...d, question: c.question };
    return { kind: "ask", question: c.question, template: null, pending_operation: d.operation, candidates: [], suffix: d.suffix };
  }
  const t = templateOf(first, utterance);
  if (t === null) return skip("CLARIFICATION_SHAPE", `classifier asked which card for ${first.kind}, which has no target template`);
  return {
    kind: "ask",
    question: c.question,
    template: t.template,
    pending_operation: null,
    candidates: c.candidates.map((x) => ({ card_id: x.card_id, label: x.label, score: null })),
    suffix: t.suffix,
  };
}

function openClarificationFor(state: MapState, proposalId: string): Clarification | null {
  for (const id of state.clarification_order) {
    const c = state.clarifications[id];
    if (c && c.status === "open" && c.proposal_id === proposalId) return c;
  }
  return null;
}

/**
 * The commands for one classifier result plus the classifier ops it had to skip. `state` is the state the commands will be
 * applied to (the server calls this under the session's write mutex).
 */
export function bridgeProposal(p: ClassifierProposal, state: MapState, utterance: Utterance, ctx: BridgeContext): BridgeResult {
  const commands: Command[] = [];
  const refused: RefusedOperation[] = [];
  let answering: Clarification | null = null;

  if (p.resolves) {
    const clar = openClarificationFor(state, p.resolves.proposal_id);
    if (clar) {
      const actor = ctx.actorForVoice(utterance);
      if (p.resolves.dismissed) {
        commands.push({ kind: "clarification.answer", clarification_id: clar.id, answer: { kind: "dismiss", reason: utterance.text }, actor });
      } else {
        answering = clar;
        if (!clar.text_answers.some((t) => t.utterance_id === utterance.id)) {
          commands.push({
            kind: "clarification.answer", clarification_id: clar.id,
            answer: { kind: "text", text: utterance.text, utterance_id: utterance.id }, actor,
          });
        }
      }
    }
  }

  const drafts: Draft[] = [];
  if (p.needs_clarification) drafts.push(askDraft(p, state, utterance));
  else for (const op of p.operations) drafts.push(draftOf(op, state, utterance, { answering }));

  const confidence = round2(p.confidence);
  const proposals: Proposal[] = [];
  for (const d of drafts) {
    if (d.kind === "skip") {
      refused.push(d.refused);
      continue;
    }
    const resolving = answering !== null;
    const operation = d.kind === "op" ? d.operation : null;
    const kind = operation?.kind ?? (d.kind === "ask" ? (d.template?.kind ?? d.pending_operation?.kind) : undefined);
    if (kind === undefined) {
      refused.push({ operation: "unknown", reason: "CLARIFICATION_SHAPE", detail: "a clarification with neither a template nor a pending operation" });
      continue;
    }
    // the person behind it: a resolving answer's speaker; a voice confirmation's speaker label (or null when none was
    // assigned); null for a pure AI interpretation
    let actor: string | null = null;
    if (resolving) actor = ctx.actorForVoice(utterance);
    else if (operation?.kind === "confirm") actor = utterance.speaker;
    proposals.push({
      id: ctx.nextId("prop"),
      intent: intentOf(kind),
      operation,
      template: d.kind === "ask" ? d.template : null,
      pending_operation: d.kind === "ask" ? d.pending_operation : null,
      candidates: d.kind === "ask" ? d.candidates : [],
      confidence,
      needs_clarification: operation === null,
      question: d.kind === "ask" ? d.question : null,
      source_utterance_ids: [...p.source_utterance_ids],
      classifier: { ...p.classifier, actor },
      resolves_clarification_id: resolving && proposals.length === 0 ? answering!.id : null,
      rationale: `${p.rationale}${d.suffix}`,
    });
  }
  if (proposals.length > 0) commands.push({ kind: "proposal.propose", proposals });
  return { commands, refused };
}

/** The core commands for one classifier result (design §8.7); bridgeProposal() also returns the skipped ops. */
export function toCoreCommands(p: ClassifierProposal, state: MapState, utterance: Utterance, ctx: BridgeContext): Command[] {
  return bridgeProposal(p, state, utterance, ctx).commands;
}
