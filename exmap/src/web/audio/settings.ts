// exmap/src/web/audio/settings.ts — AudioSettings defaults, validation and persistence (design §7.4, §7.7).
// Persisted under localStorage["exmap.audio.v1"]; a value that fails validation falls back to the default field by field.
import type { AudioSettings, LaneSource, StorageLike, WhisperDtype, WhisperModelId } from "./types.js";

export const SETTINGS_KEY = "exmap.audio.v1";
export const MODEL_SEEN_KEY = (model: string): string => `exmap.audio.modelSeen.${model}`;
export const WEBSPEECH_SEEN_KEY = "exmap.audio.webSpeechSeen";

export const WHISPER_MODELS: readonly WhisperModelId[] = ["onnx-community/whisper-base.en", "onnx-community/whisper-tiny.en"] as const;
export const WHISPER_DTYPES: readonly WhisperDtype[] = ["q8", "q4"] as const;

/** Approximate download sizes (brief §6; labelled "approx" in the UI). */
export const MODEL_INFO: Record<WhisperModelId, { short: string; approxMb: Record<WhisperDtype, number> }> = {
  "onnx-community/whisper-base.en": { short: "base.en", approxMb: { q8: 77, q4: 143 } },
  "onnx-community/whisper-tiny.en": { short: "tiny.en", approxMb: { q8: 44, q4: 60 } },
};

export function modelShortName(model: WhisperModelId | string): string {
  return (MODEL_INFO as Record<string, { short: string }>)[model]?.short ?? model.replace(/^.*\//, "");
}

export function defaultWebSpeechLang(language: string | undefined = typeof navigator === "undefined" ? undefined : navigator.language): string {
  return language && /^en/i.test(language) ? language : "en-US";
}

export function defaultSettings(): AudioSettings {
  return {
    provider: { remote: "local-whisper", me: "local-whisper" },
    remoteSource: { kind: "display" },
    deviceId: { me: null, remote: null },
    whisperModel: "onnx-community/whisper-base.en",
    whisperDtype: "q8",
    whisperDevice: "auto",
    webSpeechLang: defaultWebSpeechLang(),
  };
}

function isLaneSource(v: unknown): v is LaneSource {
  if (typeof v !== "object" || v === null) return false;
  const o = v as { kind?: unknown; deviceId?: unknown };
  if (o.kind === "display") return true;
  return o.kind === "device" && (o.deviceId === null || typeof o.deviceId === "string");
}

/** Validates an unknown value field by field against the defaults. */
export function normalizeSettings(raw: unknown, base: AudioSettings = defaultSettings()): AudioSettings {
  const out: AudioSettings = { ...base, provider: { ...base.provider }, deviceId: { ...base.deviceId } };
  if (typeof raw !== "object" || raw === null) return out;
  const r = raw as Record<string, unknown>;
  const provider = r["provider"];
  if (typeof provider === "object" && provider !== null) {
    const p = provider as Record<string, unknown>;
    if (p["remote"] === "local-whisper" || p["remote"] === null) out.provider.remote = p["remote"];
    if (p["me"] === "local-whisper" || p["me"] === "web-speech" || p["me"] === null) out.provider.me = p["me"];
  }
  if (isLaneSource(r["remoteSource"])) out.remoteSource = r["remoteSource"];
  const deviceId = r["deviceId"];
  if (typeof deviceId === "object" && deviceId !== null) {
    const d = deviceId as Record<string, unknown>;
    if (typeof d["me"] === "string" || d["me"] === null) out.deviceId.me = d["me"];
    if (typeof d["remote"] === "string" || d["remote"] === null) out.deviceId.remote = d["remote"];
  }
  if ((WHISPER_MODELS as readonly string[]).includes(r["whisperModel"] as string)) out.whisperModel = r["whisperModel"] as WhisperModelId;
  if ((WHISPER_DTYPES as readonly string[]).includes(r["whisperDtype"] as string)) out.whisperDtype = r["whisperDtype"] as WhisperDtype;
  if (r["whisperDevice"] === "auto" || r["whisperDevice"] === "wasm") out.whisperDevice = r["whisperDevice"];
  if (typeof r["webSpeechLang"] === "string" && r["webSpeechLang"].length > 0) out.webSpeechLang = r["webSpeechLang"];
  return out;
}

export function loadSettings(storage: StorageLike | null | undefined): AudioSettings {
  if (!storage) return defaultSettings();
  try {
    const raw = storage.getItem(SETTINGS_KEY);
    if (!raw) return defaultSettings();
    return normalizeSettings(JSON.parse(raw));
  } catch {
    return defaultSettings();
  }
}

export function saveSettings(storage: StorageLike | null | undefined, settings: AudioSettings): void {
  if (!storage) return;
  try {
    storage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    /* storage may be unavailable (private mode); settings then live for the page only */
  }
}

export function readFlag(storage: StorageLike | null | undefined, key: string): boolean {
  if (!storage) return false;
  try {
    return storage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function writeFlag(storage: StorageLike | null | undefined, key: string, value: boolean): void {
  if (!storage) return;
  try {
    if (value) storage.setItem(key, "1");
    else storage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/** A Map-backed StorageLike for tests and for pages whose storage throws. */
export function memoryStorage(initial: Record<string, string> = {}): StorageLike & { readonly map: Map<string, string> } {
  const map = new Map<string, string>(Object.entries(initial));
  return {
    map,
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => {
      map.set(k, String(v));
    },
    removeItem: (k) => {
      map.delete(k);
    },
  };
}

/** The page's localStorage when it is usable, else null (private mode and sandboxed frames throw on access). */
export function browserStorage(kind: "local" | "session" = "local"): StorageLike | null {
  try {
    if (typeof window === "undefined") return null;
    const s = kind === "local" ? window.localStorage : window.sessionStorage;
    if (!s) return null;
    return s;
  } catch {
    return null;
  }
}
