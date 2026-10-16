// TEST-PLAN §4.2 — the DNS-rebinding Host guard and the WebSocket Origin check (design §8.2).
import { describe, expect, it } from "vitest";
import WebSocket from "ws";
import type { StreamMessage } from "../../../src/core/types.js";
import { call, createSession, json, makeApp } from "./helpers.js";

/** Connects and collects frames until the socket closes (or `untilType` arrives). */
function connect(url: string, origin: string, untilType?: StreamMessage["type"]): Promise<{ frames: StreamMessage[]; code: number | null }> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, { origin });
    const frames: StreamMessage[] = [];
    ws.on("message", (data) => {
      const msg = JSON.parse(String(data)) as StreamMessage;
      frames.push(msg);
      if (untilType && msg.type === untilType) {
        ws.close();
        resolve({ frames, code: null });
      }
    });
    ws.on("close", (code) => resolve({ frames, code }));
    ws.on("error", reject);
  });
}

describe("Host guard and Origin check", () => {
  it("refuses a foreign Host with 403 FORBIDDEN_HOST and accepts the three loopback spellings", async () => {
    const { app } = await makeApp();
    const evil = await call(app, "GET", "/api/health", undefined, { host: "evil.example" });
    expect(evil.statusCode).toBe(403);
    expect(json(evil)).toMatchObject({ ok: false, reason: "FORBIDDEN_HOST" });
    expect(evil.headers["access-control-allow-origin"]).toBeUndefined();
    for (const host of ["127.0.0.1:4317", "localhost:4317", "[::1]:4317"]) {
      const ok = await call(app, "GET", "/api/health", undefined, { host });
      expect(ok.statusCode, host).toBe(200);
      expect(ok.headers["access-control-allow-origin"]).toBeUndefined();
    }
    expect((await call(app, "GET", "/api/health", undefined, { host: "127.0.0.1:9999" })).statusCode).toBe(403);
  });

  it("accepts the Vite dev host 127.0.0.1:5173 only with dev", async () => {
    const plain = (await makeApp()).app;
    expect((await call(plain, "GET", "/api/health", undefined, { host: "127.0.0.1:5173" })).statusCode).toBe(403);
    const dev = (await makeApp({ dev: true })).app;
    expect((await call(dev, "GET", "/api/health", undefined, { host: "127.0.0.1:5173" })).statusCode).toBe(200);
    expect((await call(dev, "GET", "/api/health", undefined, { host: "localhost:5173" })).statusCode).toBe(200);
  });

  it("with port 0 accepts the bound port", async () => {
    const { app } = await makeApp({ port: 0 });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const port = app.exmap.port();
    expect(port).toBeGreaterThan(0);
    const res = await fetch(`http://127.0.0.1:${port}/api/health`);
    expect(res.status).toBe(200);
    expect(((await res.json()) as { app: string }).app).toBe("exmap");
    expect((await call(app, "GET", "/api/health", undefined, { host: `localhost:${port}` })).statusCode).toBe(200);
    expect((await call(app, "GET", "/api/health", undefined, { host: "127.0.0.1:0" })).statusCode).toBe(403);
  });

  it("a WebSocket upgrade with a foreign Origin gets an error frame and close 4003; the Vite origin passes only with dev", async () => {
    const { app } = await makeApp({ port: 0 });
    await app.listen({ host: "127.0.0.1", port: 0 });
    const port = app.exmap.port();
    const s = await createSession(app, { story: "A patient can cancel an appointment online." });
    const url = `ws://127.0.0.1:${port}/api/sessions/${s.id}/stream?after=0`;

    const evil = await connect(url, "http://evil.example");
    expect(evil.code).toBe(4003);
    expect(evil.frames[0]).toMatchObject({ type: "error", reason: "FORBIDDEN_ORIGIN" });

    const vite = await connect(url, "http://localhost:5173");
    expect(vite.code).toBe(4003);

    const own = await connect(url, `http://127.0.0.1:${port}`, "hello");
    expect(own.frames[0]).toMatchObject({ type: "hello", session_id: s.id });

    const devApp = (await makeApp({ port: 0, dev: true })).app;
    await devApp.listen({ host: "127.0.0.1", port: 0 });
    const devPort = devApp.exmap.port();
    const ds = await createSession(devApp, { story: "A patient can cancel an appointment online." });
    const devVite = await connect(`ws://127.0.0.1:${devPort}/api/sessions/${ds.id}/stream`, "http://localhost:5173", "hello");
    expect(devVite.frames[0]).toMatchObject({ type: "hello", session_id: ds.id });
  });
});
