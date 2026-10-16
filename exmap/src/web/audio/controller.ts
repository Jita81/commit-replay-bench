// exmap/src/web/audio/controller.ts — AudioController (design §7.7): the one object the UI talks to. Owns the two
// capture lanes, the shared Whisper provider, Web Speech, the manual and replay providers, the transcription and post
// queues, the consent gates, guidance, settings and the AudioState snapshot (useSyncExternalStore-friendly).
// Framework-free; every browser surface is injectable so it is unit-tested with fakes.
import { WebAudioGraph, type AudioGraph } from "./dsp/graph.js";
import { ProviderError, type LaneStateError } from "./errors.js";
import { CaptureLane } from "./lanes/captureLane.js";
import { detectOs } from "./os.js";
import { PostQueue } from "./pipeline/postQueue.js";
import { TranscriptionQueue } from "./pipeline/transcriptionQueue.js";
import { buildUtterance } from "./pipeline/utteranceBuilder.js";
import { isLikelyHallucination } from "./providers/hallucination.js";
import { ManualProvider } from "./providers/manual.js";
import { createProvider, type ProviderDeps } from "./providers/registry.js";
import { parseReplayFixture, ReplayProvider } from "./providers/replay.js";
import { speechRecognitionCtor, WebSpeechProvider } from "./providers/webSpeech.js";
import { browserStorage, loadSettings, MODEL_SEEN_KEY, readFlag, saveSettings, WEBSPEECH_SEEN_KEY, writeFlag } from "./settings.js";
import type {
  AudioLastError, AudioNotice, AudioSettings, AudioState, Backlog, CaptureLaneId, GuidanceReason, LaneView, MediaDevicesLike, ModelStatus, OsId,
  ProviderContext, ProviderId, ReplayFixture, ReplaySpeed, ReplayStatus, Segment, SessionClock, SpeakerStoreLike, StorageLike, TranscriptionProvider, UtteranceDraft, UtteranceSink, WireLane,
} from "./types.js";

export interface AudioControllerDeps {
  sink: UtteranceSink;
  clock: SessionClock;
  speakers: SpeakerStoreLike;
  media?: MediaDevicesLike | null;
  graph?: AudioGraph;
  /** A provider factory (tests inject fakes); defaults to the registry's createProvider. */
  providers?: (id: ProviderId, settings: AudioSettings, deps: ProviderDeps) => TranscriptionProvider;
  providerDeps?: ProviderDeps;
  storage?: StorageLike | null;
  sessionStorage?: StorageLike | null;
  autostartRequested?: boolean;
  os?: OsId;
  isSecureContext?: boolean;
  /** Timers for the post queue's backoff (tests use fake timers). */
  timers?: { setTimeout(fn: () => void, ms: number): unknown; clearTimeout(h: unknown): void };
}

/** The shared Whisper provider as the controller sees it (a fake in tests only needs mode "segment"). */
type SegmentProviderLike = TranscriptionProvider & {
  readonly isReady?: boolean;
  readonly readyInfo?: { device: "webgpu" | "wasm"; threads: number; loadMs: number } | null;
};

export interface ReplayIndexEntry {
  name: string;
  file: string;
  title: string;
  utterances: number;
  durationMs: number;
}

const EMPTY_BACKLOG: Backlog = { segmentsWaiting: 0, segmentInFlight: 0, speechWaitingMs: 0, oldestWaitingMs: 0, failed: 0, utterancesUnsent: 0, postRetries: 0, droppedAsHallucination: 0 };
const EMPTY_REPLAY: ReplayStatus = { fixture: null, state: "empty", index: 0, total: 0, speed: 1, until: null };

export class AudioController {
  readonly levels: Record<CaptureLaneId, number> = { remote: 0, me: 0 };
  readonly os: OsId;

  readonly #sink: UtteranceSink;
  readonly #clock: SessionClock;
  readonly #speakers: SpeakerStoreLike;
  readonly #storage: StorageLike | null;
  readonly #graph: AudioGraph;
  readonly #providers: NonNullable<AudioControllerDeps["providers"]>;
  readonly #providerDeps: ProviderDeps;
  readonly #autostart: boolean;
  readonly #lanes: Record<CaptureLaneId, CaptureLane>;
  readonly #tq: TranscriptionQueue;
  readonly #pq: PostQueue;
  readonly #manual: ManualProvider;
  readonly #replay: ReplayProvider;
  readonly #abort = new AbortController();
  readonly #subs = new Set<() => void>();
  readonly #unsubSpeakers: () => void;

  #state: AudioState;
  #settings: AudioSettings;
  #whisper: SegmentProviderLike | null = null;
  #whisperStarting: Promise<void> | null = null;
  #webSpeech: WebSpeechProvider | null = null;
  #starting: Record<CaptureLaneId, boolean> = { remote: false, me: false };
  #dropped = 0;
  #disposed = false;
  #declined = false;

  constructor(deps: AudioControllerDeps) {
    this.#sink = deps.sink;
    this.#clock = deps.clock;
    this.#speakers = deps.speakers;
    this.#storage = deps.storage === undefined ? browserStorage("local") : deps.storage;
    this.#graph = deps.graph ?? new WebAudioGraph();
    this.#providers = deps.providers ?? createProvider;
    this.#providerDeps = { storage: this.#storage, ...deps.providerDeps };
    this.#autostart = deps.autostartRequested ?? false;
    this.os = deps.os ?? detectOs();
    this.#settings = loadSettings(this.#storage);
    const media = deps.media === undefined ? (typeof navigator !== "undefined" ? (navigator.mediaDevices as unknown as MediaDevicesLike | undefined) ?? null : null) : deps.media;

    const laneDeps = (id: CaptureLaneId): CaptureLane =>
      new CaptureLane({
        id,
        media,
        graph: this.#graph,
        clock: this.#clock,
        speaker: () => this.#speakers.get(id),
        source: id === "remote" ? this.#settings.remoteSource : { kind: "device", deviceId: this.#settings.deviceId.me },
        ...(deps.isSecureContext !== undefined ? { isSecureContext: deps.isSecureContext } : {}),
        hooks: {
          onView: (view) => this.#onLaneView(view),
          onSegment: (segment) => this.#onSegment(segment),
          onGuidance: (reason) => this.#set({ guidance: { lane: id, reason } }),
          onDeviceUnavailable: () => {
            this.#settings = { ...this.#settings, deviceId: { ...this.#settings.deviceId, [id]: null } };
            saveSettings(this.#storage, this.#settings);
            this.#set({ settings: this.#settings });
          },
          onLevel: (level) => {
            this.levels[id] = level;
          },
        },
      });
    this.#lanes = { remote: laneDeps("remote"), me: laneDeps("me") };

    this.#tq = new TranscriptionQueue({
      provider: (lane) => this.#segmentProviderFor(lane),
      onText: (segment, result) => this.#onTranscribed(segment, result.text),
      onError: (segment, error, final) => this.#onTranscribeError(segment, error, final),
      restartProvider: (_lane, error) => this.#restartWhisper(error),
      onChange: () => this.#publishBacklog(),
    });
    this.#pq = new PostQueue({
      sink: this.#sink,
      ...(deps.timers ? { timers: deps.timers } : {}),
      events: {
        onRefused: (u, o) => this.#setLastError({ scope: "post", code: o.reason, message: `${o.detail || o.reason} (${u.id})` }),
        onLastError: (u, o) => this.#setLastError({ scope: "post", code: o.status === null ? "NETWORK" : `HTTP_${o.status}`, message: `${o.message} (${u.id})` }),
        onChange: () => this.#publishBacklog(),
      },
    });

    this.#manual = new ManualProvider();
    this.#replay = new ReplayProvider({ ...(deps.providerDeps?.replayTimers ? { timers: deps.providerDeps.replayTimers } : {}), onStatus: () => this.#set({ replay: this.#replay.status }) });
    void this.#manual.start(this.#ctx());
    void this.#replay.start(this.#ctx());

    const srCtor = deps.providerDeps?.speechRecognitionCtor === undefined ? speechRecognitionCtor() : deps.providerDeps.speechRecognitionCtor;
    this.#state = {
      lanes: { remote: this.#lanes.remote.view, me: this.#lanes.me.view },
      model: { state: "idle", progress: null, device: null, threads: null, model: null, error: null, restarts: 0 },
      backlog: EMPTY_BACKLOG,
      speakers: this.#speakers.labels,
      settings: this.#settings,
      interim: { me: null },
      replay: EMPTY_REPLAY,
      guidance: null,
      notice: null,
      lastError: null,
      refused: [],
      webSpeechAvailable: srCtor !== null,
      webSpeechReason: srCtor === null ? "this browser has no SpeechRecognition (Chrome or Edge required)" : null,
      modelDeclined: false,
    };
    this.#unsubSpeakers = this.#speakers.subscribe(() => this.#set({ speakers: this.#speakers.labels }));
  }

  /* ───────────── store ───────────── */

  get clock(): SessionClock {
    return this.#clock;
  }

  get speakers(): SpeakerStoreLike {
    return this.#speakers;
  }

  getState(): AudioState {
    return this.#state;
  }

  subscribe(fn: () => void): () => void {
    this.#subs.add(fn);
    return () => {
      this.#subs.delete(fn);
    };
  }

  #set(patch: Partial<AudioState>): void {
    this.#state = { ...this.#state, ...patch };
    for (const fn of this.#subs) fn();
  }

  #setModel(patch: Partial<ModelStatus>): void {
    this.#set({ model: { ...this.#state.model, ...patch } });
  }

  #setLastError(e: Omit<AudioLastError, "at">): void {
    this.#set({ lastError: { ...e, at: Date.now() } });
  }

  #publishBacklog(): void {
    const backlog: Backlog = {
      segmentsWaiting: this.#tq.segmentsWaiting,
      segmentInFlight: this.#tq.inFlight,
      speechWaitingMs: this.#tq.speechWaitingMs,
      oldestWaitingMs: this.#tq.oldestWaitingMs,
      failed: this.#tq.failed.length,
      utterancesUnsent: this.#pq.unsent,
      postRetries: this.#pq.retries,
      droppedAsHallucination: this.#dropped,
    };
    this.#set({ backlog, refused: [...this.#pq.refused] });
  }

  #onLaneView(view: LaneView): void {
    this.#set({ lanes: { ...this.#state.lanes, [view.id]: view } });
  }

  /* ───────────── provider context and emit ───────────── */

  #ctx(): ProviderContext {
    return {
      emit: (draft) => this.#emit(draft),
      onInterim: (lane, text) => {
        if (lane === "me") this.#set({ interim: { me: text } });
      },
      onProgress: (p) => this.#setModel({ progress: p }),
      clock: this.#clock,
      speakers: this.#speakers,
      signal: this.#abort.signal,
    };
  }

  #emit(draft: UtteranceDraft): void {
    if (this.#disposed) return;
    try {
      this.#pq.enqueue(buildUtterance(draft));
    } catch {
      /* EMPTY_TEXT: nothing to post */
    }
  }

  /* ───────────── segments ───────────── */

  #segmentProviderFor(lane: CaptureLaneId): TranscriptionProvider | null {
    if (this.#settings.provider[lane] !== "local-whisper") return null;
    if (this.#declined) return null;
    return this.#whisper ?? this.#ensureWhisper();
  }

  #onSegment(segment: Segment): void {
    if (this.#disposed) return;
    this.#tq.enqueue(segment);
  }

  #onTranscribed(segment: Segment, rawText: string): void {
    const text = rawText.trim();
    if (isLikelyHallucination(text, { durationMs: segment.endedAt - segment.startedAt, peakRmsDb: segment.peakRmsDb })) {
      this.#dropped++;
      this.#publishBacklog();
      return;
    }
    this.#emit({
      text,
      lane: segment.lane,
      speaker: segment.speaker,
      provider: "local-whisper",
      model: this.#whisper?.model ?? this.#settings.whisperModel,
      isLocal: true,
      confidence: null,
      tStartMs: segment.startedAt,
      tEndMs: segment.endedAt,
    });
  }

  #onTranscribeError(_segment: Segment, error: ProviderError, _final: boolean): void {
    this.#setLastError({ scope: "provider", code: error.code, message: error.detail || error.message });
  }

  /* ───────────── whisper ───────────── */

  #ensureWhisper(): SegmentProviderLike | null {
    if (this.#whisper) return this.#whisper;
    const p = this.#providers("local-whisper", this.#settings, {
      ...this.#providerDeps,
      whisper: { ...this.#providerDeps.whisper, onReady: (info) => this.#setModel({ state: "ready", device: info.device, threads: info.threads, error: null }) },
    });
    if (p.mode !== "segment") return null;
    this.#whisper = p;
    return this.#whisper;
  }

  #consentFor(model: string): boolean {
    return readFlag(this.#storage, MODEL_SEEN_KEY(model));
  }

  /** Loads the model (consent already given). Resolves when ready or failed; never throws. */
  #startWhisper(): Promise<void> {
    if (this.#whisperStarting) return this.#whisperStarting;
    const p = this.#ensureWhisper();
    if (!p) return Promise.resolve();
    if (p.isReady) {
      this.#tq.resume();
      return Promise.resolve();
    }
    this.#tq.pause();
    this.#setModel({ state: "loading", model: this.#settings.whisperModel, error: null });
    this.#whisperStarting = p
      .start(this.#ctx())
      .then(() => {
        if (this.#whisper !== p) return;
        const info = p.readyInfo;
        this.#setModel({ state: "ready", device: info?.device ?? null, threads: info?.threads ?? null, error: null });
        this.#tq.resume();
      })
      .catch((e: unknown) => {
        const err = e instanceof ProviderError ? e : new ProviderError("MODEL_LOAD_FAILED", String((e as Error)?.message ?? e));
        this.#setModel({ state: "error", error: { code: err.code, message: err.detail || err.message } });
        this.#setLastError({ scope: "provider", code: err.code, message: err.detail || err.message });
      })
      .finally(() => {
        this.#whisperStarting = null;
      });
    return this.#whisperStarting;
  }

  /** The queue's one automatic forced restart after a crash or timeout; a second failure leaves the queue paused. */
  async #restartWhisper(error: ProviderError): Promise<boolean> {
    if (this.#state.model.restarts >= 1) {
      this.#setModel({ state: "error", error: { code: error.code, message: error.detail || error.message } });
      return false;
    }
    this.#setModel({ restarts: this.#state.model.restarts + 1 });
    const old = this.#whisper;
    this.#whisper = null;
    if (old) await old.stop({ force: true });
    await this.#startWhisper();
    return this.#state.model.state === "ready";
  }

  /* ───────────── lanes ───────────── */

  async startLane(lane: CaptureLaneId): Promise<void> {
    if (this.#disposed) return;
    const view = this.#lanes[lane].view;
    if (this.#starting[lane] || view.state === "requesting" || view.state === "live") return;
    this.#starting[lane] = true;
    try {
      this.#set({ lastError: null });
      try {
        await this.#lanes[lane].start();
      } catch (e) {
        this.#setLastError({ scope: "lane", code: (e as LaneStateError).name ?? "LaneStateError", message: String((e as Error).message) });
        return;
      }
      const after = this.#lanes[lane].view;
      if (after.state !== "live") {
        if (after.error) this.#setLastError({ scope: "lane", code: after.error.code, message: after.error.message });
        return;
      }
      const provider = this.#settings.provider[lane];
      if (provider === "local-whisper") {
        if (this.#state.model.state === "ready" || this.#state.model.state === "loading") return;
        if (this.#declined) return;
        if (!this.#consentFor(this.#settings.whisperModel)) {
          this.#tq.pause();
          this.#set({ notice: { kind: "model", model: this.#settings.whisperModel, lane } });
          this.#setModel({ state: "awaiting_consent", model: this.#settings.whisperModel });
          return;
        }
        await this.#startWhisper();
        return;
      }
      if (provider === "web-speech" && lane === "me") {
        await this.#startWebSpeech();
      }
    } finally {
      this.#starting[lane] = false;
    }
  }

  async stopLane(lane: CaptureLaneId): Promise<void> {
    await this.#lanes[lane].stop("user");
  }

  async #startWebSpeech(): Promise<void> {
    if (this.#webSpeech?.started) return;
    if (!readFlag(this.#storage, WEBSPEECH_SEEN_KEY)) {
      this.#set({ notice: { kind: "webspeech", previous: "local-whisper" } });
      return;
    }
    const p = this.#providers("web-speech", this.#settings, {
      ...this.#providerDeps,
      webSpeech: { ...this.#providerDeps.webSpeech, onError: (e) => this.#setLastError({ scope: "provider", code: e.code, message: e.detail || e.message }) },
    });
    this.#webSpeech = p as WebSpeechProvider;
    try {
      await p.start(this.#ctx());
    } catch (e) {
      const err = e instanceof ProviderError ? e : new ProviderError("WEB_SPEECH_UNSUPPORTED", String((e as Error)?.message ?? e));
      this.#setLastError({ scope: "provider", code: err.code, message: err.detail || err.message });
    }
  }

  /* ───────────── settings ───────────── */

  /** Persisted to localStorage["exmap.audio.v1"]. Lane-bound fields are refused (returns false) while that lane is requesting | live. */
  updateSettings(patch: Partial<AudioSettings>): boolean {
    const busy = (lane: CaptureLaneId) => {
      const st = this.#lanes[lane].view.state;
      return st === "requesting" || st === "live";
    };
    const next: AudioSettings = { ...this.#settings, provider: { ...this.#settings.provider }, deviceId: { ...this.#settings.deviceId } };
    let refused = false;
    if (patch.provider) {
      for (const lane of ["remote", "me"] as const) {
        const v = patch.provider[lane];
        if (v === undefined || v === next.provider[lane]) continue;
        if (busy(lane)) {
          refused = true;
          continue;
        }
        if (lane === "me") {
          next.provider.me = v as AudioSettings["provider"]["me"];
          if (v === "web-speech" && !readFlag(this.#storage, WEBSPEECH_SEEN_KEY)) {
            this.#set({ notice: { kind: "webspeech", previous: this.#settings.provider.me } });
          }
        } else if (v === "local-whisper" || v === null) next.provider.remote = v;
      }
    }
    if (patch.deviceId) {
      for (const lane of ["remote", "me"] as const) {
        const v = patch.deviceId[lane];
        if (v === undefined || v === next.deviceId[lane]) continue;
        if (busy(lane)) {
          refused = true;
          continue;
        }
        next.deviceId[lane] = v;
        if (lane === "me") this.#lanes.me.setSource({ kind: "device", deviceId: v });
        else if (next.remoteSource.kind === "device") this.#lanes.remote.setSource({ kind: "device", deviceId: v });
      }
    }
    if (patch.remoteSource && JSON.stringify(patch.remoteSource) !== JSON.stringify(next.remoteSource)) {
      if (busy("remote")) refused = true;
      else {
        next.remoteSource = patch.remoteSource.kind === "device" ? { kind: "device", deviceId: patch.remoteSource.deviceId ?? next.deviceId.remote } : { kind: "display" };
        this.#lanes.remote.setSource(next.remoteSource);
      }
    }
    let whisperChanged = false;
    for (const key of ["whisperModel", "whisperDtype", "whisperDevice"] as const) {
      const v = patch[key];
      if (v !== undefined && v !== next[key]) {
        (next as unknown as Record<string, unknown>)[key] = v;
        whisperChanged = true;
      }
    }
    if (patch.webSpeechLang !== undefined) next.webSpeechLang = patch.webSpeechLang;
    this.#settings = next;
    saveSettings(this.#storage, next);
    this.#set({ settings: next });
    if (whisperChanged) void this.#reloadWhisperForSettings();
    return !refused;
  }

  async #reloadWhisperForSettings(): Promise<void> {
    const old = this.#whisper;
    this.#whisper = null;
    this.#declined = false;
    this.#set({ modelDeclined: false });
    if (old) await old.stop({ force: true });
    this.#setModel({ state: "idle", progress: null, device: null, threads: null, model: null, error: null });
    const needs = (["remote", "me"] as const).some((l) => this.#settings.provider[l] === "local-whisper" && this.#lanes[l].view.state === "live");
    if (!needs) return;
    if (!this.#consentFor(this.#settings.whisperModel)) {
      this.#tq.pause();
      this.#set({ notice: { kind: "model", model: this.#settings.whisperModel, lane: this.#settings.provider.remote === "local-whisper" && this.#lanes.remote.view.state === "live" ? "remote" : "me" } });
      this.#setModel({ state: "awaiting_consent", model: this.#settings.whisperModel });
      return;
    }
    await this.#startWhisper();
  }

  setSpeaker(lane: CaptureLaneId, label: string | null): void {
    this.#speakers.set(lane, label);
  }

  /* ───────────── consent ───────────── */

  acceptNotice(): void {
    const notice = this.#state.notice;
    if (!notice) return;
    this.#set({ notice: null });
    if (notice.kind === "model") {
      writeFlag(this.#storage, MODEL_SEEN_KEY(notice.model), true);
      this.#declined = false;
      this.#set({ modelDeclined: false });
      void this.#startWhisper();
    } else {
      writeFlag(this.#storage, WEBSPEECH_SEEN_KEY, true);
      if (this.#lanes.me.view.state === "live" && this.#settings.provider.me === "web-speech") void this.#startWebSpeech();
    }
  }

  cancelNotice(): void {
    const notice = this.#state.notice;
    if (!notice) return;
    this.#set({ notice: null });
    if (notice.kind === "model") {
      this.#declined = true;
      this.#set({ modelDeclined: true });
      this.#setModel({ state: "idle", progress: null });
      this.#tq.failWaiting();
    } else {
      this.#settings = { ...this.#settings, provider: { ...this.#settings.provider, me: notice.previous } };
      saveSettings(this.#storage, this.#settings);
      this.#set({ settings: this.#settings });
    }
  }

  /* ───────────── manual and replay ───────────── */

  /** Typed text; tStartMs = the first keystroke into the empty box (null → now). Returns false for empty text. */
  submitManual(text: string, lane: WireLane, speaker: string | null, tStartMs: number | null = null): boolean {
    return this.#manual.submit(text, lane, speaker, tStartMs);
  }

  get replayProvider(): ReplayProvider {
    return this.#replay;
  }

  loadReplay(fixture: ReplayFixture, name: string): void {
    this.#replay.load(fixture, name);
    this.#set({ replay: this.#replay.status });
  }

  playReplay(speed: ReplaySpeed, opts?: { until?: number | string }): Promise<void> {
    return this.#replay.play(speed, opts);
  }

  stepReplay(): void {
    this.#replay.step();
  }

  skipReplay(until: number | string): void {
    this.#replay.skip(until);
  }

  pauseReplay(): void {
    this.#replay.pause();
  }

  resumeReplay(): void {
    this.#replay.resume();
  }

  resetReplay(): void {
    this.#replay.reset();
  }

  /** `?replay=<name>&speed=<ReplaySpeed>&autostart=1`: loads the named fixture from index.json; with autostart presses Play. */
  async applyReplayQuery(search: string, fetchFn: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u)): Promise<boolean> {
    const q = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
    const name = q.get("replay");
    if (!name) return false;
    const index = await fetchReplayIndex(fetchFn);
    const entry = index.find((e) => e.name === name);
    if (!entry) throw new ProviderError("REPLAY_FIXTURE_INVALID", `no fixture named ${name} in index.json`);
    const fixture = await fetchReplayFixture(entry.file, fetchFn);
    this.loadReplay(fixture, entry.name);
    const speedRaw = q.get("speed");
    const speed: ReplaySpeed = speedRaw === "instant" ? "instant" : speedRaw && [0.5, 1, 2, 4].includes(Number(speedRaw)) ? (Number(speedRaw) as ReplaySpeed) : 1;
    if (q.get("autostart") === "1") void this.playReplay(speed);
    return true;
  }

  /* ───────────── guidance, retries, idle ───────────── */

  openGuidance(lane: CaptureLaneId, reason: GuidanceReason): void {
    this.#set({ guidance: { lane, reason } });
  }

  closeGuidance(): void {
    this.#set({ guidance: null });
  }

  retryFailedSegments(): void {
    if (this.#declined) {
      // a retry after a declined download re-asks the question
      this.#declined = false;
      this.#set({ modelDeclined: false });
      if (!this.#consentFor(this.#settings.whisperModel)) {
        this.#tq.retryFailed();
        this.#tq.pause();
        this.#set({ notice: { kind: "model", model: this.#settings.whisperModel, lane: "me" } });
        this.#setModel({ state: "awaiting_consent", model: this.#settings.whisperModel });
        return;
      }
    }
    this.#setModel({ restarts: 0 });
    this.#tq.retryFailed();
    if (this.#state.model.state === "error" || this.#state.model.state === "idle") void this.#startWhisper();
  }

  async clearDownloadedModels(): Promise<void> {
    try {
      if (typeof caches !== "undefined") await caches.delete("transformers-cache");
    } catch {
      /* ignore */
    }
    for (const m of ["onnx-community/whisper-base.en", "onnx-community/whisper-tiny.en"]) writeFlag(this.#storage, MODEL_SEEN_KEY(m), false);
    await this.#reloadWhisperForSettings();
  }

  pendingWork(): number {
    const b = this.#state.backlog;
    return b.segmentsWaiting + b.segmentInFlight + b.failed + b.utterancesUnsent;
  }

  segmentsClosed(): Record<CaptureLaneId, number> {
    return { remote: this.#state.lanes.remote.segmentsClosed, me: this.#state.lanes.me.segmentsClosed };
  }

  /** Resolves when the post queue and the transcription queue are empty, the replay is not playing, and (with autostart) the replay is done. */
  async idle(): Promise<void> {
    for (;;) {
      await this.#pq.idle();
      await this.#tq.idle();
      const r = this.#replay.status;
      if (r.state === "playing" || (this.#autostart && r.fixture !== null && r.state !== "done")) {
        await new Promise<void>((resolve) => {
          const off = this.subscribe(() => {
            const s = this.#replay.status;
            if (s.state !== "playing" && (!this.#autostart || s.fixture === null || s.state === "done")) {
              off();
              resolve();
            }
          });
        });
        continue;
      }
      if (this.#pq.unsent === 0 && this.#tq.segmentsWaiting === 0 && this.#tq.inFlight === 0) return;
    }
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#abort.abort();
    this.#unsubSpeakers();
    void this.#lanes.remote.stop("user");
    void this.#lanes.me.stop("user");
    this.#tq.dispose();
    this.#pq.dispose();
    void this.#replay.stop();
    void this.#manual.stop();
    void this.#webSpeech?.stop({ force: true });
    void this.#whisper?.stop({ force: true });
    this.#whisper = null;
    this.#graph.dispose();
  }
}

/* ───────────── replay catalogue ───────────── */

export async function fetchReplayIndex(fetchFn: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u)): Promise<ReplayIndexEntry[]> {
  const res = await fetchFn("/replay/index.json");
  if (!res.ok) throw new ProviderError("REPLAY_FIXTURE_INVALID", "index.json could not be fetched");
  const body = (await res.json()) as { fixtures?: unknown };
  if (!body || !Array.isArray(body.fixtures)) throw new ProviderError("REPLAY_FIXTURE_INVALID", "index.json has no fixtures array");
  return body.fixtures as ReplayIndexEntry[];
}

export async function fetchReplayFixture(file: string, fetchFn: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u)): Promise<ReplayFixture> {
  const res = await fetchFn(`/replay/${file}`);
  if (!res.ok) throw new ProviderError("REPLAY_FIXTURE_INVALID", `${file} could not be fetched`);
  return parseReplayFixture(await res.json());
}

/** The window.__exmap.audio and .replay hooks the web module installs when test hooks are on (design §7.7, §10.9). */
export function audioTestHooks(controller: AudioController): {
  audio: { state(): AudioState; postQueueIdle(): Promise<void>; segmentsClosed(): Record<CaptureLaneId, number>; pendingWork(): number };
  replay: { playUntil(target: string | number): Promise<void>; skip(target: string | number): Promise<void>; playAll(): Promise<void>; readonly position: number };
} {
  return {
    audio: {
      state: () => controller.getState(),
      postQueueIdle: () => controller.idle(),
      segmentsClosed: () => controller.segmentsClosed(),
      pendingWork: () => controller.pendingWork(),
    },
    replay: {
      playUntil: async (target) => {
        await controller.playReplay("instant", { until: target });
        await controller.idle();
      },
      skip: async (target) => {
        controller.skipReplay(target);
        await controller.idle();
      },
      playAll: async () => {
        await controller.playReplay("instant");
        await controller.idle();
      },
      get position() {
        return controller.getState().replay.index;
      },
    },
  };
}

export type { AudioNotice };
