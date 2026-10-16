// exmap/src/web/audio/lanes/captureLane.ts — one capture lane as a state machine (design §7.2):
// idle → requesting → live → stopped | error, over one MediaStream audio track. The media request is made synchronously
// inside start() (transient activation); the graph is set up after the stream resolves. The lane owns its VAD and
// segmenter: frames from the graph become Segments through hooks.onSegment; it also publishes its LaneView on change,
// no-signal detection (10 s under −60 dBFS) and the meter level.
import { GraphError, LANE_ERROR, LaneStateError, mapDomException } from "../errors.js";
import type { AudioGraph } from "../dsp/graph.js";
import { levelStep } from "../dsp/levels.js";
import { createSegmenter, DEFAULT_SEGMENTER, segmenterFlush, segmenterStep, type SegmenterConfig, type SegmenterState } from "../dsp/segmenter.js";
import { DEFAULT_VAD, FRAME_MS, type VadConfig } from "../dsp/vad.js";
import type { CaptureLaneId, GuidanceReason, LaneError, LaneErrorCode, LaneSource, LaneView, MediaDevicesLike, Segment, SessionClock, StopReason } from "../types.js";
import { deviceConstraints, REMOTE_DISPLAY_OPTIONS } from "./constraints.js";

export const SILENT_AFTER_MS = 10_000;
export const SILENT_BELOW_DB = -60;

export interface CaptureLaneHooks {
  onView?(view: LaneView): void;
  onSegment?(segment: Segment): void;
  onGuidance?(reason: GuidanceReason): void;
  /** A saved deviceId that no longer exists was dropped (the controller clears the setting). */
  onDeviceUnavailable?(deviceId: string): void;
  onLevel?(level: number): void;
  onFlush?(): void;
}

export interface CaptureLaneDeps {
  id: CaptureLaneId;
  media: MediaDevicesLike | null;
  graph: AudioGraph;
  clock: SessionClock;
  speaker: () => string | null;
  hooks?: CaptureLaneHooks;
  source?: LaneSource;
  segmenter?: SegmenterConfig;
  vad?: VadConfig;
  isSecureContext?: boolean;
}

export class CaptureLane {
  readonly id: CaptureLaneId;
  #media: MediaDevicesLike | null;
  readonly #graph: AudioGraph;
  readonly #clock: SessionClock;
  readonly #speaker: () => string | null;
  readonly #hooks: CaptureLaneHooks;
  readonly #segCfg: SegmenterConfig;
  readonly #vadCfg: VadConfig;
  readonly #secure: boolean;

  #view: LaneView;
  #stream: MediaStream | null = null;
  #track: MediaStreamTrack | null = null;
  #seg: SegmenterState;
  #frameIndex = 0;
  #quietMs = 0;
  #level = 0;
  #generation = 0; // bumps on every start/stop so a late stream never attaches
  #frameGen = -1; // the generation whose frames are accepted (stays open through detach()'s flush)
  #trackListeners: Array<() => void> = [];

  constructor(deps: CaptureLaneDeps) {
    this.id = deps.id;
    this.#media = deps.media;
    this.#graph = deps.graph;
    this.#clock = deps.clock;
    this.#speaker = deps.speaker;
    this.#hooks = deps.hooks ?? {};
    this.#segCfg = deps.segmenter ?? DEFAULT_SEGMENTER;
    this.#vadCfg = deps.vad ?? DEFAULT_VAD;
    this.#secure = deps.isSecureContext ?? (typeof globalThis.isSecureContext === "boolean" ? globalThis.isSecureContext : true);
    const source: LaneSource = deps.source ?? (deps.id === "remote" ? { kind: "display" } : { kind: "device", deviceId: null });
    this.#view = { id: deps.id, state: "idle", source, error: null, stopReason: null, signal: "unknown", trackLabel: null, segmentsClosed: 0, startedAtMs: null };
    this.#seg = createSegmenter(deps.id, this.#vadCfg);
  }

  get view(): LaneView {
    return this.#view;
  }

  get level(): number {
    return this.#level;
  }

  setMedia(media: MediaDevicesLike | null): void {
    this.#media = media;
  }

  /** Allowed in idle | stopped | error only. `me` is always a device source. */
  setSource(source: LaneSource): void {
    const st = this.#view.state;
    if (st === "requesting" || st === "live") throw new LaneStateError("setSource", st);
    if (this.id === "me" && source.kind !== "device") throw new LaneStateError("setSource(display) on the me lane", st);
    this.#publish({ source });
  }

  /** Rejects LaneStateError while requesting | live. The media request happens synchronously in this call. */
  start(): Promise<void> {
    const st = this.#view.state;
    if (st === "requesting" || st === "live") return Promise.reject(new LaneStateError("start", st));
    const gen = ++this.#generation;
    this.#publish({ state: "requesting", error: null, stopReason: null, signal: "unknown", trackLabel: null, startedAtMs: null });
    this.#seg = createSegmenter(this.id, this.#vadCfg);
    this.#frameIndex = 0;
    this.#quietMs = 0;
    this.#level = 0;

    let request: Promise<MediaStream>;
    try {
      request = this.#request(this.#view.source, false);
    } catch (e) {
      return this.#failRequest(gen, e, this.#view.source);
    }
    return this.#afterRequest(gen, request, this.#view.source, false);
  }

  /** The synchronous media call. Throws LaneError-shaped objects for the pre-flight checks. */
  #request(source: LaneSource, retryWithoutDevice: boolean): Promise<MediaStream> {
    const media = this.#media;
    if (!this.#secure) throw laneError("INSECURE_CONTEXT", null, "capture needs a secure context (open http://127.0.0.1)");
    if (!media) throw laneError("UNSUPPORTED", null, "navigator.mediaDevices is not available");
    if (source.kind === "display") {
      const gdm = media.getDisplayMedia;
      if (typeof gdm !== "function") throw laneError("UNSUPPORTED", null, "getDisplayMedia is not available in this browser");
      return gdm.call(media, REMOTE_DISPLAY_OPTIONS);
    }
    if (typeof media.getUserMedia !== "function") throw laneError("UNSUPPORTED", null, "getUserMedia is not available in this browser");
    return media.getUserMedia(deviceConstraints(this.id, retryWithoutDevice ? null : source.deviceId));
  }

  async #afterRequest(gen: number, request: Promise<MediaStream>, source: LaneSource, retried: boolean): Promise<void> {
    let stream: MediaStream;
    try {
      stream = await request;
    } catch (e) {
      if (gen !== this.#generation || this.#view.state !== "requesting") return; // stopped meanwhile
      const mapped = mapDomException(e);
      if (mapped.domName === "OverconstrainedError" && source.kind === "device" && source.deviceId && !retried) {
        // the saved device is gone: clear the saved id, retry once without it
        const dropped = source.deviceId;
        const fallback: LaneSource = { kind: "device", deviceId: null };
        this.#publish({ source: fallback });
        this.#hooks.onDeviceUnavailable?.(dropped);
        let again: Promise<MediaStream>;
        try {
          again = this.#request(fallback, true);
        } catch (e2) {
          await this.#failRequest(gen, e2, fallback);
          return;
        }
        await this.#afterRequest(gen, again, fallback, true);
        return;
      }
      if (mapped.domName === "OverconstrainedError") {
        this.#fail({ code: "DEVICE_UNAVAILABLE", domName: mapped.domName, message: mapped.message }, source);
        return;
      }
      this.#fail(mapped, source);
      return;
    }
    if (gen !== this.#generation || this.#view.state !== "requesting") {
      stopAll(stream); // arrived after stop(): never attached
      return;
    }
    const audio = stream.getAudioTracks();
    for (const v of stream.getVideoTracks()) {
      try {
        v.stop();
      } catch {
        /* ignore */
      }
    }
    const track = audio[0];
    if (!track) {
      stopAll(stream);
      this.#fail({ code: "NO_AUDIO_TRACK", domName: null, message: "the captured stream has no audio track" }, source);
      return;
    }
    try {
      await this.#graph.ensureContext();
    } catch (e) {
      if (gen === this.#generation) {
        stopAll(stream);
        this.#fail(graphError(e, "AUDIO_CONTEXT_FAILED"), source);
      } else stopAll(stream);
      return;
    }
    if (gen !== this.#generation || this.#view.state !== "requesting") {
      stopAll(stream);
      return;
    }
    try {
      await this.#graph.attach(this.id, stream, (pcm) => this.#onFrame(gen, pcm));
    } catch (e) {
      stopAll(stream);
      if (gen === this.#generation) this.#fail(graphError(e, "WORKLET_LOAD_FAILED"), source);
      return;
    }
    if (gen !== this.#generation || this.#view.state !== "requesting") {
      await this.#graph.detach(this.id);
      stopAll(stream);
      return;
    }
    this.#stream = stream;
    this.#track = track;
    this.#frameGen = gen;
    this.#listen(track, gen);
    this.#publish({ state: "live", trackLabel: track.label || null, startedAtMs: this.#clock.nowMs(), signal: track.muted ? "silent" : "unknown" });
  }

  #failRequest(gen: number, e: unknown, source: LaneSource): Promise<void> {
    if (gen !== this.#generation) return Promise.resolve();
    const err = isLaneErrorShape(e) ? e : mapDomException(e);
    this.#fail(err, source);
    return Promise.resolve();
  }

  #fail(error: LaneError, _source: LaneSource): void {
    this.#publish({ state: "error", error, stopReason: null, startedAtMs: null });
    const reason = guidanceReasonFor(error.code);
    if (reason) this.#hooks.onGuidance?.(reason);
  }

  #listen(track: MediaStreamTrack, gen: number): void {
    const onEnded = () => {
      if (gen !== this.#generation) return;
      const reason: StopReason = this.#view.source.kind === "display" ? "ended_by_browser" : "device_lost";
      void this.#teardown(reason);
    };
    const onMute = () => {
      if (gen === this.#generation && this.#view.state === "live") this.#publish({ signal: "silent" });
    };
    const onUnmute = () => {
      if (gen === this.#generation && this.#view.state === "live") {
        this.#quietMs = 0;
        this.#publish({ signal: "signal" });
      }
    };
    track.addEventListener("ended", onEnded);
    track.addEventListener("mute", onMute);
    track.addEventListener("unmute", onUnmute);
    this.#trackListeners = [
      () => track.removeEventListener("ended", onEnded),
      () => track.removeEventListener("mute", onMute),
      () => track.removeEventListener("unmute", onUnmute),
    ];
  }

  /** Total and idempotent. A stream that arrives after this call is stopped, never attached. */
  async stop(reason: StopReason = "user"): Promise<void> {
    const st = this.#view.state;
    if (st === "requesting") {
      this.#generation++;
      this.#publish({ state: "stopped", stopReason: reason, startedAtMs: null });
      return;
    }
    if (st !== "live") return;
    await this.#teardown(reason);
  }

  async #teardown(reason: StopReason): Promise<void> {
    if (this.#view.state !== "live") return;
    this.#generation++;
    for (const off of this.#trackListeners) off();
    this.#trackListeners = [];
    const stream = this.#stream;
    this.#stream = null;
    this.#track = null;
    // detach flushes the worklet's partial frame through the (now closed) generation; flush the segmenter after it
    try {
      await this.#graph.detach(this.id);
    } catch {
      /* ignore */
    }
    this.#frameGen = -1;
    this.#flushSegmenter();
    if (stream) stopAll(stream);
    this.#level = 0;
    this.#hooks.onLevel?.(0);
    this.#publish({ state: "stopped", stopReason: reason, signal: "unknown" });
  }

  #flushSegmenter(): void {
    const tMs = this.#frameTime();
    const { state, segment } = segmenterFlush(this.#seg, tMs, this.#speaker(), this.#segCfg);
    this.#seg = state;
    this.#hooks.onFlush?.();
    if (segment) this.#emitSegment(segment);
  }

  #frameTime(): number {
    return (this.#view.startedAtMs ?? 0) + this.#frameIndex * FRAME_MS;
  }

  /** Frames keep flowing while detach() flushes the worklet; #frameGen stays open until the flush is done. */
  #onFrame(gen: number, pcm: Float32Array): void {
    if (gen !== this.#frameGen) return;
    const t = this.#frameTime();
    this.#frameIndex++;
    const r = segmenterStep(this.#seg, pcm, t, this.#speaker(), this.#segCfg, this.#vadCfg);
    this.#seg = r.state;
    if (this.#view.state === "live") {
      this.#level = levelStep(this.#level, r.rmsDb);
      this.#hooks.onLevel?.(this.#level);
      // no-signal detection: published only on change
      if (r.rmsDb > SILENT_BELOW_DB) {
        this.#quietMs = 0;
        if (this.#view.signal !== "signal" && (r.speech || !this.#isMuted())) this.#publish({ signal: "signal" });
      } else {
        this.#quietMs += FRAME_MS;
        if (this.#quietMs >= SILENT_AFTER_MS && this.#view.signal !== "silent") this.#publish({ signal: "silent" });
      }
    }
    if (r.segment) this.#emitSegment(r.segment);
  }

  #isMuted(): boolean {
    return this.#track?.muted === true;
  }

  #emitSegment(segment: Segment): void {
    this.#publish({ segmentsClosed: this.#view.segmentsClosed + 1 });
    this.#hooks.onSegment?.(segment);
  }

  #publish(patch: Partial<LaneView>): void {
    this.#view = { ...this.#view, ...patch };
    this.#hooks.onView?.(this.#view);
  }
}

/** Stops every track that is still live (a track stopped once is not stopped again). */
function stopAll(stream: MediaStream): void {
  for (const t of stream.getTracks()) {
    if (t.readyState === "ended") continue;
    try {
      t.stop();
    } catch {
      /* ignore */
    }
  }
}

function laneError(code: LaneErrorCode, domName: string | null, message: string): LaneError {
  return { code, domName, message };
}

function isLaneErrorShape(e: unknown): e is LaneError {
  return typeof e === "object" && e !== null && typeof (e as LaneError).code === "string" && (e as LaneError).code in LANE_ERROR && "message" in (e as object);
}

function graphError(e: unknown, fallback: "AUDIO_CONTEXT_FAILED" | "WORKLET_LOAD_FAILED"): LaneError {
  if (e instanceof GraphError) return { code: e.code, domName: null, message: e.message };
  const m = mapDomException(e);
  return { code: fallback, domName: m.domName, message: m.message };
}

/** Which errors open the guidance panel by themselves (design §7.2 table). */
export function guidanceReasonFor(code: LaneErrorCode): GuidanceReason | null {
  switch (code) {
    case "NO_AUDIO_TRACK":
      return "no_audio_track";
    case "PERMISSION_DENIED":
      return "permission_denied";
    case "UNSUPPORTED":
    case "INSECURE_CONTEXT":
      return "unsupported";
    case "NO_DEVICE":
      return "no_device";
    default:
      return null;
  }
}
