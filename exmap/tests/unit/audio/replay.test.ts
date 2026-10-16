// tests/unit/audio/replay.test.ts — TEST-PLAN §3 cases 25–31.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fixedClock } from "../../../src/web/audio/clock.js";
import { ProviderError } from "../../../src/web/audio/errors.js";
import { estimateDurationMs, parseReplayFixture, ReplayProvider, type ReplayTimers } from "../../../src/web/audio/providers/replay.js";
import { SpeakerStore } from "../../../src/web/audio/speakers.js";
import type { ProviderContext, ReplayFixture, Segment, UtteranceDraft } from "../../../src/web/audio/types.js";

const shipped: unknown = JSON.parse(readFileSync(new URL("../../../src/web/public/replay/conversation.v1.json", import.meta.url), "utf8"));

function fakeTimers(): ReplayTimers & { advance(ms: number): void; now(): number } {
  let now = 0;
  let seq = 0;
  const pending = new Map<number, { at: number; fn: () => void }>();
  return {
    now: () => now,
    setTimeout: (fn, ms) => {
      const id = ++seq;
      pending.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout: (h) => {
      pending.delete(h as number);
    },
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...pending.entries()].filter(([, p]) => p.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        pending.delete(due[0]);
        now = due[1].at;
        due[1].fn();
      }
      now = end;
    },
  };
}

function ctx(clockMs = 0): { ctx: ProviderContext; emitted: UtteranceDraft[] } {
  const emitted: UtteranceDraft[] = [];
  const speakers = new SpeakerStore({ userName: "Sam" });
  speakers.set("remote", "Priya");
  const clock = fixedClock(clockMs);
  return { ctx: { emit: (d) => emitted.push(d), clock, speakers, signal: new AbortController().signal }, emitted };
}

async function started(timers?: ReplayTimers, clockMs = 0): Promise<{ p: ReplayProvider; emitted: UtteranceDraft[] }> {
  const p = new ReplayProvider(timers ? { timers } : {});
  const c = ctx(clockMs);
  await p.start(c.ctx);
  p.load(parseReplayFixture(shipped), "demo");
  return { p, emitted: c.emitted };
}

const base = (): Record<string, unknown> => ({
  version: 1,
  title: "t",
  utterances: [
    { label: "u01", atMs: 0, lane: "me", speaker: "Sam", text: "one" },
    { label: "u02", atMs: 1000, lane: "remote", speaker: null, text: "two" },
  ],
});

describe("replay", () => {
  it("25. parseReplayFixture accepts the shipped fixture and rejects each malformation naming index and field", () => {
    const f = parseReplayFixture(shipped);
    expect(f.utterances).toHaveLength(31);
    expect(f.story).toBeTypeOf("string");
    expect(f.speakers).toEqual({ remote: "Priya", me: "Sam" });
    expect(f.ui).toBeDefined();
    expect(f.utterances[4]!.label).toBe("u05");
    expect(f.utterances[1]!.expect).toBeDefined();

    const bad = (mutate: (o: Record<string, unknown>) => void, re: RegExp) => {
      const o = base();
      mutate(o);
      let err: unknown;
      try {
        parseReplayFixture(o);
      } catch (e) {
        err = e;
      }
      expect(err).toBeInstanceOf(ProviderError);
      expect((err as ProviderError).code).toBe("REPLAY_FIXTURE_INVALID");
      expect((err as ProviderError).detail).toMatch(re);
    };
    bad((o) => delete o["version"], /^fixture: version/);
    bad((o) => (o["utterances"] = {}), /^fixture: utterances/);
    bad((o) => ((o["utterances"] as Record<string, unknown>[])[1]!["lane"] = "phone"), /^1: lane/);
    bad((o) => ((o["utterances"] as Record<string, unknown>[])[1]!["atMs"] = -5), /^1: atMs/);
    bad((o) => ((o["utterances"] as Record<string, unknown>[])[0]!["atMs"] = 5000), /^1: atMs: must be non-decreasing/);
    bad((o) => ((o["utterances"] as Record<string, unknown>[])[0]!["text"] = "  "), /^0: text/);
    bad((o) => ((o["utterances"] as Record<string, unknown>[])[1]!["label"] = "u01"), /^1: label: duplicate/);
    bad((o) => (o["extra"] = 1), /^fixture: extra: unknown key/);
    bad((o) => ((o["utterances"] as Record<string, unknown>[])[0]!["id"] = "x"), /^0: id: unknown key/);
  });

  it("26. instant mode emits all utterances in order synchronously; play() resolves; state === 'done'", async () => {
    const { p, emitted } = await started();
    const promise = p.play("instant");
    expect(emitted).toHaveLength(31); // synchronous
    expect(emitted.map((e) => e.text)).toEqual(parseReplayFixture(shipped).utterances.map((u) => u.text));
    await promise;
    expect(p.status.state).toBe("done");
    expect(p.status.index).toBe(31);
  });

  it("27. breakpoints: until 'u05' → paused at 5; step() emits u06; resume() emits the rest; until: 2 → three; unknown label rejects", async () => {
    const { p, emitted } = await started();
    await p.play("instant", { until: "u05" });
    expect(emitted).toHaveLength(5);
    expect(p.status.state).toBe("paused");
    expect(p.status.index).toBe(5);
    p.step();
    expect(emitted).toHaveLength(6);
    expect(emitted[5]!.text).toBe("Delete that example. It's not what I meant.".length > 0 ? parseReplayFixture(shipped).utterances[5]!.text : "");
    expect(p.status.state).toBe("paused");
    p.resume();
    expect(emitted).toHaveLength(31);
    expect(p.status.state).toBe("done");

    const second = await started();
    await second.p.play("instant", { until: 2 });
    expect(second.emitted).toHaveLength(3);
    await expect(second.p.play("instant", { until: "u99" })).rejects.toMatchObject({ code: "REPLAY_FIXTURE_INVALID" });
  });

  it("28. skip('u06') after until 'u05' advances index to 6 without emitting; play then continues from u07", async () => {
    const { p, emitted } = await started();
    await p.play("instant", { until: "u05" });
    p.skip("u06");
    expect(emitted).toHaveLength(5);
    expect(p.status.index).toBe(6);
    await p.play("instant", { until: "u07" });
    expect(emitted).toHaveLength(6);
    expect(emitted[5]!.text).toBe(parseReplayFixture(shipped).utterances[6]!.text);
  });

  it("29. timed mode at ×2: an utterance at 4000 ms emits at 2000 ms; pause at 1000 and resume 5 s later emits at 7000", async () => {
    const timers = fakeTimers();
    const { p, emitted } = await started(timers);
    const done = p.play(2, { until: 1 });
    timers.advance(0);
    expect(emitted).toHaveLength(1); // u01 at atMs 0
    timers.advance(1999);
    expect(emitted).toHaveLength(1);
    timers.advance(1);
    expect(emitted).toHaveLength(2);
    expect(timers.now()).toBe(2000);
    await done;
    expect(p.status.state).toBe("paused");

    const t2 = fakeTimers();
    const second = await started(t2);
    void second.p.play(2, { until: 1 });
    t2.advance(1000);
    second.p.pause();
    expect(second.p.status.state).toBe("paused");
    t2.advance(5000);
    expect(second.emitted).toHaveLength(1);
    second.p.resume();
    t2.advance(999);
    expect(second.emitted).toHaveLength(1);
    t2.advance(1);
    expect(second.emitted).toHaveLength(2);
    expect(t2.now()).toBe(7000);
  });

  it("30. times are session-relative from the first play(); speaker falls back to the lane label; provider/isLocal/confidence fixed", async () => {
    const fixture: ReplayFixture = {
      version: 1,
      title: "t",
      utterances: [
        { atMs: 500, lane: "me", speaker: "Sam", text: "first words here", durationMs: 900 },
        { atMs: 4500, lane: "remote", speaker: null, text: "second one", durationMs: 1200 },
        { atMs: 5000, lane: "me", speaker: null, text: "three words now" },
      ],
    };
    const p = new ReplayProvider();
    const c = ctx(90_000);
    await p.start(c.ctx);
    p.load(fixture, "custom");
    await p.play("instant");
    expect(c.emitted[0]!.tStartMs).toBe(90_000);
    expect(c.emitted[1]!.tStartMs).toBe(94_000);
    expect(c.emitted[1]!.tEndMs).toBe(94_000 + 1200);
    expect(c.emitted[2]!.tEndMs).toBe(c.emitted[2]!.tStartMs + estimateDurationMs("three words now"));
    expect(estimateDurationMs("three words now")).toBe(250 + 60 * 3);
    expect(c.emitted[1]!.speaker).toBe("Priya");
    expect(c.emitted[2]!.speaker).toBe("Sam");
    for (const e of c.emitted) {
      expect(e.provider).toBe("replay");
      expect(e.isLocal).toBe(true);
      expect(e.confidence).toBeNull();
      expect(e.model).toBeNull();
    }
  });

  it("31. transcribe() rejects NOT_SEGMENT_PROVIDER", async () => {
    const { p } = await started();
    const segment = { lane: "me", seq: 1, startedAt: 0, onsetAt: 0, endedAt: 500, speechMs: 500, pcm: new Float32Array(8000), sampleRate: 16000, peakRmsDb: -20, cappedAt15s: false, speaker: null } as Segment;
    await expect(p.transcribe(segment)).rejects.toMatchObject({ code: "NOT_SEGMENT_PROVIDER" });
  });
});
