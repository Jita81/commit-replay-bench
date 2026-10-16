// exmap/src/web/audio/providers/localWhisper.ts — the main-thread side of the Whisper worker (design §7.4). A segment
// provider: start() loads the model (after consent), transcribe(segment) posts one job and resolves on its result.
import { ProviderError } from "../errors.js";
import { MODEL_INFO } from "../settings.js";
import type { CaptureLaneId, ModelProgress, ProviderContext, Segment, TranscribeResult, TranscriptionProvider, TransformersProgressEvent, WhisperDevice, WhisperDtype, WhisperIn, WhisperModelId, WhisperOut, WhisperWasmPaths } from "../types.js";

/** The subset of Worker the provider uses; tests pass a fake. */
export interface WorkerLike {
  postMessage(msg: WhisperIn): void;
  terminate(): void;
  onmessage: ((ev: { data: WhisperOut }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export const ORT_WASM_PATHS: WhisperWasmPaths = {
  mjs: "/ort/ort-wasm-simd-threaded.asyncify.mjs",
  wasm: "/ort/ort-wasm-simd-threaded.asyncify.wasm",
};

export const DEFAULT_LOAD_TIMEOUT_MS = 10 * 60 * 1000;

export function defaultCreateWorker(): WorkerLike {
  return new Worker(new URL("./whisper.worker.ts", import.meta.url), { type: "module" }) as unknown as WorkerLike;
}

/** numThreads = crossOriginIsolated ? min(4, hardwareConcurrency − 1) : null. */
export function whisperThreads(isolated: boolean = typeof crossOriginIsolated === "boolean" ? crossOriginIsolated : false, cores: number = typeof navigator === "undefined" ? 1 : (navigator.hardwareConcurrency ?? 1)): number | null {
  if (!isolated) return null;
  return Math.max(1, Math.min(4, cores - 1));
}

export interface LocalWhisperDeps {
  model: WhisperModelId;
  dtype: WhisperDtype;
  device: WhisperDevice;
  createWorker?: () => WorkerLike;
  wasmPaths?: WhisperWasmPaths;
  numThreads?: number | null;
  loadTimeoutMs?: number;
  timers?: { setTimeout(fn: () => void, ms: number): unknown; clearTimeout(h: unknown): void };
  onReady?: (info: { device: "webgpu" | "wasm"; threads: number; loadMs: number }) => void;
}

interface Job {
  jobId: number;
  resolve: (r: TranscribeResult) => void;
  reject: (e: ProviderError) => void;
  timer: unknown;
  settled: boolean;
  done: Promise<void>;
  finish: () => void;
}

export class LocalWhisperProvider implements TranscriptionProvider {
  readonly id = "local-whisper" as const;
  readonly isLocal = true;
  readonly lanes: CaptureLaneId[] = ["remote", "me"];
  readonly mode = "segment" as const;
  readonly model: WhisperModelId;

  readonly #deps: LocalWhisperDeps;
  #worker: WorkerLike | null = null;
  #ready = false;
  #jobs = new Map<number, Job>();
  #nextJob = 1;
  #ctx: ProviderContext | null = null;
  #loadPromise: Promise<void> | null = null;
  #progressBytes = { loaded: 0, total: 0 };
  #progressFile: string | null = null;
  #sawDownloadProgress = false;
  readyInfo: { device: "webgpu" | "wasm"; threads: number; loadMs: number } | null = null;

  constructor(deps: LocalWhisperDeps) {
    this.#deps = deps;
    this.model = deps.model;
  }

  get label(): string {
    return `Whisper (local) · ${MODEL_INFO[this.model]?.short ?? this.model}`;
  }

  get isReady(): boolean {
    return this.#ready;
  }

  get inFlight(): number {
    return this.#jobs.size;
  }

  #timers() {
    return this.#deps.timers ?? { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>) };
  }

  /** Creates the worker, posts `load`, resolves on `ready`; rejects MODEL_LOAD_FAILED on a load/unhandled error or after loadTimeoutMs. */
  start(ctx: ProviderContext): Promise<void> {
    if (this.#ready) return Promise.resolve();
    if (this.#loadPromise) return this.#loadPromise;
    this.#ctx = ctx;
    const create = this.#deps.createWorker ?? defaultCreateWorker;
    let worker: WorkerLike;
    try {
      worker = create();
    } catch (e) {
      return Promise.reject(new ProviderError("MODEL_LOAD_FAILED", `worker could not be created: ${messageOf(e)}`));
    }
    this.#worker = worker;
    this.#progressBytes = { loaded: 0, total: 0 };
    this.#progressFile = null;
    this.#sawDownloadProgress = false;
    const timers = this.#timers();
    this.#loadPromise = new Promise<void>((resolve, reject) => {
      let settled = false;
      const timeout = timers.setTimeout(() => {
        if (settled) return;
        settled = true;
        this.#loadPromise = null;
        this.#killWorker();
        this.#emitProgress({ phase: "error", percent: 0, loadedBytes: this.#progressBytes.loaded, totalBytes: this.#progressBytes.total, file: null, cached: false });
        reject(new ProviderError("MODEL_LOAD_FAILED", `the model did not load within ${this.#deps.loadTimeoutMs ?? DEFAULT_LOAD_TIMEOUT_MS} ms`));
      }, this.#deps.loadTimeoutMs ?? DEFAULT_LOAD_TIMEOUT_MS);
      const fail = (detail: string) => {
        if (settled) return;
        settled = true;
        timers.clearTimeout(timeout);
        this.#loadPromise = null;
        this.#killWorker();
        this.#emitProgress({ phase: "error", percent: 0, loadedBytes: this.#progressBytes.loaded, totalBytes: this.#progressBytes.total, file: null, cached: false });
        reject(new ProviderError("MODEL_LOAD_FAILED", detail));
      };
      worker.onerror = (ev) => {
        if (!settled) fail(`worker error: ${messageOf(ev)}`);
        else this.#failAllJobs("WORKER_CRASHED", messageOf(ev));
      };
      worker.onmessage = (ev) => {
        const msg = ev.data;
        if (!msg || typeof msg !== "object") return;
        switch (msg.type) {
          case "progress":
            this.#onProgress(msg.data);
            return;
          case "ready":
            if (settled) return;
            settled = true;
            timers.clearTimeout(timeout);
            this.#ready = true;
            this.readyInfo = { device: msg.device, threads: msg.threads, loadMs: msg.loadMs };
            this.#emitProgress({ phase: "ready", percent: 100, loadedBytes: this.#progressBytes.loaded, totalBytes: this.#progressBytes.total, file: null, cached: !this.#sawDownloadProgress });
            this.#deps.onReady?.(this.readyInfo);
            resolve();
            return;
          case "result":
            this.#onResult(msg.jobId, msg.text);
            return;
          case "error":
            if (!settled && (msg.stage === "load" || msg.stage === "unhandled")) {
              fail(`${msg.stage}: ${msg.name}: ${msg.message}`);
              return;
            }
            if (msg.stage === "unhandled") {
              this.#failAllJobs("WORKER_CRASHED", `${msg.name}: ${msg.message}`);
              return;
            }
            this.#onJobError(msg.jobId, `${msg.name}: ${msg.message}`);
            return;
        }
      };
      worker.postMessage({
        type: "load",
        model: this.#deps.model,
        dtype: this.#deps.dtype,
        device: this.#deps.device,
        wasmPaths: this.#deps.wasmPaths ?? ORT_WASM_PATHS,
        numThreads: this.#deps.numThreads === undefined ? whisperThreads() : this.#deps.numThreads,
      });
    });
    return this.#loadPromise;
  }

  #onProgress(p: TransformersProgressEvent): void {
    if (p.status === "progress_total") {
      this.#progressBytes = { loaded: p.loaded, total: p.total };
      if (p.progress > 0 && p.progress < 100) this.#sawDownloadProgress = true;
      const phase: ModelProgress["phase"] = p.progress >= 100 ? "loading_runtime" : "downloading";
      this.#emitProgress({ phase, percent: Math.max(0, Math.min(100, p.progress)), loadedBytes: p.loaded, totalBytes: p.total, file: this.#progressFile, cached: false });
    } else if (p.status === "progress") {
      this.#progressFile = p.file;
      if (p.progress > 0 && p.progress < 100) this.#sawDownloadProgress = true;
    } else if (p.status === "initiate" || p.status === "download") {
      this.#progressFile = p.file;
    }
  }

  #emitProgress(p: ModelProgress): void {
    this.#ctx?.onProgress?.(p);
  }

  /** Posts one job; resolves on its result; TRANSCRIBE_FAILED on an error with its jobId (or null); TRANSCRIBE_TIMEOUT after max(30 s, 10 × segment length). */
  transcribe(segment: Segment, opts: { signal?: AbortSignal } = {}): Promise<TranscribeResult> {
    const worker = this.#worker;
    if (!worker || !this.#ready) return Promise.reject(new ProviderError("TRANSCRIBE_FAILED", "the model is not loaded"));
    if (opts.signal?.aborted) return Promise.reject(new ProviderError("TRANSCRIBE_FAILED", "aborted"));
    const jobId = this.#nextJob++;
    const segMs = Math.max(0, segment.endedAt - segment.startedAt);
    const deadline = Math.max(30_000, 10 * segMs);
    const timers = this.#timers();
    return new Promise<TranscribeResult>((resolve, reject) => {
      let finish: () => void = () => undefined;
      const done = new Promise<void>((res) => {
        finish = res;
      });
      const job: Job = { jobId, resolve, reject, timer: null, settled: false, done, finish };
      job.timer = timers.setTimeout(() => this.#settleReject(job, new ProviderError("TRANSCRIBE_TIMEOUT", `job ${jobId} exceeded ${deadline} ms`)), deadline);
      opts.signal?.addEventListener("abort", () => this.#settleReject(job, new ProviderError("TRANSCRIBE_FAILED", "aborted")), { once: true });
      this.#jobs.set(jobId, job);
      try {
        worker.postMessage({ type: "transcribe", jobId, pcm: segment.pcm });
      } catch (e) {
        this.#settleReject(job, new ProviderError("TRANSCRIBE_FAILED", `postMessage failed: ${messageOf(e)}`));
      }
    });
  }

  #onResult(jobId: number, text: string): void {
    const job = this.#jobs.get(jobId);
    if (!job || job.settled) return;
    job.settled = true;
    this.#timers().clearTimeout(job.timer);
    this.#jobs.delete(jobId);
    job.resolve({ text });
    job.finish();
  }

  #onJobError(jobId: number | null, detail: string): void {
    if (jobId === null) {
      // an error without a job id: the oldest in-flight job is the one it must belong to
      const first = [...this.#jobs.values()][0];
      if (first) this.#settleReject(first, new ProviderError("TRANSCRIBE_FAILED", detail));
      return;
    }
    const job = this.#jobs.get(jobId);
    if (job) this.#settleReject(job, new ProviderError("TRANSCRIBE_FAILED", detail));
  }

  #failAllJobs(code: "WORKER_CRASHED" | "TRANSCRIBE_FAILED", detail: string): void {
    for (const job of [...this.#jobs.values()]) this.#settleReject(job, new ProviderError(code, detail));
  }

  #settleReject(job: Job, e: ProviderError): void {
    if (job.settled) return;
    job.settled = true;
    this.#timers().clearTimeout(job.timer);
    this.#jobs.delete(job.jobId);
    job.reject(e);
    job.finish();
  }

  /** Waits for the in-flight job then disposes; { force: true } terminates at once. */
  async stop(opts: { force?: boolean } = {}): Promise<void> {
    if (!opts.force && this.#jobs.size > 0) await Promise.all([...this.#jobs.values()].map((j) => j.done));
    this.#failAllJobs("WORKER_CRASHED", "provider stopped");
    this.#killWorker(!opts.force);
    this.#ready = false;
    this.#loadPromise = null;
    this.readyInfo = null;
  }

  #killWorker(polite = false): void {
    const w = this.#worker;
    this.#worker = null;
    if (!w) return;
    try {
      if (polite) w.postMessage({ type: "dispose" });
    } catch {
      /* ignore */
    }
    try {
      w.terminate();
    } catch {
      /* ignore */
    }
  }
}

function messageOf(e: unknown): string {
  if (typeof e === "object" && e !== null && "message" in e) return String((e as { message: unknown }).message);
  return String(e);
}
