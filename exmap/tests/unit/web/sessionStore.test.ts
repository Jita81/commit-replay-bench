// TEST-PLAN §6.2 — SessionStore over a fake WebSocket: hello then events reduce; a gap resyncs with after = head.seq;
// a duplicate is ignored; a wrong prev_hash or a tampered hash is terminal (no reconnect, no further reduction);
// the reconnect backoff sequence; an export.options_set event reduces into export_options.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExmapEvent, StreamMessage } from "../../../src/core/types.js";
import { sha256 } from "../../../src/web/hash.js";
import { BACKOFF_MS, SessionStore, type WebSocketLike } from "../../../src/web/store/sessionStore.js";
import { MapBuilder, SESSION_ID, richMap } from "./helpers.js";

class FakeWS implements WebSocketLike {
  static instances: FakeWS[] = [];
  readyState = 0;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  closedWith: Array<number | undefined> = [];
  constructor(readonly url: string) {
    FakeWS.instances.push(this);
  }
  close(code?: number): void {
    this.readyState = 3;
    this.closedWith.push(code);
  }
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }
  frame(msg: StreamMessage): void {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  hello(after = 0): void {
    this.frame({ type: "hello", session_id: SESSION_ID, head: { seq: 0, hash: "" }, after });
  }
  event(e: ExmapEvent): void {
    this.frame({ type: "event", event: e });
  }
  serverClose(code?: number, reason = ""): void {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

function makeStore() {
  const store = new SessionStore({ sessionId: SESSION_ID, sha256, wsUrl: (after) => `ws://127.0.0.1/api/sessions/${SESSION_ID}/stream?after=${after}`, WebSocketCtor: FakeWS });
  store.connect();
  const ws = FakeWS.instances[FakeWS.instances.length - 1]!;
  ws.open();
  return { store, ws };
}

describe("SessionStore", () => {
  beforeEach(() => {
    FakeWS.instances = [];
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reduces hello then events exactly as the server did", () => {
    const { b, ids } = richMap();
    const { store, ws } = makeStore();
    const seen: number[] = [];
    store.subscribe(() => seen.push(store.getState().head.seq));
    ws.hello();
    expect(store.getStatus().connection).toBe("live");
    for (const e of b.events) ws.event(e);
    const state = store.getState();
    expect(state.head.seq).toBe(b.events.length);
    expect(state.head.hash).toBe(b.state.head.hash);
    expect(store.getStatus().head).toEqual({ seq: b.events.length, hash: b.state.head.hash });
    expect(state.cards[ids.rule]?.version).toBe(2);
    expect(state.cards[ids.exRemoved]?.status).toBe("rejected");
    expect(Object.keys(state.clarifications)).toEqual([ids.clar]);
    expect(JSON.stringify(state.cards)).toBe(JSON.stringify(b.state.cards));
    expect(seen.length).toBeGreaterThanOrEqual(b.events.length);
    expect(store.eventSeq(b.events[3]!.id)).toBe(4);
  });

  it("a seq gap resyncs by reopening with after = head.seq", () => {
    const { b } = richMap();
    const { store, ws } = makeStore();
    ws.hello();
    ws.event(b.events[0]!);
    ws.event(b.events[1]!);
    ws.event(b.events[3]!); // seq 4 while head is 2
    expect(store.getState().head.seq).toBe(2);
    expect(FakeWS.instances).toHaveLength(2);
    expect(FakeWS.instances[1]!.url).toContain("after=2");
    expect(ws.closedWith.length).toBeGreaterThan(0);
    expect(store.getStatus().chainError).toBeNull();
    // the replacement delivers the missing events
    const ws2 = FakeWS.instances[1]!;
    ws2.open();
    ws2.hello(2);
    ws2.event(b.events[2]!);
    ws2.event(b.events[3]!);
    expect(store.getState().head.seq).toBe(4);
  });

  it("ignores a duplicate seq", () => {
    const { b } = richMap();
    const { store, ws } = makeStore();
    ws.hello();
    ws.event(b.events[0]!);
    ws.event(b.events[0]!);
    ws.event(b.events[1]!);
    ws.event(b.events[0]!);
    expect(store.getState().head.seq).toBe(2);
    expect(store.getStatus().chainError).toBeNull();
    expect(FakeWS.instances).toHaveLength(1);
  });

  it("seq === head + 1 with a wrong prev_hash is a chain break: terminal, no reconnect, no further reduction", () => {
    const { b } = richMap();
    const { store, ws } = makeStore();
    ws.hello();
    ws.event(b.events[0]!);
    ws.event({ ...b.events[1]!, prev_hash: "0".repeat(64) });
    const status = store.getStatus();
    expect(status.chainError?.code).toBe("PREV_HASH_MISMATCH");
    expect(status.chainError?.seq).toBe(2);
    expect(status.connection).toBe("closed");
    expect(store.getState().head.seq).toBe(1);
    ws.event(b.events[1]!);
    expect(store.getState().head.seq).toBe(1);
    ws.serverClose(1006);
    expect(FakeWS.instances).toHaveLength(1);
    expect(store.getStatus().connection).toBe("closed");
  });

  it("a tampered hash is terminal and nothing after it is reduced", () => {
    const { b } = richMap();
    const { store, ws } = makeStore();
    ws.hello();
    ws.event(b.events[0]!);
    const tampered = { ...b.events[1]!, hash: "f".repeat(64) };
    ws.event(tampered);
    expect(store.getStatus().chainError?.code).toBe("HASH_MISMATCH");
    expect(store.getState().head.seq).toBe(1);
    ws.event(b.events[2]!);
    expect(store.getState().head.seq).toBe(1);
    expect(store.terminal).toBe(true);
  });

  it("an event from another session is SESSION_MISMATCH", () => {
    const { b } = richMap();
    const { store, ws } = makeStore();
    ws.hello();
    ws.event({ ...b.events[0]!, session_id: "ses_other_000001" });
    expect(store.getStatus().chainError?.code).toBe("SESSION_MISMATCH");
    expect(store.getState().head.seq).toBe(0);
  });

  it("reconnects with the 0.5 → 1 → 2 → 4 → 8 s backoff and resets on hello", () => {
    vi.useFakeTimers();
    const { store, ws } = makeStore();
    ws.hello();
    const delays: number[] = [];
    let current = ws;
    for (let i = 0; i < 6; i++) {
      current.serverClose(1006);
      const status = store.getStatus();
      expect(status.connection).toBe("reconnecting");
      delays.push(status.nextRetryMs!);
      const before = FakeWS.instances.length;
      vi.advanceTimersByTime(status.nextRetryMs! - 1);
      expect(FakeWS.instances.length).toBe(before);
      vi.advanceTimersByTime(1);
      expect(FakeWS.instances.length).toBe(before + 1);
      current = FakeWS.instances[FakeWS.instances.length - 1]!;
      current.open();
    }
    expect(delays).toEqual([...BACKOFF_MS, 8000]);
    current.hello();
    expect(store.getStatus().connection).toBe("live");
    expect(store.getStatus().attempt).toBe(0);
    current.serverClose(1006);
    expect(store.getStatus().nextRetryMs).toBe(500);
  });

  it("a 4004 / 4009 close is named and not retried", () => {
    vi.useFakeTimers();
    const { store, ws } = makeStore();
    ws.frame({ type: "error", reason: "LEDGER_BROKEN", detail: "row 7", row: 7 });
    ws.serverClose(4009);
    expect(store.getStatus().connection).toBe("closed");
    expect(store.getStatus().closeReason).toEqual({ reason: "LEDGER_BROKEN", detail: "row 7", code: 4009 });
    vi.advanceTimersByTime(20_000);
    expect(FakeWS.instances).toHaveLength(1);
  });

  it("an export.options_set event reduces into export_options", () => {
    const b = new MapBuilder();
    b.human({ kind: "card.create", card: { kind: "story", text: "A patient cancels an appointment online" } });
    b.run({ kind: "export.options_set", options: { capability_class: "backend.route.edit", kind: "code", size_estimate: "M", facts: [{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }], by: "Sam" } });
    const { store, ws } = makeStore();
    ws.hello();
    for (const e of b.events) ws.event(e);
    const opts = store.getState().export_options;
    expect(opts).toHaveLength(1);
    expect(opts[0]).toMatchObject({ capability_class: "backend.route.edit", seq: 1, by: "Sam" });
    expect(opts[0]!.facts).toEqual([{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }]);
  });

  it("connect after dispose reopens from the head (React may unmount and remount the same store)", () => {
    const { b } = richMap();
    const { store, ws } = makeStore();
    ws.hello();
    ws.event(b.events[0]!);
    store.dispose();
    store.connect();
    expect(FakeWS.instances).toHaveLength(2);
    expect(FakeWS.instances[1]!.url).toContain("after=1");
    expect(store.getStatus().connection).toBe("connecting");
    FakeWS.instances[1]!.open();
    FakeWS.instances[1]!.hello(1);
    expect(store.getStatus().connection).toBe("live");
  });

  it("dispose closes the socket and stops reconnecting", () => {
    vi.useFakeTimers();
    const { store, ws } = makeStore();
    ws.hello();
    store.dispose();
    expect(ws.closedWith.length).toBe(1);
    expect(store.getStatus().connection).toBe("closed");
    vi.advanceTimersByTime(20_000);
    expect(FakeWS.instances).toHaveLength(1);
  });
});
