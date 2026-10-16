// TEST-PLAN §4.10 — GET …/export/:file: the gate (422 NOT_HUMAN_VERIFIED with checks and the sign-off status), drafts,
// the five files of a verified map with their content types, an unknown file token.
import { describe, expect, it } from "vitest";
import { SIGNOFF_CONFIRMATION_TEXT, select } from "../../../src/core/index.js";
import type { BacklogItem, ClassificationSummary, DodReport, ExmapEvent } from "../../../src/core/types.js";
import { call, createSession, eventsOf, json, makeApp, op, ops, postUtterance, proposal, uttId, type TestApp } from "./helpers.js";

const STORY = "A patient can cancel an appointment online, but not within two hours.";

async function verifiedMap(): Promise<TestApp & { sid: string; rule: string }> {
  const t = await makeApp();
  const s = await createSession(t.app, { story: STORY });
  t.classifier.push(ops("add", [op.create("rule", "A patient cannot cancel within two hours of the appointment.")]));
  const c = json<{ classification: ClassificationSummary }>(await postUtterance(t.app, s.id, uttId(), "No cancelling within two hours.")).classification;
  const made = eventsOf(t.app, s.id).find((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made" && e.proposal.id === c.proposals[0]!.proposal_id)!;
  const rule = made.effects[0]!.card_id;
  const story = select.story(t.app.exmap.store.open(s.id).state)!.id;
  await call(t.app, "POST", `/api/sessions/${s.id}/review/checks`, { actor: "Sam", check_id: "story_rules_confirmed", card_ids: [story, rule] });
  const hash = select.currentRevision(t.app.exmap.store.open(s.id).state).hash;
  const so = await call(t.app, "POST", `/api/sessions/${s.id}/signoff`, { reviewer: "Sam", statement: SIGNOFF_CONFIRMATION_TEXT, revision_hash: hash });
  expect(so.statusCode).toBe(200);
  return { ...t, sid: s.id, rule };
}

describe("export route", () => {
  it("an unverified map → 422 NOT_HUMAN_VERIFIED with checks and signoff.status none", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const res = await call(app, "GET", `/api/sessions/${s.id}/export/crb-backlog-item.json`);
    expect(res.statusCode).toBe(422);
    const body = json<{ ok: false; reason: string; detail: string; checks: DodReport; signoff: { status: string } }>(res);
    expect(body).toMatchObject({ ok: false, reason: "NOT_HUMAN_VERIFIED", detail: "export needs a human-verified requirement; add ?draft=true for a watermarked draft" });
    expect(body.checks.checks).toHaveLength(5);
    expect(body.signoff.status).toBe("none");
    expect((await call(app, "GET", `/api/sessions/${s.id}/export/ticket.md?draft=false`)).statusCode).toBe(422);
  });

  it("an active sign-off with an open clarification → signoff.status active_but_dod_failed", async () => {
    const t = await verifiedMap();
    t.classifier.push((input) => proposal(input, {
      intent: "remove", confidence: 0.45, needs_clarification: true,
      clarification: { kind: "confirm_intent", question: "Remove the rule?", candidates: [], pending_operations: [op.remove(t.rule)] },
    }));
    await postUtterance(t.app, t.sid, uttId(), "Maybe drop that rule?");
    const res = await call(t.app, "GET", `/api/sessions/${t.sid}/export/evidence.json`);
    expect(res.statusCode).toBe(422);
    expect(json<{ signoff: { status: string; id: string } }>(res).signoff).toMatchObject({ status: "active_but_dod_failed" });
  });

  it("?draft=true → 200, Content-Disposition DRAFT-crb-backlog-item.json, a prefixed title and labels.exmap_draft", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const res = await call(app, "GET", `/api/sessions/${s.id}/export/crb-backlog-item.json?draft=true`);
    expect(res.statusCode).toBe(200);
    expect(res.headers["content-disposition"]).toBe('attachment; filename="DRAFT-crb-backlog-item.json"');
    expect(res.headers["content-type"]).toContain("application/json");
    const item = JSON.parse(res.body) as BacklogItem;
    expect(item.title.startsWith("[DRAFT / NOT VERIFIED]")).toBe(true);
    expect(item.labels["exmap_draft"]).toBe("true");
    expect(res.headers["cache-control"]).toBe("no-store");
  });

  it("a verified map → all five files 200 with the right content types", async () => {
    const t = await verifiedMap();
    const expected: Record<string, string> = {
      "crb-backlog-item.json": "application/json",
      "ticket.json": "application/json",
      "ticket.md": "text/markdown; charset=utf-8",
      "requirement.feature": "text/plain; charset=utf-8",
      "evidence.json": "application/json",
    };
    for (const [file, type] of Object.entries(expected)) {
      const res = await call(t.app, "GET", `/api/sessions/${t.sid}/export/${file}`);
      expect(res.statusCode, file).toBe(200);
      expect(res.headers["content-type"], file).toBe(type);
      expect(res.headers["content-disposition"], file).toBe(`attachment; filename="${file}"`);
      expect(res.body.length, file).toBeGreaterThan(0);
    }
    const evidence = JSON.parse((await call(t.app, "GET", `/api/sessions/${t.sid}/export/evidence.json`)).body) as { verified: boolean; draft: boolean; watermark: string | null };
    expect(evidence).toMatchObject({ verified: true, draft: false, watermark: null });
  });

  it("export/backlog-item.json → 400 EXPORT_FILE_UNKNOWN", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const res = await call(app, "GET", `/api/sessions/${s.id}/export/backlog-item.json`);
    expect(res.statusCode).toBe(400);
    expect(json(res)).toMatchObject({ ok: false, reason: "EXPORT_FILE_UNKNOWN" });
  });
});
