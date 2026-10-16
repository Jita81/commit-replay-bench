// exmap/src/web/audio/lanes/constraints.ts — the media requests (design §7.2). getDisplayMedia needs video: true
// (audio-only rejects in Chromium); the Chromium-only keys are widened locally since lib.dom does not carry them.
import type { CaptureLaneId } from "../types.js";

/** lib.dom's DisplayMediaStreamOptions plus Chromium's extensions. */
export interface DisplayMediaOptionsEx {
  audio: boolean | MediaTrackConstraints;
  video: boolean | MediaTrackConstraints;
  systemAudio?: "include" | "exclude";
  selfBrowserSurface?: "include" | "exclude";
  surfaceSwitching?: "include" | "exclude";
  monitorTypeSurfaces?: "include" | "exclude";
  preferCurrentTab?: boolean;
}

export const REMOTE_DISPLAY_OPTIONS: DisplayMediaOptionsEx = {
  audio: true,
  video: true, // audio-only rejects in Chromium
  systemAudio: "include",
  selfBrowserSurface: "exclude",
  surfaceSwitching: "include",
  monitorTypeSurfaces: "include",
  preferCurrentTab: false,
};

/** Microphone-style constraints: processing on for a real mic, off for a loopback device (the call audio is already clean). */
export function deviceConstraints(lane: CaptureLaneId, deviceId: string | null): MediaStreamConstraints {
  const processing = lane === "me";
  const audio: MediaTrackConstraints = {
    echoCancellation: processing,
    noiseSuppression: processing,
    autoGainControl: processing,
    channelCount: { ideal: 1 },
  };
  if (deviceId) audio.deviceId = { exact: deviceId };
  return { audio, video: false };
}
