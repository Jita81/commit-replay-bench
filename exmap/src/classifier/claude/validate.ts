// exmap/src/classifier/claude/validate.ts — validateModelProposal(m, input, { model }) (design §6.4 steps 1–6).
// A malformed answer is a provider failure (fallback); an unknown id is never invented and never a fallback: it becomes a
// clarification over the cards the model could have meant, or a "none" that records what was heard.
import type { CardKind, ClassifierInput, ClassifierOperation, ClassifierProposal, HeardIntent, Intent } from "../../core/types.js";
import { MAX_CANDIDATES, MIN_CONFIDENCE, RATIONALE_MAX, SYSTEM_PROMPT_VERSION } from "../constants.js";
import { verbPhrase } from "../extract.js";
import { askTarget, bySeqDesc, candidateLabel, type Resolution } from "../referents.js";
import { CHOICE, INTENT_OF_OP, assertProposalInvariants, idsOfOperation, targetCardIds, type ModelProposal } from "../schema.js";

export type ValidateResult = { ok: ClassifierProposal } | { fallback: string };

function hasChoice(ops: ClassifierOperation[]): boolean {
  return JSON.stringify(ops).includes(`"${CHOICE}"`);
}

/** I2 as a boolean: ops bind to the intent with at most one leading reject/confirm prefix; remove may carry several removes. */
function opsBind(intent: Intent, ops: ClassifierOperation[]): boolean {
  if (ops.length === 0) return false;
  let i = 0;
  const first = ops[0]!;
  if (ops.length > 1 && (first.kind === "interpretation.reject" || first.kind === "confirm") && INTENT_OF_OP[first.kind] !== intent) i = 1;
  const rest = ops.slice(i);
  if (rest.length === 0) return false;
  if (!rest.every((op) => INTENT_OF_OP[op.kind] === intent)) return false;
  return rest.length === 1 || intent === "remove";
}

function structure(m: ModelProposal): string | null {
  const clar = m.clarification;
  if (m.needs_clarification !== (clar !== null)) return "invalid:clarification_shape";
  if (m.intent === "none") return m.operations.length === 0 && clar === null ? null : "invalid:none_shape";
  if (clar) {
    if (m.operations.length !== 0) return "invalid:clarification_shape";
    if (clar.kind === "choose_target" && (clar.candidates.length < 2 || !hasChoice(clar.pending_operations))) return "invalid:clarification_shape";
    if (clar.kind === "confirm_intent" && (clar.pending_operations.length !== 1 || hasChoice(clar.pending_operations))) return "invalid:clarification_shape";
    if (!opsBind(m.intent, clar.pending_operations)) return "invalid:intent_op_mismatch";
  } else if (!opsBind(m.intent, m.operations) || hasChoice(m.operations)) {
    return "invalid:intent_op_mismatch";
  }
  for (const op of [...m.operations, ...(clar?.pending_operations ?? [])]) {
    if (op.kind === "card.replace" && (op.replacement === null) === (op.replacement_card_id === null)) return "invalid:replace_shape";
    if (op.kind === "card.replace" && op.replacement_card_id !== null && op.replacement_card_id === op.card_id) return "invalid:replace_shape";
    if (op.kind === "card.update") {
      const p = op.patch;
      if ([p.text, p.text_append, p.answer, p.rule_id, p.about_card_id].every((f) => f === null)) return "invalid:patch";
      if (p.text !== null && p.text_append !== null) return "invalid:patch";
    }
    if (op.kind === "undo" && (!Number.isInteger(op.steps) || op.steps < 1)) return "invalid:undo_steps";
  }
  return null;
}

/** The card kind an operation's primary target must have, when it can be told from the operation. */
function targetKind(op: ClassifierOperation, input: ClassifierInput): CardKind | null {
  switch (op.kind) {
    case "card.update":
      if (op.patch.answer !== null || op.patch.about_card_id !== null) return "question";
      if (op.patch.rule_id !== null) return "example";
      return null;
    case "card.replace": {
      const r = op.replacement_card_id ? input.cards.find((c) => c.id === op.replacement_card_id) : undefined;
      return r?.kind ?? null;
    }
    default:
      return null;
  }
}

function round2(x: number): number {
  return Math.round(x * 100) / 100;
}

function primaryId(op: ClassifierOperation): string | null {
  switch (op.kind) {
    case "card.update": case "card.remove": case "card.replace": case "definition.refine": return op.card_id;
    default: return null;
  }
}

function setPrimary(op: ClassifierOperation, id: string): ClassifierOperation {
  switch (op.kind) {
    case "card.update": case "card.remove": case "card.replace": case "definition.refine": return { ...op, card_id: id };
    default: return op;
  }
}

/** Validates and repairs the model's proposal into a ClassifierProposal, or names the fallback code. */
export function validateModelProposal(m: ModelProposal, input: ClassifierInput, meta: { model: string }): ValidateResult {
  const bad = structure(m);
  if (bad) return { fallback: bad };
  const index = new Map(input.cards.map((c) => [c.id, c] as const));
  let intent: ClassifierProposal["intent"] = m.intent;
  let operations: ClassifierOperation[] = [...m.operations];
  let clarification = m.clarification ? { ...m.clarification, candidates: [...m.clarification.candidates], pending_operations: [...m.clarification.pending_operations] } : null;
  let heard: HeardIntent = null;
  let rationale = m.rationale.trim();
  let resolves = m.resolves;
  const note = (s: string): void => { rationale = `${rationale} ${s}`.trim(); };
  const toNone = (h: Intent, why: string): void => { intent = "none"; operations = []; clarification = null; heard = h; note(why); };

  // 2. ids — links to unknown cards are dropped
  const fixLinks = (op: ClassifierOperation): ClassifierOperation => {
    if (op.kind === "card.create") {
      let card = op.card;
      if (card.rule_id !== null && card.rule_id !== CHOICE && !index.has(card.rule_id)) { card = { ...card, rule_id: null }; note("(link dropped: unknown card)"); }
      if (card.about_card_id !== null && card.about_card_id !== CHOICE && !index.has(card.about_card_id)) { card = { ...card, about_card_id: null }; note("(link dropped: unknown card)"); }
      return { ...op, card };
    }
    if (op.kind === "card.update") {
      let patch = op.patch;
      if (patch.rule_id !== null && !index.has(patch.rule_id)) { patch = { ...patch, rule_id: null }; note("(link dropped: unknown card)"); }
      if (patch.about_card_id !== null && !index.has(patch.about_card_id)) { patch = { ...patch, about_card_id: null }; note("(link dropped: unknown card)"); }
      if ([patch.text, patch.text_append, patch.answer, patch.rule_id, patch.about_card_id].every((f) => f === null)) return op; // handled below as unknown target
      return { ...op, patch };
    }
    return op;
  };
  operations = operations.map(fixLinks);
  if (clarification) clarification.pending_operations = clarification.pending_operations.map(fixLinks);

  // interpretation.reject must name the last rejectable or an index card's proposal
  const indexProposalIds = new Set(input.cards.map((c) => c.proposal_id).filter((x): x is string => x !== null));
  const rejectOk = (id: string): boolean => id === CHOICE || (input.last_rejectable !== null && id === input.last_rejectable.id) || indexProposalIds.has(id);
  const badReject = operations.find((op) => op.kind === "interpretation.reject" && !rejectOk(op.proposal_id))
    ?? clarification?.pending_operations.find((op) => op.kind === "interpretation.reject" && !rejectOk(op.proposal_id));
  if (badReject && intent !== "none") {
    if (intent === "reject") {
      const lr = input.last_rejectable;
      if (lr) {
        intent = "reject";
        operations = [];
        clarification = { kind: "confirm_intent", question: "Did you mean to reject the last interpretation?", candidates: [], pending_operations: [{ kind: "interpretation.reject", proposal_id: lr.id }] };
        note("(the proposal named could not be found)");
      } else {
        toNone("reject", "Heard a rejection, but nothing on the map can be rejected right now.");
      }
    } else {
      // a prefix reject on another intent: drop the prefix op
      operations = operations.filter((op) => !(op.kind === "interpretation.reject" && !rejectOk(op.proposal_id)));
      note("(the leading rejection named an unknown proposal and was dropped)");
    }
  }

  // confirm.card_ids are filtered to index ids
  const actReview = input.last_proposal !== null && input.last_proposal.status === "applied" && ["card.remove", "undo", "interpretation.reject"].includes(input.last_proposal.op);
  if (intent !== "none") {
    const fixConfirm = (ops: ClassifierOperation[]): ClassifierOperation[] | "none" => {
      const out: ClassifierOperation[] = [];
      for (const op of ops) {
        if (op.kind !== "confirm") { out.push(op); continue; }
        const ids = op.card_ids.filter((id) => index.has(id));
        if (ids.length === 0 && !actReview) {
          if (intent === "confirm") return "none";
          continue; // a prefix confirm with nothing live is dropped
        }
        out.push({ ...op, card_ids: ids });
      }
      return out;
    };
    const fixed = fixConfirm(operations);
    if (fixed === "none") toNone("confirm", "Nothing live to confirm.");
    else operations = fixed;
    if (clarification) {
      const pf = fixConfirm(clarification.pending_operations);
      if (pf === "none") toNone("confirm", "Nothing live to confirm.");
      else clarification.pending_operations = pf;
    }
  }

  // any other unknown card id -> ask over the cards the operation could target
  if (intent !== "none") {
    const unknownIn = (op: ClassifierOperation): string | null => {
      const id = primaryId(op);
      if (id !== null && id !== CHOICE && !index.has(id)) return id;
      if (op.kind === "card.replace" && op.replacement_card_id !== null && !index.has(op.replacement_card_id)) return op.replacement_card_id;
      return null;
    };
    const candBad = clarification?.candidates.some((c) => !index.has(c.card_id)) ?? false;
    if (candBad && clarification) {
      clarification.candidates = clarification.candidates.filter((c) => index.has(c.card_id));
      if (clarification.kind === "choose_target" && clarification.candidates.length < 2) return { fallback: "invalid:clarification_shape" };
    }
    const opsToCheck = clarification ? clarification.pending_operations : operations;
    const badOp = opsToCheck.find((op) => unknownIn(op) !== null);
    if (badOp) {
      const unknown = unknownIn(badOp)!;
      if (badOp.kind === "card.replace" && badOp.replacement_card_id === unknown) {
        toNone(intent as Intent, "(the replacement card named could not be found)");
      } else {
        const kind = targetKind(badOp, input);
        const pool = bySeqDesc(input.cards.filter((c) => c.kind !== "story" && (kind === null || c.kind === kind))).slice(0, MAX_CANDIDATES);
        const res: Resolution = pool.length === 0 ? { kind: "none", why: "no such card" } : { kind: "ambiguous", candidates: pool, why: "the card named could not be found" };
        const verb = intent === "amend" ? "change" : intent === "remove" ? "remove" : intent === "replace" ? "replace" : intent === "clarify" ? "define on" : intent as string;
        const base = setPrimary(badOp, CHOICE);
        const ask = askTarget(res, base, intent as Intent, verb, input, { question: `I could not match that to a card. Which did you mean: ${pool.map((c, i) => `(${i + 1}) ${candidateLabel(c, input)}`).join(", ")}?`, kind: kind ?? null });
        if (ask.kind === "none") toNone(intent as Intent, "I could not match that to a card on the map.");
        else {
          operations = [];
          clarification = ask.clarification;
          if (ask.clarification.kind === "confirm_intent") clarification.question = ask.clarification.question.replace(/ \(the card named could not be found\)$/, " (the card named could not be found)");
          note("(the card named could not be found; asking)");
        }
      }
    }
  }

  // 3. resolves
  if (resolves) {
    const pc = input.pending_clarification;
    const chosenOk = pc !== null && (pc.kind === "choose_target" ? resolves.chosen_card_ids.every((id) => pc.candidates.some((c) => c.card_id === id)) : resolves.chosen_card_ids.length === 0);
    if (!pc || resolves.proposal_id !== pc.proposal_id || !chosenOk) {
      const depended = pc !== null && (
        (pc.kind === "choose_target" && operations.some((op) => idsOfOperation(op).some((id) => pc.candidates.some((c) => c.card_id === id))))
        || (pc.kind === "confirm_intent" && JSON.stringify(operations) === JSON.stringify(pc.pending_operations))
        || (resolves.dismissed === false && resolves.chosen_card_ids.length > 0)
      );
      resolves = null;
      if (depended && pc) {
        intent = "none";
        operations = [];
        clarification = null;
        heard = pc.intent;
        rationale = "Please say which one: first or second, or name it.";
      }
    }
  }

  // 4. confidence
  let confidence = round2(Math.min(1, Math.max(0, Number.isFinite(m.confidence) ? m.confidence : 0)));
  if (intent !== "none" && clarification === null && confidence < MIN_CONFIDENCE) {
    const main = operations[operations.length - 1];
    if (main) {
      let detail: Parameters<typeof verbPhrase>[1] = {};
      const id = primaryId(main);
      const card = id ? index.get(id) : undefined;
      if (main.kind === "card.create") detail = { kind: main.card.kind, text: main.card.text };
      else if (main.kind === "definition.refine") detail = { term: main.term, label: card ? candidateLabel(card, input) : undefined };
      else if (card) detail = { label: candidateLabel(card, input) };
      clarification = { kind: "confirm_intent", question: `Did you mean to ${verbPhrase(intent as Intent, detail)}?`, candidates: [], pending_operations: [main] };
      operations = [];
      note(`(low confidence ${confidence}; asking)`);
    }
  }
  if (intent !== "none" && clarification === null && operations.length === 0) return { fallback: "invalid:intent_op_mismatch" };

  // 5–6. recompute, stamp, assert
  const partial = { operations, clarification };
  const rationaleOut = (rationale || "Classified by the model.").replace(/\s+/g, " ").trim();
  const p: ClassifierProposal = {
    intent,
    operations,
    target_card_ids: targetCardIds(partial),
    confidence,
    needs_clarification: clarification !== null,
    clarification,
    resolves: intent === "none" && resolves && !resolves.dismissed ? resolves : resolves,
    rationale: rationaleOut.length > RATIONALE_MAX ? `${rationaleOut.slice(0, RATIONALE_MAX - 1).trimEnd()}…` : rationaleOut,
    heard_intent: intent === "none" ? heard : null,
    classifier: { provider: "claude", model: meta.model, prompt_version: SYSTEM_PROMPT_VERSION, fallback_from: null, error: null },
    source_utterance_ids: resolves && input.pending_clarification ? [input.utterance.id, input.pending_clarification.asked_by_utterance_id] : [input.utterance.id],
  };
  try {
    assertProposalInvariants(p, input);
  } catch (e) {
    return { fallback: `invalid:invariant:${e instanceof Error ? e.message.split(":")[0] ?? "?" : "?"}` };
  }
  return { ok: p };
}

