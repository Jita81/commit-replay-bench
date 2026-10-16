// tests/unit/audio/queues.test.ts — TEST-PLAN §3 cases 40–44: TranscriptionQueue, the controller's lane-stop rule,
// PostQueue, HttpUtteranceSink, buildUtterance (through core's apply).
import { describe, expect, it } from "vitest";
import { apply } from "../../../src/core/apply.js";
import { initialState } from "../../../src/core/reduce.js";
import { fixedClock } from "../../../src/web/audio/clock.js";
import { AudioController } from "../../../src/web/audio/controller.js";
import { PostError, ProviderError } from "../../../src/web/audio/errors.js";
import { PostQueue, POST_BACKOFF_MS } from "../../../src/web/audio/pipeline/postQueue.js";
import { classifyResponse, HttpUtteranceSink, type FetchLike } from "../../../src/web/audio/pipeline/sink.js";
import { TranscriptionQueue } from "../../../src/web/audio/pipeline/transcriptionQueue.js";
import { buildUtterance } from "../../../src/web/audio/pipeline/utteranceBuilder.js";
import { memoryStorage, MODEL_SEEN_KEY } from "../../../src/web/audio/settings.js";
import { SpeakerStore } from "../../../src/web/audio/speakers.js";
import type { PostOutcome, Segment, UtteranceDraft, UtteranceWire } from "../../../src/web/audio/types.js";
import { testCtx } from "../core/fixtures.js";
import { FakeGraph, FakeMedia, FakePushProvider, FakeSegmentProvider, FakeStream, FakeTrack, fakeTimers, flush, ScriptedSink } from "./fakes.js";
import { framesAtDb, silence } from "./helpers.js";

function seg(lane: "remote" | "me", seq: number, startedAt = seq * 1000): Segment {
  return { lane, seq, startedAt, onsetAt: startedAt + 100, endedAt: startedAt + 900, speechMs: 700, pcm: new Float32Array(320 * 45), sampleRate: 16000, peakRmsDb: -20, cappedAt15s: false, speaker: null };
}

describe("TranscriptionQueue", () => {
  it("40. FIFO across lanes, one in flight, backlog counts, the restart-and-retry path, failed/retryFailed, null and push providers", async () => {
    const whisper = new FakeSegmentProvider();
    const texts: string[] = [];
    const errors: Array<{ code: string; final: boolean }> = [];
    let restarts = 0;
    const q = new TranscriptionQueue({
      provider: (lane) => (lane === "remote" ? whisper : null),
      onText: (s, r) => texts.push(`${s.lane}${s.seq}:${r.text}`),
      onError: (_s, e, final) => errors.push({ code: e.code, final }),
      restartProvider: async () => {
        restarts++;
        return true;
      },
    });
    expect(q.enqueue(seg("me", 1))).toBe(false);
    expect(q.segmentsWaiting).toBe(0);
    expect(q.enqueue(seg("remote", 1))).toBe(true);
    expect(q.enqueue(seg("remote", 2))).toBe(true);
    expect(q.enqueue(seg("remote", 3))).toBe(true);
    await flush();
    expect(q.inFlight).toBe(1);
    expect(q.segmentsWaiting).toBe(2);
    expect(q.speechWaitingMs).toBe(1400);
    expect(q.oldestWaitingMs).toBe(2000);
    expect(whisper.pending).toHaveLength(1);
    whisper.resolveNext("one");
    await flush();
    expect(texts).toEqual(["remote1:one"]);
    expect(whisper.pending).toHaveLength(1);
    // first failure: paused, restart hook once, same segment retried once
    whisper.rejectNext(new ProviderError("TRANSCRIBE_FAILED", "boom"));
    await flush();
    expect(restarts).toBe(1);
    expect(errors).toEqual([{ code: "TRANSCRIBE_FAILED", final: false }]);
    expect(whisper.pending).toHaveLength(1);
    expect(whisper.pending[0]!.segment.seq).toBe(2);
    // second failure of the same segment: set aside; the queue pauses
    whisper.rejectNext(new ProviderError("TRANSCRIBE_TIMEOUT", "slow"));
    await flush();
    expect(q.failed.map((s) => s.seq)).toEqual([2]);
    expect(errors[1]).toEqual({ code: "TRANSCRIBE_TIMEOUT", final: true });
    expect(q.paused).toBe(true);
    expect(restarts).toBe(1);
    expect(whisper.pending).toHaveLength(0);
    // Retry re-enqueues the failed segment after the waiting one and resumes
    q.retryFailed();
    await flush();
    expect(q.failed).toHaveLength(0);
    expect(whisper.pending[0]!.segment.seq).toBe(3);
    whisper.resolveNext("three");
    await flush();
    expect(whisper.pending[0]!.segment.seq).toBe(2);
    whisper.resolveNext("two");
    await flush();
    expect(texts).toEqual(["remote1:one", "remote3:three", "remote2:two"]);
    await q.idle();

    // a push-mode provider behaves as null
    const push = new TranscriptionQueue({ provider: () => new FakePushProvider(), onText: () => undefined, onError: () => undefined });
    expect(push.enqueue(seg("me", 1))).toBe(false);
  });

  it("41. lane stop does not drain the queue: three waiting, both lanes stopped → all three transcribed and posted; provider.stop() only at dispose()", async () => {
    const whisper = new FakeSegmentProvider();
    const sink = new ScriptedSink();
    const storage = memoryStorage({ [MODEL_SEEN_KEY("onnx-community/whisper-base.en")]: "1" });
    const graph = new FakeGraph();
    const media = new FakeMedia();
    media.nextDisplay(new FakeStream([new FakeTrack("video"), new FakeTrack("audio", "Tab")]));
    media.nextUser(new FakeStream([new FakeTrack("audio", "Mic")]));
    const c = new AudioController({ sink, clock: fixedClock(1000), speakers: new SpeakerStore({ userName: "Sam" }), media, graph, storage, isSecureContext: true, os: "linux", providers: () => whisper });
    await c.startLane("remote");
    await c.startLane("me");
    await flush();
    expect(c.getState().lanes.remote.state).toBe("live");
    expect(c.getState().lanes.me.state).toBe("live");
    expect(c.getState().model.state).toBe("ready");
    expect(whisper.startCalls).toBe(1);
    const utterance = [...framesAtDb(50, -20), ...silence(40)];
    graph.feed("remote", utterance);
    graph.feed("me", utterance);
    graph.feed("remote", utterance);
    await flush();
    expect(c.getState().lanes.remote.segmentsClosed).toBe(2);
    expect(c.getState().lanes.me.segmentsClosed).toBe(1);
    expect(c.getState().backlog.segmentsWaiting + c.getState().backlog.segmentInFlight).toBe(3);
    await c.stopLane("remote");
    await c.stopLane("me");
    expect(c.getState().lanes.remote.state).toBe("stopped");
    expect(c.getState().lanes.me.state).toBe("stopped");
    expect(whisper.stopCalls).toHaveLength(0);
    expect(c.pendingWork()).toBe(3);
    whisper.resolveNext("first call sentence");
    await flush();
    whisper.resolveNext("my own sentence");
    await flush();
    whisper.resolveNext("second call sentence");
    await flush();
    await c.idle();
    expect(sink.posted.map((u) => [u.lane, u.text, u.speaker, u.provider, u.model, u.is_local])).toEqual([
      ["remote", "first call sentence", null, "local-whisper", "onnx-community/whisper-base.en", true],
      ["me", "my own sentence", "Sam", "local-whisper", "onnx-community/whisper-base.en", true],
      ["remote", "second call sentence", null, "local-whisper", "onnx-community/whisper-base.en", true],
    ]);
    expect(sink.posted[0]!.t_start_ms).toBe(1000); // startedAt of the first segment (pre-roll is empty at a mid-speech start)
    expect(sink.posted[0]!.t_end_ms).toBe(1000 + 50 * 20 + 200);
    expect(c.pendingWork()).toBe(0);
    expect(whisper.stopCalls).toHaveLength(0);
    c.dispose();
    expect(whisper.stopCalls).toEqual([{ force: true }]);
  });

  it("42. PostQueue: order, three in flight never four, backoff until ok, duplicate-after-timeout is success, lastError on the third transient failure, refused never retried", async () => {
    const sink = new ScriptedSink();
    const timers = fakeTimers();
    const lastErrors: string[] = [];
    const refused: string[] = [];
    const posted: string[] = [];
    const q = new PostQueue({ sink, timers, events: { onLastError: (u) => lastErrors.push(u.id), onRefused: (u, o) => refused.push(`${u.id}:${o.reason}`), onPosted: (u, o) => posted.push(`${u.id}:${o.eventId}:${o.duplicate}`) } });
    const u = (id: string): UtteranceWire => ({ id: `utt_${id}`, text: id, lane: "me", speaker: null, provider: "manual", model: null, t_start_ms: 0, t_end_ms: 0, is_local: true, confidence: null });
    sink.hold = true;
    for (const id of ["a", "b", "c", "d", "e"]) q.enqueue(u(id));
    await flush();
    expect(sink.inFlight).toBe(3);
    expect(sink.maxInFlight).toBe(3);
    expect(q.unsent).toBe(5);
    sink.release(5);
    sink.hold = false;
    await flush();
    expect(sink.maxInFlight).toBe(3);
    expect(sink.posted.map((x) => x.text)).toEqual(["a", "b", "c", "d", "e"]);
    await q.idle();

    // transient retried with the backoff sequence until ok
    const t: PostOutcome = { ok: false, kind: "transient", status: 503, message: "down" };
    sink.script("utt_f", t, t, t, t, t, { ok: true, eventId: "evt_f", duplicate: false });
    q.enqueue(u("f"));
    await flush();
    expect(q.unsent).toBe(1);
    for (let i = 0; i < 5; i++) {
      const delay = POST_BACKOFF_MS[Math.min(i + 1, POST_BACKOFF_MS.length) - 1]!;
      timers.advance(delay - 1);
      await flush();
      expect(sink.posted.filter((x) => x.id === "utt_f")).toHaveLength(i + 1);
      timers.advance(1);
      await flush();
    }
    expect(sink.posted.filter((x) => x.id === "utt_f")).toHaveLength(6);
    expect(posted).toContain("utt_f:evt_f:false");
    expect(lastErrors).toEqual(["utt_f"]); // on the third consecutive transient failure
    expect(q.unsent).toBe(0);
    expect(q.retries).toBe(5);

    // a timeout followed by DUPLICATE_ID is a success with eventId and no lastError
    sink.script("utt_g", { ok: false, kind: "transient", status: null, message: "timeout" }, { ok: true, eventId: "evt_g", duplicate: true });
    q.enqueue(u("g"));
    await flush();
    timers.advance(500);
    await flush();
    expect(posted).toContain("utt_g:evt_g:true");
    expect(lastErrors).toEqual(["utt_f"]);

    // refused: not retried, lands in refused[] with the server's reason
    sink.script("utt_h", { ok: false, kind: "refused", status: 422, reason: "EMPTY_TEXT", detail: "text is empty" });
    q.enqueue(u("h"));
    await flush();
    timers.advance(60_000);
    await flush();
    expect(sink.posted.filter((x) => x.id === "utt_h")).toHaveLength(1);
    expect(q.refused).toEqual([{ id: "utt_h", text: "h", status: 422, reason: "EMPTY_TEXT", detail: "text is empty" }]);
    expect(refused).toEqual(["utt_h:EMPTY_TEXT"]);
    expect(q.unsent).toBe(0);
  });

  it("43. HttpUtteranceSink with a fake fetch classifies by the body's reason, never by status alone", async () => {
    const calls: Array<{ url: string; init: Parameters<FetchLike>[1] }> = [];
    let next: { status: number; body: string } = { status: 201, body: "{}" };
    let throwNext: Error | null = null;
    const fetchFake: FetchLike = async (url, init) => {
      calls.push({ url, init });
      if (throwNext) {
        const e = throwNext;
        throwNext = null;
        throw e;
      }
      const r = next;
      return { status: r.status, ok: r.status >= 200 && r.status < 300, text: async () => r.body };
    };
    const sink = new HttpUtteranceSink({ baseUrl: "http://127.0.0.1:4317/", sessionId: "sess_1", fetch: fetchFake });
    expect(sink.timeoutMs).toBe(15000);
    expect(sink.url).toBe("http://127.0.0.1:4317/api/sessions/sess_1/utterances");
    const u: UtteranceWire = { id: "utt_1", text: "hi", lane: "me", speaker: null, provider: "manual", model: null, t_start_ms: 0, t_end_ms: 10, is_local: true, confidence: null };

    next = { status: 201, body: JSON.stringify({ ok: true, event: { id: "evt_9", seq: 9, hash: "h" } }) };
    expect(await sink.post(u)).toEqual({ ok: true, eventId: "evt_9", duplicate: false });
    expect(calls[0]!.init.method).toBe("POST");
    expect(JSON.parse(calls[0]!.init.body)).toEqual(u);
    expect(calls[0]!.init.signal).toBeInstanceOf(AbortSignal);

    next = { status: 409, body: JSON.stringify({ ok: false, reason: "DUPLICATE_ID", detail: "seen", event: { id: "evt_3", seq: 3, hash: "h" } }) };
    expect(await sink.post(u)).toEqual({ ok: true, eventId: "evt_3", duplicate: true });

    const refusedCases: Array<[number, string]> = [
      [409, "LEDGER_BROKEN"],
      [404, "SESSION_NOT_FOUND"],
      [400, "BAD_REQUEST"],
      [403, "FORBIDDEN_ORIGIN"],
      [422, "EMPTY_TEXT"],
    ];
    for (const [status, reason] of refusedCases) {
      next = { status, body: JSON.stringify({ ok: false, reason, detail: `d-${reason}` }) };
      expect(await sink.post(u)).toEqual({ ok: false, kind: "refused", status, reason, detail: `d-${reason}` });
    }
    next = { status: 403, body: "" };
    expect(await sink.post(u)).toMatchObject({ ok: false, kind: "refused", status: 403, reason: "HTTP_403" });

    for (const status of [408, 429, 503]) {
      next = { status, body: JSON.stringify({ ok: false, reason: "X", detail: "y" }) };
      expect(await sink.post(u)).toMatchObject({ ok: false, kind: "transient", status });
    }
    throwNext = new TypeError("Failed to fetch");
    expect(await sink.post(u)).toEqual({ ok: false, kind: "transient", status: null, message: "Failed to fetch" });
    const abort = new Error("The operation was aborted");
    abort.name = "AbortError";
    throwNext = abort;
    expect(await sink.post(u)).toEqual({ ok: false, kind: "transient", status: null, message: "timeout" });
    next = { status: 200, body: "<html>not json</html>" };
    expect(await sink.post(u)).toMatchObject({ ok: false, kind: "transient", status: 200 });
    expect(classifyResponse(201, null)).toMatchObject({ ok: false, kind: "transient" });
  });

  it("44. buildUtterance: id, integers, clamps, confidence rounding, EMPTY_TEXT; the output satisfies core's utterance.record", () => {
    const draft: UtteranceDraft = { text: "  Hello there.  ", lane: "remote", speaker: "Priya", provider: "local-whisper", model: "onnx-community/whisper-base.en", isLocal: true, confidence: null, tStartMs: 1234.6, tEndMs: 1200.2 };
    const u = buildUtterance(draft);
    expect(u.id).toMatch(/^utt_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    expect(u.text).toBe("Hello there.");
    expect(Number.isInteger(u.t_start_ms)).toBe(true);
    expect(u.t_start_ms).toBe(1235);
    expect(u.t_end_ms).toBe(1235); // t_end_ms ≥ t_start_ms
    const neg = buildUtterance({ ...draft, tStartMs: -50, tEndMs: -10 });
    expect(neg.t_start_ms).toBe(0);
    expect(neg.t_end_ms).toBe(0);
    expect(buildUtterance({ ...draft, confidence: 0.98765 }).confidence).toBe(0.99);
    expect(buildUtterance({ ...draft, confidence: 1.7 }).confidence).toBe(1);
    expect(buildUtterance({ ...draft, confidence: -1 }).confidence).toBe(0);
    expect(buildUtterance({ ...draft, speaker: "  " }).speaker).toBeNull();
    expect(() => buildUtterance({ ...draft, text: "   " })).toThrow(PostError);
    expect(() => buildUtterance({ ...draft, text: "" })).toThrowError(/EMPTY_TEXT/);

    const { ctx } = testCtx();
    const wire = buildUtterance({ ...draft, provider: "web-speech", isLocal: false, confidence: 0.87, tStartMs: 10, tEndMs: 2500 }, () => "utt_fixed1");
    const res = apply(initialState("sess_test"), { kind: "utterance.record", utterance: wire }, ctx);
    expect(res.ok).toBe(true);
    if (res.ok) {
      const ev = res.events[0]!;
      expect(ev.type).toBe("utterance.recorded");
      const recorded = res.state.utterances.find((x) => x.id === "utt_fixed1")!;
      expect(recorded.is_local).toBe(false);
      expect(recorded.confidence).toBe(0.87);
      expect(recorded.t_end_ms - recorded.t_start_ms).toBe(2490);
    }
  });
});
