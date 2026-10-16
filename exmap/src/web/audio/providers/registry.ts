// exmap/src/web/audio/providers/registry.ts — the provider table and factory (design §7.4). A server-side STT provider
// is the documented seam: a fifth TranscriptionProvider id in core first, a registry entry here, isLocal: false if
// audio leaves the machine — not built in v1.
import type { AudioSettings, CaptureLaneId, ProviderId, ProviderMode, StorageLike, TranscriptionProvider } from "../types.js";
import { LocalWhisperProvider, type LocalWhisperDeps, type WorkerLike } from "./localWhisper.js";
import { ManualProvider } from "./manual.js";
import { ReplayProvider, type ReplayTimers } from "./replay.js";
import { speechRecognitionCtor, WEB_SPEECH_LABEL, WebSpeechProvider, type SpeechRecognitionCtor, type WebSpeechDeps } from "./webSpeech.js";
import { readFlag, WEBSPEECH_SEEN_KEY } from "../settings.js";

export interface ProviderInfo {
  label: string;
  isLocal: boolean;
  lanes: CaptureLaneId[];
  mode: ProviderMode;
}

export const PROVIDERS: Record<ProviderId, ProviderInfo> = {
  "local-whisper": { label: "Whisper (local)", isLocal: true, lanes: ["remote", "me"], mode: "segment" },
  "web-speech": { label: WEB_SPEECH_LABEL, isLocal: false, lanes: ["me"], mode: "push" },
  manual: { label: "Typed", isLocal: true, lanes: [], mode: "push" },
  replay: { label: "Replay", isLocal: true, lanes: ["remote", "me"], mode: "push" },
};

export interface ProviderDeps {
  createWorker?: () => WorkerLike;
  speechRecognitionCtor?: SpeechRecognitionCtor | null;
  storage?: StorageLike | null;
  replayTimers?: ReplayTimers;
  whisper?: Partial<Pick<LocalWhisperDeps, "loadTimeoutMs" | "timers" | "numThreads" | "wasmPaths" | "onReady">>;
  webSpeech?: Partial<Pick<WebSpeechDeps, "timers" | "onError" | "restartDelayMs" | "consentGiven">>;
}

export function createProvider(id: ProviderId, settings: AudioSettings, deps: ProviderDeps = {}): TranscriptionProvider {
  switch (id) {
    case "local-whisper": {
      const d: LocalWhisperDeps = { model: settings.whisperModel, dtype: settings.whisperDtype, device: settings.whisperDevice, ...deps.whisper };
      if (deps.createWorker) d.createWorker = deps.createWorker;
      return new LocalWhisperProvider(d);
    }
    case "web-speech": {
      const ctor = deps.speechRecognitionCtor === undefined ? speechRecognitionCtor() : deps.speechRecognitionCtor;
      const storage = deps.storage ?? null;
      return new WebSpeechProvider({
        ctor,
        lang: settings.webSpeechLang,
        consentGiven: deps.webSpeech?.consentGiven ?? (() => readFlag(storage, WEBSPEECH_SEEN_KEY)),
        ...(deps.webSpeech?.timers ? { timers: deps.webSpeech.timers } : {}),
        ...(deps.webSpeech?.onError ? { onError: deps.webSpeech.onError } : {}),
        ...(deps.webSpeech?.restartDelayMs !== undefined ? { restartDelayMs: deps.webSpeech.restartDelayMs } : {}),
      });
    }
    case "manual":
      return new ManualProvider();
    case "replay":
      return new ReplayProvider(deps.replayTimers ? { timers: deps.replayTimers } : {});
  }
}

export function providerLabelFor(id: ProviderId | null, declined = false): string {
  if (declined) return "Capture only (download declined)";
  if (id === null) return "Capture only";
  if (id === "web-speech") return "Web Speech (not local)";
  return PROVIDERS[id].label;
}
