// exmap/src/web/audio/react/ManualInput.tsx — type or paste an utterance (design §7.4). Enter submits, Shift+Enter
// inserts a newline; tStartMs = the first keystroke into an empty box; an empty speaker field is recorded as null.
import { useState } from "react";
import type { AudioController } from "../controller.js";
import type { SessionClock, SpeakerLabels, WireLane } from "../types.js";
import { useAudioController } from "./useAudioController.js";

export interface ManualInputProps {
  controller: AudioController;
  /** Default: controller.clock and the controller's live speaker labels ({ controller } alone is enough). */
  clock?: SessionClock;
  speakers?: SpeakerLabels;
}

const LANE_OPTIONS: Array<{ value: WireLane; label: string }> = [
  { value: "manual", label: "Typed" },
  { value: "me", label: "Me" },
  { value: "remote", label: "Call" },
];

export function ManualInput({ controller, clock: clockProp, speakers: speakersProp }: ManualInputProps) {
  const state = useAudioController(controller);
  const clock = clockProp ?? controller.clock;
  const speakers = speakersProp ?? state.speakers;
  const [text, setText] = useState("");
  const [lane, setLane] = useState<WireLane>("manual");
  const [speaker, setSpeaker] = useState<string>("");
  const [speakerTouched, setSpeakerTouched] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);

  const laneDefault = lane === "remote" ? speakers.remote : speakers.me;
  const effectiveSpeaker = speakerTouched ? speaker : (laneDefault ?? "");
  const canSubmit = text.trim().length > 0;

  const submit = () => {
    if (!canSubmit) return;
    const ok = controller.submitManual(text, lane, effectiveSpeaker.trim() || null, startedAt);
    if (ok) {
      setText("");
      setStartedAt(null);
    }
  };

  return (
    <form
      data-testid="manual-input-form"
      className="flex flex-col gap-1 border-t p-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="manual-input" className="text-xs font-medium">
        Type an utterance
      </label>
      <textarea
        id="manual-input"
        data-testid="manual-input"
        className="min-h-[3rem] rounded border p-1 text-sm"
        value={text}
        placeholder="Type or paste what was said, then press Enter"
        onChange={(e) => {
          if (text.length === 0 && e.target.value.length > 0) setStartedAt(clock.nowMs());
          setText(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label>
          Lane{" "}
          <select data-testid="manual-lane" className="rounded border px-1" value={lane} onChange={(e) => setLane(e.target.value as WireLane)}>
            {LANE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Speaker{" "}
          <input
            data-testid="manual-speaker"
            className="rounded border px-1"
            value={effectiveSpeaker}
            placeholder={lane === "remote" ? "Call" : lane === "me" ? "Me" : "Typed"}
            onChange={(e) => {
              setSpeakerTouched(true);
              setSpeaker(e.target.value);
            }}
          />
        </label>
        <button type="submit" data-testid="manual-submit" className="rounded bg-slate-900 px-2 py-0.5 text-white disabled:opacity-50" disabled={!canSubmit}>
          Add
        </button>
      </div>
    </form>
  );
}
