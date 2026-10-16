// tests/unit/audio/localWhisper.test.ts — TEST-PLAN §3 case 52: the main-thread provider against a fake Worker (the
// contract test; the real model is exercised only by scripts/whisper-check.mjs).
import { describe, expect, it } from "vitest";
import { fixedClock } from "../../../src/web/audio/clock.js";
import { LocalWhisperProvider, ORT_WASM_PATHS, whisperThreads } from "../../../src/web/audio/providers/localWhisper.js";
import { SpeakerStore } from "../../../src/web/audio/speakers.js";
import type { ModelProgress, ProviderContext, Segment } from "../../../src/web/audio/types.js";
import { FakeWorker, fakeTimers, flush } from "./fakes.js";

function setup(opts: { loadTimeoutMs?: number } = {}) {
  const timers = fakeTimers();
  const workers: FakeWorker[] = [];
  const progress: ModelProgress[] = [];
  const p = new LocalWhisperProvider({
    model: "onnx-community/whisper-tiny.en",
    dtype: "q8",
    device: "auto",
    createWorker: () => {
      const w = new FakeWorker();
      workers.push(w);
      return w;
    },
    timers,
    numThreads: 3,
    ...(opts.loadTimeoutMs !== undefined ? { loadTimeoutMs: opts.loadTimeoutMs } : {}),
  });
  const ctx: ProviderContext = { emit: () => undefined, onProgress: (x) => progress.push(x), clock: fixedClock(), speakers: new SpeakerStore(), signal: new AbortController().signal };
  return { p, timers, workers, progress, ctx };
}

const segment = (ms = 2000): Segment => ({ lane: "me", seq: 1, startedAt: 0, onsetAt: 0, endedAt: ms, speechMs: ms, pcm: new Float32Array(ms * 16), sampleRate: 16000, peakRmsDb: -20, cappedAt15s: false, speaker: null });

describe("LocalWhisperProvider", () => {
  it("52. start() resolves on ready with device/threads; transcribe() resolves on its result; errors, timeouts and stop()", async () => {
    const { p, timers, workers, progress, ctx } = setup();
    expect(p.mode).toBe("segment");
    expect(p.isLocal).toBe(true);
    expect(p.model).toBe("onnx-community/whisper-tiny.en");
    const starting = p.start(ctx);
    const w = workers[0]!;
    expect(w.posted[0]).toEqual({ type: "load", model: "onnx-community/whisper-tiny.en", dtype: "q8", device: "auto", wasmPaths: ORT_WASM_PATHS, numThreads: 3 });
    expect(w.posted[0]).toMatchObject({ wasmPaths: { mjs: "/ort/ort-wasm-simd-threaded.asyncify.mjs", wasm: "/ort/ort-wasm-simd-threaded.asyncify.wasm" } });
    // exactly transformers.js' progress shapes, forwarded by the worker
    w.emit({ type: "progress", data: { status: "initiate", name: "onnx-community/whisper-tiny.en", file: "config.json" } });
    w.emit({ type: "progress", data: { status: "progress", name: "onnx-community/whisper-tiny.en", file: "onnx/encoder_model_quantized.onnx", progress: 23.18, loaded: 65536, total: 282662 } });
    w.emit({ type: "progress", data: { status: "progress_total", name: "onnx-community/whisper-tiny.en", progress: 37, loaded: 16_000_000, total: 43_536_374 } });
    expect(progress.at(-1)).toEqual({ phase: "downloading", percent: 37, loadedBytes: 16_000_000, totalBytes: 43_536_374, file: "onnx/encoder_model_quantized.onnx", cached: false });
    w.emit({ type: "progress", data: { status: "progress_total", name: "onnx-community/whisper-tiny.en", progress: 100, loaded: 43_536_374, total: 43_536_374 } });
    expect(progress.at(-1)!.phase).toBe("loading_runtime");
    expect(p.isReady).toBe(false);
    w.emit({ type: "ready", model: "onnx-community/whisper-tiny.en", device: "wasm", threads: 3, loadMs: 1850 });
    await starting;
    expect(p.isReady).toBe(true);
    expect(p.readyInfo).toEqual({ device: "wasm", threads: 3, loadMs: 1850 });
    expect(progress.at(-1)).toMatchObject({ phase: "ready", percent: 100, cached: false });

    // transcribe → result by jobId
    const job1 = p.transcribe(segment(2000));
    const job2 = p.transcribe(segment(1000));
    expect(w.posted[1]).toMatchObject({ type: "transcribe", jobId: 1 });
    expect(w.posted[2]).toMatchObject({ type: "transcribe", jobId: 2 });
    expect((w.posted[1] as { pcm: Float32Array }).pcm.length).toBe(32000);
    w.emit({ type: "result", jobId: 2, text: " second ", ms: 300 });
    await expect(job2).resolves.toEqual({ text: " second " });
    w.emit({ type: "result", jobId: 1, text: "first", ms: 900 });
    await expect(job1).resolves.toEqual({ text: "first" });

    // TRANSCRIBE_FAILED with its jobId, and with null (the oldest in-flight job)
    const job3 = p.transcribe(segment());
    w.emit({ type: "error", jobId: 3, stage: "transcribe", name: "RuntimeError", message: "bad tensor" });
    await expect(job3).rejects.toMatchObject({ code: "TRANSCRIBE_FAILED", detail: "RuntimeError: bad tensor" });
    const job4 = p.transcribe(segment());
    w.emit({ type: "error", jobId: null, stage: "transcribe", name: "Error", message: "no id" });
    await expect(job4).rejects.toMatchObject({ code: "TRANSCRIBE_FAILED" });

    // TRANSCRIBE_TIMEOUT after max(30 s, 10 × segment length)
    const job5 = p.transcribe(segment(5000)); // 50 s deadline
    timers.advance(49_999);
    await flush();
    let settled = false;
    void job5.catch(() => (settled = true));
    await flush();
    expect(settled).toBe(false);
    timers.advance(1);
    await expect(job5).rejects.toMatchObject({ code: "TRANSCRIBE_TIMEOUT" });
    const job6 = p.transcribe(segment(100)); // 30 s floor
    timers.advance(30_000);
    await expect(job6).rejects.toMatchObject({ code: "TRANSCRIBE_TIMEOUT" });

    // stop() waits for the in-flight job
    const job7 = p.transcribe(segment());
    let stopped = false;
    const stopping = p.stop().then(() => (stopped = true));
    await flush();
    expect(stopped).toBe(false);
    expect(w.terminated).toBe(0);
    w.emit({ type: "result", jobId: 7, text: "late", ms: 1 });
    await expect(job7).resolves.toEqual({ text: "late" });
    await stopping;
    expect(stopped).toBe(true);
    expect(w.posted.at(-1)).toEqual({ type: "dispose" });
    expect(w.terminated).toBe(1);
    expect(p.isReady).toBe(false);

    // stop({ force: true }) terminates at once, failing the in-flight job
    const again = setup();
    const s2 = again.p.start(again.ctx);
    again.workers[0]!.emit({ type: "ready", model: "m", device: "webgpu", threads: 1, loadMs: 1 });
    await s2;
    expect(again.p.readyInfo?.device).toBe("webgpu");
    const job8 = again.p.transcribe(segment());
    await again.p.stop({ force: true });
    expect(again.workers[0]!.terminated).toBe(1);
    await expect(job8).rejects.toMatchObject({ code: "WORKER_CRASHED" });
  });

  it("52b. start() rejects MODEL_LOAD_FAILED on a load error, on an unhandled error while loading, and after loadTimeoutMs", async () => {
    const a = setup();
    const s = a.p.start(a.ctx);
    a.workers[0]!.emit({ type: "error", jobId: null, stage: "load", name: "Error", message: "no available backend found" });
    await expect(s).rejects.toMatchObject({ code: "MODEL_LOAD_FAILED", detail: "load: Error: no available backend found" });
    expect(a.workers[0]!.terminated).toBe(1);
    expect(a.progress.at(-1)!.phase).toBe("error");

    const b = setup();
    const s2 = b.p.start(b.ctx);
    b.workers[0]!.emit({ type: "error", jobId: null, stage: "unhandled", name: "TypeError", message: "x is not a function" });
    await expect(s2).rejects.toMatchObject({ code: "MODEL_LOAD_FAILED" });

    const c = setup({ loadTimeoutMs: 1000 });
    const s3 = c.p.start(c.ctx);
    c.timers.advance(1000);
    await expect(s3).rejects.toMatchObject({ code: "MODEL_LOAD_FAILED" });
    expect(c.workers[0]!.terminated).toBe(1);

    // a worker.onerror while loading also fails the load
    const d = setup();
    const s4 = d.p.start(d.ctx);
    d.workers[0]!.onerror?.({ message: "script error" });
    await expect(s4).rejects.toMatchObject({ code: "MODEL_LOAD_FAILED" });

    // transcribe() before ready rejects TRANSCRIBE_FAILED
    await expect(setup().p.transcribe(segment())).rejects.toMatchObject({ code: "TRANSCRIBE_FAILED" });
  });

  it("whisperThreads = crossOriginIsolated ? min(4, cores − 1) : null", () => {
    expect(whisperThreads(false, 8)).toBeNull();
    expect(whisperThreads(true, 8)).toBe(4);
    expect(whisperThreads(true, 4)).toBe(3);
    expect(whisperThreads(true, 1)).toBe(1);
  });
});
