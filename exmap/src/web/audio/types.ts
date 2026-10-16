// exmap/src/web/audio/types.ts — the audio module's shared types (design §7.2, §7.4, §7.7). Types only; imports only
// types from core. Every wire-facing name is aliased from core, never retyped.
import type { Lane, TranscriptionProvider as CoreTranscriptionProvider, Utterance } from "../../core/types.js";

/* ───────────── lanes (§7.2) ───────────── */
export type CaptureLaneId = "remote" | "me";
export type LaneSource = { kind: "display" } | { kind: "device"; deviceId: string | null };
export type LaneState = "idle" | "requesting" | "live" | "stopped" | "error";
export type StopReason = "user" | "ended_by_browser" | "device_lost";
export type SignalState = "unknown" | "signal" | "silent";
export type GuidanceReason = "no_audio_track" | "permission_denied" | "unsupported" | "silent" | "no_device" | "howto";
export type OsId = "windows" | "macos" | "linux" | "other";

export type LaneErrorCode =
  | "PERMISSION_DENIED"
  | "NO_DEVICE"
  | "DEVICE_BUSY"
  | "DEVICE_UNAVAILABLE"
  | "ABORTED"
  | "NOT_ACTIVATED"
  | "BAD_CONSTRAINTS"
  | "INSECURE_CONTEXT"
  | "UNSUPPORTED"
  | "NO_AUDIO_TRACK"
  | "AUDIO_CONTEXT_FAILED"
  | "WORKLET_LOAD_FAILED"
  | "UNKNOWN";

export interface LaneError {
  code: LaneErrorCode;
  domName: string | null;
  message: string;
}

export interface LaneView {
  id: CaptureLaneId;
  state: LaneState;
  source: LaneSource;
  error: LaneError | null; // set iff state === "error"
  stopReason: StopReason | null; // set iff state === "stopped"
  signal: SignalState;
  trackLabel: string | null;
  segmentsClosed: number;
  startedAtMs: number | null;
}

/* ───────────── segments (§7.3) ───────────── */
export interface Segment {
  lane: CaptureLaneId;
  seq: number; // per lane, from 1
  startedAt: number; // session ms (pre-roll included)
  onsetAt: number;
  endedAt: number;
  speechMs: number;
  pcm: Float32Array; // mono 16 kHz
  sampleRate: 16000;
  peakRmsDb: number;
  cappedAt15s: boolean;
  speaker: string | null;
}

/* ───────────── providers (§7.4) ───────────── */
export type ProviderId = CoreTranscriptionProvider; // aliased from core, never retyped
export type WireLane = Lane;
export type UtteranceWire = Utterance; // the wire shape IS core's Utterance

export interface UtteranceDraft {
  text: string;
  lane: WireLane;
  speaker: string | null;
  provider: ProviderId;
  model: string | null;
  isLocal: boolean;
  confidence: number | null;
  tStartMs: number;
  tEndMs: number;
}

export interface TranscribeResult {
  text: string;
  confidence?: number;
}

export type ModelProgressPhase = "downloading" | "loading_runtime" | "ready" | "error";
export interface ModelProgress {
  phase: ModelProgressPhase;
  percent: number; // 0..100
  loadedBytes: number;
  totalBytes: number;
  file: string | null;
  cached: boolean;
}

export interface SessionClock {
  nowMs(): number; // integer ms since the session's created_at, never negative
}

export interface SpeakerLabels {
  me: string | null;
  remote: string | null;
  remoteKnown: string[];
}

export interface SpeakerStoreLike {
  get(lane: WireLane): string | null;
  set(lane: CaptureLaneId, label: string | null): void;
  readonly labels: SpeakerLabels;
  subscribe(fn: () => void): () => void;
}

export interface ProviderContext {
  emit(draft: UtteranceDraft): void;
  onInterim?(lane: CaptureLaneId, text: string | null): void;
  onProgress?(p: ModelProgress): void;
  clock: SessionClock;
  speakers: SpeakerStoreLike;
  signal: AbortSignal;
}

export type ProviderMode = "segment" | "push";

export interface TranscriptionProvider {
  readonly id: ProviderId;
  readonly label: string;
  readonly isLocal: boolean;
  readonly lanes: CaptureLaneId[];
  readonly mode: ProviderMode;
  readonly model: string | null;
  start(ctx: ProviderContext): Promise<void>;
  transcribe(segment: Segment, opts?: { signal?: AbortSignal }): Promise<TranscribeResult>;
  stop(opts?: { force?: boolean }): Promise<void>;
}

export type ProviderErrorCode =
  | "NOT_SEGMENT_PROVIDER"
  | "MODEL_LOAD_FAILED"
  | "TRANSCRIBE_FAILED"
  | "TRANSCRIBE_TIMEOUT"
  | "WEBGPU_UNAVAILABLE"
  | "WEB_SPEECH_UNSUPPORTED"
  | "WEB_SPEECH_NETWORK"
  | "WEB_SPEECH_DENIED"
  | "REPLAY_FIXTURE_INVALID"
  | "WORKER_CRASHED";

/* ───────────── local whisper (§7.4) ───────────── */
export type WhisperModelId = "onnx-community/whisper-base.en" | "onnx-community/whisper-tiny.en";
export type WhisperDtype = "q8" | "q4";
export type WhisperDevice = "auto" | "wasm";
export type WhisperWasmPaths = { mjs: string; wasm: string };

export type WhisperIn =
  | { type: "load"; model: WhisperModelId; dtype: WhisperDtype; device: WhisperDevice; wasmPaths: WhisperWasmPaths; numThreads: number | null }
  | { type: "transcribe"; jobId: number; pcm: Float32Array }
  | { type: "dispose" };

/** Exactly transformers.js' progress_callback events (spike §d); the worker forwards them unchanged. */
export type TransformersProgressEvent =
  | { status: "initiate"; name: string; file: string }
  | { status: "download"; name: string; file: string }
  | { status: "progress"; name: string; file: string; progress: number; loaded: number; total: number }
  | { status: "progress_total"; name: string; progress: number; loaded: number; total: number; files?: Record<string, { loaded: number; total: number }> }
  | { status: "done"; name: string; file: string }
  | { status: "ready"; task: string; model: string };

export type WhisperOut =
  | { type: "progress"; data: TransformersProgressEvent }
  | { type: "ready"; model: string; device: "webgpu" | "wasm"; threads: number; loadMs: number }
  | { type: "result"; jobId: number; text: string; ms: number }
  | { type: "error"; jobId: number | null; stage: "load" | "transcribe" | "unhandled"; name: string; message: string };

/* ───────────── replay (§7.4) ───────────── */
export interface ReplayFixture {
  version: 1;
  title: string;
  story?: string;
  speakers?: Partial<Record<"remote" | "me", string>>;
  utterances: ReplayUtterance[];
  ui?: unknown;
}
export interface ReplayUtterance {
  label?: string; // unique when present, e.g. "u05"
  atMs: number; // non-decreasing
  lane: WireLane;
  speaker: string | null;
  text: string;
  durationMs?: number;
  expect?: unknown; // opaque
}
export type ReplaySpeed = 0.5 | 1 | 2 | 4 | "instant";
export type ReplayState = "empty" | "ready" | "playing" | "paused" | "done";
export interface ReplayStatus {
  fixture: string | null;
  state: ReplayState;
  index: number; // utterances emitted so far (= the next index to emit)
  total: number;
  speed: ReplaySpeed;
  until: number | null;
}

/* ───────────── pipeline (§7.5) ───────────── */
export type PostOutcome =
  | { ok: true; eventId: string; duplicate: boolean }
  | { ok: false; kind: "refused"; status: number; reason: string; detail: string }
  | { ok: false; kind: "transient"; status: number | null; message: string };

export interface UtteranceSink {
  post(u: UtteranceWire): Promise<PostOutcome>;
}

export interface Backlog {
  segmentsWaiting: number;
  segmentInFlight: number; // 0 | 1
  speechWaitingMs: number;
  oldestWaitingMs: number; // session ms of the oldest waiting segment's startedAt, or 0
  failed: number;
  utterancesUnsent: number;
  postRetries: number;
  droppedAsHallucination: number;
}

/* ───────────── controller (§7.7) ───────────── */
export interface AudioSettings {
  provider: { remote: "local-whisper" | null; me: "local-whisper" | "web-speech" | null };
  remoteSource: LaneSource;
  deviceId: { me: string | null; remote: string | null };
  whisperModel: WhisperModelId;
  whisperDtype: WhisperDtype;
  whisperDevice: WhisperDevice;
  webSpeechLang: string;
}

export type ModelState = "idle" | "awaiting_consent" | "loading" | "ready" | "error";

export interface ProviderErrorView {
  code: ProviderErrorCode;
  message: string;
}

export interface ModelStatus {
  state: ModelState;
  progress: ModelProgress | null;
  device: "webgpu" | "wasm" | null;
  threads: number | null;
  model: WhisperModelId | null;
  error: ProviderErrorView | null;
  restarts: number;
}

export type AudioNotice =
  | { kind: "model"; model: WhisperModelId; lane: CaptureLaneId }
  | { kind: "webspeech"; previous: AudioSettings["provider"]["me"] };

export interface AudioLastError {
  scope: "lane" | "provider" | "post";
  code: string;
  message: string;
  at: number;
}

export interface RefusedUtterance {
  id: string;
  text: string;
  status: number;
  reason: string;
  detail: string;
}

export interface AudioState {
  lanes: Record<CaptureLaneId, LaneView>;
  model: ModelStatus;
  backlog: Backlog;
  speakers: SpeakerLabels;
  settings: AudioSettings;
  interim: { me: string | null };
  replay: ReplayStatus;
  guidance: { lane: CaptureLaneId; reason: GuidanceReason } | null;
  notice: AudioNotice | null;
  lastError: AudioLastError | null;
  refused: RefusedUtterance[];
  webSpeechAvailable: boolean;
  webSpeechReason: string | null;
  modelDeclined: boolean; // the person declined the model download: whisper lanes run capture-only
}

/* ───────────── injected browser surfaces ───────────── */
export interface MediaDevicesLike {
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream>;
  getDisplayMedia?: (options: unknown) => Promise<MediaStream>;
  enumerateDevices(): Promise<MediaDeviceInfo[]>;
  addEventListener(type: "devicechange", listener: () => void): void;
  removeEventListener?(type: "devicechange", listener: () => void): void;
}

/** The subset of Storage the module uses; tests pass a Map-backed fake. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}
