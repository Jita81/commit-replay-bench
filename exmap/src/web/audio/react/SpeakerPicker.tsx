// exmap/src/web/audio/react/SpeakerPicker.tsx — the speaker label a person assigns to a lane (design §7.6). Commits on
// Enter or blur, never per keystroke; chips for names used before on the remote lane.
import { useEffect, useState } from "react";
import type { AudioController } from "../controller.js";
import { SPEAKER_COPY } from "../speakers.js";
import type { CaptureLaneId, SpeakerLabels } from "../types.js";

export function SpeakerPicker({ controller, lane, speakers }: { controller: AudioController; lane: CaptureLaneId; speakers: SpeakerLabels }) {
  const current = speakers[lane];
  const [draft, setDraft] = useState(current ?? "");
  useEffect(() => {
    setDraft(current ?? "");
  }, [current]);
  const commit = () => {
    const v = draft.trim();
    if ((v || null) !== current) controller.setSpeaker(lane, v || null);
  };
  const id = `speaker-${lane}`;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        <label htmlFor={id} className="text-xs">
          Speaker label ({lane === "remote" ? "Call" : "Me"})
        </label>
        <input
          id={id}
          data-testid={id}
          className="rounded border px-1 py-0.5 text-xs"
          value={draft}
          placeholder="no speaker label"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            }
          }}
        />
        {current ? (
          <button type="button" data-testid={`${id}-clear`} className="text-xs underline" onClick={() => controller.setSpeaker(lane, null)}>
            clear
          </button>
        ) : null}
        {lane === "remote"
          ? speakers.remoteKnown
              .filter((n) => n !== current)
              .map((n) => (
                <button key={n} type="button" data-testid={`speaker-remote-chip-${n}`} className="rounded-full bg-slate-100 px-2 text-xs text-slate-900" onClick={() => controller.setSpeaker("remote", n)}>
                  {n}
                </button>
              ))
          : null}
      </div>
      {lane === "remote" ? <p className="max-w-prose text-xs opacity-70">{SPEAKER_COPY}</p> : null}
    </div>
  );
}
