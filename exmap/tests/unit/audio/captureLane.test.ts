// tests/unit/audio/captureLane.test.ts — TEST-PLAN §3 cases 32–39 (fake MediaDevicesLike, fake AudioGraph), plus the
// WebAudioGraph with fake AudioContext / worklet-node factories for "addModule ran once across two lanes".
import { describe, expect, it } from "vitest";
import { fixedClock } from "../../../src/web/audio/clock.js";
import { WebAudioGraph, type AudioContextLike, type WorkletNodeLike } from "../../../src/web/audio/dsp/graph.js";
import { GraphError, LaneStateError, mapDomException } from "../../../src/web/audio/errors.js";
import { CaptureLane, type CaptureLaneHooks } from "../../../src/web/audio/lanes/captureLane.js";
import type { CaptureLaneId, GuidanceReason, LaneSource, LaneView, Segment } from "../../../src/web/audio/types.js";
import { deferred, domException, FakeGraph, FakeMedia, FakeStream, FakeTrack, flush } from "./fakes.js";
import { framesAtDb, silence } from "./helpers.js";

interface Harness {
  lane: CaptureLane;
  media: FakeMedia;
  graph: FakeGraph;
  views: LaneView[];
  segments: Segment[];
  guidance: GuidanceReason[];
  dropped: string[];
  flushes: number;
}

function harness(id: CaptureLaneId, opts: { source?: LaneSource; speaker?: () => string | null; graph?: FakeGraph; media?: FakeMedia } = {}): Harness {
  const media = opts.media ?? new FakeMedia();
  const graph = opts.graph ?? new FakeGraph();
  const h: Harness = { lane: undefined as unknown as CaptureLane, media, graph, views: [], segments: [], guidance: [], dropped: [], flushes: 0 };
  const hooks: CaptureLaneHooks = {
    onView: (v) => h.views.push(v),
    onSegment: (s) => h.segments.push(s),
    onGuidance: (r) => h.guidance.push(r),
    onDeviceUnavailable: (d) => h.dropped.push(d),
    onFlush: () => h.flushes++,
  };
  h.lane = new CaptureLane({ id, media, graph, clock: fixedClock(5000), speaker: opts.speaker ?? (() => "Sam"), hooks, isSecureContext: true, ...(opts.source ? { source: opts.source } : {}) });
  return h;
}

describe("CaptureLane", () => {
  it("32. start() → requesting then live; the media request is synchronous; the video track is stopped; trackLabel set; ensureContext after the stream", async () => {
    const h = harness("remote");
    const video = new FakeTrack("video");
    const audio = new FakeTrack("audio", "Tab audio");
    const gate = deferred<MediaStream>();
    h.media.nextDisplay(() => gate.promise);
    const p = h.lane.start();
    expect(h.media.calls).toHaveLength(1); // called synchronously inside start()
    expect(h.media.calls[0]!.kind).toBe("display");
    expect(h.lane.view.state).toBe("requesting");
    expect(h.graph.ensureCalls).toBe(0);
    gate.resolve(new FakeStream([video, audio]).asStream());
    await p;
    expect(h.lane.view.state).toBe("live");
    expect(h.graph.ensureCalls).toBe(1);
    expect(h.graph.attachCalls).toEqual(["remote"]);
    expect(video.stopCalls).toBe(1);
    expect(audio.stopCalls).toBe(0);
    expect(h.lane.view.trackLabel).toBe("Tab audio");
    expect(h.lane.view.startedAtMs).toBe(5000);
    expect(h.views.map((v) => v.state)).toEqual(["requesting", "live"]);

    // the me lane calls getUserMedia with the device constraints
    const me = harness("me");
    await me.lane.start();
    expect(me.media.calls[0]!.kind).toBe("user");
    expect(me.media.calls[0]!.constraints).toMatchObject({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: { ideal: 1 } }, video: false });
    expect(me.lane.view.state).toBe("live");
  });

  it("32b. the worklet module is added once per context across two lanes (WebAudioGraph with fakes)", async () => {
    let addModuleCalls = 0;
    let contexts = 0;
    const ctx: AudioContextLike = {
      state: "running",
      sampleRate: 16000,
      audioWorklet: {
        addModule: async () => {
          addModuleCalls++;
        },
      },
      resume: async () => undefined,
      close: async () => undefined,
      createMediaStreamSource: () => ({ connect: () => undefined, disconnect: () => undefined }),
    };
    const nodes: Array<WorkletNodeLike & { posted: unknown[] }> = [];
    const graph = new WebAudioGraph({
      createContext: () => {
        contexts++;
        return ctx;
      },
      createWorkletNode: () => {
        const node = { posted: [] as unknown[], port: { postMessage: (m: unknown) => node.posted.push(m), onmessage: null as null | ((ev: { data: unknown }) => void) }, disconnect: () => undefined };
        nodes.push(node);
        return node;
      },
      flushTimeoutMs: 10,
    });
    const a = harness("remote", { graph: graph as unknown as FakeGraph });
    const b = harness("me", { graph: graph as unknown as FakeGraph });
    await a.lane.start();
    await b.lane.start();
    expect(contexts).toBe(1);
    expect(addModuleCalls).toBe(1);
    expect(nodes).toHaveLength(2);
    // frames from the worklet reach the lane; a flush answers { flushed }
    const frame = framesAtDb(1, -20)[0]!;
    nodes[1]!.port.onmessage?.({ data: { type: "frame", pcm: frame } });
    expect(b.lane.level).toBeGreaterThan(0);
    const stopping = b.lane.stop();
    expect(nodes[1]!.posted).toContainEqual({ type: "flush" });
    nodes[1]!.port.onmessage?.({ data: { type: "flushed" } });
    await stopping;
    expect(b.lane.view.state).toBe("stopped");

    // a worklet that fails to load is WORKLET_LOAD_FAILED
    const bad = new WebAudioGraph({
      createContext: () => ({ ...ctx, audioWorklet: { addModule: async () => Promise.reject(new Error("404")) } }),
      createWorkletNode: () => ({ port: { postMessage: () => undefined, onmessage: null }, disconnect: () => undefined }),
    });
    await expect(bad.ensureContext()).rejects.toBeInstanceOf(GraphError);
    await expect(bad.ensureContext()).rejects.toMatchObject({ code: "WORKLET_LOAD_FAILED" });
    const suspended = new WebAudioGraph({ createContext: () => ({ ...ctx, state: "suspended" }), createWorkletNode: () => ({ port: { postMessage: () => undefined, onmessage: null }, disconnect: () => undefined }) });
    await expect(suspended.ensureContext()).rejects.toMatchObject({ code: "AUDIO_CONTEXT_FAILED" });
  });

  it("33. a stream with no audio track → error NO_AUDIO_TRACK; every track stopped; guidance no_audio_track", async () => {
    const h = harness("remote");
    const video = new FakeTrack("video");
    h.media.nextDisplay(new FakeStream([video]));
    await h.lane.start();
    expect(h.lane.view.state).toBe("error");
    expect(h.lane.view.error?.code).toBe("NO_AUDIO_TRACK");
    expect(video.stopCalls).toBe(1);
    expect(h.guidance).toEqual(["no_audio_track"]);
    expect(h.graph.attachCalls).toHaveLength(0);
  });

  it("34. each DOMException name maps to its code with domName preserved; an unknown name → UNKNOWN", async () => {
    const table: Array<[string, string]> = [
      ["NotAllowedError", "PERMISSION_DENIED"],
      ["NotFoundError", "NO_DEVICE"],
      ["NotReadableError", "DEVICE_BUSY"],
      ["AbortError", "ABORTED"],
      ["InvalidStateError", "NOT_ACTIVATED"],
      ["TypeError", "BAD_CONSTRAINTS"],
      ["SecurityError", "INSECURE_CONTEXT"],
      ["NotSupportedError", "UNSUPPORTED"],
      ["SomethingElseError", "UNKNOWN"],
    ];
    for (const [name, code] of table) {
      const m = mapDomException(domException(name, `msg for ${name}`));
      expect(m).toEqual({ code, domName: name, message: `msg for ${name}` });
      const h = harness("me");
      h.media.nextUser(domException(name, `msg for ${name}`));
      await h.lane.start();
      expect(h.lane.view.state).toBe("error");
      expect(h.lane.view.error).toEqual({ code, domName: name, message: `msg for ${name}` });
    }
    expect(mapDomException("boom")).toEqual({ code: "UNKNOWN", domName: null, message: "boom" });
    const denied = harness("me");
    denied.media.nextUser(domException("NotAllowedError"));
    await denied.lane.start();
    expect(denied.guidance).toEqual(["permission_denied"]);
  });

  it("35. OverconstrainedError with a saved deviceId → one retry without it → live; a second failure → DEVICE_UNAVAILABLE and the id cleared", async () => {
    const h = harness("me", { source: { kind: "device", deviceId: "mic-123" } });
    h.media.nextUser(domException("OverconstrainedError"));
    h.media.nextUser(new FakeStream([new FakeTrack("audio", "Built-in")]));
    await h.lane.start();
    expect(h.media.calls).toHaveLength(2);
    expect((h.media.calls[0]!.constraints as MediaStreamConstraints).audio).toMatchObject({ deviceId: { exact: "mic-123" } });
    expect((h.media.calls[1]!.constraints as MediaStreamConstraints).audio).not.toHaveProperty("deviceId");
    expect(h.lane.view.state).toBe("live");
    expect(h.lane.view.source).toEqual({ kind: "device", deviceId: null });
    expect(h.dropped).toEqual(["mic-123"]);

    const twice = harness("me", { source: { kind: "device", deviceId: "mic-999" } });
    twice.media.nextUser(domException("OverconstrainedError"));
    twice.media.nextUser(domException("OverconstrainedError"));
    await twice.lane.start();
    expect(twice.lane.view.state).toBe("error");
    expect(twice.lane.view.error?.code).toBe("DEVICE_UNAVAILABLE");
    expect(twice.lane.view.source).toEqual({ kind: "device", deviceId: null });
    expect(twice.dropped).toEqual(["mic-999"]);
  });

  it("36. audio track ended while live → stopped with ended_by_browser (display) / device_lost (device); detached; the segmenter flushed", async () => {
    const h = harness("remote");
    const audio = new FakeTrack("audio");
    h.media.nextDisplay(new FakeStream([new FakeTrack("video"), audio]));
    await h.lane.start();
    h.graph.feed("remote", framesAtDb(40, -20)); // 800 ms of speech, not yet closed
    expect(h.segments).toHaveLength(0);
    audio.dispatch("ended");
    await flush();
    expect(h.lane.view.state).toBe("stopped");
    expect(h.lane.view.stopReason).toBe("ended_by_browser");
    expect(h.graph.detachCalls).toEqual(["remote"]);
    expect(h.flushes).toBe(1);
    expect(h.segments).toHaveLength(1);
    expect(h.segments[0]!.speechMs).toBe(800);
    expect(h.segments[0]!.speaker).toBe("Sam");
    expect(h.lane.view.segmentsClosed).toBe(1);

    const d = harness("me");
    const mic = new FakeTrack("audio");
    d.media.nextUser(new FakeStream([mic]));
    await d.lane.start();
    mic.dispatch("ended");
    await flush();
    expect(d.lane.view.state).toBe("stopped");
    expect(d.lane.view.stopReason).toBe("device_lost");
    expect(d.flushes).toBe(1);
    expect(d.segments).toHaveLength(0); // nothing was in speech
  });

  it("37. mute/unmute toggle signal; 10 s of frames under −60 dB → silent; a loud frame → signal", async () => {
    const h = harness("me");
    const mic = new FakeTrack("audio");
    h.media.nextUser(new FakeStream([mic]));
    await h.lane.start();
    expect(h.lane.view.signal).toBe("unknown");
    mic.dispatch("mute");
    expect(h.lane.view.signal).toBe("silent");
    mic.dispatch("unmute");
    expect(h.lane.view.signal).toBe("signal");
    h.graph.feed("me", silence(499));
    expect(h.lane.view.signal).toBe("signal");
    h.graph.feed("me", silence(1));
    expect(h.lane.view.signal).toBe("silent");
    const signalChanges = h.views.filter((v) => v.state === "live").map((v) => v.signal);
    expect(signalChanges.filter((s, i, a) => i === 0 || s !== a[i - 1])).toEqual(["unknown", "silent", "signal", "silent"]); // published only on change
    h.graph.feed("me", framesAtDb(1, -20));
    expect(h.lane.view.signal).toBe("signal");
    expect(h.lane.level).toBeGreaterThan(0.5);
  });

  it("38. illegal transitions and teardown guarantees", async () => {
    const h = harness("me");
    const gate = deferred<MediaStream>();
    h.media.nextUser(() => gate.promise);
    const starting = h.lane.start();
    await expect(h.lane.start()).rejects.toBeInstanceOf(LaneStateError);
    expect(() => h.lane.setSource({ kind: "device", deviceId: "x" })).toThrow(LaneStateError);
    // stop() while requesting: the later stream is stopped, never attached
    await h.lane.stop();
    expect(h.lane.view.state).toBe("stopped");
    const late = new FakeTrack("audio");
    gate.resolve(new FakeStream([late]).asStream());
    await starting;
    expect(late.stopCalls).toBe(1);
    expect(h.graph.attachCalls).toHaveLength(0);
    expect(h.lane.view.state).toBe("stopped");

    // stop() in idle / stopped / error is a no-op
    const idle = harness("me");
    await idle.lane.stop();
    expect(idle.lane.view.state).toBe("idle");
    expect(idle.views).toHaveLength(0);
    await h.lane.stop();
    expect(h.lane.view.state).toBe("stopped");

    // start() while live rejects; setSource while live throws
    const live = harness("me");
    await live.lane.start();
    await expect(live.lane.start()).rejects.toBeInstanceOf(LaneStateError);
    expect(() => live.lane.setSource({ kind: "device", deviceId: "y" })).toThrow(LaneStateError);
    await live.lane.stop();
    expect(() => live.lane.setSource({ kind: "device", deviceId: "y" })).not.toThrow();
    expect(live.lane.view.source).toEqual({ kind: "device", deviceId: "y" });

    // attach throwing → WORKLET_LOAD_FAILED with all tracks stopped
    const bad = harness("me");
    bad.graph.attachError = new GraphError("WORKLET_LOAD_FAILED", "addModule failed");
    const t = new FakeTrack("audio");
    bad.media.nextUser(new FakeStream([t]));
    await bad.lane.start();
    expect(bad.lane.view.state).toBe("error");
    expect(bad.lane.view.error?.code).toBe("WORKLET_LOAD_FAILED");
    expect(t.stopCalls).toBe(1);

    // ensureContext throwing → AUDIO_CONTEXT_FAILED
    const ctxFail = harness("me");
    ctxFail.graph.ensureError = new GraphError("AUDIO_CONTEXT_FAILED", "did not resume");
    const t2 = new FakeTrack("audio");
    ctxFail.media.nextUser(new FakeStream([t2]));
    await ctxFail.lane.start();
    expect(ctxFail.lane.view.error?.code).toBe("AUDIO_CONTEXT_FAILED");
    expect(t2.stopCalls).toBe(1);

    // an error lane can start again (error and stopReason cleared)
    ctxFail.graph.ensureError = null;
    await ctxFail.lane.start();
    expect(ctxFail.lane.view.state).toBe("live");
    expect(ctxFail.lane.view.error).toBeNull();
  });

  it("39. getDisplayMedia undefined → UNSUPPORTED without calling anything", async () => {
    const h = harness("remote");
    h.media.hasDisplay = false;
    await h.lane.start();
    expect(h.lane.view.state).toBe("error");
    expect(h.lane.view.error?.code).toBe("UNSUPPORTED");
    expect(h.media.calls).toHaveLength(0);
    expect(h.graph.ensureCalls).toBe(0);
    expect(h.guidance).toEqual(["unsupported"]);
    const none = new CaptureLane({ id: "remote", media: null, graph: new FakeGraph(), clock: fixedClock(), speaker: () => null, isSecureContext: true });
    await none.start();
    expect(none.view.error?.code).toBe("UNSUPPORTED");
    const insecure = new CaptureLane({ id: "me", media: new FakeMedia(), graph: new FakeGraph(), clock: fixedClock(), speaker: () => null, isSecureContext: false });
    await insecure.start();
    expect(insecure.view.error?.code).toBe("INSECURE_CONTEXT");
  });
});
