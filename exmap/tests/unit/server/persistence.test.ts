// TEST-PLAN §4.8 — events.jsonl (canonical lines, one fsync per batch), restart, replay-and-verify on open (a broken chain
// refuses to open with its row; the list shows it with a prefix summary), a failed append (truncated back, the session
// broken, WebSocket 4009), export options through a restart, server.lock, and the prebuilt ledger fixtures.
import { spawn } from "node:child_process";
import fs from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import WebSocket from "ws";
import { canonicalJson } from "../../../src/core/index.js";
import type { ExmapEvent, SessionSummary, StreamMessage } from "../../../src/core/types.js";
import { HomeLockedError } from "../../../src/server/home.js";
import { startServer } from "../../../src/server/main.js";
import { FIXTURE_DIR, FIXTURE_IDS, fixtureFiles } from "./fixture-ledgers.js";
import {
  call, createSession, fakeClassifier, json, ledgerText, makeApp, op, ops, postUtterance, readLedger, tempHome, uttId, type TestApp,
} from "./helpers.js";

const STORY = "A patient can cancel an appointment online.";

afterEach(() => {
  vi.restoreAllMocks();
});

async function withThreeBatches(): Promise<TestApp & { sid: string }> {
  const t = await makeApp();
  t.classifier.push(ops("add", [op.create("rule", "A patient cannot cancel online within two hours of the appointment.")]));
  const s = await createSession(t.app, { story: STORY });
  await postUtterance(t.app, s.id, uttId(), "A patient should be able to cancel online, but not within two hours of their appointment.");
  await call(t.app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "question", text: "What if the clinic cancels?", about_card_id: null } });
  return { ...t, sid: s.id };
}

function lines(home: string, sid: string): string[] {
  const text = ledgerText(home, sid);
  return text.split("\n").slice(0, -1);
}

function writeLines(home: string, sid: string, rows: string[], terminated = true): void {
  fs.writeFileSync(join(home, "sessions", sid, "events.jsonl"), rows.join("\n") + (terminated ? "\n" : ""));
}

describe("events.jsonl", () => {
  it("every line is canonicalJson(event), the file ends with \\n, and its length is the sum of its lines", async () => {
    const t = await withThreeBatches();
    const text = ledgerText(t.home, t.sid);
    expect(text.endsWith("\n")).toBe(true);
    const rows = lines(t.home, t.sid);
    const events = t.app.exmap.store.open(t.sid).events;
    expect(rows).toHaveLength(events.length);
    rows.forEach((row, i) => expect(row).toBe(canonicalJson(events[i])));
    expect(Buffer.byteLength(text)).toBe(rows.reduce((n, r) => n + Buffer.byteLength(r) + 1, 0));
  });

  it("one fsync per appended batch", async () => {
    const t = await withThreeBatches();
    const spy = vi.spyOn(fs, "fsyncSync");
    const res = await call(t.app, "POST", `/api/sessions/${t.sid}/cards`, { actor: "Ana", card: { kind: "rule", text: "A receptionist may cancel for a patient." } });
    expect(res.statusCode).toBe(200);
    expect(json<{ events: ExmapEvent[] }>(res).events).toHaveLength(2);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("a restart on the same home serves the same head and counts", async () => {
    const t = await withThreeBatches();
    const before = json<{ session: SessionSummary }>(await call(t.app, "GET", `/api/sessions/${t.sid}`)).session;
    await t.app.close();
    const again = (await makeApp({ home: t.home })).app;
    const after = json<{ session: SessionSummary }>(await call(again, "GET", `/api/sessions/${t.sid}`)).session;
    expect(after.head).toEqual(before.head);
    expect(after.counts).toEqual(before.counts);
    expect(after.revision).toEqual(before.revision);
  });

  it("export.options_set events round-trip through a restart", async () => {
    const t = await withThreeBatches();
    await call(t.app, "PUT", `/api/sessions/${t.sid}/export-options`, { actor: "Sam", capability_class: "bug.fix", kind: "code", size_estimate: "S", facts: [{ slot: "reproduction", text: "Cancel at 9:59 for a 10:00 slot." }] });
    await call(t.app, "PUT", `/api/sessions/${t.sid}/export-options`, { actor: "Sam", capability_class: "bug.fix", kind: "code", size_estimate: "M", facts: [] });
    await t.app.close();
    const again = (await makeApp({ home: t.home })).app;
    const state = again.exmap.store.open(t.sid).state;
    expect(state.export_options.map((o) => [o.seq, o.size_estimate])).toEqual([[1, "S"], [2, "M"]]);
    expect(json<{ export_options: { seq: number } }>(await call(again, "GET", `/api/sessions/${t.sid}`)).export_options.seq).toBe(2);
  });
});

describe("replay and verify on open", () => {
  it("tamper one character of event 3's text → 409 LEDGER_BROKEN { row 3, seq 3, HASH_MISMATCH }; the list shows broken with counts of events 1–2", async () => {
    const t = await withThreeBatches();
    await t.app.close();
    const rows = lines(t.home, t.sid);
    expect(rows[2]).toContain("cancel online");
    rows[2] = rows[2]!.replace("cancel online", "cancel Online");
    writeLines(t.home, t.sid, rows);
    const app = (await makeApp({ home: t.home })).app;
    const res = await call(app, "GET", `/api/sessions/${t.sid}`);
    expect(res.statusCode).toBe(409);
    expect(json(res)).toMatchObject({ ok: false, reason: "LEDGER_BROKEN", row: 3, seq: 3, code: "HASH_MISMATCH" });
    const listed = json<{ sessions: SessionSummary[] }>(await call(app, "GET", "/api/sessions")).sessions.find((s) => s.id === t.sid)!;
    expect(listed.broken).toMatchObject({ code: "HASH_MISMATCH", row: 3, seq: 3 });
    expect(listed.head.seq).toBe(2);
    expect(listed.counts.events).toBe(2);
    expect(listed.counts.utterances).toBe(0);
    expect(listed.counts.by_kind.story).toBe(1);
  });

  it("remove line 2 → PREV_HASH_MISMATCH or SEQ_MISMATCH at row 2", async () => {
    const t = await withThreeBatches();
    await t.app.close();
    const rows = lines(t.home, t.sid);
    rows.splice(1, 1);
    writeLines(t.home, t.sid, rows);
    const app = (await makeApp({ home: t.home })).app;
    const res = await call(app, "GET", `/api/sessions/${t.sid}`);
    expect(res.statusCode).toBe(409);
    const body = json<{ reason: string; row: number; code: string }>(res);
    expect(body.reason).toBe("LEDGER_BROKEN");
    expect(body.row).toBe(2);
    expect(["PREV_HASH_MISMATCH", "SEQ_MISMATCH"]).toContain(body.code);
  });

  it("the last line cut mid-JSON → LEDGER_PARSE_ERROR at the last row, with a prefix summary", async () => {
    const t = await withThreeBatches();
    await t.app.close();
    const rows = lines(t.home, t.sid);
    const lastRow = rows.length;
    rows[lastRow - 1] = rows[lastRow - 1]!.slice(0, 40);
    writeLines(t.home, t.sid, rows, false);
    const app = (await makeApp({ home: t.home })).app;
    const res = await call(app, "GET", `/api/sessions/${t.sid}`);
    expect(res.statusCode).toBe(409);
    expect(json(res)).toMatchObject({ reason: "LEDGER_BROKEN", row: lastRow, code: "LEDGER_PARSE_ERROR", seq: null });
    const listed = json<{ sessions: SessionSummary[] }>(await call(app, "GET", "/api/sessions")).sessions.find((s) => s.id === t.sid)!;
    expect(listed.broken).toMatchObject({ code: "LEDGER_PARSE_ERROR", row: lastRow });
    expect(listed.head.seq).toBe(lastRow - 1);
  });

  it("a ledger cut at a line boundary inside a batch → 409 LEDGER_BROKEN INCOMPLETE_BATCH naming the batch's first row; writes are refused, not 500 (review finding)", async () => {
    const t = await withThreeBatches();
    await t.app.close();
    const rows = lines(t.home, t.sid);
    const last = JSON.parse(rows[rows.length - 1]!) as ExmapEvent;
    const batchStart = rows.findIndex((r) => (JSON.parse(r) as ExmapEvent).batch_id === last.batch_id) + 1;
    expect(rows.length - batchStart).toBe(1); // a two-event batch: proposal.made, proposal.applied
    writeLines(t.home, t.sid, rows.slice(0, -1)); // newline-terminated, chain intact
    const app = (await makeApp({ home: t.home })).app;
    const res = await call(app, "GET", `/api/sessions/${t.sid}`);
    expect(res.statusCode).toBe(409);
    expect(json(res)).toMatchObject({ reason: "LEDGER_BROKEN", code: "INCOMPLETE_BATCH", row: batchStart, seq: batchStart });
    expect(json<{ detail: string }>(res).detail).toContain(`row ${batchStart}`);
    const listed = json<{ sessions: SessionSummary[] }>(await call(app, "GET", "/api/sessions")).sessions.find((s) => s.id === t.sid)!;
    expect(listed.broken).toMatchObject({ code: "INCOMPLETE_BATCH", row: batchStart });
    expect(listed.head.seq).toBe(batchStart); // the summary is computed from every readable row
    const write = await call(app, "POST", `/api/sessions/${t.sid}/cards`, { actor: "Ana", card: { kind: "rule", text: "Another rule.", about_card_id: null } });
    expect(write.statusCode).toBe(409);
    expect(lines(t.home, t.sid)).toEqual(rows.slice(0, -1));
    await app.close();
    writeLines(t.home, t.sid, rows.slice(0, batchStart - 1)); // the advice: truncate before that row
    const healed = (await makeApp({ home: t.home })).app;
    expect((await call(healed, "GET", `/api/sessions/${t.sid}`)).statusCode).toBe(200);
  });

  it("a cut inside a two-event batch's last line names the batch's first row in the detail", async () => {
    const t = await withThreeBatches();
    await t.app.close();
    const rows = lines(t.home, t.sid);
    rows[rows.length - 1] = rows[rows.length - 1]!.slice(0, 40);
    writeLines(t.home, t.sid, rows, false);
    const app = (await makeApp({ home: t.home })).app;
    const res = await call(app, "GET", `/api/sessions/${t.sid}`);
    expect(json(res)).toMatchObject({ code: "LEDGER_PARSE_ERROR", row: rows.length });
    expect(json<{ detail: string }>(res).detail).toContain(`truncate before row ${rows.length - 1}`);
  });

  it("a broken session refuses POST …/utterances and writes nothing", async () => {
    const t = await withThreeBatches();
    await t.app.close();
    const rows = lines(t.home, t.sid);
    rows[2] = rows[2]!.replace("cancel online", "cancel Online");
    writeLines(t.home, t.sid, rows);
    const before = ledgerText(t.home, t.sid);
    const app = (await makeApp({ home: t.home })).app;
    const res = await postUtterance(app, t.sid, uttId(), "Anything at all.");
    expect(res.statusCode).toBe(409);
    expect(json(res)).toMatchObject({ reason: "LEDGER_BROKEN" });
    expect((await call(app, "POST", `/api/sessions/${t.sid}/cards`, { actor: "Ana", card: { kind: "rule", text: "x y z" } })).statusCode).toBe(409);
    expect(ledgerText(t.home, t.sid)).toBe(before);
  });

  it("a failed append (half a write, then ENOSPC) → 500, the file truncated back, head unchanged, then 409 LEDGER_BROKEN; a WS client gets 4009; a fresh open loads the same head", async () => {
    const t = await makeApp({ port: 0 });
    await t.app.listen({ host: "127.0.0.1", port: 0 });
    const port = t.app.exmap.port();
    const s = await createSession(t.app, { story: STORY });
    const ws = new WebSocket(`ws://127.0.0.1:${port}/api/sessions/${s.id}/stream`, { origin: `http://127.0.0.1:${port}` });
    const frames: StreamMessage[] = [];
    const closed = new Promise<number>((resolve) => ws.on("close", (code) => resolve(code)));
    await new Promise<void>((resolve) => ws.on("message", (d) => {
      frames.push(JSON.parse(String(d)) as StreamMessage);
      resolve();
    }));
    const before = ledgerText(t.home, s.id);
    const headBefore = t.app.exmap.store.open(s.id).state.head;

    const realWrite = fs.writeSync;
    let writes = 0;
    vi.spyOn(fs, "writeSync").mockImplementation(((fd: number, buffer: Buffer, offset: number, length: number) => {
      writes++;
      if (writes === 1) return realWrite(fd, buffer, offset, Math.floor(length / 2));
      throw Object.assign(new Error("ENOSPC: no space left on device, write"), { code: "ENOSPC" });
    }) as unknown as typeof fs.writeSync);
    const truncate = vi.spyOn(fs, "ftruncateSync");

    const res = await call(t.app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "rule", text: "A receptionist may cancel for a patient." } });
    vi.restoreAllMocks();
    expect(res.statusCode).toBe(500);
    expect(json(res)).toMatchObject({ ok: false, reason: "LEDGER_WRITE_FAILED" });
    expect(writes).toBe(2);
    expect(truncate).toHaveBeenCalledWith(expect.any(Number), Buffer.byteLength(before));
    expect(ledgerText(t.home, s.id)).toBe(before);
    const listed = json<{ sessions: SessionSummary[] }>(await call(t.app, "GET", "/api/sessions")).sessions.find((x) => x.id === s.id)!;
    expect(listed.head).toEqual({ seq: headBefore.seq, hash: headBefore.hash });
    expect(listed.broken).toMatchObject({ code: "LEDGER_WRITE_FAILED" });
    const next = await call(t.app, "POST", `/api/sessions/${s.id}/cards`, { actor: "Ana", card: { kind: "rule", text: "Another rule entirely." } });
    expect(next.statusCode).toBe(409);
    expect(json(next)).toMatchObject({ reason: "LEDGER_BROKEN" });
    expect(await closed).toBe(4009);
    expect(frames.some((f) => f.type === "error" && f.reason === "LEDGER_BROKEN")).toBe(true);
    expect(ledgerText(t.home, s.id)).toBe(before);

    await t.app.close();
    const fresh = (await makeApp({ home: t.home })).app;
    const reopened = json<{ session: SessionSummary }>(await call(fresh, "GET", `/api/sessions/${s.id}`)).session;
    expect(reopened.head).toEqual({ seq: headBefore.seq, hash: headBefore.hash });
    expect(reopened.broken).toBeNull();
  });
});

describe("the prebuilt ledger fixtures (tests/fixtures/sessions)", () => {
  it("are byte-identical to the generator's output (the real core)", () => {
    const files = fixtureFiles();
    for (const key of Object.keys(FIXTURE_IDS) as Array<keyof typeof FIXTURE_IDS>) {
      const dir = join(FIXTURE_DIR, FIXTURE_IDS[key]);
      expect(fs.readFileSync(join(dir, "meta.json"), "utf8"), `${key} meta`).toBe(files[key].meta);
      expect(fs.readFileSync(join(dir, "events.jsonl"), "utf8"), `${key} events`).toBe(files[key].events);
    }
  });

  it("valid opens; tampered → HASH_MISMATCH at row 3; truncated → LEDGER_PARSE_ERROR at its last row", async () => {
    const home = tempHome();
    fs.cpSync(FIXTURE_DIR, join(home, "sessions"), { recursive: true });
    const { app } = await makeApp({ home });
    const valid = await call(app, "GET", `/api/sessions/${FIXTURE_IDS.valid}`);
    expect(valid.statusCode).toBe(200);
    const v = json<{ session: SessionSummary }>(valid).session;
    expect(v.head.seq).toBe(readLedger(home, FIXTURE_IDS.valid).length);
    expect(v.counts).toMatchObject({ utterances: 3, classified: 3, cards_live: 4 });
    expect(v.broken).toBeNull();
    const tampered = await call(app, "GET", `/api/sessions/${FIXTURE_IDS.tampered}`);
    expect(tampered.statusCode).toBe(409);
    expect(json(tampered)).toMatchObject({ reason: "LEDGER_BROKEN", row: 3, seq: 3, code: "HASH_MISMATCH" });
    const truncated = await call(app, "GET", `/api/sessions/${FIXTURE_IDS.truncated}`);
    expect(truncated.statusCode).toBe(409);
    const rows = fs.readFileSync(join(home, "sessions", FIXTURE_IDS.truncated, "events.jsonl"), "utf8").split("\n").length;
    expect(json(truncated)).toMatchObject({ reason: "LEDGER_BROKEN", code: "LEDGER_PARSE_ERROR", row: rows });
    const list = json<{ sessions: SessionSummary[] }>(await call(app, "GET", "/api/sessions")).sessions;
    expect(list.map((s) => [s.id, s.broken?.code ?? null]).sort()).toEqual([
      [FIXTURE_IDS.tampered, "HASH_MISMATCH"], [FIXTURE_IDS.truncated, "LEDGER_PARSE_ERROR"], [FIXTURE_IDS.valid, null],
    ].sort());
  });
});

describe("server.lock", () => {
  const opts = (home: string) => ({ home, port: 0, webDist: null, ortDir: null, env: {}, classifier: fakeClassifier() });

  it("a second startServer on the same home → HomeLockedError with the first's URL; close() removes the lock", async () => {
    const home = tempHome();
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const first = await startServer(opts(home));
    try {
      const lock = JSON.parse(fs.readFileSync(join(home, "server.lock"), "utf8")) as { pid: number; port: number; version: string };
      expect(lock).toMatchObject({ pid: process.pid, port: first.port, version: "0.1.0" });
      const err = await startServer(opts(home)).then(() => null, (e: unknown) => e);
      expect(err).toBeInstanceOf(HomeLockedError);
      expect((err as HomeLockedError).url).toBe(first.url);
    } finally {
      await first.close();
    }
    expect(fs.existsSync(join(home, "server.lock"))).toBe(false);
  });

  it("a dead pid's lock is taken over; a live pid without a port → HomeLockedError { url: null }", async () => {
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const child = spawn(process.execPath, ["-e", "0"]);
    const deadPid = child.pid!;
    await new Promise((r) => child.on("exit", r));
    const home = tempHome();
    fs.writeFileSync(join(home, "server.lock"), JSON.stringify({ pid: deadPid, started_at: "2026-10-16T00:00:00.000Z", version: "0.1.0", port: 4999 }));
    const srv = await startServer(opts(home));
    const lock = JSON.parse(fs.readFileSync(join(home, "server.lock"), "utf8")) as { pid: number; port: number };
    expect(lock).toMatchObject({ pid: process.pid, port: srv.port });
    await srv.close();

    const home2 = tempHome();
    fs.writeFileSync(join(home2, "server.lock"), JSON.stringify({ pid: process.pid, started_at: "2026-10-16T00:00:00.000Z", version: "0.1.0" }));
    const err = await startServer(opts(home2)).then(() => null, (e: unknown) => e);
    expect(err).toBeInstanceOf(HomeLockedError);
    expect((err as HomeLockedError).url).toBeNull();
    expect(fs.existsSync(join(home2, "server.lock"))).toBe(true); // not ours: left alone
    expect((err as Error).message).toContain(`delete ${join(home2, "server.lock")}`); // the remedy is printed
  });

  it("a lock with a port where no exmap with that pid answers is stale even though the pid is alive (pid reused after a crash or reboot; review finding)", async () => {
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const net = await import("node:net");
    const closed = await new Promise<number>((r) => { const srv = net.createServer().listen(0, "127.0.0.1", () => { const p = (srv.address() as { port: number }).port; srv.close(() => r(p)); }); });
    const sleeper = spawn(process.execPath, ["-e", "setTimeout(() => {}, 30000)"]);
    try {
      for (const pid of [sleeper.pid!, process.pid]) { // an unrelated live process, and this very process (same pid after a restart)
        const home = tempHome();
        fs.writeFileSync(join(home, "server.lock"), JSON.stringify({ pid, started_at: "2026-10-16T00:00:00.000Z", version: "0.1.0", port: closed }));
        const srv = await startServer(opts(home));
        const lock = JSON.parse(fs.readFileSync(join(home, "server.lock"), "utf8")) as { pid: number; port: number };
        expect(lock, `pid ${pid}`).toMatchObject({ pid: process.pid, port: srv.port });
        await srv.close();
      }
    } finally {
      sleeper.kill();
    }
  });
});
