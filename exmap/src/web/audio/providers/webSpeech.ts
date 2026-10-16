// exmap/src/web/audio/providers/webSpeech.ts — Chrome's Web Speech API on the mic lane (design §7.4). NOT local: the
// audio goes to the browser vendor; labelled as such everywhere and gated behind a consent flag. A push provider.
import { ProviderError } from "../errors.js";
import type { CaptureLaneId, ProviderContext, Segment, TranscribeResult, TranscriptionProvider } from "../types.js";

/* lib.dom does not declare SpeechRecognition in every TS version; the subset used is declared here. */
export interface SpeechRecognitionAlternativeLike {
  transcript: string;
  confidence: number;
}
export interface SpeechRecognitionResultLike {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}
export interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: { length: number; [index: number]: SpeechRecognitionResultLike };
}
export interface SpeechRecognitionErrorEventLike {
  error: string;
  message?: string;
}
export interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  lang: string;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  onstart?: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
export type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

export const WEB_SPEECH_LABEL = "Web Speech (not local — audio goes to the browser vendor)";
export const WEB_SPEECH_NOTICE = "Web Speech sends audio from your microphone to the browser vendor's speech service while the lane is live. exmap stores nothing from it, but the audio does leave this machine.";

export function speechRecognitionCtor(win: unknown = typeof window === "undefined" ? undefined : window): SpeechRecognitionCtor | null {
  if (!win || typeof win !== "object") return null;
  const w = win as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface WebSpeechDeps {
  ctor: SpeechRecognitionCtor | null;
  lang: string;
  consentGiven: () => boolean;
  timers?: { setTimeout(fn: () => void, ms: number): unknown; clearTimeout(h: unknown): void };
  onError?: (e: ProviderError) => void;
  restartDelayMs?: number;
}

const NETWORK_BACKOFF_MS = [1000, 2000, 4000, 8000];

export class WebSpeechProvider implements TranscriptionProvider {
  readonly id = "web-speech" as const;
  readonly label = WEB_SPEECH_LABEL;
  readonly isLocal = false;
  readonly lanes: CaptureLaneId[] = ["me"];
  readonly mode = "push" as const;
  readonly model = null;

  #deps: WebSpeechDeps;
  #rec: SpeechRecognitionLike | null = null;
  #ctx: ProviderContext | null = null;
  #started = false;
  #interimStartedAt = new Map<number, number>();
  #networkFailures = 0;
  #networkSurfaced = false;
  #restartTimer: unknown = null;
  #onAbort: (() => void) | null = null;

  constructor(deps: WebSpeechDeps) {
    this.#deps = deps;
  }

  get started(): boolean {
    return this.#started;
  }

  async start(ctx: ProviderContext): Promise<void> {
    if (!this.#deps.ctor) throw new ProviderError("WEB_SPEECH_UNSUPPORTED", "this browser has no SpeechRecognition");
    if (!this.#deps.consentGiven()) throw new ProviderError("WEB_SPEECH_DENIED", "consent not given");
    if (this.#started) return;
    this.#ctx = ctx;
    this.#started = true;
    this.#networkFailures = 0;
    this.#networkSurfaced = false;
    this.#onAbort = () => void this.stop({ force: true });
    ctx.signal.addEventListener("abort", this.#onAbort, { once: true });
    this.#open();
  }

  #open(): void {
    const Ctor = this.#deps.ctor;
    const ctx = this.#ctx;
    if (!Ctor || !ctx || !this.#started) return;
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.lang = this.#deps.lang;
    rec.onresult = (ev) => this.#onResult(ev);
    rec.onerror = (ev) => this.#onError(ev);
    rec.onend = () => this.#onEnd();
    this.#rec = rec;
    this.#interimStartedAt.clear();
    try {
      rec.start();
    } catch (e) {
      this.#fail(new ProviderError("WEB_SPEECH_DENIED", `start() threw: ${String((e as Error)?.message ?? e)}`));
    }
  }

  #onResult(ev: SpeechRecognitionEventLike): void {
    const ctx = this.#ctx;
    if (!ctx) return;
    const now = ctx.clock.nowMs();
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (!r) continue;
      const alt = r[0];
      const text = (alt?.transcript ?? "").trim();
      if (!r.isFinal) {
        if (!this.#interimStartedAt.has(i)) this.#interimStartedAt.set(i, now);
        ctx.onInterim?.("me", text.length > 0 ? text : null);
        continue;
      }
      ctx.onInterim?.("me", null);
      if (text.length === 0) continue;
      const started = this.#interimStartedAt.get(i);
      const conf = alt?.confidence;
      ctx.emit({
        text,
        lane: "me",
        speaker: ctx.speakers.get("me"),
        provider: "web-speech",
        model: null,
        isLocal: false,
        confidence: typeof conf === "number" && conf > 0 ? Math.round(Math.min(1, conf) * 100) / 100 : null,
        tStartMs: started ?? Math.max(0, now - 1000),
        tEndMs: now,
      });
      this.#interimStartedAt.delete(i);
    }
  }

  #onError(ev: SpeechRecognitionErrorEventLike): void {
    switch (ev.error) {
      case "not-allowed":
      case "service-not-allowed":
        this.#fail(new ProviderError("WEB_SPEECH_DENIED", ev.message || ev.error));
        return;
      case "audio-capture":
        this.#fail(new ProviderError("WEB_SPEECH_DENIED", "no microphone"));
        return;
      case "network": {
        this.#networkFailures++;
        if (!this.#networkSurfaced) {
          this.#networkSurfaced = true;
          this.#deps.onError?.(new ProviderError("WEB_SPEECH_NETWORK", ev.message || "the speech service could not be reached"));
        }
        return; // onend follows and restarts with backoff
      }
      case "no-speech":
      case "aborted":
      default:
        return; // silent restart on onend
    }
  }

  #onEnd(): void {
    this.#rec = null;
    this.#interimStartedAt.clear();
    if (!this.#started) return;
    const base = this.#deps.restartDelayMs ?? 250;
    const backoff = this.#networkFailures > 0 ? (NETWORK_BACKOFF_MS[Math.min(this.#networkFailures, NETWORK_BACKOFF_MS.length) - 1] ?? 8000) : base;
    const timers = this.#deps.timers ?? { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>) };
    this.#restartTimer = timers.setTimeout(() => {
      this.#restartTimer = null;
      if (this.#started) this.#open();
    }, backoff);
  }

  #fail(e: ProviderError): void {
    this.#started = false;
    this.#deps.onError?.(e);
    const rec = this.#rec;
    this.#rec = null;
    try {
      rec?.abort();
    } catch {
      /* ignore */
    }
    this.#ctx?.onInterim?.("me", null);
  }

  transcribe(_segment: Segment): Promise<TranscribeResult> {
    return Promise.reject(new ProviderError("NOT_SEGMENT_PROVIDER", "web-speech captures the microphone itself"));
  }

  async stop(opts: { force?: boolean } = {}): Promise<void> {
    this.#started = false;
    if (this.#restartTimer !== null) {
      const timers = this.#deps.timers ?? { setTimeout: () => null, clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>) };
      timers.clearTimeout(this.#restartTimer);
      this.#restartTimer = null;
    }
    const rec = this.#rec;
    this.#rec = null;
    try {
      if (opts.force) rec?.abort();
      else rec?.stop();
    } catch {
      /* ignore */
    }
    if (this.#onAbort && this.#ctx) this.#ctx.signal.removeEventListener("abort", this.#onAbort);
    this.#onAbort = null;
    this.#ctx?.onInterim?.("me", null);
    this.#interimStartedAt.clear();
  }
}
