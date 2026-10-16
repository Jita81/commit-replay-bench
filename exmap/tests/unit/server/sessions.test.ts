// TEST-PLAN §4.3 — the session routes of design §8.3.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { select } from "../../../src/core/index.js";
import type { ExmapEvent, MapState, SessionSummary } from "../../../src/core/types.js";
import { call, createSession, json, makeApp, ops, op, postUtterance, uttId } from "./helpers.js";

const STORY = "A patient can cancel an appointment online, but not within two hours.";

describe("session routes", () => {
  it("create → 201; meta.json carries schema and created_at; events.jsonl exists and is empty", async () => {
    const { app, home } = await makeApp();
    const res = await call(app, "POST", "/api/sessions", { title: "Cancellation" });
    expect(res.statusCode).toBe(201);
    const s = json<{ session: SessionSummary }>(res).session;
    expect(s.id).toMatch(/^ses_[a-z0-9]{6,12}_[a-f0-9]{6}$/);
    expect(s.title).toBe("Cancellation");
    expect(s.head).toEqual({ seq: 0, hash: "" });
    expect(s.broken).toBeNull();
    const meta = JSON.parse(readFileSync(join(home, "sessions", s.id, "meta.json"), "utf8")) as Record<string, unknown>;
    expect(meta).toEqual({ schema: "exmap.session-meta.v1", id: s.id, title: "Cancellation", created_at: s.created_at });
    const ledger = join(home, "sessions", s.id, "events.jsonl");
    expect(existsSync(ledger)).toBe(true);
    expect(readFileSync(ledger, "utf8")).toBe("");
  });

  it("with story and actor → two events and the story applied", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY, actor: "Sam" });
    expect(s.head.seq).toBe(2);
    expect(s.counts.by_kind.story).toBe(1);
    const page = json<{ events: ExmapEvent[] }>(await call(app, "GET", `/api/sessions/${s.id}/events`));
    expect(page.events.map((e) => e.type)).toEqual(["proposal.made", "proposal.applied"]);
    const state = app.exmap.store.open(s.id).state;
    const story = select.story(state);
    expect(story?.status).toBe("applied");
    expect(story?.text).toBe(STORY);
    const made = page.events[0] as Extract<ExmapEvent, { type: "proposal.made" }>;
    expect(made.proposal.classifier).toMatchObject({ provider: "human", actor: "Sam" });
  });

  it("story without actor → 400 ACTOR_REQUIRED and nothing is created", async () => {
    const { app } = await makeApp();
    const res = await call(app, "POST", "/api/sessions", { title: "Cancellation", story: STORY });
    expect(res.statusCode).toBe(400);
    expect(json(res)).toMatchObject({ ok: false, reason: "ACTOR_REQUIRED" });
    expect(json<{ sessions: SessionSummary[] }>(await call(app, "GET", "/api/sessions")).sessions).toEqual([]);
    expect((await call(app, "POST", "/api/sessions", { title: "" })).statusCode).toBe(400);
    expect((await call(app, "POST", "/api/sessions", { title: "x".repeat(121) })).statusCode).toBe(400);
  });

  it("lists newest first with counts equal to select.counts", async () => {
    const { app } = await makeApp();
    const a = await createSession(app, { title: "First", story: STORY });
    const b = await createSession(app, { title: "Second" });
    app.exmap.store.open(a.id); // cached
    const list = json<{ sessions: SessionSummary[] }>(await call(app, "GET", "/api/sessions")).sessions;
    expect(list.map((s) => s.id)).toEqual([b.id, a.id]);
    for (const s of list) {
      expect(s.counts).toEqual(select.counts(app.exmap.store.open(s.id).state));
      expect(s.revision).toEqual({ seq: select.currentRevision(app.exmap.store.open(s.id).state).seq, hash: select.currentRevision(app.exmap.store.open(s.id).state).hash });
    }
  });

  it("GET /api/sessions/bad → 400 INVALID_SESSION_ID; an unknown well-formed id → 404 SESSION_NOT_FOUND", async () => {
    const { app } = await makeApp();
    const bad = await call(app, "GET", "/api/sessions/bad");
    expect(bad.statusCode).toBe(400);
    expect(json(bad)).toMatchObject({ reason: "INVALID_SESSION_ID" });
    const traversal = await call(app, "GET", "/api/sessions/..%2F..%2Fetc");
    expect(traversal.statusCode).toBe(400);
    const unknown = await call(app, "GET", "/api/sessions/ses_abcdef12_abcdef");
    expect(unknown.statusCode).toBe(404);
    expect(json(unknown)).toMatchObject({ ok: false, reason: "SESSION_NOT_FOUND" });
  });

  it("events?after=1 returns seq > 1 only; limit pages with has_more", async () => {
    const { app, classifier } = await makeApp();
    classifier.push(ops("add", [op.create("rule", "Cancelling within two hours of the appointment is refused.")]));
    const s = await createSession(app, { story: STORY });
    await postUtterance(app, s.id, uttId(), "Cancelling within two hours of the appointment is refused.");
    const all = json<{ events: ExmapEvent[]; head: { seq: number } }>(await call(app, "GET", `/api/sessions/${s.id}/events`));
    const after = json<{ events: ExmapEvent[]; has_more: boolean }>(await call(app, "GET", `/api/sessions/${s.id}/events?after=1`));
    expect(after.events.every((e) => e.seq > 1)).toBe(true);
    expect(after.events.length).toBe(all.events.length - 1);
    expect(after.has_more).toBe(false);
    const paged = json<{ events: ExmapEvent[]; has_more: boolean }>(await call(app, "GET", `/api/sessions/${s.id}/events?after=1&limit=2`));
    expect(paged.events.map((e) => e.seq)).toEqual([2, 3]);
    expect(paged.has_more).toBe(true);
    expect((await call(app, "GET", `/api/sessions/${s.id}/events?after=-1`)).statusCode).toBe(400);
    expect(all.head.seq).toBe(all.events.length);
  });

  it("state omits revision snapshots", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const { state } = json<{ state: MapState }>(await call(app, "GET", `/api/sessions/${s.id}/state`));
    expect(state.schema).toBe("exmap.state.v1");
    expect(state.revisions.length).toBe(2);
    for (const r of state.revisions) expect("snapshot" in r).toBe(false);
  });

  it("GET /api/sessions/:id returns export_options null, then the current value after a PUT", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const before = json<{ session: SessionSummary; dod: { checks: unknown[] }; signoff: unknown; export_options: unknown }>(await call(app, "GET", `/api/sessions/${s.id}`));
    expect(before.export_options).toBeNull();
    expect(before.signoff).toBeNull();
    expect(before.dod.checks).toHaveLength(5);
    expect(before.session.id).toBe(s.id);
    const put = await call(app, "PUT", `/api/sessions/${s.id}/export-options`, { actor: "Sam", capability_class: "bug.fix", kind: "code", size_estimate: "S", facts: [] });
    expect(put.statusCode).toBe(200);
    const after = json<{ export_options: { capability_class: string; seq: number } }>(await call(app, "GET", `/api/sessions/${s.id}`));
    expect(after.export_options).toMatchObject({ capability_class: "bug.fix", seq: 1, by: "Sam" });
  });
});
