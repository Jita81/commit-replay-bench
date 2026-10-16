// exmap/src/web/audio/lanes/devices.ts — audio input enumeration (design §7.2). Labels are empty until microphone
// permission was granted once; `primeDeviceLabels` asks for it, stops the tracks and lists again.
import type { MediaDevicesLike } from "../types.js";

export interface AudioInputInfo {
  deviceId: string;
  label: string;
  isDefault: boolean;
}

export function isDefault(deviceId: string): boolean {
  return deviceId === "default";
}

export async function listAudioInputs(media: MediaDevicesLike | null | undefined): Promise<AudioInputInfo[]> {
  if (!media || typeof media.enumerateDevices !== "function") return [];
  let devices: MediaDeviceInfo[];
  try {
    devices = await media.enumerateDevices();
  } catch {
    return [];
  }
  return devices
    .filter((d) => d.kind === "audioinput")
    .map((d) => ({ deviceId: d.deviceId, label: d.label ?? "", isDefault: isDefault(d.deviceId) }));
}

/** True when at least one input has a label (permission was granted at some point). */
export function labelsAvailable(inputs: AudioInputInfo[]): boolean {
  return inputs.some((d) => d.label.length > 0);
}

/** Asks for the microphone once so labels become visible, stops the tracks, lists again. */
export async function primeDeviceLabels(media: MediaDevicesLike): Promise<AudioInputInfo[]> {
  try {
    const stream = await media.getUserMedia({ audio: true });
    for (const t of stream.getTracks()) t.stop();
  } catch {
    /* denied: the list stays unlabelled; the picker says so */
  }
  return listAudioInputs(media);
}

export function onDeviceChange(media: MediaDevicesLike | null | undefined, cb: () => void): () => void {
  if (!media || typeof media.addEventListener !== "function") return () => undefined;
  media.addEventListener("devicechange", cb);
  return () => media.removeEventListener?.("devicechange", cb);
}
