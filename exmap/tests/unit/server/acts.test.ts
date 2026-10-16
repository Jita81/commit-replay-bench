// TEST-PLAN §4.6 — the human acts of design §8.5 (proposals, clarifications, cards, questions, undo, review marks).
import { describe, expect, it } from "vitest";
import { SIGNOFF_CONFIRMATION_TEXT, select } from "../../../src/core/index.js";
import type { ActResponse, ClassificationSummary, ClassifierOperation, ExmapEvent } from "../../../src/core/types.js";
import {
  call, createSession, eventsOf, json, makeApp, none, op, ops, postUtterance, proposal, types, uttId, type FakeClassifier, type TestApp,
} from "./helpers.js";

const STORY = "A patient can cancel an appointment online.";

interface Ctx extends TestApp {
  sid: string;
}

async function setup(): Promise<Ctx> {
  const t = await makeApp();
  const s = await createSession(t.app, { story: STORY });
  return { ...t, sid: s.id };
}

/** An AI proposal from one utterance (wait=1); returns its summary and the created card id, if any. */
async function voice(c: Ctx, text: string, step: Parameters<FakeClassifier["push"]>[0], speaker: string | null = "Priya"): Promise<{ summary: ClassificationSummary; utt: string; card: string | null }> {
  c.classifier.push(step);
  const utt = uttId();
  const res = await postUtterance(c.app, c.sid, utt, text, { speaker });
  const summary = json<{ classification: ClassificationSummary }>(res).classification;
  const made = eventsOf(c.app, c.sid).find((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made" && e.proposal.id === summary.proposals[0]?.proposal_id);
  return { summary, utt, card: made?.effects.find((f) => f.before === null)?.card_id ?? null };
}

const addOp = (kind: "rule" | "example" | "question", text: string, links: { rule_id?: string; about_card_id?: string } = {}): ClassifierOperation => op.create(kind, text, links);

async function post(c: Ctx, path: string, body: unknown) {
  return call(c.app, "POST", `/api/sessions/${c.sid}${path}`, body);
}

async function chooseTarget(c: Ctx, candidates: string[], pending: ClassifierOperation): Promise<{ cid: string; pid: string; utt: string }> {
  const r = await voice(c, "Delete that example.", (input) => proposal(input, {
    intent: "remove", confidence: 0.5, needs_clarification: true,
    clarification: { kind: "choose_target", question: "Which example do you mean?", candidates: candidates.map((id, i) => ({ card_id: id, label: `candidate ${i + 1}` })), pending_operations: [pending] },
  }));
  return { cid: r.summary.proposals[0]!.clarification_id!, pid: r.summary.proposals[0]!.proposal_id, utt: r.utt };
}

async function twoExamples(c: Ctx): Promise<{ rule: string; e1: string; e2: string }> {
  const rule = (await voice(c, "No cancelling within two hours.", ops("add", [addOp("rule", "A patient cannot cancel within two hours of the appointment.")]))).card!;
  const e1 = (await voice(c, "GP example.", ops("add", [addOp("example", "A GP appointment at 10am cancelled at 9am is refused.", { rule_id: rule })]))).card!;
  const e2 = (await voice(c, "Nurse example.", ops("add", [addOp("example", "A nurse appointment at 10am cancelled at 7am is allowed.", { rule_id: rule })]))).card!;
  return { rule, e1, e2 };
}

describe("proposal accept / reject", () => {
  it("accept of a content proposal → proposal.confirmed naming the card, stamped human with actor Ana", async () => {
    const c = await setup();
    const { summary, card } = await voice(c, "No cancelling within two hours.", ops("add", [addOp("rule", "A patient cannot cancel within two hours of the appointment.")]));
    const pid = summary.proposals[0]!.proposal_id;
    const res = await post(c, `/proposals/${pid}/accept`, { actor: "Ana" });
    expect(res.statusCode).toBe(200);
    const body = json<ActResponse>(res);
    expect(types(body.events)).toEqual(["proposal.made", "proposal.confirmed"]);
    const made = body.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>;
    expect(made.proposal.classifier).toMatchObject({ provider: "human", actor: "Ana" });
    expect(made.proposal.rationale).toBe("accepted by Ana");
    expect(body.proposal_id).toBe(made.proposal.id);
    const confirmed = body.events[1] as Extract<ExmapEvent, { type: "proposal.confirmed" }>;
    expect(confirmed.card_ids).toEqual([card]);
    expect(confirmed.confirms_proposal_ids).toEqual([pid]);
    expect(c.app.exmap.store.open(c.sid).state.cards[card!]!.confirmation?.by).toEqual({ provider: "human", actor: "Ana", confidence: 1 });
  });

  it("accept of a removal → 200 with confirms_proposal_ids [pid], no effects, and no unreviewed acts left", async () => {
    const c = await setup();
    const { e2 } = await twoExamples(c);
    const { summary } = await voice(c, "Delete the nurse example.", ops("remove", [op.remove(e2)]));
    const pid = summary.proposals[0]!.proposal_id;
    expect(select.unreviewedActs(c.app.exmap.store.open(c.sid).state).map((p) => p.proposal.id)).toEqual([pid]);
    const res = await post(c, `/proposals/${pid}/accept`, { actor: "Ana" });
    expect(res.statusCode).toBe(200);
    const confirmed = json<ActResponse>(res).events.find((e): e is Extract<ExmapEvent, { type: "proposal.confirmed" }> => e.type === "proposal.confirmed")!;
    expect(confirmed.confirms_proposal_ids).toEqual([pid]);
    expect(confirmed.effects).toEqual([]);
    expect(confirmed.proposal_ids).toEqual([pid]);
    expect(select.unreviewedActs(c.app.exmap.store.open(c.sid).state)).toEqual([]);
  });

  it("accept of a confirm proposal → 409 PROPOSAL_NOT_CONFIRMABLE; unknown pid → 404; missing actor → 400", async () => {
    const c = await setup();
    const { card } = await voice(c, "No cancelling within two hours.", ops("add", [addOp("rule", "A patient cannot cancel within two hours of the appointment.")]));
    const yes = await voice(c, "Yes, that rule is right.", ops("confirm", [op.confirm([card!])]));
    const res = await post(c, `/proposals/${yes.summary.proposals[0]!.proposal_id}/accept`, { actor: "Ana" });
    expect(res.statusCode).toBe(409);
    expect(json(res)).toMatchObject({ ok: false, reason: "PROPOSAL_NOT_CONFIRMABLE" });
    const unknown = await post(c, "/proposals/prop_nope/accept", { actor: "Ana" });
    expect(unknown.statusCode).toBe(404);
    expect(json(unknown)).toMatchObject({ reason: "PROPOSAL_NOT_FOUND" });
    for (const body of [{}, { actor: "" }, { actor: "   " }, { actor: "x".repeat(81) }, { actor: 7 }]) {
      const r = await post(c, `/proposals/${yes.summary.proposals[0]!.proposal_id}/accept`, body);
      expect(r.statusCode).toBe(400);
      expect(json(r)).toMatchObject({ reason: "ACTOR_REQUIRED" });
    }
    expect((await post(c, "/proposals/prop_nope/reject", { actor: "Ana" })).statusCode).toBe(404);
  });

  it("reject → proposal.rejected and a new revision", async () => {
    const c = await setup();
    const { summary, card } = await voice(c, "No cancelling within two hours.", ops("add", [addOp("rule", "A patient cannot cancel within two hours of the appointment.")]));
    const before = select.currentRevision(c.app.exmap.store.open(c.sid).state).seq;
    const res = await post(c, `/proposals/${summary.proposals[0]!.proposal_id}/reject`, { actor: "Ana" });
    expect(res.statusCode).toBe(200);
    const events = json<ActResponse>(res).events;
    expect(types(events)).toEqual(["proposal.made", "proposal.rejected"]);
    const state = c.app.exmap.store.open(c.sid).state;
    expect(select.currentRevision(state).seq).toBe(before + 1);
    expect(state.cards[card!]!.rejection?.kind).toBe("interpretation_rejected");
    const again = await post(c, `/proposals/${summary.proposals[0]!.proposal_id}/reject`, { actor: "Ana" });
    expect(again.statusCode).toBe(409);
    expect(json(again)).toMatchObject({ reason: "PROPOSAL_NOT_REJECTABLE" });
  });
});

describe("clarification answers", () => {
  it("candidate → [clarification.answered, proposal.made, proposal.applied] with the asking provider and actor Ana", async () => {
    const c = await setup();
    const { e1, e2 } = await twoExamples(c);
    const { cid } = await chooseTarget(c, [e1, e2], op.remove("$choice"));
    const res = await post(c, `/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "candidate", card_id: e1 } });
    expect(res.statusCode).toBe(200);
    const body = json<ActResponse>(res);
    expect(types(body.events)).toEqual(["clarification.answered", "proposal.made", "proposal.applied"]);
    const made = body.events[1] as Extract<ExmapEvent, { type: "proposal.made" }>;
    expect(made.proposal.classifier).toMatchObject({ provider: "rules.v1", actor: "Ana" });
    expect(made.proposal.resolves_clarification_id).toBe(cid);
    expect(body.proposal_id).toBe(made.proposal.id);
    const state = c.app.exmap.store.open(c.sid).state;
    expect(state.cards[e1]!.status).toBe("rejected");
    expect(state.clarifications[cid]!.status).toBe("answered");
    const again = await post(c, `/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "candidate", card_id: e2 } });
    expect(again.statusCode).toBe(409);
    expect(json(again)).toMatchObject({ reason: "CLARIFICATION_NOT_ANSWERABLE" });
  });

  it("yes on a pending_operation clarification → the same shape; yes on a template clarification → 409 CLARIFICATION_NO_OPERATION", async () => {
    const c = await setup();
    const { e1, e2 } = await twoExamples(c);
    const ask = await voice(c, "Maybe drop the nurse example?", (input) => proposal(input, {
      intent: "remove", confidence: 0.45, needs_clarification: true,
      clarification: { kind: "confirm_intent", question: "Remove the nurse example?", candidates: [], pending_operations: [op.remove(e2)] },
    }));
    const cid = ask.summary.proposals[0]!.clarification_id!;
    const res = await post(c, `/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "yes" } });
    expect(res.statusCode).toBe(200);
    expect(types(json<ActResponse>(res).events)).toEqual(["clarification.answered", "proposal.made", "proposal.applied"]);
    expect(c.app.exmap.store.open(c.sid).state.cards[e2]!.status).toBe("rejected");

    const tmpl = await chooseTarget(c, [e1, (await voice(c, "Another.", ops("add", [addOp("example", "A dentist appointment cancelled the day before is allowed.")]))).card!], op.remove("$choice"));
    const no = await post(c, `/clarifications/${tmpl.cid}/answer`, { actor: "Ana", answer: { kind: "yes" } });
    expect(no.statusCode).toBe(409);
    expect(json(no)).toMatchObject({ reason: "CLARIFICATION_NO_OPERATION" });
    const missing = await post(c, "/clarifications/clar_nope/answer", { actor: "Ana", answer: { kind: "yes" } });
    expect(missing.statusCode).toBe(404);
    expect((await post(c, `/clarifications/${tmpl.cid}/answer`, { actor: "Ana", answer: { kind: "maybe" } })).statusCode).toBe(400);
  });

  it("text → 201 at once with a manual utterance by the actor and a text answer (still open); with wait=1 the classifier sees the clarification and its resolving proposal closes it", async () => {
    const c = await setup();
    const { e1, e2 } = await twoExamples(c);
    const { cid, pid, utt: askedBy } = await chooseTarget(c, [e1, e2], op.remove("$choice"));

    // without wait: 201, the utterance and the text answer, the clarification still open
    c.classifier.push((input) => none(input));
    const quick = await post(c, `/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "text", text: "Hmm, let me think." } });
    expect(quick.statusCode).toBe(201);
    const qb = json<ActResponse & { utterance_id: string }>(quick);
    expect(types(qb.events)).toEqual(["utterance.recorded", "clarification.answered"]);
    const rec = qb.events[0] as Extract<ExmapEvent, { type: "utterance.recorded" }>;
    expect(rec.utterance).toMatchObject({ id: qb.utterance_id, lane: "manual", speaker: "Ana", provider: "manual", is_local: true, confidence: null, model: null });
    expect(rec.utterance.t_start_ms).toBe(rec.utterance.t_end_ms);
    expect(qb.events[1]).toMatchObject({ type: "clarification.answered", answer: { kind: "text", text: "Hmm, let me think.", utterance_id: qb.utterance_id }, actor: "Ana", resolved_by_proposal_id: null });
    await c.app.exmap.store.open(c.sid).classificationsIdle();
    expect(c.app.exmap.store.open(c.sid).state.clarifications[cid]!.status).toBe("open");

    // with wait: the classifier answers the pending clarification
    c.classifier.push((input) => {
      expect(input.pending_clarification?.proposal_id).toBe(pid);
      expect(input.utterance.lane).toBe("manual");
      return proposal(input, {
        intent: "remove", confidence: 1, operations: [op.remove(e1)], source_utterance_ids: [input.utterance.id, askedBy],
        resolves: { proposal_id: pid, chosen_card_ids: [e1], dismissed: false }, rationale: "You chose candidate 1.",
      });
    });
    const res = await post(c, `/clarifications/${cid}/answer?wait=1`, { actor: "Ana", answer: { kind: "text", text: "The GP one." } });
    expect(res.statusCode).toBe(201);
    const body = json<ActResponse & { utterance_id: string; resolved: boolean; classification: ClassificationSummary }>(res);
    expect(body.resolved).toBe(true);
    expect(body.classification.proposals).toHaveLength(1);
    const state = c.app.exmap.store.open(c.sid).state;
    expect(state.clarifications[cid]!.status).toBe("answered");
    expect(state.clarifications[cid]!.text_answers.map((t) => t.text)).toEqual(["Hmm, let me think.", "The GP one."]);
    expect(state.cards[e1]!.status).toBe("rejected");
    const resolver = state.proposals[body.classification.proposals[0]!.proposal_id]!.proposal;
    expect(resolver.classifier.actor).toBe("Ana");
  });

  it("a text answer classified as none → resolved false, still open, and a later candidate click succeeds; dismiss → dismissed", async () => {
    const c = await setup();
    const { e1, e2 } = await twoExamples(c);
    const { cid } = await chooseTarget(c, [e1, e2], op.remove("$choice"));
    c.classifier.push((input) => none(input));
    const res = await post(c, `/clarifications/${cid}/answer?wait=1`, { actor: "Ana", answer: { kind: "text", text: "Not sure yet." } });
    expect(res.statusCode).toBe(201);
    expect(json<{ resolved: boolean }>(res).resolved).toBe(false);
    expect(c.app.exmap.store.open(c.sid).state.clarifications[cid]!.status).toBe("open");
    expect((await post(c, `/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "candidate", card_id: e2 } })).statusCode).toBe(200);
    expect((await post(c, `/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "text", text: "late" } })).statusCode).toBe(409);

    const second = await chooseTarget(c, [e1, (await voice(c, "Another.", ops("add", [addOp("example", "A dentist appointment cancelled the day before is allowed.")]))).card!], op.remove("$choice"));
    const noReason = await post(c, `/clarifications/${second.cid}/answer`, { actor: "Ana", answer: { kind: "dismiss", reason: "" } });
    expect(noReason.statusCode).toBe(400);
    expect(json(noReason)).toMatchObject({ reason: "REASON_REQUIRED" });
    const dismissed = await post(c, `/clarifications/${second.cid}/answer`, { actor: "Ana", answer: { kind: "dismiss", reason: "We keep them all." } });
    expect(dismissed.statusCode).toBe(200);
    expect(types(json<ActResponse>(dismissed).events)).toEqual(["clarification.answered"]);
    expect(c.app.exmap.store.open(c.sid).state.clarifications[second.cid]!.status).toBe("dismissed");
    const empty = await post(c, `/clarifications/${second.cid}/answer`, { actor: "Ana", answer: { kind: "text", text: "  " } });
    expect(empty.statusCode).toBe(409);
  });
});

describe("cards, questions, undo", () => {
  it("cards: create / confirm / remove / update; an empty patch → 422 PATCH_EMPTY", async () => {
    const c = await setup();
    const created = await post(c, "/cards", { actor: "Ana", card: { kind: "rule", text: "A receptionist may cancel for a patient." } });
    expect(created.statusCode).toBe(200);
    const cb = json<ActResponse>(created);
    expect(types(cb.events)).toEqual(["proposal.made", "proposal.applied"]);
    const rule = (cb.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;
    const confirmed = await post(c, `/cards/${rule}/confirm`, { actor: "Ana" });
    expect(confirmed.statusCode).toBe(200);
    expect(types(json<ActResponse>(confirmed).events)).toEqual(["proposal.made", "proposal.confirmed"]);
    const updated = await post(c, `/cards/${rule}/update`, { actor: "Ana", patch: { text: "A receptionist may cancel for a patient who phones." } });
    expect(updated.statusCode).toBe(200);
    const state1 = c.app.exmap.store.open(c.sid).state;
    expect(state1.cards[rule]).toMatchObject({ version: 2, status: "applied", text: "A receptionist may cancel for a patient who phones." });
    const empty = await post(c, `/cards/${rule}/update`, { actor: "Ana", patch: {} });
    expect(empty.statusCode).toBe(422);
    expect(json(empty)).toMatchObject({ reason: "PATCH_EMPTY" });
    const removed = await post(c, `/cards/${rule}/remove`, { actor: "Ana" });
    expect(removed.statusCode).toBe(200);
    const state2 = c.app.exmap.store.open(c.sid).state;
    expect(state2.cards[rule]!.rejection?.kind).toBe("removed");
    expect(select.unreviewedActs(state2)).toEqual([]); // a human removal has an actor
    const story = await post(c, "/cards", { actor: "Ana", card: { kind: "story", text: "Another story." } });
    expect(story.statusCode).toBe(409);
    expect(json(story)).toMatchObject({ reason: "STORY_ALREADY_EXISTS" });
    const bad = await post(c, "/cards", { actor: "Ana", card: { kind: "epic", text: "x" } });
    expect(bad.statusCode).toBe(422);
    expect((await post(c, `/cards/card_nope/confirm`, { actor: "Ana" })).statusCode).toBeGreaterThanOrEqual(404);
  });

  it("accept-outstanding without a reason → 400 REASON_REQUIRED; with one → question.accepted_outstanding and the answer stays null", async () => {
    const c = await setup();
    const q = await post(c, "/cards", { actor: "Ana", card: { kind: "question", text: "What if the clinic cancels?", about_card_id: null } });
    const qid = (json<ActResponse>(q).events[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;
    const missing = await post(c, `/questions/${qid}/accept-outstanding`, { actor: "Sam" });
    expect(missing.statusCode).toBe(400);
    expect(json(missing)).toMatchObject({ reason: "REASON_REQUIRED" });
    const ok = await post(c, `/questions/${qid}/accept-outstanding`, { actor: "Sam", reason: "To be settled with the practice manager" });
    expect(ok.statusCode).toBe(200);
    expect(types(json<ActResponse>(ok).events)).toEqual(["question.accepted_outstanding"]);
    const card = c.app.exmap.store.open(c.sid).state.cards[qid]!;
    expect(card.kind === "question" && card.answer).toBeNull();
    expect(card.kind === "question" && card.accepted_outstanding).toMatchObject({ by: "Sam", reason: "To be settled with the practice manager" });
    expect((await post(c, `/questions/${qid}/accept-outstanding`, { actor: "Sam", reason: "again" })).statusCode).toBe(409);
  });

  it("undo → undo.applied whose revision hash is the target's", async () => {
    const c = await setup();
    const before = select.currentRevision(c.app.exmap.store.open(c.sid).state);
    await post(c, "/cards", { actor: "Ana", card: { kind: "rule", text: "A receptionist may cancel for a patient." } });
    const res = await post(c, "/undo", { actor: "Ana", to_revision_seq: null });
    expect(res.statusCode).toBe(200);
    const undo = json<ActResponse>(res).events.find((e): e is Extract<ExmapEvent, { type: "undo.applied" }> => e.type === "undo.applied")!;
    expect(undo.to_revision).toEqual({ seq: before.seq, hash: before.hash });
    expect(undo.revision.hash).toBe(before.hash);
    const far = await post(c, "/undo", { actor: "Ana", to_revision_seq: 99 });
    expect(far.statusCode).toBe(409);
  });
});

describe("review marks and sign-off", () => {
  it("review/checks: exactly the sent card_ids are confirmed; wrong kind 422; empty 409; changes_resolved 400; a repeated mark 409", async () => {
    const c = await setup();
    const rule = (await voice(c, "No cancelling within two hours.", ops("add", [addOp("rule", "A patient cannot cancel within two hours of the appointment.")]))).card!;
    const ex = (await voice(c, "GP example.", ops("add", [addOp("example", "A GP appointment at 10am cancelled at 9am is refused.", { rule_id: rule })]))).card!;
    const story = select.story(c.app.exmap.store.open(c.sid).state)!.id;
    const mark = await post(c, "/review/checks", { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [story, rule] });
    expect(mark.statusCode).toBe(200);
    const body = json<ActResponse & { card_ids: string[] }>(mark);
    expect(body.card_ids).toEqual([story, rule]);
    const confirmed = body.events.filter((e): e is Extract<ExmapEvent, { type: "proposal.confirmed" }> => e.type === "proposal.confirmed");
    expect(confirmed).toHaveLength(1);
    expect(confirmed[0]!.card_ids).toEqual([story, rule]);

    const wrong = await post(c, "/review/checks", { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [ex] });
    expect(wrong.statusCode).toBe(422);
    expect(json(wrong)).toMatchObject({ reason: "KIND_MISMATCH" });
    const none = await post(c, "/review/checks", { actor: "Sam", check_id: "examples_reviewed", card_ids: [] });
    expect(none.statusCode).toBe(409);
    expect(json(none)).toMatchObject({ reason: "NOTHING_TO_CONFIRM" });
    const unmarkable = await post(c, "/review/checks", { actor: "Sam", check_id: "changes_resolved", card_ids: [ex] });
    expect(unmarkable.statusCode).toBe(400);
    expect(json(unmarkable)).toMatchObject({ reason: "CHECK_NOT_MARKABLE" });
    expect((await post(c, "/review/checks", { actor: "Sam", check_id: "final_version_recorded", card_ids: [ex] })).statusCode).toBe(400);
    const repeat = await post(c, "/review/checks", { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [story, rule] });
    expect(repeat.statusCode).toBe(409);
    expect(json(repeat)).toMatchObject({ reason: "NOTHING_TO_CONFIRM" });
    const examples = await post(c, "/review/checks", { actor: "Sam", check_id: "examples_reviewed", card_ids: [ex] });
    expect(examples.statusCode).toBe(200);
  });

  it("sign-off needs no actor (the body names the reviewer)", async () => {
    const c = await setup();
    const story = select.story(c.app.exmap.store.open(c.sid).state)!.id;
    expect((await post(c, "/review/checks", { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [story] })).statusCode).toBe(200);
    const hash = select.currentRevision(c.app.exmap.store.open(c.sid).state).hash;
    const res = await post(c, "/signoff", { reviewer: "Sam", statement: SIGNOFF_CONFIRMATION_TEXT, revision_hash: hash });
    expect(res.statusCode).toBe(200);
    expect(types(json<ActResponse>(res).events)).toEqual(["signoff.recorded"]);
  });
});
