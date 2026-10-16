// TEST-PLAN §4.7 — POST …/signoff: the DoD gate, the confirmation statement, a stale revision, invalidation by a later
// change, re-sign-off, and a clarification asked after sign-off (not verified, not invalidated; verified again on Dismiss).
import { describe, expect, it } from "vitest";
import { SIGNOFF_CONFIRMATION_TEXT, select } from "../../../src/core/index.js";
import type { ActResponse, ClassificationSummary, DodReport, ExmapEvent, MapState, SessionSummary } from "../../../src/core/types.js";
import { call, createSession, eventsOf, json, makeApp, op, ops, postUtterance, proposal, uttId, type TestApp } from "./helpers.js";

const STORY = "A patient can cancel an appointment online.";

async function voice(t: TestApp, sid: string, step: Parameters<TestApp["classifier"]["push"]>[0]): Promise<ClassificationSummary> {
  t.classifier.push(step);
  return json<{ classification: ClassificationSummary }>(await postUtterance(t.app, sid, uttId(), "an utterance")).classification;
}

function createdBy(t: TestApp, sid: string, pid: string): string {
  const made = eventsOf(t.app, sid).find((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made" && e.proposal.id === pid)!;
  return made.effects[0]!.card_id;
}

/** story, an AI rule, an AI example under it, an AI removal of a second example: everything a reviewer must look at. */
async function mapToReview(): Promise<TestApp & { sid: string; rule: string; example: string; removal: string }> {
  const t = await makeApp();
  const s = await createSession(t.app, { story: STORY });
  const r = await voice(t, s.id, ops("add", [op.create("rule", "A patient cannot cancel within two hours of the appointment.")]));
  const rule = createdBy(t, s.id, r.proposals[0]!.proposal_id);
  const e = await voice(t, s.id, ops("add", [op.create("example", "A GP appointment at 10am cancelled at 9am is refused.", { rule_id: rule })]));
  const example = createdBy(t, s.id, e.proposals[0]!.proposal_id);
  const e2 = await voice(t, s.id, ops("add", [op.create("example", "A nurse appointment at 10am cancelled at 7am is allowed.", { rule_id: rule })]));
  const rm = await voice(t, s.id, ops("remove", [op.remove(createdBy(t, s.id, e2.proposals[0]!.proposal_id))]));
  return { ...t, sid: s.id, rule, example, removal: rm.proposals[0]!.proposal_id };
}

const state = (t: TestApp, sid: string): MapState => t.app.exmap.store.open(sid).state;

async function review(t: TestApp & { sid: string; rule: string; example: string; removal: string }): Promise<void> {
  const story = select.story(state(t, t.sid))!.id;
  expect((await call(t.app, "POST", `/api/sessions/${t.sid}/proposals/${t.removal}/accept`, { actor: "Sam" })).statusCode).toBe(200);
  expect((await call(t.app, "POST", `/api/sessions/${t.sid}/review/checks`, { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [story, t.rule] })).statusCode).toBe(200);
  expect((await call(t.app, "POST", `/api/sessions/${t.sid}/review/checks`, { actor: "Sam", check_id: "examples_reviewed", card_ids: [t.example] })).statusCode).toBe(200);
}

async function signoff(t: TestApp & { sid: string }, statement = SIGNOFF_CONFIRMATION_TEXT, hash?: string) {
  return call(t.app, "POST", `/api/sessions/${t.sid}/signoff`, { reviewer: "Sam", statement, revision_hash: hash ?? select.currentRevision(state(t, t.sid)).hash });
}

async function verified(t: TestApp & { sid: string }): Promise<boolean> {
  return json<{ session: SessionSummary }>(await call(t.app, "GET", `/api/sessions/${t.sid}`)).session.human_verified;
}

describe("sign-off", () => {
  it("an unreviewed map → 422 SIGNOFF_DOD_FAILED with all five checks and pass false", async () => {
    const t = await mapToReview();
    const res = await signoff(t);
    expect(res.statusCode).toBe(422);
    const body = json<{ reason: string; checks: DodReport }>(res);
    expect(body.reason).toBe("SIGNOFF_DOD_FAILED");
    expect(body.checks.pass).toBe(false);
    expect(body.checks.checks.map((c) => c.id)).toEqual(["story_rules_confirmed", "examples_reviewed", "changes_resolved", "questions_resolved", "final_version_recorded"]);
    expect(body.checks.checks.find((c) => c.id === "changes_resolved")!.pass).toBe(false);
  });

  it("after a full review (Accept on every AI act) → 200 and human_verified; a wrong statement 400; a stale hash 409", async () => {
    const t = await mapToReview();
    await review(t);
    const wrong = await signoff(t, "Looks fine to me.");
    expect(wrong.statusCode).toBe(400);
    expect(json(wrong)).toMatchObject({ reason: "SIGNOFF_CONFIRMATION_TEXT_MISMATCH" });
    const stale = await signoff(t, SIGNOFF_CONFIRMATION_TEXT, "0".repeat(64));
    expect(stale.statusCode).toBe(409);
    expect(json(stale)).toMatchObject({ reason: "SIGNOFF_STALE_REVISION" });
    const noReviewer = await call(t.app, "POST", `/api/sessions/${t.sid}/signoff`, { reviewer: " ", statement: SIGNOFF_CONFIRMATION_TEXT, revision_hash: select.currentRevision(state(t, t.sid)).hash });
    expect(noReviewer.statusCode).toBe(400);
    expect(json(noReviewer)).toMatchObject({ reason: "SIGNOFF_REVIEWER_REQUIRED" });
    const ok = await signoff(t);
    expect(ok.statusCode).toBe(200);
    expect(await verified(t)).toBe(true);
    const twice = await signoff(t);
    expect(twice.statusCode).toBe(409);
    expect(json(twice)).toMatchObject({ reason: "SIGNOFF_ALREADY_ACTIVE" });
  });

  it("a later card update's batch carries signoff.invalidated; re-sign-off → 200 and the earlier one reads invalidated in /state", async () => {
    const t = await mapToReview();
    await review(t);
    expect((await signoff(t)).statusCode).toBe(200);
    const upd = await call(t.app, "POST", `/api/sessions/${t.sid}/cards/${t.rule}/update`, { actor: "Sam", patch: { text: "A patient cannot cancel within 24 hours of the appointment." } });
    expect(upd.statusCode).toBe(200);
    const events = json<ActResponse>(upd).events;
    expect(events.map((e) => e.type)).toContain("signoff.invalidated");
    expect(await verified(t)).toBe(false);
    const story = select.story(state(t, t.sid))!.id;
    expect((await call(t.app, "POST", `/api/sessions/${t.sid}/review/checks`, { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [t.rule] })).statusCode).toBe(200);
    expect((await call(t.app, "POST", `/api/sessions/${t.sid}/review/checks`, { actor: "Sam", check_id: "examples_reviewed", card_ids: [t.example] })).statusCode).toBe(200);
    void story;
    expect((await signoff(t)).statusCode).toBe(200);
    const s = json<{ state: MapState }>(await call(t.app, "GET", `/api/sessions/${t.sid}/state`)).state;
    expect(s.signoffs.map((x) => x.status)).toEqual(["invalidated", "active"]);
    expect(await verified(t)).toBe(true);
  });

  it("a clarification asked after sign-off → not verified, not invalidated; verified again after Dismiss", async () => {
    const t = await mapToReview();
    await review(t);
    expect((await signoff(t)).statusCode).toBe(200);
    const ask = await voice(t, t.sid, (input) => proposal(input, {
      intent: "remove", confidence: 0.45, needs_clarification: true,
      clarification: { kind: "confirm_intent", question: "Remove the GP example?", candidates: [], pending_operations: [op.remove(t.example)] },
    }));
    const cid = ask.proposals[0]!.clarification_id!;
    expect(await verified(t)).toBe(false);
    expect(select.lastSignoff(state(t, t.sid))!.status).toBe("active");
    expect(eventsOf(t.app, t.sid).some((e) => e.type === "signoff.invalidated")).toBe(false);
    const dismiss = await call(t.app, "POST", `/api/sessions/${t.sid}/clarifications/${cid}/answer`, { actor: "Sam", answer: { kind: "dismiss", reason: "We keep it." } });
    expect(dismiss.statusCode).toBe(200);
    expect(await verified(t)).toBe(true);
  });
});
