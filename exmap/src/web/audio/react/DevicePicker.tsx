// exmap/src/web/audio/react/DevicePicker.tsx — the audio input select (design §7.2). Labels are empty until the
// microphone was allowed once, so an "Allow microphone to list devices" button primes them.
import { useCallback, useEffect, useState } from "react";
import type { AudioController } from "../controller.js";
import { labelsAvailable, listAudioInputs, onDeviceChange, primeDeviceLabels, type AudioInputInfo } from "../lanes/devices.js";
import type { CaptureLaneId, MediaDevicesLike } from "../types.js";

export function DevicePicker({ controller, lane, media, disabled, value }: { controller: AudioController; lane: CaptureLaneId; media: MediaDevicesLike | null; disabled: boolean; value: string | null }) {
  const [inputs, setInputs] = useState<AudioInputInfo[]>([]);
  const refresh = useCallback(() => {
    void listAudioInputs(media).then(setInputs);
  }, [media]);
  useEffect(() => {
    refresh();
    return onDeviceChange(media, refresh);
  }, [media, refresh]);
  const labelled = labelsAvailable(inputs);
  return (
    <span className="inline-flex items-center gap-1">
      <label className="text-xs">
        <span className="sr-only">{lane === "remote" ? "Call audio device" : "Microphone"}</span>
        <select
          data-testid={`device-select-${lane}`}
          className="rounded border px-1 py-0.5 text-xs"
          disabled={disabled}
          title={disabled ? "Stop the lane to change this" : undefined}
          value={value ?? ""}
          onChange={(e) => controller.updateSettings({ deviceId: { ...controller.getState().settings.deviceId, [lane]: e.target.value || null } })}
        >
          <option value="">Default device</option>
          {inputs.map((d) => (
            <option key={d.deviceId} value={d.deviceId}>
              {d.label || `(unnamed device ${d.deviceId.slice(0, 6)})`}
              {d.isDefault ? " (default)" : ""}
            </option>
          ))}
        </select>
      </label>
      {!labelled && media ? (
        <button type="button" className="text-xs underline" onClick={() => void primeDeviceLabels(media).then(setInputs)}>
          Allow microphone to list devices
        </button>
      ) : null}
    </span>
  );
}
