// TEST-PLAN §4.9 — WebSocket GET /api/sessions/:id/stream?after=<seq> with a real listener and the `ws` client (design §8.8).
import { describe, expect, it } from "vitest";
import WebSocket from "ws";
import type { ExmapEvent, StreamMessage } from "../../../src/core/types.js";
import { call, createSession, deferred, makeApp, op, postUtterance, proposal, uttId, type TestApp } from "./helpers.js";

const STORY = "A patient can cancel an appointment online.";

interface Client {
  ws: WebSocket;
  frames: StreamMessage[];
  closed: Promise<{ code: number; reason: string }>;
  waitFor(pred: (frames: StreamMessage[]) => boolean, ms?: number): Promise<void>;
}

function client(port: number, path: string, origin = `http://127.0.0.1:${port}`): Client {
  const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, { origin });
  const frames: StreamMessage[] = [];
  const waiters: Array<() => void> = [];
  ws.on("message", (data) => {
    frames.push(JSON.parse(String(data)) as StreamMessage);
    for (const w of waiters.splice(0)) w();
  });
  const closed = new Promise<{ code: number; reason: string }>((resolve) => ws.on("close", (code, reason) => resolve({ code, reason: String(reason) })));
  return {
    ws,
    frames,
    closed,
    waitFor(pred, ms = 3000) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`timed out; frames: ${JSON.stringify(frames.map((f) => (f.type === "event" ? f.event.seq : f.type)))}`)), ms);
        const check = (): void => {
          if (pred(frames)) {
            clearTimeout(timer);
            resolve();
          } else waiters.push(check);
        };
        check();
      });
    },
  };
}

const events = (frames: StreamMessage[]): ExmapEvent[] => frames.flatMap((f) => (f.type === "event" ? [f.event] : []));

async function listening(): Promise<TestApp & { port: number }> {
  const t = await makeApp({ port: 0 });
  await t.app.listen({ host: "127.0.0.1", port: 0 });
  return { ...t, port: t.app.exmap.port() };
}

async function addCard(t: TestApp, sid: string, text: string): Promise<void> {
  const res = await call(t.app, "POST", `/api/sessions/${sid}/cards`, { actor: "Ana", card: { kind: "rule", text } });
  expect(res.statusCode).toBe(200);
}

describe("session stream", () => {
  it("hello first; after=2 delivers seq 3..n, then live events", async () => {
    const t = await listening();
    const s = await createSession(t.app, { story: STORY });
    await addCard(t, s.id, "Rule one: no cancelling within two hours.");
    await addCard(t, s.id, "Rule two: a receptionist may cancel for a patient.");
    const head = t.app.exmap.store.open(s.id).state.head.seq;
    expect(head).toBe(6);
    const c = client(t.port, `/api/sessions/${s.id}/stream?after=2`);
    await c.waitFor((f) => events(f).length === head - 2);
    expect(c.frames[0]).toMatchObject({ type: "hello", session_id: s.id, head: { seq: head }, after: 2 });
    expect(events(c.frames).map((e) => e.seq)).toEqual([3, 4, 5, 6]);
    await addCard(t, s.id, "Rule three: cancellations are confirmed by email.");
    await c.waitFor((f) => events(f).length === 6);
    expect(events(c.frames).map((e) => e.seq)).toEqual([3, 4, 5, 6, 7, 8]);
    c.ws.close();
  });

  it("acts racing a connect are delivered exactly once, in order", async () => {
    const t = await listening();
    const s = await createSession(t.app, { story: STORY });
    const c = client(t.port, `/api/sessions/${s.id}/stream?after=0`);
    const acts: Promise<unknown>[] = [];
    for (let i = 0; i < 6; i++) acts.push(addCard(t, s.id, `Racing rule number ${i}.`));
    c.ws.once("open", () => {
      for (let i = 6; i < 10; i++) acts.push(addCard(t, s.id, `Racing rule number ${i}.`));
    });
    await c.waitFor(() => acts.length === 10);
    await Promise.all(acts);
    const head = t.app.exmap.store.open(s.id).state.head.seq;
    expect(head).toBe(2 + 10 * 2);
    await c.waitFor((f) => events(f).length >= head);
    await new Promise((r) => setTimeout(r, 30));
    const seqs = events(c.frames).map((e) => e.seq);
    expect(seqs).toEqual(Array.from({ length: head }, (_, i) => i + 1));
    expect(c.frames[0]!.type).toBe("hello");
    c.ws.close();
  });

  it("proposal.* and utterance.classified arrive after the 201", async () => {
    const t = await listening();
    const gate = deferred<void>();
    t.classifier.push(async (input) => {
      await gate.promise;
      return proposal(input, { intent: "add", operations: [op.create("rule", "A patient cannot cancel within two hours.")] });
    });
    const s = await createSession(t.app, { story: STORY });
    const c = client(t.port, `/api/sessions/${s.id}/stream?after=2`);
    await c.waitFor((f) => f.length >= 1);
    const res = await postUtterance(t.app, s.id, uttId(), "No cancelling within two hours.", { wait: false });
    expect(res.statusCode).toBe(201);
    await c.waitFor((f) => events(f).length === 1);
    expect(events(c.frames).map((e) => e.type)).toEqual(["utterance.recorded"]);
    gate.resolve();
    await c.waitFor((f) => events(f).length === 4);
    expect(events(c.frames).map((e) => e.type)).toEqual(["utterance.recorded", "proposal.made", "proposal.applied", "utterance.classified"]);
    expect(c.frames.every((f) => f.type === "hello" || f.type === "event")).toBe(true);
    c.ws.close();
  });

  it("an unknown session → an error frame, then close 4004; a foreign Origin → 4003", async () => {
    const t = await listening();
    const c = client(t.port, "/api/sessions/ses_abcdef12_abcdef/stream");
    const { code } = await c.closed;
    expect(code).toBe(4004);
    expect(c.frames).toEqual([{ type: "error", reason: "SESSION_NOT_FOUND", detail: expect.any(String) }]);
    const bad = client(t.port, "/api/sessions/not-an-id/stream");
    expect((await bad.closed).code).toBe(4004);
    const s = await createSession(t.app, { story: STORY });
    const evil = client(t.port, `/api/sessions/${s.id}/stream`, "http://evil.example");
    expect((await evil.closed).code).toBe(4003);
    expect(evil.frames[0]).toMatchObject({ type: "error", reason: "FORBIDDEN_ORIGIN" });
  });

  it("close() sends 1001 to every client", async () => {
    const t = await listening();
    const s = await createSession(t.app, { story: STORY });
    const c = client(t.port, `/api/sessions/${s.id}/stream`);
    await c.waitFor((f) => f.length >= 1);
    await t.app.close();
    expect((await c.closed).code).toBe(1001);
  });
});
