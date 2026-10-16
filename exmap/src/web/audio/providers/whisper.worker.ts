// exmap/src/web/audio/providers/whisper.worker.ts — the Whisper Web Worker (design §7.4; shapes verified by the spike).
// One model in memory, one job at a time. env is per realm, so the ORT wasm paths and thread count are set HERE.
// Every failure path posts an `error` message: an exception out of an async onmessage never reaches the main
// thread's onerror.
import { env, pipeline } from "@huggingface/transformers";
import type { TransformersProgressEvent, WhisperIn, WhisperOut } from "../types.js";

type AsrPipeline = (audio: Float32Array) => Promise<{ text: string } | Array<{ text: string }>>;

const scope = self as unknown as {
  postMessage(msg: WhisperOut): void;
  onmessage: ((ev: MessageEvent<WhisperIn>) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onunhandledrejection: ((ev: unknown) => void) | null;
  close(): void;
  crossOriginIsolated?: boolean;
  navigator?: { gpu?: { requestAdapter(): Promise<unknown> } };
};

function post(msg: WhisperOut): void {
  scope.postMessage(msg);
}

function nameOf(e: unknown): string {
  return typeof e === "object" && e !== null && typeof (e as { name?: unknown }).name === "string" ? (e as { name: string }).name : "Error";
}
function messageOf(e: unknown): string {
  return typeof e === "object" && e !== null && "message" in e ? String((e as { message: unknown }).message) : String(e);
}

let asr: AsrPipeline | null = null;
let loading: Promise<void> | null = null;
let busy = false;

async function probeWebGpu(): Promise<boolean> {
  try {
    const gpu = scope.navigator?.gpu;
    if (!gpu) return false;
    const adapter = await gpu.requestAdapter();
    return adapter !== null && adapter !== undefined;
  } catch {
    return false;
  }
}

async function load(msg: Extract<WhisperIn, { type: "load" }>): Promise<void> {
  const t0 = performance.now();
  // env is per realm: configure inside the worker.
  const onnx = env.backends.onnx as { wasm?: { wasmPaths?: unknown; numThreads?: number } };
  onnx.wasm ??= {};
  onnx.wasm.wasmPaths = { mjs: msg.wasmPaths.mjs, wasm: msg.wasmPaths.wasm };
  let threads = 1;
  if (msg.numThreads && msg.numThreads > 1 && scope.crossOriginIsolated) {
    onnx.wasm.numThreads = msg.numThreads;
    threads = msg.numThreads;
  }
  const progress_callback = (p: unknown) => post({ type: "progress", data: p as TransformersProgressEvent });

  const tryDevice = async (device: "webgpu" | "wasm"): Promise<AsrPipeline> => {
    const p = await pipeline("automatic-speech-recognition", msg.model, { device, dtype: msg.dtype, progress_callback });
    return p as unknown as AsrPipeline;
  };

  let device: "webgpu" | "wasm" = "wasm";
  if (msg.device === "auto" && (await probeWebGpu())) {
    try {
      asr = await tryDevice("webgpu");
      device = "webgpu";
    } catch (e) {
      // the files are cached by now; retry on wasm (the spike saw this exact failure after a full download)
      post({ type: "progress", data: { status: "initiate", name: msg.model, file: `webgpu failed (${messageOf(e)}); retrying on wasm` } });
      asr = await tryDevice("wasm");
      device = "wasm";
    }
  } else {
    asr = await tryDevice("wasm");
  }
  const loadMs = Math.round(performance.now() - t0);
  post({ type: "ready", model: msg.model, device, threads: device === "wasm" ? threads : 1, loadMs });
}

async function transcribe(msg: Extract<WhisperIn, { type: "transcribe" }>): Promise<void> {
  if (!asr) {
    post({ type: "error", jobId: msg.jobId, stage: "transcribe", name: "NotLoaded", message: "the model is not loaded" });
    return;
  }
  if (busy) {
    post({ type: "error", jobId: msg.jobId, stage: "transcribe", name: "Busy", message: "a transcription is already running" });
    return;
  }
  busy = true;
  const t0 = performance.now();
  try {
    const out = await asr(msg.pcm);
    const text = Array.isArray(out) ? out.map((o) => o.text).join(" ") : out.text;
    post({ type: "result", jobId: msg.jobId, text: typeof text === "string" ? text : "", ms: Math.round(performance.now() - t0) });
  } catch (e) {
    post({ type: "error", jobId: msg.jobId, stage: "transcribe", name: nameOf(e), message: messageOf(e) });
  } finally {
    busy = false;
  }
}

scope.onmessage = (ev: MessageEvent<WhisperIn>) => {
  const msg = ev.data;
  if (!msg || typeof msg !== "object") return;
  switch (msg.type) {
    case "load":
      if (loading) return;
      loading = load(msg).catch((e: unknown) => {
        loading = null;
        asr = null;
        post({ type: "error", jobId: null, stage: "load", name: nameOf(e), message: messageOf(e) });
      });
      return;
    case "transcribe":
      void transcribe(msg);
      return;
    case "dispose":
      asr = null;
      loading = null;
      scope.close();
      return;
  }
};

scope.onerror = (ev: unknown) => {
  post({ type: "error", jobId: null, stage: "unhandled", name: nameOf(ev), message: messageOf(ev) });
};
scope.onunhandledrejection = (ev: unknown) => {
  const reason = typeof ev === "object" && ev !== null && "reason" in ev ? (ev as { reason: unknown }).reason : ev;
  post({ type: "error", jobId: null, stage: "unhandled", name: nameOf(reason), message: messageOf(reason) });
};
