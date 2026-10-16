// exmap/src/web/components/SettingsDialog.tsx — settings and the actor (design §10.7): the name stamped on every
// change, the classifier status from /api/config (never a key field), the audio provider selects, the data location.
import { useEffect, useState } from "react";
import type { ConfigResponse } from "../../core/types.js";
import type { AudioSettings, WhisperDtype, WhisperModelId } from "../audio/types.js";
import { Drawer } from "./Drawer.js";

export interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
  userName: string;
  onSaveName: (name: string) => Promise<void> | void;
  config: ConfigResponse | null;
  /** The prompt shown when an act was refused for lack of a name. */
  prompt?: string | null;
  audio?: { settings: AudioSettings; update(patch: Partial<AudioSettings>): void; locked: boolean } | null;
  returnFocusTo?: HTMLElement | null;
}

export const WHISPER_MODEL_OPTIONS: Array<{ id: WhisperModelId; label: string }> = [
  { id: "onnx-community/whisper-base.en", label: "base.en (approx 77 MB at q8)" },
  { id: "onnx-community/whisper-tiny.en", label: "tiny.en (approx 44 MB at q8)" },
];
export const WHISPER_DTYPE_OPTIONS: WhisperDtype[] = ["q8", "q4"];

export function SettingsDialog({ open, onClose, userName, onSaveName, config, prompt = null, audio = null, returnFocusTo }: SettingsDialogProps) {
  const [name, setName] = useState(userName);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) setName(userName);
  }, [open, userName]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSaveName(name.trim());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer open={open} title="Settings" testId="settings-dialog" onClose={onClose} returnFocusTo={returnFocusTo} variant="dialog">
      {prompt ? (
        <p role="alert" data-testid="settings-prompt" className="rounded border border-amber-700 bg-amber-50 p-2 text-sm text-amber-950">
          {prompt}
        </p>
      ) : null}
      <form
        className="flex flex-col gap-2 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <label className="flex flex-col gap-1">
          Your name
          <input data-testid="settings-name" className="rounded border border-slate-400 px-2 py-1" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        </label>
        <p className="text-xs text-slate-700">This name is stamped on every change you make and is the default speaker label for your microphone.</p>
        <button type="submit" data-testid="settings-save" className="self-start rounded border border-slate-700 bg-slate-800 px-3 py-1 text-white disabled:opacity-50" disabled={saving || name.trim().length === 0}>
          Save name{saving ? " (pending…)" : ""}
        </button>
        {error ? (
          <p role="alert" className="text-xs text-red-800">
            {error}
          </p>
        ) : null}
      </form>

      <section className="flex flex-col gap-1 text-sm" aria-labelledby="settings-classifier-heading">
        <h3 id="settings-classifier-heading" className="font-semibold">
          Classifier
        </h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs" data-testid="classifier-status">
          <dt>provider</dt>
          <dd data-testid="classifier-provider">{config?.classifier.provider ?? "unknown"}</dd>
          <dt>reason</dt>
          <dd data-testid="classifier-reason">{config?.classifier.reason ?? "config not loaded"}</dd>
          <dt>model</dt>
          <dd data-testid="classifier-model">{config?.classifier.model ?? "none"}</dd>
          <dt>credentials</dt>
          <dd>{config?.classifier.credentials ?? "unknown"}</dd>
          <dt>last error</dt>
          <dd data-testid="classifier-last-error">{config?.classifier.last_error ? `${config.classifier.last_error.code}: ${config.classifier.last_error.message} (${config.classifier.last_error.at})` : "none"}</dd>
        </dl>
        <p className="text-xs text-slate-700">Set ANTHROPIC_API_KEY before starting to use Claude; without it the offline rules classifier is used.</p>
      </section>

      <section className="flex flex-col gap-1 text-sm" aria-labelledby="settings-audio-heading">
        <h3 id="settings-audio-heading" className="font-semibold">
          Audio providers
        </h3>
        {audio ? (
          <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              Whisper model
              <select data-testid="settings-whisper-model" className="rounded border border-slate-400 p-1" value={audio.settings.whisperModel} disabled={audio.locked} onChange={(e) => audio.update({ whisperModel: e.target.value as WhisperModelId })}>
                {WHISPER_MODEL_OPTIONS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              Quantisation
              <select data-testid="settings-whisper-dtype" className="rounded border border-slate-400 p-1" value={audio.settings.whisperDtype} disabled={audio.locked} onChange={(e) => audio.update({ whisperDtype: e.target.value as WhisperDtype })}>
                {WHISPER_DTYPE_OPTIONS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            {audio.locked ? <p className="sm:col-span-2">Stop the live lanes to change the model.</p> : null}
          </div>
        ) : (
          <p className="text-xs text-slate-700">Audio settings are available on the session screen once the audio pipeline is loaded.</p>
        )}
      </section>

      <section className="flex flex-col gap-1 text-sm" aria-labelledby="settings-data-heading">
        <h3 id="settings-data-heading" className="font-semibold">
          Data
        </h3>
        <p className="text-xs">
          Sessions live under <code data-testid="settings-home">{config?.home ?? "(unknown until the server answers)"}</code> as append-only, hash-chained event files; nothing is deleted. The server listens on loopback only.
        </p>
      </section>
      <p className="text-xs text-slate-700" data-testid="settings-version">
        exmap {config?.version ?? ""}
      </p>
    </Drawer>
  );
}
