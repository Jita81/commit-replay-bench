// TEST-PLAN §4.4 — POST /api/sessions/:id/utterances: 201 before classification, ?wait=1, refusals, the serial
// classification chain, the stale-answer guard and close() during an in-flight classify (design §8.4).
import { describe, expect, it } from "vitest";
import { ClassifierError } from "../../../src/classifier/types.js";
import type { ClassificationSummary, ClassifierProposal, ExmapEvent, UtterancePostResponse } from "../../../src/core/types.js";
import {
  awaitClassified, call, createSession, deferred, eventsOf, json, makeApp, none, op, ops, postUtterance, proposal, readLedger, types, uttId,
  wireUtterance, type Step,
} from "./helpers.js";

const STORY = "A patient can cancel an appointment online.";
const RULE = "A patient cannot cancel within two hours of the appointment.";

type Classified = Extract<ExmapEvent, { type: "utterance.classified" }>;

describe("POST …/utterances", () => {
  it("without wait: 201 arrives before the classifier resolves and the body is exactly { ok, event }", async () => {
    const gate = deferred<void>();
    const { app, classifier } = await makeApp();
    classifier.push(async (input) => {
      await gate.promise;
      return proposal(input, { intent: "add", operations: [op.create("rule", RULE)] });
    });
    const s = await createSession(app);
    const id = uttId();
    const res = await postUtterance(app, s.id, id, RULE, { wait: false });
    expect(res.statusCode).toBe(201);
    const body = json<UtterancePostResponse>(res);
    expect(Object.keys(body).sort()).toEqual(["event", "ok"]);
    expect(body).toMatchObject({ ok: true, event: { seq: 1 } });
    expect(types(eventsOf(app, s.id))).toEqual(["utterance.recorded"]);
    gate.resolve();
    const classified = await awaitClassified(app, s.id, id);
    expect(classified.proposal_ids).toHaveLength(1);
  });

  it("with wait=1: the classification summary names the proposal's events, and utterance.classified follows naming it", async () => {
    const { app, classifier } = await makeApp();
    classifier.push(ops("add", [op.create("rule", RULE)]));
    const s = await createSession(app);
    const id = uttId();
    const res = await postUtterance(app, s.id, id, RULE);
    expect(res.statusCode).toBe(201);
    const body = json<UtterancePostResponse & { classification: ClassificationSummary }>(res);
    expect(body.event.seq).toBe(1);
    const c = body.classification;
    expect(c.intent).toBe("add");
    expect(c.proposals).toHaveLength(1);
    expect(c.proposals[0]!.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied"]);
    expect(c.proposals[0]!.status).toBe("applied");
    expect(c.proposals[0]!.clarification_id).toBeNull();
    const events = eventsOf(app, s.id);
    expect(types(events)).toEqual(["utterance.recorded", "proposal.made", "proposal.applied", "utterance.classified"]);
    const classified = events[3] as Classified;
    expect(classified.proposal_ids).toEqual([c.proposals[0]!.proposal_id]);
    expect(c.event).toEqual({ id: classified.id, seq: classified.seq });
  });

  it("a duplicate id → 409 DUPLICATE_ID with the original { id, seq, hash } and no second classification", async () => {
    const { app, classifier } = await makeApp();
    const s = await createSession(app);
    const id = uttId();
    const first = json<UtterancePostResponse>(await postUtterance(app, s.id, id, "Hello everyone."));
    const again = await postUtterance(app, s.id, id, "Hello everyone.");
    expect(again.statusCode).toBe(409);
    expect(json(again)).toMatchObject({ ok: false, reason: "DUPLICATE_ID", event: first.event });
    await app.exmap.store.open(s.id).classificationsIdle();
    expect(classifier.calls).toHaveLength(1);
    expect(types(eventsOf(app, s.id))).toEqual(["utterance.recorded", "utterance.classified"]);
  });

  it("refusals: blank text 422 EMPTY_TEXT; a bad lane, a missing is_local, an extra key 422 BAD_REQUEST with issues; end < start 422 INVALID_TIMING", async () => {
    const { app } = await makeApp();
    const s = await createSession(app);
    const url = `/api/sessions/${s.id}/utterances`;
    const blank = await call(app, "POST", url, wireUtterance(uttId(), "  "));
    expect(blank.statusCode).toBe(422);
    expect(json(blank)).toMatchObject({ ok: false, reason: "EMPTY_TEXT" });

    const badLane = await call(app, "POST", url, { ...wireUtterance(uttId(), "Hello."), lane: "phone" });
    expect(badLane.statusCode).toBe(422);
    expect(json(badLane)).toMatchObject({ ok: false, reason: "BAD_REQUEST" });
    expect(Array.isArray(json<{ issues: unknown[] }>(badLane).issues)).toBe(true);
    expect(json<{ issues: unknown[] }>(badLane).issues.length).toBeGreaterThan(0);

    const { is_local: _drop, ...missing } = wireUtterance(uttId(), "Hello.") as Record<string, unknown>;
    const noLocal = await call(app, "POST", url, missing);
    expect(noLocal.statusCode).toBe(422);
    expect(json(noLocal)).toMatchObject({ reason: "BAD_REQUEST" });

    const extra = await call(app, "POST", url, { ...wireUtterance(uttId(), "Hello."), diarised_speaker: "Bob" });
    expect(extra.statusCode).toBe(422);
    expect(json(extra)).toMatchObject({ reason: "BAD_REQUEST" });

    const timing = await call(app, "POST", url, { ...wireUtterance(uttId(), "Hello."), t_start_ms: 5000, t_end_ms: 4000 });
    expect(timing.statusCode).toBe(422);
    expect(json(timing)).toMatchObject({ reason: "INVALID_TIMING" });
    expect(eventsOf(app, s.id)).toHaveLength(0);
  });

  it("is_local and confidence are stored on the utterance.recorded event", async () => {
    const { app, home } = await makeApp();
    const s = await createSession(app);
    const id = uttId();
    await call(app, "POST", `/api/sessions/${s.id}/utterances?wait=1`, { ...wireUtterance(id, "Hello.", { lane: "me" }), provider: "web-speech", is_local: false, confidence: 0.87 });
    const recorded = readLedger(home, s.id)[0] as Extract<ExmapEvent, { type: "utterance.recorded" }>;
    expect(recorded.utterance).toMatchObject({ id, is_local: false, confidence: 0.87, provider: "web-speech", lane: "me", speaker: "Priya" });
  });

  it("intent none with heard_intent confirm → one utterance.classified and nothing else", async () => {
    const { app, classifier } = await makeApp();
    classifier.push((input) => none(input, "confirm"));
    const s = await createSession(app);
    const id = uttId();
    await postUtterance(app, s.id, id, "Yes.");
    const events = eventsOf(app, s.id);
    expect(types(events)).toEqual(["utterance.recorded", "utterance.classified"]);
    expect(events[1]).toMatchObject({ type: "utterance.classified", intent: "none", heard_intent: "confirm", proposal_ids: [], refused: [], error: null });
  });

  it("a thrown ClassifierError → 201, then utterance.classified { error, proposal_ids: [] }", async () => {
    const { app, classifier } = await makeApp();
    classifier.push(new ClassifierError("E_PROPOSAL_INVARIANT", "I4: invented card id"));
    const s = await createSession(app);
    const id = uttId();
    const res = await postUtterance(app, s.id, id, "Delete card 99.");
    expect(res.statusCode).toBe(201);
    const c = await awaitClassified(app, s.id, id);
    expect(c.error).toEqual({ code: "E_PROPOSAL_INVARIANT", message: "I4: invented card id" });
    expect(c.proposal_ids).toEqual([]);
    expect(c.intent).toBe("none");
    expect(app.exmap.store.open(s.id).state.classifications).toHaveLength(1);
  });

  it("a result core cannot record (a malformed stamp) is ledgered as a classification error, never lost", async () => {
    const { app, classifier } = await makeApp();
    classifier.push((input) => ({ ...none(input), classifier: { provider: "human" as never, model: null, prompt_version: null, fallback_from: null, error: null } }));
    const s = await createSession(app);
    const id = uttId();
    await postUtterance(app, s.id, id, "Hello.");
    const c = await awaitClassified(app, s.id, id);
    expect(c.error?.code).toBe("E_CLASSIFICATION_REFUSED");
    expect(c.classifier.provider).toBe("rules.v1");
    expect(c.intent).toBe("none");
  });

  it("two concurrent posts, the first classification resolving last: both utterances first, then the proposals in utterance order", async () => {
    const gate = deferred<void>();
    const { app, classifier } = await makeApp();
    classifier.push(
      async (input) => {
        await gate.promise;
        return proposal(input, { intent: "add", operations: [op.create("rule", "First rule: cancellation needs a reason.")] });
      },
      ops("add", [op.create("rule", "Second rule: a receptionist may cancel for a patient.")]),
    );
    const s = await createSession(app);
    const a = uttId();
    const b = uttId();
    const [ra, rb] = await Promise.all([postUtterance(app, s.id, a, "First.", { wait: false }), postUtterance(app, s.id, b, "Second.", { wait: false })]);
    expect([ra.statusCode, rb.statusCode]).toEqual([201, 201]);
    expect(classifier.calls).toHaveLength(1); // B waits on the serial chain
    gate.resolve();
    await awaitClassified(app, s.id, b);
    const events = eventsOf(app, s.id);
    expect(types(events)).toEqual([
      "utterance.recorded", "utterance.recorded",
      "proposal.made", "proposal.applied", "utterance.classified",
      "proposal.made", "proposal.applied", "utterance.classified",
    ]);
    const made = events.filter((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made");
    expect(made.map((m) => m.proposal.source_utterance_ids[0])).toEqual([a, b]);
  });

  it("a proposal targeting a card removed meanwhile → refused[0].reason CARD_NOT_LIVE, still 201", async () => {
    const gate = deferred<void>();
    const { app, classifier } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const created = json<{ events: ExmapEvent[] }>(await call(app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "rule", text: RULE } }));
    const ruleId = (created.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;
    classifier.push(async (input) => {
      await gate.promise;
      return proposal(input, { intent: "amend", operations: [op.update(ruleId, { text_append: "Make that 24 hours for nurses." })] });
    });
    const id = uttId();
    const res = await postUtterance(app, s.id, id, "Make that 24 hours for nurses.", { wait: false });
    expect(res.statusCode).toBe(201);
    expect((await call(app, "POST", `/api/sessions/${s.id}/cards/${ruleId}/remove`, { actor: "Ana" })).statusCode).toBe(200);
    gate.resolve();
    const c = await awaitClassified(app, s.id, id);
    expect(c.refused[0]).toMatchObject({ operation: "card.update", reason: "CARD_NOT_LIVE" });
    expect(c.proposal_ids).toEqual([]);
  });

  it("fallback provenance (fallback_from, error, prompt_version) is preserved on the proposal and the classified event", async () => {
    const { app, classifier } = await makeApp();
    const fallbackStamp = { provider: "rules.v1" as const, model: null, prompt_version: "exmap.classifier.claude.v1", fallback_from: "claude" as const, error: "timeout" };
    classifier.push(ops("add", [op.create("rule", RULE)], { classifier: fallbackStamp, rationale: "A rule statement. (rules.v1 fallback: claude timeout)" }));
    const s = await createSession(app);
    const id = uttId();
    await postUtterance(app, s.id, id, RULE);
    const events = eventsOf(app, s.id);
    const made = events.find((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made")!;
    expect(made.proposal.classifier).toEqual({ ...fallbackStamp, actor: null });
    const classified = events.find((e): e is Classified => e.type === "utterance.classified")!;
    expect(classified.classifier).toEqual({ ...fallbackStamp, actor: null });
    expect(app.exmap.store.open(s.id).state.classifications[0]!.classifier.fallback_from).toBe("claude");
  });

  it("the stale-answer race: a click dismisses while a voice answer is in flight → classify re-runs with pending_clarification null; nothing refused", async () => {
    const gate = deferred<void>();
    const { app, classifier } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const ruleRes = json<{ events: ExmapEvent[] }>(await call(app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "rule", text: RULE } }));
    const ruleId = (ruleRes.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;
    const e1 = json<{ events: ExmapEvent[] }>(await call(app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "example", text: "A GP appointment at 10am cancelled at 9am is refused.", rule_id: ruleId } }));
    const e2 = json<{ events: ExmapEvent[] }>(await call(app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "example", text: "A nurse appointment at 10am cancelled at 7am is allowed.", rule_id: ruleId } }));
    const ex1 = (e1.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;
    const ex2 = (e2.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>).effects[0]!.card_id;

    const ask: Step = (input) => proposal(input, {
      intent: "remove", confidence: 0.5, needs_clarification: true,
      clarification: { kind: "choose_target", question: "Which example do you mean?", candidates: [{ card_id: ex1, label: "GP" }, { card_id: ex2, label: "nurse" }], pending_operations: [op.remove("$choice", "Not what I meant.")] },
      target_card_ids: [ex1, ex2],
    });
    let askedBy = "";
    let askingProposal = "";
    const answer: Step = async (input): Promise<ClassifierProposal> => {
      await gate.promise;
      return proposal(input, {
        intent: "remove", confidence: 1, operations: [op.remove(ex1)], resolves: { proposal_id: askingProposal, chosen_card_ids: [ex1], dismissed: false },
        source_utterance_ids: [input.utterance.id, askedBy], rationale: "You chose GP.",
      });
    };
    classifier.push(ask, answer, ops("add", [op.create("question", "What if the clinic cancels?", { about_card_id: ruleId })]));

    askedBy = uttId();
    const asked = json<{ classification: ClassificationSummary }>(await postUtterance(app, s.id, askedBy, "Delete that example."));
    askingProposal = asked.classification.proposals[0]!.proposal_id;
    const cid = asked.classification.proposals[0]!.clarification_id!;
    expect(cid).toBeTruthy();

    const voice = uttId();
    await postUtterance(app, s.id, voice, "The GP one.", { wait: false });
    const dismiss = await call(app, "POST", `/api/sessions/${s.id}/clarifications/${cid}/answer`, { actor: "Ana", answer: { kind: "dismiss", reason: "We keep both." } });
    expect(dismiss.statusCode).toBe(200);
    gate.resolve();
    const c = await awaitClassified(app, s.id, voice);

    expect(classifier.calls).toHaveLength(3);
    expect(classifier.calls[1]!.pending_clarification?.proposal_id).toBe(askingProposal);
    expect(classifier.calls[2]!.pending_clarification).toBeNull();
    expect(classifier.calls[2]!.utterance.id).toBe(voice);
    expect(c.refused).toEqual([]);
    expect(c.intent).toBe("add");
    expect(c.proposal_ids).toHaveLength(1);
    const state = app.exmap.store.open(s.id).state;
    expect(state.clarifications[cid]!.status).toBe("dismissed");
    expect(state.cards[ex1]!.status).toBe("applied"); // the stale removal was never ledgered
    const answered = eventsOf(app, s.id).filter((e) => e.type === "clarification.answered");
    expect(answered).toHaveLength(1);
  });

  it("close() during an in-flight classify aborts its signal and queued jobs never run", async () => {
    const gate = deferred<void>();
    const { app, classifier, home } = await makeApp();
    classifier.push(async (input) => {
      await gate.promise;
      return proposal(input, { intent: "add", operations: [op.create("rule", RULE)] });
    });
    const s = await createSession(app);
    const a = uttId();
    await postUtterance(app, s.id, a, "First.", { wait: false });
    await postUtterance(app, s.id, uttId(), "Second.", { wait: false });
    await new Promise((r) => setTimeout(r, 10));
    expect(classifier.calls).toHaveLength(1);
    await app.close();
    expect(classifier.signals[0]?.aborted).toBe(true);
    gate.resolve();
    await new Promise((r) => setTimeout(r, 20));
    expect(classifier.calls).toHaveLength(1);
    expect(types(readLedger(home, s.id))).toEqual(["utterance.recorded", "utterance.recorded"]);
  });
});
