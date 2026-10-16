// exmap/src/web/audio/dsp/graph.ts — the Web Audio graph (design §7.3): one AudioContext at 16 kHz (a default-rate
// context plus resampleTo16k() when 16 kHz is refused), the worklet module loaded once per context, and per lane a
// MediaStreamAudioSourceNode → AudioWorkletNode("exmap-pcm-framer") with no output (exmap never creates an echo path).
// The browser classes are injected so the graph is unit-tested with fakes.
import { GraphError } from "../errors.js";
import type { CaptureLaneId } from "../types.js";
import { resampleTo16k, TARGET_RATE } from "./resample.js";
import { FRAME_SAMPLES } from "./vad.js";

export type FrameHandler = (pcm: Float32Array) => void;

export interface AudioGraph {
  ensureContext(): Promise<void>;
  /** Frames (320 samples, mono, 16 kHz) reach onFrame until detach() resolves. */
  attach(lane: CaptureLaneId, stream: MediaStream, onFrame: FrameHandler): Promise<void>;
  /** Flushes the worklet's partial frame through onFrame, then disconnects. Idempotent. */
  detach(lane: CaptureLaneId): Promise<void>;
  readonly sampleRate: number | null;
  dispose(): void;
}

/* ───── the browser surface, narrowed so tests can fake it ───── */
export interface WorkletPortLike {
  postMessage(msg: unknown): void;
  onmessage: ((ev: { data: unknown }) => void) | null;
  close?(): void;
}
export interface WorkletNodeLike {
  readonly port: WorkletPortLike;
  disconnect(): void;
}
export interface SourceNodeLike {
  connect(node: WorkletNodeLike): unknown;
  disconnect(): void;
}
export interface AudioContextLike {
  readonly state: "suspended" | "running" | "closed" | string;
  readonly sampleRate: number;
  readonly audioWorklet: { addModule(url: string): Promise<void> };
  resume(): Promise<void>;
  close(): Promise<void>;
  createMediaStreamSource(stream: MediaStream): SourceNodeLike;
}

export interface GraphDeps {
  createContext?: (opts: { sampleRate?: number; latencyHint?: "playback" | "interactive" }) => AudioContextLike;
  createWorkletNode?: (ctx: AudioContextLike, name: string) => WorkletNodeLike;
  workletUrl?: string;
  flushTimeoutMs?: number;
}

export const WORKLET_URL = "/pcm-worklet.js";
export const WORKLET_NAME = "exmap-pcm-framer";

function defaultCreateContext(opts: { sampleRate?: number; latencyHint?: "playback" | "interactive" }): AudioContextLike {
  return new AudioContext(opts) as unknown as AudioContextLike;
}

function defaultCreateWorkletNode(ctx: AudioContextLike, name: string): WorkletNodeLike {
  return new AudioWorkletNode(ctx as unknown as BaseAudioContext, name, {
    numberOfInputs: 1,
    numberOfOutputs: 0,
    channelCount: 1,
    channelCountMode: "explicit",
    channelInterpretation: "speakers",
  }) as unknown as WorkletNodeLike;
}

interface LaneNodes {
  source: SourceNodeLike;
  node: WorkletNodeLike;
  onFrame: FrameHandler;
  flushed: (() => void) | null;
}

export class WebAudioGraph implements AudioGraph {
  #ctx: AudioContextLike | null = null;
  #moduleLoaded: Promise<void> | null = null;
  #lanes = new Map<CaptureLaneId, LaneNodes>();
  readonly #createContext: NonNullable<GraphDeps["createContext"]>;
  readonly #createWorkletNode: NonNullable<GraphDeps["createWorkletNode"]>;
  readonly #workletUrl: string;
  readonly #flushTimeoutMs: number;
  addModuleCalls = 0;

  constructor(deps: GraphDeps = {}) {
    this.#createContext = deps.createContext ?? defaultCreateContext;
    this.#createWorkletNode = deps.createWorkletNode ?? defaultCreateWorkletNode;
    this.#workletUrl = deps.workletUrl ?? WORKLET_URL;
    this.#flushTimeoutMs = deps.flushTimeoutMs ?? 500;
  }

  get sampleRate(): number | null {
    return this.#ctx?.sampleRate ?? null;
  }

  get context(): AudioContextLike | null {
    return this.#ctx;
  }

  async ensureContext(): Promise<void> {
    if (!this.#ctx || this.#ctx.state === "closed") {
      this.#moduleLoaded = null;
      try {
        this.#ctx = this.#createContext({ sampleRate: TARGET_RATE, latencyHint: "playback" });
      } catch (e) {
        if (isDomName(e, "NotSupportedError")) {
          try {
            this.#ctx = this.#createContext({ latencyHint: "playback" });
          } catch (e2) {
            throw new GraphError("AUDIO_CONTEXT_FAILED", messageOf(e2));
          }
        } else {
          throw new GraphError("AUDIO_CONTEXT_FAILED", messageOf(e));
        }
      }
    }
    const ctx = this.#ctx;
    try {
      await ctx.resume();
    } catch (e) {
      throw new GraphError("AUDIO_CONTEXT_FAILED", messageOf(e));
    }
    if (ctx.state === "suspended") throw new GraphError("AUDIO_CONTEXT_FAILED", "AudioContext did not resume — click Start again");
    if (!this.#moduleLoaded) {
      this.addModuleCalls++;
      this.#moduleLoaded = ctx.audioWorklet.addModule(this.#workletUrl).catch((e: unknown) => {
        this.#moduleLoaded = null;
        throw new GraphError("WORKLET_LOAD_FAILED", messageOf(e));
      });
    }
    await this.#moduleLoaded;
  }

  async attach(lane: CaptureLaneId, stream: MediaStream, onFrame: FrameHandler): Promise<void> {
    const ctx = this.#ctx;
    if (!ctx) throw new GraphError("AUDIO_CONTEXT_FAILED", "ensureContext() was not called");
    if (this.#lanes.has(lane)) await this.detach(lane);
    let source: SourceNodeLike;
    let node: WorkletNodeLike;
    try {
      source = ctx.createMediaStreamSource(stream);
      node = this.#createWorkletNode(ctx, WORKLET_NAME);
    } catch (e) {
      throw new GraphError("WORKLET_LOAD_FAILED", messageOf(e));
    }
    const rate = ctx.sampleRate;
    const entry: LaneNodes = { source, node, onFrame, flushed: null };
    node.port.onmessage = (ev) => {
      const data = ev.data as { type?: string; pcm?: Float32Array } | null;
      if (!data || typeof data !== "object") return;
      if (data.type === "frame" && data.pcm instanceof Float32Array) {
        let pcm = data.pcm;
        if (rate !== TARGET_RATE) pcm = fitFrame(resampleTo16k(pcm, rate));
        entry.onFrame(pcm);
      } else if (data.type === "flushed") {
        entry.flushed?.();
        entry.flushed = null;
      }
    };
    try {
      source.connect(node);
    } catch (e) {
      throw new GraphError("WORKLET_LOAD_FAILED", messageOf(e));
    }
    this.#lanes.set(lane, entry);
  }

  async detach(lane: CaptureLaneId): Promise<void> {
    const entry = this.#lanes.get(lane);
    if (!entry) return;
    this.#lanes.delete(lane);
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        entry.flushed = null;
        resolve();
      }, this.#flushTimeoutMs);
      entry.flushed = () => {
        clearTimeout(timer);
        resolve();
      };
      try {
        entry.node.port.postMessage({ type: "flush" });
      } catch {
        clearTimeout(timer);
        resolve();
      }
    });
    try {
      entry.source.disconnect();
    } catch {
      /* already disconnected */
    }
    try {
      entry.node.disconnect();
      entry.node.port.onmessage = null;
      entry.node.port.close?.();
    } catch {
      /* ignore */
    }
  }

  dispose(): void {
    for (const lane of [...this.#lanes.keys()]) void this.detach(lane);
    const ctx = this.#ctx;
    this.#ctx = null;
    this.#moduleLoaded = null;
    if (ctx && ctx.state !== "closed") void ctx.close().catch(() => undefined);
  }
}

/** A resampled frame is padded or trimmed to exactly 320 samples so the segmenter's arithmetic holds. */
function fitFrame(pcm: Float32Array): Float32Array {
  if (pcm.length === FRAME_SAMPLES) return pcm;
  const out = new Float32Array(FRAME_SAMPLES);
  out.set(pcm.subarray(0, Math.min(pcm.length, FRAME_SAMPLES)));
  return out;
}

function isDomName(e: unknown, name: string): boolean {
  return typeof e === "object" && e !== null && (e as { name?: unknown }).name === name;
}

function messageOf(e: unknown): string {
  if (typeof e === "object" && e !== null && "message" in e) return String((e as { message: unknown }).message);
  return String(e);
}
