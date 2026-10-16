// exmap/src/server/routes/acts.ts — the human acts of design §8.5. Every act is a proposal with classifier.provider "human"
// and the actor stamped (nothing a person does is unevented); each answers 200 ActResponse with the whole appended batch,
// including any signoff.invalidated. Core refusals pass through with their status (design §8.2).
import type { FastifyInstance } from "fastify";
import { select } from "../../core/index.js";
import type {
  ActResponse, CardKind, CardPatch, ClarificationAnswer, Command, DodCheckId, ExmapEvent, ExportFact, NewCard, Operation, ProposalId,
} from "../../core/types.js";
import { isCatalogueClass } from "../../export/index.js";
import { badRequest, httpError, refusalError } from "../errors.js";
import type { ClassificationOutcome, Session } from "../session.js";
import { humanProposal } from "../session.js";
import { actorOf, bodyOf, runOrThrow, sessionOf, stringField, wantWait, type Body } from "./common.js";

const ACT_KINDS: readonly Operation["kind"][] = ["card.remove", "undo", "interpretation.reject"];

/** The checks a person can mark from the Review drawer, and the card kinds each covers (design §8.5). */
export const MARKABLE_CHECKS: Readonly<Partial<Record<DodCheckId, readonly CardKind[]>>> = {
  story_rules_confirmed: ["story", "rule"],
  examples_reviewed: ["example"],
  questions_resolved: ["question"],
};

function isLiveStatus(status: string): boolean {
  return status === "applied" || status === "confirmed";
}

/** One human proposal as one proposal.propose command; returns the proposal id with the command. */
function proposeHuman(session: Session, operation: Operation, actor: string, rationale: string): { id: ProposalId; command: Command } {
  const id = session.nextId("prop");
  return { id, command: { kind: "proposal.propose", proposals: [humanProposal(id, operation, actor, rationale)] } };
}

async function humanAct(session: Session, build: () => { operation: Operation; rationale: string }, actor: string): Promise<ActResponse> {
  let pid: ProposalId = "";
  const r = await runOrThrow(session, () => {
    const { operation, rationale } = build();
    const { id, command } = proposeHuman(session, operation, actor, rationale);
    pid = id;
    return command;
  });
  return { ok: true, events: r.events, proposal_id: pid };
}

function stringArray(body: Body, key: string): string[] {
  const v = body[key];
  if (!Array.isArray(v) || !v.every((x) => typeof x === "string")) throw badRequest(`${key} must be an array of strings`);
  return v as string[];
}

const PARAMS = { cardId: (req: { params: unknown }) => (req.params as { cardId: string }).cardId };

export async function actRoutes(app: FastifyInstance): Promise<void> {
  /* ───── proposals ───── */

  app.post("/api/sessions/:id/proposals/:pid/accept", async (req) => {
    const session = sessionOf(app, req);
    const actor = actorOf(bodyOf(req));
    const pid = (req.params as { pid: string }).pid;
    return humanAct(session, () => {
      const record = session.state.proposals[pid];
      if (!record) throw httpError("PROPOSAL_NOT_FOUND", `proposal ${pid} does not exist`);
      const op = record.proposal.operation;
      if (op === null) throw httpError("PROPOSAL_NOT_CONFIRMABLE", `proposal ${pid} asked a question; answer or dismiss the clarification instead`);
      if (op.kind === "confirm") throw httpError("PROPOSAL_NOT_CONFIRMABLE", `proposal ${pid} is itself a confirmation`);
      const rationale = `accepted by ${actor}`;
      if (ACT_KINDS.includes(op.kind)) return { operation: { kind: "confirm", card_ids: [], proposal_ids: [pid] }, rationale };
      const live = record.affected_card_ids.filter((id) => {
        const c = session.state.cards[id];
        return c !== undefined && isLiveStatus(c.status);
      });
      if (live.length === 0) throw httpError("NOTHING_TO_CONFIRM", `proposal ${pid} has no live card left to confirm`);
      return { operation: { kind: "confirm", card_ids: live, proposal_ids: [] }, rationale };
    }, actor);
  });

  app.post("/api/sessions/:id/proposals/:pid/reject", async (req) => {
    const session = sessionOf(app, req);
    const actor = actorOf(bodyOf(req));
    const pid = (req.params as { pid: string }).pid;
    return humanAct(session, () => ({ operation: { kind: "interpretation.reject", proposal_id: pid }, rationale: `rejected by ${actor}` }), actor);
  });

  /* ───── clarifications ───── */

  app.post("/api/sessions/:id/clarifications/:cid/answer", async (req, reply) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const cid = (req.params as { cid: string }).cid;
    const raw = body["answer"];
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) throw badRequest("answer must be an object");
    const a = raw as Body;
    let answer: ClarificationAnswer;
    switch (a["kind"]) {
      case "candidate":
        if (typeof a["card_id"] !== "string") throw badRequest("answer.card_id must be a string");
        answer = { kind: "candidate", card_id: a["card_id"] };
        break;
      case "yes":
        answer = { kind: "yes" };
        break;
      case "dismiss":
        answer = { kind: "dismiss", reason: stringField(a, "reason").trim() };
        break;
      case "text": {
        const text = stringField(a, "text").trim();
        return answerByText(session, cid, text, actor, wantWait(req)).then((res) => reply.code(201).send(res));
      }
      default:
        throw badRequest('answer.kind must be one of "candidate", "yes", "dismiss", "text"');
    }
    const r = await runOrThrow(session, () => ({ kind: "clarification.answer", clarification_id: cid, answer, actor }));
    const answered = r.events.find((e): e is Extract<ExmapEvent, { type: "clarification.answered" }> => e.type === "clarification.answered");
    const res: ActResponse = { ok: true, events: r.events };
    if (answered?.resolved_by_proposal_id) res.proposal_id = answered.resolved_by_proposal_id;
    return res;
  });

  /* ───── cards ───── */

  app.post("/api/sessions/:id/cards", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const card = body["card"];
    if (card === null || typeof card !== "object" || Array.isArray(card)) throw badRequest("card must be an object");
    return humanAct(session, () => ({ operation: { kind: "card.create", card: card as NewCard }, rationale: `added by ${actor}` }), actor);
  });

  app.post("/api/sessions/:id/cards/:cardId/confirm", async (req) => {
    const session = sessionOf(app, req);
    const actor = actorOf(bodyOf(req));
    const cardId = PARAMS.cardId(req);
    return humanAct(session, () => ({ operation: { kind: "confirm", card_ids: [cardId], proposal_ids: [] }, rationale: `confirmed by ${actor}` }), actor);
  });

  app.post("/api/sessions/:id/cards/:cardId/remove", async (req) => {
    const session = sessionOf(app, req);
    const actor = actorOf(bodyOf(req));
    const cardId = PARAMS.cardId(req);
    return humanAct(session, () => ({ operation: { kind: "card.remove", card_id: cardId }, rationale: `removed by ${actor}` }), actor);
  });

  app.post("/api/sessions/:id/cards/:cardId/update", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const cardId = PARAMS.cardId(req);
    const patch = body["patch"];
    if (patch === null || typeof patch !== "object" || Array.isArray(patch)) throw badRequest("patch must be an object");
    return humanAct(session, () => ({ operation: { kind: "card.update", card_id: cardId, patch: patch as CardPatch }, rationale: `edited by ${actor}` }), actor);
  });

  /* ───── questions, undo ───── */

  app.post("/api/sessions/:id/questions/:qid/accept-outstanding", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const reason = stringField(body, "reason").trim();
    const qid = (req.params as { qid: string }).qid;
    const r = await runOrThrow(session, () => ({ kind: "question.accept", question_id: qid, by: actor, reason }));
    return { ok: true, events: r.events } satisfies ActResponse;
  });

  app.post("/api/sessions/:id/undo", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const raw = body["to_revision_seq"];
    if (raw !== undefined && raw !== null && typeof raw !== "number") throw badRequest("to_revision_seq must be a number or null");
    const to_revision_seq = typeof raw === "number" ? raw : null;
    return humanAct(session, () => ({ operation: { kind: "undo", to_revision_seq }, rationale: `undone by ${actor}` }), actor);
  });

  /* ───── review ───── */

  app.post("/api/sessions/:id/review/checks", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const checkId = body["check_id"];
    const kinds = typeof checkId === "string" && Object.hasOwn(MARKABLE_CHECKS, checkId) ? MARKABLE_CHECKS[checkId as DodCheckId] : undefined;
    if (!kinds) {
      throw httpError("CHECK_NOT_MARKABLE", `check ${JSON.stringify(checkId)} cannot be marked; only ${Object.keys(MARKABLE_CHECKS).join(", ")} can (changes and the final version resolve themselves)`);
    }
    const cardIds = stringArray(body, "card_ids");
    const res = await humanAct(session, () => {
      if (cardIds.length === 0) throw httpError("NOTHING_TO_CONFIRM", "the mark lists no cards");
      for (const id of cardIds) {
        const card = session.state.cards[id];
        if (!card) throw httpError("CARD_NOT_FOUND", `card ${id} does not exist`);
        if (!isLiveStatus(card.status)) throw httpError("CARD_NOT_LIVE", `card ${id} is ${select.statusLabel(card)}, not live`);
        if (!kinds.includes(card.kind)) throw httpError("KIND_MISMATCH", `card ${id} is a ${card.kind}; ${String(checkId)} covers ${kinds.join(" and ")} cards`);
      }
      // exactly the card_ids the person saw
      return { operation: { kind: "confirm", card_ids: [...cardIds], proposal_ids: [] }, rationale: `review check ${String(checkId)} marked by ${actor}` };
    }, actor);
    return { ...res, card_ids: cardIds };
  });

  /* ───── sign-off ───── */

  app.post("/api/sessions/:id/signoff", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const reviewer = stringField(body, "reviewer").trim();
    const statement = stringField(body, "statement");
    const revisionHash = stringField(body, "revision_hash").trim();
    const r = await runOrThrow(session, () => ({ kind: "signoff.record", reviewer: { name: reviewer }, confirmation_text: statement, cited_revision_hash: revisionHash }));
    return { ok: true, events: r.events } satisfies ActResponse;
  });

  /* ───── export options ───── */

  app.put("/api/sessions/:id/export-options", async (req) => {
    const session = sessionOf(app, req);
    const body = bodyOf(req);
    const actor = actorOf(body);
    const cls = stringField(body, "capability_class").trim();
    if (cls !== "unclassified" && !isCatalogueClass(cls)) {
      throw httpError("CLASS_UNKNOWN", `capability class ${JSON.stringify(cls)} is not in the vendored crb catalogue (or "unclassified")`);
    }
    const facts = body["facts"] === undefined ? [] : body["facts"];
    const r = await runOrThrow(session, () => ({
      kind: "export.options_set",
      options: { capability_class: cls, kind: body["kind"] as never, size_estimate: body["size_estimate"] as never, facts: facts as ExportFact[], by: actor },
    }));
    const set = r.events.find((e): e is Extract<ExmapEvent, { type: "export.options_set" }> => e.type === "export.options_set")!;
    return { ok: true, events: r.events, export_options: set.options };
  });
}

/**
 * A typed answer (design §8.5): in one mutex section, a manual utterance spoken by the actor, the text answer (the
 * clarification stays open), and the classification enqueued exactly as for a posted utterance. 201 at once; ?wait=1 adds
 * the classification and whether a proposal of that run resolved this clarification.
 */
async function answerByText(session: Session, cid: string, text: string, actor: string, wait: boolean): Promise<ActResponse & { utterance_id: string; classification?: ClassificationOutcome["summary"]; resolved?: boolean }> {
  let job: Promise<ClassificationOutcome | null> | null = null;
  let utteranceId = "";
  const events = await session.exclusive((): ExmapEvent[] => {
    const clar = session.state.clarifications[cid];
    if (!clar) throw httpError("CLARIFICATION_NOT_FOUND", `clarification ${cid} does not exist`);
    if (clar.status !== "open") throw httpError("CLARIFICATION_NOT_ANSWERABLE", `clarification ${cid} is ${clar.status}`);
    if (text === "") throw httpError("EMPTY_TEXT", "the text answer is empty");
    if (session.broken) throw session.brokenError();
    utteranceId = session.nextId("utt");
    const t = session.sessionMs();
    const recorded = session.applyLocked({
      kind: "utterance.record",
      utterance: { id: utteranceId, text, lane: "manual", speaker: actor, provider: "manual", model: null, t_start_ms: t, t_end_ms: t, is_local: true, confidence: null },
    });
    if (!recorded.ok) throw refusalError(recorded);
    const answered = session.applyLocked({ kind: "clarification.answer", clarification_id: cid, answer: { kind: "text", text, utterance_id: utteranceId }, actor });
    job = session.classify(utteranceId); // the utterance is recorded, so it is classified whatever the answer's fate
    if (!answered.ok) throw refusalError(answered);
    return [...recorded.events, ...answered.events];
  });
  const res: ActResponse & { utterance_id: string; classification?: ClassificationOutcome["summary"]; resolved?: boolean } = { ok: true, events, utterance_id: utteranceId };
  if (wait && job) {
    const outcome = await (job as Promise<ClassificationOutcome | null>);
    if (outcome) res.classification = outcome.summary;
    res.resolved = (outcome?.proposal_ids ?? []).some((pid) => session.state.proposals[pid]?.proposal.resolves_clarification_id === cid);
  }
  return res;
}
