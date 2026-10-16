// TEST-PLAN §6.8 — ReplayDriver over a fake controller: playUntil plays in instant mode to the label then awaits idle;
// skip calls skipReplay; playAll plays the rest; position follows the controller's replay index.
import { describe, expect, it, vi } from "vitest";
import type { ReplayStatus } from "../../../src/web/audio/types.js";
import { ReplayDriver } from "../../../src/web/replay/driver.js";

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
});
