// exmap/src/web/audio/errors.ts — lane / provider / post error codes and the DOMException mapping (design §7.2, §7.4).
import type { LaneError, LaneErrorCode, ProviderErrorCode } from "./types.js";

export const LANE_ERROR = {
  PERMISSION_DENIED: "PERMISSION_DENIED",
  NO_DEVICE: "NO_DEVICE",
  DEVICE_BUSY: "DEVICE_BUSY",
  DEVICE_UNAVAILABLE: "DEVICE_UNAVAILABLE",
  ABORTED: "ABORTED",
  NOT_ACTIVATED: "NOT_ACTIVATED",
  BAD_CONSTRAINTS: "BAD_CONSTRAINTS",
  INSECURE_CONTEXT: "INSECURE_CONTEXT",
  UNSUPPORTED: "UNSUPPORTED",
  NO_AUDIO_TRACK: "NO_AUDIO_TRACK",
  AUDIO_CONTEXT_FAILED: "AUDIO_CONTEXT_FAILED",
  WORKLET_LOAD_FAILED: "WORKLET_LOAD_FAILED",
  UNKNOWN: "UNKNOWN",
} as const satisfies Record<LaneErrorCode, LaneErrorCode>;

export const PROVIDER_ERROR = {
  NOT_SEGMENT_PROVIDER: "NOT_SEGMENT_PROVIDER",
  MODEL_LOAD_FAILED: "MODEL_LOAD_FAILED",
  TRANSCRIBE_FAILED: "TRANSCRIBE_FAILED",
  TRANSCRIBE_TIMEOUT: "TRANSCRIBE_TIMEOUT",
  WEBGPU_UNAVAILABLE: "WEBGPU_UNAVAILABLE",
  WEB_SPEECH_UNSUPPORTED: "WEB_SPEECH_UNSUPPORTED",
  WEB_SPEECH_NETWORK: "WEB_SPEECH_NETWORK",
  WEB_SPEECH_DENIED: "WEB_SPEECH_DENIED",
  REPLAY_FIXTURE_INVALID: "REPLAY_FIXTURE_INVALID",
  WORKER_CRASHED: "WORKER_CRASHED",
} as const satisfies Record<ProviderErrorCode, ProviderErrorCode>;

/** The human text the badge shows for each lane error code (the details disclosure shows domName/message verbatim). */
export const LANE_ERROR_TEXT: Record<LaneErrorCode, string> = {
  PERMISSION_DENIED: "permission denied or sharing cancelled",
  NO_DEVICE: "no input device found",
  DEVICE_BUSY: "the device is in use by another application",
  DEVICE_UNAVAILABLE: "the saved device is no longer available",
  ABORTED: "the request was aborted",
  NOT_ACTIVATED: "press Start again (the browser needs a click to share)",
  BAD_CONSTRAINTS: "the capture constraints were rejected",
  INSECURE_CONTEXT: "capture needs a secure context (open http://127.0.0.1)",
  UNSUPPORTED: "this browser cannot capture this source (use Chrome or Edge)",
  NO_AUDIO_TRACK: "the shared surface had no audio",
  AUDIO_CONTEXT_FAILED: "the audio engine could not start",
  WORKLET_LOAD_FAILED: "the audio framer could not load",
  UNKNOWN: "unknown capture error",
};

/** Thrown by CaptureLane.start()/setSource() when the call is illegal in the current state. */
export class LaneStateError extends Error {
  readonly state: string;
  constructor(action: string, state: string) {
    super(`${action} is not allowed while the lane is ${state}`);
    this.name = "LaneStateError";
    this.state = state;
  }
}

/** A graph failure with the lane code it maps to. */
export class GraphError extends Error {
  readonly code: "AUDIO_CONTEXT_FAILED" | "WORKLET_LOAD_FAILED";
  constructor(code: "AUDIO_CONTEXT_FAILED" | "WORKLET_LOAD_FAILED", message: string) {
    super(message);
    this.name = "GraphError";
    this.code = code;
  }
}

export class ProviderError extends Error {
  readonly code: ProviderErrorCode;
  readonly detail: string;
  constructor(code: ProviderErrorCode, detail = "") {
    super(detail ? `${code}: ${detail}` : code);
    this.name = "ProviderError";
    this.code = code;
    this.detail = detail;
  }
}

export class PostError extends Error {
  readonly code: "EMPTY_TEXT";
  constructor(code: "EMPTY_TEXT", detail = "") {
    super(detail ? `${code}: ${detail}` : code);
    this.name = "PostError";
    this.code = code;
  }
}

const DOM_NAME_TO_CODE: Record<string, LaneErrorCode> = {
  NotAllowedError: "PERMISSION_DENIED",
  NotFoundError: "NO_DEVICE",
  NotReadableError: "DEVICE_BUSY",
  OverconstrainedError: "DEVICE_UNAVAILABLE",
  AbortError: "ABORTED",
  InvalidStateError: "NOT_ACTIVATED",
  TypeError: "BAD_CONSTRAINTS",
  SecurityError: "INSECURE_CONTEXT",
  NotSupportedError: "UNSUPPORTED",
};

/** Maps a rejection of getUserMedia / getDisplayMedia by its `name`; the message is kept verbatim. */
export function mapDomException(e: unknown): LaneError {
  const name = typeof e === "object" && e !== null && "name" in e && typeof (e as { name: unknown }).name === "string" ? (e as { name: string }).name : null;
  const message =
    typeof e === "object" && e !== null && "message" in e && typeof (e as { message: unknown }).message === "string"
      ? (e as { message: string }).message
      : String(e);
  const code = (name && DOM_NAME_TO_CODE[name]) || "UNKNOWN";
  return { code, domName: name, message };
}

export function isProviderError(e: unknown, code?: ProviderErrorCode): e is ProviderError {
  return e instanceof ProviderError && (code === undefined || e.code === code);
}
