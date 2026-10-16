// tests/unit/audio/fakes.ts — fake browser surfaces for the lane, graph, controller and React tests: MediaDevices,
// MediaStream/Track, AudioGraph, Worker, SpeechRecognition, timers and a scripted sink.
import type { AudioGraph, FrameHandler } from "../../../src/web/audio/dsp/graph.js";
import type { ProviderError } from "../../../src/web/audio/errors.js";
import type { WorkerLike } from "../../../src/web/audio/providers/localWhisper.js";
import type { SpeechRecognitionErrorEventLike, SpeechRecognitionEventLike, SpeechRecognitionLike } from "../../../src/web/audio/providers/webSpeech.js";
import type { CaptureLaneId, MediaDevicesLike, PostOutcome, ProviderContext, Segment, TranscribeResult, TranscriptionProvider, UtteranceSink, UtteranceWire, WhisperIn, WhisperOut } from "../../../src/web/audio/types.js";

/* ───── timers ───── */
export interface FakeTimers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(h: unknown): void;
  now(): number;
  advance(ms: number): void;
  pending(): number;
}

export function fakeTimers(): FakeTimers {
  let now = 0;
  let seq = 0;
  const pending = new Map<number, { at: number; fn: () => void }>();
  return {
    now: () => now,
    pending: () => pending.size,
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
        const due = [...pending.entries()].filter(([, p]) => p.at <= end).sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
        if (!due) break;
        pending.delete(due[0]);
        now = due[1].at;
        due[1].fn();
      }
      now = end;
    },
  };
}

/** Lets awaited promise chains settle (several microtask turns). */
export async function flush(turns = 10): Promise<void> {
  for (let i = 0; i < turns; i++) await Promise.resolve();
}

/* ───── media ───── */
type Listener = (ev: unknown) => void;

export class FakeTrack {
  readonly kind: "audio" | "video";
  label: string;
  muted = false;
  enabled = true;
  readyState: "live" | "ended" = "live";
  stopCalls = 0;
  #listeners = new Map<string, Set<Listener>>();
  constructor(kind: "audio" | "video", label = kind === "audio" ? "Fake Microphone" : "Fake Screen") {
    this.kind = kind;
    this.label = label;
  }
  stop(): void {
    this.stopCalls++;
    this.readyState = "ended";
  }
  addEventListener(type: string, fn: Listener): void {
    if (!this.#listeners.has(type)) this.#listeners.set(type, new Set());
    this.#listeners.get(type)!.add(fn);
  }
  removeEventListener(type: string, fn: Listener): void {
    this.#listeners.get(type)?.delete(fn);
  }
  dispatch(type: "ended" | "mute" | "unmute"): void {
    if (type === "mute") this.muted = true;
    if (type === "unmute") this.muted = false;
    for (const fn of this.#listeners.get(type) ?? []) fn({ type });
  }
}

export class FakeStream {
  readonly tracks: FakeTrack[];
  constructor(tracks: FakeTrack[]) {
    this.tracks = tracks;
  }
  getTracks(): FakeTrack[] {
    return this.tracks;
  }
  getAudioTracks(): FakeTrack[] {
    return this.tracks.filter((t) => t.kind === "audio");
  }
  getVideoTracks(): FakeTrack[] {
    return this.tracks.filter((t) => t.kind === "video");
  }
  asStream(): MediaStream {
    return this as unknown as MediaStream;
  }
}

export function domException(name: string, message = `${name} happened`): Error {
  const e = new Error(message);
  e.name = name;
  return e;
}

export interface MediaCall {
  kind: "user" | "display";
  constraints: unknown;
}

/** A MediaDevicesLike whose next results are scripted; every call is recorded synchronously. */
export class FakeMedia implements MediaDevicesLike {
  calls: MediaCall[] = [];
  #userQueue: Array<() => Promise<MediaStream>> = [];
  #displayQueue: Array<() => Promise<MediaStream>> = [];
  devices: MediaDeviceInfo[] = [];
  listeners = new Set<() => void>();
  hasDisplay = true;

  nextUser(result: FakeStream | Error | (() => Promise<MediaStream>)): void {
    this.#userQueue.push(toThunk(result));
  }
  nextDisplay(result: FakeStream | Error | (() => Promise<MediaStream>)): void {
    this.#displayQueue.push(toThunk(result));
  }
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream> {
    this.calls.push({ kind: "user", constraints });
    const next = this.#userQueue.shift();
    return next ? next() : Promise.resolve(new FakeStream([new FakeTrack("audio")]).asStream());
  }
  get getDisplayMedia(): ((options: unknown) => Promise<MediaStream>) | undefined {
    if (!this.hasDisplay) return undefined;
    return (options: unknown) => {
      this.calls.push({ kind: "display", constraints: options });
      const next = this.#displayQueue.shift();
      return next ? next() : Promise.resolve(new FakeStream([new FakeTrack("video"), new FakeTrack("audio", "Tab audio")]).asStream());
    };
  }
  enumerateDevices(): Promise<MediaDeviceInfo[]> {
    return Promise.resolve(this.devices);
  }
  addEventListener(_type: "devicechange", listener: () => void): void {
    this.listeners.add(listener);
  }
  removeEventListener(_type: "devicechange", listener: () => void): void {
    this.listeners.delete(listener);
  }
}

function toThunk(result: FakeStream | Error | (() => Promise<MediaStream>)): () => Promise<MediaStream> {
  if (typeof result === "function") return result;
  if (result instanceof FakeStream) return () => Promise.resolve(result.asStream());
  return () => Promise.reject(result);
}

/** A promise whose settlement the test controls. */
export function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void } {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/* ───── graph ───── */
export class FakeGraph implements AudioGraph {
  ensureCalls = 0;
  attachCalls: CaptureLaneId[] = [];
  detachCalls: CaptureLaneId[] = [];
  ensureError: Error | null = null;
  attachError: Error | null = null;
  ensureGate: Promise<void> | null = null;
  handlers = new Map<CaptureLaneId, FrameHandler>();
  flushFrames = new Map<CaptureLaneId, Float32Array[]>();
  disposed = false;
  readonly sampleRate = 16000;

  async ensureContext(): Promise<void> {
    this.ensureCalls++;
    if (this.ensureGate) await this.ensureGate;
    if (this.ensureError) throw this.ensureError;
  }
  async attach(lane: CaptureLaneId, _stream: MediaStream, onFrame: FrameHandler): Promise<void> {
    this.attachCalls.push(lane);
    if (this.attachError) throw this.attachError;
    this.handlers.set(lane, onFrame);
  }
  async detach(lane: CaptureLaneId): Promise<void> {
    this.detachCalls.push(lane);
    const h = this.handlers.get(lane);
    for (const f of this.flushFrames.get(lane) ?? []) h?.(f);
    this.handlers.delete(lane);
  }
  feed(lane: CaptureLaneId, frames: Float32Array[]): void {
    const h = this.handlers.get(lane);
    if (!h) throw new Error(`no handler attached for lane ${lane}`);
    for (const f of frames) h(f);
  }
  dispose(): void {
    this.disposed = true;
  }
}

/* ───── worker ───── */
export class FakeWorker implements WorkerLike {
  posted: WhisperIn[] = [];
  terminated = 0;
  onmessage: ((ev: { data: WhisperOut }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  postMessage(msg: WhisperIn): void {
    this.posted.push(msg);
  }
  terminate(): void {
    this.terminated++;
  }
  emit(msg: WhisperOut): void {
    this.onmessage?.({ data: msg });
  }
}

/* ───── speech recognition ───── */
export class FakeRecognition implements SpeechRecognitionLike {
  static instances: FakeRecognition[] = [];
  continuous = false;
  interimResults = false;
  maxAlternatives = 1;
  lang = "";
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null = null;
  onerror: ((ev: SpeechRecognitionErrorEventLike) => void) | null = null;
  onend: (() => void) | null = null;
  startCalls = 0;
  stopCalls = 0;
  abortCalls = 0;
  constructor() {
    FakeRecognition.instances.push(this);
  }
  start(): void {
    this.startCalls++;
  }
  stop(): void {
    this.stopCalls++;
  }
  abort(): void {
    this.abortCalls++;
  }
  result(index: number, transcript: string, isFinal: boolean, confidence = 0.9): void {
    const results: SpeechRecognitionEventLike["results"] = { length: index + 1 } as SpeechRecognitionEventLike["results"];
    for (let i = 0; i <= index; i++) results[i] = { isFinal: i < index ? true : isFinal, length: 1, 0: { transcript: i === index ? transcript : "earlier", confidence } };
    this.onresult?.({ resultIndex: index, results });
  }
  error(error: string, message = ""): void {
    this.onerror?.({ error, message });
  }
  end(): void {
    this.onend?.();
  }
}

/* ───── providers ───── */
export class FakeSegmentProvider implements TranscriptionProvider {
  readonly id = "local-whisper" as const;
  readonly label = "Fake Whisper";
  readonly isLocal = true;
  readonly lanes: CaptureLaneId[] = ["remote", "me"];
  readonly mode = "segment" as const;
  readonly model = "onnx-community/whisper-base.en";
  startCalls = 0;
  stopCalls: Array<{ force?: boolean }> = [];
  pending: Array<{ segment: Segment; resolve: (r: TranscribeResult) => void; reject: (e: ProviderError | Error) => void }> = [];
  isReady = false;
  readyInfo: { device: "webgpu" | "wasm"; threads: number; loadMs: number } | null = null;
  startGate: ReturnType<typeof deferred<void>> | null = null;
  ctx: ProviderContext | null = null;
  autoText: ((s: Segment) => string) | null = null;

  async start(ctx: ProviderContext): Promise<void> {
    this.startCalls++;
    this.ctx = ctx;
    if (this.startGate) await this.startGate.promise;
    this.isReady = true;
    this.readyInfo = { device: "wasm", threads: 1, loadMs: 5 };
  }
  transcribe(segment: Segment): Promise<TranscribeResult> {
    if (this.autoText) return Promise.resolve({ text: this.autoText(segment) });
    return new Promise((resolve, reject) => this.pending.push({ segment, resolve, reject }));
  }
  async stop(opts: { force?: boolean } = {}): Promise<void> {
    this.stopCalls.push(opts);
    this.isReady = false;
  }
  resolveNext(text: string): void {
    const p = this.pending.shift();
    if (!p) throw new Error("no pending transcription");
    p.resolve({ text });
  }
  rejectNext(e: ProviderError | Error): void {
    const p = this.pending.shift();
    if (!p) throw new Error("no pending transcription");
    p.reject(e);
  }
}

export class FakePushProvider implements TranscriptionProvider {
  readonly id = "web-speech" as const;
  readonly label = "Fake push";
  readonly isLocal = false;
  readonly lanes: CaptureLaneId[] = ["me"];
  readonly mode = "push" as const;
  readonly model = null;
  async start(): Promise<void> {}
  transcribe(): Promise<TranscribeResult> {
    return Promise.reject(new Error("NOT_SEGMENT_PROVIDER"));
  }
  async stop(): Promise<void> {}
}

/* ───── sink ───── */
export class ScriptedSink implements UtteranceSink {
  readonly posted: UtteranceWire[] = [];
  readonly outcomes = new Map<string, PostOutcome[]>();
  inFlight = 0;
  maxInFlight = 0;
  gates: Array<ReturnType<typeof deferred<void>>> = [];
  hold = false;
  #seq = 0;

  script(id: string, ...outcomes: PostOutcome[]): void {
    this.outcomes.set(id, outcomes);
  }
  async post(u: UtteranceWire): Promise<PostOutcome> {
    this.inFlight++;
    this.maxInFlight = Math.max(this.maxInFlight, this.inFlight);
    if (this.hold) {
      const g = deferred<void>();
      this.gates.push(g);
      await g.promise;
    }
    this.inFlight--;
    this.posted.push(u);
    const scripted = this.outcomes.get(u.id)?.shift();
    if (scripted) return scripted;
    this.#seq++;
    return { ok: true, eventId: `evt_${this.#seq}`, duplicate: false };
  }
  release(n = 1): void {
    for (let i = 0; i < n; i++) this.gates.shift()?.resolve();
  }
}
