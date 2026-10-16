// TEST-PLAN §4.11 — PUT …/export-options: ledgered as export.options_set (seq 1, 2, …), catalogue membership (CLASS_UNKNOWN),
// the slot shape, the actor rule, the latest value on GET /api/sessions/:id, and the history in evidence.json.
import { describe, expect, it } from "vitest";
import type { ActResponse, Evidence, ExportOptions } from "../../../src/core/types.js";
import { call, createSession, json, makeApp } from "./helpers.js";

const STORY = "A patient can cancel an appointment online.";

describe("export options", () => {
  it("PUT → export.options_set with seq 1, then seq 2; the latest on GET; both in evidence.json's history", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const url = `/api/sessions/${s.id}/export-options`;
    const first = await call(app, "PUT", url, { actor: "Sam", capability_class: "backend.route.edit", kind: "code", size_estimate: "M", facts: [{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }] });
    expect(first.statusCode).toBe(200);
    const fb = json<ActResponse & { export_options: ExportOptions }>(first);
    expect(fb.events[0]!.type).toBe("export.options_set");
    expect(fb.export_options).toMatchObject({ seq: 1, by: "Sam", capability_class: "backend.route.edit", size_estimate: "M" });
    const second = await call(app, "PUT", url, { actor: "Ana", capability_class: "unclassified", kind: "code", size_estimate: "unsized", facts: [] });
    expect(second.statusCode).toBe(200);
    expect(json<{ export_options: ExportOptions }>(second).export_options).toMatchObject({ seq: 2, by: "Ana", capability_class: "unclassified" });
    const detail = json<{ export_options: ExportOptions }>(await call(app, "GET", `/api/sessions/${s.id}`));
    expect(detail.export_options).toMatchObject({ seq: 2, by: "Ana" });
    const ev = await call(app, "GET", `/api/sessions/${s.id}/export/evidence.json?draft=true`);
    expect(ev.statusCode).toBe(200);
    const evidence = JSON.parse(ev.body) as Evidence;
    expect(evidence.export_options_history.map((o) => o.seq)).toEqual([1, 2]);
    expect(evidence.export_options?.seq).toBe(2);
  });

  it("an unknown class → 400 CLASS_UNKNOWN; a bad slot → 422 BAD_SHAPE; no actor → 400 ACTOR_REQUIRED", async () => {
    const { app } = await makeApp();
    const s = await createSession(app, { story: STORY });
    const url = `/api/sessions/${s.id}/export-options`;
    const nope = await call(app, "PUT", url, { actor: "Sam", capability_class: "nope", kind: "code", size_estimate: "S", facts: [] });
    expect(nope.statusCode).toBe(400);
    expect(json(nope)).toMatchObject({ ok: false, reason: "CLASS_UNKNOWN" });
    const slot = await call(app, "PUT", url, { actor: "Sam", capability_class: "bug.fix", kind: "code", size_estimate: "S", facts: [{ slot: "1bad", text: "x" }] });
    expect(slot.statusCode).toBe(422);
    expect(json(slot)).toMatchObject({ reason: "BAD_SHAPE" });
    const actor = await call(app, "PUT", url, { capability_class: "bug.fix", kind: "code", size_estimate: "S", facts: [] });
    expect(actor.statusCode).toBe(400);
    expect(json(actor)).toMatchObject({ reason: "ACTOR_REQUIRED" });
    const kind = await call(app, "PUT", url, { actor: "Sam", capability_class: "bug.fix", kind: "frontend", size_estimate: "S", facts: [] });
    expect(kind.statusCode).toBe(422);
    expect(json(kind)).toMatchObject({ reason: "INVALID_ENUM" });
    expect(app.exmap.store.open(s.id).state.export_options).toEqual([]);
  });
});
