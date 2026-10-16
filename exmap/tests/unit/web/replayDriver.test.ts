// TEST-PLAN §6.8 — ReplayDriver over a fake controller: playUntil plays in instant mode to the label then awaits idle;
// skip calls skipReplay; playAll plays the rest; position follows the controller's replay index.
import { describe, expect, it, vi } from "vitest";
import type { ReplayStatus } from "../../../src/web/audio/types.js";
import type { PostOutcome, UtteranceWire } from "../../../src/web/audio/types.js";
import { RecordingSink, ReplayDriver, ledgerHolds, ledgerSettled } from "../../../src/web/replay/driver.js";
import { staticSource } from "../../../src/web/store/useSession.js";
import { classify } from "../core/fixtures.js";
import { MapBuilder } from "./helpers.js";

function fakeController() {
  const status: ReplayStatus = { fixture: "demo", state: "ready", index: 0, total: 31, speed: "instant", until: null };
  const calls: string[] = [];
  return {
    status,
    calls,
    playReplay: vi.fn(async (speed: "instant" | 0.5 | 1 | 2 | 4, opts?: { until?: number | string }) => {
      calls.push(`play:${speed}:${opts?.until ?? "all"}`);
      status.index = opts?.until === undefined ? status.total : status.index + 5;
      status.state = opts?.until === undefined ? "done" : "paused";
    }),
    skipReplay: vi.fn((until: number | string) => {
      calls.push(`skip:${until}`);
      status.index += 1;
    }),
    getState: () => ({ replay: status }),
  };
}

describe("ReplayDriver", () => {
  it("playUntil plays instant to the label, then awaits the post queue", async () => {
    const c = fakeController();
    const idle = vi.fn(async () => {
      c.calls.push("idle");
    });
    const driver = new ReplayDriver({ controller: c, postQueueIdle: idle });
    await driver.playUntil("u05");
    expect(c.playReplay).toHaveBeenCalledWith("instant", { until: "u05" });
    expect(c.calls).toEqual(["play:instant:u05", "idle"]);
    expect(driver.position).toBe(5);
  });

  it("skip calls skipReplay without emitting and then waits for idle", async () => {
    const c = fakeController();
    const idle = vi.fn(async () => {
      c.calls.push("idle");
    });
    const driver = new ReplayDriver({ controller: c, postQueueIdle: idle });
    await driver.skip("u06");
    expect(c.skipReplay).toHaveBeenCalledWith("u06");
    expect(c.playReplay).not.toHaveBeenCalled();
    expect(c.calls).toEqual(["skip:u06", "idle"]);
    expect(driver.position).toBe(1);
  });

  it("playAll plays the rest and awaits idle, then the optional settled hook", async () => {
    const c = fakeController();
    const order: string[] = [];
    const driver = new ReplayDriver({
      controller: c,
      postQueueIdle: async () => {
        order.push("idle");
      },
      settled: async () => {
        order.push("settled");
      },
    });
    await driver.playAll();
    expect(c.playReplay).toHaveBeenCalledWith("instant");
    expect(order).toEqual(["idle", "settled"]);
    expect(driver.position).toBe(31);
    expect(driver.status.state).toBe("done");
  });

  it("position follows the controller's replay index", () => {
    const c = fakeController();
    const driver = new ReplayDriver({ controller: c, postQueueIdle: async () => {} });
    expect(driver.position).toBe(0);
    c.status.index = 12;
    expect(driver.position).toBe(12);
  });

  it("waits for the fixture to be ready before playing", async () => {
    const c = fakeController();
    let release!: () => void;
    const ready = new Promise<void>((r) => (release = r));
    const driver = new ReplayDriver({ controller: c, postQueueIdle: async () => {}, ready });
    const run = driver.playUntil("u02");
    await Promise.resolve();
    expect(c.playReplay).not.toHaveBeenCalled();
    release();
    await run;
    expect(c.playReplay).toHaveBeenCalledWith("instant", { until: "u02" });
  });

  it("settles once the reduced ledger holds every posted utterance with its classification record", async () => {
    const accepted: PostOutcome = { ok: true, eventId: "evt_1", duplicate: false };
    const refused: PostOutcome = { ok: false, kind: "refused", status: 422, reason: "EMPTY_TEXT", detail: "" };
    const sink = new RecordingSink({ post: async (u: UtteranceWire) => (u.text ? accepted : refused) });
    const b = new MapBuilder();
    const u1 = b.utter("Right, let's start.");
    const wire = (id: string, text: string) => ({ ...b.state.utterances.find((u) => u.id === id)!, id, text });
    await sink.post(wire(u1, "Right, let's start."));
    await sink.post(wire("utt_refused", ""));
    expect(sink.posted).toEqual([u1]); // a refused post never lands, so it is not waited for
    const source = staticSource(b.state);
    expect(ledgerHolds(b.state, sink.posted)).toBe(false); // recorded, not yet classified
    let settled = false;
    const done = ledgerSettled(source, sink, 5_000)().then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    b.run(classify(u1, "none", []));
    source.set(b.state);
    await done;
    expect(settled).toBe(true);
  });

  it("the recording sink sends one post at a time, in emission order", async () => {
    const sent: string[] = [];
    const releases: Array<() => void> = [];
    const sink = new RecordingSink({
      post: (u: UtteranceWire) =>
        new Promise<PostOutcome>((resolve) => {
          sent.push(u.id);
          releases.push(() => resolve({ ok: true, eventId: `evt_${u.id}`, duplicate: false }));
        }),
    });
    const b = new MapBuilder();
    const ids = [b.utter("u04 text"), b.utter("u05 text")];
    const wires = ids.map((id) => b.state.utterances.find((u) => u.id === id)!);
    const first = sink.post(wires[0]!);
    const second = sink.post(wires[1]!);
    await Promise.resolve();
    await Promise.resolve();
    expect(sent).toEqual([ids[0]]); // the second waits for the first answer
    releases[0]!();
    await first;
    await new Promise((r) => setTimeout(r, 0));
    expect(sent).toEqual(ids);
    releases[1]!();
    await second;
    expect(sink.posted).toEqual(ids);
  });
});
